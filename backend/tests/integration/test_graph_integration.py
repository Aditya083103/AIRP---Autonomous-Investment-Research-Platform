# backend/tests/integration/test_graph_integration.py
"""
AIRP -- LangGraph End-to-End Integration Tests (T-035)

Tests the complete investment analysis pipeline from a raw InvestmentState
through the full LangGraph StateGraph to a populated final state.

Acceptance criteria (from project plan):
  - Full pipeline runs in <2 minutes on mock data
  - All state fields populated after the pipeline completes
  - Error routing verified (fetch_financials empty -> error_handler path;
    negative sentiment -> sentiment_escalation path)

Why integration tests (not unit tests)?
----------------------------------------
These tests call build_graph().invoke() which runs the REAL compiled
LangGraph graph -- all 15 nodes (T-043 adds pdf_export), real
routing functions, real state merging.  The only mocking is at the
agent layer (the four research agents and the state persistence
layer).  This gives us:

  - Proof that the graph compiles and runs end-to-end
  - Proof that LangGraph's parallel fan-out, join barrier, and conditional
    routing all work together correctly on real state
  - Proof that the full pipeline completes in <2 minutes

What IS mocked:
  - All four research agent functions (run_fundamental_analysis,
    run_technical_analysis, run_sentiment_analysis, run_macro_analysis)
    -- replaced with fast synchronous functions that return controlled dicts
  - _run_persist in nodes.py -- prevents any DB connection
  - export_mermaid_diagram in graph.py -- prevents filesystem writes

What is NOT mocked:
  - build_graph() -- real LangGraph compilation
  - graph.invoke() -- real LangGraph execution loop
  - planner_node -- real validation logic
  - research_join_node -- real join barrier
  - error_handler_node -- real flag writing
  - sentiment_escalation_node -- real flag writing
  - contrarian_node, risk_node, valuation_node, portfolio_manager_node
    (stubs but real functions -- Phase 4 logic added in T-037 to T-044)
  - route_after_planner, route_after_research, route_after_contrarian
    -- real routing functions with real threshold logic

Test classes
------------
TestHappyPath
    Full pipeline on clean mock data -- verifies all state fields populated.

TestErrorRoutingFundamentals
    Mocks fetch_financials failure -- verifies error_handler node runs
    and FUNDAMENTAL_DATA_UNAVAILABLE flag is set.

TestErrorRoutingNegativeSentiment
    Mocks sentiment_score < -0.8 -- verifies sentiment_escalation runs
    and NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH flag is set.

TestPipelineTiming
    Full pipeline completes in <2 minutes (<120 seconds).

TestPlannerAbortPath
    Planner aborts when ticker is missing.

TestStateFieldPopulation
    Every expected state field is present and has the correct type
    after a full pipeline run.

TestMultipleRuns
    Two independent invocations produce independent results (no shared
    state between runs).

All tests are marked @pytest.mark.integration so they are excluded from
the default pytest run (addopts = \"-m 'not integration'\") and must be
run explicitly:

    ENVIRONMENT=test python -m pytest -m integration -v

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare type: ignore -- cast() and explicit annotations only.
* All mock agent functions are fast (< 5ms each) so timing tests
  measure LangGraph overhead, not agent latency.
* build_graph() is called fresh per test class (not shared) to avoid
  lru_cache pollution from get_compiled_graph().
* Mocks are applied at the function level, not the module level, so
  tests remain independent.
"""
import os
import time
from typing import Any, cast
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.graph.graph import build_graph  # noqa: E402
from backend.graph.routing import ESCALATION_FLAG_NEGATIVE_SENTIMENT  # noqa: E402
from backend.graph.state import InvestmentState, make_initial_state  # noqa: E402

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

_JOB_ID = "t035-integration-test-job-001"
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"
_EXCHANGE = "NSE"

# Maximum acceptable pipeline duration in seconds (acceptance criterion).
PIPELINE_TIMEOUT_S: float = 120.0

# ---------------------------------------------------------------------------
# Mock agent output factories
# ---------------------------------------------------------------------------
# These return the same shape as the real agent functions but instantly,
# with no external API calls.  They simulate a healthy analysis run.


