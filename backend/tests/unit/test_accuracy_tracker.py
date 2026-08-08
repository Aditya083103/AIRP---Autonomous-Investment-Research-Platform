# backend/tests/unit/test_accuracy_tracker.py
"""
Unit tests for T-088: backend/services/accuracy_tracker.py

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

All database interactions use a mocked AsyncSession (AsyncMock) --  no
real PostgreSQL connection, matching the existing
test_state_persistence.py / test_analysis_service.py pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from backend.graph.state import InvestmentState, make_initial_state
from backend.models.orm import VerdictOutcome
from backend.services.accuracy_tracker import (
    DEFAULT_EVALUATION_HORIZON_DAYS,
    HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS,
    derive_evaluation_horizon_days,
    record_pending_evaluations,
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
