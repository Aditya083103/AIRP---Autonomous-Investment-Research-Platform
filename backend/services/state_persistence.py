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

* Dedicated per-call engine for the module-level helpers (see "Why a
  dedicated engine per call" below) -- ``persist_state``/``load_state``
  do NOT use ``backend.db.session``'s shared, process-wide
  ``AsyncSessionLocal``. They build and dispose a throwaway
  single-connection engine scoped to exactly the ``asyncio`` event loop
  that is running when they are called.

* In ENVIRONMENT=test the session is always mocked -- this module never
  opens a real DB connection in unit tests.

* No bare ``type: ignore`` anywhere.  All mypy --strict paths use
  cast(), explicit annotations, or assert.

* Plain ASCII section comments (# ---).  No Unicode box-drawing chars.

* NO ``from __future__ import annotations`` -- established AIRP rule
  that prevents Pydantic v2 union resolution breakage.

Why a dedicated engine per call (NOT backend.db.session.AsyncSessionLocal)
----------------------------------------------------------------------------
``persist_state``/``load_state`` are called from
``backend.graph.nodes._run_persist``, which itself runs inside a
LangGraph node executing on a worker thread (LangGraph dispatches nodes
via a ThreadPoolExecutor) via ``asyncio.run(...)``. Every single
``asyncio.run()`` call creates a BRAND NEW event loop, runs the
coroutine to completion, then closes that loop.

``backend.db.session``'s ``engine``/``AsyncSessionLocal`` is a
module-level singleton shared by the entire process -- including the
main FastAPI/uvicorn event loop that handles ordinary HTTP requests
(GET /status, GET /result, etc.). asyncpg's underlying connection
objects are NOT safe to use from more than one event loop: each
connection's internal protocol object binds to the loop that created
or last used it. The moment a pooled connection that was bound to one
loop gets checked out and used inside a *different* loop -- which is
exactly what happens every time ``_run_persist``'s fresh
``asyncio.run()`` loop reuses a connection from the shared pool --
asyncpg raises::

    RuntimeError: Task <Task ...> got Future <Future pending> attached
    to a different loop

This is not a flaky/occasional failure: it happens on effectively every
node completion once the shared pool has been touched by more than one
loop, and it can also poison the pool badly enough (partially-cancelled
connections, "Event loop is closed" warnings) that ordinary HTTP
requests on the MAIN loop start failing too, even though they never
touched ``asyncio.run()`` themselves.

The fix: ``persist_state``/``load_state`` build their OWN engine,
backed by ``NullPool`` (a single connection, opened fresh and closed
immediately -- never pooled, never reused across calls or loops),
scoped entirely to the one ``await`` chain running inside the current
``asyncio.run()`` call's loop. The engine is disposed in a ``finally``
block before the function returns, so no connection or engine-level
background task ever outlives the loop that created it. This trades a
small amount of per-call connection-setup latency (a fresh TCP+SSL
handshake to Neon per node, instead of reusing a pooled connection) for
correctness -- an acceptable trade for a ~9-node pipeline with no
realistic concurrent-analysis load, and the only sound option given
LangGraph's worker-thread execution model without restructuring how
nodes schedule their async work (e.g. ``run_coroutine_threadsafe``
back onto the main loop, a larger change reserved for a future task if
this code path ever needs to avoid the per-call connection cost).

Ordinary FastAPI route handlers (GET /status, GET /result, GET /history,
etc.) are UNAFFECTED by this change -- they continue to use
``backend.db.session.get_async_session``/``AsyncSessionLocal`` exactly
as before, since they always run on the single main event loop and
never hit the cross-loop problem this module works around.

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

    This class itself is loop-agnostic -- it only ever uses whichever
    ``AsyncSession`` it is constructed with. It is the module-level
    ``persist_state``/``load_state`` helpers below (not this class)
    that are responsible for choosing a session bound to the correct
    event loop -- see this module's "Why a dedicated engine per call"
    docstring section for why that distinction matters.
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

            rows_affected: int = result.rowcount  # type: ignore[attr-defined]
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
# Dedicated per-call engine builder
# ---------------------------------------------------------------------------
# See this module's docstring ("Why a dedicated engine per call") for the
# full rationale. Every helper below builds, uses, and disposes ONE
# throwaway engine scoped entirely to the current async call -- never the
# shared backend.db.session.engine/AsyncSessionLocal singleton.


async def _open_dedicated_session() -> tuple[Any, AsyncSession]:
    """
    Build a single-connection engine + session bound to the CURRENT
    running event loop, ready for exactly one unit of work.

    Reuses ``backend.db.session``'s own URL-resolution and SSL-handling
    helpers (``_build_database_url``, ``_prepare_url``) so this module
    never re-implements the Neon ``sslmode=require`` -> ``connect_args``
    translation differently from the rest of the app -- only the
    pooling strategy differs here, not the connection target or SSL
    handling.

    ``poolclass=NullPool`` is the load-bearing choice: NullPool opens a
    brand-new physical connection on every checkout and closes it
    immediately on return, so there is never a previously-used,
    possibly-different-loop-bound connection sitting around for this
    engine to hand out. Each call to this function -- and therefore
    each call to ``persist_state``/``load_state``/``mark_pipeline_failed``
    -- gets a connection that is opened and closed entirely within the
    one event loop currently running, with nothing left over to leak
    into a future ``asyncio.run()`` call's different loop.

    Returns:
        (engine, session) -- the caller MUST dispose ``engine`` (via
        ``await engine.dispose()``) in a ``finally`` block after closing
        ``session``, or the underlying connection will not be released
        promptly.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from backend.db.session import _build_database_url, _prepare_url

    raw_url = _build_database_url()
    url, connect_args = _prepare_url(raw_url)

    engine = create_async_engine(
        url,
        echo=False,
        poolclass=NullPool,
        connect_args=connect_args,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    session: AsyncSession = session_factory()
    return engine, session


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------
# These thin wrappers are imported by graph nodes.  Each one builds its
# OWN dedicated engine+session (see _open_dedicated_session above),
# delegates to the service, then closes the session and disposes the
# engine.  In ENVIRONMENT=test they are patched at the module level via
# unittest.mock.patch so no real DB is ever touched.


async def persist_state(
    job_id: str,
    node_name: str,
    state: InvestmentState,
) -> bool:
    """
    Persist InvestmentState after a node completes (module-level helper).

    Builds a dedicated, single-connection engine+session bound to
    whichever event loop is running when this coroutine executes (see
    this module's "Why a dedicated engine per call" docstring section),
    delegates to StatePersistenceService, then closes the session and
    disposes the engine before returning.

    This is deliberately NOT ``backend.db.session.AsyncSessionLocal`` --
    this function is called from ``backend.graph.nodes._run_persist``
    via a fresh ``asyncio.run()`` on every invocation (LangGraph nodes
    execute on worker threads), and the shared session factory's pooled
    asyncpg connections are not safe to reuse across the different event
    loop each such call creates.

    In ENVIRONMENT=test this function is patched to return True without
    touching the database.

    Args:
        job_id:    The UUID string from state["job_id"].
        node_name: The LangGraph node name that just completed.
        state:     The current InvestmentState.

    Returns:
        True on success, False when no analyses row exists for job_id.
    """
    engine, session = await _open_dedicated_session()
    try:
        svc = StatePersistenceService(session)
        return await svc.save(job_id=job_id, node_name=node_name, state=state)
    finally:
        await session.close()
        await engine.dispose()


async def load_state(job_id: str) -> Optional[InvestmentState]:
    """
    Load the last persisted InvestmentState (module-level helper).

    Builds a dedicated, single-connection engine+session bound to
    whichever event loop is running when this coroutine executes --
    see ``persist_state``'s docstring and this module's "Why a
    dedicated engine per call" section for the full rationale.

    In ENVIRONMENT=test this function is patched to return None.

    Args:
        job_id: The UUID string of the analysis job.

    Returns:
        InvestmentState dict or None.
    """
    engine, session = await _open_dedicated_session()
    try:
        svc = StatePersistenceService(session)
        return await svc.load(job_id=job_id)
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "StatePersistenceService",
    "persist_state",
    "load_state",
]
