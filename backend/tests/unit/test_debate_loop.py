# backend/tests/unit/test_debate_loop.py
"""
Unit tests for T-040: Multi-Round Debate Loop.

Acceptance criteria (from project plan):
  - 2 debate rounds complete in <3min
  - debate_rounds[] contains responses from each agent
  - no infinite loops

Test strategy
-------------
  1. _agent_response_text       -- per-agent deterministic response builder
  2. _build_agent_responses     -- full agent_responses dict for one round
  3. _debate_loop_impl          -- core node logic, debate_rounds[] shape
  4. debate_loop_node           -- persistence-wrapped public node
  5. Graph wiring               -- debate_loop registered, 15 total nodes,
                                   contrarian -> debate_loop -> route edge
  6. route_after_contrarian     -- unchanged T-038 behaviour still holds
                                   after the topology change (regression)
  7. Multi-round integration    -- two full rounds via the compiled graph,
                                   each appends exactly one debate_rounds[]
                                   entry, terminates at MAX_DEBATE_ROUNDS
  8. Timing                     -- two rounds complete well under 3 minutes
                                   with mocked LLM (no real network calls)
  9. No infinite loop           -- debate_round_count is monotonic and the
                                   graph always reaches END

All external calls (LLM, APIs, DB) are mocked. No network. No database.
ENVIRONMENT must be set to 'test' before any backend import.
"""
from __future__ import annotations

import os
import time
from typing import Any, cast
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# T-033: patch _run_persist so debate loop tests never touch the database
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_db_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent state_persistence from opening DB connections in these tests."""
    monkeypatch.setattr(
        "backend.graph.nodes._run_persist",
        lambda *args, **kwargs: None,
    )


@pytest.fixture(autouse=True)
def _no_mermaid_export(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent build_graph() from writing docs/GRAPH_DIAGRAM.md in tests."""
    monkeypatch.setattr(
        "backend.graph.graph.export_mermaid_diagram",
        lambda *args, **kwargs: None,
    )


from backend.graph.graph import build_graph  # noqa: E402
from backend.graph.nodes import (  # noqa: E402
    NODE_CONTRARIAN,
    NODE_DEBATE_LOOP,
    NODE_RISK,
    _agent_response_text,
    _build_agent_responses,
    _debate_loop_impl,
    debate_loop_node,
)
from backend.graph.routing import (  # noqa: E402
    MAX_DEBATE_ROUNDS,
    ROUTE_DEBATE_AGAIN,
    ROUTE_PROCEED,
    route_after_contrarian,
)
from backend.graph.state import InvestmentState, make_initial_state  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_JOB_ID = "t040-test-job-uuid-001"
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"
_EXCHANGE = "NSE"

_FUNDAMENTAL_BULLISH: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "score": 9,
    "debt_to_equity": 0.02,
    "roe_pct": 46.2,
    "summary": "Exceptional fundamental quality with double-digit growth.",
}

_TECHNICAL_BUY: dict[str, Any] = {
    "agent_name": "technical_analyst",
    "signal": "BUY",
    "signal_strength": 8,
    "rsi_14": 68.0,
    "summary": "Strong uptrend with bullish momentum.",
}

_SENTIMENT_POSITIVE: dict[str, Any] = {
    "agent_name": "sentiment_analyst",
    "sentiment_score": 0.4,
    "sentiment_label": "positive",
    "summary": "Positive coverage across major news outlets.",
}

_MACRO_FAVOURABLE: dict[str, Any] = {
    "agent_name": "macro_economist",
    "macro_environment": "favourable",
    "summary": "Favourable IT services demand environment.",
}

_RISK_LOW: dict[str, Any] = {
    "agent_name": "risk_officer",
    "risk_score": 3,
    "summary": "Low governance and regulatory risk.",
}

_CONTRARIAN_HIGH_CONVICTION: dict[str, Any] = {
    "agent_name": "contrarian_investor",
    "counter_arguments": [
        "PE of 28x leaves no margin of safety.",
        "ROE of 46% invites mean reversion.",
        "RSI of 68 signals overbought conditions.",
    ],
    "challenged_agents": ["fundamental_analyst", "technical_analyst"],
    "overlooked_risks": ["Client concentration in BFSI vertical."],
    "bear_conviction": 8,
    "strongest_argument": "Valuation already prices in years of flawless execution.",
    "summary": "The bull case is more fragile than consensus believes.",
}

