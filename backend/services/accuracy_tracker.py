# backend/services/accuracy_tracker.py
"""
AIRP -- Verdict Accuracy Tracker: Recording + Evaluation Service
(T-088 / T-089)

Writes the "pending evaluation" row into ``verdict_outcomes`` (T-087
schema) once a LangGraph pipeline run reaches ``status == "completed"``
(T-088), and later scores it once its evaluation horizon has elapsed
(T-089) by fetching the real market price and applying a dead-zone
directional scoring rule.

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
3. ``score_directional_correctness`` -- pure function implementing the
   +-5% dead-zone rule: a verdict is only marked wrong when the price
   moves against it by *more* than the dead zone, and a HOLD is only
   marked wrong when the price moves *out of* the dead zone in either
   direction. See "The dead-zone scoring rule" below for the full
   rationale and boundary semantics.
4. ``run_due_evaluations`` -- the batch job. Loads every
   ``verdict_outcomes`` row with ``evaluated_at IS NULL``, keeps the
   ones whose ``verdict_date + evaluation_horizon_days`` has already
   passed, fetches each one's current price via the existing T-010
   ``fetch_stock_price`` tool, computes ``price_change_pct``, scores
   ``directional_correct``, and commits the four evaluation-time
   columns one row at a time so a mid-batch failure never loses
   already-scored rows.

The dead-zone scoring rule
---------------------------
A +-5% "dead zone" absorbs ordinary price noise so a verdict is not
penalised for a move too small to represent a real directional
outcome. The rule is intentionally asymmetric per verdict type -- each
verdict only fails when the price moves *against* what it predicted by
more than the dead zone; a small move, or a move in the predicted
direction, never counts as a miss:

    BUY:  wrong only if price_change_pct <= -DEAD_ZONE_PCT (fell hard)
          correct otherwise -- including flat, and including any rise
    SELL: wrong only if price_change_pct >=  DEAD_ZONE_PCT (rose hard)
          correct otherwise -- including flat, and including any fall
    HOLD: wrong if the price moved out of the dead zone in EITHER
          direction (price_change_pct >= DEAD_ZONE_PCT or
          <= -DEAD_ZONE_PCT); correct only while it stayed inside it

Boundary semantics: the dead zone is the OPEN interval
``(-DEAD_ZONE_PCT, DEAD_ZONE_PCT)``. A move of exactly +-5.0% counts as
having left the dead zone (a HOLD at exactly +5.0% is wrong; a BUY at
exactly -5.0% is wrong), matching the "moved meaningfully" language a
5% threshold implies -- 5% is meant to be the point at which the move
stops being noise, not one step short of it.

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
  .run_analysis_pipeline). ``run_due_evaluations`` applies the same
  rule per row: one ticker with a temporarily-unreachable price feed,
  or one row that fails to commit, is logged and skipped -- it never
  aborts the rest of the batch.
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
* ``run_due_evaluations`` fetches the CURRENT price with
  ``period="1mo"`` (not the pipeline's original ``"1y"``) -- only
  ``stats.current_price`` is needed, evaluation runs long after the
  original analysis so there is no cache to reuse either way (yFinance
  data is cached for 15 minutes; verdicts are evaluated 90-365 days
  later), and a 1-month candle series is a much smaller fetch/parse for
  a job that may score many rows in one run. Mirrors the existing
  "blocking yFinance call MUST run through asyncio.to_thread" pattern
  already used by backend.services.analysis.get_analysis_chart_data
  for fetch_ohlcv/fetch_income_statement.
* Each due row is scored and committed individually, not batched into
  one transaction -- if ``run_due_evaluations`` is interrupted partway
  through (a bad ticker, a dropped DB connection), every row already
  scored before the interruption stays scored; the next run only needs
  to re-process what is still ``evaluated_at IS NULL`` and due.

Public API
----------
    from backend.services.accuracy_tracker import (
        DEFAULT_EVALUATION_HORIZON_DAYS,
        HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS,
        DEAD_ZONE_PCT,
        derive_evaluation_horizon_days,
        record_pending_evaluations,
        score_directional_correctness,
        EvaluationBatchResult,
        run_due_evaluations,
    )
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.graph.state import InvestmentState
from backend.models.orm import VerdictOutcome
from backend.tools.stock_price import fetch_stock_price

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_EVALUATION_HORIZON_DAYS",
    "HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS",
    "DEAD_ZONE_PCT",
    "derive_evaluation_horizon_days",
    "record_pending_evaluations",
    "score_directional_correctness",
    "EvaluationBatchResult",
    "run_due_evaluations",
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


# ---------------------------------------------------------------------------
# Dead-zone directional scoring rule (T-089)
# ---------------------------------------------------------------------------

#: Percentage-point width of the "no signal" band around 0% price
#: change. See this module's docstring ("The dead-zone scoring rule")
#: for the full rationale and boundary semantics.
DEAD_ZONE_PCT = 5.0


def _moved_up_meaningfully(price_change_pct: float) -> bool:
    """True once a move has left the dead zone on the upside."""
    return price_change_pct >= DEAD_ZONE_PCT


def _moved_down_meaningfully(price_change_pct: float) -> bool:
    """True once a move has left the dead zone on the downside."""
    return price_change_pct <= -DEAD_ZONE_PCT


def score_directional_correctness(verdict: str, price_change_pct: float) -> bool:
    """
    Apply the +-DEAD_ZONE_PCT dead-zone rule for one verdict type.

    Args:
        verdict:          "BUY" / "HOLD" / "SELL" (case-sensitive,
                           matching VerdictOutcome.verdict exactly).
        price_change_pct: Percent change from price_at_verdict to the
                           current evaluation price, e.g. 7.5 for a
                           7.5% rise or -3.2 for a 3.2% fall.

    Returns:
        BUY:  False only when the price fell by DEAD_ZONE_PCT or more;
              True otherwise (flat, or any rise).
        SELL: False only when the price rose by DEAD_ZONE_PCT or more;
              True otherwise (flat, or any fall).
        HOLD: True only while the move stays strictly inside
              (-DEAD_ZONE_PCT, DEAD_ZONE_PCT); False once it leaves the
              dead zone in either direction.
        Any other verdict string is defensively scored with the HOLD
        rule (the strictest of the three) -- this should never happen
        in practice since VerdictOutcome.verdict is DB-enum-constrained
        to BUY/HOLD/SELL, but a scoring function must still return a
        definite bool rather than raising on unexpected input.
    """
    if verdict == "BUY":
        return not _moved_down_meaningfully(price_change_pct)
    if verdict == "SELL":
        return not _moved_up_meaningfully(price_change_pct)
    return not _moved_up_meaningfully(
        price_change_pct
    ) and not _moved_down_meaningfully(price_change_pct)


def _compute_price_change_pct(price_at_verdict: float, current_price: float) -> float:
    """
    Percent change from price_at_verdict to current_price, rounded to
    4 decimal places to match VerdictOutcome.price_change_pct's
    Numeric(8, 4) column precision.

    Returns 0.0 (rather than dividing by zero) in the pathological case
    of price_at_verdict == 0 -- this should never occur for a real
    equity price but must not crash the evaluation batch if it somehow
    does.
    """
    if price_at_verdict == 0:
        logger.warning(
            "accuracy_tracker: price_at_verdict is 0 -- returning 0.0%% "
            "price_change_pct instead of dividing by zero"
        )
        return 0.0
    return round((current_price - price_at_verdict) / price_at_verdict * 100.0, 4)


# ---------------------------------------------------------------------------
# Live price fetch for evaluation (blocking -- run via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _fetch_current_price_sync(ticker: str) -> tuple[Optional[float], Optional[str]]:
    """
    Blocking call into the existing T-010 ``fetch_stock_price`` tool.

    Callers MUST run this through ``asyncio.to_thread``, never directly
    on the event loop -- mirrors backend.services.analysis
    ._fetch_price_history_sync's documented contract for the sibling
    fetch_ohlcv tool.

    Uses period="1mo" -- only ``stats.current_price`` is needed here;
    see this module's docstring for why a full "1y" fetch (the
    pipeline's original period) would be unnecessary weight for this
    call site.

    Returns:
        (current_price, None) on success, or (None, error_message) when
        the tool itself reported an error or the response was missing
        stats.current_price.
    """
    result = fetch_stock_price.invoke({"ticker": ticker, "period": "1mo"})
    if "error" in result:
        return None, str(result.get("message", result["error"]))

    stats: dict[str, Any] = result.get("stats") or {}
    current_price = stats.get("current_price")
    if current_price is None:
        return None, "fetch_stock_price response missing stats.current_price"

    try:
        return float(current_price), None
    except (TypeError, ValueError) as exc:
        return None, f"could not coerce current_price={current_price!r}: {exc}"


# ---------------------------------------------------------------------------
# run_due_evaluations -- the batch job
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationBatchResult:
    """Summary counts returned by one run_due_evaluations() call."""

    #: Rows whose evaluation_horizon_days had already elapsed this run.
    due_count: int
    #: Of those, how many were successfully scored and committed.
    evaluated_count: int
    #: Of those, how many were left unevaluated (price fetch failed, or
    #: the commit itself failed) -- always due_count - evaluated_count.
    skipped_count: int


def _is_due(row: VerdictOutcome, reference_time: datetime) -> bool:
    """
    True when ``row.verdict_date + row.evaluation_horizon_days`` days
    has already passed as of ``reference_time``.

    Normalises a naive ``verdict_date`` to UTC before comparing --
    PostgreSQL TIMESTAMPTZ columns always round-trip as timezone-aware
    datetimes through asyncpg, but a row built directly in Python (unit
    tests, or a future caller) may not have set tzinfo explicitly.
    """
    verdict_date = row.verdict_date
    if verdict_date.tzinfo is None:
        verdict_date = verdict_date.replace(tzinfo=timezone.utc)
    due_at = verdict_date + timedelta(days=row.evaluation_horizon_days)
    return due_at <= reference_time


async def run_due_evaluations(
    session: AsyncSession,
    now: Optional[datetime] = None,
) -> EvaluationBatchResult:
    """
    Score every verdict_outcomes row whose evaluation horizon has
    elapsed.

    For each due row: fetches the current price via fetch_stock_price,
    computes price_change_pct against price_at_verdict, applies
    score_directional_correctness for that row's verdict, and commits
    price_at_evaluation / price_change_pct / directional_correct /
    evaluated_at onto the row.

    Each row is scored and committed independently -- a failure on one
    row (an unreachable ticker, a DB error on that row's commit) is
    logged and counted in skipped_count; it does not stop the rest of
    the batch and never raises out of this function.

    Args:
        session: Active AsyncSession. Callers own its lifecycle.
        now:     Reference time to evaluate "due" against. Defaults to
                 the current UTC time; a caller can pass an explicit
                 value for testing or for a batch run that should be
                 evaluated as of a specific moment.

    Returns:
        EvaluationBatchResult with due_count, evaluated_count, and
        skipped_count. due_count == 0 (no rows past their horizon yet)
        is a normal, successful outcome, not an error.
    """
    reference_time = now or datetime.now(timezone.utc)

    try:
        result = await session.execute(
            select(VerdictOutcome).where(VerdictOutcome.evaluated_at.is_(None))
        )
        pending_rows = list(result.scalars().all())
    except SQLAlchemyError as exc:
        logger.error("run_due_evaluations: failed to load pending rows: %s", exc)
        return EvaluationBatchResult(due_count=0, evaluated_count=0, skipped_count=0)

    due_rows = [row for row in pending_rows if _is_due(row, reference_time)]
    due_count = len(due_rows)
    evaluated_count = 0

    for row in due_rows:
        try:
            current_price, error = await asyncio.to_thread(
                _fetch_current_price_sync, row.ticker
            )
            if current_price is None:
                logger.warning(
                    "run_due_evaluations: could not fetch current price for "
                    "verdict_outcomes id=%s ticker=%s: %s -- leaving "
                    "unevaluated",
                    row.id,
                    row.ticker,
                    error,
                )
                continue

            price_change_pct = _compute_price_change_pct(
                row.price_at_verdict, current_price
            )
            directional_correct = score_directional_correctness(
                row.verdict, price_change_pct
            )

            row.price_at_evaluation = current_price
            row.price_change_pct = price_change_pct
            row.directional_correct = directional_correct
            row.evaluated_at = reference_time

            await session.commit()
            await session.refresh(row)
            evaluated_count += 1
            logger.info(
                "run_due_evaluations: scored verdict_outcomes id=%s "
                "ticker=%s verdict=%s price_change_pct=%s "
                "directional_correct=%s",
                row.id,
                row.ticker,
                row.verdict,
                price_change_pct,
                directional_correct,
            )
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.error(
                "run_due_evaluations: DB error scoring verdict_outcomes " "id=%s: %s",
                row.id,
                exc,
            )
        except Exception as exc:
            # Catch-all so one bad row (unexpected tool/library error)
            # never aborts the rest of the batch -- see this module's
            # "never raises" design decision.
            logger.error(
                "run_due_evaluations: unexpected error scoring "
                "verdict_outcomes id=%s: %s",
                row.id,
                exc,
            )

    skipped_count = due_count - evaluated_count
    logger.info(
        "run_due_evaluations: due=%d evaluated=%d skipped=%d",
        due_count,
        evaluated_count,
        skipped_count,
    )
    return EvaluationBatchResult(
        due_count=due_count,
        evaluated_count=evaluated_count,
        skipped_count=skipped_count,
    )
