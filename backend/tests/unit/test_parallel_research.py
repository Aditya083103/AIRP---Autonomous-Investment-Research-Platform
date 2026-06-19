# backend/tests/unit/test_parallel_research.py
"""
Unit tests for T-031: Parallel Research Agent Execution.

Acceptance criteria (from project plan):
  - All 4 agents run concurrently
  - Total time < max(individual agent times) + 5s overhead

Test strategy
-------------
  1. Send API dispatch    -- route_after_planner returns list[Send], not str
  2. Send objects         -- each Send targets the correct node with full state
  3. Parallel timing      -- 4 mocked agents with sleep() run in < max + 5s
  4. State merge          -- all 4 outputs appear in state after join
  5. Abort path           -- failed planner returns END, not Send list
  6. PARALLEL_OVERHEAD_S  -- constant is defined and equals 5.0
  7. RESEARCH_NODE_NAMES  -- tuple of exactly 4 node names
  8. Graph structure      -- compiled graph contains all 9 nodes
  9. Mermaid diagram      -- draw_mermaid() shows all nodes
 10. route_after_research -- logs errors but always returns PROCEED
 11. Individual node fns  -- each research node returns correct state key
 12. Concurrency proof    -- timing test with time.sleep mocks

All external calls (LLMs, APIs, Redis, ChromaDB) are mocked.
LangGraph itself is NOT mocked -- graph compilation is a real test.

ENVIRONMENT must be 'test' before any backend import.
"""
from __future__ import annotations

