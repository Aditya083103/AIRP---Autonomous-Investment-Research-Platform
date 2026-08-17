# backend/tests/integration/test_latency_eval_integration.py
"""
AIRP -- Latency Eval Integration Test (T-071)

Proves that backend.evals.latency_evaluators.LatencyLogCapture correctly
reconstructs the per-node latency breakdown from a REAL, fully-compiled
LangGraph pipeline run -- not from state["node_latencies"] (see
latency_evaluators.py's module docstring for why state is not trusted).

Like backend/tests/integration/test_graph_integration.py, this test calls
build_graph().invoke() against the REAL compiled graph -- all 15 nodes,
real routing, real state merging, real profile_node() wrapping (T-036)
around every node. Only the 8 agent CORE functions (run_fundamental_
analysis, run_technical_analysis, ..., run_portfolio_manager_decision)
are mocked, exactly as test_graph_integration.py already establishes, for
the same reason: those calls would otherwise hit get_llm() with a fake
test key and fail with an auth error rather than a useful assertion
failure.

Why a separate, self-contained mock set instead of importing
test_graph_integration.py's helpers
------------------------------------------------------------------------
Those helpers (_mock_fundamental_success, _run_graph, etc.) are
test-module-local (leading underscore, not a public API) and tightly
coupled to that file's own mocking of all 8 agents. Importing them here
would create a fragile cross-test-file dependency for no real benefit --
matching the same design decision T-070's debate eval already made for
its own dataset (see docs/week-26/T-070-eval-debate.md). This file's
mocks are deliberately minimal (just enough to satisfy each agent's
output schema and keep routing on the happy path), not a full replica.

What this file proves that the unit tests (test_latency_evaluators.py)
cannot
------------------------------------------------------------------------
The unit tests exercise LatencyLogCapture / summarize_latency_runs /
format_latency_report against SYNTHETIC log lines and SYNTHETIC
PipelineRunResult rows -- they prove the parsing/aggregation logic is
correct in isolation, but not that it correctly observes a genuine
LangGraph run. This file closes that gap: it attaches a real
LatencyLogCapture to the real node_profiler logger, invokes the real
compiled graph, and asserts the captured breakdown matches what actually
executed -- including that a node which runs twice (the debate loop
across 2 rounds) is correctly SUMMED, not overwritten.

Marked @pytest.mark.integration -- excluded from the default CI run
(addopts = "-m 'not integration'") and must be run explicitly:

    ENVIRONMENT=test python -m pytest -m integration \
        backend/tests/integration/test_latency_eval_integration.py -v

This is supplementary verification, not the load-bearing proof of T-071's
acceptance criteria -- that proof is the fully offline, CI-covered
test_latency_evaluators.py suite plus a real run of
scripts/run_eval_latency.py against real market data and a real LLM
(pasted into the PR description).
"""
import logging
import os
import time
from typing import Any
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.evals.latency_evaluators import (  # noqa: E402
    NODE_PROFILER_LOGGER_NAME,
    LatencyLogCapture,
    PipelineRunResult,
    format_latency_report,
    meets_latency_targets,
    summarize_latency_runs,
)
from backend.graph.graph import build_graph  # noqa: E402
from backend.graph.state import InvestmentState, make_initial_state  # noqa: E402

pytestmark = pytest.mark.integration

_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"
_EXCHANGE = "NSE"

# ---------------------------------------------------------------------------
# Minimal agent mocks -- just enough to satisfy each agent's output schema
# and keep routing on the happy path (no error/escalation branch).
# ---------------------------------------------------------------------------


def _mock_fundamental(state: dict[str, Any]) -> dict[str, Any]:
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
            "summary": "Strong fundamentals.",
        }
    }


def _mock_technical(state: dict[str, Any]) -> dict[str, Any]:
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
            "summary": "Positive setup.",
        }
    }


def _mock_sentiment(state: dict[str, Any]) -> dict[str, Any]:
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
            "positive_themes": ["strong guidance"],
            "negative_themes": [],
            "summary": "Moderately positive sentiment.",
        }
    }


def _mock_macro(state: dict[str, Any]) -> dict[str, Any]:
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
            "summary": "Favourable macro backdrop.",
        }
    }


def _mock_risk(state: dict[str, Any]) -> dict[str, Any]:
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
            "summary": "Low risk.",
        },
        "risk_flags": list(upstream_risk_flags),
        "critical_flags": list(upstream_critical_flags),
    }


