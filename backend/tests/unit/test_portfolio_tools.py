# backend/tests/unit/test_portfolio_tools.py
"""
Unit tests for T-101: backend/tools/portfolio_tools.py's
get_user_analyses, get_memo_by_ticker, and search_uploaded_documents.

Test strategy
-------------
Each tool is tested at two levels, per this task's own acceptance
criterion ("each tool independently unit tested"):

1. Core function tests (_get_user_analyses_core,
   _get_memo_by_ticker_core, _search_uploaded_documents_core) -- the
   primary coverage. Mocked AsyncSession objects (AsyncMock/MagicMock)
   for the two DB-backed tools, mirroring the pattern established in
   test_analysis_result_history_service.py and test_chat_service.py;
   a patched module-level semantic_search for the ChromaDB-backed tool,
   mirroring test_sentiment_analyst.py's
   patch("backend.agents.sentiment_analyst.semantic_search") pattern.

2. build_portfolio_tools() wiring tests -- confirm the factory returns
   exactly 3 correctly-named BaseTool instances, and that invoking each
   tool through its public .invoke()/.ainvoke() interface (not calling
   the core function directly) reaches the same underlying logic with
   session/user_id correctly bound via closure -- proving the tools
   the chat loop will actually receive work end to end, not just their
   private implementations.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from langchain_core.tools import BaseTool
import pytest

from backend.tools.portfolio_tools import (
    DEFAULT_ANALYSES_LIMIT,
    DEFAULT_SEARCH_RESULTS,
    MAX_ANALYSES_LIMIT,
    MAX_SEARCH_RESULTS,
    _get_memo_by_ticker_core,
    _get_user_analyses_core,
    _search_uploaded_documents_core,
    build_portfolio_tools,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _make_session_returning_rows(rows: list[tuple[Any, ...]]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=rows)
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_session_returning_row(row: Optional[tuple[Any, ...]]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=mock_result)
    return session


_COMPLETED_AT = datetime(2026, 8, 1, 10, 6, 0, tzinfo=timezone.utc)

_DECISION_FIXTURE: dict[str, Any] = {
    "verdict": "BUY",
    "conviction_score": 8,
    "price_target": "Rs 4,200 (12-month)",
    "time_horizon": "12 months",
    "executive_summary": "TCS presents a durable growth story at a fair valuation.",
    "investment_thesis": "Deal wins and margin resilience support a BUY.",
}


# ---------------------------------------------------------------------------
# _get_user_analyses_core
# ---------------------------------------------------------------------------


class TestGetUserAnalysesCore:
    @pytest.mark.asyncio
    async def test_no_rows_returns_empty(self) -> None:
        session = _make_session_returning_rows([])

        result = await _get_user_analyses_core(session, uuid.uuid4())

        assert result == {"count": 0, "analyses": []}

    @pytest.mark.asyncio
    async def test_invalid_verdict_returns_error(self) -> None:
        session = _make_session_returning_rows([])

        result = await _get_user_analyses_core(session, uuid.uuid4(), verdict="MAYBE")

        assert result["error"] == "invalid_verdict"
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_verdict_is_normalised_to_uppercase(self) -> None:
        session = _make_session_returning_rows([])

        await _get_user_analyses_core(session, uuid.uuid4(), verdict="buy")

        bound_params = session.execute.call_args.args[1]
        assert bound_params["verdict"] == "BUY"

    @pytest.mark.asyncio
    async def test_populated_rows_are_mapped_correctly(self) -> None:
        job_id = uuid.uuid4()
        row = (
            job_id,
            "Tata Consultancy Services",
            "TCS.NS",
            "NSE",
            "completed",
            _COMPLETED_AT,
            "BUY",
            "8",
            "Rs 4,200 (12-month)",
        )
        session = _make_session_returning_rows([row])

        result = await _get_user_analyses_core(session, uuid.uuid4())

        assert result["count"] == 1
        entry = result["analyses"][0]
        assert entry["analysis_id"] == str(job_id)
        assert entry["company_name"] == "Tata Consultancy Services"
        assert entry["ticker"] == "TCS.NS"
        assert entry["verdict"] == "BUY"
        assert entry["conviction_score"] == 8
        assert isinstance(entry["conviction_score"], int)
        assert entry["completed_at"] == _COMPLETED_AT.isoformat()

    @pytest.mark.asyncio
    async def test_null_verdict_and_conviction_pass_through_as_none(self) -> None:
        row = (
            uuid.uuid4(),
            "Infosys",
            "INFY.NS",
            "NSE",
            "completed",
            _COMPLETED_AT,
            None,
            None,
            None,
        )
        session = _make_session_returning_rows([row])

        result = await _get_user_analyses_core(session, uuid.uuid4())

        entry = result["analyses"][0]
        assert entry["verdict"] is None
        assert entry["conviction_score"] is None

    @pytest.mark.asyncio
    async def test_limit_clamped_to_maximum(self) -> None:
        session = _make_session_returning_rows([])

        await _get_user_analyses_core(session, uuid.uuid4(), limit=999)

        bound_params = session.execute.call_args.args[1]
        assert bound_params["limit"] == MAX_ANALYSES_LIMIT

    @pytest.mark.asyncio
    async def test_limit_clamped_to_minimum_one(self) -> None:
        session = _make_session_returning_rows([])

        await _get_user_analyses_core(session, uuid.uuid4(), limit=0)

        bound_params = session.execute.call_args.args[1]
        assert bound_params["limit"] == 1

    @pytest.mark.asyncio
    async def test_default_limit_used_when_unspecified(self) -> None:
        session = _make_session_returning_rows([])

        await _get_user_analyses_core(session, uuid.uuid4())

        bound_params = session.execute.call_args.args[1]
        assert bound_params["limit"] == DEFAULT_ANALYSES_LIMIT

    @pytest.mark.asyncio
    async def test_query_scoped_to_correct_user_id(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session_returning_rows([])

        await _get_user_analyses_core(session, user_id)

        bound_params = session.execute.call_args.args[1]
        assert bound_params["user_id"] == str(user_id)

    @pytest.mark.asyncio
    async def test_ticker_filter_passed_through_unmodified(self) -> None:
        session = _make_session_returning_rows([])

        await _get_user_analyses_core(session, uuid.uuid4(), ticker="TCS.NS")

        bound_params = session.execute.call_args.args[1]
        assert bound_params["ticker"] == "TCS.NS"

    @pytest.mark.asyncio
    async def test_no_filters_binds_none(self) -> None:
        session = _make_session_returning_rows([])

        await _get_user_analyses_core(session, uuid.uuid4())

        bound_params = session.execute.call_args.args[1]
        assert bound_params["verdict"] is None
        assert bound_params["ticker"] is None


# ---------------------------------------------------------------------------
# _get_memo_by_ticker_core
# ---------------------------------------------------------------------------


class TestGetMemoByTickerCore:
    @pytest.mark.asyncio
    async def test_empty_ticker_returns_error(self) -> None:
        session = _make_session_returning_row(None)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="")

        assert result["error"] == "invalid_ticker"
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_whitespace_only_ticker_returns_error(self) -> None:
        session = _make_session_returning_row(None)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="   ")

        assert result["error"] == "invalid_ticker"

    @pytest.mark.asyncio
    async def test_no_matching_row_returns_not_found(self) -> None:
        session = _make_session_returning_row(None)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="ZZZZ.NS")

        assert result["error"] == "not_found"
        assert result["ticker"] == "ZZZZ.NS"

    @pytest.mark.asyncio
    async def test_row_with_null_snapshot_returns_no_decision(self) -> None:
        job_id = uuid.uuid4()
        row = (job_id, "TCS", "TCS.NS", "NSE", _COMPLETED_AT, None)
        session = _make_session_returning_row(row)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="TCS")

        assert result["error"] == "no_decision"

    @pytest.mark.asyncio
    async def test_row_with_no_decision_key_returns_no_decision(self) -> None:
        job_id = uuid.uuid4()
        row = (job_id, "TCS", "TCS.NS", "NSE", _COMPLETED_AT, {"job_id": "x"})
        session = _make_session_returning_row(row)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="TCS")

        assert result["error"] == "no_decision"

    @pytest.mark.asyncio
    async def test_populated_row_returns_memo_fields(self) -> None:
        job_id = uuid.uuid4()
        row = (
            job_id,
            "Tata Consultancy Services",
            "TCS.NS",
            "NSE",
            _COMPLETED_AT,
            {"decision": _DECISION_FIXTURE},
        )
        session = _make_session_returning_row(row)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="TCS")

        assert result["analysis_id"] == str(job_id)
        assert result["company_name"] == "Tata Consultancy Services"
        assert result["verdict"] == "BUY"
        assert result["conviction_score"] == 8
        assert result["price_target"] == "Rs 4,200 (12-month)"
        assert "durable growth story" in result["executive_summary"]

    @pytest.mark.asyncio
    async def test_psycopg2_style_string_snapshot_is_parsed(self) -> None:
        job_id = uuid.uuid4()
        snapshot_json = json.dumps({"decision": _DECISION_FIXTURE})
        row = (job_id, "TCS", "TCS.NS", "NSE", _COMPLETED_AT, snapshot_json)
        session = _make_session_returning_row(row)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="TCS")

        assert result["verdict"] == "BUY"

    @pytest.mark.asyncio
    async def test_malformed_json_string_snapshot_returns_no_decision(self) -> None:
        job_id = uuid.uuid4()
        row = (job_id, "TCS", "TCS.NS", "NSE", _COMPLETED_AT, "{not valid json")
        session = _make_session_returning_row(row)

        result = await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="TCS")

        assert result["error"] == "no_decision"

    @pytest.mark.asyncio
    async def test_ticker_is_stripped_before_binding(self) -> None:
        session = _make_session_returning_row(None)

        await _get_memo_by_ticker_core(session, uuid.uuid4(), ticker="  TCS.NS  ")

        bound_params = session.execute.call_args.args[1]
        assert bound_params["ticker"] == "TCS.NS"

    @pytest.mark.asyncio
    async def test_query_scoped_to_correct_user_id(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session_returning_row(None)

        await _get_memo_by_ticker_core(session, user_id, ticker="TCS")

        bound_params = session.execute.call_args.args[1]
        assert bound_params["user_id"] == str(user_id)


# ---------------------------------------------------------------------------
# _search_uploaded_documents_core
# ---------------------------------------------------------------------------


class TestSearchUploadedDocumentsCore:
    def test_empty_query_returns_error(self) -> None:
        result = _search_uploaded_documents_core(query="")

        assert result["error"] == "invalid_query"

    def test_whitespace_only_query_returns_error(self) -> None:
        result = _search_uploaded_documents_core(query="   ")

        assert result["error"] == "invalid_query"

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_queries_the_documents_collection(self, mock_search: MagicMock) -> None:
        mock_search.return_value = []

        _search_uploaded_documents_core(query="debt covenant clause")

        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        assert kwargs["collection_name"] == "airp_documents"

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_returns_results_from_semantic_search(self, mock_search: MagicMock) -> None:
        mock_search.return_value = [
            {"id": "doc_1", "document": "...covenant text...", "distance": 0.12},
        ]

        result = _search_uploaded_documents_core(query="debt covenant clause")

        assert result["count"] == 1
        assert result["results"][0]["id"] == "doc_1"

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_empty_results_is_not_an_error(self, mock_search: MagicMock) -> None:
        mock_search.return_value = []

        result = _search_uploaded_documents_core(query="something not present")

        assert "error" not in result
        assert result["count"] == 0
        assert result["results"] == []

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_ticker_passed_through_as_company_filter(
        self, mock_search: MagicMock
    ) -> None:
        mock_search.return_value = []

        _search_uploaded_documents_core(query="margin guidance", ticker="TCS.NS")

        _, kwargs = mock_search.call_args
        assert kwargs["company_filter"] == "TCS.NS"

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_n_results_clamped_to_maximum(self, mock_search: MagicMock) -> None:
        mock_search.return_value = []

        _search_uploaded_documents_core(query="x", n_results=999)

        _, kwargs = mock_search.call_args
        assert kwargs["n_results"] == MAX_SEARCH_RESULTS

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_n_results_clamped_to_minimum_one(self, mock_search: MagicMock) -> None:
        mock_search.return_value = []

        _search_uploaded_documents_core(query="x", n_results=0)

        _, kwargs = mock_search.call_args
        assert kwargs["n_results"] == 1

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_default_n_results_used_when_unspecified(
        self, mock_search: MagicMock
    ) -> None:
        mock_search.return_value = []

        _search_uploaded_documents_core(query="x")

        _, kwargs = mock_search.call_args
        assert kwargs["n_results"] == DEFAULT_SEARCH_RESULTS

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_chroma_client_forwarded(self, mock_search: MagicMock) -> None:
        mock_search.return_value = []
        fake_chroma = MagicMock()

        _search_uploaded_documents_core(query="x", chroma=fake_chroma)

        _, kwargs = mock_search.call_args
        assert kwargs["chroma"] is fake_chroma


# ---------------------------------------------------------------------------
# build_portfolio_tools -- factory wiring
# ---------------------------------------------------------------------------


class TestBuildPortfolioTools:
    def test_returns_three_tools(self) -> None:
        session = _make_session_returning_rows([])
        tools = build_portfolio_tools(session, uuid.uuid4())

        assert len(tools) == 3

    def test_every_tool_is_a_base_tool_instance(self) -> None:
        session = _make_session_returning_rows([])
        tools = build_portfolio_tools(session, uuid.uuid4())

        assert all(isinstance(t, BaseTool) for t in tools)

    def test_tool_names_match_expected(self) -> None:
        session = _make_session_returning_rows([])
        tools = build_portfolio_tools(session, uuid.uuid4())

        names = {t.name for t in tools}
        assert names == {
            "get_user_analyses",
            "get_memo_by_ticker",
            "search_uploaded_documents",
        }

    @pytest.mark.asyncio
    async def test_get_user_analyses_tool_invokes_bound_session_and_user(
        self,
    ) -> None:
        user_id = uuid.uuid4()
        job_id = uuid.uuid4()
        row = (
            job_id,
            "TCS",
            "TCS.NS",
            "NSE",
            "completed",
            _COMPLETED_AT,
            "BUY",
            "8",
            None,
        )
        session = _make_session_returning_rows([row])
        tools = build_portfolio_tools(session, user_id)
        get_user_analyses_tool = next(t for t in tools if t.name == "get_user_analyses")

        result = await get_user_analyses_tool.ainvoke({"limit": 5})

        assert result["count"] == 1
        bound_params = session.execute.call_args.args[1]
        assert bound_params["user_id"] == str(user_id)
        assert bound_params["limit"] == 5

    @pytest.mark.asyncio
    async def test_get_memo_by_ticker_tool_invokes_bound_session_and_user(
        self,
    ) -> None:
        user_id = uuid.uuid4()
        session = _make_session_returning_row(None)
        tools = build_portfolio_tools(session, user_id)
        get_memo_tool = next(t for t in tools if t.name == "get_memo_by_ticker")

        result = await get_memo_tool.ainvoke({"ticker": "TCS.NS"})

        assert result["error"] == "not_found"
        bound_params = session.execute.call_args.args[1]
        assert bound_params["user_id"] == str(user_id)
        assert bound_params["ticker"] == "TCS.NS"

    @patch("backend.tools.portfolio_tools.semantic_search")
    def test_search_uploaded_documents_tool_invokes_semantic_search(
        self, mock_search: MagicMock
    ) -> None:
        mock_search.return_value = [
            {"id": "doc_1", "document": "text", "distance": 0.1}
        ]
        session = _make_session_returning_rows([])
        tools = build_portfolio_tools(session, uuid.uuid4())
        search_tool = next(t for t in tools if t.name == "search_uploaded_documents")

        result = search_tool.invoke({"query": "debt covenant clause"})

        assert result["count"] == 1
        _, kwargs = mock_search.call_args
        assert kwargs["collection_name"] == "airp_documents"

    def test_chroma_client_is_forwarded_from_factory(self) -> None:
        session = _make_session_returning_rows([])
        fake_chroma = MagicMock()
        tools = build_portfolio_tools(session, uuid.uuid4(), chroma=fake_chroma)
        search_tool = next(t for t in tools if t.name == "search_uploaded_documents")

        with patch("backend.tools.portfolio_tools.semantic_search") as mock_search:
            mock_search.return_value = []
            search_tool.invoke({"query": "x"})

        _, kwargs = mock_search.call_args
        assert kwargs["chroma"] is fake_chroma
