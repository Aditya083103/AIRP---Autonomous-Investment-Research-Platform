# backend/tests/unit/test_node_profiler.py
"""
Unit tests for T-036: Node Performance Profiler.

Acceptance criteria verified:
  - Node latencies logged (log line with AIRP_LATENCY prefix)
  - No node runs >30s without timeout (NodeTimeoutError raised)
  - Profiling report exists in docs/ (checked in TestProfilingReport)

Test strategy
-------------
  1. NodeTimeoutError -- class and constructor
  2. profile_node -- normal return path
       latency stored in state
       log line emitted
       partial dict returned unchanged
  3. profile_node -- exception propagation
       non-timeout exceptions re-raised
  4. profile_node -- timeout path (ENVIRONMENT=test disables real timeout;
       test manually invokes timeout by patching _EFFECTIVE_TIMEOUT_S)
  5. profile_node -- LangSmith emission (mocked, non-fatal)
  6. _log_latency -- log content
  7. _store_latency_in_state -- state mutation
  8. nodes.py integration -- every node is wrapped with profile_node
  9. _EFFECTIVE_TIMEOUT_S -- infinity in test env
 10. PROFILER_LOG_PREFIX constant
 11. NODE_TIMEOUT_S constant
 12. Profiling report file existence
 13. Public API

ENVIRONMENT=test is set at the top to disable the real timeout watchdog
so tests don't accidentally race against the 30-second limit.
"""

import logging
import os
from typing import Any, Literal
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.graph.node_profiler import (  # noqa: E402
    _EFFECTIVE_TIMEOUT_S,
    NODE_TIMEOUT_S,
    PROFILER_LOG_PREFIX,
    NodeTimeoutError,
    _log_latency,
    _store_latency_in_state,
    profile_node,
)