def _mock_fundamental_success(state: dict[str, Any]) -> dict[str, Any]:
    """Clean fundamental output -- no error."""
    return {
        "fundamental": {
            "agent_name": "fundamental_analyst",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "revenue_growth_score": 8,
            "margin_score": 7,
            "debt_score": 9,
            "fcf_score": 8,
            "balance_sheet_score": 8,
            "overall_score": 8,
            "recommendation": "STRONG_BUY",
            "summary": "Strong fundamentals across all dimensions.",
        }
    }


def _mock_fundamental_empty_financials(state: dict[str, Any]) -> dict[str, Any]:
    """Fundamental output with fetch_financials error (error routing test)."""
    return {
        "fundamental": {
            "agent_name": "fundamental_analyst",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": "fetch_financials returned empty: Alpha Vantage 429",
            "revenue_growth_score": 0,
            "margin_score": 0,
            "debt_score": 0,
            "fcf_score": 0,
            "balance_sheet_score": 0,
            "overall_score": 0,
            "recommendation": "INSUFFICIENT_DATA",
            "summary": "Cannot analyse: financial data unavailable.",
        }
    }


def _mock_technical_success(state: dict[str, Any]) -> dict[str, Any]:
    """Clean technical output."""
    return {
        "technical": {
            "agent_name": "technical_analyst",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "signal": "BUY",
            "rsi": 58.4,
            "ma_50": 3820.0,
            "ma_200": 3650.0,
            "price_vs_52w_high": 0.93,
            "momentum_score": 7,
            "trend_score": 8,
            "overall_score": 7,
            "summary": "Positive technical setup with bullish momentum.",
        }
    }


def _mock_sentiment_success(state: dict[str, Any]) -> dict[str, Any]:
    """Clean sentiment output -- mildly positive."""
    return {
        "sentiment": {
            "agent_name": "sentiment_analyst",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "sentiment_score": 0.35,
            "article_count": 28,
            "red_flags": [],
            "positive_themes": ["strong Q3 guidance", "large deal wins"],
            "negative_themes": ["attrition concerns"],
            "summary": "Moderately positive news sentiment.",
        }
    }


def _mock_sentiment_negative(state: dict[str, Any]) -> dict[str, Any]:
    """Sentiment output with score < -0.8 (escalation routing test)."""
    return {
        "sentiment": {
            "agent_name": "sentiment_analyst",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "sentiment_score": -0.92,
            "article_count": 45,
            "red_flags": [
                "SEBI investigation",
                "CFO resignation",
                "earnings restatement",
            ],
            "positive_themes": [],
            "negative_themes": ["fraud allegations", "regulatory action"],
            "summary": "Severely negative news environment.",
        }
    }


def _mock_macro_success(state: dict[str, Any]) -> dict[str, Any]:
    """Clean macro output."""
    return {
        "macro": {
            "agent_name": "macro_economist",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "macro_environment": "favourable",
            "rbi_rate_stance": "neutral",
            "gdp_growth_score": 7,
            "inflation_score": 6,
            "sector_tailwind_score": 8,
            "overall_score": 7,
            "summary": "Favourable macro backdrop for IT sector.",
        }
    }


# ---------------------------------------------------------------------------
# Shared graph invocation helper
# ---------------------------------------------------------------------------


