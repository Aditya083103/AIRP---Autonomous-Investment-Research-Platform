# backend/tests/unit/test_ws_broadcast_nodes.py
"""
Unit tests for T-049: the WebSocket broadcast additions to
backend/graph/nodes.py (_run_broadcast, _build_output_preview,
_summarise_agent_output, and _persist_after's new second
fire-and-forget call).

Acceptance criteria (from project plan, T-049):
  - WebSocket sends event per agent completion
  - frontend receives and displays in order
  - connection closes cleanly

This file is the backend.graph.nodes-side counterpart to
test_ws_broadcaster.py (which covers the broadcaster module in
isolation) and test_websocket_router.py (which covers the WS route
handler). Together the three files cover the full path from "a
LangGraph node finishes" to "a WebSocket client receives the event in
order."

Test strategy
-------------
  1. _build_output_preview -- one test per node category: an agent
     output field present, error present (overrides the headline),
     report_generator/pdf_export/research_join/planner's bespoke
     branches, and the generic node_name fallback
  2. _summarise_agent_output -- the per-node headline-field dispatch
     table, plus its own fallback when the expected field is absent
  3. _run_broadcast -- calls publish_event with a correctly-shaped
     AgentStreamEvent; progress_percent matches
     backend.services.analysis.compute_progress exactly; is_final is
     True only for pdf_export or status='failed'; never raises even
     when ws_broadcaster.publish_event itself raises
  4. _persist_after integration -- the wrapper now calls BOTH
     _run_persist and _run_broadcast; a _run_broadcast failure does not
     prevent _run_persist (or vice versa) and does not propagate
  5. End-to-end ordering -- subscribing before invoking a real
     sequential node function delivers an event in the broadcaster
     queue, proving the node -> _persist_after -> _run_broadcast ->
     ws_broadcaster.publish_event chain is wired correctly

All external calls (DB, LLMs, Redis, APIs) are mocked or bypassed via
patching _run_persist, matching the existing T-033 test convention
(see test_state_persistence.py's identical pattern). ws_broadcaster
itself is NOT mocked in most tests here -- it is pure in-memory
asyncio, the same reasoning backend.graph.nodes' own module docstring
gives for why it does not need DB-style hermetic patching.
ENVIRONMENT must be set to 'test' before any backend import.
"""

import asyncio
from collections.abc import Generator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from backend.graph.state import InvestmentState, make_initial_state
from backend.services.ws_broadcaster import _reset_for_testing, subscribe

_JOB_ID = "t049-test-job-uuid-001"
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"


def _make_state(**overrides: Any) -> InvestmentState:
    state = make_initial_state(
        job_id=_JOB_ID,
        company_name=_COMPANY,
        ticker=_TICKER,
        exchange="NSE",
        raw_query="TCS",
    )
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


@pytest.fixture(autouse=True)
def _clean_broadcaster_registry() -> Generator[None, None, None]:
    """Mirrors test_ws_broadcaster.py's _clean_registry fixture -- the
    broadcaster registry is process-wide state, so every test in this
    file must start and end with an empty registry."""
    _reset_for_testing()
    yield
    _reset_for_testing()


# ---------------------------------------------------------------------------
# 1. _build_output_preview
# ---------------------------------------------------------------------------


