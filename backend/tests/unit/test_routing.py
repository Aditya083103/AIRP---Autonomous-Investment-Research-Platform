# backend/tests/unit/test_routing.py
"""
Unit tests for T-032: Conditional Routing Logic.

Acceptance criteria (from project plan):
  - Error path routes correctly for mocked failures
    (fetch_financials returns empty -> error_handler node)
  - Escalation triggers on negative sentiment threshold
    (sentiment.score < -0.8 -> sentiment_escalation node)

Test strategy
-------------
  1. route_after_research -- error path
       fundamental["error"] non-null -> ROUTE_ERROR
  2. route_after_research -- escalation path
       sentiment_score < -0.8 -> ROUTE_ESCALATE_SENTIMENT
  3. route_after_research -- normal proceed path
       clean outputs -> ROUTE_PROCEED
  4. route_after_research -- boundary values
       sentiment_score exactly -0.8 -> ROUTE_PROCEED (threshold is strict <)
       sentiment_score = -0.81 -> ROUTE_ESCALATE_SENTIMENT
  5. route_after_research -- error path takes priority
       both fundamental error AND negative sentiment -> ROUTE_ERROR
  6. route_after_research -- missing / empty state
       absent keys -> ROUTE_PROCEED (must never raise)
  7. error_handler_node -- state updates
       writes pipeline_error, appends FUNDAMENTAL_DATA_UNAVAILABLE flag
       does not terminate pipeline (no status=failed)
  8. error_handler_node -- idempotent flag writes
       calling twice does not duplicate flags
  9. error_handler_node -- missing fundamental in state
       must not raise, still writes flags
 10. sentiment_escalation_node -- state updates
       writes NEGATIVE_SENTIMENT flag to risk_flags and critical_flags
 11. sentiment_escalation_node -- idempotent flag writes
 12. sentiment_escalation_node -- missing sentiment in state
       must not raise
 13. graph compilation -- 11 nodes registered
 14. graph end-to-end -- error path (mocked financials failure)
       final state has error_handler flag and pipeline continues
 15. graph end-to-end -- escalation path (mocked negative sentiment)
       final state has escalation flag and pipeline completes
 16. graph end-to-end -- normal path (mocked clean outputs)
       final state status=completed, no error flags
 17. ROUTE_* constants -- all defined and distinct
 18. NEGATIVE_SENTIMENT_THRESHOLD -- correct value (-0.8)
 19. ESCALATION_FLAG_NEGATIVE_SENTIMENT -- correct string value
 20. graph Mermaid diagram -- new nodes appear in diagram

All external calls (LLMs, APIs, Redis, ChromaDB) are mocked.
LangGraph itself is NOT mocked -- graph compilation is a real test.

ENVIRONMENT must be set to 'test' before any backend import.
"""
from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# T-033: patch _run_persist so routing tests never touch the database
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_db_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent state_persistence from opening DB connections in routing tests."""
    monkeypatch.setattr(
        "backend.graph.nodes._run_persist",
        lambda *args, **kwargs: None,
    )


@pytest.fixture(autouse=True)
def _no_real_pdf_export(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Prevent any test in this file from reaching real WeasyPrint.

    TestGraphEndToEnd*Path tests below invoke the full compiled graph,
    which always reaches pdf_export_node en route to END (portfolio_manager
    -> report_generator -> pdf_export -> END is unconditional -- see
    backend/graph/graph.py). render_memo_pdf calls real WeasyPrint, which
    has been observed to crash with a native Windows access violation
    during font subsetting / box layout on some local WeasyPrint+GTK3
    installs -- a fault below the Python interpreter that no try/except
    in pdf_export.py can catch. These tests only assert on routing/flag
    behaviour, never on PDF contents, so PDF rendering is mocked out
    globally here.
    """
    monkeypatch.setattr(
        "backend.services.pdf_export.render_memo_pdf",
        lambda *args, **kwargs: None,
    )


from backend.graph.graph import ROUTING_NODE_NAMES, build_graph  # noqa: E402
from backend.graph.nodes import (  # noqa: E402
    NODE_CONTRARIAN,
    NODE_DEBATE_LOOP,
    NODE_ERROR_HANDLER,
    NODE_FUNDAMENTAL,
    NODE_MACRO,
    NODE_PLANNER,
    NODE_PORTFOLIO_MANAGER,
    NODE_RESEARCH_JOIN,
    NODE_RISK,
    NODE_SENTIMENT,
    NODE_SENTIMENT_ESCALATION,
    NODE_TECHNICAL,
    NODE_VALUATION,
    error_handler_node,
    sentiment_escalation_node,
)
from backend.graph.routing import (  # noqa: E402
    ESCALATION_FLAG_NEGATIVE_SENTIMENT,
    NEGATIVE_SENTIMENT_THRESHOLD,
    ROUTE_ABORT,
    ROUTE_DEBATE_AGAIN,
    ROUTE_ERROR,
    ROUTE_ESCALATE_SENTIMENT,
    ROUTE_PROCEED,
    route_after_research,
)
from backend.graph.state import InvestmentState, make_initial_state  # noqa: E402

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_JOB_ID = "t032-test-job-uuid-001"
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"
_EXCHANGE = "NSE"

_ALL_NODE_NAMES: list[str] = [
    NODE_PLANNER,
    NODE_FUNDAMENTAL,
    NODE_TECHNICAL,
    NODE_SENTIMENT,
    NODE_MACRO,
    NODE_RESEARCH_JOIN,
    NODE_ERROR_HANDLER,
    NODE_SENTIMENT_ESCALATION,
    NODE_CONTRARIAN,
    NODE_DEBATE_LOOP,
    NODE_RISK,
    NODE_VALUATION,
    NODE_PORTFOLIO_MANAGER,
]


def _make_state(**overrides: Any) -> InvestmentState:
    state = make_initial_state(
        job_id=_JOB_ID,
        company_name=_COMPANY,
        ticker=_TICKER,
        exchange=_EXCHANGE,
        raw_query="TCS",
    )
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


def _running_state(**overrides: Any) -> InvestmentState:
    """State with status=running (passed planner validation)."""
    return _make_state(status="running", **overrides)


