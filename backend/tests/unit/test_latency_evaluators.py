# backend/tests/unit/test_latency_evaluators.py
"""
Unit tests for T-071: End-to-End Latency Eval.

Test strategy:
  1. Dataset shape             -- 3 companies, unique tickers, valid NSE
                                   suffix, all required fields present
  2. parse_latency_log_line()  -- valid OK/TIMEOUT lines parse correctly;
                                   malformed/unrelated lines return None
                                   without raising
  3. LatencyLogCapture         -- emit() aggregates repeated node hits
                                   (e.g. debate loop running twice),
                                   ignores unrelated log records, reset()
                                   clears state for reuse across runs
  4. compute_percentile()      -- known small datasets, single-value and
                                   two-value edge cases, invalid-input
                                   guards
  5. identify_bottleneck()     -- empty input -> (None, None); normal
                                   input -> correct max
  6. summarize_latency_runs()  -- p50/p95 computed correctly from
                                   synthetic PipelineRunResult rows, both
                                   a passing and a failing-target case,
                                   the all-failed-runs degenerate case,
                                   and per-node aggregation across
                                   multiple runs
  7. meets_latency_targets()   -- both targets required, either alone
                                   insufficient
  8. format_latency_report()   -- never raises, contains expected
                                   substrings for both the normal and the
                                   zero-completed-runs case

None of these tests call a real LLM, hit the network, or invoke the real
LangGraph pipeline. This entire suite runs fully offline, deterministically,
every time.
"""
from __future__ import annotations

import logging
import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.evals.latency_eval_dataset import LATENCY_EVAL_COMPANIES  # noqa: E402
from backend.evals.latency_evaluators import (  # noqa: E402
    NODE_PROFILER_LOGGER_NAME,
    PIPELINE_P50_TARGET_S,
    PIPELINE_P95_TARGET_S,
    LatencyLogCapture,
    PipelineRunResult,
    compute_percentile,
    format_latency_report,
    identify_bottleneck,
    meets_latency_targets,
    parse_latency_log_line,
    summarize_latency_runs,
)

# ---------------------------------------------------------------------------
# 1. Dataset shape
# ---------------------------------------------------------------------------


class TestDatasetShape:
    def test_has_exactly_three_companies(self) -> None:
        assert len(LATENCY_EVAL_COMPANIES) == 3

    def test_tickers_are_unique(self) -> None:
        tickers = [c["ticker"] for c in LATENCY_EVAL_COMPANIES]
        assert len(tickers) == len(set(tickers))

    def test_every_ticker_has_nse_suffix(self) -> None:
        for company in LATENCY_EVAL_COMPANIES:
            assert company["ticker"].endswith(".NS"), company["ticker"]

    def test_every_company_has_required_fields(self) -> None:
        required = {"company_name", "ticker", "exchange", "sector", "raw_query"}
        for company in LATENCY_EVAL_COMPANIES:
            assert required.issubset(company.keys()), company

    def test_every_field_is_non_empty_string(self) -> None:
        for company in LATENCY_EVAL_COMPANIES:
            for key in ("company_name", "ticker", "exchange", "sector", "raw_query"):
                value = company[key]  # type: ignore[literal-required]
                assert isinstance(value, str) and value.strip(), (key, company)

    def test_not_all_companies_share_the_same_sector(self) -> None:
        # Deliberate sector spread -- see latency_eval_dataset.py's
        # "Company selection rationale" docstring section.
        sectors = {c["sector"] for c in LATENCY_EVAL_COMPANIES}
        assert len(sectors) >= 2


# ---------------------------------------------------------------------------
# 2. parse_latency_log_line
# ---------------------------------------------------------------------------


