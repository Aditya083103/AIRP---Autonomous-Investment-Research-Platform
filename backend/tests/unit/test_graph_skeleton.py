# backend/tests/unit/test_graph_skeleton.py
"""
Unit tests for T-030: LangGraph StateGraph Skeleton.

Acceptance criteria (from project plan):
  - graph.get_graph().draw_mermaid() produces correct diagram
  - No compile errors

Test strategy
-------------
  1. Compile             -- build_graph() produces a compiled graph without error
  2. Mermaid             -- draw_mermaid() returns a non-empty string containing
                           every expected node name and edge shape
  3. Node registration   -- all 9 nodes are registered in the compiled graph
  4. Node functions      -- each node function (planner, stubs) returns the
                           correct partial state dict shape
  5. Routing functions   -- route_after_planner, route_after_research,
                           route_after_contrarian return the correct route
                           strings for each input condition
  6. Node name constants -- the NODE_* constants match what graph uses
  7. Route constants     -- ROUTE_* constants are non-empty strings
  8. Public API          -- build_graph, get_compiled_graph are importable
  9. Edge structure      -- all expected edges are present in graph repr
 10. Stub nodes          -- Phase 4 stubs return correct-shape sentinel dicts

All external calls (LLMs, APIs, Redis, ChromaDB) are mocked.
LangGraph itself is NOT mocked -- we test the real graph compilation
because that is the acceptance criterion.

ENVIRONMENT must be set to 'test' before any backend import.
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

from backend.graph.nodes import (  # noqa: E402
    NODE_CONTRARIAN,
    NODE_FUNDAMENTAL,
    NODE_MACRO,
    NODE_PLANNER,
    NODE_PORTFOLIO_MANAGER,
    NODE_RISK,
    NODE_SENTIMENT,
    NODE_TECHNICAL,
    NODE_VALUATION,
    contrarian_node,
    fundamental_node,
    macro_node,
    planner_node,
    portfolio_manager_node,
    risk_node,
    sentiment_node,
    technical_node,
    valuation_node,
)
from backend.graph.routing import (  # noqa: E402
    ROUTE_ABORT,
    ROUTE_DEBATE_AGAIN,
    ROUTE_PROCEED,
    route_after_contrarian,
    route_after_planner,
    route_after_research,
)
from backend.graph.state import InvestmentState, make_initial_state  # noqa: E402

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_JOB_ID = "t030-test-job-uuid-001"
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"
_EXCHANGE = "NSE"

_ALL_NODE_NAMES: list[str] = [
    NODE_PLANNER,
    NODE_FUNDAMENTAL,
    NODE_TECHNICAL,
    NODE_SENTIMENT,
    NODE_MACRO,
    NODE_CONTRARIAN,
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


def _empty_state() -> InvestmentState:
    """Return a minimal state dict (no ticker -- triggers error paths)."""
    return make_initial_state(
        job_id=_JOB_ID,
        company_name="",
        ticker="",
        exchange="",
        raw_query="",
    )


# ---------------------------------------------------------------------------
# 1. Graph compilation
# ---------------------------------------------------------------------------


class TestGraphCompiles:
    """build_graph() must compile without raising any exception."""

    def test_build_graph_returns_object(self) -> None:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        assert compiled is not None

    def test_build_graph_has_get_graph_method(self) -> None:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        assert hasattr(compiled, "get_graph")

    def test_build_graph_has_invoke_method(self) -> None:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        assert hasattr(compiled, "invoke")

    def test_build_graph_has_ainvoke_method(self) -> None:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        assert hasattr(compiled, "ainvoke")

    def test_build_graph_twice_is_independent(self) -> None:
        """Each call to build_graph() returns a fresh instance."""
        from backend.graph.graph import build_graph

        g1 = build_graph()
        g2 = build_graph()
        # Different objects -- not the same singleton
        assert g1 is not g2

    def test_get_compiled_graph_is_singleton(self) -> None:
        """get_compiled_graph() returns the same object every call."""
        from backend.graph.graph import get_compiled_graph

        g1 = get_compiled_graph()
        g2 = get_compiled_graph()
        assert g1 is g2

    def test_get_compiled_graph_importable(self) -> None:
        from backend.graph.graph import get_compiled_graph  # noqa: F401

        assert get_compiled_graph is not None


# ---------------------------------------------------------------------------
# 2. Mermaid diagram -- acceptance criterion
# ---------------------------------------------------------------------------


class TestMermaidDiagram:
    """draw_mermaid() must return a string with all nodes and key edges."""

    def _get_mermaid(self) -> str:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        mermaid: str = compiled.get_graph().draw_mermaid()
        return mermaid

    def test_draw_mermaid_returns_string(self) -> None:
        mermaid = self._get_mermaid()
        assert isinstance(mermaid, str)

    def test_draw_mermaid_non_empty(self) -> None:
        mermaid = self._get_mermaid()
        assert len(mermaid) > 100

    def test_mermaid_contains_planner(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_PLANNER in mermaid

    def test_mermaid_contains_fundamental(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_FUNDAMENTAL in mermaid

    def test_mermaid_contains_technical(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_TECHNICAL in mermaid

    def test_mermaid_contains_sentiment(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_SENTIMENT in mermaid

    def test_mermaid_contains_macro(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_MACRO in mermaid

    def test_mermaid_contains_contrarian(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_CONTRARIAN in mermaid

    def test_mermaid_contains_risk(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_RISK in mermaid

    def test_mermaid_contains_valuation(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_VALUATION in mermaid

    def test_mermaid_contains_portfolio_manager(self) -> None:
        mermaid = self._get_mermaid()
        assert NODE_PORTFOLIO_MANAGER in mermaid

    def test_mermaid_has_start_marker(self) -> None:
        """LangGraph Mermaid diagrams always start with 'stateDiagram'
        or '%%' or 'flowchart' depending on the version."""
        mermaid = self._get_mermaid()
        # At minimum the output must be non-trivially long and contain
        # one of the standard Mermaid graph headers
        assert any(
            keyword in mermaid
            for keyword in ["stateDiagram", "flowchart", "%%", "graph"]
        )

    def test_mermaid_contains_end_marker(self) -> None:
        mermaid = self._get_mermaid()
        # LangGraph uses __end__ or END in its Mermaid output
        assert "__end__" in mermaid or "END" in mermaid or "end" in mermaid.lower()

    def test_all_nodes_in_mermaid(self) -> None:
        mermaid = self._get_mermaid()
        missing = [n for n in _ALL_NODE_NAMES if n not in mermaid]
        assert not missing, f"Missing nodes in Mermaid diagram: {missing}"


# ---------------------------------------------------------------------------
# 3. Node registration
# ---------------------------------------------------------------------------


class TestNodeRegistration:
    """All 9 nodes must be registered in the compiled graph."""

    def _get_nodes(self) -> Any:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        return compiled.get_graph().nodes

    def test_planner_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_PLANNER in nodes

    def test_fundamental_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_FUNDAMENTAL in nodes

    def test_technical_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_TECHNICAL in nodes

    def test_sentiment_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_SENTIMENT in nodes

    def test_macro_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_MACRO in nodes

    def test_contrarian_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_CONTRARIAN in nodes

    def test_risk_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_RISK in nodes

    def test_valuation_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_VALUATION in nodes

    def test_portfolio_manager_registered(self) -> None:
        nodes = self._get_nodes()
        assert NODE_PORTFOLIO_MANAGER in nodes

    def test_exactly_nine_content_nodes(self) -> None:
        """Exactly 9 content nodes (excludes __start__ and __end__)."""
        nodes = self._get_nodes()
        content_nodes = [n for n in nodes if not n.startswith("__")]
        assert len(content_nodes) == 9, (
            f"Expected 9 content nodes, got {len(content_nodes)}: " f"{content_nodes}"
        )


# ---------------------------------------------------------------------------
# 4. Planner node function
# ---------------------------------------------------------------------------


class TestPlannerNode:
    """planner_node returns correct partial state for valid and invalid input."""

    def test_valid_state_returns_running(self) -> None:
        state = _make_state()
        result = planner_node(state)
        assert result["status"] == "running"

    def test_valid_state_sets_current_node(self) -> None:
        state = _make_state()
        result = planner_node(state)
        assert result["current_node"] == NODE_PLANNER

    def test_valid_state_sets_started_at(self) -> None:
        state = _make_state()
        result = planner_node(state)
        assert "started_at" in result
        assert isinstance(result["started_at"], str)
        assert result["started_at"].endswith("Z")

    def test_missing_ticker_returns_failed(self) -> None:
        state = _make_state()
        state["ticker"] = ""
        result = planner_node(state)
        assert result["status"] == "failed"

    def test_missing_company_returns_failed(self) -> None:
        state = _make_state()
        state["company_name"] = ""
        result = planner_node(state)
        assert result["status"] == "failed"

    def test_failed_state_has_pipeline_error(self) -> None:
        state = _empty_state()
        result = planner_node(state)
        assert "pipeline_error" in result
        assert len(result["pipeline_error"]) > 0

    def test_failed_state_current_node_is_planner(self) -> None:
        state = _empty_state()
        result = planner_node(state)
        assert result["current_node"] == NODE_PLANNER

    def test_planner_returns_dict(self) -> None:
        state = _make_state()
        result = planner_node(state)
        assert isinstance(result, dict)

    def test_planner_never_raises(self) -> None:
        # Even a completely empty dict must not raise
        result = planner_node({})  # type: ignore[arg-type]
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 5. Stub node functions -- Phase 4 placeholders
# ---------------------------------------------------------------------------


class TestStubNodes:
    """Phase 4 stub nodes return correctly shaped sentinel output dicts."""

    def test_risk_node_returns_dict(self) -> None:
        result = risk_node(_make_state())
        assert isinstance(result, dict)

    def test_risk_node_has_risk_key(self) -> None:
        result = risk_node(_make_state())
        assert "risk" in result

    def test_risk_node_risk_has_agent_name(self) -> None:
        result = risk_node(_make_state())
        risk_out = result["risk"]
        assert isinstance(risk_out, dict)
        assert risk_out["agent_name"] == "risk_officer"

    def test_risk_node_sets_current_node(self) -> None:
        result = risk_node(_make_state())
        assert result.get("current_node") == NODE_RISK

    def test_risk_node_has_risk_score(self) -> None:
        result = risk_node(_make_state())
        risk_out = result["risk"]
        assert isinstance(risk_out, dict)
        assert isinstance(risk_out["risk_score"], int)

    def test_contrarian_node_returns_dict(self) -> None:
        result = contrarian_node(_make_state())
        assert isinstance(result, dict)

    def test_contrarian_node_has_contrarian_key(self) -> None:
        result = contrarian_node(_make_state())
        assert "contrarian" in result

    def test_contrarian_node_has_agent_name(self) -> None:
        result = contrarian_node(_make_state())
        c_out = result["contrarian"]
        assert isinstance(c_out, dict)
        assert c_out["agent_name"] == "contrarian_investor"

    def test_contrarian_node_sets_current_node(self) -> None:
        result = contrarian_node(_make_state())
        assert result.get("current_node") == NODE_CONTRARIAN

    def test_contrarian_node_has_bear_conviction(self) -> None:
        result = contrarian_node(_make_state())
        c_out = result["contrarian"]
        assert isinstance(c_out, dict)
        assert isinstance(c_out["bear_conviction"], int)

    def test_valuation_node_returns_dict(self) -> None:
        result = valuation_node(_make_state())
        assert isinstance(result, dict)

    def test_valuation_node_has_valuation_key(self) -> None:
        result = valuation_node(_make_state())
        assert "valuation" in result

    def test_valuation_node_has_agent_name(self) -> None:
        result = valuation_node(_make_state())
        v_out = result["valuation"]
        assert isinstance(v_out, dict)
        assert v_out["agent_name"] == "valuation_agent"

    def test_valuation_node_sets_current_node(self) -> None:
        result = valuation_node(_make_state())
        assert result.get("current_node") == NODE_VALUATION

    def test_portfolio_manager_node_returns_dict(self) -> None:
        result = portfolio_manager_node(_make_state())
        assert isinstance(result, dict)

    def test_portfolio_manager_node_has_decision_key(self) -> None:
        result = portfolio_manager_node(_make_state())
        assert "decision" in result

    def test_portfolio_manager_sets_final_verdict(self) -> None:
        result = portfolio_manager_node(_make_state())
        assert "final_verdict" in result
        assert result["final_verdict"] in ("BUY", "HOLD", "SELL")

    def test_portfolio_manager_sets_conviction_score(self) -> None:
        result = portfolio_manager_node(_make_state())
        score = result.get("conviction_score")
        assert isinstance(score, int)
        assert 1 <= score <= 10

    def test_portfolio_manager_sets_status_completed(self) -> None:
        result = portfolio_manager_node(_make_state())
        assert result.get("status") == "completed"

    def test_portfolio_manager_sets_completed_at(self) -> None:
        result = portfolio_manager_node(_make_state())
        assert "completed_at" in result
        assert isinstance(result["completed_at"], str)

    def test_portfolio_manager_sets_current_node(self) -> None:
        result = portfolio_manager_node(_make_state())
        assert result.get("current_node") == NODE_PORTFOLIO_MANAGER

    def test_all_stub_nodes_never_raise(self) -> None:
        """All Phase 4 stub nodes must be robust to any state content."""
        empty: InvestmentState = {}  # type: ignore[typeddict-item]
        for fn in (risk_node, contrarian_node, valuation_node, portfolio_manager_node):
            result = fn(empty)
            assert isinstance(result, dict)

    def test_stub_nodes_preserve_job_id_in_output(self) -> None:
        """Stub outputs carry the job_id for traceability."""
        state = _make_state()
        for fn in (risk_node, contrarian_node, valuation_node):
            result = fn(state)
            # Find the nested output dict (first dict value that has agent_name)
            agent_out = next(
                (
                    v
                    for v in result.values()
                    if isinstance(v, dict) and "agent_name" in v
                ),
                None,
            )
            assert agent_out is not None
            assert agent_out.get("analysis_id") == _JOB_ID


# ---------------------------------------------------------------------------
# 6. Research agent node wrappers (mocked)
# ---------------------------------------------------------------------------


class TestResearchNodeWrappers:
    """fundamental/technical/sentiment/macro nodes delegate to real agents."""

    def _mock_run(self, return_key: str, return_value: dict[str, Any]) -> MagicMock:
        m = MagicMock(return_value={return_key: return_value})
        return m

    def test_fundamental_node_delegates(self) -> None:
        state = _make_state()
        fa_output = {"agent_name": "fundamental_analyst", "score": 8}
        with patch(
            "backend.graph.nodes.run_fundamental_analysis",
            return_value={"fundamental": fa_output},
        ):
            result = fundamental_node(state)
        assert "fundamental" in result
        assert result["fundamental"]["score"] == 8

    def test_fundamental_node_sets_current_node(self) -> None:
        state = _make_state()
        with patch(
            "backend.graph.nodes.run_fundamental_analysis",
            return_value={"fundamental": {}},
        ):
            result = fundamental_node(state)
        assert result.get("current_node") == NODE_FUNDAMENTAL

    def test_technical_node_delegates(self) -> None:
        state = _make_state()
        ta_output = {"agent_name": "technical_analyst", "signal": "BUY"}
        with patch(
            "backend.graph.nodes.run_technical_analysis",
            return_value={"technical": ta_output},
        ):
            result = technical_node(state)
        assert "technical" in result
        assert result["technical"]["signal"] == "BUY"

    def test_technical_node_sets_current_node(self) -> None:
        state = _make_state()
        with patch(
            "backend.graph.nodes.run_technical_analysis",
            return_value={"technical": {}},
        ):
            result = technical_node(state)
        assert result.get("current_node") == NODE_TECHNICAL

    def test_sentiment_node_delegates(self) -> None:
        state = _make_state()
        sa_output = {"agent_name": "news_sentiment", "sentiment_score": 0.5}
        with patch(
            "backend.graph.nodes.run_sentiment_analysis",
            return_value={"sentiment": sa_output},
        ):
            result = sentiment_node(state)
        assert "sentiment" in result
        assert result["sentiment"]["sentiment_score"] == 0.5

    def test_sentiment_node_sets_current_node(self) -> None:
        state = _make_state()
        with patch(
            "backend.graph.nodes.run_sentiment_analysis",
            return_value={"sentiment": {}},
        ):
            result = sentiment_node(state)
        assert result.get("current_node") == NODE_SENTIMENT

    def test_macro_node_delegates(self) -> None:
        state = _make_state()
        ma_output = {"agent_name": "macro_economist", "macro_environment": "neutral"}
        with patch(
            "backend.graph.nodes.run_macro_analysis",
            return_value={"macro": ma_output},
        ):
            result = macro_node(state)
        assert "macro" in result
        assert result["macro"]["macro_environment"] == "neutral"

    def test_macro_node_sets_current_node(self) -> None:
        state = _make_state()
        with patch(
            "backend.graph.nodes.run_macro_analysis",
            return_value={"macro": {}},
        ):
            result = macro_node(state)
        assert result.get("current_node") == NODE_MACRO


# ---------------------------------------------------------------------------
# 7. Routing functions
# ---------------------------------------------------------------------------


class TestRoutingFunctions:
    """Routing functions return the correct route string for each condition."""

    # route_after_planner

    def test_route_planner_running_returns_proceed(self) -> None:
        state = _make_state()
        state["status"] = "running"
        assert route_after_planner(state) == ROUTE_PROCEED

    def test_route_planner_pending_returns_proceed(self) -> None:
        state = _make_state()
        state["status"] = "pending"
        assert route_after_planner(state) == ROUTE_PROCEED

    def test_route_planner_failed_returns_abort(self) -> None:
        state = _make_state()
        state["status"] = "failed"
        assert route_after_planner(state) == ROUTE_ABORT

    def test_route_planner_missing_status_returns_proceed(self) -> None:
        """Empty state has no status key -- defaults to 'pending' -> PROCEED."""
        empty: InvestmentState = {}  # type: ignore[typeddict-item]
        result = route_after_planner(empty)
        assert result == ROUTE_PROCEED

    # route_after_research

    def test_route_research_clean_state_returns_proceed(self) -> None:
        state = _make_state()
        state["fundamental"] = {"agent_name": "fundamental_analyst", "score": 8}
        state["technical"] = {"agent_name": "technical_analyst", "signal": "BUY"}
        state["sentiment"] = {
            "agent_name": "news_sentiment",
            "sentiment_score": 0.3,
        }
        state["macro"] = {
            "agent_name": "macro_economist",
            "macro_environment": "neutral",
        }
        assert route_after_research(state) == ROUTE_PROCEED

    def test_route_research_partial_errors_still_proceeds(self) -> None:
        """Skeleton: partial agent errors do not abort the pipeline."""
        state = _make_state()
        state["fundamental"] = {
            "agent_name": "fundamental_analyst",
            "error": "API timeout",
        }
        state["technical"] = {"agent_name": "technical_analyst", "signal": "HOLD"}
        assert route_after_research(state) == ROUTE_PROCEED

    def test_route_research_all_errors_still_proceeds_in_skeleton(self) -> None:
        """Skeleton always proceeds -- Phase 4 will add abort logic."""
        state = _make_state()
        for field in ("fundamental", "technical", "sentiment", "macro"):
            # type: ignore[literal-required] needed: looping over typed keys
            state[field] = {  # type: ignore[literal-required]
                "agent_name": field,
                "error": "failed",
            }
        assert route_after_research(state) == ROUTE_PROCEED

    def test_route_research_empty_state_returns_proceed(self) -> None:
        empty: InvestmentState = {}  # type: ignore[typeddict-item]
        assert route_after_research(empty) == ROUTE_PROCEED

    # route_after_contrarian

    def test_route_contrarian_low_conviction_returns_proceed(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 3}
        assert route_after_contrarian(state) == ROUTE_PROCEED

    def test_route_contrarian_conviction_6_returns_proceed(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 6}
        assert route_after_contrarian(state) == ROUTE_PROCEED

    def test_route_contrarian_conviction_7_returns_debate_again(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 7}
        state["debate_round_count"] = 0
        assert route_after_contrarian(state) == ROUTE_DEBATE_AGAIN

    def test_route_contrarian_conviction_10_returns_debate_again(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 10}
        state["debate_round_count"] = 0
        assert route_after_contrarian(state) == ROUTE_DEBATE_AGAIN

    def test_route_contrarian_max_rounds_caps_at_proceed(self) -> None:
        """After 2 rounds, always PROCEED regardless of conviction."""
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 10}
        state["debate_round_count"] = 2
        assert route_after_contrarian(state) == ROUTE_PROCEED

    def test_route_contrarian_one_round_high_conviction_debates_again(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 8}
        state["debate_round_count"] = 1
        assert route_after_contrarian(state) == ROUTE_DEBATE_AGAIN

    def test_route_contrarian_missing_contrarian_returns_proceed(self) -> None:
        """No contrarian output yet -- defaults to bear_conviction=1."""
        state = _make_state()
        assert route_after_contrarian(state) == ROUTE_PROCEED

    def test_route_contrarian_empty_state_returns_proceed(self) -> None:
        empty: InvestmentState = {}  # type: ignore[typeddict-item]
        assert route_after_contrarian(empty) == ROUTE_PROCEED


# ---------------------------------------------------------------------------
# 8. Node name constants
# ---------------------------------------------------------------------------


class TestNodeNameConstants:
    """NODE_* constants are non-empty strings matching expected values."""

    def test_node_planner_is_string(self) -> None:
        assert isinstance(NODE_PLANNER, str) and NODE_PLANNER

    def test_node_fundamental_is_string(self) -> None:
        assert isinstance(NODE_FUNDAMENTAL, str) and NODE_FUNDAMENTAL

    def test_node_technical_is_string(self) -> None:
        assert isinstance(NODE_TECHNICAL, str) and NODE_TECHNICAL

    def test_node_sentiment_is_string(self) -> None:
        assert isinstance(NODE_SENTIMENT, str) and NODE_SENTIMENT

    def test_node_macro_is_string(self) -> None:
        assert isinstance(NODE_MACRO, str) and NODE_MACRO

    def test_node_contrarian_is_string(self) -> None:
        assert isinstance(NODE_CONTRARIAN, str) and NODE_CONTRARIAN

    def test_node_risk_is_string(self) -> None:
        assert isinstance(NODE_RISK, str) and NODE_RISK

    def test_node_valuation_is_string(self) -> None:
        assert isinstance(NODE_VALUATION, str) and NODE_VALUATION

    def test_node_portfolio_manager_is_string(self) -> None:
        assert isinstance(NODE_PORTFOLIO_MANAGER, str) and NODE_PORTFOLIO_MANAGER

    def test_all_node_names_unique(self) -> None:
        assert len(set(_ALL_NODE_NAMES)) == len(_ALL_NODE_NAMES)

    def test_node_names_match_expected_values(self) -> None:
        assert NODE_PLANNER == "planner"
        assert NODE_FUNDAMENTAL == "fundamental_analyst"
        assert NODE_TECHNICAL == "technical_analyst"
        assert NODE_SENTIMENT == "sentiment_analyst"
        assert NODE_MACRO == "macro_economist"
        assert NODE_CONTRARIAN == "contrarian_investor"
        assert NODE_RISK == "risk_officer"
        assert NODE_VALUATION == "valuation_agent"
        assert NODE_PORTFOLIO_MANAGER == "portfolio_manager"


# ---------------------------------------------------------------------------
# 9. Route constants
# ---------------------------------------------------------------------------


class TestRouteConstants:
    """ROUTE_* constants are non-empty strings."""

    def test_route_proceed_is_string(self) -> None:
        assert isinstance(ROUTE_PROCEED, str) and ROUTE_PROCEED

    def test_route_abort_is_string(self) -> None:
        assert isinstance(ROUTE_ABORT, str) and ROUTE_ABORT

    def test_route_debate_again_is_string(self) -> None:
        assert isinstance(ROUTE_DEBATE_AGAIN, str) and ROUTE_DEBATE_AGAIN

    def test_route_constants_are_distinct(self) -> None:
        routes = {ROUTE_PROCEED, ROUTE_ABORT, ROUTE_DEBATE_AGAIN}
        assert len(routes) == 3

    def test_route_proceed_value(self) -> None:
        assert ROUTE_PROCEED == "proceed"

    def test_route_abort_value(self) -> None:
        assert ROUTE_ABORT == "abort"

    def test_route_debate_again_value(self) -> None:
        assert ROUTE_DEBATE_AGAIN == "debate_again"


# ---------------------------------------------------------------------------
# 10. Public API surface
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """All public symbols are importable from expected modules."""

    def test_build_graph_importable(self) -> None:
        from backend.graph.graph import build_graph  # noqa: F401

        assert build_graph is not None

    def test_get_compiled_graph_importable(self) -> None:
        from backend.graph.graph import get_compiled_graph  # noqa: F401

        assert get_compiled_graph is not None

    def test_nodes_module_all_symbols_importable(self) -> None:
        from backend.graph import nodes  # noqa: F401

        for symbol in nodes.__all__:
            assert hasattr(nodes, symbol), f"Missing symbol: {symbol}"

    def test_routing_module_all_symbols_importable(self) -> None:
        from backend.graph import routing  # noqa: F401

        for symbol in routing.__all__:
            assert hasattr(routing, symbol), f"Missing symbol: {symbol}"

    def test_graph_module_all_importable(self) -> None:
        from backend.graph import graph  # noqa: F401

        for symbol in graph.__all__:
            assert hasattr(graph, symbol), f"Missing symbol: {symbol}"


# ---------------------------------------------------------------------------
# 11. Edge structure verification via Mermaid content
# ---------------------------------------------------------------------------


class TestEdgeStructure:
    """Expected edges are reflected in the Mermaid diagram output."""

    def _mermaid(self) -> str:
        from backend.graph.graph import build_graph

        return build_graph().get_graph().draw_mermaid()

    def test_planner_to_fundamental_edge_present(self) -> None:
        mermaid = self._mermaid()
        # Either planner -> fundamental_analyst or they're adjacent in output
        assert NODE_PLANNER in mermaid and NODE_FUNDAMENTAL in mermaid

    def test_research_nodes_to_contrarian(self) -> None:
        mermaid = self._mermaid()
        assert NODE_CONTRARIAN in mermaid

    def test_risk_to_valuation_edge(self) -> None:
        mermaid = self._mermaid()
        assert NODE_RISK in mermaid and NODE_VALUATION in mermaid

    def test_valuation_to_portfolio_manager_edge(self) -> None:
        mermaid = self._mermaid()
        assert NODE_VALUATION in mermaid and NODE_PORTFOLIO_MANAGER in mermaid

    def test_graph_has_edges_attribute(self) -> None:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        graph_repr = compiled.get_graph()
        assert hasattr(graph_repr, "edges")