_CONTRARIAN_LOW_CONVICTION: dict[str, Any] = {
    "agent_name": "contrarian_investor",
    "counter_arguments": [
        "Mediocre fundamentals leave little room for error.",
    ],
    "challenged_agents": [],
    "overlooked_risks": [],
    "bear_conviction": 2,
    "strongest_argument": "Limited but non-zero downside risk exists.",
    "summary": "No strong contrarian case found.",
}


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


def _full_research_state(**overrides: Any) -> InvestmentState:
    """State with all 4 research agents + risk + contrarian populated.

    Overrides win over the defaults below -- merged into a single dict
    before being splatted into _make_state() exactly once, so passing
    e.g. contrarian=... or debate_round_count=... as an override never
    collides with the defaults (the bug fixed here: previously these
    defaults were passed as literal keyword arguments AND re-passed via
    **overrides in the same call, which raises TypeError: got multiple
    values for keyword argument whenever a test overrode one of them).
    """
    defaults: dict[str, Any] = {
        "status": "running",
        "fundamental": _FUNDAMENTAL_BULLISH,
        "technical": _TECHNICAL_BUY,
        "sentiment": _SENTIMENT_POSITIVE,
        "macro": _MACRO_FAVOURABLE,
        "risk": _RISK_LOW,
        "contrarian": _CONTRARIAN_HIGH_CONVICTION,
        "debate_round_count": 1,
    }
    defaults.update(overrides)
    return _make_state(**defaults)


# ---------------------------------------------------------------------------
# 1. _agent_response_text -- per-agent deterministic response builder
# ---------------------------------------------------------------------------


class TestAgentResponseText:
    """_agent_response_text produces a deterministic single-sentence stance."""

    def test_missing_agent_output_returns_no_position(self) -> None:
        text = _agent_response_text(
            agent_field_name="fundamental",
            agent_label="Fundamental Analyst",
            agent_out={},
            challenged_agents=[],
            bear_conviction=5,
        )
        assert "no position" in text.lower()

    def test_errored_agent_output_returns_no_position(self) -> None:
        text = _agent_response_text(
            agent_field_name="fundamental",
            agent_label="Fundamental Analyst",
            agent_out={"error": "fetch failed"},
            challenged_agents=[],
            bear_conviction=5,
        )
        assert "no position" in text.lower()

    def test_unchallenged_agent_reaffirms_with_summary(self) -> None:
        text = _agent_response_text(
            agent_field_name="macro",
            agent_label="Macro Economist",
            agent_out=_MACRO_FAVOURABLE,
            challenged_agents=["fundamental_analyst"],
            bear_conviction=8,
        )
        assert "reaffirms" in text.lower()
        assert _MACRO_FAVOURABLE["summary"] in text

    def test_unchallenged_agent_without_summary_still_reaffirms(self) -> None:
        text = _agent_response_text(
            agent_field_name="macro",
            agent_label="Macro Economist",
            agent_out={"agent_name": "macro_economist"},
            challenged_agents=["fundamental_analyst"],
            bear_conviction=8,
        )
        assert "reaffirms" in text.lower()

    def test_challenged_agent_high_conviction_concedes(self) -> None:
        text = _agent_response_text(
            agent_field_name="fundamental",
            agent_label="Fundamental Analyst",
            agent_out=_FUNDAMENTAL_BULLISH,
            challenged_agents=["fundamental_analyst"],
            bear_conviction=8,
        )
        assert "concedes" in text.lower()

    def test_challenged_agent_low_conviction_holds_position(self) -> None:
        text = _agent_response_text(
            agent_field_name="fundamental",
            agent_label="Fundamental Analyst",
            agent_out=_FUNDAMENTAL_BULLISH,
            challenged_agents=["fundamental_analyst"],
            bear_conviction=3,
        )
        assert "maintains" in text.lower()
        assert "concedes" not in text.lower()

    def test_challenged_agent_conviction_exactly_at_threshold_concedes(self) -> None:
        """_CONCEDE_THRESHOLD is 7 -- boundary value must concede, not hold."""
        text = _agent_response_text(
            agent_field_name="fundamental",
            agent_label="Fundamental Analyst",
            agent_out=_FUNDAMENTAL_BULLISH,
            challenged_agents=["fundamental_analyst"],
            bear_conviction=7,
        )
        assert "concedes" in text.lower()

    def test_challenged_agent_conviction_one_below_threshold_holds(self) -> None:
        text = _agent_response_text(
            agent_field_name="fundamental",
            agent_label="Fundamental Analyst",
            agent_out=_FUNDAMENTAL_BULLISH,
            challenged_agents=["fundamental_analyst"],
            bear_conviction=6,
        )
        assert "maintains" in text.lower()

    def test_response_always_non_empty_string(self) -> None:
        for agent_out in ({}, {"error": "x"}, _FUNDAMENTAL_BULLISH):
            text = _agent_response_text(
                agent_field_name="fundamental",
                agent_label="Fundamental Analyst",
                agent_out=agent_out,
                challenged_agents=[],
                bear_conviction=1,
            )
            assert isinstance(text, str)
            assert len(text) > 0


