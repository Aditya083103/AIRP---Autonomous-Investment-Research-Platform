# backend/evals/latency_evaluators.py
"""
AIRP -- End-to-End Latency Eval: Parsing, Aggregation & Reporting (T-071)

Implements the latency benchmark designed per T-067's
docs/EVAL_FRAMEWORK_DESIGN.md and T-071's literal acceptance criteria:

    "Time full pipeline for 3 companies; assert <90s p50, <120s p95;
     log per-node latency breakdown"
    Acceptance: p50 <90s; p95 <120s; per-node breakdown visible in
    LangSmith; bottleneck identified and documented.

Why this eval does NOT need new LangSmith plumbing
-----------------------------------------------------
Two things T-071 might look like it needs already exist:

1. "Per-node breakdown visible in LangSmith" -- every node in
   backend/graph/nodes.py is already wrapped with
   backend.graph.node_profiler.profile_node() (T-036), which calls
   backend.agents.tracing's tracing wiring (configured automatically by
   get_llm(), T-026) and best-effort patches per-node latency onto the
   current LangSmith run via ``_emit_langsmith_metadata()``. Running the
   real pipeline with LANGSMITH_API_KEY configured (scripts/run_eval_
   latency.py does this) already produces that visibility -- nothing new
   to build here.
2. A per-run local breakdown for THIS script's own console report and
   for docs/PERFORMANCE_PROFILE.md -- this DOES need new code, because
   ``state["node_latencies"]`` (mentioned in node_profiler.py's own
   docstring) is not actually a declared field of ``InvestmentState``
   (backend/graph/state.py) and LangGraph's default per-key "last write
   wins" merge semantics means a value written by an earlier node in the
   pipeline is not reliably preserved once a later node's own partial
   update overwrites the same key. Trusting final state for the
   breakdown would silently under-report every node except roughly the
   last one to run. The one thing that IS reliably per-node is the
   structured ``[AIRP_LATENCY] node=... elapsed_ms=...`` log line
   ``node_profiler._log_latency()`` emits for every single node
   execution (log records are never merged or overwritten) -- so this
   module captures and parses THOSE instead.

Two layers, same separation T-068/T-069/T-070 established
------------------------------------------------------------
* The PARSING / AGGREGATION / REPORTING logic in this module
  (``parse_latency_log_line``, ``LatencyLogCapture``,
  ``compute_percentile``, ``summarize_latency_runs``,
  ``identify_bottleneck``, ``format_latency_report``) is pure, has no
  network/LLM/LangGraph dependency, and is fully covered by CI
  (backend/tests/unit/test_latency_evaluators.py runs it against
  synthetic log lines and synthetic per-run results).
* The REAL benchmark run -- invoking the live compiled LangGraph
  pipeline against real market data and a real LLM for the 3 companies
  in latency_eval_dataset.py -- happens only in
  ``scripts/run_eval_latency.py``, a manual script, NOT part of the
  pytest/CI gate (same reasoning already established for
  scripts/run_eval_fundamental.py).

Never-raises contract
----------------------
Every function in this module follows the AIRP-wide "evaluators never
raise" convention: malformed log lines are skipped (not fatal), a
summary computed from zero completed runs still returns a well-formed
(if target-failing) ``LatencySummary`` rather than raising a
ZeroDivisionError or IndexError, and ``format_latency_report`` renders a
readable message for that empty case too.

Public interface
-----------------
    NodeLatencyLogEntry       -- TypedDict: one parsed [AIRP_LATENCY] line
    PipelineRunResult         -- TypedDict: one company's full-pipeline run
    LatencySummary            -- TypedDict: aggregated benchmark result
    PIPELINE_P50_TARGET_S     -- 90.0  (T-071 acceptance criterion)
    PIPELINE_P95_TARGET_S     -- 120.0 (T-071 acceptance criterion)
    parse_latency_log_line(...)   -- pure: str -> NodeLatencyLogEntry | None
    LatencyLogCapture             -- logging.Handler subclass, collects
                                      NodeLatencyLogEntry records during a
                                      real (or mocked) graph.invoke() call
    compute_percentile(...)       -- pure: linear-interpolation percentile
    summarize_latency_runs(...)   -- pure: list[PipelineRunResult] -> LatencySummary
    identify_bottleneck(...)      -- pure: per-node means -> (name, ms) | (None, None)
    meets_latency_targets(...)    -- pure: LatencySummary -> bool
    format_latency_report(...)    -- pure: LatencySummary -> human-readable str
"""