class TestBuildOutputPreview:
    def test_risk_officer_success_includes_score(self) -> None:
        from backend.graph.nodes import NODE_RISK, _build_output_preview

        state = _make_state(
            risk={
                "agent_name": "risk_officer",
                "error": None,
                "risk_score": 4,
                "risk_flags": ["x"],
            }
        )
        preview = _build_output_preview(NODE_RISK, state)
        assert "4/10" in preview

    def test_risk_officer_error_overrides_headline_field(self) -> None:
        from backend.graph.nodes import NODE_RISK, _build_output_preview

        state = _make_state(
            risk={
                "agent_name": "risk_officer",
                "error": "data source unavailable",
                "risk_score": 0,
            }
        )
        preview = _build_output_preview(NODE_RISK, state)
        assert preview.startswith("Failed:")
        assert "data source unavailable" in preview

    def test_contrarian_success_includes_bear_conviction(self) -> None:
        from backend.graph.nodes import NODE_CONTRARIAN, _build_output_preview

        state = _make_state(
            contrarian={
                "agent_name": "contrarian_investor",
                "error": None,
                "bear_conviction": 7,
            }
        )
        preview = _build_output_preview(NODE_CONTRARIAN, state)
        assert "7/10" in preview

    def test_valuation_success_includes_verdict(self) -> None:
        from backend.graph.nodes import NODE_VALUATION, _build_output_preview

        state = _make_state(
            valuation={
                "agent_name": "valuation_agent",
                "error": None,
                "valuation_verdict": "UNDERVALUED",
            }
        )
        preview = _build_output_preview(NODE_VALUATION, state)
        assert "UNDERVALUED" in preview

    def test_portfolio_manager_success_includes_verdict_and_conviction(self) -> None:
        from backend.graph.nodes import NODE_PORTFOLIO_MANAGER, _build_output_preview

        state = _make_state(
            decision={
                "agent_name": "portfolio_manager",
                "error": None,
                "verdict": "BUY",
                "conviction_score": 8,
            }
        )
        preview = _build_output_preview(NODE_PORTFOLIO_MANAGER, state)
        assert "BUY" in preview
        assert "8/10" in preview

    def test_report_generator_with_memo_present(self) -> None:
        from backend.graph.nodes import NODE_REPORT_GENERATOR, _build_output_preview

        state = _make_state(memo_markdown="# Investment Memo\n...")
        preview = _build_output_preview(NODE_REPORT_GENERATOR, state)
        assert "memo" in preview.lower() or "Memo" in preview

    def test_report_generator_without_memo(self) -> None:
        from backend.graph.nodes import NODE_REPORT_GENERATOR, _build_output_preview

        state = _make_state()
        preview = _build_output_preview(NODE_REPORT_GENERATOR, state)
        assert preview  # non-empty fallback

    def test_pdf_export_with_path_present(self) -> None:
        from backend.graph.nodes import NODE_PDF_EXPORT, _build_output_preview

        state = _make_state(memo_pdf_path="/tmp/memo.pdf")
        preview = _build_output_preview(NODE_PDF_EXPORT, state)
        assert "/tmp/memo.pdf" in preview

    def test_pdf_export_without_path(self) -> None:
        from backend.graph.nodes import NODE_PDF_EXPORT, _build_output_preview

        state = _make_state(memo_pdf_path=None)
        preview = _build_output_preview(NODE_PDF_EXPORT, state)
        assert preview  # non-empty fallback

    def test_research_join_returns_fixed_message(self) -> None:
        from backend.graph.nodes import NODE_RESEARCH_JOIN, _build_output_preview

        preview = _build_output_preview(NODE_RESEARCH_JOIN, _make_state())
        assert "research" in preview.lower()

    def test_planner_includes_company_name(self) -> None:
        from backend.graph.nodes import NODE_PLANNER, _build_output_preview

        preview = _build_output_preview(NODE_PLANNER, _make_state())
        assert _COMPANY in preview

    def test_unknown_node_falls_back_to_generic_message(self) -> None:
        from backend.graph.nodes import _build_output_preview

        preview = _build_output_preview("some_future_node", _make_state())
        assert preview == "some_future_node completed"

    def test_preview_is_truncated_to_max_length(self) -> None:
        from backend.graph.nodes import (
            _OUTPUT_PREVIEW_MAX_CHARS,
            NODE_VALUATION,
            _build_output_preview,
        )

        long_verdict = "X" * 500
        state = _make_state(
            valuation={
                "agent_name": "valuation_agent",
                "error": None,
                "valuation_verdict": long_verdict,
            }
        )
        preview = _build_output_preview(NODE_VALUATION, state)
        assert len(preview) <= _OUTPUT_PREVIEW_MAX_CHARS

    def test_preview_never_empty_for_any_known_node(self) -> None:
        from backend.graph.nodes import (
            NODE_CONTRARIAN,
            NODE_ERROR_HANDLER,
            NODE_PDF_EXPORT,
            NODE_PLANNER,
            NODE_PORTFOLIO_MANAGER,
            NODE_REPORT_GENERATOR,
            NODE_RESEARCH_JOIN,
            NODE_RISK,
            NODE_SENTIMENT_ESCALATION,
            NODE_VALUATION,
            _build_output_preview,
        )

        state = _make_state()
        for node_name in (
            NODE_PLANNER,
            NODE_RESEARCH_JOIN,
            NODE_ERROR_HANDLER,
            NODE_SENTIMENT_ESCALATION,
            NODE_RISK,
            NODE_CONTRARIAN,
            NODE_VALUATION,
            NODE_PORTFOLIO_MANAGER,
            NODE_REPORT_GENERATOR,
            NODE_PDF_EXPORT,
        ):
            assert _build_output_preview(node_name, state)