# ---------------------------------------------------------------------------
# 2. _build_agent_responses -- full agent_responses dict for one round
# ---------------------------------------------------------------------------


class TestBuildAgentResponses:
    """_build_agent_responses returns one entry per known agent field."""

    def test_returns_dict(self) -> None:
        state = _full_research_state()
        responses = _build_agent_responses(
            state=state,
            challenged_agents=["fundamental_analyst"],
            bear_conviction=8,
        )
        assert isinstance(responses, dict)

    def test_contains_all_five_agent_keys(self) -> None:
        state = _full_research_state()
        responses = _build_agent_responses(
            state=state,
            challenged_agents=[],
            bear_conviction=1,
        )
        for key in ("fundamental", "technical", "sentiment", "macro", "risk"):
            assert key in responses

    def test_every_response_is_non_empty_string(self) -> None:
        state = _full_research_state()
        responses = _build_agent_responses(
            state=state,
            challenged_agents=["fundamental_analyst", "technical_analyst"],
            bear_conviction=8,
        )
        for value in responses.values():
            assert isinstance(value, str)
            assert len(value) > 0

    def test_missing_risk_output_round_one_is_no_position(self) -> None:
        """Risk Officer runs AFTER the debate loop -- round 1 has no risk yet."""
        state = _make_state(
            status="running",
            fundamental=_FUNDAMENTAL_BULLISH,
            technical=_TECHNICAL_BUY,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            contrarian=_CONTRARIAN_HIGH_CONVICTION,
            debate_round_count=1,
        )
        responses = _build_agent_responses(
            state=state,
            challenged_agents=[],
            bear_conviction=1,
        )
        assert "no position" in responses["risk"].lower()

    def test_challenged_agents_concede_at_high_conviction(self) -> None:
        state = _full_research_state()
        responses = _build_agent_responses(
            state=state,
            challenged_agents=["fundamental_analyst", "technical_analyst"],
            bear_conviction=9,
        )
        assert "concedes" in responses["fundamental"].lower()
        assert "concedes" in responses["technical"].lower()
        # macro and sentiment were not challenged -- they reaffirm
        assert "reaffirms" in responses["macro"].lower()
        assert "reaffirms" in responses["sentiment"].lower()

    def test_never_raises_on_empty_state(self) -> None:
        empty: InvestmentState = cast(InvestmentState, {})
        responses = _build_agent_responses(
            state=empty,
            challenged_agents=[],
            bear_conviction=1,
        )
        assert isinstance(responses, dict)
        assert len(responses) == 5


# ---------------------------------------------------------------------------
# 3. _debate_loop_impl -- core node logic
# ---------------------------------------------------------------------------