def _run_graph(
    fa_mock: Any,
    ta_mock: Any,
    sa_mock: Any,
    ma_mock: Any,
    job_id: str = _JOB_ID,
    ticker: str = _TICKER,
) -> dict[str, Any]:
    """
    Run the full LangGraph pipeline with mocked research agents.

    Patches:
    - run_fundamental_analysis -> fa_mock
    - run_technical_analysis   -> ta_mock
    - run_sentiment_analysis   -> sa_mock
    - run_macro_analysis       -> ma_mock
    - _run_persist             -> no-op (no DB)
    - export_mermaid_diagram   -> no-op (no filesystem)

    Args:
        fa_mock: Mock for fundamental analysis function.
        ta_mock: Mock for technical analysis function.
        sa_mock: Mock for sentiment analysis function.
        ma_mock: Mock for macro analysis function.
        job_id:  Job ID for the initial state.
        ticker:  Ticker symbol to analyse.

    Returns:
        The final state dict after pipeline completion.
    """
    initial: InvestmentState = make_initial_state(
        job_id=job_id,
        company_name=_COMPANY,
        ticker=ticker,
        exchange=_EXCHANGE,
        raw_query="TCS",
    )

    with (
        patch(
            "backend.graph.nodes.run_fundamental_analysis",
            side_effect=fa_mock,
        ),
        patch(
            "backend.graph.nodes.run_technical_analysis",
            side_effect=ta_mock,
        ),
        patch(
            "backend.graph.nodes.run_sentiment_analysis",
            side_effect=sa_mock,
        ),
        patch(
            "backend.graph.nodes.run_macro_analysis",
            side_effect=ma_mock,
        ),
        patch(
            "backend.graph.nodes._run_persist",
            side_effect=lambda *a, **kw: None,
        ),
        patch(
            "backend.graph.graph.export_mermaid_diagram",
            side_effect=lambda *a, **kw: None,
        ),
    ):
        compiled = build_graph()
        result: Any = compiled.invoke(dict(initial))

    return cast(dict[str, Any], result)


