# backend/services/state_persistence.py
"""
AIRP -- State Persistence Service (T-033)

Saves InvestmentState to PostgreSQL after each LangGraph node completes,
enabling pipeline resumption from the last saved checkpoint on failure.

Design
------
* Every LangGraph node calls ``persist_state(job_id, node_name, state)``
  after it finishes.  The call is fire-and-forget inside graph nodes
  (wrapped with asyncio.create_task or run via asyncio.run in sync
  context) so it never blocks the LangGraph execution loop.

* Persistence target: ``analyses.state_snapshot`` (JSONB) and
  ``analyses.last_completed_node`` (VARCHAR).  These two columns are
  added by the T-033 Alembic migration.

* Resumption: ``load_state(job_id)`` returns the last persisted
  InvestmentState dict, or None when no snapshot exists.  The graph
  runner checks this before starting and resumes from the saved
  ``current_node`` instead of restarting from the planner.

* All database operations are fully async (SQLAlchemy 2.x asyncpg).

* In ENVIRONMENT=test the session is always mocked -- this module never
  opens a real DB connection in unit tests.

* No bare ``type: ignore`` anywhere.  All mypy --strict paths use
  cast(), explicit annotations, or assert.

* Plain ASCII section comments (# ---).  No Unicode box-drawing chars.

* NO ``from __future__ import annotations`` -- established AIRP rule
  that prevents Pydantic v2 union resolution breakage.

Public API
----------
    from backend.services.state_persistence import (
        StatePersistenceService,
        persist_state,
        load_state,
    )
"""

import json
import logging
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.graph.state import InvestmentState, state_to_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL -- raw text queries (no ORM join needed; we update a single row)
# ---------------------------------------------------------------------------

# Update state_snapshot and last_completed_node on the analyses row.
# Uses text() with named bind params for asyncpg compatibility.
_SQL_UPSERT_SNAPSHOT = text(
    """
    UPDATE analyses
       SET state_snapshot        = CAST(:snapshot AS jsonb),
           last_completed_node   = :node_name,
           status                = :status
     WHERE id = CAST(:job_id AS uuid)
    """
)

# Load the most recent snapshot for a given job.
_SQL_LOAD_SNAPSHOT = text(
    """
    SELECT state_snapshot, last_completed_node, status
      FROM analyses
     WHERE id = CAST(:job_id AS uuid)
     LIMIT 1
    """
)

# ---------------------------------------------------------------------------
# StatePersistenceService
# ---------------------------------------------------------------------------