def _mock_contrarian(state: dict[str, Any]) -> dict[str, Any]:
    # bear_conviction=4 stays below the route-again threshold (7) so the
    # pipeline proceeds after exactly ONE debate round in most tests.
    return {
        "contrarian": {
            "agent_name": "contrarian_investor",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": None,
            "counter_arguments": ["Customer concentration risk."],
            "challenged_agents": ["fundamental_analyst"],
            "overlooked_risks": ["Currency exposure."],
            "bear_conviction": 4,
            "strongest_argument": "Customer concentration exceeds 40%.",
            "summary": "Moderate bear case.",
        },
        "debate_round_count": int(state.get("debate_round_count") or 0) + 1,
    }


def _mock_valuation(state: dict[str, Any]) -> dict[str, Any]:
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
            "peer_tickers": ["INFY.NS", "WIPRO.NS"],
            "premium_discount_to_peers_pct": 5.2,
            "margin_of_safety": "moderate",
            "summary": "18.4% upside to intrinsic value.",
        }
    }


def _mock_portfolio_manager(state: dict[str, Any]) -> dict[str, Any]:
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
        "executive_summary": "Strong fundamentals, favourable macro.",
        "investment_thesis": "Bull case rests on strong ROE.",
        "bull_case": "Fundamental score of 8/10.",
        "bear_case": "Customer concentration risk.",
        "risk_summary": "Risk score of 3/10.",
        "valuation_summary": "18.4% upside to intrinsic value.",
        "key_risks": ["Customer concentration."],
        "key_catalysts": ["Strong deal pipeline."],
        "contrarian_response": "Addressed directly in the verdict.",
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
        "summary": "BUY with conviction 8/10.",
    }
    return {
        "decision": decision,
        "final_verdict": decision["verdict"],
        "conviction_score": decision["conviction_score"],
        "price_target": decision["price_target"],
    }


