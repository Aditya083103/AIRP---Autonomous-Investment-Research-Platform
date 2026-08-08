# backend/tests/unit/test_accuracy_summary_history.py
"""
Unit tests for T-091:
  * backend/services/accuracy_tracker.py -- get_accuracy_summary(),
    get_accuracy_history()
  * backend/routers/accuracy.py -- GET /api/v1/accuracy/summary,
    GET /api/v1/accuracy/history

Test strategy
-------------
1. get_accuracy_summary() (service layer, mocked AsyncSession)
     empty verdict_outcomes table -- total_evaluated=0, total_pending=0,
       overall_accuracy_pct is None, by_verdict has exactly 3 entries
       (BUY/HOLD/SELL) all zero/None, by_conviction has exactly 3
       entries (low/medium/high) all zero/None
     populated table -- overall_accuracy_pct computed correctly;
       accuracy_pct rounded to 2 decimal places
     a verdict/bucket with rows in the DB but none evaluated yet --
       evaluated_count/correct_count are 0, accuracy_pct is None (not
       a fabricated 0%)
     a verdict the GROUP BY query has no row for at all (e.g. no SELL
       verdicts exist yet) -- still appears in the response with zero
       counts, not omitted
     three independent session.execute() calls, in order (overall,
       by-verdict, by-conviction)
2. get_accuracy_history() (service layer, mocked AsyncSession)
     no rows -- empty page, total_count=0, has_more=False
     fewer rows than limit -- has_more=False
     more rows than limit -- has_more=True
     offset beyond total_count -- empty items, has_more=False,
       total_count still reflects the true total
     entry field mapping -- every AccuracyHistoryEntry field matches
       the underlying VerdictOutcome ORM row, including a still-
       pending row (price_at_evaluation/price_change_pct/
       directional_correct/evaluated_at all None)
     query order -- COUNT query, then the page query, in that order
3. GET /api/v1/accuracy/summary (router, HTTP-level via
   httpx.ASGITransport)
     no authentication header required at all -- 200 with zero args
     response body matches get_accuracy_summary()'s return value
       field-for-field
     get_accuracy_summary is called with the request's session
4. GET /api/v1/accuracy/history (router, HTTP-level)
     no authentication header required at all -- 200 with zero args
     default limit/offset applied when omitted
     explicit limit/offset forwarded to get_accuracy_history()
     limit > MAX_ACCURACY_HISTORY_PAGE_SIZE -- 422 (Query validation)
     limit < 1 -- 422 (Query validation)
     negative offset -- 422 (Query validation)
     response body matches get_accuracy_history()'s return value
       field-for-field, including has_more

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, matching the existing
test_accuracy_tracker.py / test_analysis_result_history_service.py
pattern. Router tests patch backend.routers.accuracy.get_accuracy_summary
/ get_accuracy_history directly (patch-where-it's-looked-up, the same
rule test_accuracy_router.py's own docstring documents), so the service
layer's own mocked-session tests (sections 1-2 above) are the only place
the real aggregation SQL statements are exercised (against a mocked
Result, never a live database). ENVIRONMENT must be set to 'test' before
any backend import.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import Any, Optional, cast
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import FastAPI
import httpx
import pytest

from backend.db.session import get_async_session
from backend.main import create_app
from backend.models.orm import VerdictOutcome
from backend.services.accuracy_tracker import (
    DEFAULT_ACCURACY_HISTORY_PAGE_SIZE,
    MAX_ACCURACY_HISTORY_PAGE_SIZE,
    AccuracyHistoryEntry,
    AccuracyHistoryPage,
    AccuracySummary,
    ConvictionAccuracyBreakdown,
    VerdictAccuracyBreakdown,
    get_accuracy_history,
    get_accuracy_summary,
)

# ---------------------------------------------------------------------------
# get_accuracy_summary() -- shared fixtures/helpers
# ---------------------------------------------------------------------------


def _make_session_for_summary(
    overall_row: tuple[int, int, int],
    verdict_rows: list[tuple[str, int, int]],
    conviction_rows: list[tuple[str, int, int]],
) -> AsyncMock:
    """
    AsyncSession whose execute() is called exactly three times by
    get_accuracy_summary -- overall counts, GROUP BY verdict, GROUP BY
    conviction bucket -- in that exact order.
    """
    overall_result = MagicMock()
    overall_result.one = MagicMock(return_value=overall_row)

    verdict_result = MagicMock()
    verdict_result.all = MagicMock(return_value=verdict_rows)

    conviction_result = MagicMock()
    conviction_result.all = MagicMock(return_value=conviction_rows)

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[overall_result, verdict_result, conviction_result]
    )
    return session


class TestGetAccuracySummaryEmpty:
    @pytest.mark.asyncio
    async def test_empty_table_returns_zeroed_summary(self) -> None:
        session = _make_session_for_summary(
            overall_row=(0, 0, 0), verdict_rows=[], conviction_rows=[]
        )

        summary = await get_accuracy_summary(session)

        assert summary.total_evaluated == 0
        assert summary.total_pending == 0
        assert summary.overall_accuracy_pct is None

    @pytest.mark.asyncio
    async def test_empty_table_by_verdict_has_all_three_verdicts(self) -> None:
        session = _make_session_for_summary(
            overall_row=(0, 0, 0), verdict_rows=[], conviction_rows=[]
        )

        summary = await get_accuracy_summary(session)

        assert [entry.verdict for entry in summary.by_verdict] == [
            "BUY",
            "HOLD",
            "SELL",
        ]
        for entry in summary.by_verdict:
            assert entry.evaluated_count == 0
            assert entry.correct_count == 0
            assert entry.accuracy_pct is None

    @pytest.mark.asyncio
    async def test_empty_table_by_conviction_has_all_three_buckets(self) -> None:
        session = _make_session_for_summary(
            overall_row=(0, 0, 0), verdict_rows=[], conviction_rows=[]
        )

        summary = await get_accuracy_summary(session)

        assert [entry.bucket for entry in summary.by_conviction] == [
            "low",
            "medium",
            "high",
        ]
        assert [entry.label for entry in summary.by_conviction] == [
            "Low (1-3)",
            "Medium (4-6)",
            "High (7-10)",
        ]
        for entry in summary.by_conviction:
            assert entry.evaluated_count == 0
            assert entry.correct_count == 0
            assert entry.accuracy_pct is None


class TestGetAccuracySummaryPopulated:
    @pytest.mark.asyncio
    async def test_overall_accuracy_pct_computed_correctly(self) -> None:
        session = _make_session_for_summary(
            overall_row=(10, 3, 7),  # evaluated=10, pending=3, correct=7
            verdict_rows=[],
            conviction_rows=[],
        )

        summary = await get_accuracy_summary(session)

        assert summary.total_evaluated == 10
        assert summary.total_pending == 3
        assert summary.overall_accuracy_pct == 70.0

    @pytest.mark.asyncio
    async def test_accuracy_pct_rounded_to_two_decimal_places(self) -> None:
        session = _make_session_for_summary(
            overall_row=(3, 0, 2),  # 2/3 = 66.6666...
            verdict_rows=[],
            conviction_rows=[],
        )

        summary = await get_accuracy_summary(session)

        assert summary.overall_accuracy_pct == 66.67

    @pytest.mark.asyncio
    async def test_by_verdict_counts_and_pct_match_query_rows(self) -> None:
        session = _make_session_for_summary(
            overall_row=(10, 0, 7),
            verdict_rows=[("BUY", 5, 4), ("HOLD", 3, 2), ("SELL", 2, 1)],
            conviction_rows=[],
        )

        summary = await get_accuracy_summary(session)
        by_verdict = {entry.verdict: entry for entry in summary.by_verdict}

        assert by_verdict["BUY"].evaluated_count == 5
        assert by_verdict["BUY"].correct_count == 4
        assert by_verdict["BUY"].accuracy_pct == 80.0

        assert by_verdict["HOLD"].evaluated_count == 3
        assert by_verdict["HOLD"].correct_count == 2
        assert by_verdict["HOLD"].accuracy_pct == 66.67

        assert by_verdict["SELL"].evaluated_count == 2
        assert by_verdict["SELL"].correct_count == 1
        assert by_verdict["SELL"].accuracy_pct == 50.0

    @pytest.mark.asyncio
    async def test_verdict_with_no_rows_at_all_still_present_with_zeros(
        self,
    ) -> None:
        """No SELL verdicts have ever been issued -- the GROUP BY query
        has no row for 'SELL' at all, but the response must still
        include it with zero counts rather than omitting it."""
        session = _make_session_for_summary(
            overall_row=(5, 0, 4),
            verdict_rows=[("BUY", 5, 4)],
            conviction_rows=[],
        )

        summary = await get_accuracy_summary(session)
        by_verdict = {entry.verdict: entry for entry in summary.by_verdict}

        assert by_verdict["HOLD"].evaluated_count == 0
        assert by_verdict["HOLD"].accuracy_pct is None
        assert by_verdict["SELL"].evaluated_count == 0
        assert by_verdict["SELL"].accuracy_pct is None

    @pytest.mark.asyncio
    async def test_verdict_with_rows_but_none_evaluated_yet(self) -> None:
        """Rows exist for this verdict but none have been scored yet --
        evaluated_count/correct_count are 0, accuracy_pct is None (an
        unknown accuracy), never a fabricated 0%."""
        session = _make_session_for_summary(
            overall_row=(0, 4, 0),
            verdict_rows=[("BUY", 0, 0)],
            conviction_rows=[],
        )

        summary = await get_accuracy_summary(session)
        buy_entry = next(e for e in summary.by_verdict if e.verdict == "BUY")

        assert buy_entry.evaluated_count == 0
        assert buy_entry.accuracy_pct is None

    @pytest.mark.asyncio
    async def test_by_conviction_counts_and_pct_match_query_rows(self) -> None:
        session = _make_session_for_summary(
            overall_row=(10, 0, 7),
            verdict_rows=[],
            conviction_rows=[("low", 2, 1), ("medium", 5, 4), ("high", 3, 2)],
        )

        summary = await get_accuracy_summary(session)
        by_bucket = {entry.bucket: entry for entry in summary.by_conviction}

        assert by_bucket["low"].evaluated_count == 2
        assert by_bucket["low"].correct_count == 1
        assert by_bucket["low"].accuracy_pct == 50.0
        assert by_bucket["low"].min_score == 1
        assert by_bucket["low"].max_score == 3

        assert by_bucket["medium"].evaluated_count == 5
        assert by_bucket["medium"].correct_count == 4
        assert by_bucket["medium"].accuracy_pct == 80.0
        assert by_bucket["medium"].min_score == 4
        assert by_bucket["medium"].max_score == 6

        assert by_bucket["high"].evaluated_count == 3
        assert by_bucket["high"].correct_count == 2
        assert round(by_bucket["high"].accuracy_pct or 0.0, 2) == 66.67
        assert by_bucket["high"].min_score == 7
        assert by_bucket["high"].max_score == 10


class TestGetAccuracySummaryQueryOrder:
    @pytest.mark.asyncio
    async def test_three_queries_executed_in_order(self) -> None:
        session = _make_session_for_summary(
            overall_row=(0, 0, 0), verdict_rows=[], conviction_rows=[]
        )

        await get_accuracy_summary(session)

        assert session.execute.await_count == 3


class TestAccuracyBreakdownDataclasses:
    def test_verdict_accuracy_breakdown_fields(self) -> None:
        entry = VerdictAccuracyBreakdown(
            verdict="BUY", evaluated_count=5, correct_count=4, accuracy_pct=80.0
        )
        assert entry.verdict == "BUY"
        assert entry.accuracy_pct == 80.0

    def test_conviction_accuracy_breakdown_fields(self) -> None:
        entry = ConvictionAccuracyBreakdown(
            bucket="high",
            label="High (7-10)",
            min_score=7,
            max_score=10,
            evaluated_count=3,
            correct_count=2,
            accuracy_pct=66.67,
        )
        assert entry.bucket == "high"
        assert entry.min_score == 7
        assert entry.max_score == 10

    def test_accuracy_summary_is_a_frozen_dataclass(self) -> None:
        summary = AccuracySummary(
            total_evaluated=0,
            total_pending=0,
            overall_accuracy_pct=None,
            by_verdict=[],
            by_conviction=[],
        )
        with pytest.raises(FrozenInstanceError):
            cast(Any, summary).total_evaluated = 1


# ---------------------------------------------------------------------------
# get_accuracy_history() -- shared fixtures/helpers
# ---------------------------------------------------------------------------


def _make_outcome(
    *,
    row_id: Optional[uuid.UUID] = None,
    analysis_id: Optional[uuid.UUID] = None,
    ticker: str = "TCS.NS",
    verdict: str = "BUY",
    conviction_score: int = 7,
    price_at_verdict: float = 3000.0,
    verdict_date: Optional[datetime] = None,
    evaluation_horizon_days: int = 90,
    price_at_evaluation: Optional[float] = None,
    price_change_pct: Optional[float] = None,
    directional_correct: Optional[bool] = None,
    evaluated_at: Optional[datetime] = None,
) -> VerdictOutcome:
    return VerdictOutcome(
        id=row_id or uuid.uuid4(),
        analysis_id=analysis_id or uuid.uuid4(),
        ticker=ticker,
        verdict=verdict,
        conviction_score=conviction_score,
        price_at_verdict=price_at_verdict,
        verdict_date=verdict_date or datetime(2026, 1, 1, tzinfo=timezone.utc),
        evaluation_horizon_days=evaluation_horizon_days,
        price_at_evaluation=price_at_evaluation,
        price_change_pct=price_change_pct,
        directional_correct=directional_correct,
        evaluated_at=evaluated_at,
    )


def _make_session_for_history(
    total_count: int, rows: list[VerdictOutcome]
) -> AsyncMock:
    """
    AsyncSession whose execute() is called exactly twice by
    get_accuracy_history -- once for the COUNT query (returns a Result
    with scalar_one()) and once for the page query (returns a Result
    with scalars().all()) -- in that exact order.
    """
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=total_count)

    page_result = MagicMock()
    page_result.scalars.return_value.all = MagicMock(return_value=rows)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, page_result])
    return session


class TestGetAccuracyHistoryEmpty:
    @pytest.mark.asyncio
    async def test_no_rows_returns_empty_page(self) -> None:
        session = _make_session_for_history(total_count=0, rows=[])

        page = await get_accuracy_history(session)

        assert page.items == []
        assert page.total_count == 0
        assert page.has_more is False


class TestGetAccuracyHistoryPagination:
    @pytest.mark.asyncio
    async def test_fewer_rows_than_limit_has_more_false(self) -> None:
        rows = [_make_outcome() for _ in range(3)]
        session = _make_session_for_history(total_count=3, rows=rows)

        page = await get_accuracy_history(session, limit=20, offset=0)

        assert len(page.items) == 3
        assert page.has_more is False

    @pytest.mark.asyncio
    async def test_more_rows_than_limit_has_more_true(self) -> None:
        rows = [_make_outcome() for _ in range(20)]
        session = _make_session_for_history(total_count=25, rows=rows)

        page = await get_accuracy_history(session, limit=20, offset=0)

        assert len(page.items) == 20
        assert page.total_count == 25
        assert page.has_more is True

    @pytest.mark.asyncio
    async def test_offset_beyond_total_has_more_false(self) -> None:
        session = _make_session_for_history(total_count=5, rows=[])

        page = await get_accuracy_history(session, limit=20, offset=100)

        assert page.items == []
        assert page.total_count == 5
        assert page.has_more is False

    def test_has_more_property_on_a_raw_history_page(self) -> None:
        entry = AccuracyHistoryEntry(
            id=uuid.uuid4(),
            analysis_id=uuid.uuid4(),
            ticker="TCS.NS",
            verdict="BUY",
            conviction_score=8,
            price_at_verdict=3000.0,
            verdict_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            evaluation_horizon_days=90,
            price_at_evaluation=None,
            price_change_pct=None,
            directional_correct=None,
            evaluated_at=None,
        )
        page = AccuracyHistoryPage(items=[entry], total_count=10, limit=1, offset=5)
        assert page.has_more is True

        exhausted = AccuracyHistoryPage(items=[], total_count=10, limit=1, offset=10)
        assert exhausted.has_more is False


class TestGetAccuracyHistoryEntryShape:
    @pytest.mark.asyncio
    async def test_pending_row_fields_pass_through_as_none(self) -> None:
        row_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        row = _make_outcome(
            row_id=row_id,
            analysis_id=analysis_id,
            ticker="INFY.NS",
            verdict="HOLD",
            conviction_score=5,
            price_at_verdict=1500.0,
        )
        session = _make_session_for_history(total_count=1, rows=[row])

        page = await get_accuracy_history(session)
        entry = page.items[0]

        assert entry.id == row_id
        assert entry.analysis_id == analysis_id
        assert entry.ticker == "INFY.NS"
        assert entry.verdict == "HOLD"
        assert entry.conviction_score == 5
        assert entry.price_at_verdict == 1500.0
        assert entry.price_at_evaluation is None
        assert entry.price_change_pct is None
        assert entry.directional_correct is None
        assert entry.evaluated_at is None

    @pytest.mark.asyncio
    async def test_evaluated_row_fields_pass_through(self) -> None:
        evaluated_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        row = _make_outcome(
            price_at_evaluation=3200.0,
            price_change_pct=6.6667,
            directional_correct=True,
            evaluated_at=evaluated_at,
        )
        session = _make_session_for_history(total_count=1, rows=[row])

        page = await get_accuracy_history(session)
        entry = page.items[0]

        assert entry.price_at_evaluation == 3200.0
        assert entry.price_change_pct == 6.6667
        assert entry.directional_correct is True
        assert entry.evaluated_at == evaluated_at


class TestGetAccuracyHistoryQueryOrder:
    @pytest.mark.asyncio
    async def test_two_queries_executed_in_order(self) -> None:
        session = _make_session_for_history(total_count=0, rows=[])

        await get_accuracy_history(session)

        assert session.execute.await_count == 2


# ---------------------------------------------------------------------------
# HTTP-level router tests
# ---------------------------------------------------------------------------

_SUMMARY_URL = "/api/v1/accuracy/summary"
_HISTORY_URL = "/api/v1/accuracy/history"


async def _session_override() -> AsyncGenerator[AsyncMock, None]:
    yield AsyncMock()


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _session_override

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


_SAMPLE_SUMMARY = AccuracySummary(
    total_evaluated=10,
    total_pending=2,
    overall_accuracy_pct=70.0,
    by_verdict=[
        VerdictAccuracyBreakdown(
            verdict="BUY", evaluated_count=5, correct_count=4, accuracy_pct=80.0
        ),
        VerdictAccuracyBreakdown(
            verdict="HOLD", evaluated_count=3, correct_count=2, accuracy_pct=66.67
        ),
        VerdictAccuracyBreakdown(
            verdict="SELL", evaluated_count=2, correct_count=1, accuracy_pct=50.0
        ),
    ],
    by_conviction=[
        ConvictionAccuracyBreakdown(
            bucket="low",
            label="Low (1-3)",
            min_score=1,
            max_score=3,
            evaluated_count=1,
            correct_count=0,
            accuracy_pct=0.0,
        ),
        ConvictionAccuracyBreakdown(
            bucket="medium",
            label="Medium (4-6)",
            min_score=4,
            max_score=6,
            evaluated_count=4,
            correct_count=3,
            accuracy_pct=75.0,
        ),
        ConvictionAccuracyBreakdown(
            bucket="high",
            label="High (7-10)",
            min_score=7,
            max_score=10,
            evaluated_count=5,
            correct_count=4,
            accuracy_pct=80.0,
        ),
    ],
)


class TestSummaryEndpoint:
    @pytest.mark.asyncio
    async def test_no_auth_header_returns_200(self, client: httpx.AsyncClient) -> None:
        with patch(
            "backend.routers.accuracy.get_accuracy_summary",
            new=AsyncMock(return_value=_SAMPLE_SUMMARY),
        ):
            response = await client.get(_SUMMARY_URL)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_body_matches_summary(
        self, client: httpx.AsyncClient
    ) -> None:
        with patch(
            "backend.routers.accuracy.get_accuracy_summary",
            new=AsyncMock(return_value=_SAMPLE_SUMMARY),
        ):
            response = await client.get(_SUMMARY_URL)

        body = response.json()
        assert body["total_evaluated"] == 10
        assert body["total_pending"] == 2
        assert body["overall_accuracy_pct"] == 70.0
        assert [v["verdict"] for v in body["by_verdict"]] == ["BUY", "HOLD", "SELL"]
        assert body["by_verdict"][0]["accuracy_pct"] == 80.0
        assert [b["bucket"] for b in body["by_conviction"]] == [
            "low",
            "medium",
            "high",
        ]
        assert body["by_conviction"][2]["accuracy_pct"] == 80.0

    @pytest.mark.asyncio
    async def test_service_called_with_request_session(
        self, client: httpx.AsyncClient
    ) -> None:
        mock_summary = AsyncMock(return_value=_SAMPLE_SUMMARY)
        with patch("backend.routers.accuracy.get_accuracy_summary", new=mock_summary):
            await client.get(_SUMMARY_URL)

        mock_summary.assert_awaited_once()
        args, _kwargs = mock_summary.call_args
        assert len(args) == 1


class TestHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_no_auth_header_returns_200(self, client: httpx.AsyncClient) -> None:
        empty_page = AccuracyHistoryPage(items=[], total_count=0, limit=20, offset=0)
        with patch(
            "backend.routers.accuracy.get_accuracy_history",
            new=AsyncMock(return_value=empty_page),
        ):
            response = await client.get(_HISTORY_URL)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_default_limit_and_offset_applied(
        self, client: httpx.AsyncClient
    ) -> None:
        empty_page = AccuracyHistoryPage(
            items=[],
            total_count=0,
            limit=DEFAULT_ACCURACY_HISTORY_PAGE_SIZE,
            offset=0,
        )
        mock_history = AsyncMock(return_value=empty_page)
        with patch("backend.routers.accuracy.get_accuracy_history", new=mock_history):
            await client.get(_HISTORY_URL)

        mock_history.assert_awaited_once()
        _args, kwargs = mock_history.call_args
        assert kwargs["limit"] == DEFAULT_ACCURACY_HISTORY_PAGE_SIZE
        assert kwargs["offset"] == 0

    @pytest.mark.asyncio
    async def test_explicit_limit_and_offset_forwarded(
        self, client: httpx.AsyncClient
    ) -> None:
        empty_page = AccuracyHistoryPage(items=[], total_count=0, limit=5, offset=10)
        mock_history = AsyncMock(return_value=empty_page)
        with patch("backend.routers.accuracy.get_accuracy_history", new=mock_history):
            await client.get(_HISTORY_URL, params={"limit": 5, "offset": 10})

        _args, kwargs = mock_history.call_args
        assert kwargs["limit"] == 5
        assert kwargs["offset"] == 10

    @pytest.mark.asyncio
    async def test_limit_above_max_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            _HISTORY_URL,
            params={"limit": MAX_ACCURACY_HISTORY_PAGE_SIZE + 1},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_below_one_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get(_HISTORY_URL, params={"limit": 0})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_offset_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get(_HISTORY_URL, params={"offset": -1})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_response_body_matches_history_page(
        self, client: httpx.AsyncClient
    ) -> None:
        entry = AccuracyHistoryEntry(
            id=uuid.uuid4(),
            analysis_id=uuid.uuid4(),
            ticker="TCS.NS",
            verdict="BUY",
            conviction_score=8,
            price_at_verdict=3000.0,
            verdict_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            evaluation_horizon_days=90,
            price_at_evaluation=3200.0,
            price_change_pct=6.6667,
            directional_correct=True,
            evaluated_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        page = AccuracyHistoryPage(items=[entry], total_count=25, limit=1, offset=0)
        with patch(
            "backend.routers.accuracy.get_accuracy_history",
            new=AsyncMock(return_value=page),
        ):
            response = await client.get(_HISTORY_URL, params={"limit": 1})

        body = response.json()
        assert body["total_count"] == 25
        assert body["limit"] == 1
        assert body["offset"] == 0
        assert body["has_more"] is True
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["ticker"] == "TCS.NS"
        assert item["verdict"] == "BUY"
        assert item["conviction_score"] == 8
        assert item["directional_correct"] is True