class StatePersistenceService:
    """
    Saves and loads InvestmentState snapshots from PostgreSQL (T-033).

    Intended to be instantiated once per graph run and injected into
    the node wrapper that calls ``after_node()``.

    Usage inside a LangGraph node wrapper::

        svc = StatePersistenceService(session)
        await svc.save(job_id="abc-123", node_name="planner", state=state)
        saved_state = await svc.load(job_id="abc-123")
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        job_id: str,
        node_name: str,
        state: InvestmentState,
    ) -> bool:
        """
        Persist the current InvestmentState snapshot to PostgreSQL.

        Serialises the full state dict to JSON and writes it to
        ``analyses.state_snapshot`` along with ``last_completed_node``
        and the current ``status`` field from state.

        Args:
            job_id:    The UUID string from state["job_id"].
            node_name: The LangGraph node name that just completed.
            state:     The current InvestmentState after the node ran.

        Returns:
            True when the UPDATE affected exactly one row (success).
            False when no row was found for job_id (logs a warning).

        Raises:
            Exception: Re-raises any SQLAlchemy / asyncpg error after
                       logging it so the caller decides whether to swallow
                       or propagate.
        """
        snapshot_json: str = state_to_json(state)
        pipeline_status: str = str(state.get("status", "running"))

        try:
            result = await self._session.execute(
                _SQL_UPSERT_SNAPSHOT,
                {
                    "snapshot": snapshot_json,
                    "node_name": node_name,
                    "job_id": job_id,
                    "status": pipeline_status,
                },
            )
            await self._session.commit()

            rows_affected: int = result.rowcount  # type: ignore[union-attr]
            if rows_affected == 0:
                logger.warning(
                    "state_persistence.save: no analyses row for job_id=%s "
                    "-- snapshot NOT written (node=%s)",
                    job_id,
                    node_name,
                )
                return False

            logger.debug(
                "state_persistence.save: persisted state after node=%s "
                "for job_id=%s (status=%s)",
                node_name,
                job_id,
                pipeline_status,
            )
            return True

        except Exception as exc:
            logger.error(
                "state_persistence.save: DB error for job_id=%s node=%s: %s",
                job_id,
                node_name,
                exc,
            )
            await self._session.rollback()
            raise

    async def load(self, job_id: str) -> Optional[InvestmentState]:
        """
        Load the last persisted InvestmentState snapshot from PostgreSQL.

        Used by the graph runner before starting a new pipeline run to
        detect whether a previous run left a resumable checkpoint.

        Args:
            job_id: The UUID string of the analysis job.

        Returns:
            The deserialized InvestmentState dict when a snapshot exists,
            or None when no snapshot has been saved for this job_id.

        Raises:
            Exception: Re-raises any SQLAlchemy / asyncpg error after
                       logging it.
        """
        try:
            result = await self._session.execute(
                _SQL_LOAD_SNAPSHOT,
                {"job_id": job_id},
            )
            row = result.fetchone()
        except Exception as exc:
            logger.error(
                "state_persistence.load: DB error for job_id=%s: %s",
                job_id,
                exc,
            )
            raise

        if row is None:
            logger.debug(
                "state_persistence.load: no analyses row for job_id=%s",
                job_id,
            )
            return None

        snapshot_val: Any = row[0]
        if snapshot_val is None:
            logger.debug(
                "state_persistence.load: analyses row exists but "
                "state_snapshot is NULL for job_id=%s",
                job_id,
            )
            return None

        # asyncpg returns JSONB as a dict already; psycopg2 returns str.
        # Normalise to str then parse so both drivers work identically.
        if isinstance(snapshot_val, dict):
            snapshot_str: str = json.dumps(snapshot_val, default=str)
        else:
            snapshot_str = str(snapshot_val)

        try:
            raw: Any = json.loads(snapshot_str)
            assert isinstance(raw, dict), "snapshot must be a JSON object"
            from typing import cast as typing_cast

            state: InvestmentState = typing_cast(InvestmentState, raw)
        except (json.JSONDecodeError, AssertionError) as exc:
            logger.error(
                "state_persistence.load: invalid snapshot JSON for " "job_id=%s: %s",
                job_id,
                exc,
            )
            return None

        last_node: str = str(row[1]) if row[1] is not None else ""
        logger.info(
            "state_persistence.load: resuming job_id=%s from "
            "last_completed_node=%r (status=%s)",
            job_id,
            last_node,
            row[2],
        )
        return state

    async def mark_failed(
        self,
        job_id: str,
        error_message: str,
        node_name: str,
    ) -> None:
        """
        Mark an analysis as failed in PostgreSQL.

        Called by the graph runner when an unhandled exception escapes
        a node.  Sets status='failed' and error_message so the dashboard
        can surface the failure without polling.

        Args:
            job_id:        The UUID string of the analysis job.
            error_message: Human-readable error description.
            node_name:     The node that was running when the failure occurred.
        """
        _sql_fail = text(
            """
            UPDATE analyses
               SET status        = 'failed',
                   error_message = :error_message,
                   completed_at  = NOW()
             WHERE id = CAST(:job_id AS uuid)
            """
        )
        try:
            await self._session.execute(
                _sql_fail,
                {"error_message": error_message, "job_id": job_id},
            )
            await self._session.commit()
            logger.info(
                "state_persistence.mark_failed: job_id=%s marked failed " "at node=%s",
                job_id,
                node_name,
            )
        except Exception as exc:
            logger.error(
                "state_persistence.mark_failed: DB error for job_id=%s: %s",
                job_id,
                exc,
            )
            await self._session.rollback()
            raise


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------
# These thin wrappers are imported by graph nodes.  They build a session
# from the module-level session factory, delegate to the service, and
# close the session.  In ENVIRONMENT=test they are patched at the
# module level via unittest.mock.patch so no real DB is ever touched.


async def persist_state(
    job_id: str,
    node_name: str,
    state: InvestmentState,
) -> bool:
    """
    Persist InvestmentState after a node completes (module-level helper).

    Creates a fresh AsyncSession, delegates to StatePersistenceService,
    then closes the session.  Safe to call from any async context.

    In ENVIRONMENT=test this function is patched to return True without
    touching the database.

    Args:
        job_id:    The UUID string from state["job_id"].
        node_name: The LangGraph node name that just completed.
        state:     The current InvestmentState.

    Returns:
        True on success, False when no analyses row exists for job_id.
    """
    from backend.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        svc = StatePersistenceService(session)
        return await svc.save(job_id=job_id, node_name=node_name, state=state)


async def load_state(job_id: str) -> Optional[InvestmentState]:
    """
    Load the last persisted InvestmentState (module-level helper).

    Creates a fresh AsyncSession, delegates to StatePersistenceService,
    then closes the session.

    In ENVIRONMENT=test this function is patched to return None.

    Args:
        job_id: The UUID string of the analysis job.

    Returns:
        InvestmentState dict or None.
    """
    from backend.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        svc = StatePersistenceService(session)
        return await svc.load(job_id=job_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "StatePersistenceService",
    "persist_state",
    "load_state",
]
