# backend/tests/unit/test_analysis_result_history_service.py
"""
Unit tests for T-050: backend/services/analysis.py's
get_analysis_result, get_analysis_history, and AnalysisNotReadyError.

A separate file from test_analysis_service.py (T-047/T-048) -- mirrors
the same "T-050 is its own task, gets its own test file" decision
test_websocket_router.py already established for T-049, rather than
further growing the 700+-line T-047/T-048 file.

Test strategy
-------------
1. get_analysis_result()
     no row for job_id                   -- returns None
     row belongs to a different user     -- returns None (never 403)
     status='pending'/'running'/'failed' -- raises AnalysisNotReadyError
       with .status set to the row's actual status
     status='completed', snapshot is NULL          -- raises
       AnalysisNotReadyError (defensive fallback, not a 404/None)
     status='completed', snapshot has no 'decision' key -- same
       defensive fallback
     status='completed', psycopg2-style string snapshot -- decision
       parsed identically to the asyncpg-style dict snapshot
     status='completed', valid decision  -- returns AnalysisResultData
       with the decision dict passed through unchanged
     malformed (non-JSON-parsable string) snapshot -- treated as "no
       decision", not propagated as a raw JSONDecodeError
     fundamental_years_available (T-084) -- extracted from the same
       snapshot's 'fundamental' entry; None when absent, non-dict, or
       missing years_available; never blocks a successful result even
       when unavailable
2. get_analysis_history()
     no rows for user_id                 -- empty page, total_count=0,
                                             has_more=False
     fewer rows than one page            -- has_more=False
     more rows than one page             -- has_more=True, items
                                             truncated to limit
     offset beyond total_count           -- empty items, has_more=False
       (total_count still reflects the true total, not zero)
     conviction_score as a string (JSONB ->> always returns text) is
       cast to int; a NULL verdict/conviction_score (pending/running/
       failed rows) is passed through as None, not coerced
     query parameters                    -- COUNT query and page query
       are each called with the correct {"user_id": ...} /
       {"user_id", "limit", "offset"} bound parameters

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, matching the existing
test_analysis_service.py pattern. ENVIRONMENT must be set to 'test'
before any backend import.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from backend.services.analysis import (
    AnalysisNotReadyError,
    AnalysisResultData,
    HistoryEntry,
    HistoryPage,
    get_analysis_history,
    get_analysis_result,
)

# ---------------------------------------------------------------------------
# get_analysis_result() -- shared fixtures/helpers
# ---------------------------------------------------------------------------


def _make_result_row(
    user_id: uuid.UUID,
    status: str = "completed",
    state_snapshot: Any = None,
) -> tuple[Any, ...]:
    """Build a fake asyncpg Row as a plain tuple -- indexable like the
    real Result row get_analysis_result reads via row[0]..row[2]."""
    return (user_id, status, state_snapshot)


def _make_session_returning_row(row: Optional[tuple[Any, ...]]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=mock_result)
    return session


_VALID_DECISION: dict[str, Any] = {
    "agent_name": "portfolio_manager",
    "verdict": "BUY",
    "conviction_score": 8,
    "generated_at": "2026-06-20 10:30:00.000000",
}


class TestGetAnalysisResultNotFound:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_row_exists(self) -> None:
        session = _make_session_returning_row(None)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=uuid.uuid4()
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_a_different_users_job(self) -> None:
        owner_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        row = _make_result_row(
            user_id=owner_id, state_snapshot={"decision": _VALID_DECISION}
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=requester_id
        )

        assert result is None


class TestGetAnalysisResultNotReady:
    @pytest.mark.asyncio
    async def test_pending_status_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(user_id=user_id, status="pending")
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError) as exc_info:
            await get_analysis_result(session, job_id=uuid.uuid4(), user_id=user_id)
        assert exc_info.value.status == "pending"

    @pytest.mark.asyncio
    async def test_running_status_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(user_id=user_id, status="running")
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError) as exc_info:
            await get_analysis_result(session, job_id=uuid.uuid4(), user_id=user_id)
        assert exc_info.value.status == "running"

    @pytest.mark.asyncio
    async def test_failed_status_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(user_id=user_id, status="failed")
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError) as exc_info:
            await get_analysis_result(session, job_id=uuid.uuid4(), user_id=user_id)
        assert exc_info.value.status == "failed"

    @pytest.mark.asyncio
    async def test_completed_with_null_snapshot_raises_not_ready(self) -> None:
        """status='completed' but state_snapshot is SQL NULL -- should
        never happen given portfolio_manager_node's contract, but must
        degrade to AnalysisNotReadyError rather than a raw TypeError
        deep inside JSON parsing."""
        user_id = uuid.uuid4()
        row = _make_result_row(user_id=user_id, status="completed", state_snapshot=None)
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await get_analysis_result(session, job_id=uuid.uuid4(), user_id=user_id)

    @pytest.mark.asyncio
    async def test_completed_with_no_decision_key_raises_not_ready(self) -> None:
        """The snapshot exists and is valid JSON, but has no 'decision'
        key (e.g. a checkpoint saved by an earlier node, somehow tagged
        status='completed' -- defensive coverage, not a real pipeline
        path)."""
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"job_id": "abc", "status": "completed"},
        )
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await get_analysis_result(session, job_id=uuid.uuid4(), user_id=user_id)

    @pytest.mark.asyncio
    async def test_malformed_json_string_snapshot_raises_not_ready(self) -> None:
        """A psycopg2-style string snapshot that is not valid JSON --
        json.loads failure must be caught and treated as "no decision",
        not propagated as a raw JSONDecodeError out of this function."""
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id, status="completed", state_snapshot="{not valid json"
        )
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await get_analysis_result(session, job_id=uuid.uuid4(), user_id=user_id)


class TestGetAnalysisResultSuccess:
    @pytest.mark.asyncio
    async def test_returns_analysis_result_data(self) -> None:
        user_id = uuid.uuid4()
        job_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"decision": _VALID_DECISION},
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(session, job_id=job_id, user_id=user_id)

        assert isinstance(result, AnalysisResultData)
        assert result.job_id == job_id
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_decision_dict_passed_through_unchanged(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"decision": _VALID_DECISION},
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.decision == _VALID_DECISION

    @pytest.mark.asyncio
    async def test_psycopg2_style_string_snapshot_is_parsed(self) -> None:
        """asyncpg returns JSONB as a dict already; psycopg2 returns a
        JSON string -- both must produce the identical decision dict."""
        user_id = uuid.uuid4()
        snapshot_json = '{"decision": {"verdict": "SELL", "conviction_score": 3}}'
        row = _make_result_row(
            user_id=user_id, status="completed", state_snapshot=snapshot_json
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.decision["verdict"] == "SELL"

    @pytest.mark.asyncio
    async def test_queries_with_correct_job_id_parameter(self) -> None:
        user_id = uuid.uuid4()
        job_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"decision": _VALID_DECISION},
        )
        session = _make_session_returning_row(row)

        await get_analysis_result(session, job_id=job_id, user_id=user_id)

        session.execute.assert_awaited_once()
        bound_params = session.execute.call_args.args[1]
        assert bound_params == {"job_id": str(job_id)}


class TestGetAnalysisResultFundamentalYearsAvailable:
    """T-084: fundamental_years_available is a soft signal extracted
    from the same state_snapshot's 'fundamental' entry -- it never
    blocks a successful result, unlike a missing 'decision'."""

    @pytest.mark.asyncio
    async def test_extracted_when_present(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={
                "decision": _VALID_DECISION,
                "fundamental": {"years_available": 2},
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.fundamental_years_available == 2

    @pytest.mark.asyncio
    async def test_none_when_fundamental_key_missing(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"decision": _VALID_DECISION},
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.fundamental_years_available is None

    @pytest.mark.asyncio
    async def test_none_when_fundamental_is_not_a_dict(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={
                "decision": _VALID_DECISION,
                "fundamental": "not-a-dict",
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.fundamental_years_available is None

    @pytest.mark.asyncio
    async def test_none_when_years_available_key_missing(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={
                "decision": _VALID_DECISION,
                "fundamental": {"score": 8},
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.fundamental_years_available is None

    @pytest.mark.asyncio
    async def test_full_four_years_extracted_correctly(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={
                "decision": _VALID_DECISION,
                "fundamental": {"years_available": 4},
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.fundamental_years_available == 4

    @pytest.mark.asyncio
    async def test_string_years_available_is_cast_to_int(self) -> None:
        """JSONB ->> style string values (e.g. from a raw SQL path) are
        coerced to int rather than left as a string or dropped."""
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={
                "decision": _VALID_DECISION,
                "fundamental": {"years_available": "3"},
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.fundamental_years_available == 3

    @pytest.mark.asyncio
    async def test_malformed_years_available_returns_none(self) -> None:
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={
                "decision": _VALID_DECISION,
                "fundamental": {"years_available": "not-a-number"},
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.fundamental_years_available is None

    @pytest.mark.asyncio
    async def test_missing_fundamental_never_blocks_a_successful_result(self) -> None:
        """Unlike a missing 'decision', a missing/malformed 'fundamental'
        entry must never raise AnalysisNotReadyError."""
        user_id = uuid.uuid4()
        row = _make_result_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"decision": _VALID_DECISION},
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_result(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.decision == _VALID_DECISION


# ---------------------------------------------------------------------------
# get_analysis_history() -- shared fixtures/helpers
# ---------------------------------------------------------------------------


def _make_history_row(
    job_id: uuid.UUID,
    company_name: str = "Tata Consultancy Services",
    ticker_yf: str = "TCS.NS",
    exchange: str = "NSE",
    status: str = "completed",
    requested_at: Any = None,
    completed_at: Any = None,
    verdict: Any = "BUY",
    conviction_score: Any = "8",
) -> tuple[Any, ...]:
    """Build a fake asyncpg Row as a plain tuple -- indexable like the
    real Result row get_analysis_history reads via row[0]..row[8].
    conviction_score defaults to a STRING ('8') since Postgres's JSONB
    ->> operator always extracts text, matching the real query's
    actual return type rather than the int the response eventually
    becomes after get_analysis_history's own int(row[8]) cast."""
    return (
        job_id,
        company_name,
        ticker_yf,
        exchange,
        status,
        requested_at,
        completed_at,
        verdict,
        conviction_score,
    )


