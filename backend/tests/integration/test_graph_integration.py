# backend/tests/integration/test_graph_integration.py
"""
AIRP -- LangGraph End-to-End Integration Tests (T-035, extended T-044)

Tests the complete investment analysis pipeline from a raw InvestmentState
through the full LangGraph StateGraph to a populated final state.

Acceptance criteria (from project plan):
  - Full pipeline runs in <2 minutes on mock data (T-035)
  - All state fields populated after the pipeline completes (T-035)
  - Error routing verified (fetch_financials empty -> error_handler path;
    negative sentiment -> sentiment_escalation path) (T-035)
  - All Phase 4 agents unit tested (T-044 -- see test_risk_officer.py,
    test_contrarian_investor.py, test_valuation_agent.py,
    test_portfolio_manager.py, test_memo_generator.py, test_pdf_export.py;
    this file covers the INTEGRATION level only)
  - Debate loop integration test runs in <5min on mocks (T-044)
  - debate_rounds[] populated; Portfolio Manager verdict present (T-044)

Why integration tests (not unit tests)?
----------------------------------------
These tests call build_graph().invoke() which runs the REAL compiled
LangGraph graph -- all 15 nodes (T-043 adds pdf_export), real
routing functions, real state merging.  Every agent FUNCTION CALL is
mocked at the nodes.py layer (see "What IS mocked" below); every node
WRAPPER, every routing decision, and every state-merge operation
around those calls is real LangGraph machinery.  This gives us:

  - Proof that the graph compiles and runs end-to-end
  - Proof that LangGraph's parallel fan-out, join barrier, and conditional
    routing all work together correctly on real state
  - Proof that the debate loop (contrarian -> debate_loop ->
    route_after_contrarian) genuinely populates debate_rounds[]
  - Proof that the full pipeline completes well within budget

T-044 fix -- why the four Phase 4 agents are now mocked too
-------------------------------------------------------------
Prior to T-044, only the four research agents were mocked here.
risk_node, contrarian_node, valuation_node, and portfolio_manager_node
all ran with their REAL implementations, every one of which calls
get_llm() (see backend.agents.llm_factory) and constructs a real
ChatGroq client using the fake key from conftest.py's test_settings
fixture ("gsk_test-groq-key-for-unit-tests"). Because addopts = "-m
'not integration'" excludes this file from the default pytest run,
this had never actually been exercised: running `pytest -m
integration` against this file would have attempted a real,
authenticated Groq API call with an invalid key for every test class
that reaches contrarian_node onward, and failed with an auth error
rather than a useful assertion failure. T-044 closes this gap by
mocking run_risk_analysis, run_contrarian_analysis,
run_valuation_analysis, and run_portfolio_manager_decision at the same
nodes.py level the four research agents were already mocked at (see
_run_graph's risk_mock/contrarian_mock/valuation_mock/pm_mock
parameters, all defaulting to realistic "success" mocks so every
pre-existing call site keeps exercising exactly the same
research-agent paths it always did).

report_generator_node (T-042) and pdf_export_node (T-043) are
deliberately NEVER mocked -- both are zero-LLM, zero-network pure
functions by design, so they always run for real here, genuinely
exercising Markdown memo assembly and (best-effort) PDF rendering.

What IS mocked:
  - All four research agent functions (run_fundamental_analysis,
    run_technical_analysis, run_sentiment_analysis, run_macro_analysis)
    -- replaced with fast synchronous functions that return controlled dicts
  - All four Phase 4 agent functions (run_risk_analysis,
    run_contrarian_analysis, run_valuation_analysis,
    run_portfolio_manager_decision) -- T-044, same reasoning as above
  - _run_persist in nodes.py -- prevents any DB connection
  - export_mermaid_diagram in graph.py -- prevents filesystem writes

What is NOT mocked:
  - build_graph() -- real LangGraph compilation
  - graph.invoke() -- real LangGraph execution loop
  - planner_node -- real validation logic
  - research_join_node -- real join barrier
  - error_handler_node -- real flag writing
  - sentiment_escalation_node -- real flag writing
  - debate_loop_node -- real transcript-building logic (T-040); this is
    the node whose output debate_rounds[] populated checks are testing
  - report_generator_node -- real Markdown memo assembly (T-042)
  - pdf_export_node -- real (best-effort) PDF rendering (T-043)
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

TestPhase4DebateEngine (T-044)
    Full pipeline through the real debate engine (contrarian_node ->
    debate_loop_node -> route_after_contrarian) with all eight agent
    functions mocked. Verifies debate_rounds[] is genuinely populated
    (not merely typed as a list), the Portfolio Manager's verdict is
    present and well-formed, the T-042 Markdown memo and T-043 PDF
    export fields are present in the final state, and the whole
    debate-engine path completes in <5 minutes on mocks.

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
* The Contrarian mock's bear_conviction is fixed at 4 (below the
  route-again threshold of 7) so every test in this file takes exactly
  one pass through the debate loop -- enough to prove debate_rounds[]
  gets populated without spending two full LLM-shaped round-trips of
  (mocked, but still real-LangGraph-scheduled) work per test.
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

# T-044 acceptance criterion: "debate loop integration test runs in
# <5min on mocks". Distinct from PIPELINE_TIMEOUT_S above (the stricter
# pre-existing T-035 budget of 2 minutes, which the debate-engine test
# also comfortably satisfies) -- this constant exists so the T-044
# criterion is checked explicitly under its own name, not only as an
# inferred side effect of a different, stricter pre-existing test.
DEBATE_ENGINE_TIMEOUT_S: float = 300.0

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


def _mock_risk_success(state: dict[str, Any]) -> dict[str, Any]:
    """
    Clean Risk Officer output -- low risk, no NEW critical flags.

    T-044: the real run_risk_analysis (backend.agents.risk_officer)
    calls get_llm() and would otherwise attempt a real Groq API call
    using the fake key from conftest.py's test_settings fixture. This
    mock replaces that entire function call, exactly mirroring how the
    four research agents above are mocked.

    IMPORTANT: state["risk_flags"] and state["critical_flags"] have no
    custom LangGraph reducer (plain list[str] fields in state.py), so
    LangGraph's default merge behaviour is last-write-wins, not
    concatenation. The real run_risk_analysis reads whatever flags
    upstream nodes (error_handler_node, sentiment_escalation_node)
    already wrote and merges its own findings on top (see
    backend.agents.risk_officer's _merge_flags helper) rather than
    unconditionally returning a fresh list. This mock must do the same
    merge, or it silently wipes out FUNDAMENTAL_DATA_UNAVAILABLE /
    NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH flags that ran
    earlier in the same pipeline invocation -- exactly the regression
    this comment exists to prevent from recurring.
    """
    upstream_risk_flags = list(state.get("risk_flags") or [])
    upstream_critical_flags = list(state.get("critical_flags") or [])
    return {
        "risk": {
            "agent_name": "risk_officer",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "risk_score": 3,
            "governance_risk": 2,
            "regulatory_risk": 2,
            "financial_risk": 3,
            "concentration_risk": 4,
            "risk_flags": list(upstream_risk_flags),
            "critical_flags": list(upstream_critical_flags),
            "risk_recommendation": "proceed",
            "summary": "Risk score of 3/10; no critical flags identified.",
        },
        "risk_flags": list(upstream_risk_flags),
        "critical_flags": list(upstream_critical_flags),
    }


def _mock_contrarian_success(state: dict[str, Any]) -> dict[str, Any]:
    """
    Clean Contrarian Investor output -- bear_conviction below the
    debate-loop-again threshold (7) so the pipeline proceeds after
    exactly one debate round. This keeps the integration test fast
    (one round, not two) while still genuinely exercising
    debate_loop_node and proving debate_rounds[] gets populated --
    the T-044 acceptance criterion.
    """
    return {
        "contrarian": {
            "agent_name": "contrarian_investor",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "counter_arguments": [
                "Customer concentration in top 5 clients exceeds 40%."
            ],
            "challenged_agents": ["fundamental_analyst"],
            "overlooked_risks": ["Currency exposure on USD-denominated contracts"],
            "bear_conviction": 4,
            "strongest_argument": (
                "Customer concentration exceeds 40% in the top 5 clients, "
                "a structural risk the bull case understates."
            ),
            "summary": "Moderate bear case; concentration risk is the key concern.",
        },
        "debate_round_count": int(state.get("debate_round_count") or 0) + 1,
    }


def _mock_valuation_success(state: dict[str, Any]) -> dict[str, Any]:
    """
    Clean Valuation Agent output -- undervalued, positive margin of
    safety. Replaces the entire run_valuation_analysis call, so the
    real function's own internal fetch_financials/fetch_ratios/
    fetch_stock_price/_fetch_peer_multiples/get_llm calls never fire.
    """
    return {
        "valuation": {
            "agent_name": "valuation_agent",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "intrinsic_value_per_share": 4500.0,
            "current_price": 3800.0,
            "upside_downside_pct": 18.4,
            "valuation_verdict": "undervalued",
            "dcf_wacc_pct": 11.5,
            "dcf_terminal_growth_pct": 4.0,
            "dcf_projection_years": 5,
            "pe_ratio": 28.5,
            "sector_avg_pe": 26.0,
            "pb_ratio": 12.1,
            "sector_avg_pb": 11.0,
            "ev_ebitda": 19.8,
            "sector_avg_ev_ebitda": 18.5,
            "peer_tickers": ["INFY.NS", "WIPRO.NS", "HCLTECH.NS"],
            "premium_discount_to_peers_pct": 5.2,
            "margin_of_safety": "moderate",
            "summary": "DCF implies 18.4% upside to intrinsic value.",
        }
    }


def _mock_portfolio_manager_success(state: dict[str, Any]) -> dict[str, Any]:
    """
    Clean Portfolio Manager decision -- BUY with high conviction.
    Replaces the entire run_portfolio_manager_decision call so the
    real function's get_llm() call never fires.
    """
    decision = {
        "agent_name": "portfolio_manager",
        "analysis_id": state.get("job_id", "unknown"),
        "company_name": state.get("company_name", "unknown"),
        "ticker": state.get("ticker", "unknown"),
        "error": None,
        "verdict": "BUY",
        "conviction_score": 8,
        "price_target": "Rs. 4,500 (12 months)",
        "time_horizon": "12 months",
        "executive_summary": (
            "TCS demonstrates exceptional fundamental quality with a "
            "46.2% ROE and a favourable macro backdrop."
        ),
        "investment_thesis": (
            "The bull case rests on strong ROE, though Round 1 of the "
            "debate raised customer concentration as a tempering factor."
        ),
        "bull_case": "Fundamental score of 9/10 driven by 46.2% ROE.",
        "bear_case": "Customer concentration exceeds 40% per the Contrarian.",
        "risk_summary": "Risk score of 3/10; no critical flags identified.",
        "valuation_summary": "DCF implies 18.4% upside to intrinsic value.",
        "key_risks": ["Customer concentration in top 5 clients exceeds 40%"],
        "key_catalysts": ["Strong deal pipeline reported in latest earnings"],
        "contrarian_response": (
            "Addressing the Contrarian's strongest argument on customer "
            "concentration directly in the final verdict."
        ),
        "debate_rounds_used": 1,
        "agent_weights": {
            "fundamental_analyst": 0.2,
            "valuation_agent": 0.2,
            "risk_officer": 0.15,
            "contrarian_investor": 0.15,
            "technical_analyst": 0.12,
            "macro_economist": 0.1,
            "news_sentiment": 0.08,
        },
        "summary": "TCS: BUY with conviction 8/10.",
    }
    return {
        "decision": decision,
        "final_verdict": decision["verdict"],
        "conviction_score": decision["conviction_score"],
        "price_target": decision["price_target"],
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
    risk_mock: Any = _mock_risk_success,
    contrarian_mock: Any = _mock_contrarian_success,
    valuation_mock: Any = _mock_valuation_success,
    pm_mock: Any = _mock_portfolio_manager_success,
) -> dict[str, Any]:
    """
    Run the full LangGraph pipeline with mocked research agents.

    Patches:
    - run_fundamental_analysis        -> fa_mock
    - run_technical_analysis          -> ta_mock
    - run_sentiment_analysis          -> sa_mock
    - run_macro_analysis              -> ma_mock
    - run_risk_analysis               -> risk_mock        (T-044)
    - run_contrarian_analysis         -> contrarian_mock   (T-044)
    - run_valuation_analysis          -> valuation_mock    (T-044)
    - run_portfolio_manager_decision  -> pm_mock           (T-044)
    - _run_persist                    -> no-op (no DB)
    - export_mermaid_diagram          -> no-op (no filesystem)

    T-044 note: risk_mock/contrarian_mock/valuation_mock/pm_mock all
    default to realistic "success" mocks so every pre-existing call
    site (T-035 through T-043) continues to exercise exactly the same
    research-agent error/escalation paths it always did, while now
    also safely avoiding the real Phase 4 agents' get_llm() calls --
    previously unmocked, which would have attempted a real Groq API
    call using conftest.py's fake test key the first time any test in
    this file actually ran with `-m integration`. report_generator_node
    and pdf_export_node (T-042/T-043) are never mocked -- both are
    zero-LLM, zero-network functions by design, so they always run for
    real here, exercising the genuine Markdown/PDF generation logic.

    Args:
        fa_mock: Mock for fundamental analysis function.
        ta_mock: Mock for technical analysis function.
        sa_mock: Mock for sentiment analysis function.
        ma_mock: Mock for macro analysis function.
        job_id:  Job ID for the initial state.
        ticker:  Ticker symbol to analyse.
        risk_mock: Mock for the Risk Officer agent function.
        contrarian_mock: Mock for the Contrarian Investor agent function.
        valuation_mock: Mock for the Valuation Agent function.
        pm_mock: Mock for the Portfolio Manager decision function.

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
            "backend.graph.nodes.run_risk_analysis",
            side_effect=risk_mock,
        ),
        patch(
            "backend.graph.nodes.run_contrarian_analysis",
            side_effect=contrarian_mock,
        ),
        patch(
            "backend.graph.nodes.run_valuation_analysis",
            side_effect=valuation_mock,
        ),
        patch(
            "backend.graph.nodes.run_portfolio_manager_decision",
            side_effect=pm_mock,
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
# TestPhase4DebateEngine -- T-044 acceptance criteria
# ---------------------------------------------------------------------------
#
# T-044's task description names three specific things to verify at the
# integration level, distinct from what TestHappyPath / TestStateFieldPopulation
# already cover:
#   1. "integration test full debate loop" -- exercised here via the real
#      contrarian_node -> debate_loop_node -> route_after_contrarian edge,
#      with the four Phase 4 agents mocked (see _run_graph's T-044 addition)
#      instead of left to call a real, unmocked LLM.
#   2. "assert debate_rounds populated" -- the existing
#      TestStateFieldPopulation.test_debate_rounds_is_list only asserts
#      *type* (a list, possibly empty). This class asserts the list is
#      non-empty AND that each entry has the real DebateRound shape
#      (round_number, agent_responses, contrarian, completed_at) written
#      by debate_loop_node's _debate_loop_impl.
#   3. "Portfolio Manager verdict present" -- strengthens the existing
#      verdict check with the full decision-shape assertions a memo
#      consumer would actually rely on.
#
# This class also closes a real gap: prior to T-044, nothing in this file
# asserted memo_markdown (T-042) or memo_pdf_path (T-043) at all, despite
# the module docstring's claim of exercising "all 15 nodes".


class TestPhase4DebateEngine:
    """Full pipeline run verifying the Phase 4 debate engine and its
    Investment Memo / PDF export outputs (T-037 through T-043)."""

    @pytest.fixture(autouse=True)
    def _run(self) -> None:
        self.result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
        )

    # -- debate_rounds[] populated (T-044 acceptance criterion) -----------

    def test_debate_rounds_is_non_empty(self) -> None:
        """The mocked Contrarian has bear_conviction=4 (below the
        route-again threshold of 7), so the pipeline takes exactly one
        pass through contrarian_node -> debate_loop_node before
        proceeding -- debate_loop_node always appends one entry per
        pass, so the list must contain at least one round."""
        rounds = cast(list[Any], self.result.get("debate_rounds"))
        assert isinstance(rounds, list)
        assert len(rounds) >= 1, (
            "debate_rounds is empty -- the debate loop did not run, or "
            "its output was not persisted to state"
        )

    def test_debate_round_entry_has_round_number(self) -> None:
        rounds = cast(list[dict[str, Any]], self.result.get("debate_rounds", []))
        assert "round_number" in rounds[0]
        assert isinstance(rounds[0]["round_number"], int)

    def test_debate_round_entry_has_agent_responses(self) -> None:
        rounds = cast(list[dict[str, Any]], self.result.get("debate_rounds", []))
        assert "agent_responses" in rounds[0]
        assert isinstance(rounds[0]["agent_responses"], dict)
        assert len(rounds[0]["agent_responses"]) > 0

    def test_debate_round_entry_has_contrarian_text(self) -> None:
        rounds = cast(list[dict[str, Any]], self.result.get("debate_rounds", []))
        assert "contrarian" in rounds[0]
        assert isinstance(rounds[0]["contrarian"], str)
        assert len(rounds[0]["contrarian"]) > 0

    def test_debate_round_entry_has_completed_at(self) -> None:
        rounds = cast(list[dict[str, Any]], self.result.get("debate_rounds", []))
        assert "completed_at" in rounds[0]

    def test_debate_round_count_matches_rounds_length(self) -> None:
        """debate_round_count is the scalar counter route_after_contrarian
        reads; debate_rounds is the transcript list. For a single-round
        run (this fixture) they must agree."""
        rounds = cast(list[Any], self.result.get("debate_rounds", []))
        count = self.result.get("debate_round_count")
        assert count == len(rounds)

    # -- Portfolio Manager verdict present (T-044 acceptance criterion) ---

    def test_portfolio_manager_decision_present(self) -> None:
        assert self.result.get("decision") is not None

    def test_portfolio_manager_verdict_is_valid(self) -> None:
        decision = cast(dict[str, Any], self.result.get("decision", {}))
        assert decision.get("verdict") in ("BUY", "HOLD", "SELL")

    def test_portfolio_manager_conviction_score_in_range(self) -> None:
        decision = cast(dict[str, Any], self.result.get("decision", {}))
        score = decision.get("conviction_score")
        assert isinstance(score, int)
        assert 1 <= score <= 10

    def test_portfolio_manager_key_risks_present(self) -> None:
        decision = cast(dict[str, Any], self.result.get("decision", {}))
        assert isinstance(decision.get("key_risks"), list)

    def test_portfolio_manager_agent_weights_present(self) -> None:
        decision = cast(dict[str, Any], self.result.get("decision", {}))
        assert isinstance(decision.get("agent_weights"), dict)

    def test_final_verdict_mirrors_decision_verdict(self) -> None:
        """state['final_verdict'] is the flat convenience field written
        alongside the full decision dict -- both must agree."""
        decision = cast(dict[str, Any], self.result.get("decision", {}))
        assert self.result.get("final_verdict") == decision.get("verdict")

    # -- Investment Memo (T-042) and PDF export (T-043) --------------------
    # report_generator_node and pdf_export_node are NEVER mocked in
    # _run_graph -- both are zero-LLM, zero-network functions, so they
    # run for real here, exercising the genuine end-to-end Markdown
    # generation and (best-effort) PDF rendering pipeline.

    def test_memo_markdown_present(self) -> None:
        memo = self.result.get("memo_markdown")
        assert isinstance(memo, str)
        assert len(memo) > 0

    def test_memo_markdown_contains_company_name(self) -> None:
        memo = cast(str, self.result.get("memo_markdown", ""))
        assert _COMPANY in memo

    def test_memo_markdown_contains_verdict(self) -> None:
        decision = cast(dict[str, Any], self.result.get("decision", {}))
        memo = cast(str, self.result.get("memo_markdown", ""))
        assert decision.get("verdict", "") in memo

    def test_memo_pdf_path_key_present(self) -> None:
        """memo_pdf_path must be present in state regardless of whether
        WeasyPrint's system libraries (Pango/Cairo/GDK-Pixbuf) are
        actually installed in the environment running this test --
        pdf_export_node degrades to None rather than failing when they
        are not, by design (see backend.services.pdf_export)."""
        assert "memo_pdf_path" in self.result

    def test_memo_pdf_path_is_none_or_string(self) -> None:
        path_value = self.result.get("memo_pdf_path")
        assert path_value is None or isinstance(path_value, str)

    # -- Pipeline completion despite the additional Phase 4 nodes ----------

    def test_pipeline_still_completes(self) -> None:
        assert self.result.get("status") == "completed"

    def test_pipeline_reaches_pdf_export_as_current_node(self) -> None:
        """pdf_export is the final node before END (T-043) -- current_node
        should reflect that it was the last node to run."""
        assert self.result.get("current_node") == "pdf_export"

    # -- T-044 acceptance criterion: debate loop runs in <5min on mocks ---

    def test_debate_engine_pipeline_under_five_minutes(self) -> None:
        """
        Explicit T-044 acceptance criterion check, measured independently
        of the autouse fixture's invocation above (a fresh _run_graph
        call here so this test's timing is not affected by whatever the
        test collection/fixture-setup overhead for other tests in this
        class happened to be).

        All four research agents AND all four Phase 4 agents are mocked
        to return instantly -- the measured time reflects only LangGraph
        orchestration overhead across all 15 nodes, not any agent or
        LLM latency.
        """
        start: float = time.perf_counter()

        result = _run_graph(
            fa_mock=_mock_fundamental_success,
            ta_mock=_mock_technical_success,
            sa_mock=_mock_sentiment_success,
            ma_mock=_mock_macro_success,
            job_id="t044-debate-engine-timing-001",
        )

        elapsed: float = time.perf_counter() - start

        assert result.get("status") == "completed", (
            f"Debate engine pipeline did not complete "
            f"(status={result.get('status')})"
        )
        assert elapsed < DEBATE_ENGINE_TIMEOUT_S, (
            f"Debate engine pipeline took {elapsed:.1f}s -- "
            f"must be <{DEBATE_ENGINE_TIMEOUT_S}s (T-044 acceptance criterion)"
        )


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
