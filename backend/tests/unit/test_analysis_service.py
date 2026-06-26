# backend/tests/unit/test_analysis_service.py
"""
Unit tests for T-047 / T-048: backend/services/analysis.py

Test strategy
-------------
1. resolve_company()
     ticker_override path             -- uses override directly
     bare ticker with exchange suffix -- 'TCS.NS' / 'INFY.BO' recognised
     known company name (override table, case-insensitive)
     unknown bare symbol fallback     -- 'WIPRO' -> 'WIPRO.NS'
     unknown free-text fallback       -- spaces stripped, upper-cased
     exchange_override is honoured / invalid value falls back to default
2. get_or_create_company()
     existing row found  -- returns it, no INSERT
     no existing row     -- inserts, commits, refreshes, returns new row
3. create_analysis_job()
     inserts an Analysis row with status='pending', returns it with id set
4. run_analysis_pipeline()
     success path -- builds InvestmentState, invokes the graph via a
                     mocked _invoke_graph_sync (patched module-level),
                     never touches StatePersistenceService.mark_failed
     failure path -- graph invocation raises -> mark_failed is called
                     with the job_id and the exception message
     never raises -- even when mark_failed itself raises, the coroutine
                     completes without propagating
5. compute_progress() (T-048)
     pending (no last_completed_node)  -- 0%, "queued" phase
     each canonical node               -- correct completed_nodes prefix
                                          and monotonically increasing %
     completed status                  -- always 100%, full sequence
     failed status, no checkpoint yet  -- distinct "before start" phase
     failed status, with a checkpoint  -- "Failed after: <phase>" prefix,
                                          same % as the equivalent
                                          running-status checkpoint
     non-canonical node (error_handler,
     sentiment_escalation, a parallel
     research agent name)              -- reported by raw name, 1%,
                                          empty completed_nodes
     monotonicity                       -- percent never decreases when
                                          walking CANONICAL_NODE_SEQUENCE
                                          in order
6. get_analysis_status() (T-048)
     no row for job_id                  -- returns None
     row belongs to a different user    -- returns None (never 403)
     row belongs to the requester       -- returns a populated
                                           AnalysisStatusResult, derived
                                           fields match compute_progress
                                           on the same inputs

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, matching the existing
test_state_persistence.py / test_dependencies_auth.py pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from backend.models.orm import Analysis, Company
from backend.services.analysis import (
    CANONICAL_NODE_SEQUENCE,
    AnalysisStatusResult,
    TickerResolution,
    compute_progress,
    create_analysis_job,
    get_analysis_status,
    get_or_create_company,
    resolve_company,
    run_analysis_pipeline,
)

# ---------------------------------------------------------------------------
# resolve_company()
# ---------------------------------------------------------------------------


class TestResolveCompanyTickerOverride:
    def test_ticker_override_used_directly(self) -> None:
        result = resolve_company("Tata Consultancy Services", ticker_override="TCS")
        assert result.ticker == "TCS.NS"
        assert result.exchange == "NSE"

    def test_ticker_override_with_existing_suffix_is_normalised(self) -> None:
        result = resolve_company("Infosys", ticker_override="INFY.NS")
        assert result.ticker == "INFY.NS"

    def test_ticker_override_with_exchange_override(self) -> None:
        result = resolve_company(
            "Reliance", ticker_override="RELIANCE", exchange_override="BSE"
        )
        assert result.ticker == "RELIANCE.BO"
        assert result.exchange == "BSE"

    def test_company_name_preserved_as_typed(self) -> None:
        result = resolve_company("Tata Consultancy Services", ticker_override="TCS")
        assert result.company_name == "Tata Consultancy Services"


class TestResolveCompanyExplicitSuffix:
    def test_nse_suffix_recognised(self) -> None:
        result = resolve_company("TCS.NS")
        assert result.ticker == "TCS.NS"
        assert result.exchange == "NSE"

    def test_bse_suffix_recognised(self) -> None:
        result = resolve_company("INFY.BO")
        assert result.ticker == "INFY.BO"
        assert result.exchange == "BSE"

    def test_suffix_is_case_insensitive(self) -> None:
        result = resolve_company("tcs.ns")
        assert result.ticker == "TCS.NS"
        assert result.exchange == "NSE"


class TestResolveCompanyNameOverrideTable:
    @pytest.mark.parametrize(
        "company_name,expected_bare",
        [
            ("Tata Consultancy Services", "TCS"),
            ("Infosys", "INFY"),
            ("Infosys Limited", "INFY"),
            ("Reliance Industries", "RELIANCE"),
            ("HDFC Bank", "HDFCBANK"),
            ("ICICI Bank", "ICICIBANK"),
            ("State Bank of India", "SBIN"),
            ("Wipro", "WIPRO"),
        ],
    )
    def test_known_company_name_resolves_to_expected_ticker(
        self, company_name: str, expected_bare: str
    ) -> None:
        result = resolve_company(company_name)
        assert result.ticker == f"{expected_bare}.NS"

    def test_lookup_is_case_insensitive(self) -> None:
        result = resolve_company("TATA CONSULTANCY SERVICES")
        assert result.ticker == "TCS.NS"

    def test_lookup_ignores_surrounding_whitespace(self) -> None:
        result = resolve_company("  Infosys  ")
        assert result.ticker == "INFY.NS"


class TestResolveCompanyFallback:
    def test_unknown_bare_symbol_gets_default_exchange_suffix(self) -> None:
        result = resolve_company("WIPRO")
        assert result.ticker == "WIPRO.NS"
        assert result.exchange == "NSE"

    def test_unknown_free_text_strips_spaces_and_upper_cases(self) -> None:
        result = resolve_company("Some New Company")
        assert result.ticker == "SOMENEWCOMPANY.NS"

    def test_exchange_override_changes_default_suffix(self) -> None:
        result = resolve_company("WIPRO", exchange_override="BSE")
        assert result.ticker == "WIPRO.BO"
        assert result.exchange == "BSE"

    def test_invalid_exchange_override_falls_back_to_default(self) -> None:
        result = resolve_company("WIPRO", exchange_override="NYSE")
        assert result.exchange == "NSE"
        assert result.ticker == "WIPRO.NS"


# ---------------------------------------------------------------------------
# get_or_create_company()
# ---------------------------------------------------------------------------


def _make_session_returning_company(company: Company | None) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=company)
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


class TestGetOrCreateCompany:
    @pytest.mark.asyncio
    async def test_returns_existing_company_without_inserting(self) -> None:
        existing = Company(
            id=uuid.uuid4(),
            name="Tata Consultancy Services",
            ticker="TCS",
            ticker_yf="TCS.NS",
            exchange="NSE",
        )
        session = _make_session_returning_company(existing)
        resolution = TickerResolution(
            company_name="TCS", ticker="TCS.NS", exchange="NSE"
        )

        result = await get_or_create_company(session, resolution)

        assert result is existing
        session.add.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_company_when_none_exists(self) -> None:
        session = _make_session_returning_company(None)
        resolution = TickerResolution(
            company_name="Wipro", ticker="WIPRO.NS", exchange="NSE"
        )

        result = await get_or_create_company(session, resolution)

        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()
        assert result.ticker == "WIPRO"
        assert result.ticker_yf == "WIPRO.NS"
        assert result.exchange == "NSE"

    @pytest.mark.asyncio
    async def test_new_company_uses_bare_ticker_without_suffix(self) -> None:
        session = _make_session_returning_company(None)
        resolution = TickerResolution(
            company_name="Infosys", ticker="INFY.NS", exchange="NSE"
        )

        result = await get_or_create_company(session, resolution)

        assert result.ticker == "INFY"


# ---------------------------------------------------------------------------
# create_analysis_job()
# ---------------------------------------------------------------------------


class TestCreateAnalysisJob:
    @pytest.mark.asyncio
    async def test_inserts_analysis_with_pending_status(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        company = Company(
            id=uuid.uuid4(),
            name="TCS",
            ticker="TCS",
            ticker_yf="TCS.NS",
            exchange="NSE",
        )
        user_id = uuid.uuid4()

        async def _fake_refresh(instance: Any) -> None:
            instance.id = uuid.uuid4()
            instance.status = "pending"

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        result = await create_analysis_job(session, company=company, user_id=user_id)

        assert isinstance(result, Analysis)
        assert result.status == "pending"
        assert result.id is not None
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_links_analysis_to_correct_company_and_user(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        company = Company(
            id=uuid.uuid4(),
            name="TCS",
            ticker="TCS",
            ticker_yf="TCS.NS",
            exchange="NSE",
        )
        user_id = uuid.uuid4()

        result = await create_analysis_job(session, company=company, user_id=user_id)

        assert result.company_id == company.id
        assert result.user_id == user_id


# ---------------------------------------------------------------------------
# run_analysis_pipeline()
# ---------------------------------------------------------------------------


class TestRunAnalysisPipelineSuccess:
    @pytest.mark.asyncio
    async def test_invokes_graph_with_initial_state(self) -> None:
        job_id = uuid.uuid4()
        with (
            patch("backend.services.analysis._invoke_graph_sync") as mock_invoke,
            patch(
                "backend.services.state_persistence.StatePersistenceService"
            ) as mock_svc_cls,
        ):
            mock_invoke.return_value = {"status": "completed"}

            await run_analysis_pipeline(
                job_id=job_id,
                company_name="Tata Consultancy Services",
                ticker="TCS.NS",
                exchange="NSE",
                requested_by="user-123",
            )

            mock_invoke.assert_called_once()
            called_state = mock_invoke.call_args.args[0]
            assert called_state["job_id"] == str(job_id)
            assert called_state["ticker"] == "TCS.NS"
            assert called_state["company_name"] == "Tata Consultancy Services"
            mock_svc_cls.return_value.mark_failed.assert_not_called()


class TestRunAnalysisPipelineFailure:
    @pytest.mark.asyncio
    async def test_marks_job_failed_when_graph_raises(self) -> None:
        job_id = uuid.uuid4()
        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "backend.services.analysis._invoke_graph_sync",
                side_effect=RuntimeError("boom"),
            ),
            patch("backend.db.session.AsyncSessionLocal", mock_session_local),
            patch(
                "backend.services.state_persistence.StatePersistenceService"
            ) as mock_svc_cls,
        ):
            mock_svc_cls.return_value.mark_failed = AsyncMock()

            await run_analysis_pipeline(
                job_id=job_id,
                company_name="TCS",
                ticker="TCS.NS",
                exchange="NSE",
                requested_by="user-123",
            )

            mock_svc_cls.return_value.mark_failed.assert_awaited_once()
            _, kwargs = mock_svc_cls.return_value.mark_failed.call_args
            assert kwargs["job_id"] == str(job_id)
            assert "boom" in kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_never_raises_when_mark_failed_itself_raises(self) -> None:
        job_id = uuid.uuid4()
        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "backend.services.analysis._invoke_graph_sync",
                side_effect=RuntimeError("graph exploded"),
            ),
            patch("backend.db.session.AsyncSessionLocal", mock_session_local),
            patch(
                "backend.services.state_persistence.StatePersistenceService"
            ) as mock_svc_cls,
        ):
            mock_svc_cls.return_value.mark_failed = AsyncMock(
                side_effect=RuntimeError("db also exploded")
            )

            # Must complete without raising -- this call itself is the
            # assertion; pytest fails the test if an exception escapes.
            await run_analysis_pipeline(
                job_id=job_id,
                company_name="TCS",
                ticker="TCS.NS",
                exchange="NSE",
                requested_by="user-123",
            )


# ---------------------------------------------------------------------------
# compute_progress() -- T-048
# ---------------------------------------------------------------------------


class TestComputeProgressPending:
    def test_no_checkpoint_yet_returns_zero_percent(self) -> None:
        phase, completed, percent = compute_progress(
            last_completed_node=None, status="pending"
        )
        assert percent == 0
        assert completed == []
        assert "queued" in phase.lower() or "waiting" in phase.lower()

    def test_empty_string_last_completed_node_treated_as_none(self) -> None:
        # The analyses.last_completed_node column is nullable VARCHAR;
        # an empty string should behave identically to NULL rather than
        # raising or matching CANONICAL_NODE_SEQUENCE by accident.
        phase, completed, percent = compute_progress(
            last_completed_node="", status="pending"
        )
        assert percent == 0
        assert completed == []


class TestComputeProgressRunning:
    @pytest.mark.parametrize(
        "node_name",
        list(CANONICAL_NODE_SEQUENCE),
    )
    def test_each_canonical_node_returns_nonzero_percent(self, node_name: str) -> None:
        _, completed, percent = compute_progress(
            last_completed_node=node_name, status="running"
        )
        assert percent > 0
        assert node_name in completed
        assert completed[-1] == node_name

    def test_completed_nodes_is_exact_prefix_of_canonical_sequence(self) -> None:
        target = CANONICAL_NODE_SEQUENCE[3]
        _, completed, _ = compute_progress(last_completed_node=target, status="running")
        expected_prefix = list(CANONICAL_NODE_SEQUENCE[:4])
        assert completed == expected_prefix

    def test_progress_percent_is_monotonically_nondecreasing(self) -> None:
        percentages = [
            compute_progress(last_completed_node=node, status="running")[2]
            for node in CANONICAL_NODE_SEQUENCE
        ]
        assert percentages == sorted(percentages)

    def test_progress_percent_never_reaches_100_while_running(self) -> None:
        for node in CANONICAL_NODE_SEQUENCE:
            _, _, percent = compute_progress(last_completed_node=node, status="running")
            assert percent <= 99

    def test_last_node_in_sequence_is_99_percent_not_100(self) -> None:
        last_node = CANONICAL_NODE_SEQUENCE[-1]
        _, _, percent = compute_progress(
            last_completed_node=last_node, status="running"
        )
        assert percent == 99

    def test_current_phase_uses_human_readable_label(self) -> None:
        phase, _, _ = compute_progress(
            last_completed_node="valuation_agent", status="running"
        )
        assert phase == "Running DCF valuation and peer comparison"

    def test_error_handler_uses_its_display_label(self) -> None:
        phase, completed, percent = compute_progress(
            last_completed_node="error_handler", status="running"
        )
        assert completed == []
        assert percent == 1
        assert phase == "Recovering from a research data error"

    def test_sentiment_escalation_uses_its_display_label(self) -> None:
        phase, completed, percent = compute_progress(
            last_completed_node="sentiment_escalation", status="running"
        )
        assert completed == []
        assert percent == 1
        assert phase == "Flagging severe negative sentiment for review"

    @pytest.mark.parametrize(
        "research_node",
        ["fundamental_analyst", "technical_analyst"],
    )
    def test_individual_research_agent_falls_back_to_raw_name(
        self, research_node: str
    ) -> None:
        # The 4 parallel research nodes are not individually persisted
        # (only research_join_node is, per _persist_after's docstring),
        # so last_completed_node should never actually hold one of these
        # in production -- but compute_progress must still degrade
        # gracefully rather than raising if it ever does.
        phase, completed, percent = compute_progress(
            last_completed_node=research_node, status="running"
        )
        assert completed == []
        assert percent == 1
        assert phase == research_node


class TestComputeProgressCompleted:
    def test_completed_status_is_always_100_percent(self) -> None:
        _, _, percent = compute_progress(
            last_completed_node="portfolio_manager", status="completed"
        )
        assert percent == 100

    def test_completed_status_returns_full_node_sequence(self) -> None:
        _, completed, _ = compute_progress(
            last_completed_node="portfolio_manager", status="completed"
        )
        assert completed == list(CANONICAL_NODE_SEQUENCE)

    def test_completed_status_overrides_an_earlier_last_completed_node(self) -> None:
        # status='completed' is set as early as portfolio_manager_node
        # (backend.graph.nodes._portfolio_manager_impl) even though
        # report_generator and pdf_export still run afterward -- the
        # response must show 100%/full-sequence regardless of exactly
        # which node happened to write the last checkpoint.
        phase, completed, percent = compute_progress(
            last_completed_node="planner", status="completed"
        )
        assert percent == 100
        assert completed == list(CANONICAL_NODE_SEQUENCE)
        assert phase == "Analysis complete"


class TestComputeProgressFailed:
    def test_failed_with_no_checkpoint_yet(self) -> None:
        phase, completed, percent = compute_progress(
            last_completed_node=None, status="failed"
        )
        assert percent == 0
        assert completed == []
        assert "before" in phase.lower()

    def test_failed_with_a_checkpoint_prefixes_failed_after(self) -> None:
        phase, _, _ = compute_progress(
            last_completed_node="risk_officer", status="failed"
        )
        assert phase.startswith("Failed after:")
        assert "risk" in phase.lower()

    def test_failed_with_a_checkpoint_matches_running_percent(self) -> None:
        node = "contrarian_investor"
        _, _, failed_percent = compute_progress(
            last_completed_node=node, status="failed"
        )
        _, _, running_percent = compute_progress(
            last_completed_node=node, status="running"
        )
        assert failed_percent == running_percent

    def test_failed_status_never_reports_100_percent(self) -> None:
        for node in CANONICAL_NODE_SEQUENCE:
            _, _, percent = compute_progress(last_completed_node=node, status="failed")
            assert percent < 100


# ---------------------------------------------------------------------------
# get_analysis_status() -- T-048
# ---------------------------------------------------------------------------


def _make_status_row(
    user_id: uuid.UUID,
    status: str = "running",
    last_completed_node: Optional[str] = "fundamental_analyst",
    error_message: Optional[str] = None,
    requested_at: Optional[datetime] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> tuple[Any, ...]:
    """Build a fake asyncpg Row as a plain tuple -- indexable like the
    real Result row get_analysis_status reads via row[0]..row[6]."""
    return (
        user_id,
        status,
        last_completed_node,
        error_message,
        requested_at,
        started_at,
        completed_at,
    )


def _make_session_returning_row(row: Optional[tuple[Any, ...]]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=mock_result)
    return session


class TestGetAnalysisStatusNotFound:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_row_exists(self) -> None:
        session = _make_session_returning_row(None)
        result = await get_analysis_status(
            session, job_id=uuid.uuid4(), user_id=uuid.uuid4()
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_row_belongs_to_different_user(self) -> None:
        owner_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        row = _make_status_row(user_id=owner_id)
        session = _make_session_returning_row(row)

        result = await get_analysis_status(
            session, job_id=uuid.uuid4(), user_id=requester_id
        )

        assert result is None


class TestGetAnalysisStatusFound:
    @pytest.mark.asyncio
    async def test_returns_result_for_owning_user(self) -> None:
        user_id = uuid.uuid4()
        job_id = uuid.uuid4()
        requested_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row = _make_status_row(
            user_id=user_id,
            status="running",
            last_completed_node="technical_analyst",
            requested_at=requested_at,
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_status(session, job_id=job_id, user_id=user_id)

        assert isinstance(result, AnalysisStatusResult)
        assert result.job_id == job_id
        assert result.status == "running"
        assert result.requested_at == requested_at

    @pytest.mark.asyncio
    async def test_derived_fields_match_compute_progress_directly(self) -> None:
        user_id = uuid.uuid4()
        row = _make_status_row(
            user_id=user_id, status="running", last_completed_node="risk_officer"
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_status(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        expected_phase, expected_nodes, expected_percent = compute_progress(
            last_completed_node="risk_officer", status="running"
        )
        assert result.current_phase == expected_phase
        assert result.completed_nodes == expected_nodes
        assert result.progress_percent == expected_percent

    @pytest.mark.asyncio
    async def test_error_message_passed_through_for_failed_job(self) -> None:
        user_id = uuid.uuid4()
        row = _make_status_row(
            user_id=user_id,
            status="failed",
            last_completed_node="valuation_agent",
            error_message="yfinance timed out after 3 retries",
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_status(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.status == "failed"
        assert result.error_message == "yfinance timed out after 3 retries"

    @pytest.mark.asyncio
    async def test_completed_job_reports_full_progress(self) -> None:
        user_id = uuid.uuid4()
        row = _make_status_row(
            user_id=user_id,
            status="completed",
            last_completed_node="pdf_export",
            completed_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_status(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.progress_percent == 100
        assert result.completed_nodes == list(CANONICAL_NODE_SEQUENCE)

    @pytest.mark.asyncio
    async def test_queries_with_correct_job_id_parameter(self) -> None:
        user_id = uuid.uuid4()
        job_id = uuid.uuid4()
        row = _make_status_row(user_id=user_id)
        session = _make_session_returning_row(row)

        await get_analysis_status(session, job_id=job_id, user_id=user_id)

        session.execute.assert_awaited_once()
        bound_params = session.execute.call_args.args[1]
        assert bound_params == {"job_id": str(job_id)}