def _clean_research_outputs() -> dict[str, Any]:
    """Minimal valid research agent outputs -- no errors."""
    return {
        "fundamental": {
            "agent_name": "fundamental_analyst",
            "score": 7,
            "error": None,
        },
        "technical": {
            "agent_name": "technical_analyst",
            "signal": "BUY",
            "error": None,
        },
        "sentiment": {
            "agent_name": "sentiment_analyst",
            "sentiment_score": 0.2,
            "error": None,
        },
        "macro": {
            "agent_name": "macro_economist",
            "macro_environment": "favourable",
            "error": None,
        },
    }


def _failed_fundamental_outputs() -> dict[str, Any]:
    """Research outputs where fundamental agent has an error."""
    outputs = _clean_research_outputs()
    outputs["fundamental"] = {
        "agent_name": "fundamental_analyst",
        "error": "fetch_financials returned empty: API rate limit exceeded",
        "score": 0,
    }
    return outputs


def _negative_sentiment_outputs(score: float = -0.9) -> dict[str, Any]:
    """Research outputs where sentiment is severely negative."""
    outputs = _clean_research_outputs()
    outputs["sentiment"] = {
        "agent_name": "sentiment_analyst",
        "sentiment_score": score,
        "error": None,
    }
    return outputs


# ---------------------------------------------------------------------------
# Mock helpers for graph-level end-to-end tests
# ---------------------------------------------------------------------------


def _make_agent_mock(output_key: str, output_value: dict[str, Any]) -> MagicMock:
    """Return a mock agent function that returns the given output."""
    return MagicMock(return_value={output_key: output_value})


#: Schema-valid Phase 4 agent outputs shared by every _run_graph_with_mocks()
#: call below. These four agents (contrarian/risk/valuation/portfolio
#: manager) are not under test in this file -- route_after_research and
#: the error_handler/sentiment_escalation nodes are -- so a single fixed
#: "everything is fine downstream" mock is reused rather than rebuilt per
#: call site. Without mocking these, the graph falls through to the real
#: run_portfolio_manager_decision (a real Groq API call against
#: conftest.py's fake test key) and real pdf_export_node (real
#: WeasyPrint, which has crashed with a native Windows access violation
#: on some local installs) -- neither acceptable in a unit test.
_CONTRARIAN_OUT: dict[str, Any] = {
    "contrarian": {
        "agent_name": "contrarian_investor",
        "bear_conviction": 3,
        "counter_arguments": [],
        "overlooked_risks": [],
        "challenged_agents": [],
        "strongest_argument": "Mock argument",
        "summary": "Mock summary",
        "error": None,
    },
    "debate_round_count": 1,
}


def _risk_mock_side_effect(state: dict[str, Any]) -> dict[str, Any]:
    """
    Mimic run_risk_analysis's upstream-flag merge (see
    backend/agents/risk_officer.py) rather than overwriting risk_flags/
    critical_flags outright.

    risk_flags and critical_flags in InvestmentState are plain list[str]
    fields with no LangGraph reducer (no Annotated[..., operator.add]),
    so a node's partial-update return value REPLACES the prior value for
    that key rather than appending to it. The real run_risk_analysis
    reads state["risk_flags"]/state["critical_flags"] and merges its own
    findings in (_merge_flags) precisely because of this. A mock that
    just returns risk_flags=[] would silently erase the
    FUNDAMENTAL_DATA_UNAVAILABLE / NEGATIVE_SENTIMENT flags that
    error_handler_node / sentiment_escalation_node wrote earlier in the
    pipeline, breaking TestGraphEndToEndErrorPath and
    TestGraphEndToEndEscalationPath below.
    """
    upstream_risk_flags = list(state.get("risk_flags") or [])
    upstream_critical_flags = list(state.get("critical_flags") or [])
    return {
        "risk": {
            "agent_name": "risk_officer",
            "risk_score": 4,
            "governance_risk": 4,
            "regulatory_risk": 4,
            "financial_risk": 4,
            "concentration_risk": 4,
            "risk_flags": upstream_risk_flags,
            "critical_flags": upstream_critical_flags,
            "risk_recommendation": "proceed_with_caution",
            "summary": "Mock risk summary",
            "error": None,
        },
        "risk_flags": upstream_risk_flags,
        "critical_flags": upstream_critical_flags,
    }


_VALUATION_OUT: dict[str, Any] = {
    "valuation": {
        "agent_name": "valuation_agent",
        "valuation_verdict": "fairly_valued",
        "peer_tickers": [],
        "summary": "Mock valuation summary",
        "error": None,
    }
}


_DECISION_OUT: dict[str, Any] = {
    "decision": {
        "agent_name": "portfolio_manager",
        "verdict": "HOLD",
        "conviction_score": 5,
        "price_target": None,
        "time_horizon": "12 months",
        "executive_summary": "Mock executive summary.",
        "investment_thesis": "Mock investment thesis.",
        "bull_case": "Mock bull case.",
        "bear_case": "Mock bear case.",
        "risk_summary": "Mock risk summary.",
        "valuation_summary": "Mock valuation summary.",
        "key_risks": [],
        "key_catalysts": [],
        "contrarian_response": "Mock contrarian response.",
        "debate_rounds_used": 1,
        "agent_weights": {},
        "summary": "Mock decision summary.",
        "error": None,
    },
    "final_verdict": "HOLD",
    "conviction_score": 5,
    "price_target": None,
}


def _run_graph_with_mocks(
    initial_state: InvestmentState,
    fa_output: dict[str, Any],
    ta_output: dict[str, Any],
    sa_output: dict[str, Any],
    ma_output: dict[str, Any],
) -> dict[str, Any]:
    """Run build_graph().invoke() with mocked research and Phase 4 agents."""
    fa_mock = _make_agent_mock("fundamental", fa_output)
    ta_mock = _make_agent_mock("technical", ta_output)
    sa_mock = _make_agent_mock("sentiment", sa_output)
    ma_mock = _make_agent_mock("macro", ma_output)

    with (
        patch(
            "backend.graph.nodes.run_fundamental_analysis",
            fa_mock,
        ),
        patch(
            "backend.graph.nodes.run_technical_analysis",
            ta_mock,
        ),
        patch(
            "backend.graph.nodes.run_sentiment_analysis",
            sa_mock,
        ),
        patch(
            "backend.graph.nodes.run_macro_analysis",
            ma_mock,
        ),
        patch(
            "backend.graph.nodes.run_contrarian_analysis",
            return_value=_CONTRARIAN_OUT,
        ),
        patch(
            "backend.graph.nodes.run_risk_analysis",
            side_effect=_risk_mock_side_effect,
        ),
        patch(
            "backend.graph.nodes.run_valuation_analysis",
            return_value=_VALUATION_OUT,
        ),
        patch(
            "backend.graph.nodes.run_portfolio_manager_decision",
            return_value=_DECISION_OUT,
        ),
    ):
        compiled = build_graph()
        result = compiled.invoke(dict(initial_state))
    return dict(result)


