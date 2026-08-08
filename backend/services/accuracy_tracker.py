# backend/services/accuracy_tracker.py
"""
AIRP -- Verdict Accuracy Tracker: Recording Service (T-088)

Writes the "pending evaluation" row into ``verdict_outcomes`` (T-087
schema) once a LangGraph pipeline run reaches ``status == "completed"``.
This is the write side only -- a later Phase 8 task reads back rows
where ``evaluated_at IS NULL`` and ``verdict_date + evaluation_horizon_days
<= now()``, fetches the real market price, and fills in the outcome
columns (``price_at_evaluation``, ``price_change_pct``,
``directional_correct``, ``evaluated_at``).

What this module does
----------------------
1. ``derive_evaluation_horizon_days`` -- pure function mapping a
   verdict + its ``time_horizon`` label (from
   ``backend.agents.portfolio_manager._determine_time_horizon``) onto
   a concrete number of days to wait before evaluating accuracy.
   Deliberately only two buckets exist (90 vs 365) even though
   ``time_horizon`` itself has four possible free-text values --
   collapsing "quarterly review (3 months)" / "3-6 months (...)" /
   "12 months" all into the 90-day default keeps the accuracy tracker
   simple: it answers "was this verdict directionally right a quarter
   later", not "did the stock hit every intermediate checkpoint the
   memo's prose happened to mention". Only a BUY verdict backed by a
   high margin of safety earns the long 365-day horizon, matching the
   one case ``_determine_time_horizon`` itself treats as a genuine
   multi-year hold ("3-5 years (high margin of safety supports a long
   hold)").
2. ``record_pending_evaluations`` -- reads the final ``InvestmentState``
   a completed pipeline run produced, pulls out the verdict-time fields
   (ticker, verdict, conviction_score, current price from the
   Technical Analyst's output, and the completion timestamp), and
   inserts one ``VerdictOutcome`` row via the given ``AsyncSession``.
   Idempotent: relies on ``uq_verdict_outcomes_analysis_horizon``
   (T-087) to make a second call for the same
   ``(analysis_id, evaluation_horizon_days)`` a harmless no-op rather
   than a duplicate row or an unhandled IntegrityError.

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- established AIRP rule
  (breaks Pydantic v2 union resolution for modules that import this
  one; this module has no Pydantic models itself, but the rule is
  applied uniformly across backend/ production files regardless).
* Plain ASCII section comments (# ---).
* No bare ``type: ignore`` -- cast()/explicit annotations only.
* Never raises: mirrors the project-wide "agent/node functions must
  never raise" rule. A malformed or partially-populated final state
  (missing decision, missing price data, an unrecognised verdict
  string) is logged and skipped -- it must not turn an otherwise
  successful analysis into a failed one, and it must not crash the
  background task that calls it (backend.services.analysis
  .run_analysis_pipeline). The one exception the pipeline caller is
  expected to see is a caller-supplied ``session`` itself being
  unusable (e.g. already closed) -- SQLAlchemy/asyncpg errors on
  ``commit()`` are still caught here and logged, not re-raised, for
  the same reason.
* ``price_at_verdict`` is read from ``state["technical"]["current_price"]``
  (the Technical Analyst's own OHLCV-derived closing price) rather than
  making a fresh live yFinance call -- the price used to score the
  verdict should be the exact price the committee saw when it made the
  call, not a slightly later live quote.
* Reads ``state["decision"]`` (an
  ``backend.agents.output_models.InvestmentDecision.model_dump()``
  dict) rather than importing that Pydantic model directly -- this
  service only needs a handful of plain fields out of it and importing
  the full agents-package output model would pull in the same "heavy,
  optional-at-import-time dependency" backend.services.analysis
  ._invoke_graph_sync's docstring already documents avoiding.

Public API
----------
    from backend.services.accuracy_tracker import (
        DEFAULT_EVALUATION_HORIZON_DAYS,
        HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS,
        derive_evaluation_horizon_days,
        record_pending_evaluations,
    )
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.graph.state import InvestmentState
from backend.models.orm import VerdictOutcome

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_EVALUATION_HORIZON_DAYS",
    "HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS",
    "derive_evaluation_horizon_days",
    "record_pending_evaluations",
]

# ---------------------------------------------------------------------------
# Horizon mapping (T-088 acceptance criteria)
# ---------------------------------------------------------------------------

#: Days to wait before evaluating accuracy for every verdict EXCEPT the
#: high-conviction, high-margin-of-safety BUY case below.
DEFAULT_EVALUATION_HORIZON_DAYS = 90

#: Days to wait for a BUY verdict whose time_horizon reflects a high
#: margin of safety -- the one case _determine_time_horizon treats as a
#: genuine multi-year hold ("3-5 years (high margin of safety supports
#: a long hold)").
HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS = 365

#: Verdict strings the Portfolio Manager can produce (T-042/T-043).
_VALID_VERDICTS: frozenset[str] = frozenset({"BUY", "HOLD", "SELL"})

#: Substring _determine_time_horizon embeds in its BUY-only long-hold
#: branch. Matched case-insensitively so this stays robust to any future
#: capitalisation tweak to that literal without needing a second edit
#: here every time.
_HIGH_MARGIN_OF_SAFETY_MARKER = "high margin of safety"


def derive_evaluation_horizon_days(verdict: str, time_horizon: str) -> int:
    """
    Map a verdict + its time_horizon label onto an evaluation horizon.

    Args:
        verdict:      One of "BUY" / "HOLD" / "SELL" (case-sensitive,
                      matching backend.agents.output_models
                      .InvestmentDecision.verdict exactly).
        time_horizon: The free-text holding-period label from
                      InvestmentDecision.time_horizon, e.g. "12 months"
                      or "3-5 years (high margin of safety supports a
                      long hold)".

    Returns:
        HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS (365) when verdict is
        "BUY" and time_horizon mentions a high margin of safety;
        DEFAULT_EVALUATION_HORIZON_DAYS (90) for every other
        verdict/time_horizon combination, including HOLD, SELL, and any
        BUY that is not backed by a high margin of safety.
    """
    if verdict == "BUY" and _HIGH_MARGIN_OF_SAFETY_MARKER in time_horizon.lower():
        return HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS
    return DEFAULT_EVALUATION_HORIZON_DAYS


# ---------------------------------------------------------------------------
# Timestamp parsing helper
# ---------------------------------------------------------------------------


def _parse_verdict_date(raw: Optional[str]) -> datetime:
    """
    Parse ``state["completed_at"]`` (an ISO string + "Z", written by
    backend.graph.nodes as ``datetime.utcnow().isoformat() + "Z"``) into
    a timezone-aware UTC ``datetime``.

    Falls back to the current UTC time when ``raw`` is missing or fails
    to parse -- a verdict_outcomes row with a slightly-off verdict_date
    is far better than no row at all, and this should only ever happen
    for a state dict that predates T-042 (portfolio_manager_node always
    sets completed_at).
    """
    if raw:
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            logger.warning(
                "accuracy_tracker: could not parse completed_at=%r -- "
                "falling back to current UTC time",
                raw,
            )
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# record_pending_evaluations
# ---------------------------------------------------------------------------


async def record_pending_evaluations(
    session: AsyncSession,
    job_id: str,
    state: InvestmentState,
) -> Optional[VerdictOutcome]:
    """
    Insert the pending verdict_outcomes row for a completed analysis.

    Called by backend.services.analysis.run_analysis_pipeline
    immediately after a pipeline run reaches ``status == "completed"``.
    Reads the verdict-time fields out of the final InvestmentState and
    writes one row with the four evaluation-time columns left NULL, to
    be filled in later once ``evaluation_horizon_days`` has elapsed.

    Args:
        session: Active AsyncSession. Callers own its lifecycle (this
                 function commits but does not close the session).
        job_id:  UUID string of the analyses row this outcome tracks --
                 identical to state["job_id"], passed separately so
                 callers do not need to trust state["job_id"] was not
                 corrupted in transit.
        state:   The final InvestmentState after the graph reaches END
                 (backend.services.analysis._invoke_graph_sync's return
                 value).

    Returns:
        The persisted VerdictOutcome on success, or None when the row
        could not be recorded -- either because the state was missing
        required data (logged as a warning) or because the insert
        failed at the database level, including the expected
        already-recorded case (logged as info, not an error).

    Never raises: every failure path is caught, logged, and turned into
    a None return so a bad/duplicate accuracy-tracking row never fails
    the analysis it is trying to score.
    """
    decision: Optional[dict[str, Any]] = state.get("decision")
    if not decision:
        logger.warning(
            "record_pending_evaluations: no decision in state for "
            "job_id=%s -- skipping",
            job_id,
        )
        return None

    verdict = str(decision.get("verdict") or "")
    if verdict not in _VALID_VERDICTS:
        logger.warning(
            "record_pending_evaluations: unrecognised verdict=%r for "
            "job_id=%s -- skipping",
            verdict,
            job_id,
        )
        return None

    conviction_score_raw = decision.get("conviction_score")
    if conviction_score_raw is None:
        logger.warning(
            "record_pending_evaluations: decision has no conviction_score "
            "for job_id=%s -- skipping",
            job_id,
        )
        return None

    ticker = str(state.get("ticker") or "").strip()
    if not ticker:
        logger.warning(
            "record_pending_evaluations: no ticker in state for job_id=%s "
            "-- skipping",
            job_id,
        )
        return None

    technical: dict[str, Any] = state.get("technical") or {}
    price_at_verdict_raw = technical.get("current_price")
    if price_at_verdict_raw is None:
        logger.warning(
            "record_pending_evaluations: no technical.current_price "
            "available for job_id=%s ticker=%s -- skipping",
            job_id,
            ticker,
        )
        return None

    try:
        conviction_score = int(conviction_score_raw)
        price_at_verdict = float(price_at_verdict_raw)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "record_pending_evaluations: could not coerce conviction_score/"
            "price for job_id=%s: %s -- skipping",
            job_id,
            exc,
        )
        return None

    time_horizon = str(decision.get("time_horizon") or "")
    horizon_days = derive_evaluation_horizon_days(verdict, time_horizon)
    verdict_date = _parse_verdict_date(state.get("completed_at"))

    try:
        analysis_uuid = uuid.UUID(job_id)
    except ValueError:
        logger.warning(
            "record_pending_evaluations: job_id=%r is not a valid UUID " "-- skipping",
            job_id,
        )
        return None

    outcome = VerdictOutcome(
        analysis_id=analysis_uuid,
        ticker=ticker,
        verdict=verdict,
        conviction_score=conviction_score,
        price_at_verdict=price_at_verdict,
        verdict_date=verdict_date,
        evaluation_horizon_days=horizon_days,
    )

    try:
        session.add(outcome)
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.info(
            "record_pending_evaluations: insert failed for job_id=%s "
            "horizon=%sd (likely already recorded): %s",
            job_id,
            horizon_days,
            exc,
        )
        return None

    await session.refresh(outcome)
    logger.info(
        "record_pending_evaluations: recorded pending evaluation "
        "job_id=%s ticker=%s verdict=%s conviction=%s horizon=%sd "
        "price_at_verdict=%s",
        job_id,
        ticker,
        verdict,
        conviction_score,
        horizon_days,
        price_at_verdict,
    )
    return outcome