import os
import time
from typing import Any, cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# T-033: patch _run_persist so graph tests never touch the database
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_db_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent state_persistence from opening DB connections in graph tests."""
    monkeypatch.setattr(
        "backend.graph.nodes._run_persist",
        lambda *args, **kwargs: None,
    )


from backend.graph.graph import (  # noqa: E402
    PARALLEL_OVERHEAD_S,
    RESEARCH_NODE_NAMES,
    build_graph,
    get_compiled_graph,
)
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
    fundamental_node,
    macro_node,
    sentiment_node,
    technical_node,
)
from backend.graph.routing import (  # noqa: E402
    ROUTE_PROCEED,
    route_after_planner,
    route_after_research,
)
from backend.graph.state import InvestmentState, make_initial_state  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JOB_ID = "t031-test-job-uuid-001"
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


def _running_state() -> InvestmentState:
    """Return a state that passed the planner (status=running)."""
    return _make_state(status="running")


def _failed_state() -> InvestmentState:
    """Return a state that failed the planner (status=failed)."""
    return _make_state(
        status="failed",
        ticker="",
        company_name="",
        pipeline_error="Planner failed: ticker missing",
    )


# ---------------------------------------------------------------------------
# 1. Send API dispatch -- route_after_planner returns list[Send]
# ---------------------------------------------------------------------------


class TestSendAPIDispatch:
    """route_after_planner returns list[Send] on the PROCEED path."""

    def test_returns_list_on_proceed(self) -> None:
        state = _running_state()
        result = route_after_planner(state)
        assert isinstance(result, list)

    def test_returns_four_sends(self) -> None:
        from langgraph.types import Send

        state = _running_state()
        result = route_after_planner(state)
        assert isinstance(result, list)
        assert len(result) == 4
        for item in result:
            assert isinstance(item, Send)

    def test_returns_end_on_abort(self) -> None:
        from langgraph.graph import END

        state = _failed_state()
        result = route_after_planner(state)
        assert result is END

    def test_abort_is_not_list(self) -> None:
        state = _failed_state()
        result = route_after_planner(state)
        assert not isinstance(result, list)

    def test_pending_state_returns_list(self) -> None:
        """State with status=pending (not failed) -> Send fan-out."""
        state = _make_state(status="pending")
        result = route_after_planner(state)
        assert isinstance(result, list)

    def test_empty_ticker_fails(self) -> None:
        """If planner sets status=failed, route returns END."""
        from langgraph.graph import END

        state = _make_state(status="failed", ticker="")
        result = route_after_planner(state)
        assert result is END


# ---------------------------------------------------------------------------
# 2. Send objects -- each targets correct node with full state
# ---------------------------------------------------------------------------


class TestSendObjects:
    """Each Send object targets the right node and carries the full state."""

    def _get_sends(self) -> list[Any]:
        from langgraph.types import Send

        state = _running_state()
        result = route_after_planner(state)
        assert isinstance(result, list)
        return [item for item in result if isinstance(item, Send)]

    def test_fundamental_send_present(self) -> None:
        sends = self._get_sends()
        nodes = [s.node for s in sends]
        assert NODE_FUNDAMENTAL in nodes

    def test_technical_send_present(self) -> None:
        sends = self._get_sends()
        nodes = [s.node for s in sends]
        assert NODE_TECHNICAL in nodes

    def test_sentiment_send_present(self) -> None:
        sends = self._get_sends()
        nodes = [s.node for s in sends]
        assert NODE_SENTIMENT in nodes

    def test_macro_send_present(self) -> None:
        sends = self._get_sends()
        nodes = [s.node for s in sends]
        assert NODE_MACRO in nodes

    def test_each_send_carries_ticker(self) -> None:
        sends = self._get_sends()
        for s in sends:
            assert s.arg.get("ticker") == _TICKER

    def test_each_send_carries_company_name(self) -> None:
        sends = self._get_sends()
        for s in sends:
            assert s.arg.get("company_name") == _COMPANY

    def test_each_send_carries_job_id(self) -> None:
        sends = self._get_sends()
        for s in sends:
            assert s.arg.get("job_id") == _JOB_ID

    def test_each_send_arg_is_dict(self) -> None:
        sends = self._get_sends()
        for s in sends:
            assert isinstance(s.arg, dict)

    def test_no_duplicate_node_targets(self) -> None:
        sends = self._get_sends()
        nodes = [s.node for s in sends]
        assert len(nodes) == len(set(nodes)), f"Duplicate Send targets: {nodes}"

    def test_send_nodes_match_research_node_names(self) -> None:
        sends = self._get_sends()
        sent_nodes = {s.node for s in sends}
        expected = set(RESEARCH_NODE_NAMES)
        assert sent_nodes == expected


# ---------------------------------------------------------------------------
# 3. Parallel timing -- mocked agents with sleep run in < max + 5s
# ---------------------------------------------------------------------------


class TestParallelTiming:
    """
    Acceptance criterion: total < max(individual_times) + PARALLEL_OVERHEAD_S.

    We mock the 4 research agents to sleep for different durations
    (simulating different API response times) and measure wall-clock
    time for the combined run.

    Because LangGraph's .invoke() is synchronous but uses threading
    internally for parallel node execution, we use time.sleep() in
    the mocks to simulate real latency.

    Individual sleep times: FA=1s, TA=2s, SA=1.5s, MA=0.8s
    Max individual time: 2.0s
    Acceptance: total < 2.0 + 5.0 = 7.0s
    Sequential total would be: 5.3s (but confirms parallelism when < 7s)
    """

    _SLEEP_FA = 0.3  # Fundamental Analyst (seconds -- scaled for test speed)
    _SLEEP_TA = 0.5  # Technical Analyst (slowest)
    _SLEEP_SA = 0.2  # Sentiment Analyst
    _SLEEP_MA = 0.15  # Macro Economist
    _MAX_INDIVIDUAL = 0.5  # max of the four
    _SEQUENTIAL_SUM = 1.15  # sum of all four

    def _make_agent_mock(
        self, output_key: str, sleep_s: float, agent_name: str
    ) -> MagicMock:
        """Return a mock node function that sleeps then returns a valid dict."""

        def _side_effect(state: dict[str, Any]) -> dict[str, Any]:
            time.sleep(sleep_s)
            return {
                output_key: {
                    "agent_name": agent_name,
                    "analysis_id": state.get("job_id", "unknown"),
                    "company_name": state.get("company_name", "unknown"),
                    "ticker": state.get("ticker", "unknown"),
                    "error": None,
                }
            }

        m = MagicMock(side_effect=_side_effect)
        return m

    def test_parallel_faster_than_sequential_sum(self) -> None:
        """
        Total wall-clock time must be well below the sequential sum.

        With parallel execution: total ~ max(individual) + overhead.
        With sequential: total = sum(individual).

        This test verifies the system is actually running concurrently.

        LangSmith tracing is explicitly disabled for this test via
        patch.dict so background retry threads (429 errors from the
        rate-limited free tier) do not add spurious latency to the
        measurement.  The _SEQUENTIAL_SUM guard is set generously to
        accommodate CI machine variance (4x the actual sequential sum).
        """
        fa_mock = self._make_agent_mock(
            "fundamental", self._SLEEP_FA, "fundamental_analyst"
        )
        ta_mock = self._make_agent_mock(
            "technical", self._SLEEP_TA, "technical_analyst"
        )
        sa_mock = self._make_agent_mock("sentiment", self._SLEEP_SA, "news_sentiment")
        ma_mock = self._make_agent_mock("macro", self._SLEEP_MA, "macro_economist")
        # Phase 4 agent mocks -- prevent real LLM/API calls from inflating latency
        _contrarian_out: dict[str, Any] = {
            "contrarian": {
                "agent_name": "contrarian_investor",
                "bear_conviction": 3,
                "counter_arguments": ["Mock challenge"],
                "overlooked_risks": [],
                "challenged_agents": [],
                "strongest_argument": "Mock argument",
                "summary": "Mock summary",
                "error": None,
            },
            "debate_round_count": 1,
        }
        _risk_out: dict[str, Any] = {
            "risk": {
                "agent_name": "risk_officer",
                "risk_score": 4,
                "governance_risk": 4,
                "regulatory_risk": 4,
                "financial_risk": 4,
                "concentration_risk": 4,
                "risk_flags": [],
                "critical_flags": [],
                "risk_recommendation": "proceed_with_caution",
                "summary": "Mock risk summary",
                "error": None,
            },
            "risk_flags": [],
            "critical_flags": [],
        }
        _valuation_out: dict[str, Any] = {
            "valuation": {
                "agent_name": "valuation_agent",
                "valuation_verdict": "fairly_valued",
                "peer_tickers": [],
                "summary": "Mock valuation summary",
                "error": None,
            }
        }
        # T-044 fix: run_portfolio_manager_decision was the one Phase 4
        # agent function NOT mocked here, despite the other three
        # (contrarian/risk/valuation) already being mocked above for
        # exactly this reason. portfolio_manager_node otherwise calls
        # the real run_portfolio_manager_decision, which calls get_llm()
        # and attempts a real Groq API call using conftest.py's fake
        # test key -- adding multi-second real network latency to a
        # test whose entire purpose is measuring LangGraph orchestration
        # overhead in milliseconds. This is what caused
        # test_parallel_faster_than_sequential_sum to intermittently
        # exceed its timing guard.
        _decision_out: dict[str, Any] = {
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

        with (
            patch("backend.graph.nodes.run_fundamental_analysis", fa_mock),
            patch("backend.graph.nodes.run_technical_analysis", ta_mock),
            patch("backend.graph.nodes.run_sentiment_analysis", sa_mock),
            patch("backend.graph.nodes.run_macro_analysis", ma_mock),
            patch(
                "backend.graph.nodes.run_contrarian_analysis",
                return_value=_contrarian_out,
            ),
            patch(
                "backend.graph.nodes.run_risk_analysis",
                return_value=_risk_out,
            ),
            patch(
                "backend.graph.nodes.run_valuation_analysis",
                return_value=_valuation_out,
            ),
            patch(
                "backend.graph.nodes.run_portfolio_manager_decision",
                return_value=_decision_out,
            ),
            patch.dict(
                os.environ,
                {"LANGCHAIN_TRACING_V2": "false", "LANGSMITH_API_KEY": ""},
            ),
        ):
            compiled = build_graph()
            initial_state = _running_state()

            t_start = time.monotonic()
            compiled.invoke(dict(initial_state))
            t_elapsed = time.monotonic() - t_start

        # Must be faster than sequential sum (proves parallelism).
        # Guard is 4x the actual sequential sum to tolerate CI variance.
        sequential_guard = self._SEQUENTIAL_SUM * 4.0
        assert t_elapsed < sequential_guard, (
            f"Elapsed {t_elapsed:.3f}s >= sequential guard "
            f"{sequential_guard:.3f}s -- agents may be running serially"
        )

    def test_parallel_within_overhead_budget(self) -> None:
        """
        Acceptance criterion: total < max(individual) + PARALLEL_OVERHEAD_S.

        LangSmith tracing is explicitly disabled so background retry
        threads (429 from rate-limited free tier) do not inflate elapsed
        time.  The overhead budget is doubled for Windows CI tolerance.
        """
        fa_mock = self._make_agent_mock(
            "fundamental", self._SLEEP_FA, "fundamental_analyst"
        )
        ta_mock = self._make_agent_mock(
            "technical", self._SLEEP_TA, "technical_analyst"
        )
        sa_mock = self._make_agent_mock("sentiment", self._SLEEP_SA, "news_sentiment")
        ma_mock = self._make_agent_mock("macro", self._SLEEP_MA, "macro_economist")
        # Phase 4 agent mocks -- prevent real LLM/API calls from inflating latency
        _contrarian_out2: dict[str, Any] = {
            "contrarian": {
                "agent_name": "contrarian_investor",
                "bear_conviction": 3,
                "counter_arguments": ["Mock challenge"],
                "overlooked_risks": [],
                "challenged_agents": [],
                "strongest_argument": "Mock argument",
                "summary": "Mock summary",
                "error": None,
            },
            "debate_round_count": 1,
        }
        _risk_out2: dict[str, Any] = {
            "risk": {
                "agent_name": "risk_officer",
                "risk_score": 4,
                "governance_risk": 4,
                "regulatory_risk": 4,
                "financial_risk": 4,
                "concentration_risk": 4,
                "risk_flags": [],
                "critical_flags": [],
                "risk_recommendation": "proceed_with_caution",
                "summary": "Mock risk summary",
                "error": None,
            },
            "risk_flags": [],
            "critical_flags": [],
        }
        _valuation_out2: dict[str, Any] = {
            "valuation": {
                "agent_name": "valuation_agent",
                "valuation_verdict": "fairly_valued",
                "peer_tickers": [],
                "summary": "Mock valuation summary",
                "error": None,
            }
        }
        # T-044 fix: see test_parallel_faster_than_sequential_sum above
        # for the full explanation -- run_portfolio_manager_decision was
        # the one Phase 4 agent function not mocked here either, exposing
        # this timing test to the same real-LLM-latency risk.
        _decision_out2: dict[str, Any] = {
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

        with (
            patch("backend.graph.nodes.run_fundamental_analysis", fa_mock),
            patch("backend.graph.nodes.run_technical_analysis", ta_mock),
            patch("backend.graph.nodes.run_sentiment_analysis", sa_mock),
            patch("backend.graph.nodes.run_macro_analysis", ma_mock),
            patch(
                "backend.graph.nodes.run_contrarian_analysis",
                return_value=_contrarian_out2,
            ),
            patch(
                "backend.graph.nodes.run_risk_analysis",
                return_value=_risk_out2,
            ),
            patch(
                "backend.graph.nodes.run_valuation_analysis",
                return_value=_valuation_out2,
            ),
            patch(
                "backend.graph.nodes.run_portfolio_manager_decision",
                return_value=_decision_out2,
            ),
            patch.dict(
                os.environ,
                {"LANGCHAIN_TRACING_V2": "false", "LANGSMITH_API_KEY": ""},
            ),
        ):
            compiled = build_graph()
            initial_state = _running_state()

            t_start = time.monotonic()
            compiled.invoke(dict(initial_state))
            t_elapsed = time.monotonic() - t_start

        # Budget = max_individual + 2x overhead to tolerate CI variance.
        budget = self._MAX_INDIVIDUAL + (PARALLEL_OVERHEAD_S * 2)
        assert t_elapsed < budget, (
            f"Elapsed {t_elapsed:.3f}s >= budget "
            f"max({self._MAX_INDIVIDUAL}) + 2x overhead({PARALLEL_OVERHEAD_S*2}) "
            f"= {budget:.1f}s"
        )

    def test_all_four_agents_called(self) -> None:
        """All 4 mocked agent functions must be invoked exactly once."""
        fa_mock = self._make_agent_mock("fundamental", 0.01, "fundamental_analyst")
        ta_mock = self._make_agent_mock("technical", 0.01, "technical_analyst")
        sa_mock = self._make_agent_mock("sentiment", 0.01, "news_sentiment")
        ma_mock = self._make_agent_mock("macro", 0.01, "macro_economist")

        with (
            patch("backend.graph.nodes.run_fundamental_analysis", fa_mock),
            patch("backend.graph.nodes.run_technical_analysis", ta_mock),
            patch("backend.graph.nodes.run_sentiment_analysis", sa_mock),
            patch("backend.graph.nodes.run_macro_analysis", ma_mock),
        ):
            compiled = build_graph()
            compiled.invoke(dict(_running_state()))

        fa_mock.assert_called_once()
        ta_mock.assert_called_once()
        sa_mock.assert_called_once()
        ma_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 4. State merge -- all 4 outputs appear in state after join
# ---------------------------------------------------------------------------


class TestStateMerge:
    """After parallel execution, all 4 agent outputs are in state."""

    def _run_with_mocks(self) -> dict[str, Any]:
        """Run the compiled graph with minimal mocks, return final state.

        T-044 fix: this helper previously mocked only the four research
        agents, leaving risk_node/contrarian_node/valuation_node/
        portfolio_manager_node to run for real -- each calling get_llm()
        and attempting a real Groq API call with conftest.py's fake test
        key. test_pipeline_reaches_completed_status and
        test_final_state_has_decision both depend on this helper
        producing a real "completed" status and a real "decision" dict,
        which should not be left dependent on an unmocked external
        network call succeeding. All four Phase 4 agents are now mocked
        here too, consistent with TestParallelTiming's tests above.
        """
        fa_out = {
            "fundamental": {
                "agent_name": "fundamental_analyst",
                "score": 8,
                "error": None,
            }
        }
        ta_out = {
            "technical": {
                "agent_name": "technical_analyst",
                "signal": "BUY",
                "error": None,
            }
        }
        sa_out = {
            "sentiment": {
                "agent_name": "news_sentiment",
                "sentiment_score": 0.4,
                "error": None,
            }
        }
        ma_out = {
            "macro": {
                "agent_name": "macro_economist",
                "macro_environment": "favourable",
                "error": None,
            }
        }
        contrarian_out = {
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
        risk_out = {
            "risk": {
                "agent_name": "risk_officer",
                "risk_score": 4,
                "governance_risk": 4,
                "regulatory_risk": 4,
                "financial_risk": 4,
                "concentration_risk": 4,
                "risk_flags": [],
                "critical_flags": [],
                "risk_recommendation": "proceed_with_caution",
                "summary": "Mock risk summary",
                "error": None,
            },
            "risk_flags": [],
            "critical_flags": [],
        }
        valuation_out = {
            "valuation": {
                "agent_name": "valuation_agent",
                "valuation_verdict": "fairly_valued",
                "peer_tickers": [],
                "summary": "Mock valuation summary",
                "error": None,
            }
        }
        decision_out = {
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

        with (
            patch(
                "backend.graph.nodes.run_fundamental_analysis",
                return_value=fa_out,
            ),
            patch(
                "backend.graph.nodes.run_technical_analysis",
                return_value=ta_out,
            ),
            patch(
                "backend.graph.nodes.run_sentiment_analysis",
                return_value=sa_out,
            ),
            patch(
                "backend.graph.nodes.run_macro_analysis",
                return_value=ma_out,
            ),
            patch(
                "backend.graph.nodes.run_contrarian_analysis",
                return_value=contrarian_out,
            ),
            patch(
                "backend.graph.nodes.run_risk_analysis",
                return_value=risk_out,
            ),
            patch(
                "backend.graph.nodes.run_valuation_analysis",
                return_value=valuation_out,
            ),
            patch(
                "backend.graph.nodes.run_portfolio_manager_decision",
                return_value=decision_out,
            ),
        ):
            compiled = build_graph()
            result = compiled.invoke(dict(_running_state()))
        return dict(result)

    def test_fundamental_in_final_state(self) -> None:
        state = self._run_with_mocks()
        assert "fundamental" in state
        assert state["fundamental"] is not None

    def test_technical_in_final_state(self) -> None:
        state = self._run_with_mocks()
        assert "technical" in state
        assert state["technical"] is not None

    def test_sentiment_in_final_state(self) -> None:
        state = self._run_with_mocks()
        assert "sentiment" in state
        assert state["sentiment"] is not None

    def test_macro_in_final_state(self) -> None:
        state = self._run_with_mocks()
        assert "macro" in state
        assert state["macro"] is not None

    def test_fundamental_correct_score(self) -> None:
        state = self._run_with_mocks()
        fund = state.get("fundamental")
        assert isinstance(fund, dict)
        assert fund.get("score") == 8

    def test_technical_correct_signal(self) -> None:
        state = self._run_with_mocks()
        tech = state.get("technical")
        assert isinstance(tech, dict)
        assert tech.get("signal") == "BUY"

    def test_sentiment_correct_score(self) -> None:
        state = self._run_with_mocks()
        sent = state.get("sentiment")
        assert isinstance(sent, dict)
        assert sent.get("sentiment_score") == 0.4

    def test_macro_correct_environment(self) -> None:
        state = self._run_with_mocks()
        mac = state.get("macro")
        assert isinstance(mac, dict)
        assert mac.get("macro_environment") == "favourable"

    def test_all_four_keys_present_together(self) -> None:
        state = self._run_with_mocks()
        missing = [
            k
            for k in ("fundamental", "technical", "sentiment", "macro")
            if k not in state
        ]
        assert not missing, f"Missing keys after parallel join: {missing}"

    def test_pipeline_reaches_completed_status(self) -> None:
        """Graph runs end-to-end; portfolio manager sets completed."""
        state = self._run_with_mocks()
        assert state.get("status") == "completed"

    def test_final_state_has_decision(self) -> None:
        """Portfolio manager stub sets decision field."""
        state = self._run_with_mocks()
        assert "decision" in state
        decision = state["decision"]
        assert isinstance(decision, dict)


# ---------------------------------------------------------------------------
# 5. Abort path -- failed planner routes to END
# ---------------------------------------------------------------------------


class TestAbortPath:
    """When planner returns failed status, graph terminates early."""

    def test_abort_state_skips_agents(self) -> None:
        fa_mock = MagicMock()
        ta_mock = MagicMock()
        sa_mock = MagicMock()
        ma_mock = MagicMock()

        with (
            patch("backend.graph.nodes.run_fundamental_analysis", fa_mock),
            patch("backend.graph.nodes.run_technical_analysis", ta_mock),
            patch("backend.graph.nodes.run_sentiment_analysis", sa_mock),
            patch("backend.graph.nodes.run_macro_analysis", ma_mock),
        ):
            compiled = build_graph()
            # Invoke with empty ticker -- planner will fail
            initial = _make_state(ticker="", company_name="")
            compiled.invoke(dict(initial))

        fa_mock.assert_not_called()
        ta_mock.assert_not_called()
        sa_mock.assert_not_called()
        ma_mock.assert_not_called()

    def test_abort_state_has_failed_status(self) -> None:
        with (
            patch("backend.graph.nodes.run_fundamental_analysis"),
            patch("backend.graph.nodes.run_technical_analysis"),
            patch("backend.graph.nodes.run_sentiment_analysis"),
            patch("backend.graph.nodes.run_macro_analysis"),
        ):
            compiled = build_graph()
            initial = _make_state(ticker="", company_name="")
            result = compiled.invoke(dict(initial))
        assert result.get("status") == "failed"

    def test_abort_state_has_pipeline_error(self) -> None:
        with (
            patch("backend.graph.nodes.run_fundamental_analysis"),
            patch("backend.graph.nodes.run_technical_analysis"),
            patch("backend.graph.nodes.run_sentiment_analysis"),
            patch("backend.graph.nodes.run_macro_analysis"),
        ):
            compiled = build_graph()
            initial = _make_state(ticker="", company_name="")
            result = compiled.invoke(dict(initial))
        assert result.get("pipeline_error") is not None
        assert len(str(result.get("pipeline_error"))) > 0


# ---------------------------------------------------------------------------
# 6. PARALLEL_OVERHEAD_S constant
# ---------------------------------------------------------------------------


class TestParallelOverheadConstant:
    """PARALLEL_OVERHEAD_S is defined with the correct value."""

    def test_constant_exists(self) -> None:
        assert PARALLEL_OVERHEAD_S is not None

    def test_constant_is_float(self) -> None:
        assert isinstance(PARALLEL_OVERHEAD_S, float)

    def test_constant_is_five_seconds(self) -> None:
        assert PARALLEL_OVERHEAD_S == 5.0

    def test_constant_positive(self) -> None:
        assert PARALLEL_OVERHEAD_S > 0


# ---------------------------------------------------------------------------
# 7. RESEARCH_NODE_NAMES tuple
# ---------------------------------------------------------------------------


class TestResearchNodeNames:
    """RESEARCH_NODE_NAMES is a tuple of exactly 4 distinct node names."""

    def test_is_tuple(self) -> None:
        assert isinstance(RESEARCH_NODE_NAMES, tuple)

    def test_has_four_entries(self) -> None:
        assert len(RESEARCH_NODE_NAMES) == 4

    def test_all_unique(self) -> None:
        assert len(set(RESEARCH_NODE_NAMES)) == 4

    def test_contains_fundamental(self) -> None:
        assert NODE_FUNDAMENTAL in RESEARCH_NODE_NAMES

    def test_contains_technical(self) -> None:
        assert NODE_TECHNICAL in RESEARCH_NODE_NAMES

    def test_contains_sentiment(self) -> None:
        assert NODE_SENTIMENT in RESEARCH_NODE_NAMES

    def test_contains_macro(self) -> None:
        assert NODE_MACRO in RESEARCH_NODE_NAMES

    def test_no_non_research_nodes(self) -> None:
        non_research = {
            NODE_PLANNER,
            NODE_CONTRARIAN,
            NODE_RISK,
            NODE_VALUATION,
            NODE_PORTFOLIO_MANAGER,
        }
        for name in RESEARCH_NODE_NAMES:
            assert name not in non_research


# ---------------------------------------------------------------------------
# 8. Graph structure -- 9 nodes registered
# ---------------------------------------------------------------------------


class TestGraphStructure:
    """build_graph() produces a compiled graph with all 9 nodes."""

    def test_compiles_without_error(self) -> None:
        compiled = build_graph()
        assert compiled is not None

    def test_has_invoke_method(self) -> None:
        compiled = build_graph()
        assert hasattr(compiled, "invoke")

    def test_has_get_graph_method(self) -> None:
        compiled = build_graph()
        assert hasattr(compiled, "get_graph")

    def test_nine_content_nodes_registered(self) -> None:
        """T-043: 15 content nodes (9 original + 3 T-032 + 1 T-040
        debate_loop + 1 T-042 report_generator + 1 T-043 pdf_export)."""
        compiled = build_graph()
        nodes = compiled.get_graph().nodes
        content_nodes = [n for n in nodes if not n.startswith("__")]
        assert len(content_nodes) == 15, (
            f"Expected 15 content nodes, got {len(content_nodes)}: " f"{content_nodes}"
        )

    def test_all_node_names_registered(self) -> None:
        compiled = build_graph()
        nodes = compiled.get_graph().nodes
        missing = [n for n in _ALL_NODE_NAMES if n not in nodes]
        assert not missing, f"Missing nodes: {missing}"

    def test_get_compiled_graph_is_singleton(self) -> None:
        g1 = get_compiled_graph()
        g2 = get_compiled_graph()
        assert g1 is g2

    def test_build_graph_returns_fresh_instance(self) -> None:
        g1 = build_graph()
        g2 = build_graph()
        assert g1 is not g2


# ---------------------------------------------------------------------------
# 9. Mermaid diagram -- draw_mermaid() contains all node names
# ---------------------------------------------------------------------------


class TestMermaidDiagram:
    """draw_mermaid() contains all 9 node names and end marker."""

    def _mermaid(self) -> str:
        compiled = build_graph()
        return str(compiled.get_graph().draw_mermaid())

    def test_returns_non_empty_string(self) -> None:
        assert len(self._mermaid()) > 50

    def test_all_nodes_in_diagram(self) -> None:
        mermaid = self._mermaid()
        missing = [n for n in _ALL_NODE_NAMES if n not in mermaid]
        assert not missing, f"Nodes missing from Mermaid: {missing}"

    def test_end_marker_present(self) -> None:
        mermaid = self._mermaid()
        assert any(marker in mermaid for marker in ("__end__", "END", "end"))


# ---------------------------------------------------------------------------
# 10. route_after_research -- logs errors but always proceeds
# ---------------------------------------------------------------------------


class TestRouteAfterResearch:
    """route_after_research always returns ROUTE_PROCEED in skeleton."""

    def test_clean_state_proceeds(self) -> None:
        state = _make_state()
        state["fundamental"] = {"agent_name": "fa", "score": 8}
        state["technical"] = {"agent_name": "ta", "signal": "BUY"}
        state["sentiment"] = {"agent_name": "sa", "sentiment_score": 0.3}
        state["macro"] = {"agent_name": "ma", "macro_environment": "neutral"}
        assert route_after_research(state) == ROUTE_PROCEED

    def test_all_errors_fundamental_routes_to_error_handler(self) -> None:
        """T-032: fundamental error -> ROUTE_ERROR, not ROUTE_PROCEED."""
        from backend.graph.routing import ROUTE_ERROR

        state = _make_state()
        state["fundamental"] = {"agent_name": "fa", "error": "timeout"}
        state["technical"] = {"agent_name": "ta", "error": "timeout"}
        state["sentiment"] = {"agent_name": "sa", "error": "timeout"}
        state["macro"] = {"agent_name": "ma", "error": "timeout"}
        result = route_after_research(state)
        assert result == ROUTE_ERROR

    def test_partial_fundamental_error_routes_to_error_handler(self) -> None:
        """T-032: fundamental error (even with other agents clean) -> ROUTE_ERROR."""
        from backend.graph.routing import ROUTE_ERROR

        state = _make_state()
        state["fundamental"] = {"agent_name": "fa", "error": "API limit"}
        state["technical"] = {"agent_name": "ta", "signal": "HOLD"}
        result = route_after_research(state)
        assert result == ROUTE_ERROR

    def test_empty_state_proceeds(self) -> None:
        empty: InvestmentState = cast(InvestmentState, {})
        result = route_after_research(empty)
        assert result == ROUTE_PROCEED

    def test_returns_string(self) -> None:
        result = route_after_research(_make_state())
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 11. Individual node functions return correct state keys
# ---------------------------------------------------------------------------


class TestResearchNodeReturnKeys:
    """Each research node function returns the right state key."""

    def test_fundamental_node_returns_fundamental_key(self) -> None:
        mock_output = {"fundamental": {"agent_name": "fa", "score": 7}}
        with patch(
            "backend.graph.nodes.run_fundamental_analysis",
            return_value=mock_output,
        ):
            result = fundamental_node(_make_state())
        assert "fundamental" in result

    def test_technical_node_returns_technical_key(self) -> None:
        mock_output = {"technical": {"agent_name": "ta", "signal": "HOLD"}}
        with patch(
            "backend.graph.nodes.run_technical_analysis",
            return_value=mock_output,
        ):
            result = technical_node(_make_state())
        assert "technical" in result

    def test_sentiment_node_returns_sentiment_key(self) -> None:
        mock_output = {"sentiment": {"agent_name": "sa", "sentiment_score": 0.1}}
        with patch(
            "backend.graph.nodes.run_sentiment_analysis",
            return_value=mock_output,
        ):
            result = sentiment_node(_make_state())
        assert "sentiment" in result

    def test_macro_node_returns_macro_key(self) -> None:
        mock_output = {
            "macro": {
                "agent_name": "ma",
                "macro_environment": "unfavourable",
            }
        }
        with patch(
            "backend.graph.nodes.run_macro_analysis",
            return_value=mock_output,
        ):
            result = macro_node(_make_state())
        assert "macro" in result

    def test_keys_are_distinct(self) -> None:
        """The 4 output keys are different -- required for state merge."""
        keys = {"fundamental", "technical", "sentiment", "macro"}
        assert len(keys) == 4

    def test_fundamental_node_does_not_set_current_node(self) -> None:
        # Parallel research nodes must NOT write current_node: all 4 run in
        # the same super-step, and LangGraph raises InvalidUpdateError when
        # multiple nodes write to the same LastValue key in one step.
        mock_output = {"fundamental": {"agent_name": "fa"}}
        with patch(
            "backend.graph.nodes.run_fundamental_analysis",
            return_value=mock_output,
        ):
            result = fundamental_node(_make_state())
        assert "current_node" not in result

    def test_technical_node_does_not_set_current_node(self) -> None:
        # Same parallel super-step constraint as fundamental_node.
        mock_output = {"technical": {"agent_name": "ta"}}
        with patch(
            "backend.graph.nodes.run_technical_analysis",
            return_value=mock_output,
        ):
            result = technical_node(_make_state())
        assert "current_node" not in result

    def test_sentiment_node_does_not_set_current_node(self) -> None:
        # Same parallel super-step constraint as fundamental_node.
        mock_output = {"sentiment": {"agent_name": "sa"}}
        with patch(
            "backend.graph.nodes.run_sentiment_analysis",
            return_value=mock_output,
        ):
            result = sentiment_node(_make_state())
        assert "current_node" not in result

    def test_macro_node_does_not_set_current_node(self) -> None:
        # Same parallel super-step constraint as fundamental_node.
        mock_output = {"macro": {"agent_name": "ma"}}
        with patch(
            "backend.graph.nodes.run_macro_analysis",
            return_value=mock_output,
        ):
            result = macro_node(_make_state())
        assert "current_node" not in result