class TestDebateLoopImpl:
    """_debate_loop_impl appends exactly one well-formed debate_rounds[] entry."""

    def test_returns_dict(self) -> None:
        state = _full_research_state()
        result = _debate_loop_impl(state)
        assert isinstance(result, dict)

    def test_has_debate_rounds_key(self) -> None:
        state = _full_research_state()
        result = _debate_loop_impl(state)
        assert "debate_rounds" in result

    def test_debate_rounds_is_list(self) -> None:
        state = _full_research_state()
        result = _debate_loop_impl(state)
        assert isinstance(result["debate_rounds"], list)

    def test_appends_exactly_one_entry_to_existing_list(self) -> None:
        state = _full_research_state(debate_rounds=[{"round_number": 0}])
        result = _debate_loop_impl(state)
        assert len(result["debate_rounds"]) == 2

    def test_first_round_produces_one_entry(self) -> None:
        state = _full_research_state(debate_rounds=[])
        result = _debate_loop_impl(state)
        assert len(result["debate_rounds"]) == 1

    def test_entry_has_round_number(self) -> None:
        state = _full_research_state(debate_round_count=1)
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        assert entry["round_number"] == 1

    def test_entry_round_number_matches_debate_round_count(self) -> None:
        state = _full_research_state(debate_round_count=2)
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        assert entry["round_number"] == 2

    def test_entry_has_agent_responses_dict(self) -> None:
        state = _full_research_state()
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        assert isinstance(entry["agent_responses"], dict)
        assert len(entry["agent_responses"]) == 5

    def test_entry_agent_responses_contains_all_agents(self) -> None:
        """Acceptance criterion: debate_rounds[] contains responses from
        each agent."""
        state = _full_research_state()
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        for key in ("fundamental", "technical", "sentiment", "macro", "risk"):
            assert key in entry["agent_responses"]
            assert isinstance(entry["agent_responses"][key], str)
            assert len(entry["agent_responses"][key]) > 0

    def test_entry_has_contrarian_text(self) -> None:
        state = _full_research_state()
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        assert isinstance(entry["contrarian"], str)
        assert len(entry["contrarian"]) > 0
        assert entry["contrarian"] == _CONTRARIAN_HIGH_CONVICTION["strongest_argument"]

    def test_entry_contrarian_falls_back_to_summary(self) -> None:
        contrarian_no_strongest = dict(_CONTRARIAN_HIGH_CONVICTION)
        contrarian_no_strongest["strongest_argument"] = ""
        state = _full_research_state(contrarian=contrarian_no_strongest)
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        assert entry["contrarian"] == contrarian_no_strongest["summary"]

    def test_entry_contrarian_falls_back_to_placeholder(self) -> None:
        state = _full_research_state(contrarian={})
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        assert "unavailable" in entry["contrarian"].lower()

    def test_entry_has_completed_at_iso_timestamp(self) -> None:
        state = _full_research_state()
        result = _debate_loop_impl(state)
        entry = result["debate_rounds"][-1]
        assert isinstance(entry["completed_at"], str)
        assert entry["completed_at"].endswith("Z")

    def test_sets_current_node(self) -> None:
        state = _full_research_state()
        result = _debate_loop_impl(state)
        assert result["current_node"] == NODE_DEBATE_LOOP

    def test_never_raises_on_missing_contrarian(self) -> None:
        state = _make_state(status="running", debate_round_count=1)
        result = _debate_loop_impl(state)
        assert isinstance(result, dict)
        assert len(result["debate_rounds"]) == 1

    def test_never_raises_on_empty_state(self) -> None:
        empty: InvestmentState = cast(InvestmentState, {})
        result = _debate_loop_impl(empty)
        assert isinstance(result, dict)
        assert len(result["debate_rounds"]) == 1

    def test_never_raises_on_malformed_bear_conviction(self) -> None:
        """bear_conviction as a non-int (e.g. string from a bad LLM parse)
        must not raise -- defaults to 1."""
        state = _full_research_state(
            contrarian={**_CONTRARIAN_HIGH_CONVICTION, "bear_conviction": "high"}
        )
        result = _debate_loop_impl(state)
        assert isinstance(result, dict)
        entry = result["debate_rounds"][-1]
        assert isinstance(entry["agent_responses"], dict)

    def test_two_sequential_calls_produce_two_distinct_entries(self) -> None:
        """Simulates round 1 then round 2 -- list grows monotonically."""
        state_round_1 = _full_research_state(
            debate_round_count=1, contrarian=_CONTRARIAN_HIGH_CONVICTION
        )
        result_1 = _debate_loop_impl(state_round_1)
        assert len(result_1["debate_rounds"]) == 1

        state_round_2 = _full_research_state(
            debate_round_count=2,
            contrarian=_CONTRARIAN_LOW_CONVICTION,
            debate_rounds=result_1["debate_rounds"],
        )
        result_2 = _debate_loop_impl(state_round_2)
        assert len(result_2["debate_rounds"]) == 2
        assert result_2["debate_rounds"][0]["round_number"] == 1
        assert result_2["debate_rounds"][1]["round_number"] == 2