import logging
import re
from typing import Optional, Sequence, TypedDict

from backend.graph.node_profiler import PROFILER_LOG_PREFIX

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants -- T-071's own acceptance criteria
# ---------------------------------------------------------------------------

#: p50 (median) total pipeline wall-clock time across all runs must be
#: strictly under this many seconds.
PIPELINE_P50_TARGET_S: float = 90.0

#: p95 total pipeline wall-clock time across all runs must be strictly
#: under this many seconds.
PIPELINE_P95_TARGET_S: float = 120.0

#: The logger name node_profiler.py's structured latency lines are
#: emitted under -- LatencyLogCapture attaches to exactly this logger.
NODE_PROFILER_LOGGER_NAME: str = "backend.graph.node_profiler"

# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


class NodeLatencyLogEntry(TypedDict):
    """One parsed [AIRP_LATENCY] structured log line."""

    node_name: str
    elapsed_ms: int
    job_id: str
    ticker: str
    timed_out: bool


class PipelineRunResult(TypedDict):
    """One company's full end-to-end pipeline run."""

    company_name: str
    ticker: str
    job_id: str
    status: str
    total_elapsed_s: float
    #: node_name -> total elapsed_ms summed across every execution of
    #: that node in this run (a node can run more than once -- e.g.
    #: contrarian_investor / debate_loop loop back for a second debate
    #: round -- summing reflects genuine total time spent in that node,
    #: not just its most recent execution).
    node_latencies_ms: dict[str, int]
    #: node_name -> number of times that node executed in this run.
    node_call_counts: dict[str, int]
    error: Optional[str]


class LatencySummary(TypedDict):
    """Aggregated result across every completed PipelineRunResult."""

    n_runs: int
    n_completed: int
    n_failed: int
    p50_s: Optional[float]
    p95_s: Optional[float]
    mean_s: Optional[float]
    max_s: Optional[float]
    meets_p50_target: bool
    meets_p95_target: bool
    #: node_name -> mean elapsed_ms across completed runs that executed it.
    per_node_mean_ms: dict[str, float]
    bottleneck_node: Optional[str]
    bottleneck_mean_ms: Optional[float]


# ---------------------------------------------------------------------------
# Log-line parsing
# ---------------------------------------------------------------------------

# Matches lines of the exact shape node_profiler._log_latency() emits:
#   [AIRP_LATENCY] node=<n> elapsed_ms=<N> job_id=<uuid> ticker=<t> status=<S>
_LOG_LINE_PATTERN = re.compile(
    r"^\[AIRP_LATENCY\]\s+"
    r"node=(?P<node_name>\S+)\s+"
    r"elapsed_ms=(?P<elapsed_ms>\d+)\s+"
    r"job_id=(?P<job_id>\S+)\s+"
    r"ticker=(?P<ticker>\S+)\s+"
    r"status=(?P<status>OK|TIMEOUT)\s*$"
)


def parse_latency_log_line(message: str) -> Optional[NodeLatencyLogEntry]:
    """
    Parse one structured [AIRP_LATENCY] log line into a NodeLatencyLogEntry.

    Pure, defensive, and never raises: any line that does not match the
    expected shape -- a log line from an unrelated logger, a malformed
    or truncated line, empty input -- returns None rather than raising.

    Args:
        message: The fully-formatted log message (``record.getMessage()``),
            expected to start with ``PROFILER_LOG_PREFIX``
            (``"[AIRP_LATENCY]"``).

    Returns:
        A NodeLatencyLogEntry on a successful parse, else None.
    """
    if not message or PROFILER_LOG_PREFIX not in message:
        return None

    match = _LOG_LINE_PATTERN.match(message.strip())
    if match is None:
        return None

    try:
        return {
            "node_name": match.group("node_name"),
            "elapsed_ms": int(match.group("elapsed_ms")),
            "job_id": match.group("job_id"),
            "ticker": match.group("ticker"),
            "timed_out": match.group("status") == "TIMEOUT",
        }
    except (ValueError, TypeError) as exc:
        # Defensive belt-and-suspenders -- the regex already constrains
        # elapsed_ms to \d+, so int() should never fail here, but a
        # parsing helper in AIRP must never raise regardless.
        logger.debug("parse_latency_log_line: failed to parse %r: %s", message, exc)
        return None


