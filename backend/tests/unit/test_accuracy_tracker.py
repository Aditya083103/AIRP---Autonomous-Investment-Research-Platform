# backend/tests/unit/test_accuracy_tracker.py
"""
Unit tests for T-088 / T-089: backend/services/accuracy_tracker.py

Test strategy
-------------
1. derive_evaluation_horizon_days()
     BUY + high margin of safety phrase   -- 365 days
     BUY + high margin, different case    -- 365 days (case-insensitive)
     BUY without the high-margin phrase   -- 90 days (default)
     HOLD                                 -- 90 days (default)
     SELL                                 -- 90 days (default)
     empty time_horizon string            -- 90 days (default), no raise
2. record_pending_evaluations()
     happy path -- decision + technical.current_price + completed_at all
                   present -> a VerdictOutcome is added, session.commit()
                   is awaited, the row's fields match the input state
     BUY + high margin of safety -- evaluation_horizon_days == 365 on the
                   inserted row
     missing decision           -- returns None, session.add() never called
     unrecognised verdict       -- returns None, session.add() never called
     missing conviction_score   -- returns None, session.add() never called
     missing ticker             -- returns None, session.add() never called
     missing technical.current_price -- returns None, session.add() never
                   called
     non-numeric conviction_score/current_price -- returns None (coercion
                   failure), session.add() never called
     invalid job_id (not a UUID) -- returns None, session.add() never
                   called
     unparsable completed_at    -- falls back to "now" rather than raising
     missing completed_at entirely -- falls back to "now" rather than
                   raising
     DB error on commit (e.g. the expected duplicate-insert case via the
                   T-087 unique constraint) -- rollback is awaited, returns
                   None, does not raise
3. score_directional_correctness() (T-089) -- the +-5% dead-zone rule
     BUY:  a fall of exactly -5%   -- wrong
           a fall just short of -5%, e.g. -4.99% -- correct
           flat (0%)               -- correct
           a large rise            -- correct
     SELL: a rise of exactly +5%   -- wrong
           a rise just short of +5%, e.g. +4.99% -- correct
           flat (0%)               -- correct
           a large fall            -- correct
     HOLD: a rise of exactly +5%   -- wrong
           a fall of exactly -5%   -- wrong
           just inside the dead zone on either side -- correct
           flat (0%)               -- correct
     unrecognised verdict string   -- scored with the (strictest) HOLD
                   rule rather than raising
4. _compute_price_change_pct()
     rise, fall, flat -- correct percentage, rounded to 4 dp
     price_at_verdict == 0 -- returns 0.0 rather than raising
5. run_due_evaluations()
     no pending rows            -- due=0, evaluated=0, skipped=0
     pending row not yet due    -- excluded from due_count entirely
     pending row exactly at its horizon (verdict_date + horizon == now)
                                 -- counted as due (boundary is inclusive)
     one due row, happy path    -- price fetched, row's four evaluation
                   columns set, committed, refreshed, evaluated_count == 1
     several due rows           -- each is scored independently
     fetch_stock_price returns an error dict -- row left unevaluated,
                   counted in skipped_count, no commit for that row
     commit() raises for one row -- rollback is awaited for that row,
                   it is skipped, and remaining due rows are still
                   processed (one bad row never aborts the batch)
     a row's evaluation raises an unexpected exception -- caught,
                   logged, skipped -- run_due_evaluations itself never
                   raises
     load-pending-rows query itself raises -- returns an all-zero
                   EvaluationBatchResult rather than raising

All database interactions use a mocked AsyncSession (AsyncMock) --  no
real PostgreSQL connection, matching the existing
test_state_persistence.py / test_analysis_service.py pattern. All
fetch_stock_price calls are mocked -- no real yFinance/network access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.graph.state import InvestmentState, make_initial_state
from backend.models.orm import VerdictOutcome
from backend.services.accuracy_tracker import (
    DEAD_ZONE_PCT,
    DEFAULT_EVALUATION_HORIZON_DAYS,
    HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS,
    EvaluationBatchResult,
    _compute_price_change_pct,
    derive_evaluation_horizon_days,
    record_pending_evaluations,
    run_due_evaluations,
    score_directional_correctness,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_JOB_ID = str(uuid.uuid4())
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"


def _make_completed_state(**overrides: Any) -> InvestmentState:
    """
    Build a minimal, fully-populated "completed" InvestmentState -- just
    enough for record_pending_evaluations to succeed on the happy path.
    """
    state = make_initial_state(
        job_id=_JOB_ID,
        company_name=_COMPANY,
        ticker=_TICKER,
        exchange="NSE",
        raw_query="TCS",
    )
    state["status"] = "completed"
    state["completed_at"] = "2026-08-01T12:00:00Z"
    state["technical"] = {"current_price": 3550.25}
    state["decision"] = {
        "verdict": "BUY",
        "conviction_score": 8,
        "time_horizon": "12 months",
    }
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


def _make_mock_session() -> AsyncMock:
    """Return a mocked AsyncSession with add/commit/rollback/refresh."""
    session = AsyncMock()
    # session.add() is synchronous even on AsyncSession -- MagicMock,
    # not AsyncMock, matching the established pattern in
    # test_analysis_service.py's get_or_create_company/create_analysis_job
    # tests (an AsyncMock here would leave an unawaited coroutine behind
    # every time production code calls session.add(outcome) without
    # awaiting it, which is the correct, non-buggy call style).
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# derive_evaluation_horizon_days()
# ---------------------------------------------------------------------------


class TestDeriveEvaluationHorizonDays:
    def test_buy_with_high_margin_of_safety_is_365_days(self) -> None:
        days = derive_evaluation_horizon_days(
            "BUY", "3-5 years (high margin of safety supports a long hold)"
        )
        assert days == HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS
        assert days == 365

    def test_matching_is_case_insensitive(self) -> None:
        days = derive_evaluation_horizon_days(
            "BUY", "3-5 YEARS (HIGH MARGIN OF SAFETY SUPPORTS A LONG HOLD)"
        )
        assert days == 365

    def test_buy_without_high_margin_phrase_is_default(self) -> None:
        days = derive_evaluation_horizon_days("BUY", "12 months")
        assert days == DEFAULT_EVALUATION_HORIZON_DAYS
        assert days == 90

    def test_buy_technically_driven_horizon_is_default(self) -> None:
        days = derive_evaluation_horizon_days(
            "BUY", "3-6 months (technically driven, reassess on momentum shift)"
        )
        assert days == 90

    def test_hold_is_default(self) -> None:
        days = derive_evaluation_horizon_days("HOLD", "quarterly review (3 months)")
        assert days == 90

    def test_sell_is_default(self) -> None:
        days = derive_evaluation_horizon_days("SELL", "12 months")
        assert days == 90

    def test_sell_with_high_margin_phrase_is_still_default(self) -> None:
        # The 365-day horizon is BUY-only by spec -- a SELL verdict must
        # never get the long horizon even if the phrase were somehow
        # present on it.
        days = derive_evaluation_horizon_days(
            "SELL", "high margin of safety mentioned incorrectly"
        )
        assert days == 90

    def test_empty_time_horizon_does_not_raise(self) -> None:
        days = derive_evaluation_horizon_days("BUY", "")
        assert days == 90


# ---------------------------------------------------------------------------
# record_pending_evaluations() -- happy path
# ---------------------------------------------------------------------------


class TestRecordPendingEvaluationsHappyPath:
    @pytest.mark.asyncio
    async def test_adds_a_verdict_outcome(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state()

        result = await record_pending_evaluations(session, _JOB_ID, state)

        session.add.assert_called_once()
        added = session.add.call_args.args[0]
        assert isinstance(added, VerdictOutcome)
        assert result is added

    @pytest.mark.asyncio
    async def test_commits_and_refreshes(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state()

        await record_pending_evaluations(session, _JOB_ID, state)

        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()
        session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_row_fields_match_state(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state()

        await record_pending_evaluations(session, _JOB_ID, state)

        added = session.add.call_args.args[0]
        assert added.analysis_id == uuid.UUID(_JOB_ID)
        assert added.ticker == _TICKER
        assert added.verdict == "BUY"
        assert added.conviction_score == 8
        assert added.price_at_verdict == 3550.25

    @pytest.mark.asyncio
    async def test_default_horizon_is_90_days(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state()  # time_horizon = "12 months"

        await record_pending_evaluations(session, _JOB_ID, state)

        added = session.add.call_args.args[0]
        assert added.evaluation_horizon_days == 90

    @pytest.mark.asyncio
    async def test_buy_high_margin_of_safety_uses_365_day_horizon(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(
            decision={
                "verdict": "BUY",
                "conviction_score": 9,
                "time_horizon": (
                    "3-5 years (high margin of safety supports a long hold)"
                ),
            }
        )

        await record_pending_evaluations(session, _JOB_ID, state)

        added = session.add.call_args.args[0]
        assert added.evaluation_horizon_days == 365

    @pytest.mark.asyncio
    async def test_verdict_date_parsed_from_completed_at(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(completed_at="2026-08-01T12:00:00Z")

        await record_pending_evaluations(session, _JOB_ID, state)

        added = session.add.call_args.args[0]
        assert added.verdict_date == datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# record_pending_evaluations() -- missing / malformed data
# ---------------------------------------------------------------------------


class TestRecordPendingEvaluationsMissingData:
    @pytest.mark.asyncio
    async def test_missing_decision_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(decision=None)

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_decision_dict_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(decision={})

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_unrecognised_verdict_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(
            decision={"verdict": "MAYBE", "conviction_score": 5}
        )

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_conviction_score_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(decision={"verdict": "BUY"})

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_ticker_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(ticker="")

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_current_price_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(technical={})

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_technical_entirely_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(technical=None)

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_numeric_conviction_score_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(
            decision={
                "verdict": "BUY",
                "conviction_score": "not-a-number",
                "time_horizon": "12 months",
            }
        )

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_numeric_current_price_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(technical={"current_price": "n/a"})

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_job_id_returns_none(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state()

        result = await record_pending_evaluations(session, "not-a-uuid", state)

        assert result is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_unparsable_completed_at_falls_back_to_now(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(completed_at="not-a-timestamp")

        before = datetime.now(timezone.utc)
        result = await record_pending_evaluations(session, _JOB_ID, state)
        after = datetime.now(timezone.utc)

        assert result is not None
        added = session.add.call_args.args[0]
        assert before <= added.verdict_date <= after

    @pytest.mark.asyncio
    async def test_missing_completed_at_falls_back_to_now(self) -> None:
        session = _make_mock_session()
        state = _make_completed_state(completed_at=None)

        before = datetime.now(timezone.utc)
        result = await record_pending_evaluations(session, _JOB_ID, state)
        after = datetime.now(timezone.utc)

        assert result is not None
        added = session.add.call_args.args[0]
        assert before <= added.verdict_date <= after


# ---------------------------------------------------------------------------
# record_pending_evaluations() -- database errors (never raises)
# ---------------------------------------------------------------------------


class TestRecordPendingEvaluationsDbErrors:
    @pytest.mark.asyncio
    async def test_integrity_error_on_commit_rolls_back_and_returns_none(
        self,
    ) -> None:
        session = _make_mock_session()
        session.commit = AsyncMock(
            side_effect=IntegrityError("duplicate key", {}, BaseException())
        )
        state = _make_completed_state()

        result = await record_pending_evaluations(session, _JOB_ID, state)

        assert result is None
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_db_error_never_raises(self) -> None:
        session = _make_mock_session()
        session.commit = AsyncMock(
            side_effect=IntegrityError("duplicate key", {}, BaseException())
        )
        state = _make_completed_state()

        # Must complete without raising -- this call itself is the
        # assertion; pytest fails the test if an exception escapes.
        await record_pending_evaluations(session, _JOB_ID, state)


# ---------------------------------------------------------------------------
# score_directional_correctness() -- T-089 dead-zone rule
# ---------------------------------------------------------------------------


class TestScoreDirectionalCorrectnessBuy:
    def test_fall_of_exactly_dead_zone_is_wrong(self) -> None:
        assert score_directional_correctness("BUY", -DEAD_ZONE_PCT) is False

    def test_fall_just_short_of_dead_zone_is_correct(self) -> None:
        assert score_directional_correctness("BUY", -4.99) is True

    def test_large_fall_is_wrong(self) -> None:
        assert score_directional_correctness("BUY", -20.0) is False

    def test_flat_is_correct(self) -> None:
        assert score_directional_correctness("BUY", 0.0) is True

    def test_large_rise_is_correct(self) -> None:
        assert score_directional_correctness("BUY", 25.0) is True

    def test_rise_of_exactly_dead_zone_is_correct(self) -> None:
        # The dead zone only ever penalises a BUY for falling -- a rise,
        # however large, is never a miss for a BUY verdict.
        assert score_directional_correctness("BUY", DEAD_ZONE_PCT) is True


class TestScoreDirectionalCorrectnessSell:
    def test_rise_of_exactly_dead_zone_is_wrong(self) -> None:
        assert score_directional_correctness("SELL", DEAD_ZONE_PCT) is False

    def test_rise_just_short_of_dead_zone_is_correct(self) -> None:
        assert score_directional_correctness("SELL", 4.99) is True

    def test_large_rise_is_wrong(self) -> None:
        assert score_directional_correctness("SELL", 20.0) is False

    def test_flat_is_correct(self) -> None:
        assert score_directional_correctness("SELL", 0.0) is True

    def test_large_fall_is_correct(self) -> None:
        assert score_directional_correctness("SELL", -25.0) is True

    def test_fall_of_exactly_dead_zone_is_correct(self) -> None:
        # The dead zone only ever penalises a SELL for rising -- a fall,
        # however large, is never a miss for a SELL verdict.
        assert score_directional_correctness("SELL", -DEAD_ZONE_PCT) is True


class TestScoreDirectionalCorrectnessHold:
    def test_rise_of_exactly_dead_zone_is_wrong(self) -> None:
        assert score_directional_correctness("HOLD", DEAD_ZONE_PCT) is False

    def test_fall_of_exactly_dead_zone_is_wrong(self) -> None:
        assert score_directional_correctness("HOLD", -DEAD_ZONE_PCT) is False

    def test_just_inside_dead_zone_on_upside_is_correct(self) -> None:
        assert score_directional_correctness("HOLD", 4.99) is True

    def test_just_inside_dead_zone_on_downside_is_correct(self) -> None:
        assert score_directional_correctness("HOLD", -4.99) is True

    def test_flat_is_correct(self) -> None:
        assert score_directional_correctness("HOLD", 0.0) is True

    def test_large_rise_is_wrong(self) -> None:
        assert score_directional_correctness("HOLD", 30.0) is False

    def test_large_fall_is_wrong(self) -> None:
        assert score_directional_correctness("HOLD", -30.0) is False


class TestScoreDirectionalCorrectnessUnrecognisedVerdict:
    def test_unrecognised_verdict_uses_hold_rule_not_raise(self) -> None:
        # Should never happen in practice (DB-enum-constrained), but the
        # function must degrade to the strictest (HOLD) rule rather than
        # raising on unexpected input.
        assert score_directional_correctness("MAYBE", 0.0) is True
        assert score_directional_correctness("MAYBE", 10.0) is False
        assert score_directional_correctness("MAYBE", -10.0) is False


# ---------------------------------------------------------------------------
# _compute_price_change_pct() -- T-089
# ---------------------------------------------------------------------------


class TestComputePriceChangePct:
    def test_rise(self) -> None:
        pct = _compute_price_change_pct(100.0, 110.0)
        assert pct == 10.0

    def test_fall(self) -> None:
        pct = _compute_price_change_pct(100.0, 90.0)
        assert pct == -10.0

    def test_flat(self) -> None:
        pct = _compute_price_change_pct(100.0, 100.0)
        assert pct == 0.0

    def test_rounds_to_four_decimal_places(self) -> None:
        pct = _compute_price_change_pct(3.0, 4.0)
        # (4 - 3) / 3 * 100 = 33.333333...
        assert pct == 33.3333

    def test_zero_price_at_verdict_returns_zero_without_raising(self) -> None:
        pct = _compute_price_change_pct(0.0, 100.0)
        assert pct == 0.0


# ---------------------------------------------------------------------------
# run_due_evaluations() -- T-089
# ---------------------------------------------------------------------------


def _make_outcome_row(
    *,
    verdict_date: datetime,
    evaluation_horizon_days: int = 90,
    verdict: str = "BUY",
    ticker: str = "TCS.NS",
    price_at_verdict: float = 3000.0,
    evaluated_at: Any = None,
) -> VerdictOutcome:
    return VerdictOutcome(
        id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        ticker=ticker,
        verdict=verdict,
        conviction_score=7,
        price_at_verdict=price_at_verdict,
        verdict_date=verdict_date,
        evaluation_horizon_days=evaluation_horizon_days,
        evaluated_at=evaluated_at,
    )


def _make_select_session(rows: list[VerdictOutcome]) -> AsyncMock:
    """AsyncSession whose execute(select(...)) returns the given rows."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all = MagicMock(return_value=rows)
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _mock_price_success(current_price: float) -> dict[str, Any]:
    return {
        "ticker": "TCS.NS",
        "stats": {"current_price": current_price},
    }