class TestParseLatencyLogLine:
    def test_parses_ok_line(self) -> None:
        line = (
            "[AIRP_LATENCY] node=fundamental_analyst elapsed_ms=1234 "
            "job_id=abc-123 ticker=TCS.NS status=OK"
        )
        entry = parse_latency_log_line(line)
        assert entry is not None
        assert entry["node_name"] == "fundamental_analyst"
        assert entry["elapsed_ms"] == 1234
        assert entry["job_id"] == "abc-123"
        assert entry["ticker"] == "TCS.NS"
        assert entry["timed_out"] is False

    def test_parses_timeout_line(self) -> None:
        line = (
            "[AIRP_LATENCY] node=valuation_agent elapsed_ms=30000 "
            "job_id=xyz-999 ticker=INFY.NS status=TIMEOUT"
        )
        entry = parse_latency_log_line(line)
        assert entry is not None
        assert entry["timed_out"] is True
        assert entry["elapsed_ms"] == 30000

    def test_returns_none_for_empty_string(self) -> None:
        assert parse_latency_log_line("") is None

    def test_returns_none_for_unrelated_log_line(self) -> None:
        assert parse_latency_log_line("INFO some other log message entirely") is None

    def test_returns_none_for_truncated_line(self) -> None:
        assert parse_latency_log_line("[AIRP_LATENCY] node=planner elapsed_ms=") is None

    def test_returns_none_for_wrong_status_value(self) -> None:
        line = (
            "[AIRP_LATENCY] node=planner elapsed_ms=10 "
            "job_id=j ticker=T status=WEIRD"
        )
        assert parse_latency_log_line(line) is None

    def test_never_raises_on_arbitrary_garbage(self) -> None:
        # A parsing helper in AIRP must never raise -- try a handful of
        # adversarial inputs and confirm every one returns None cleanly.
        garbage_inputs = [
            "[AIRP_LATENCY]",
            "[AIRP_LATENCY] " * 50,
            "node=x elapsed_ms=1 job_id=y ticker=z status=OK",  # missing prefix
            "\x00\x01[AIRP_LATENCY] node=a elapsed_ms=1 job_id=b ticker=c status=OK",
        ]
        for garbage in garbage_inputs:
            # Should not raise; result may be None or a valid entry.
            parse_latency_log_line(garbage)


# ---------------------------------------------------------------------------
# 3. LatencyLogCapture
# ---------------------------------------------------------------------------


class TestLatencyLogCapture:
    def _emit_latency_line(
        self, capture: LatencyLogCapture, node: str, elapsed_ms: int, status: str = "OK"
    ) -> None:
        record = logging.LogRecord(
            name=NODE_PROFILER_LOGGER_NAME,
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=(
                f"[AIRP_LATENCY] node={node} elapsed_ms={elapsed_ms} "
                f"job_id=job-1 ticker=TCS.NS status={status}"
            ),
            args=(),
            exc_info=None,
        )
        capture.emit(record)

    def test_captures_single_node_execution(self) -> None:
        capture = LatencyLogCapture()
        self._emit_latency_line(capture, "planner", 100)
        assert capture.node_latencies_ms() == {"planner": 100}
        assert capture.node_call_counts() == {"planner": 1}

    def test_sums_repeated_node_executions(self) -> None:
        # Simulates the debate loop -- contrarian_investor / debate_loop
        # can each execute twice in a single pipeline run (2 debate
        # rounds). Total time spent in that node should be the sum, not
        # the last value.
        capture = LatencyLogCapture()
        self._emit_latency_line(capture, "contrarian_investor", 500)
        self._emit_latency_line(capture, "contrarian_investor", 700)
        assert capture.node_latencies_ms() == {"contrarian_investor": 1200}
        assert capture.node_call_counts() == {"contrarian_investor": 2}

    def test_tracks_multiple_distinct_nodes_independently(self) -> None:
        capture = LatencyLogCapture()
        self._emit_latency_line(capture, "planner", 50)
        self._emit_latency_line(capture, "fundamental_analyst", 900)
        self._emit_latency_line(capture, "technical_analyst", 300)
        latencies = capture.node_latencies_ms()
        assert latencies["planner"] == 50
        assert latencies["fundamental_analyst"] == 900
        assert latencies["technical_analyst"] == 300

    def test_ignores_unrelated_log_records(self) -> None:
        capture = LatencyLogCapture()
        unrelated = logging.LogRecord(
            name=NODE_PROFILER_LOGGER_NAME,
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="some unrelated informational message",
            args=(),
            exc_info=None,
        )
        capture.emit(unrelated)
        assert capture.node_latencies_ms() == {}
        assert capture.entries == []

    def test_any_timed_out_false_when_all_ok(self) -> None:
        capture = LatencyLogCapture()
        self._emit_latency_line(capture, "planner", 50, status="OK")
        assert capture.any_timed_out() is False

    def test_any_timed_out_true_when_one_timeout_present(self) -> None:
        capture = LatencyLogCapture()
        self._emit_latency_line(capture, "planner", 50, status="OK")
        self._emit_latency_line(capture, "valuation_agent", 30000, status="TIMEOUT")
        assert capture.any_timed_out() is True

    def test_reset_clears_entries_for_reuse_across_runs(self) -> None:
        capture = LatencyLogCapture()
        self._emit_latency_line(capture, "planner", 50)
        assert capture.entries != []
        capture.reset()
        assert capture.entries == []
        assert capture.node_latencies_ms() == {}

    def test_attaches_and_detaches_from_real_logger_cleanly(self) -> None:
        # Exercises the exact addHandler/removeHandler pattern
        # scripts/run_eval_latency.py uses, against the real
        # node_profiler logger name, to prove no leakage between tests.
        profiler_logger = logging.getLogger(NODE_PROFILER_LOGGER_NAME)
        capture = LatencyLogCapture()
        previous_level = profiler_logger.level
        profiler_logger.addHandler(capture)
        profiler_logger.setLevel(logging.INFO)
        try:
            profiler_logger.info(
                "[AIRP_LATENCY] node=planner elapsed_ms=42 "
                "job_id=j ticker=TCS.NS status=OK"
            )
        finally:
            profiler_logger.removeHandler(capture)
            profiler_logger.setLevel(previous_level)

        assert capture.node_latencies_ms() == {"planner": 42}
        # Confirm detachment -- a second log call after removal must not
        # be captured.
        profiler_logger.info(
            "[AIRP_LATENCY] node=planner elapsed_ms=999 "
            "job_id=j ticker=TCS.NS status=OK"
        )
        assert capture.node_latencies_ms() == {"planner": 42}