# ---------------------------------------------------------------------------
# 4. debate_loop_node -- persistence-wrapped public node
# ---------------------------------------------------------------------------


class TestDebateLoopNode:
    """debate_loop_node (profiled + persistence-wrapped) behaves like the
    underlying impl function from the caller's perspective."""

    def test_returns_dict(self) -> None:
        state = _full_research_state()
        result = debate_loop_node(state)
        assert isinstance(result, dict)

    def test_has_debate_rounds_key(self) -> None:
        state = _full_research_state()
        result = debate_loop_node(state)
        assert "debate_rounds" in result

    def test_does_not_touch_database(self) -> None:
        """Patched _run_persist (autouse fixture) means no DB calls occur --
        this test simply confirms the node still returns successfully."""
        state = _full_research_state()
        result = debate_loop_node(state)
        assert isinstance(result["debate_rounds"], list)

    def test_never_raises_on_empty_state(self) -> None:
        result = debate_loop_node(cast(InvestmentState, {}))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 5. Graph wiring -- debate_loop registered, 15 total nodes
# ---------------------------------------------------------------------------


class TestGraphWiring:
    """debate_loop is correctly registered and wired into the compiled graph."""

    def _nodes(self) -> Any:
        return build_graph().get_graph().nodes

    def test_debate_loop_node_registered(self) -> None:
        assert NODE_DEBATE_LOOP in self._nodes()

    def test_total_node_count_is_thirteen(self) -> None:
        content_nodes = [n for n in self._nodes() if not n.startswith("__")]
        assert len(content_nodes) == 15, (
            f"Expected 15 content nodes after T-043, got "
            f"{len(content_nodes)}: {content_nodes}"
        )

    def test_mermaid_contains_debate_loop(self) -> None:
        mermaid = cast(str, build_graph().get_graph().draw_mermaid())
        assert NODE_DEBATE_LOOP in mermaid

    def test_mermaid_contains_contrarian_and_risk(self) -> None:
        """Sanity check that contrarian and risk are still both present
        around the new debate_loop node."""
        mermaid = cast(str, build_graph().get_graph().draw_mermaid())
        assert NODE_CONTRARIAN in mermaid
        assert NODE_RISK in mermaid


# ---------------------------------------------------------------------------
# 6. route_after_contrarian -- unchanged T-038 behaviour (regression)
# ---------------------------------------------------------------------------


class TestRouteAfterContrarianUnchanged:
    """T-040 moved route_after_contrarian's position in the graph (it now
    fires after debate_loop_node instead of directly after contrarian_node)
    but must NOT change its decision logic.  These mirror the pre-existing
    T-032/T-038 test_routing.py / test_graph_skeleton.py assertions exactly
    so a regression here is caught immediately."""

    def test_low_conviction_returns_proceed(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 3}
        assert route_after_contrarian(state) == ROUTE_PROCEED

    def test_conviction_six_returns_proceed(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 6}
        assert route_after_contrarian(state) == ROUTE_PROCEED

    def test_conviction_seven_returns_debate_again(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 7}
        state["debate_round_count"] = 0
        assert route_after_contrarian(state) == ROUTE_DEBATE_AGAIN

    def test_conviction_ten_returns_debate_again(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 10}
        state["debate_round_count"] = 0
        assert route_after_contrarian(state) == ROUTE_DEBATE_AGAIN

    def test_max_rounds_caps_at_proceed_even_with_high_conviction(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 10}
        state["debate_round_count"] = MAX_DEBATE_ROUNDS
        assert route_after_contrarian(state) == ROUTE_PROCEED

    def test_one_round_high_conviction_debates_again(self) -> None:
        state = _make_state()
        state["contrarian"] = {"bear_conviction": 8}
        state["debate_round_count"] = MAX_DEBATE_ROUNDS - 1
        assert route_after_contrarian(state) == ROUTE_DEBATE_AGAIN

    def test_max_debate_rounds_constant_is_two(self) -> None:
        """Acceptance criterion: max 2 rounds."""
        assert MAX_DEBATE_ROUNDS == 2