def _mock_price_error(message: str = "ticker not found") -> dict[str, Any]:
    return {"error": "ticker_not_found", "ticker": "TCS.NS", "message": message}


_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestRunDueEvaluationsNoPendingRows:
    @pytest.mark.asyncio
    async def test_returns_all_zero_result(self) -> None:
        session = _make_select_session([])

        result = await run_due_evaluations(session, now=_NOW)

        assert result == EvaluationBatchResult(
            due_count=0, evaluated_count=0, skipped_count=0
        )


class TestRunDueEvaluationsDueFiltering:
    @pytest.mark.asyncio
    async def test_row_not_yet_due_is_excluded(self) -> None:
        row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=30),
            evaluation_horizon_days=90,
        )
        session = _make_select_session([row])

        result = await run_due_evaluations(session, now=_NOW)

        assert result.due_count == 0
        assert result.evaluated_count == 0
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_row_exactly_at_horizon_is_due(self) -> None:
        # verdict_date + 90 days == _NOW exactly -- boundary is inclusive.
        row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=90),
            evaluation_horizon_days=90,
        )
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(return_value=_mock_price_success(3300.0))
            result = await run_due_evaluations(session, now=_NOW)

        assert result.due_count == 1
        assert result.evaluated_count == 1

    @pytest.mark.asyncio
    async def test_row_past_its_horizon_is_due(self) -> None:
        row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=200),
            evaluation_horizon_days=90,
        )
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(return_value=_mock_price_success(3300.0))
            result = await run_due_evaluations(session, now=_NOW)

        assert result.due_count == 1
        assert result.evaluated_count == 1

    @pytest.mark.asyncio
    async def test_naive_verdict_date_treated_as_utc(self) -> None:
        # A row built without tzinfo (e.g. a test fixture, or a future
        # caller) must not crash the datetime comparison.
        naive_date = (_NOW - timedelta(days=100)).replace(tzinfo=None)
        row = _make_outcome_row(
            verdict_date=naive_date,
            evaluation_horizon_days=90,
        )
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(return_value=_mock_price_success(3300.0))
            result = await run_due_evaluations(session, now=_NOW)

        assert result.due_count == 1
        assert result.evaluated_count == 1