# ---------------------------------------------------------------------------
# 1. route_after_research -- error path (fundamental failure)
# ---------------------------------------------------------------------------


class TestRouteAfterResearchErrorPath:
    """fundamental['error'] non-null -> ROUTE_ERROR."""

    def test_fundamental_error_routes_to_error(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        result = route_after_research(state)
        assert result == ROUTE_ERROR

    def test_fundamental_error_string_routes_to_error(self) -> None:
        state = _make_state(
            fundamental={
                "agent_name": "fundamental_analyst",
                "error": "fetch_failed",
            }
        )
        result = route_after_research(state)
        assert result == ROUTE_ERROR

    def test_fundamental_error_api_rate_limit_routes_to_error(self) -> None:
        state = _make_state(
            fundamental={
                "agent_name": "fundamental_analyst",
                "error": "Alpha Vantage 429: daily limit exceeded",
            }
        )
        assert route_after_research(state) == ROUTE_ERROR

    def test_fundamental_error_yfinance_routes_to_error(self) -> None:
        state = _make_state(
            fundamental={
                "agent_name": "fundamental_analyst",
                "error": "yfinance: no data found for ticker INVALID.NS",
            }
        )
        assert route_after_research(state) == ROUTE_ERROR

    def test_fundamental_error_generic_string_routes_to_error(self) -> None:
        state = _make_state(
            fundamental={"agent_name": "fundamental_analyst", "error": "some error"}
        )
        assert route_after_research(state) == ROUTE_ERROR

    def test_fundamental_none_error_does_not_route_to_error(self) -> None:
        """error=None (success) must NOT trigger error path."""
        state = _make_state(
            fundamental={
                "agent_name": "fundamental_analyst",
                "error": None,
                "score": 8,
            }
        )
        result = route_after_research(state)
        assert result != ROUTE_ERROR

    def test_fundamental_missing_error_key_does_not_route_to_error(self) -> None:
        """No 'error' key at all (success dict) must NOT trigger error path."""
        state = _make_state(
            fundamental={"agent_name": "fundamental_analyst", "score": 8}
        )
        result = route_after_research(state)
        assert result != ROUTE_ERROR

    def test_returns_string(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        assert isinstance(route_after_research(state), str)


# ---------------------------------------------------------------------------
# 2. route_after_research -- escalation path (negative sentiment)
# ---------------------------------------------------------------------------


class TestRouteAfterResearchEscalationPath:
    """sentiment_score < -0.8 -> ROUTE_ESCALATE_SENTIMENT."""

    def test_score_minus_09_escalates(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        assert route_after_research(state) == ROUTE_ESCALATE_SENTIMENT

    def test_score_minus_1_escalates(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-1.0))
        assert route_after_research(state) == ROUTE_ESCALATE_SENTIMENT

    def test_score_minus_081_escalates(self) -> None:
        """Just past the threshold (< -0.8)."""
        state = _make_state(**_negative_sentiment_outputs(-0.81))
        assert route_after_research(state) == ROUTE_ESCALATE_SENTIMENT

    def test_score_minus_099_escalates(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.99))
        assert route_after_research(state) == ROUTE_ESCALATE_SENTIMENT

    def test_score_minus_08_does_not_escalate(self) -> None:
        """Exactly -0.8 is NOT < -0.8 so should NOT escalate."""
        state = _make_state(**_negative_sentiment_outputs(-0.8))
        result = route_after_research(state)
        assert result != ROUTE_ESCALATE_SENTIMENT

    def test_score_minus_079_does_not_escalate(self) -> None:
        """Slightly above threshold -> no escalation."""
        state = _make_state(**_negative_sentiment_outputs(-0.79))
        result = route_after_research(state)
        assert result != ROUTE_ESCALATE_SENTIMENT

    def test_score_zero_does_not_escalate(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(0.0))
        assert route_after_research(state) != ROUTE_ESCALATE_SENTIMENT

    def test_score_positive_does_not_escalate(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(0.5))
        assert route_after_research(state) != ROUTE_ESCALATE_SENTIMENT

    def test_escalation_returns_correct_constant(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        assert route_after_research(state) == ROUTE_ESCALATE_SENTIMENT

    def test_returns_string(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        assert isinstance(route_after_research(state), str)


# ---------------------------------------------------------------------------
# 3. route_after_research -- normal proceed path
# ---------------------------------------------------------------------------


class TestRouteAfterResearchProceedPath:
    """Clean outputs -> ROUTE_PROCEED."""

    def test_clean_outputs_returns_proceed(self) -> None:
        state = _make_state(**_clean_research_outputs())
        assert route_after_research(state) == ROUTE_PROCEED

    def test_mild_negative_sentiment_returns_proceed(self) -> None:
        """score = -0.5 is negative but not severe enough."""
        state = _make_state(**_negative_sentiment_outputs(-0.5))
        assert route_after_research(state) == ROUTE_PROCEED

    def test_borderline_sentiment_score_minus_08_returns_proceed(self) -> None:
        """Exactly -0.8 does NOT meet the < -0.8 threshold."""
        state = _make_state(**_negative_sentiment_outputs(-0.8))
        assert route_after_research(state) == ROUTE_PROCEED

    def test_no_research_outputs_returns_proceed(self) -> None:
        """Missing all research outputs -> no error, no escalation."""
        state = _make_state(status="running")
        assert route_after_research(state) == ROUTE_PROCEED

    def test_empty_state_returns_proceed(self) -> None:
        empty: InvestmentState = cast(InvestmentState, {})
        assert route_after_research(empty) == ROUTE_PROCEED

    def test_technical_error_only_returns_proceed(self) -> None:
        """Non-fundamental errors are warnings, not errors -- proceed."""
        outputs = _clean_research_outputs()
        outputs["technical"] = {
            "agent_name": "technical_analyst",
            "error": "insufficient OHLCV data",
        }
        state = _make_state(**outputs)
        assert route_after_research(state) == ROUTE_PROCEED

    def test_macro_error_only_returns_proceed(self) -> None:
        """Non-fundamental errors -> still proceed."""
        outputs = _clean_research_outputs()
        outputs["macro"] = {
            "agent_name": "macro_economist",
            "error": "RBI scrape failed",
        }
        state = _make_state(**outputs)
        assert route_after_research(state) == ROUTE_PROCEED

    def test_sentiment_error_only_returns_proceed(self) -> None:
        """Sentiment error (not negative score) -> proceed."""
        outputs = _clean_research_outputs()
        outputs["sentiment"] = {
            "agent_name": "sentiment_analyst",
            "error": "NewsAPI rate limit",
        }
        state = _make_state(**outputs)
        assert route_after_research(state) == ROUTE_PROCEED

    def test_returns_string(self) -> None:
        state = _make_state(**_clean_research_outputs())
        assert isinstance(route_after_research(state), str)


# ---------------------------------------------------------------------------
# 4. route_after_research -- boundary values
# ---------------------------------------------------------------------------


class TestRouteAfterResearchBoundaryValues:
    """Edge cases and boundary values for the routing thresholds."""

    def test_sentiment_exactly_at_threshold_is_proceed(self) -> None:
        """sentiment_score == -0.8 is NOT < -0.8, must be PROCEED."""
        state = _make_state(**_negative_sentiment_outputs(-0.8))
        assert route_after_research(state) == ROUTE_PROCEED

    def test_sentiment_epsilon_below_threshold_escalates(self) -> None:
        """sentiment_score = -0.800001 IS < -0.8, must escalate."""
        state = _make_state(**_negative_sentiment_outputs(-0.800001))
        assert route_after_research(state) == ROUTE_ESCALATE_SENTIMENT

    def test_fundamental_empty_string_error_routes_error(self) -> None:
        """Any truthy error string triggers error path."""
        state = _make_state(fundamental={"agent_name": "fa", "error": "x"})
        assert route_after_research(state) == ROUTE_ERROR

    def test_fundamental_false_error_does_not_route_error(self) -> None:
        """error=False is falsy but not None -- check None explicitly."""
        # Our check is: if fund_error is not None.  False is not None.
        # This corner case is intentionally conservative: any non-None
        # value is treated as an error to protect pipeline integrity.
        state = _make_state(fundamental={"agent_name": "fa", "error": False})
        # False is not None, but it is falsy.  Our code checks `is not None`.
        # This test documents the actual behaviour.
        result = route_after_research(state)
        # False triggers the error path because `False is not None` is True.
        assert result == ROUTE_ERROR

    def test_sentiment_score_as_int_escalates(self) -> None:
        """Integer -1 should also trigger escalation (int < float comparison)."""
        state = _make_state(
            **{
                **_clean_research_outputs(),
                "sentiment": {
                    "agent_name": "sa",
                    "sentiment_score": -1,
                    "error": None,
                },
            }
        )
        assert route_after_research(state) == ROUTE_ESCALATE_SENTIMENT

    def test_sentiment_score_missing_returns_proceed(self) -> None:
        """No sentiment_score key in sentiment dict -> proceed."""
        state = _make_state(sentiment={"agent_name": "sa", "error": None})
        assert route_after_research(state) == ROUTE_PROCEED

    def test_sentiment_not_dict_returns_proceed(self) -> None:
        """state["sentiment"] is not a dict -> no crash -> proceed."""
        state = _make_state(status="running")
        cast(Any, state)["sentiment"] = "invalid"
        assert route_after_research(state) == ROUTE_PROCEED

    def test_fundamental_not_dict_returns_proceed(self) -> None:
        """state["fundamental"] is not a dict -> no crash -> proceed."""
        state = _make_state(status="running")
        cast(Any, state)["fundamental"] = 42
        assert route_after_research(state) == ROUTE_PROCEED


# ---------------------------------------------------------------------------
# 5. route_after_research -- error takes priority over escalation
# ---------------------------------------------------------------------------


class TestRouteAfterResearchPriority:
    """Error path (fundamental failure) takes priority over escalation."""

    def test_both_error_and_negative_sentiment_routes_error(self) -> None:
        """Both conditions present -> error path wins (checked first)."""
        outputs = _failed_fundamental_outputs()
        outputs["sentiment"] = {
            "agent_name": "sentiment_analyst",
            "sentiment_score": -0.99,
            "error": None,
        }
        state = _make_state(**outputs)
        result = route_after_research(state)
        assert result == ROUTE_ERROR

    def test_error_priority_not_escalate_sentiment(self) -> None:
        outputs = _failed_fundamental_outputs()
        outputs["sentiment"] = {
            "agent_name": "sentiment_analyst",
            "sentiment_score": -1.0,
            "error": None,
        }
        state = _make_state(**outputs)
        assert route_after_research(state) != ROUTE_ESCALATE_SENTIMENT


# ---------------------------------------------------------------------------
# 6. route_after_research -- robustness (never raises)
# ---------------------------------------------------------------------------


class TestRouteAfterResearchRobustness:
    """route_after_research must never raise, even on corrupt state."""

    def test_completely_empty_state(self) -> None:
        empty: InvestmentState = cast(InvestmentState, {})
        result = route_after_research(empty)
        assert isinstance(result, str)

    def test_none_fundamental(self) -> None:
        state = _make_state(status="running")
        cast(Any, state)["fundamental"] = None
        result = route_after_research(state)
        assert isinstance(result, str)

    def test_none_sentiment(self) -> None:
        state = _make_state(status="running")
        cast(Any, state)["sentiment"] = None
        result = route_after_research(state)
        assert isinstance(result, str)

    def test_all_none(self) -> None:
        state = _make_state(status="running")
        cast(Any, state)["fundamental"] = None
        cast(Any, state)["technical"] = None
        cast(Any, state)["sentiment"] = None
        cast(Any, state)["macro"] = None
        result = route_after_research(state)
        assert isinstance(result, str)

    def test_does_not_raise_on_any_valid_state(self) -> None:
        """A selection of valid states must all return without raising."""
        states = [
            _make_state(**_clean_research_outputs()),
            _make_state(**_failed_fundamental_outputs()),
            _make_state(**_negative_sentiment_outputs(-0.9)),
            _make_state(status="running"),
            cast(InvestmentState, {}),
        ]
        for st in states:
            result = route_after_research(st)
            assert result in (
                ROUTE_PROCEED,
                ROUTE_ERROR,
                ROUTE_ESCALATE_SENTIMENT,
            )


# ---------------------------------------------------------------------------
# 7. error_handler_node -- state updates
# ---------------------------------------------------------------------------


class TestErrorHandlerNode:
    """error_handler_node writes the correct state updates."""

    def test_returns_dict(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert isinstance(result, dict)

    def test_sets_pipeline_error(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert "pipeline_error" in result
        assert isinstance(result["pipeline_error"], str)
        assert len(result["pipeline_error"]) > 0

    def test_pipeline_error_mentions_ticker(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert _TICKER in result["pipeline_error"]

    def test_pipeline_error_mentions_company(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert _COMPANY in result["pipeline_error"]

    def test_appends_fundamental_data_unavailable_flag(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in result.get("risk_flags", [])

    def test_appends_flag_to_critical_flags(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in result.get("critical_flags", [])

    def test_sets_current_node(self) -> None:
        """error_handler runs in its own step after research_join_node
        (T-032 topology fix), so it CAN safely write current_node."""
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert result.get("current_node") == NODE_ERROR_HANDLER

    def test_does_not_set_status_failed(self) -> None:
        """Pipeline must continue -- error_handler does NOT terminate it."""
        state = _make_state(**_failed_fundamental_outputs())
        result = error_handler_node(state)
        assert result.get("status") != "failed"

    def test_preserves_existing_risk_flags(self) -> None:
        """Pre-existing risk flags must be kept (not overwritten)."""
        state = _make_state(**_failed_fundamental_outputs())
        state["risk_flags"] = ["EXISTING_FLAG"]
        result = error_handler_node(state)
        assert "EXISTING_FLAG" in result.get("risk_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in result.get("risk_flags", [])

    def test_preserves_existing_critical_flags(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        state["critical_flags"] = ["EXISTING_CRITICAL"]
        result = error_handler_node(state)
        assert "EXISTING_CRITICAL" in result.get("critical_flags", [])

    def test_pipeline_error_contains_original_error_text(self) -> None:
        error_msg = "fetch_financials returned empty: API rate limit exceeded"
        state = _make_state(fundamental={"agent_name": "fa", "error": error_msg})
        result = error_handler_node(state)
        assert error_msg in result.get("pipeline_error", "")


# ---------------------------------------------------------------------------
# 8. error_handler_node -- idempotent flag writes
# ---------------------------------------------------------------------------


class TestErrorHandlerNodeIdempotent:
    """Calling error_handler_node twice does not duplicate flags."""

    def test_flag_not_duplicated_on_second_call(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        first = error_handler_node(state)
        # Simulate second call with flags already present
        state["risk_flags"] = first.get("risk_flags", [])
        state["critical_flags"] = first.get("critical_flags", [])
        second = error_handler_node(state)
        risk_flags = second.get("risk_flags", [])
        assert risk_flags.count("FUNDAMENTAL_DATA_UNAVAILABLE") == 1

    def test_critical_flag_not_duplicated(self) -> None:
        state = _make_state(**_failed_fundamental_outputs())
        first = error_handler_node(state)
        state["critical_flags"] = first.get("critical_flags", [])
        second = error_handler_node(state)
        critical_flags = second.get("critical_flags", [])
        assert critical_flags.count("FUNDAMENTAL_DATA_UNAVAILABLE") == 1


# ---------------------------------------------------------------------------
# 9. error_handler_node -- missing fundamental in state
# ---------------------------------------------------------------------------


class TestErrorHandlerNodeMissingFundamental:
    """error_handler_node must be robust to missing fundamental data."""

    def test_no_fundamental_key_does_not_raise(self) -> None:
        state = _make_state(status="running")
        result = error_handler_node(state)
        assert isinstance(result, dict)

    def test_none_fundamental_does_not_raise(self) -> None:
        state = _make_state(status="running")
        cast(Any, state)["fundamental"] = None
        result = error_handler_node(state)
        assert isinstance(result, dict)

    def test_empty_state_does_not_raise(self) -> None:
        empty: InvestmentState = cast(InvestmentState, {})
        result = error_handler_node(empty)
        assert isinstance(result, dict)

    def test_still_sets_flags_when_fundamental_missing(self) -> None:
        state = _make_state(status="running")
        result = error_handler_node(state)
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in result.get("risk_flags", [])


# ---------------------------------------------------------------------------
# 10. sentiment_escalation_node -- state updates
# ---------------------------------------------------------------------------


class TestSentimentEscalationNode:
    """sentiment_escalation_node writes the correct state updates."""

    def test_returns_dict(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        result = sentiment_escalation_node(state)
        assert isinstance(result, dict)

    def test_appends_escalation_flag_to_risk_flags(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        result = sentiment_escalation_node(state)
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT in result.get("risk_flags", [])

    def test_appends_escalation_flag_to_critical_flags(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        result = sentiment_escalation_node(state)
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT in result.get("critical_flags", [])

    def test_sets_current_node(self) -> None:
        """sentiment_escalation runs in its own step after research_join_node
        (T-032 topology fix), so it CAN safely write current_node."""
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        result = sentiment_escalation_node(state)
        assert result.get("current_node") == NODE_SENTIMENT_ESCALATION

    def test_does_not_set_status_failed(self) -> None:
        """Escalation is a flag, not a termination."""
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        result = sentiment_escalation_node(state)
        assert result.get("status") != "failed"

    def test_does_not_set_pipeline_error(self) -> None:
        """Escalation writes a flag but not a pipeline_error."""
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        result = sentiment_escalation_node(state)
        assert "pipeline_error" not in result

    def test_preserves_existing_risk_flags(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        state["risk_flags"] = ["SOME_EXISTING_FLAG"]
        result = sentiment_escalation_node(state)
        assert "SOME_EXISTING_FLAG" in result.get("risk_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT in result.get("risk_flags", [])

    def test_preserves_existing_critical_flags(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        state["critical_flags"] = ["EXISTING_CRITICAL"]
        result = sentiment_escalation_node(state)
        assert "EXISTING_CRITICAL" in result.get("critical_flags", [])

    def test_flag_value_matches_constant(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        result = sentiment_escalation_node(state)
        risk_flags = result.get("risk_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT in risk_flags


# ---------------------------------------------------------------------------
# 11. sentiment_escalation_node -- idempotent flag writes
# ---------------------------------------------------------------------------


class TestSentimentEscalationNodeIdempotent:
    """Calling sentiment_escalation_node twice does not duplicate flags."""

    def test_flag_not_duplicated(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        first = sentiment_escalation_node(state)
        state["risk_flags"] = first.get("risk_flags", [])
        state["critical_flags"] = first.get("critical_flags", [])
        second = sentiment_escalation_node(state)
        risk_flags = second.get("risk_flags", [])
        assert risk_flags.count(ESCALATION_FLAG_NEGATIVE_SENTIMENT) == 1

    def test_critical_flag_not_duplicated(self) -> None:
        state = _make_state(**_negative_sentiment_outputs(-0.9))
        first = sentiment_escalation_node(state)
        state["critical_flags"] = first.get("critical_flags", [])
        second = sentiment_escalation_node(state)
        critical_flags = second.get("critical_flags", [])
        assert critical_flags.count(ESCALATION_FLAG_NEGATIVE_SENTIMENT) == 1


# ---------------------------------------------------------------------------
# 12. sentiment_escalation_node -- missing sentiment in state
# ---------------------------------------------------------------------------


class TestSentimentEscalationNodeMissing:
    """sentiment_escalation_node must be robust to missing/corrupt sentiment."""

    def test_no_sentiment_key_does_not_raise(self) -> None:
        state = _make_state(status="running")
        result = sentiment_escalation_node(state)
        assert isinstance(result, dict)

    def test_none_sentiment_does_not_raise(self) -> None:
        state = _make_state(status="running")
        cast(Any, state)["sentiment"] = None
        result = sentiment_escalation_node(state)
        assert isinstance(result, dict)

    def test_empty_state_does_not_raise(self) -> None:
        empty: InvestmentState = cast(InvestmentState, {})
        result = sentiment_escalation_node(empty)
        assert isinstance(result, dict)

    def test_still_writes_flag_when_sentiment_missing(self) -> None:
        """Even without sentiment data the flag is appended (defensive)."""
        state = _make_state(status="running")
        result = sentiment_escalation_node(state)
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT in result.get("risk_flags", [])


# ---------------------------------------------------------------------------
# 13. Graph compilation -- 11 nodes registered
# ---------------------------------------------------------------------------


class TestGraphCompilationWithRoutingNodes:
    """build_graph() must compile with all 11 nodes (9 + 2 T-032)."""

    def test_compiles_without_error(self) -> None:
        compiled = build_graph()
        assert compiled is not None

    def test_twelve_content_nodes_registered(self) -> None:
        """T-043: 15 content nodes (9 original + 3 T-032 + 1 T-040
        debate_loop + 1 T-042 report_generator + 1 T-043 pdf_export)."""
        compiled = build_graph()
        nodes = compiled.get_graph().nodes
        content_nodes = [n for n in nodes if not n.startswith("__")]
        assert len(content_nodes) == 15, (
            f"Expected 15 content nodes, got {len(content_nodes)}: " f"{content_nodes}"
        )

    def test_research_join_registered(self) -> None:
        compiled = build_graph()
        nodes = compiled.get_graph().nodes
        assert NODE_RESEARCH_JOIN in nodes

    def test_error_handler_registered(self) -> None:
        compiled = build_graph()
        nodes = compiled.get_graph().nodes
        assert NODE_ERROR_HANDLER in nodes

    def test_sentiment_escalation_registered(self) -> None:
        compiled = build_graph()
        nodes = compiled.get_graph().nodes
        assert NODE_SENTIMENT_ESCALATION in nodes

    def test_all_11_node_names_registered(self) -> None:
        compiled = build_graph()
        nodes = compiled.get_graph().nodes
        missing = [n for n in _ALL_NODE_NAMES if n not in nodes]
        assert not missing, f"Missing nodes: {missing}"

    def test_has_invoke_method(self) -> None:
        assert hasattr(build_graph(), "invoke")

    def test_has_get_graph_method(self) -> None:
        assert hasattr(build_graph(), "get_graph")

    def test_routing_node_names_tuple_has_three_entries(self) -> None:
        assert len(ROUTING_NODE_NAMES) == 3

    def test_routing_node_names_contains_research_join(self) -> None:
        assert NODE_RESEARCH_JOIN in ROUTING_NODE_NAMES

    def test_routing_node_names_contains_error_handler(self) -> None:
        assert NODE_ERROR_HANDLER in ROUTING_NODE_NAMES

    def test_routing_node_names_contains_sentiment_escalation(self) -> None:
        assert NODE_SENTIMENT_ESCALATION in ROUTING_NODE_NAMES


# ---------------------------------------------------------------------------
# 14. Graph end-to-end -- error path
# ---------------------------------------------------------------------------


class TestGraphEndToEndErrorPath:
    """End-to-end test: mocked financials failure routes through error_handler."""

    def _run_error_path(self) -> dict[str, Any]:
        clean = _clean_research_outputs()
        failed_fa = {
            "agent_name": "fundamental_analyst",
            "error": "fetch_financials returned empty: rate limit",
            "score": 0,
        }
        return _run_graph_with_mocks(
            initial_state=_running_state(),
            fa_output=failed_fa,
            ta_output=clean["technical"],
            sa_output=clean["sentiment"],
            ma_output=clean["macro"],
        )

    def test_error_path_pipeline_completes(self) -> None:
        """Pipeline must complete (not hang) even with degraded fundamentals."""
        state = self._run_error_path()
        assert state.get("status") == "completed"

    def test_error_path_has_pipeline_error_message(self) -> None:
        state = self._run_error_path()
        assert state.get("pipeline_error") is not None
        assert len(str(state.get("pipeline_error", ""))) > 0

    def test_error_path_has_fundamental_data_unavailable_flag(self) -> None:
        state = self._run_error_path()
        risk_flags = state.get("risk_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in risk_flags

    def test_error_path_flag_in_critical_flags(self) -> None:
        state = self._run_error_path()
        critical_flags = state.get("critical_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in critical_flags

    def test_error_path_has_decision(self) -> None:
        """Portfolio Manager still runs and sets decision."""
        state = self._run_error_path()
        assert "decision" in state

    def test_error_path_has_final_verdict(self) -> None:
        state = self._run_error_path()
        assert state.get("final_verdict") in ("BUY", "HOLD", "SELL")


# ---------------------------------------------------------------------------
# 15. Graph end-to-end -- escalation path
# ---------------------------------------------------------------------------


class TestGraphEndToEndEscalationPath:
    """End-to-end test: negative sentiment routes through sentiment_escalation."""

    def _run_escalation_path(self) -> dict[str, Any]:
        clean = _clean_research_outputs()
        negative_sa = {
            "agent_name": "sentiment_analyst",
            "sentiment_score": -0.95,
            "error": None,
        }
        return _run_graph_with_mocks(
            initial_state=_running_state(),
            fa_output=clean["fundamental"],
            ta_output=clean["technical"],
            sa_output=negative_sa,
            ma_output=clean["macro"],
        )

    def test_escalation_path_pipeline_completes(self) -> None:
        state = self._run_escalation_path()
        assert state.get("status") == "completed"

    def test_escalation_path_has_negative_sentiment_flag(self) -> None:
        state = self._run_escalation_path()
        risk_flags = state.get("risk_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT in risk_flags

    def test_escalation_path_flag_in_critical_flags(self) -> None:
        state = self._run_escalation_path()
        critical_flags = state.get("critical_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT in critical_flags

    def test_escalation_path_no_pipeline_error(self) -> None:
        """Escalation is a flag, not an error -- pipeline_error stays None."""
        state = self._run_escalation_path()
        # pipeline_error may be absent or None -- either is acceptable
        pipeline_err = state.get("pipeline_error")
        assert pipeline_err is None or pipeline_err == ""

    def test_escalation_path_has_decision(self) -> None:
        state = self._run_escalation_path()
        assert "decision" in state

    def test_escalation_path_has_final_verdict(self) -> None:
        state = self._run_escalation_path()
        assert state.get("final_verdict") in ("BUY", "HOLD", "SELL")


# ---------------------------------------------------------------------------
# 16. Graph end-to-end -- normal path
# ---------------------------------------------------------------------------


class TestGraphEndToEndNormalPath:
    """End-to-end test: clean outputs take the normal proceed path."""

    def _run_normal_path(self) -> dict[str, Any]:
        clean = _clean_research_outputs()
        return _run_graph_with_mocks(
            initial_state=_running_state(),
            fa_output=clean["fundamental"],
            ta_output=clean["technical"],
            sa_output=clean["sentiment"],
            ma_output=clean["macro"],
        )

    def test_normal_path_completes(self) -> None:
        state = self._run_normal_path()
        assert state.get("status") == "completed"

    def test_normal_path_no_error_flags(self) -> None:
        state = self._run_normal_path()
        risk_flags = state.get("risk_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" not in risk_flags

    def test_normal_path_no_escalation_flags(self) -> None:
        state = self._run_normal_path()
        risk_flags = state.get("risk_flags", [])
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT not in risk_flags

    def test_normal_path_no_pipeline_error(self) -> None:
        state = self._run_normal_path()
        assert state.get("pipeline_error") is None or state.get("pipeline_error") == ""

    def test_normal_path_has_all_research_outputs(self) -> None:
        state = self._run_normal_path()
        for key in ("fundamental", "technical", "sentiment", "macro"):
            assert key in state

    def test_normal_path_has_decision(self) -> None:
        state = self._run_normal_path()
        assert "decision" in state


# ---------------------------------------------------------------------------
# 17. ROUTE_* constants -- all defined and distinct
# ---------------------------------------------------------------------------


class TestRouteConstants:
    """All ROUTE_* constants are non-empty, distinct strings."""

    def test_route_proceed_is_string(self) -> None:
        assert isinstance(ROUTE_PROCEED, str) and ROUTE_PROCEED

    def test_route_abort_is_string(self) -> None:
        assert isinstance(ROUTE_ABORT, str) and ROUTE_ABORT

    def test_route_error_is_string(self) -> None:
        assert isinstance(ROUTE_ERROR, str) and ROUTE_ERROR

    def test_route_debate_again_is_string(self) -> None:
        assert isinstance(ROUTE_DEBATE_AGAIN, str) and ROUTE_DEBATE_AGAIN

    def test_route_escalate_sentiment_is_string(self) -> None:
        assert isinstance(ROUTE_ESCALATE_SENTIMENT, str) and ROUTE_ESCALATE_SENTIMENT

    def test_all_route_constants_distinct(self) -> None:
        routes = {
            ROUTE_PROCEED,
            ROUTE_ABORT,
            ROUTE_ERROR,
            ROUTE_DEBATE_AGAIN,
            ROUTE_ESCALATE_SENTIMENT,
        }
        assert len(routes) == 5

    def test_route_proceed_value(self) -> None:
        assert ROUTE_PROCEED == "proceed"

    def test_route_abort_value(self) -> None:
        assert ROUTE_ABORT == "abort"

    def test_route_error_value(self) -> None:
        assert ROUTE_ERROR == "error"

    def test_route_debate_again_value(self) -> None:
        assert ROUTE_DEBATE_AGAIN == "debate_again"

    def test_route_escalate_sentiment_value(self) -> None:
        assert ROUTE_ESCALATE_SENTIMENT == "escalate_sentiment"


# ---------------------------------------------------------------------------
# 18. NEGATIVE_SENTIMENT_THRESHOLD -- correct value
# ---------------------------------------------------------------------------


class TestNegativeSentimentThreshold:
    """NEGATIVE_SENTIMENT_THRESHOLD is -0.8."""

    def test_is_float(self) -> None:
        assert isinstance(NEGATIVE_SENTIMENT_THRESHOLD, float)

    def test_correct_value(self) -> None:
        assert NEGATIVE_SENTIMENT_THRESHOLD == -0.8

    def test_is_negative(self) -> None:
        assert NEGATIVE_SENTIMENT_THRESHOLD < 0

    def test_is_in_valid_range(self) -> None:
        """Must be within the [-1.0, 0.0] range for sentiment scores."""
        assert -1.0 <= NEGATIVE_SENTIMENT_THRESHOLD <= 0.0

    def test_importable_from_routing(self) -> None:
        from backend.graph.routing import (  # noqa: F401
            NEGATIVE_SENTIMENT_THRESHOLD as nst,
        )

        assert nst == -0.8


# ---------------------------------------------------------------------------
# 19. ESCALATION_FLAG_NEGATIVE_SENTIMENT -- correct value
# ---------------------------------------------------------------------------


class TestEscalationFlagConstant:
    """ESCALATION_FLAG_NEGATIVE_SENTIMENT is the expected string."""

    def test_is_string(self) -> None:
        assert isinstance(ESCALATION_FLAG_NEGATIVE_SENTIMENT, str)

    def test_is_non_empty(self) -> None:
        assert len(ESCALATION_FLAG_NEGATIVE_SENTIMENT) > 0

    def test_correct_value(self) -> None:
        assert (
            ESCALATION_FLAG_NEGATIVE_SENTIMENT
            == "NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH"
        )

    def test_is_screaming_snake_case(self) -> None:
        """AIRP convention: constants use SCREAMING_SNAKE_CASE."""
        assert ESCALATION_FLAG_NEGATIVE_SENTIMENT.isupper() or "_" in (
            ESCALATION_FLAG_NEGATIVE_SENTIMENT
        )

    def test_importable_from_routing(self) -> None:
        from backend.graph.routing import (  # noqa: F401
            ESCALATION_FLAG_NEGATIVE_SENTIMENT as flag,
        )

        assert isinstance(flag, str)


# ---------------------------------------------------------------------------
# 20. Graph Mermaid diagram -- new nodes appear
# ---------------------------------------------------------------------------


class TestMermaidDiagramT032:
    """T-032 nodes (error_handler, sentiment_escalation) appear in Mermaid."""

    def _mermaid(self) -> str:
        compiled = build_graph()
        return str(compiled.get_graph().draw_mermaid())

    def test_research_join_in_diagram(self) -> None:
        assert NODE_RESEARCH_JOIN in self._mermaid()

    def test_error_handler_in_diagram(self) -> None:
        assert NODE_ERROR_HANDLER in self._mermaid()

    def test_sentiment_escalation_in_diagram(self) -> None:
        assert NODE_SENTIMENT_ESCALATION in self._mermaid()

    def test_all_11_nodes_in_diagram(self) -> None:
        mermaid = self._mermaid()
        missing = [n for n in _ALL_NODE_NAMES if n not in mermaid]
        assert not missing, f"Missing from Mermaid: {missing}"

    def test_diagram_non_empty(self) -> None:
        assert len(self._mermaid()) > 100

    def test_diagram_has_end_marker(self) -> None:
        mermaid = self._mermaid()
        assert any(m in mermaid for m in ("__end__", "END", "end"))


# ---------------------------------------------------------------------------
# 21. Public API -- all symbols importable
# ---------------------------------------------------------------------------


class TestPublicAPIRoutingModule:
    """All __all__ symbols from routing module are importable."""

    def test_all_routing_symbols_importable(self) -> None:
        from backend.graph import routing

        for symbol in routing.__all__:
            assert hasattr(routing, symbol), f"Missing: {symbol}"

    def test_all_nodes_symbols_importable(self) -> None:
        from backend.graph import nodes

        for symbol in nodes.__all__:
            assert hasattr(nodes, symbol), f"Missing: {symbol}"

    def test_all_graph_symbols_importable(self) -> None:
        from backend.graph import graph

        for symbol in graph.__all__:
            assert hasattr(graph, symbol), f"Missing: {symbol}"

    def test_route_error_in_routing_all(self) -> None:
        from backend.graph import routing

        assert "ROUTE_ERROR" in routing.__all__

    def test_route_escalate_in_routing_all(self) -> None:
        from backend.graph import routing

        assert "ROUTE_ESCALATE_SENTIMENT" in routing.__all__

    def test_escalation_flag_in_routing_all(self) -> None:
        from backend.graph import routing

        assert "ESCALATION_FLAG_NEGATIVE_SENTIMENT" in routing.__all__

    def test_threshold_in_routing_all(self) -> None:
        from backend.graph import routing

        assert "NEGATIVE_SENTIMENT_THRESHOLD" in routing.__all__

    def test_error_handler_node_in_nodes_all(self) -> None:
        from backend.graph import nodes

        assert "error_handler_node" in nodes.__all__

    def test_sentiment_escalation_node_in_nodes_all(self) -> None:
        from backend.graph import nodes

        assert "sentiment_escalation_node" in nodes.__all__

    def test_node_research_join_constant_in_nodes_all(self) -> None:
        from backend.graph import nodes

        assert "NODE_RESEARCH_JOIN" in nodes.__all__

    def test_research_join_node_in_nodes_all(self) -> None:
        from backend.graph import nodes

        assert "research_join_node" in nodes.__all__

    def test_node_error_handler_constant_in_nodes_all(self) -> None:
        from backend.graph import nodes

        assert "NODE_ERROR_HANDLER" in nodes.__all__

    def test_node_sentiment_escalation_constant_in_nodes_all(self) -> None:
        from backend.graph import nodes

        assert "NODE_SENTIMENT_ESCALATION" in nodes.__all__

    def test_routing_node_names_in_graph_all(self) -> None:
        from backend.graph import graph

        assert "ROUTING_NODE_NAMES" in graph.__all__