# ---------------------------------------------------------------------------
# TestHappyPath -- full pipeline on clean mock data
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Full pipeline run with clean agent outputs. Happy path."""

    @pytest.fixture(autouse=True)
    def _run(self) -> None:
        self.result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
        )

    # -- Pipeline completion -----------------------------------------------

    def test_pipeline_completes(self) -> None:
        assert self.result is not None

    def test_status_is_completed(self) -> None:
        assert self.result.get("status") == "completed"

    def test_job_id_preserved(self) -> None:
        assert self.result.get("job_id") == _JOB_ID

    def test_ticker_preserved(self) -> None:
        assert self.result.get("ticker") == _TICKER

    def test_company_name_preserved(self) -> None:
        assert self.result.get("company_name") == _COMPANY

    # -- Research agent outputs populated ---------------------------------

    def test_fundamental_output_present(self) -> None:
        assert "fundamental" in self.result
        assert self.result["fundamental"] is not None

    def test_technical_output_present(self) -> None:
        assert "technical" in self.result
        assert self.result["technical"] is not None

    def test_sentiment_output_present(self) -> None:
        assert "sentiment" in self.result
        assert self.result["sentiment"] is not None

    def test_macro_output_present(self) -> None:
        assert "macro" in self.result
        assert self.result["macro"] is not None

    # -- Advanced agent stub outputs present ------------------------------

    def test_contrarian_output_present(self) -> None:
        assert "contrarian" in self.result
        assert self.result["contrarian"] is not None

    def test_risk_output_present(self) -> None:
        assert "risk" in self.result
        assert self.result["risk"] is not None

    def test_valuation_output_present(self) -> None:
        assert "valuation" in self.result
        assert self.result["valuation"] is not None

    def test_decision_output_present(self) -> None:
        assert "decision" in self.result
        assert self.result["decision"] is not None

    # -- Final outputs ----------------------------------------------------

    def test_final_verdict_present(self) -> None:
        assert "final_verdict" in self.result
        verdict = self.result.get("final_verdict")
        assert verdict in ("BUY", "HOLD", "SELL")

    def test_conviction_score_present(self) -> None:
        score = self.result.get("conviction_score")
        assert isinstance(score, int)
        assert 1 <= score <= 10

    def test_completed_at_set(self) -> None:
        assert "completed_at" in self.result
        assert self.result.get("completed_at") is not None

    def test_no_pipeline_error(self) -> None:
        assert self.result.get("pipeline_error") is None

    # -- Research agent content accuracy ----------------------------------

    def test_fundamental_agent_name_correct(self) -> None:
        fundamental = self.result.get("fundamental", {})
        assert isinstance(fundamental, dict)
        assert fundamental.get("agent_name") == "fundamental_analyst"

    def test_fundamental_no_error(self) -> None:
        fundamental = self.result.get("fundamental", {})
        assert isinstance(fundamental, dict)
        assert fundamental.get("error") is None

    def test_technical_signal_is_buy(self) -> None:
        technical = self.result.get("technical", {})
        assert isinstance(technical, dict)
        assert technical.get("signal") == "BUY"

    def test_sentiment_score_matches_mock(self) -> None:
        sentiment = self.result.get("sentiment", {})
        assert isinstance(sentiment, dict)
        score = sentiment.get("sentiment_score")
        assert isinstance(score, float)
        assert abs(score - 0.35) < 0.01

    def test_macro_environment_matches_mock(self) -> None:
        macro = self.result.get("macro", {})
        assert isinstance(macro, dict)
        assert macro.get("macro_environment") == "favourable"

    # -- Normal path: no error flags --------------------------------------

    def test_no_fundamental_data_unavailable_flag(self) -> None:
        risk_flags = self.result.get("risk_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" not in risk_flags

    def test_no_negative_sentiment_flag(self) -> None:
        risk_flags = self.result.get("risk_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT not in risk_flags


# ---------------------------------------------------------------------------
# TestErrorRoutingFundamentals -- fetch_financials returns empty
# ---------------------------------------------------------------------------


class TestErrorRoutingFundamentals:
    """
    Error routing test: fundamental agent returns fetch_financials error.
    The error_handler node must run and set FUNDAMENTAL_DATA_UNAVAILABLE flag.
    """

    @pytest.fixture(autouse=True)
    def _run(self) -> None:
        self.result = _run_graph(
            fa_mock=_mock_fundamental_empty_financials,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-error-routing-fund-001",
        )

    # -- Pipeline still completes -----------------------------------------

    def test_pipeline_still_completes(self) -> None:
        """Error path must NOT abort the pipeline."""
        assert self.result is not None

    def test_status_is_completed(self) -> None:
        """Even with degraded fundamentals, the pipeline reaches completion."""
        assert self.result.get("status") == "completed"

    # -- Error flag set correctly -----------------------------------------

    def test_fundamental_data_unavailable_in_risk_flags(self) -> None:
        risk_flags = self.result.get("risk_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in risk_flags

    def test_fundamental_data_unavailable_in_critical_flags(self) -> None:
        critical_flags = self.result.get("critical_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in critical_flags

    # -- Pipeline error message written -----------------------------------

    def test_pipeline_error_message_set(self) -> None:
        """error_handler writes a human-readable degraded-pipeline message."""
        pipeline_error = self.result.get("pipeline_error")
        assert pipeline_error is not None
        assert len(str(pipeline_error)) > 0

    def test_pipeline_error_mentions_fundamental_data(self) -> None:
        pipeline_error = str(self.result.get("pipeline_error", ""))
        assert "Fundamental data unavailable" in pipeline_error

    def test_pipeline_error_mentions_ticker(self) -> None:
        pipeline_error = str(self.result.get("pipeline_error", ""))
        assert _TICKER in pipeline_error

    # -- Committee still produces a verdict (degraded but present) --------

    def test_decision_still_produced(self) -> None:
        assert "decision" in self.result
        assert self.result["decision"] is not None

    def test_final_verdict_still_present(self) -> None:
        verdict = self.result.get("final_verdict")
        assert verdict in ("BUY", "HOLD", "SELL")

    # -- Other agents still ran -------------------------------------------

    def test_technical_still_ran(self) -> None:
        technical = self.result.get("technical", {})
        assert isinstance(technical, dict)
        assert technical.get("agent_name") == "technical_analyst"

    def test_sentiment_still_ran(self) -> None:
        sentiment = self.result.get("sentiment", {})
        assert isinstance(sentiment, dict)
        assert sentiment.get("agent_name") == "sentiment_analyst"

    def test_macro_still_ran(self) -> None:
        macro = self.result.get("macro", {})
        assert isinstance(macro, dict)
        assert macro.get("agent_name") == "macro_economist"

    # -- No sentiment escalation flag (clean sentiment) -------------------

    def test_no_sentiment_escalation_flag(self) -> None:
        risk_flags = self.result.get("risk_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT not in risk_flags


# ---------------------------------------------------------------------------
# TestErrorRoutingNegativeSentiment -- sentiment_score < -0.8
# ---------------------------------------------------------------------------


class TestErrorRoutingNegativeSentiment:
    """
    Escalation routing test: sentiment agent returns score < -0.8.
    The sentiment_escalation node must run and set the escalation flag.
    """

    @pytest.fixture(autouse=True)
    def _run(self) -> None:
        self.result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_negative,
            ma_mock=_mock_macro_success,
            job_id="t035-escalation-routing-001",
        )

    # -- Pipeline completes -----------------------------------------------

    def test_pipeline_completes(self) -> None:
        assert self.result is not None

    def test_status_is_completed(self) -> None:
        assert self.result.get("status") == "completed"

    # -- Escalation flag set correctly ------------------------------------

    def test_negative_sentiment_flag_in_risk_flags(self) -> None:
        risk_flags = self.result.get("risk_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTINEL in risk_flags

    def test_negative_sentiment_flag_in_critical_flags(self) -> None:
        critical_flags = self.result.get("critical_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTINEL in critical_flags

    # -- No fundamental error (clean fundamentals) ------------------------

    def test_no_fundamental_error_flag(self) -> None:
        risk_flags = self.result.get("risk_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" not in risk_flags

    def test_no_pipeline_error_message(self) -> None:
        """Escalation is a flag, not an error -- no pipeline_error set."""
        pipeline_error = self.result.get("pipeline_error")
        assert pipeline_error is None or pipeline_error == ""

    # -- All agents still ran ---------------------------------------------

    def test_fundamental_ran(self) -> None:
        fundamental = self.result.get("fundamental", {})
        assert isinstance(fundamental, dict)
        assert fundamental.get("agent_name") == "fundamental_analyst"

    def test_decision_produced(self) -> None:
        assert "decision" in self.result

    def test_final_verdict_present(self) -> None:
        verdict = self.result.get("final_verdict")
        assert verdict in ("BUY", "HOLD", "SELL")

    # -- Sentiment score preserved in state -------------------------------

    def test_sentiment_score_below_threshold(self) -> None:
        sentiment = self.result.get("sentiment", {})
        assert isinstance(sentiment, dict)
        score = sentiment.get("sentiment_score")
        assert isinstance(score, float)
        assert score < -0.8


# ---------------------------------------------------------------------------
# TestPipelineTiming -- acceptance criterion: <2 minutes
# ---------------------------------------------------------------------------


class TestPipelineTiming:
    """Full pipeline run must complete in under 120 seconds on mock data."""

    def test_full_pipeline_under_two_minutes(self) -> None:
        """
        Acceptance criterion: 'Full pipeline runs in <2min on mock data'.

        All four research agents are mocked to return instantly (<5ms each).
        The measured time reflects only LangGraph orchestration overhead --
        parallel scheduling, state merging, and conditional routing.

        If this test fails it means LangGraph itself has become unacceptably
        slow or there is an unexpected blocking call somewhere in the graph.
        """
        start: float = time.perf_counter()

        result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-timing-test-001",
        )

        elapsed: float = time.perf_counter() - start

        assert (
            result.get("status") == "completed"
        ), f"Pipeline did not complete (status={result.get('status')})"
        assert (
            elapsed < PIPELINE_TIMEOUT_S
        ), f"Pipeline took {elapsed:.1f}s -- must be <{PIPELINE_TIMEOUT_S}s"

    def test_error_path_under_two_minutes(self) -> None:
        """Error routing path must also complete under the timing budget."""
        start: float = time.perf_counter()

        result = _run_graph(
            fa_mock=_mock_fundamental_empty_financials,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-timing-error-001",
        )

        elapsed: float = time.perf_counter() - start

        assert result is not None
        assert elapsed < PIPELINE_TIMEOUT_S, f"Error-path pipeline took {elapsed:.1f}s"

    def test_escalation_path_under_two_minutes(self) -> None:
        """Escalation routing path must also complete under the timing budget."""
        start: float = time.perf_counter()

        result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_negative,
            ma_mock=_mock_macro_success,
            job_id="t035-timing-escalation-001",
        )

        elapsed: float = time.perf_counter() - start

        assert result is not None
        assert (
            elapsed < PIPELINE_TIMEOUT_S
        ), f"Escalation-path pipeline took {elapsed:.1f}s"


# ---------------------------------------------------------------------------
# TestPlannerAbortPath -- planner aborts on missing ticker
# ---------------------------------------------------------------------------


class TestPlannerAbortPath:
    """Planner must abort (status='failed') when required fields are missing."""

    def _run_with_bad_state(self, ticker: str = "") -> dict[str, Any]:
        """Run graph with an intentionally bad initial state."""
        bad_state: InvestmentState = make_initial_state(
            job_id="t035-abort-test-001",
            company_name="Test Company",
            ticker=ticker,
            exchange=_EXCHANGE,
            raw_query="test",
        )

        with (
            patch(
                "backend.graph.nodes._run_persist",
                side_effect=lambda *a, **kw: None,
            ),
            patch(
                "backend.graph.graph.export_mermaid_diagram",
                side_effect=lambda *a, **kw: None,
            ),
        ):
            compiled = build_graph()
            result: Any = compiled.invoke(dict(bad_state))

        return cast(dict[str, Any], result)

    def test_abort_on_empty_ticker(self) -> None:
        result = self._run_with_bad_state(ticker="")
        # Planner sets status=failed and routes to END
        assert result.get("status") == "failed"

    def test_abort_sets_pipeline_error(self) -> None:
        result = self._run_with_bad_state(ticker="")
        pipeline_error = result.get("pipeline_error")
        assert pipeline_error is not None
        assert len(str(pipeline_error)) > 0

    def test_abort_no_fundamental_output(self) -> None:
        """On abort, no research agent should have run."""
        result = self._run_with_bad_state(ticker="")
        # fundamental should be absent (not populated) on abort
        assert result.get("fundamental") is None


# ---------------------------------------------------------------------------
# TestStateFieldPopulation -- every expected field present after completion
# ---------------------------------------------------------------------------


class TestStateFieldPopulation:
    """
    After a successful pipeline run, every expected state field must be
    present and have the correct type.
    """

    @pytest.fixture(autouse=True)
    def _run(self) -> None:
        self.result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-field-population-001",
        )

    # -- Identity fields (set by make_initial_state, preserved) -----------

    def test_job_id_is_string(self) -> None:
        assert isinstance(self.result.get("job_id"), str)

    def test_ticker_is_string(self) -> None:
        assert isinstance(self.result.get("ticker"), str)

    def test_company_name_is_string(self) -> None:
        assert isinstance(self.result.get("company_name"), str)

    def test_exchange_is_string(self) -> None:
        assert isinstance(self.result.get("exchange"), str)

    def test_raw_query_is_string(self) -> None:
        assert isinstance(self.result.get("raw_query"), str)

    def test_version_is_int(self) -> None:
        assert isinstance(self.result.get("version"), int)

    def test_requested_at_is_string(self) -> None:
        assert isinstance(self.result.get("requested_at"), str)

    # -- Pipeline status fields -------------------------------------------

    def test_status_is_string(self) -> None:
        assert isinstance(self.result.get("status"), str)

    def test_started_at_is_string(self) -> None:
        # set by planner node
        assert isinstance(self.result.get("started_at"), str)

    def test_completed_at_is_string(self) -> None:
        assert isinstance(self.result.get("completed_at"), str)

    # -- Research agent output fields (dicts) -----------------------------

    def test_fundamental_is_dict(self) -> None:
        assert isinstance(self.result.get("fundamental"), dict)

    def test_technical_is_dict(self) -> None:
        assert isinstance(self.result.get("technical"), dict)

    def test_sentiment_is_dict(self) -> None:
        assert isinstance(self.result.get("sentiment"), dict)

    def test_macro_is_dict(self) -> None:
        assert isinstance(self.result.get("macro"), dict)

    # -- Advanced agent output fields (dicts) -----------------------------

    def test_contrarian_is_dict(self) -> None:
        assert isinstance(self.result.get("contrarian"), dict)

    def test_risk_is_dict(self) -> None:
        assert isinstance(self.result.get("risk"), dict)

    def test_valuation_is_dict(self) -> None:
        assert isinstance(self.result.get("valuation"), dict)

    def test_decision_is_dict(self) -> None:
        assert isinstance(self.result.get("decision"), dict)

    # -- Final output fields ----------------------------------------------

    def test_final_verdict_is_string(self) -> None:
        verdict = self.result.get("final_verdict")
        assert isinstance(verdict, str)
        assert verdict in ("BUY", "HOLD", "SELL")

    def test_conviction_score_is_int(self) -> None:
        score = self.result.get("conviction_score")
        assert isinstance(score, int)

    # -- Collection fields always present ---------------------------------

    def test_risk_flags_is_list(self) -> None:
        assert isinstance(self.result.get("risk_flags"), list)

    def test_critical_flags_is_list(self) -> None:
        assert isinstance(self.result.get("critical_flags"), list)

    def test_debate_rounds_is_list(self) -> None:
        assert isinstance(self.result.get("debate_rounds"), list)

    def test_debate_round_count_is_int(self) -> None:
        count = self.result.get("debate_round_count")
        assert isinstance(count, int)
        assert count >= 0

    def test_langsmith_run_ids_is_dict(self) -> None:
        assert isinstance(self.result.get("langsmith_run_ids"), dict)

    # -- Each agent output has required keys ------------------------------

    def test_fundamental_has_agent_name(self) -> None:
        fa = cast(dict[str, Any], self.result.get("fundamental", {}))
        assert "agent_name" in fa

    def test_fundamental_has_analysis_id(self) -> None:
        fa = cast(dict[str, Any], self.result.get("fundamental", {}))
        assert "analysis_id" in fa

    def test_technical_has_agent_name(self) -> None:
        ta = cast(dict[str, Any], self.result.get("technical", {}))
        assert "agent_name" in ta

    def test_decision_has_verdict(self) -> None:
        dec = cast(dict[str, Any], self.result.get("decision", {}))
        assert "verdict" in dec
        assert dec["verdict"] in ("BUY", "HOLD", "SELL")

    def test_decision_has_conviction_score(self) -> None:
        dec = cast(dict[str, Any], self.result.get("decision", {}))
        assert "conviction_score" in dec


# ---------------------------------------------------------------------------
# TestMultipleRuns -- independent results per invocation
# ---------------------------------------------------------------------------


class TestMultipleRuns:
    """Two independent graph invocations produce independent results."""

    def test_two_runs_have_different_job_ids(self) -> None:
        result_a = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-multi-run-a",
        )
        result_b = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-multi-run-b",
        )
        assert result_a.get("job_id") == "t035-multi-run-a"
        assert result_b.get("job_id") == "t035-multi-run-b"

    def test_two_runs_both_complete(self) -> None:
        for i in range(2):
            result = _run_graph(
                fa_mock=_mock_fundamental_success,
                ta_mock=_mock_technical_success,
                sa_mock=_mock_sentiment_success,
                ma_mock=_mock_macro_success,
                job_id=f"t035-multi-run-{i}",
            )
            assert result.get("status") == "completed", f"Run {i} did not complete"

    def test_error_and_happy_path_independent(self) -> None:
        """Running error path then happy path does not contaminate results."""
        error_result = _run_graph(
            fa_mock=_mock_fundamental_empty_financials,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-error-first",
        )
        happy_result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t035-happy-second",
        )

        # Error run has the flag
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in error_result.get("risk_flags", [])
        # Happy run does NOT
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" not in happy_result.get("risk_flags", [])


# ---------------------------------------------------------------------------
# Module-level constant used in tests (alias for readability)
# ---------------------------------------------------------------------------

ESCALATION_FLAG_NEGATIVE_SENTINEL: str = ESCALATION_FLAG_NEGATIVE_SENTIMENT