# ---------------------------------------------------------------------------
# 2. _summarise_agent_output
# ---------------------------------------------------------------------------


class TestSummariseAgentOutput:
    def test_risk_officer_missing_score_falls_back(self) -> None:
        from backend.graph.nodes import NODE_RISK, _summarise_agent_output

        result = _summarise_agent_output(NODE_RISK, {})
        assert result == f"{NODE_RISK} output ready"

    def test_contrarian_missing_conviction_falls_back(self) -> None:
        from backend.graph.nodes import NODE_CONTRARIAN, _summarise_agent_output

        result = _summarise_agent_output(NODE_CONTRARIAN, {})
        assert result == f"{NODE_CONTRARIAN} output ready"

    def test_valuation_missing_verdict_falls_back(self) -> None:
        from backend.graph.nodes import NODE_VALUATION, _summarise_agent_output

        result = _summarise_agent_output(NODE_VALUATION, {})
        assert result == f"{NODE_VALUATION} output ready"

    def test_portfolio_manager_missing_fields_falls_back(self) -> None:
        from backend.graph.nodes import NODE_PORTFOLIO_MANAGER, _summarise_agent_output

        result = _summarise_agent_output(NODE_PORTFOLIO_MANAGER, {"verdict": "BUY"})
        assert result == f"{NODE_PORTFOLIO_MANAGER} output ready"

    def test_unrecognised_node_falls_back(self) -> None:
        from backend.graph.nodes import _summarise_agent_output

        result = _summarise_agent_output("some_other_node", {"score": 9})
        assert result == "some_other_node output ready"


# ---------------------------------------------------------------------------
# 3. _run_broadcast
# ---------------------------------------------------------------------------