def _make_session_for_history(
    total_count: int, rows: list[tuple[Any, ...]]
) -> AsyncMock:
    """
    Build a session whose execute() is called exactly twice by
    get_analysis_history -- once for _SQL_COUNT_HISTORY (returns a
    Result with scalar_one()) and once for _SQL_LOAD_HISTORY_PAGE
    (returns a Result with fetchall()) -- in that exact order, mirroring
    the two sequential await session.execute(...) calls in the real
    function.
    """
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=total_count)

    page_result = MagicMock()
    page_result.fetchall = MagicMock(return_value=rows)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, page_result])
    return session


class TestGetAnalysisHistoryEmpty:
    @pytest.mark.asyncio
    async def test_no_rows_returns_empty_page(self) -> None:
        session = _make_session_for_history(total_count=0, rows=[])

        page = await get_analysis_history(session, user_id=uuid.uuid4())

        assert page.items == []
        assert page.total_count == 0
        assert page.has_more is False


class TestGetAnalysisHistoryPagination:
    @pytest.mark.asyncio
    async def test_fewer_rows_than_limit_has_more_false(self) -> None:
        rows = [_make_history_row(job_id=uuid.uuid4()) for _ in range(3)]
        session = _make_session_for_history(total_count=3, rows=rows)

        page = await get_analysis_history(
            session, user_id=uuid.uuid4(), limit=20, offset=0
        )

        assert len(page.items) == 3
        assert page.has_more is False

    @pytest.mark.asyncio
    async def test_more_rows_than_limit_has_more_true(self) -> None:
        """The fake returns exactly `limit` rows for this page (mirroring
        what the real LIMIT clause does at the database level) while
        total_count reports the true, larger total -- HistoryPage.has_more
        must be computed from that arithmetic, not from len(items) alone."""
        page_of_rows = [_make_history_row(job_id=uuid.uuid4()) for _ in range(20)]
        session = _make_session_for_history(total_count=25, rows=page_of_rows)

        page = await get_analysis_history(
            session, user_id=uuid.uuid4(), limit=20, offset=0
        )

        assert len(page.items) == 20
        assert page.total_count == 25
        assert page.has_more is True

    @pytest.mark.asyncio
    async def test_offset_beyond_total_has_more_false(self) -> None:
        session = _make_session_for_history(total_count=5, rows=[])

        page = await get_analysis_history(
            session, user_id=uuid.uuid4(), limit=20, offset=100
        )

        assert page.items == []
        assert page.total_count == 5
        assert page.has_more is False

    @pytest.mark.asyncio
    async def test_has_more_property_on_a_raw_history_page(self) -> None:
        """Direct unit test of HistoryPage.has_more's own arithmetic,
        independent of get_analysis_history -- offset + len(items) <
        total_count."""
        entry = HistoryEntry(
            job_id=uuid.uuid4(),
            company_name="Tata Consultancy Services",
            ticker="TCS.NS",
            exchange="NSE",
            status="completed",
            requested_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
            completed_at=None,
            verdict="BUY",
            conviction_score=8,
        )
        page = HistoryPage(items=[entry], total_count=10, limit=1, offset=5)
        assert page.has_more is True

        exhausted = HistoryPage(items=[], total_count=10, limit=1, offset=10)
        assert exhausted.has_more is False