# ---------------------------------------------------------------------------
# 4. compute_percentile
# ---------------------------------------------------------------------------


class TestComputePercentile:
    def test_median_of_three_values(self) -> None:
        assert compute_percentile([10.0, 20.0, 30.0], 50.0) == pytest.approx(20.0)

    def test_p95_of_three_values_interpolates(self) -> None:
        # rank = 0.95 * 2 = 1.9 -> interpolate between index 1 (20) and
        # index 2 (30): 20 + 0.9 * 10 = 29.0
        assert compute_percentile([10.0, 20.0, 30.0], 95.0) == pytest.approx(29.0)

    def test_single_value_returns_that_value_for_any_percentile(self) -> None:
        assert compute_percentile([42.0], 50.0) == pytest.approx(42.0)
        assert compute_percentile([42.0], 95.0) == pytest.approx(42.0)
        assert compute_percentile([42.0], 0.0) == pytest.approx(42.0)

    def test_two_values_p50_is_midpoint(self) -> None:
        assert compute_percentile([10.0, 20.0], 50.0) == pytest.approx(15.0)

    def test_p0_returns_minimum(self) -> None:
        assert compute_percentile([5.0, 1.0, 9.0], 0.0) == pytest.approx(1.0)

    def test_p100_returns_maximum(self) -> None:
        assert compute_percentile([5.0, 1.0, 9.0], 100.0) == pytest.approx(9.0)

    def test_unsorted_input_is_handled(self) -> None:
        assert compute_percentile([30.0, 10.0, 20.0], 50.0) == pytest.approx(20.0)

    def test_empty_sequence_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            compute_percentile([], 50.0)

    def test_out_of_range_percentile_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            compute_percentile([1.0, 2.0], 150.0)
        with pytest.raises(ValueError):
            compute_percentile([1.0, 2.0], -1.0)


# ---------------------------------------------------------------------------
# 5. identify_bottleneck
# ---------------------------------------------------------------------------


class TestIdentifyBottleneck:
    def test_empty_dict_returns_none_none(self) -> None:
        assert identify_bottleneck({}) == (None, None)

    def test_single_entry_is_the_bottleneck(self) -> None:
        assert identify_bottleneck({"planner": 100.0}) == ("planner", 100.0)

    def test_returns_the_maximum(self) -> None:
        per_node = {
            "planner": 50.0,
            "fundamental_analyst": 4000.0,
            "technical_analyst": 900.0,
            "valuation_agent": 3500.0,
        }
        node_name, mean_ms = identify_bottleneck(per_node)
        assert node_name == "fundamental_analyst"
        assert mean_ms == pytest.approx(4000.0)


# ---------------------------------------------------------------------------
# 6. summarize_latency_runs
# ---------------------------------------------------------------------------