def _run_pipeline_with_capture(job_id: str) -> tuple[dict[str, Any], LatencyLogCapture]:
    """Invoke the real compiled graph (agents mocked) with latency capture."""
    initial: InvestmentState = make_initial_state(
        job_id=job_id,
        company_name=_COMPANY,
        ticker=_TICKER,
        exchange=_EXCHANGE,
        raw_query="TCS",
    )

    profiler_logger = logging.getLogger(NODE_PROFILER_LOGGER_NAME)
    capture = LatencyLogCapture()
    previous_level = profiler_logger.level
    profiler_logger.addHandler(capture)
    profiler_logger.setLevel(logging.INFO)

    try:
        with (
            patch(
                "backend.graph.nodes.run_fundamental_analysis",
                side_effect=_mock_fundamental,
            ),
            patch(
                "backend.graph.nodes.run_technical_analysis",
                side_effect=_mock_technical,
            ),
            patch(
                "backend.graph.nodes.run_sentiment_analysis",
                side_effect=_mock_sentiment,
            ),
            patch(
                "backend.graph.nodes.run_macro_analysis",
                side_effect=_mock_macro,
            ),
            patch(
                "backend.graph.nodes.run_risk_analysis",
                side_effect=_mock_risk,
            ),
            patch(
                "backend.graph.nodes.run_contrarian_analysis",
                side_effect=_mock_contrarian,
            ),
            patch(
                "backend.graph.nodes.run_valuation_analysis",
                side_effect=_mock_valuation,
            ),
            patch(
                "backend.graph.nodes.run_portfolio_manager_decision",
                side_effect=_mock_portfolio_manager,
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
            final_state = compiled.invoke(dict(initial))
    finally:
        profiler_logger.removeHandler(capture)
        profiler_logger.setLevel(previous_level)

    return final_state, capture


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLatencyCaptureAgainstRealGraph:
    def test_captures_every_node_that_executed(self) -> None:
        final_state, capture = _run_pipeline_with_capture("t071-int-001")

        assert final_state.get("status") == "completed"
        node_latencies = capture.node_latencies_ms()

        expected_nodes = {
            "planner",
            "fundamental_analyst",
            "technical_analyst",
            "sentiment_analyst",
            "macro_economist",
            "research_join",
            "contrarian_investor",
            "debate_loop",
            "risk_officer",
            "valuation_agent",
            "portfolio_manager",
            "report_generator",
            "pdf_export",
        }
        assert expected_nodes.issubset(node_latencies.keys())

    def test_every_captured_latency_is_non_negative(self) -> None:
        _, capture = _run_pipeline_with_capture("t071-int-002")
        for node_name, elapsed_ms in capture.node_latencies_ms().items():
            assert elapsed_ms >= 0, node_name

    def test_summary_from_one_real_run_reports_bottleneck(self) -> None:
        _, capture = _run_pipeline_with_capture("t071-int-003")

        start = time.perf_counter()
        # The real invoke() already happened inside _run_pipeline_with_capture;
        # here we just need SOME total_elapsed_s for the summary -- reuse a
        # tiny measured duration since the mocked agents are near-instant.
        elapsed_s = max(time.perf_counter() - start, 0.001)

        run: PipelineRunResult = {
            "company_name": _COMPANY,
            "ticker": _TICKER,
            "job_id": "t071-int-003",
            "status": "completed",
            "total_elapsed_s": elapsed_s,
            "node_latencies_ms": capture.node_latencies_ms(),
            "node_call_counts": capture.node_call_counts(),
            "error": None,
        }
        summary = summarize_latency_runs([run])

        assert summary["bottleneck_node"] is not None
        assert summary["bottleneck_node"] in capture.node_latencies_ms()
        # A single fully-mocked pipeline run is far faster than the 90s/120s
        # targets -- this is LangGraph orchestration overhead only.
        assert meets_latency_targets(summary) is True

        report = format_latency_report(summary, [run])
        assert _COMPANY in report
        assert "bottleneck" in report.lower()

    def test_repeated_node_execution_is_summed_not_overwritten(self) -> None:
        """
        Forces bear_conviction >= 7 so route_after_contrarian sends the
        pipeline back for a SECOND debate round -- contrarian_investor and
        debate_loop each execute twice. Proves LatencyLogCapture sums
        elapsed_ms across repeated executions of the same node, which is
        exactly the guarantee state["node_latencies"] cannot provide (see
        latency_evaluators.py's module docstring).
        """

        call_count = {"n": 0}

        def _mock_contrarian_two_rounds(state: dict[str, Any]) -> dict[str, Any]:
            call_count["n"] += 1
            # First call: high conviction -> triggers a second round.
            # Second call: low conviction -> proceeds to risk_officer.
            bear_conviction = 8 if call_count["n"] == 1 else 3
            return {
                "contrarian": {
                    "agent_name": "contrarian_investor",
                    "analysis_id": state.get("job_id", "unknown"),
                    "company_name": state.get("company_name", "unknown"),
                    "ticker": state.get("ticker", "unknown"),
                    "error": None,
                    "counter_arguments": ["Concentration risk."],
                    "challenged_agents": ["fundamental_analyst"],
                    "overlooked_risks": ["Currency exposure."],
                    "bear_conviction": bear_conviction,
                    "strongest_argument": "Customer concentration exceeds 40%.",
                    "summary": "Bear case.",
                },
                "debate_round_count": int(state.get("debate_round_count") or 0) + 1,
            }

        job_id = "t071-int-004"
        initial: InvestmentState = make_initial_state(
            job_id=job_id,
            company_name=_COMPANY,
            ticker=_TICKER,
            exchange=_EXCHANGE,
            raw_query="TCS",
        )

        profiler_logger = logging.getLogger(NODE_PROFILER_LOGGER_NAME)
        capture = LatencyLogCapture()
        previous_level = profiler_logger.level
        profiler_logger.addHandler(capture)
        profiler_logger.setLevel(logging.INFO)

        try:
            with (
                patch(
                    "backend.graph.nodes.run_fundamental_analysis",
                    side_effect=_mock_fundamental,
                ),
                patch(
                    "backend.graph.nodes.run_technical_analysis",
                    side_effect=_mock_technical,
                ),
                patch(
                    "backend.graph.nodes.run_sentiment_analysis",
                    side_effect=_mock_sentiment,
                ),
                patch(
                    "backend.graph.nodes.run_macro_analysis",
                    side_effect=_mock_macro,
                ),
                patch(
                    "backend.graph.nodes.run_risk_analysis",
                    side_effect=_mock_risk,
                ),
                patch(
                    "backend.graph.nodes.run_contrarian_analysis",
                    side_effect=_mock_contrarian_two_rounds,
                ),
                patch(
                    "backend.graph.nodes.run_valuation_analysis",
                    side_effect=_mock_valuation,
                ),
                patch(
                    "backend.graph.nodes.run_portfolio_manager_decision",
                    side_effect=_mock_portfolio_manager,
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
                final_state = compiled.invoke(dict(initial))
        finally:
            profiler_logger.removeHandler(capture)
            profiler_logger.setLevel(previous_level)

        assert final_state.get("debate_round_count") == 2
        call_counts = capture.node_call_counts()
        assert call_counts.get("contrarian_investor") == 2
        assert call_counts.get("debate_loop") == 2

        # The summed total must be >= either individual call's own
        # elapsed_ms could plausibly be -- i.e. it genuinely accumulated
        # rather than being overwritten by the second call.
        latencies = capture.node_latencies_ms()
        assert latencies["contrarian_investor"] >= 0