class TestRunDueEvaluationsHappyPath:
    @pytest.mark.asyncio
    async def test_scores_and_commits_one_due_row(self) -> None:
        row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=100),
            evaluation_horizon_days=90,
            verdict="BUY",
            price_at_verdict=3000.0,
        )
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(return_value=_mock_price_success(3300.0))
            result = await run_due_evaluations(session, now=_NOW)

        assert result == EvaluationBatchResult(
            due_count=1, evaluated_count=1, skipped_count=0
        )
        assert row.price_at_evaluation == 3300.0
        assert row.price_change_pct == 10.0
        assert row.directional_correct is True
        assert row.evaluated_at == _NOW
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(row)

    @pytest.mark.asyncio
    async def test_scores_multiple_due_rows_independently(self) -> None:
        buy_row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=100),
            verdict="BUY",
            price_at_verdict=1000.0,
            ticker="TCS.NS",
        )
        sell_row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=100),
            verdict="SELL",
            price_at_verdict=2000.0,
            ticker="INFY.NS",
        )
        session = _make_select_session([buy_row, sell_row])

        prices = {"TCS.NS": 1200.0, "INFY.NS": 2300.0}

        def _invoke(payload: dict[str, Any]) -> dict[str, Any]:
            return _mock_price_success(prices[payload["ticker"]])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(side_effect=_invoke)
            result = await run_due_evaluations(session, now=_NOW)

        assert result.due_count == 2
        assert result.evaluated_count == 2
        # BUY rose 20% -> correct
        assert buy_row.directional_correct is True
        # SELL rose 15% (against the SELL thesis, beyond the dead zone)
        # -> wrong
        assert sell_row.directional_correct is False