class TestRunBroadcast:
    def test_calls_publish_event_once(self) -> None:
        from backend.graph.nodes import NODE_PLANNER, _run_broadcast

        state = _make_state(status="running")
        with patch("backend.services.ws_broadcaster.publish_event") as mock_publish:
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_PLANNER, merged=state)
        mock_publish.assert_called_once()

    def test_event_job_id_matches(self) -> None:
        from backend.graph.nodes import NODE_PLANNER, _run_broadcast

        state = _make_state(status="running")
        with patch("backend.services.ws_broadcaster.publish_event") as mock_publish:
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_PLANNER, merged=state)
        _, kwargs = mock_publish.call_args
        assert kwargs["event"]["job_id"] == _JOB_ID

    def test_event_agent_matches_node_name(self) -> None:
        from backend.graph.nodes import NODE_RISK, _run_broadcast

        state = _make_state(status="running")
        with patch("backend.services.ws_broadcaster.publish_event") as mock_publish:
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_RISK, merged=state)
        _, kwargs = mock_publish.call_args
        assert kwargs["event"]["agent"] == NODE_RISK

    def test_progress_percent_matches_compute_progress(self) -> None:
        from backend.graph.nodes import NODE_VALUATION, _run_broadcast
        from backend.services.analysis import compute_progress

        state = _make_state(status="running")
        with patch("backend.services.ws_broadcaster.publish_event") as mock_publish:
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_VALUATION, merged=state)
        _, kwargs = mock_publish.call_args

        _, _, expected_percent = compute_progress(
            last_completed_node=NODE_VALUATION, status="running"
        )
        assert kwargs["event"]["progress_percent"] == expected_percent

    def test_pdf_export_sets_is_final_true(self) -> None:
        from backend.graph.nodes import NODE_PDF_EXPORT, _run_broadcast

        state = _make_state(status="completed")
        with patch("backend.services.ws_broadcaster.publish_event") as mock_publish:
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_PDF_EXPORT, merged=state)
        _, kwargs = mock_publish.call_args
        assert kwargs["event"]["is_final"] is True

    def test_failed_status_sets_is_final_true_on_any_node(self) -> None:
        from backend.graph.nodes import NODE_VALUATION, _run_broadcast

        state = _make_state(status="failed")
        with patch("backend.services.ws_broadcaster.publish_event") as mock_publish:
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_VALUATION, merged=state)
        _, kwargs = mock_publish.call_args
        assert kwargs["event"]["is_final"] is True

    def test_non_terminal_node_sets_is_final_false(self) -> None:
        from backend.graph.nodes import NODE_RISK, _run_broadcast

        state = _make_state(status="running")
        with patch("backend.services.ws_broadcaster.publish_event") as mock_publish:
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_RISK, merged=state)
        _, kwargs = mock_publish.call_args
        assert kwargs["event"]["is_final"] is False

    def test_never_raises_when_publish_event_raises(self) -> None:
        from backend.graph.nodes import NODE_PLANNER, _run_broadcast

        state = _make_state(status="running")
        with patch(
            "backend.services.ws_broadcaster.publish_event",
            side_effect=RuntimeError("registry exploded"),
        ):
            # Must not raise.
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_PLANNER, merged=state)

    def test_never_raises_when_compute_progress_raises(self) -> None:
        from backend.graph.nodes import NODE_PLANNER, _run_broadcast

        state = _make_state(status="running")
        with patch(
            "backend.services.analysis.compute_progress",
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise.
            _run_broadcast(job_id=_JOB_ID, node_name=NODE_PLANNER, merged=state)


# ---------------------------------------------------------------------------
# 4. _persist_after now calls both _run_persist and _run_broadcast
# ---------------------------------------------------------------------------


class TestPersistAfterCallsBothPersistAndBroadcast:
    def test_wrapper_calls_run_persist_and_run_broadcast(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(
            return_value={"current_node": "planner", "status": "running"}
        )
        wrapped = _persist_after(mock_fn, "planner")
        state = _make_state()
        with (
            patch("backend.graph.nodes._run_persist") as mock_persist,
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            wrapped(state)
        mock_persist.assert_called_once()
        mock_broadcast.assert_called_once()

    def test_broadcast_failure_does_not_prevent_persist(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        state = _make_state()
        with (
            patch("backend.graph.nodes._run_persist") as mock_persist,
            patch(
                "backend.graph.nodes._run_broadcast",
                side_effect=RuntimeError("broadcast exploded"),
            ),
        ):
            result = wrapped(state)
        mock_persist.assert_called_once()
        assert result == {"current_node": "planner"}

    def test_persist_failure_does_not_prevent_broadcast(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        state = _make_state()
        with (
            patch(
                "backend.graph.nodes._run_persist",
                side_effect=RuntimeError("DB down"),
            ),
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            result = wrapped(state)
        mock_broadcast.assert_called_once()
        assert result == {"current_node": "planner"}

    def test_wrapper_skips_broadcast_when_no_job_id(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        empty_state: InvestmentState = cast(InvestmentState, {})
        with (
            patch("backend.graph.nodes._run_persist") as mock_persist,
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            wrapped(empty_state)
        mock_persist.assert_not_called()
        mock_broadcast.assert_not_called()

    def test_wrapper_passes_same_node_name_to_broadcast(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "risk_officer"})
        wrapped = _persist_after(mock_fn, "risk_officer")
        state = _make_state()
        with (
            patch("backend.graph.nodes._run_persist"),
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            wrapped(state)
        _, kwargs = mock_broadcast.call_args
        assert kwargs["node_name"] == "risk_officer"


# ---------------------------------------------------------------------------
# 5. End-to-end: a real sequential node delivers an event to a real
#    broadcaster subscriber, in order
# ---------------------------------------------------------------------------


class TestEndToEndNodeToBroadcaster:
    @pytest.mark.asyncio
    async def test_planner_node_completion_is_delivered_to_subscriber(self) -> None:
        from backend.graph.nodes import planner_node

        queue = await subscribe(_JOB_ID)
        state = _make_state()

        with patch("backend.graph.nodes._run_persist"):
            planner_node(state)

        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["job_id"] == _JOB_ID
        assert event["agent"] == "planner"

    @pytest.mark.asyncio
    async def test_two_sequential_nodes_are_delivered_in_order(self) -> None:
        from backend.graph.nodes import planner_node, research_join_node

        queue = await subscribe(_JOB_ID)
        state = _make_state()

        with patch("backend.graph.nodes._run_persist"):
            planner_node(state)
            research_join_node(state)

        first = await asyncio.wait_for(queue.get(), timeout=1.0)
        second = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert first["agent"] == "planner"
        assert second["agent"] == "research_join"


# ---------------------------------------------------------------------------
# 6. Research node previews (fundamental/technical/sentiment/macro) --
#    added alongside the _broadcast_research_node fix below. Before this,
#    these 4 nodes were absent from both _NODE_OUTPUT_STATE_FIELD and
#    _summarise_agent_output, so even once they started broadcasting they
#    would have shown the generic "<node> output ready" fallback instead
#    of a real headline.
# ---------------------------------------------------------------------------


class TestResearchNodePreviews:
    def test_fundamental_success_includes_score(self) -> None:
        from backend.graph.nodes import NODE_FUNDAMENTAL, _build_output_preview

        state = _make_state(
            fundamental={"agent_name": "fundamental_analyst", "error": None, "score": 7}
        )
        preview = _build_output_preview(NODE_FUNDAMENTAL, state)
        assert "7/10" in preview

    def test_technical_success_includes_signal(self) -> None:
        from backend.graph.nodes import NODE_TECHNICAL, _build_output_preview

        state = _make_state(
            technical={
                "agent_name": "technical_analyst",
                "error": None,
                "signal": "BUY",
            }
        )
        preview = _build_output_preview(NODE_TECHNICAL, state)
        assert "BUY" in preview

    def test_sentiment_success_includes_label_and_score(self) -> None:
        from backend.graph.nodes import NODE_SENTIMENT, _build_output_preview

        state = _make_state(
            sentiment={
                "agent_name": "news_sentiment",
                "error": None,
                "sentiment_label": "positive",
                "sentiment_score": 0.42,
            }
        )
        preview = _build_output_preview(NODE_SENTIMENT, state)
        assert "positive" in preview
        assert "0.42" in preview

    def test_macro_success_includes_environment(self) -> None:
        from backend.graph.nodes import NODE_MACRO, _build_output_preview

        state = _make_state(
            macro={
                "agent_name": "macro_economist",
                "error": None,
                "macro_environment": "favourable",
            }
        )
        preview = _build_output_preview(NODE_MACRO, state)
        assert "favourable" in preview

    def test_fundamental_error_overrides_headline_field(self) -> None:
        from backend.graph.nodes import NODE_FUNDAMENTAL, _build_output_preview

        state = _make_state(
            fundamental={
                "agent_name": "fundamental_analyst",
                "error": "yfinance rate limited",
                "score": 0,
            }
        )
        preview = _build_output_preview(NODE_FUNDAMENTAL, state)
        assert preview.startswith("Failed:")
        assert "yfinance rate limited" in preview

    def test_fundamental_missing_score_falls_back(self) -> None:
        from backend.graph.nodes import NODE_FUNDAMENTAL, _summarise_agent_output

        result = _summarise_agent_output(NODE_FUNDAMENTAL, {})
        assert result == f"{NODE_FUNDAMENTAL} output ready"


# ---------------------------------------------------------------------------
# 7. The 4 Send-parallel research nodes now broadcast live (bugfix,
#    PERF-001 follow-up): previously fundamental_node/technical_node/
#    sentiment_node/macro_node never called _run_broadcast at all, so
#    frontend/src/lib/agentProgress.ts's deriveAgentCards had no event
#    to key off and showed all 4 seats as permanently "Skipped" once the
#    stream ended -- even on a fully successful analysis where the
#    backend log clearly showed all 4 agents running. Persistence stays
#    deferred to research_join_node (unchanged) since that constraint
#    -- 4 concurrent branches cannot safely share one DB write inside a
#    Send super-step -- is real and correct; only the broadcast, which
#    has no such constraint, moves earlier.
# ---------------------------------------------------------------------------


class TestResearchNodesBroadcastLive:
    def test_fundamental_node_calls_broadcast(self) -> None:
        from backend.graph.nodes import NODE_FUNDAMENTAL, fundamental_node

        state = _make_state()
        with (
            patch(
                "backend.graph.nodes._run_research_node_safely",
                return_value={"fundamental": {"agent_name": "fundamental_analyst"}},
            ),
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            result = fundamental_node(state)

        mock_broadcast.assert_called_once()
        assert mock_broadcast.call_args.kwargs["node_name"] == NODE_FUNDAMENTAL
        assert mock_broadcast.call_args.kwargs["job_id"] == _JOB_ID
        assert result == {"fundamental": {"agent_name": "fundamental_analyst"}}

    def test_technical_node_calls_broadcast(self) -> None:
        from backend.graph.nodes import NODE_TECHNICAL, technical_node

        state = _make_state()
        with (
            patch(
                "backend.graph.nodes._run_research_node_safely",
                return_value={"technical": {"agent_name": "technical_analyst"}},
            ),
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            technical_node(state)

        assert mock_broadcast.call_args.kwargs["node_name"] == NODE_TECHNICAL

    def test_sentiment_node_calls_broadcast(self) -> None:
        from backend.graph.nodes import NODE_SENTIMENT, sentiment_node

        state = _make_state()
        with (
            patch(
                "backend.graph.nodes._run_research_node_safely",
                return_value={"sentiment": {"agent_name": "news_sentiment"}},
            ),
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            sentiment_node(state)

        assert mock_broadcast.call_args.kwargs["node_name"] == NODE_SENTIMENT

    def test_macro_node_calls_broadcast(self) -> None:
        from backend.graph.nodes import NODE_MACRO, macro_node

        state = _make_state()
        with (
            patch(
                "backend.graph.nodes._run_research_node_safely",
                return_value={"macro": {"agent_name": "macro_economist"}},
            ),
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            macro_node(state)

        assert mock_broadcast.call_args.kwargs["node_name"] == NODE_MACRO

    def test_broadcast_failure_does_not_break_node_return_value(self) -> None:
        """A broadcast bug must never take down the pipeline it is only
        reporting on -- this is the same fire-and-forget contract
        _persist_after's broadcast call already has."""
        from backend.graph.nodes import fundamental_node

        state = _make_state()
        with (
            patch(
                "backend.graph.nodes._run_research_node_safely",
                return_value={"fundamental": {"agent_name": "fundamental_analyst"}},
            ),
            patch(
                "backend.graph.nodes._run_broadcast",
                side_effect=RuntimeError("broadcaster exploded"),
            ),
        ):
            result = fundamental_node(state)

        assert result == {"fundamental": {"agent_name": "fundamental_analyst"}}

    def test_skips_broadcast_when_no_job_id(self) -> None:
        from backend.graph.nodes import fundamental_node

        empty_state: InvestmentState = cast(InvestmentState, {})
        with (
            patch(
                "backend.graph.nodes._run_research_node_safely",
                return_value={"fundamental": {"agent_name": "fundamental_analyst"}},
            ),
            patch("backend.graph.nodes._run_broadcast") as mock_broadcast,
        ):
            fundamental_node(empty_state)

        mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_fundamental_node_event_is_actually_delivered(self) -> None:
        """End-to-end: a real subscriber actually receives the event --
        not just a mock assertion that _run_broadcast was called."""
        from backend.graph.nodes import fundamental_node

        queue = await subscribe(_JOB_ID)
        state = _make_state()
        with patch(
            "backend.graph.nodes._run_research_node_safely",
            return_value={
                "fundamental": {
                    "agent_name": "fundamental_analyst",
                    "error": None,
                    "score": 6,
                }
            },
        ):
            fundamental_node(state)

        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["agent"] == "fundamental_analyst"
        assert "6/10" in event["output_preview"]