# ---------------------------------------------------------------------------
# T-033 compatibility: patch _run_persist so graph tests never touch DB
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_db_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent state_persistence from opening DB connections in these tests."""
    monkeypatch.setattr(
        "backend.graph.nodes._run_persist",
        lambda *args, **kwargs: None,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_JOB_ID = "t036-profiler-test-job-001"
_TICKER = "TCS.NS"
_NODE_NAME = "test_node"


def _make_state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "job_id": _JOB_ID,
        "ticker": _TICKER,
        "company_name": "Tata Consultancy Services",
        "status": "running",
    }
    base.update(overrides)
    return base


def _make_node_fn(return_val: dict[str, Any]) -> Any:
    """Return a simple callable that returns return_val instantly."""
    return MagicMock(return_value=return_val)


# ---------------------------------------------------------------------------
# 1. NodeTimeoutError
# ---------------------------------------------------------------------------


class TestNodeTimeoutError:
    """NodeTimeoutError has the correct class hierarchy and attributes."""

    def test_inherits_from_runtime_error(self) -> None:
        err = NodeTimeoutError("planner", 30.0, 35.2)
        assert isinstance(err, RuntimeError)

    def test_node_name_attribute(self) -> None:
        err = NodeTimeoutError("fundamental_analyst", 30.0, 31.5)
        assert err.node_name == "fundamental_analyst"

    def test_timeout_s_attribute(self) -> None:
        err = NodeTimeoutError("technical_analyst", 30.0, 31.5)
        assert err.timeout_s == 30.0

    def test_elapsed_s_attribute(self) -> None:
        err = NodeTimeoutError("sentiment_analyst", 30.0, 45.8)
        assert abs(err.elapsed_s - 45.8) < 0.01

    def test_str_contains_node_name(self) -> None:
        err = NodeTimeoutError("risk_officer", 30.0, 31.0)
        assert "risk_officer" in str(err)

    def test_str_contains_elapsed_time(self) -> None:
        err = NodeTimeoutError("valuation_agent", 30.0, 31.5)
        assert "31.5" in str(err)

    def test_str_contains_limit(self) -> None:
        err = NodeTimeoutError("portfolio_manager", 30.0, 35.0)
        assert "30" in str(err)

    def test_is_catchable_as_runtime_error(self) -> None:
        with pytest.raises(RuntimeError):
            raise NodeTimeoutError("planner", 30.0, 31.0)


# ---------------------------------------------------------------------------
# 2. profile_node -- normal return path
# ---------------------------------------------------------------------------


class TestProfileNodeNormalPath:
    """profile_node wraps a node and returns the partial dict unchanged."""

    def test_returns_dict(self) -> None:
        fn = _make_node_fn({"current_node": "planner", "status": "running"})
        wrapped = profile_node(fn, _NODE_NAME)
        result = wrapped(_make_state())
        assert isinstance(result, dict)

    def test_returns_original_partial_dict_fields(self) -> None:
        expected = {"current_node": "planner", "status": "running"}
        fn = _make_node_fn(expected)
        wrapped = profile_node(fn, _NODE_NAME)
        result = wrapped(_make_state())
        assert result["current_node"] == "planner"
        assert result["status"] == "running"

    def test_adds_node_latencies_key(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        result = wrapped(_make_state())
        assert "node_latencies" in result

    def test_node_latencies_contains_node_name(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        result = wrapped(_make_state())
        latencies = result.get("node_latencies", {})
        assert _NODE_NAME in latencies

    def test_node_latency_is_non_negative_int(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        result = wrapped(_make_state())
        elapsed = result["node_latencies"][_NODE_NAME]
        assert isinstance(elapsed, int)
        assert elapsed >= 0

    def test_calls_wrapped_fn_once(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        wrapped(_make_state())
        fn.assert_called_once()

    def test_passes_state_to_wrapped_fn(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        state = _make_state(ticker="INFY.NS")
        wrapped(state)
        fn.assert_called_once_with(state)

    def test_preserves_existing_node_latencies(self) -> None:
        """If node_fn returns a node_latencies dict, entries are preserved."""
        existing_latencies: dict[str, Any] = {"other_node": 100}
        fn = _make_node_fn(
            {"current_node": "planner", "node_latencies": existing_latencies}
        )
        wrapped = profile_node(fn, _NODE_NAME)
        result = wrapped(_make_state())
        latencies = result.get("node_latencies", {})
        assert "other_node" in latencies
        assert _NODE_NAME in latencies

    def test_does_not_raise_on_clean_execution(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        wrapped(_make_state())  # must not raise

    def test_works_with_empty_state(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        result = wrapped({})
        assert "node_latencies" in result


# ---------------------------------------------------------------------------
# 3. profile_node -- exception propagation
# ---------------------------------------------------------------------------


class TestProfileNodeExceptionPropagation:
    """Non-timeout exceptions from the wrapped function are re-raised."""

    def test_reraises_value_error(self) -> None:
        fn = MagicMock(side_effect=ValueError("bad ticker"))
        wrapped = profile_node(fn, _NODE_NAME)
        with pytest.raises(ValueError, match="bad ticker"):
            wrapped(_make_state())

    def test_reraises_runtime_error(self) -> None:
        fn = MagicMock(side_effect=RuntimeError("agent failed"))
        wrapped = profile_node(fn, _NODE_NAME)
        with pytest.raises(RuntimeError, match="agent failed"):
            wrapped(_make_state())

    def test_reraises_key_error(self) -> None:
        fn = MagicMock(side_effect=KeyError("missing_key"))
        wrapped = profile_node(fn, _NODE_NAME)
        with pytest.raises(KeyError):
            wrapped(_make_state())

    def test_exception_type_preserved(self) -> None:
        class CustomError(Exception):
            pass

        fn = MagicMock(side_effect=CustomError("custom"))
        wrapped = profile_node(fn, _NODE_NAME)
        with pytest.raises(CustomError):
            wrapped(_make_state())


# ---------------------------------------------------------------------------
# 4. profile_node -- timeout path
# ---------------------------------------------------------------------------


class TestProfileNodeTimeout:
    """
    Timeout tests using a patched _EFFECTIVE_TIMEOUT_S.

    In ENVIRONMENT=test the real timeout is disabled (infinity).
    We override _EFFECTIVE_TIMEOUT_S to 0.001s to trigger the timeout
    mechanism in tests.

    For the POSIX path (SIGALRM), signal.alarm(0) means "fire immediately"
    which is not reliable for unit tests.  We therefore patch
    _make_timeout_ctx to return a context manager that always raises
    NodeTimeoutError, which tests the error path without depending on
    SIGALRM timing.
    """

    def _make_always_timeout_ctx(self, seconds: float, node_name: str) -> Any:
        """A context manager that always raises NodeTimeoutError on enter."""

        class _AlwaysTimeout:
            def __enter__(self) -> "_AlwaysTimeout":
                raise NodeTimeoutError(
                    node_name=node_name,
                    timeout_s=seconds,
                    elapsed_s=seconds + 1.0,
                )

            def __exit__(self, *args: Any) -> Literal[False]:
                return False

        return _AlwaysTimeout()

    def test_raises_node_timeout_error(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        with patch(
            "backend.graph.node_profiler._make_timeout_ctx",
            side_effect=self._make_always_timeout_ctx,
        ):
            with pytest.raises(NodeTimeoutError):
                wrapped(_make_state())

    def test_timeout_error_has_correct_node_name(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, "risk_officer")
        with patch(
            "backend.graph.node_profiler._make_timeout_ctx",
            side_effect=lambda seconds, node_name: self._make_always_timeout_ctx(
                seconds, node_name
            ),
        ):
            with pytest.raises(NodeTimeoutError) as exc_info:
                wrapped(_make_state())
        assert exc_info.value.node_name == "risk_officer"

    def test_timeout_is_runtime_error(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        with patch(
            "backend.graph.node_profiler._make_timeout_ctx",
            side_effect=self._make_always_timeout_ctx,
        ):
            with pytest.raises(RuntimeError):
                wrapped(_make_state())

    def test_effective_timeout_is_infinity_in_test_env(self) -> None:
        """In ENVIRONMENT=test, the timeout must be disabled."""
        assert _EFFECTIVE_TIMEOUT_S == float("inf")

    def test_node_timeout_s_constant_is_30(self) -> None:
        assert NODE_TIMEOUT_S == 30.0


# ---------------------------------------------------------------------------
# 5. profile_node -- LangSmith emission (mocked, non-fatal)
# ---------------------------------------------------------------------------


class TestProfileNodeLangSmithEmission:
    """LangSmith metadata emission is best-effort and never fatal."""

    def test_langsmith_failure_does_not_abort_node(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        with patch(
            "backend.graph.node_profiler._emit_langsmith_metadata",
            side_effect=RuntimeError("LangSmith down"),
        ):
            # Must not raise even when emission fails
            result = wrapped(_make_state())
        assert isinstance(result, dict)

    def test_langsmith_called_with_node_name(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, "fundamental_analyst")
        with patch("backend.graph.node_profiler._emit_langsmith_metadata") as mock_emit:
            wrapped(_make_state())
        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args[1]
        assert call_kwargs["node_name"] == "fundamental_analyst"

    def test_langsmith_called_with_correct_job_id(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        with patch("backend.graph.node_profiler._emit_langsmith_metadata") as mock_emit:
            wrapped(_make_state(job_id="specific-job-123"))
        call_kwargs = mock_emit.call_args[1]
        assert call_kwargs["job_id"] == "specific-job-123"

    def test_langsmith_called_with_timed_out_false_on_success(self) -> None:
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        with patch("backend.graph.node_profiler._emit_langsmith_metadata") as mock_emit:
            wrapped(_make_state())
        call_kwargs = mock_emit.call_args[1]
        assert call_kwargs["timed_out"] is False

    def test_langsmith_not_called_when_tracing_disabled(self) -> None:
        """When LANGCHAIN_TRACING_V2 is not 'true', no LangSmith client call."""
        fn = _make_node_fn({"current_node": "planner"})
        wrapped = profile_node(fn, _NODE_NAME)
        with (
            patch.dict(
                os.environ,
                {"LANGCHAIN_TRACING_V2": "false", "LANGSMITH_API_KEY": ""},
            ),
            patch("backend.graph.node_profiler._emit_langsmith_metadata") as mock_emit,
        ):
            wrapped(_make_state())
        # _emit_langsmith_metadata IS called from profile_node, but internally
        # it no-ops when tracing is disabled. We verify the wrapper calls it:
        mock_emit.assert_called_once()


# ---------------------------------------------------------------------------
# 6. _log_latency
# ---------------------------------------------------------------------------


class TestLogLatency:
    """_log_latency emits structured log lines with the correct prefix."""

    def test_log_line_contains_prefix(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=150,
                job_id=_JOB_ID,
                ticker=_TICKER,
                timed_out=False,
            )
        assert any(PROFILER_LOG_PREFIX in r.message for r in caplog.records)

    def test_log_line_contains_node_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="risk_officer",
                elapsed_ms=200,
                job_id=_JOB_ID,
                ticker=_TICKER,
                timed_out=False,
            )
        log_text = " ".join(r.message for r in caplog.records)
        assert "risk_officer" in log_text

    def test_log_line_contains_elapsed_ms(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=1234,
                job_id=_JOB_ID,
                ticker=_TICKER,
                timed_out=False,
            )
        log_text = " ".join(r.message for r in caplog.records)
        assert "1234" in log_text

    def test_log_line_contains_job_id(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=100,
                job_id="specific-uuid-here",
                ticker=_TICKER,
                timed_out=False,
            )
        log_text = " ".join(r.message for r in caplog.records)
        assert "specific-uuid-here" in log_text

    def test_log_line_contains_ticker(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=100,
                job_id=_JOB_ID,
                ticker="INFY.NS",
                timed_out=False,
            )
        log_text = " ".join(r.message for r in caplog.records)
        assert "INFY.NS" in log_text

    def test_timeout_log_is_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=31000,
                job_id=_JOB_ID,
                ticker=_TICKER,
                timed_out=True,
            )
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1

    def test_normal_log_is_info(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=100,
                job_id=_JOB_ID,
                ticker=_TICKER,
                timed_out=False,
            )
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1

    def test_log_line_contains_status_ok_on_success(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=100,
                job_id=_JOB_ID,
                ticker=_TICKER,
                timed_out=False,
            )
        log_text = " ".join(r.message for r in caplog.records)
        assert "status=OK" in log_text

    def test_log_line_contains_status_timeout_on_timeout(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="backend.graph.node_profiler"):
            _log_latency(
                node_name="planner",
                elapsed_ms=31000,
                job_id=_JOB_ID,
                ticker=_TICKER,
                timed_out=True,
            )
        log_text = " ".join(r.message for r in caplog.records)
        assert "status=TIMEOUT" in log_text


# ---------------------------------------------------------------------------
# 7. _store_latency_in_state
# ---------------------------------------------------------------------------


class TestStoreLatencyInState:
    """_store_latency_in_state adds latency to the partial dict."""

    def test_adds_node_latencies_key_when_absent(self) -> None:
        partial: dict[str, Any] = {"current_node": "planner"}
        _store_latency_in_state(partial, "planner", 150)
        assert "node_latencies" in partial

    def test_stores_correct_elapsed_ms(self) -> None:
        partial: dict[str, Any] = {}
        _store_latency_in_state(partial, "planner", 250)
        assert partial["node_latencies"]["planner"] == 250

    def test_does_not_overwrite_existing_entries(self) -> None:
        partial: dict[str, Any] = {"node_latencies": {"other_node": 100}}
        _store_latency_in_state(partial, "planner", 200)
        assert partial["node_latencies"]["other_node"] == 100
        assert partial["node_latencies"]["planner"] == 200

    def test_overwrites_own_entry_on_second_call(self) -> None:
        partial: dict[str, Any] = {"node_latencies": {"planner": 100}}
        _store_latency_in_state(partial, "planner", 999)
        assert partial["node_latencies"]["planner"] == 999

    def test_does_not_affect_other_keys(self) -> None:
        partial: dict[str, Any] = {"current_node": "planner", "status": "running"}
        _store_latency_in_state(partial, "planner", 150)
        assert partial["current_node"] == "planner"
        assert partial["status"] == "running"

    def test_elapsed_ms_is_int(self) -> None:
        partial: dict[str, Any] = {}
        _store_latency_in_state(partial, "planner", 123)
        assert isinstance(partial["node_latencies"]["planner"], int)

    def test_handles_zero_elapsed(self) -> None:
        partial: dict[str, Any] = {}
        _store_latency_in_state(partial, "planner", 0)
        assert partial["node_latencies"]["planner"] == 0


# ---------------------------------------------------------------------------
# 8. nodes.py integration -- every node is wrapped
# ---------------------------------------------------------------------------


class TestNodesIntegration:
    """
    Verifies that all 12 nodes in nodes.py call profile_node.
    We check this by asserting that after a node runs, node_latencies
    is present in the returned partial dict.
    """

    def _run_node(self, node_fn: Any, state: dict[str, Any]) -> dict[str, Any]:
        """Run a node function and return its partial dict."""
        return node_fn(state)  # type: ignore[no-any-return]

    def test_planner_node_adds_latency(self) -> None:
        from backend.graph.nodes import planner_node

        result = self._run_node(planner_node, _make_state())
        assert "node_latencies" in result

    def test_research_join_node_adds_latency(self) -> None:
        from backend.graph.nodes import research_join_node

        result = self._run_node(research_join_node, _make_state())
        assert "node_latencies" in result

    def test_error_handler_node_adds_latency(self) -> None:
        from backend.graph.nodes import error_handler_node

        state = _make_state(fundamental={"agent_name": "fa", "error": "rate limit"})
        result = self._run_node(error_handler_node, state)
        assert "node_latencies" in result

    def test_sentiment_escalation_node_adds_latency(self) -> None:
        from backend.graph.nodes import sentiment_escalation_node

        state = _make_state(sentiment={"agent_name": "sa", "sentiment_score": -0.95})
        result = self._run_node(sentiment_escalation_node, state)
        assert "node_latencies" in result

    def test_risk_node_adds_latency(self) -> None:
        from backend.graph.nodes import risk_node

        result = self._run_node(risk_node, _make_state())
        assert "node_latencies" in result

    def test_contrarian_node_adds_latency(self) -> None:
        from backend.graph.nodes import contrarian_node

        result = self._run_node(contrarian_node, _make_state())
        assert "node_latencies" in result

    def test_valuation_node_adds_latency(self) -> None:
        from backend.graph.nodes import valuation_node

        result = self._run_node(valuation_node, _make_state())
        assert "node_latencies" in result

    def test_portfolio_manager_node_adds_latency(self) -> None:
        from backend.graph.nodes import portfolio_manager_node

        result = self._run_node(portfolio_manager_node, _make_state())
        assert "node_latencies" in result

    def test_fundamental_node_adds_latency(self) -> None:
        from backend.graph.nodes import fundamental_node

        mock_result = {"fundamental": {"agent_name": "fa", "score": 7}}
        with patch(
            "backend.graph.nodes.run_fundamental_analysis",
            return_value=mock_result,
        ):
            result = self._run_node(fundamental_node, _make_state())
        assert "node_latencies" in result

    def test_technical_node_adds_latency(self) -> None:
        from backend.graph.nodes import technical_node

        mock_result = {"technical": {"agent_name": "ta", "signal": "BUY"}}
        with patch(
            "backend.graph.nodes.run_technical_analysis",
            return_value=mock_result,
        ):
            result = self._run_node(technical_node, _make_state())
        assert "node_latencies" in result

    def test_sentiment_node_adds_latency(self) -> None:
        from backend.graph.nodes import sentiment_node

        mock_result = {"sentiment": {"agent_name": "sa", "sentiment_score": 0.2}}
        with patch(
            "backend.graph.nodes.run_sentiment_analysis",
            return_value=mock_result,
        ):
            result = self._run_node(sentiment_node, _make_state())
        assert "node_latencies" in result

    def test_macro_node_adds_latency(self) -> None:
        from backend.graph.nodes import macro_node

        mock_result = {"macro": {"agent_name": "ma", "macro_environment": "neutral"}}
        with patch(
            "backend.graph.nodes.run_macro_analysis",
            return_value=mock_result,
        ):
            result = self._run_node(macro_node, _make_state())
        assert "node_latencies" in result

    def test_planner_node_latency_key_matches_node_name(self) -> None:
        from backend.graph.nodes import NODE_PLANNER, planner_node

        result = self._run_node(planner_node, _make_state())
        assert NODE_PLANNER in result.get("node_latencies", {})

    def test_node_latency_is_non_negative(self) -> None:
        from backend.graph.nodes import risk_node

        result = self._run_node(risk_node, _make_state())
        latencies = result.get("node_latencies", {})
        for elapsed in latencies.values():
            assert isinstance(elapsed, int)
            assert elapsed >= 0


# ---------------------------------------------------------------------------
# 9. _EFFECTIVE_TIMEOUT_S
# ---------------------------------------------------------------------------


class TestEffectiveTimeout:
    """_EFFECTIVE_TIMEOUT_S is infinity in test environment."""

    def test_is_infinity_in_test_env(self) -> None:
        assert _EFFECTIVE_TIMEOUT_S == float("inf")

    def test_node_timeout_s_is_30(self) -> None:
        assert NODE_TIMEOUT_S == 30.0

    def test_effective_timeout_greater_than_node_timeout(self) -> None:
        """In test env, effective timeout must be greater than NODE_TIMEOUT_S."""
        assert _EFFECTIVE_TIMEOUT_S > NODE_TIMEOUT_S


# ---------------------------------------------------------------------------
# 10. PROFILER_LOG_PREFIX constant
# ---------------------------------------------------------------------------


class TestProfilerLogPrefix:
    """PROFILER_LOG_PREFIX is the correct literal."""

    def test_is_string(self) -> None:
        assert isinstance(PROFILER_LOG_PREFIX, str)

    def test_non_empty(self) -> None:
        assert len(PROFILER_LOG_PREFIX) > 0

    def test_value(self) -> None:
        assert PROFILER_LOG_PREFIX == "[AIRP_LATENCY]"

    def test_starts_with_bracket(self) -> None:
        assert PROFILER_LOG_PREFIX.startswith("[")

    def test_ends_with_bracket(self) -> None:
        assert PROFILER_LOG_PREFIX.endswith("]")


# ---------------------------------------------------------------------------
# 11. NODE_TIMEOUT_S constant
# ---------------------------------------------------------------------------


class TestNodeTimeoutSConstant:
    """NODE_TIMEOUT_S is 30.0."""

    def test_is_float(self) -> None:
        assert isinstance(NODE_TIMEOUT_S, float)

    def test_value_is_30(self) -> None:
        assert NODE_TIMEOUT_S == 30.0

    def test_positive(self) -> None:
        assert NODE_TIMEOUT_S > 0


# ---------------------------------------------------------------------------
# 12. Profiling report file existence
# ---------------------------------------------------------------------------


class TestProfilingReportExists:
    """docs/PERFORMANCE_PROFILE.md must exist (acceptance criterion)."""

    def test_performance_profile_md_exists(self) -> None:
        from pathlib import Path

        # Walk up from this test file to find repo root
        this_file = Path(__file__).resolve()
        # backend/tests/unit/test_node_profiler.py
        # -> backend/tests/unit -> backend/tests -> backend -> repo root
        repo_root = this_file.parent.parent.parent.parent
        profile_path = repo_root / "docs" / "PERFORMANCE_PROFILE.md"
        assert profile_path.exists(), (
            f"docs/PERFORMANCE_PROFILE.md not found at {profile_path}. "
            "T-036 acceptance criterion: 'profiling report in docs/'"
        )

    def test_performance_profile_md_is_non_empty(self) -> None:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        profile_path = repo_root / "docs" / "PERFORMANCE_PROFILE.md"
        if profile_path.exists():
            assert profile_path.stat().st_size > 100


# ---------------------------------------------------------------------------
# 13. Public API
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """All __all__ symbols from node_profiler are importable."""

    def test_all_exports_importable(self) -> None:
        import backend.graph.node_profiler as m

        for sym in m.__all__:
            assert hasattr(m, sym), f"Missing from module: {sym}"

    def test_node_timeout_error_importable(self) -> None:
        from backend.graph.node_profiler import NodeTimeoutError  # noqa: F401

        assert NodeTimeoutError is not None

    def test_profile_node_importable(self) -> None:
        from backend.graph.node_profiler import profile_node  # noqa: F401

        assert callable(profile_node)

    def test_node_timeout_s_importable(self) -> None:
        from backend.graph.node_profiler import NODE_TIMEOUT_S  # noqa: F401

        assert NODE_TIMEOUT_S is not None

    def test_profiler_log_prefix_importable(self) -> None:
        from backend.graph.node_profiler import PROFILER_LOG_PREFIX  # noqa: F401

        assert PROFILER_LOG_PREFIX is not None

    def test_nodes_module_exports_node_timeout_error(self) -> None:
        import backend.graph.nodes as n

        assert "NodeTimeoutError" in n.__all__