def _make_run(
    company_name: str,
    ticker: str,
    total_elapsed_s: float,
    status: str = "completed",
    node_latencies_ms: dict[str, int] | None = None,
    error: str | None = None,
) -> PipelineRunResult:
    latencies = node_latencies_ms or {}
    return {
        "company_name": company_name,
        "ticker": ticker,
        "job_id": f"job-{ticker}",
        "status": status,
        "total_elapsed_s": total_elapsed_s,
        "node_latencies_ms": latencies,
        "node_call_counts": dict.fromkeys(latencies, 1),
        "error": error,
    }


class TestSummarizeLatencyRuns:
    def test_all_runs_pass_targets(self) -> None:
        runs = [
            _make_run("TCS", "TCS.NS", 60.0, node_latencies_ms={"planner": 100}),
            _make_run("Infosys", "INFY.NS", 65.0, node_latencies_ms={"planner": 120}),
            _make_run(
                "Reliance", "RELIANCE.NS", 70.0, node_latencies_ms={"planner": 140}
            ),
        ]
        summary = summarize_latency_runs(runs)

        assert summary["n_runs"] == 3
        assert summary["n_completed"] == 3
        assert summary["n_failed"] == 0
        assert summary["p50_s"] == pytest.approx(65.0)
        assert summary["meets_p50_target"] is True
        assert summary["meets_p95_target"] is True
        assert summary["per_node_mean_ms"]["planner"] == pytest.approx(120.0)
        assert summary["bottleneck_node"] == "planner"

    def test_slow_runs_fail_both_targets(self) -> None:
        runs = [
            _make_run("TCS", "TCS.NS", 95.0),
            _make_run("Infosys", "INFY.NS", 130.0),
            _make_run("Reliance", "RELIANCE.NS", 140.0),
        ]
        summary = summarize_latency_runs(runs)

        assert summary["meets_p50_target"] is False
        assert summary["meets_p95_target"] is False

    def test_failed_run_excluded_from_percentiles_but_counted(self) -> None:
        runs = [
            _make_run("TCS", "TCS.NS", 60.0),
            _make_run("Infosys", "INFY.NS", 65.0),
            _make_run(
                "Reliance",
                "RELIANCE.NS",
                999.0,
                status="failed",
                error="yFinance timeout",
            ),
        ]
        summary = summarize_latency_runs(runs)

        assert summary["n_completed"] == 2
        assert summary["n_failed"] == 1
        # p50 of the 2 completed runs (60, 65) -- the failed run's 999s
        # total must NOT pollute the percentile calculation.
        assert summary["p50_s"] == pytest.approx(62.5)
        p95_s = summary["p95_s"]
        assert p95_s is not None
        assert p95_s < 100.0

    def test_all_runs_failed_returns_degenerate_summary_without_raising(self) -> None:
        runs = [
            _make_run("TCS", "TCS.NS", 0.0, status="failed", error="boom"),
            _make_run("Infosys", "INFY.NS", 0.0, status="failed", error="boom"),
        ]
        summary = summarize_latency_runs(runs)

        assert summary["n_completed"] == 0
        assert summary["n_failed"] == 2
        assert summary["p50_s"] is None
        assert summary["p95_s"] is None
        assert summary["meets_p50_target"] is False
        assert summary["meets_p95_target"] is False
        assert summary["bottleneck_node"] is None

    def test_empty_runs_list_returns_degenerate_summary_without_raising(self) -> None:
        summary = summarize_latency_runs([])
        assert summary["n_runs"] == 0
        assert summary["n_completed"] == 0
        assert summary["p50_s"] is None
        assert summary["meets_p50_target"] is False

    def test_per_node_mean_only_averages_runs_that_executed_that_node(self) -> None:
        # error_handler only executes on the error-routing path -- it
        # should not run in every company's pipeline run. Its mean must
        # be computed only over the runs where it actually appeared.
        runs = [
            _make_run(
                "TCS",
                "TCS.NS",
                60.0,
                node_latencies_ms={"planner": 100, "error_handler": 200},
            ),
            _make_run("Infosys", "INFY.NS", 65.0, node_latencies_ms={"planner": 120}),
        ]
        summary = summarize_latency_runs(runs)

        assert summary["per_node_mean_ms"]["planner"] == pytest.approx(110.0)
        assert summary["per_node_mean_ms"]["error_handler"] == pytest.approx(200.0)

    def test_bottleneck_identifies_slowest_mean_node(self) -> None:
        runs = [
            _make_run(
                "TCS",
                "TCS.NS",
                60.0,
                node_latencies_ms={"planner": 100, "fundamental_analyst": 5000},
            ),
        ]
        summary = summarize_latency_runs(runs)
        assert summary["bottleneck_node"] == "fundamental_analyst"
        assert summary["bottleneck_mean_ms"] == pytest.approx(5000.0)