class TestRunDueEvaluationsPriceFetchFailure:
    @pytest.mark.asyncio
    async def test_error_dict_leaves_row_unevaluated(self) -> None:
        row = _make_outcome_row(verdict_date=_NOW - timedelta(days=100))
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(return_value=_mock_price_error())
            result = await run_due_evaluations(session, now=_NOW)

        assert result == EvaluationBatchResult(
            due_count=1, evaluated_count=0, skipped_count=1
        )
        assert row.evaluated_at is None
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_current_price_in_stats_leaves_row_unevaluated(
        self,
    ) -> None:
        row = _make_outcome_row(verdict_date=_NOW - timedelta(days=100))
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(
                return_value={"ticker": "TCS.NS", "stats": {}}
            )
            result = await run_due_evaluations(session, now=_NOW)

        assert result.evaluated_count == 0
        assert result.skipped_count == 1


class TestRunDueEvaluationsDbErrors:
    @pytest.mark.asyncio
    async def test_commit_failure_on_one_row_is_skipped_others_continue(
        self,
    ) -> None:
        bad_row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=100), ticker="BAD.NS"
        )
        good_row = _make_outcome_row(
            verdict_date=_NOW - timedelta(days=100), ticker="GOOD.NS"
        )
        session = _make_select_session([bad_row, good_row])
        session.commit = AsyncMock(side_effect=[SQLAlchemyError("db exploded"), None])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(return_value=_mock_price_success(3300.0))
            result = await run_due_evaluations(session, now=_NOW)

        assert result.due_count == 2
        assert result.evaluated_count == 1
        assert result.skipped_count == 1
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unexpected_exception_on_one_row_never_raises(self) -> None:
        row = _make_outcome_row(verdict_date=_NOW - timedelta(days=100))
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(side_effect=RuntimeError("boom"))
            # Must complete without raising -- this call itself is the
            # assertion; pytest fails the test if an exception escapes.
            result = await run_due_evaluations(session, now=_NOW)

        assert result.evaluated_count == 0
        assert result.skipped_count == 1

    @pytest.mark.asyncio
    async def test_load_pending_rows_query_failure_returns_zero_result(
        self,
    ) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=SQLAlchemyError("connection lost"))

        result = await run_due_evaluations(session, now=_NOW)

        assert result == EvaluationBatchResult(
            due_count=0, evaluated_count=0, skipped_count=0
        )


class TestRunDueEvaluationsDefaultNow:
    @pytest.mark.asyncio
    async def test_defaults_now_to_current_utc_time_when_omitted(self) -> None:
        # A row due comfortably in the past should still be picked up
        # when `now` is not passed explicitly (defaults to datetime.now).
        row = _make_outcome_row(
            verdict_date=datetime.now(timezone.utc) - timedelta(days=200),
            evaluation_horizon_days=90,
        )
        session = _make_select_session([row])

        with patch("backend.services.accuracy_tracker.fetch_stock_price") as mock_fetch:
            mock_fetch.invoke = MagicMock(return_value=_mock_price_success(3300.0))
            result = await run_due_evaluations(session)

        assert result.due_count == 1
        assert result.evaluated_count == 1