class TestGetAnalysisHistoryEntryShape:
    @pytest.mark.asyncio
    async def test_conviction_score_string_is_cast_to_int(self) -> None:
        job_id = uuid.uuid4()
        row = _make_history_row(job_id=job_id, conviction_score="7")
        session = _make_session_for_history(total_count=1, rows=[row])

        page = await get_analysis_history(session, user_id=uuid.uuid4())

        assert page.items[0].conviction_score == 7
        assert isinstance(page.items[0].conviction_score, int)

    @pytest.mark.asyncio
    async def test_null_verdict_and_conviction_pass_through_as_none(self) -> None:
        """A pending/running/failed row -- the JSONB ->> extraction
        yields SQL NULL for both columns when no decision exists yet."""
        job_id = uuid.uuid4()
        row = _make_history_row(
            job_id=job_id,
            status="pending",
            verdict=None,
            conviction_score=None,
        )
        session = _make_session_for_history(total_count=1, rows=[row])

        page = await get_analysis_history(session, user_id=uuid.uuid4())

        assert page.items[0].verdict is None
        assert page.items[0].conviction_score is None

    @pytest.mark.asyncio
    async def test_company_fields_mapped_correctly(self) -> None:
        job_id = uuid.uuid4()
        row = _make_history_row(
            job_id=job_id,
            company_name="Infosys Limited",
            ticker_yf="INFY.NS",
            exchange="NSE",
        )
        session = _make_session_for_history(total_count=1, rows=[row])

        page = await get_analysis_history(session, user_id=uuid.uuid4())
        entry = page.items[0]

        assert entry.job_id == job_id
        assert entry.company_name == "Infosys Limited"
        assert entry.ticker == "INFY.NS"
        assert entry.exchange == "NSE"


class TestGetAnalysisHistoryQueryParameters:
    @pytest.mark.asyncio
    async def test_count_query_bound_with_user_id(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session_for_history(total_count=0, rows=[])

        await get_analysis_history(session, user_id=user_id)

        first_call_params = session.execute.call_args_list[0].args[1]
        assert first_call_params == {"user_id": str(user_id)}

    @pytest.mark.asyncio
    async def test_page_query_bound_with_user_id_limit_and_offset(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session_for_history(total_count=0, rows=[])

        await get_analysis_history(session, user_id=user_id, limit=5, offset=10)

        second_call_params = session.execute.call_args_list[1].args[1]
        assert second_call_params == {
            "user_id": str(user_id),
            "limit": 5,
            "offset": 10,
        }

    @pytest.mark.asyncio
    async def test_default_limit_and_offset(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session_for_history(total_count=0, rows=[])

        page = await get_analysis_history(session, user_id=user_id)

        assert page.limit == 20
        assert page.offset == 0