# ---------------------------------------------------------------------------
# 7. meets_latency_targets
# ---------------------------------------------------------------------------


class TestMeetsLatencyTargets:
    def test_true_when_both_targets_met(self) -> None:
        runs = [
            _make_run("TCS", "TCS.NS", 60.0),
            _make_run("Infosys", "INFY.NS", 65.0),
            _make_run("Reliance", "RELIANCE.NS", 70.0),
        ]
        summary = summarize_latency_runs(runs)
        assert meets_latency_targets(summary) is True

    def test_false_when_only_p50_met(self) -> None:
        # 3 samples where p50 comfortably passes but the top sample
        # pushes p95 over 120s.
        runs = [
            _make_run("TCS", "TCS.NS", 50.0),
            _make_run("Infosys", "INFY.NS", 55.0),
            _make_run("Reliance", "RELIANCE.NS", 200.0),
        ]
        summary = summarize_latency_runs(runs)
        assert summary["meets_p50_target"] is True
        assert summary["meets_p95_target"] is False
        assert meets_latency_targets(summary) is False

    def test_false_when_neither_target_met(self) -> None:
        runs = [
            _make_run("TCS", "TCS.NS", 150.0),
            _make_run("Infosys", "INFY.NS", 160.0),
        ]
        summary = summarize_latency_runs(runs)
        assert meets_latency_targets(summary) is False


# ---------------------------------------------------------------------------
# 8. format_latency_report
# ---------------------------------------------------------------------------


class TestFormatLatencyReport:
    def test_normal_report_contains_key_figures(self) -> None:
        runs = [
            _make_run(
                "Tata Consultancy Services",
                "TCS.NS",
                60.0,
                node_latencies_ms={"fundamental_analyst": 4000, "planner": 50},
            ),
            _make_run(
                "Infosys",
                "INFY.NS",
                65.0,
                node_latencies_ms={"fundamental_analyst": 4200, "planner": 40},
            ),
            _make_run(
                "Reliance Industries",
                "RELIANCE.NS",
                70.0,
                node_latencies_ms={"fundamental_analyst": 4500, "planner": 60},
            ),
        ]
        summary = summarize_latency_runs(runs)
        report = format_latency_report(summary, runs)

        assert "Tata Consultancy Services" in report
        assert "Infosys" in report
        assert "Reliance Industries" in report
        assert "p50" in report
        assert "p95" in report
        assert "fundamental_analyst" in report
        assert "bottleneck" in report.lower()
        assert f"{PIPELINE_P50_TARGET_S:.0f}" in report
        assert f"{PIPELINE_P95_TARGET_S:.0f}" in report

    def test_report_marks_bottleneck_node_inline(self) -> None:
        runs = [
            _make_run(
                "TCS",
                "TCS.NS",
                60.0,
                node_latencies_ms={"fundamental_analyst": 9000, "planner": 50},
            ),
        ]
        summary = summarize_latency_runs(runs)
        report = format_latency_report(summary, runs)
        assert "<-- bottleneck" in report

    def test_report_never_raises_when_all_runs_failed(self) -> None:
        runs = [
            _make_run("TCS", "TCS.NS", 0.0, status="failed", error="network error"),
        ]
        summary = summarize_latency_runs(runs)
        report = format_latency_report(summary, runs)
        assert "TCS" in report
        assert "network error" in report
        assert "cannot be computed" in report.lower()

    def test_report_never_raises_with_no_runs_at_all(self) -> None:
        summary = summarize_latency_runs([])
        report = format_latency_report(summary, [])
        assert isinstance(report, str)
        assert "T-071" in report


# ---------------------------------------------------------------------------
# 9. Target constants -- must match T-071's literal acceptance criteria
# ---------------------------------------------------------------------------


class TestTargetConstants:
    def test_p50_target_is_90_seconds(self) -> None:
        assert PIPELINE_P50_TARGET_S == 90.0

    def test_p95_target_is_120_seconds(self) -> None:
        assert PIPELINE_P95_TARGET_S == 120.0