# ---------------------------------------------------------------------------
# Log capture handler
# ---------------------------------------------------------------------------


class LatencyLogCapture(logging.Handler):
    """
    A logging.Handler that captures every [AIRP_LATENCY] line emitted by
    backend.graph.node_profiler during one pipeline run.

    Usage
    -----
        capture = LatencyLogCapture()
        profiler_logger = logging.getLogger(NODE_PROFILER_LOGGER_NAME)
        profiler_logger.addHandler(capture)
        previous_level = profiler_logger.level
        profiler_logger.setLevel(logging.INFO)
        try:
            final_state = compiled_graph.invoke(initial_state)
        finally:
            profiler_logger.removeHandler(capture)
            profiler_logger.setLevel(previous_level)

        node_latencies_ms = capture.node_latencies_ms()
        node_call_counts = capture.node_call_counts()

    Why a Handler and not a state field
    -------------------------------------
    See this module's docstring -- ``state["node_latencies"]`` is not a
    reliable source of the full per-node breakdown because LangGraph's
    default per-key merge semantics can drop earlier nodes' contributions.
    Log records, by contrast, are never merged or overwritten -- every
    single node execution produces exactly one durable log record, which
    is exactly the guarantee this eval needs.

    Never raises
    ------------
    ``emit()`` swallows any parsing failure via ``parse_latency_log_line``
    returning None -- a malformed or unrelated log record is silently
    skipped, never allowed to crash the pipeline run it is observing.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.entries: list[NodeLatencyLogEntry] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception as exc:  # pragma: no cover -- defensive only
            logger.debug("LatencyLogCapture: failed to format record: %s", exc)
            return

        entry = parse_latency_log_line(message)
        if entry is not None:
            self.entries.append(entry)

    def node_latencies_ms(self) -> dict[str, int]:
        """Sum elapsed_ms per node_name across every captured entry."""
        totals: dict[str, int] = {}
        for entry in self.entries:
            totals[entry["node_name"]] = (
                totals.get(entry["node_name"], 0) + entry["elapsed_ms"]
            )
        return totals

    def node_call_counts(self) -> dict[str, int]:
        """Count executions per node_name across every captured entry."""
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry["node_name"]] = counts.get(entry["node_name"], 0) + 1
        return counts

    def any_timed_out(self) -> bool:
        """True if any captured node execution exceeded NODE_TIMEOUT_S."""
        return any(entry["timed_out"] for entry in self.entries)

    def reset(self) -> None:
        """Clear captured entries -- call between runs to reuse one handler."""
        self.entries = []


# ---------------------------------------------------------------------------
# Percentile computation
# ---------------------------------------------------------------------------


def compute_percentile(values: Sequence[float], pct: float) -> float:
    """
    Compute the ``pct``-th percentile of ``values`` via linear interpolation
    between closest ranks (the same convention numpy's default
    ``numpy.percentile`` uses).

    Pure and dependency-free -- deliberately avoids adding numpy as a
    project dependency for a single percentile calculation used only by
    this eval.

    Args:
        values: A non-empty sequence of numeric samples.
        pct:    Percentile to compute, in the range [0, 100].

    Returns:
        The interpolated percentile value.

    Raises:
        ValueError: If ``values`` is empty or ``pct`` is outside [0, 100].
            (Callers in this module always guard against an empty
            sequence before calling this -- see ``summarize_latency_runs``
            -- so this only fires for genuine programmer error.)
    """
    if not values:
        raise ValueError("compute_percentile: values must be non-empty")
    if not 0.0 <= pct <= 100.0:
        raise ValueError(f"compute_percentile: pct must be in [0, 100], got {pct!r}")

    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return float(ordered[0])

    # Rank position (0-indexed) using the "linear" interpolation method.
    rank = (pct / 100.0) * (n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    fraction = rank - lower_idx

    lower_val = float(ordered[lower_idx])
    upper_val = float(ordered[upper_idx])
    return lower_val + (upper_val - lower_val) * fraction


# ---------------------------------------------------------------------------
# Bottleneck identification
# ---------------------------------------------------------------------------


def identify_bottleneck(
    per_node_mean_ms: dict[str, float],
) -> tuple[Optional[str], Optional[float]]:
    """
    Return the (node_name, mean_elapsed_ms) pair for the slowest node.

    Pure, never raises. Returns (None, None) for an empty input rather
    than raising on ``max()`` of an empty sequence.

    Args:
        per_node_mean_ms: node_name -> mean elapsed_ms across completed runs.

    Returns:
        The single slowest node by mean elapsed_ms, or (None, None) when
        ``per_node_mean_ms`` is empty.
    """
    if not per_node_mean_ms:
        return None, None

    bottleneck_node = max(per_node_mean_ms, key=lambda name: per_node_mean_ms[name])
    return bottleneck_node, per_node_mean_ms[bottleneck_node]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def summarize_latency_runs(runs: Sequence[PipelineRunResult]) -> LatencySummary:
    """
    Aggregate a list of PipelineRunResult rows into one LatencySummary.

    Percentiles (p50/p95/mean/max) are computed only over runs whose
    ``status == "completed"`` -- a failed run has no meaningful total
    pipeline duration to include in the latency distribution, but it is
    still counted in ``n_failed`` so a summary never silently hides a
    failure.

    Per-node means are computed only from completed runs' node_latencies_ms,
    averaged over however many completed runs actually executed that node
    (a node on an error/escalation-only path, e.g. error_handler, may not
    execute in every run -- its mean reflects only the runs where it did).

    Never raises: an all-failed or empty ``runs`` sequence still returns a
    well-formed LatencySummary with None percentiles and
    ``meets_p50_target=False`` / ``meets_p95_target=False`` (there is no
    evidence the targets were met) rather than raising.

    Args:
        runs: One PipelineRunResult per company benchmarked.

    Returns:
        The aggregated LatencySummary.
    """
    n_runs = len(runs)
    completed = [r for r in runs if r.get("status") == "completed"]
    n_completed = len(completed)
    n_failed = n_runs - n_completed

    if not completed:
        return {
            "n_runs": n_runs,
            "n_completed": 0,
            "n_failed": n_failed,
            "p50_s": None,
            "p95_s": None,
            "mean_s": None,
            "max_s": None,
            "meets_p50_target": False,
            "meets_p95_target": False,
            "per_node_mean_ms": {},
            "bottleneck_node": None,
            "bottleneck_mean_ms": None,
        }

    durations = [r["total_elapsed_s"] for r in completed]
    p50 = compute_percentile(durations, 50.0)
    p95 = compute_percentile(durations, 95.0)
    mean_s = sum(durations) / len(durations)
    max_s = max(durations)

    # -- Per-node mean latency across completed runs -----------------------
    node_ms_totals: dict[str, int] = {}
    node_run_counts: dict[str, int] = {}
    for run in completed:
        run_node_latencies: dict[str, int] = run["node_latencies_ms"]
        for node_name, elapsed_ms in run_node_latencies.items():
            node_ms_totals[node_name] = node_ms_totals.get(node_name, 0) + elapsed_ms
            node_run_counts[node_name] = node_run_counts.get(node_name, 0) + 1

    per_node_mean_ms: dict[str, float] = {
        node_name: node_ms_totals[node_name] / node_run_counts[node_name]
        for node_name in node_ms_totals
    }

    bottleneck_node, bottleneck_mean_ms = identify_bottleneck(per_node_mean_ms)

    return {
        "n_runs": n_runs,
        "n_completed": n_completed,
        "n_failed": n_failed,
        "p50_s": p50,
        "p95_s": p95,
        "mean_s": mean_s,
        "max_s": max_s,
        "meets_p50_target": p50 < PIPELINE_P50_TARGET_S,
        "meets_p95_target": p95 < PIPELINE_P95_TARGET_S,
        "per_node_mean_ms": per_node_mean_ms,
        "bottleneck_node": bottleneck_node,
        "bottleneck_mean_ms": bottleneck_mean_ms,
    }


def meets_latency_targets(summary: LatencySummary) -> bool:
    """
    True only when both the p50 and p95 targets are met.

    Pure convenience wrapper -- matches the ``meets_target`` naming
    convention already used by fundamental_evaluators.py / sentiment_
    evaluators.py / debate_evaluators.py.
    """
    return bool(summary["meets_p50_target"] and summary["meets_p95_target"])


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_latency_report(
    summary: LatencySummary,
    runs: Sequence[PipelineRunResult],
) -> str:
    """
    Render a human-readable console/PR-paste report for one benchmark run.

    Pure and never raises, including for the degenerate zero-completed-run
    case (every run failed) -- the report still explains what happened
    rather than crashing on a None percentile.

    Args:
        summary: The LatencySummary produced by summarize_latency_runs().
        runs:    The individual PipelineRunResult rows the summary was
                 computed from, for the per-company table.

    Returns:
        A multi-line report string.
    """
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("AIRP -- End-to-End Latency Eval (T-071)")
    lines.append("=" * 72)

    lines.append("")
    lines.append(
        f"Runs: {summary['n_runs']} total, "
        f"{summary['n_completed']} completed, "
        f"{summary['n_failed']} failed"
    )

    lines.append("")
    lines.append("Per-company results:")
    for run in runs:
        status_marker = "OK  " if run["status"] == "completed" else "FAIL"
        lines.append(
            f"  [{status_marker}] {run['company_name']:<28} "
            f"({run['ticker']:<12}) "
            f"{run['total_elapsed_s']:6.1f}s"
            + (f"  -- {run['error']}" if run.get("error") else "")
        )

    p50_s: Optional[float] = summary["p50_s"]
    p95_s: Optional[float] = summary["p95_s"]
    mean_s: Optional[float] = summary["mean_s"]
    max_s: Optional[float] = summary["max_s"]

    lines.append("")
    if p50_s is None or p95_s is None:
        lines.append(
            "No completed runs -- p50/p95 cannot be computed. "
            "Every run failed; see per-company errors above."
        )
    else:
        p50_status = "PASS" if summary["meets_p50_target"] else "FAIL"
        p95_status = "PASS" if summary["meets_p95_target"] else "FAIL"
        lines.append(
            f"p50: {p50_s:.1f}s (target <{PIPELINE_P50_TARGET_S:.0f}s) -- {p50_status}"
        )
        lines.append(
            f"p95: {p95_s:.1f}s (target <{PIPELINE_P95_TARGET_S:.0f}s) -- {p95_status}"
        )
        if mean_s is not None and max_s is not None:
            lines.append(f"mean: {mean_s:.1f}s   max: {max_s:.1f}s")

    lines.append("")
    lines.append("Per-node latency breakdown (mean across completed runs):")
    per_node = summary["per_node_mean_ms"]
    if not per_node:
        lines.append("  (no node-level data captured)")
    else:
        for node_name, mean_ms in sorted(
            per_node.items(), key=lambda kv: kv[1], reverse=True
        ):
            is_bottleneck = node_name == summary["bottleneck_node"]
            marker = " <-- bottleneck" if is_bottleneck else ""
            lines.append(f"  {node_name:<24} {mean_ms:8.0f} ms{marker}")

    bottleneck_node: Optional[str] = summary["bottleneck_node"]
    bottleneck_mean_ms: Optional[float] = summary["bottleneck_mean_ms"]

    lines.append("")
    if bottleneck_node is not None and bottleneck_mean_ms is not None:
        lines.append(
            f"Bottleneck: {bottleneck_node} ({bottleneck_mean_ms:.0f} ms mean)"
        )
    else:
        lines.append("Bottleneck: none identified (no node-level data captured)")

    lines.append("=" * 72)
    return "\n".join(lines)


__all__ = [
    "NodeLatencyLogEntry",
    "PipelineRunResult",
    "LatencySummary",
    "PIPELINE_P50_TARGET_S",
    "PIPELINE_P95_TARGET_S",
    "NODE_PROFILER_LOGGER_NAME",
    "parse_latency_log_line",
    "LatencyLogCapture",
    "compute_percentile",
    "summarize_latency_runs",
    "identify_bottleneck",
    "meets_latency_targets",
    "format_latency_report",
]