# ---------------------------------------------------------------------------
# 7 & 9. Multi-round integration via the compiled graph -- no infinite loop
# ---------------------------------------------------------------------------


def _mock_contrarian_factory(bear_convictions: list[int]) -> Any:
    """Build a side_effect function for run_contrarian_analysis that returns
    an increasing bear_conviction sequence across calls, then settles low so
    the loop terminates naturally if MAX_DEBATE_ROUNDS were not hit first."""
    call_count = {"n": 0}

    def _side_effect(state: dict[str, Any]) -> dict[str, Any]:
        idx = min(call_count["n"], len(bear_convictions) - 1)
        conviction = bear_convictions[idx]
        call_count["n"] += 1
        prev_round_count = int(state.get("debate_round_count") or 0)
        new_round_count = prev_round_count + 1
        return {
            "contrarian": {
                **_CONTRARIAN_HIGH_CONVICTION,
                "bear_conviction": conviction,
            },
            "debate_round_count": new_round_count,
        }

    return _side_effect


class TestMultiRoundIntegration:
    """Runs the contrarian <-> debate_loop sub-loop through the real
    compiled graph (research agents mocked) and asserts debate_rounds[]
    grows correctly and the pipeline always terminates."""

    def _run_pipeline(self, bear_convictions: list[int]) -> dict[str, Any]:
        initial: InvestmentState = make_initial_state(
            job_id=_JOB_ID,
            company_name=_COMPANY,
            ticker=_TICKER,
            exchange=_EXCHANGE,
            raw_query="TCS",
        )

        def fa_mock(state: dict[str, Any]) -> dict[str, Any]:
            return {"fundamental": _FUNDAMENTAL_BULLISH}

        def ta_mock(state: dict[str, Any]) -> dict[str, Any]:
            return {"technical": _TECHNICAL_BUY}

        def sa_mock(state: dict[str, Any]) -> dict[str, Any]:
            return {"sentiment": _SENTIMENT_POSITIVE}

        def ma_mock(state: dict[str, Any]) -> dict[str, Any]:
            return {"macro": _MACRO_FAVOURABLE}

        def risk_mock(state: dict[str, Any]) -> dict[str, Any]:
            return {"risk": _RISK_LOW, "risk_flags": [], "critical_flags": []}

        def valuation_mock(state: dict[str, Any]) -> dict[str, Any]:
            return {"valuation": {"agent_name": "valuation_agent"}}

        def portfolio_mock(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "decision": {"agent_name": "portfolio_manager"},
                "final_verdict": "HOLD",
                "status": "completed",
            }

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
                "backend.graph.nodes.run_contrarian_analysis",
                side_effect=_mock_contrarian_factory(bear_convictions),
            ),
            patch(
                "backend.graph.nodes.run_risk_analysis",
                side_effect=risk_mock,
            ),
            patch(
                "backend.graph.nodes.run_valuation_analysis",
                side_effect=valuation_mock,
            ),
            patch(
                "backend.graph.nodes._run_persist",
                side_effect=lambda *a, **k: None,
            ),
            patch(
                "backend.graph.graph.export_mermaid_diagram",
                side_effect=lambda *a, **k: None,
            ),
        ):
            compiled = build_graph()
            result: Any = compiled.invoke(dict(initial))

        return cast(dict[str, Any], result)

    def test_two_rounds_run_when_conviction_stays_high(self) -> None:
        """bear_conviction=8 every round -> MAX_DEBATE_ROUNDS forces exactly
        2 rounds, then proceeds (acceptance: max 2 rounds, no infinite loop).
        """
        result = self._run_pipeline(bear_convictions=[8, 8, 8, 8])
        assert result["debate_round_count"] == 2
        assert len(result["debate_rounds"]) == 2

    def test_single_round_when_conviction_drops_immediately(self) -> None:
        """bear_conviction=2 on round 1 -> route_after_contrarian returns
        PROCEED immediately, only 1 debate_rounds[] entry created."""
        result = self._run_pipeline(bear_convictions=[2])
        assert result["debate_round_count"] == 1
        assert len(result["debate_rounds"]) == 1

    def test_debate_rounds_entries_have_increasing_round_numbers(self) -> None:
        result = self._run_pipeline(bear_convictions=[9, 9])
        rounds = result["debate_rounds"]
        assert [r["round_number"] for r in rounds] == [1, 2]

    def test_every_round_entry_has_all_agent_responses(self) -> None:
        result = self._run_pipeline(bear_convictions=[8, 8])
        for round_entry in result["debate_rounds"]:
            assert set(round_entry["agent_responses"].keys()) == {
                "fundamental",
                "technical",
                "sentiment",
                "macro",
                "risk",
            }

    def test_pipeline_reaches_completed_status(self) -> None:
        """No infinite loop -- the pipeline always reaches the Portfolio
        Manager and completes."""
        result = self._run_pipeline(bear_convictions=[8, 8])
        assert result.get("status") == "completed"
        assert "decision" in result
        assert "valuation" in result

    def test_pipeline_with_immediate_low_conviction_still_completes(self) -> None:
        result = self._run_pipeline(bear_convictions=[1])
        assert result.get("status") == "completed"


# ---------------------------------------------------------------------------
# 8. Timing -- 2 debate rounds well under 3 minutes (mocked LLM/agents)
# ---------------------------------------------------------------------------


class TestDebateLoopTiming:
    """Acceptance criterion: 2 debate rounds complete in <3min."""

    #: Generous upper bound for fully-mocked agents -- the real-world
    #: <3min budget is dominated by LLM latency, which is mocked out here.
    #: This test instead guards against accidental quadratic blow-ups or
    #: synchronous sleeps being introduced into the loop machinery.
    _TIMEOUT_S: float = 10.0

    def test_two_rounds_complete_within_budget(self) -> None:
        runner = TestMultiRoundIntegration()
        start = time.monotonic()
        result = runner._run_pipeline(bear_convictions=[8, 8])
        elapsed = time.monotonic() - start

        assert result["debate_round_count"] == 2
        assert elapsed < self._TIMEOUT_S, (
            f"2 debate rounds took {elapsed:.2f}s with mocked agents -- "
            f"expected well under {self._TIMEOUT_S}s"
        )

    def test_debate_loop_impl_itself_is_fast(self) -> None:
        """_debate_loop_impl makes zero LLM calls -- must run in milliseconds."""
        state = _full_research_state()
        start = time.monotonic()
        for _ in range(50):
            _debate_loop_impl(state)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"50 calls took {elapsed:.3f}s -- expected < 1.0s"


# ---------------------------------------------------------------------------
# 9. Public API surface
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """New T-040 symbols are importable from their expected modules."""

    def test_node_debate_loop_importable(self) -> None:
        from backend.graph.nodes import NODE_DEBATE_LOOP as _n  # noqa: F401

        assert _n == "debate_loop"

    def test_debate_loop_node_importable(self) -> None:
        from backend.graph.nodes import debate_loop_node as _f  # noqa: F401

        assert callable(_f)

    def test_max_debate_rounds_importable_from_routing(self) -> None:
        from backend.graph.routing import MAX_DEBATE_ROUNDS as _m  # noqa: F401

        assert _m == 2

    def test_nodes_module_all_includes_debate_loop_symbols(self) -> None:
        from backend.graph import nodes

        assert "NODE_DEBATE_LOOP" in nodes.__all__
        assert "debate_loop_node" in nodes.__all__

    def test_routing_module_all_includes_max_debate_rounds(self) -> None:
        from backend.graph import routing

        assert "MAX_DEBATE_ROUNDS" in routing.__all__

    def test_graph_module_compiles_with_new_node(self) -> None:
        from backend.graph.graph import build_graph

        compiled = build_graph()
        assert compiled is not None
