    # scripts/run_eval_latency.py
"""
AIRP -- End-to-End Latency Eval Runner (T-071)

Runs the REAL, fully-compiled AIRP LangGraph pipeline end-to-end for the
3-company dataset in backend/evals/latency_eval_dataset.py, timing each
run and capturing every node's structured latency log line via
backend.evals.latency_evaluators.LatencyLogCapture. Prints a console
report -- p50/p95 vs. T-071's targets, per-node breakdown, and the
identified bottleneck -- that a PR description can paste directly.

This is a manual, one-off script (see scripts/README.md) -- NOT part of
the pytest/CI gate, same reasoning already established for
scripts/run_eval_fundamental.py and scripts/run_full_analysis.py. It:

  1. Builds the compiled LangGraph pipeline (backend.graph.graph.
     build_graph()) -- the same graph the FastAPI backend triggers.
  2. For each of the 3 companies, creates a fresh InvestmentState via
     make_initial_state() and invokes the graph synchronously, letting
     all 8 agents run for REAL -- real yFinance/NewsAPI/Alpha Vantage/
     Screener.in fetches, real LLM calls, real debate loop.
  3. Attaches a LatencyLogCapture handler to the node_profiler logger
     around each invoke() call, so every node's [AIRP_LATENCY] log line
     is captured and attributed to that company's run, independent of
     any state-merging concerns (see latency_evaluators.py's module
     docstring for why log capture -- not state -- is the source of
     truth here).
  4. Aggregates the 3 runs via summarize_latency_runs() and prints
     format_latency_report()'s output -- p50/p95 vs. targets, the full
     per-node mean-latency breakdown, and the identified bottleneck node.
  5. When LANGSMITH_API_KEY is configured (settings.tracing_enabled),
     every node's latency is ALSO already visible in the LangSmith
     dashboard automatically -- backend.graph.node_profiler's existing
     _emit_langsmith_metadata() (T-036) and backend.agents.tracing's
     configure_tracing() (T-026, called automatically by get_llm())
     require no new wiring for this. The script prints a reminder of
     this rather than re-implementing it.

Usage
-----
    set ENVIRONMENT=development   (Windows CMD; do NOT chain with &&)
    python -m scripts.run_eval_latency

Requirements
------------
- A real LLM key configured in .env (LLM_PROVIDER=groq + GROQ_API_KEY is
  the default AIRP dev provider; LLM_PROVIDER=anthropic works too).
- Network access to yFinance / NewsAPI / Alpha Vantage / Screener.in and
  your configured LLM provider.
- Optional: LANGSMITH_API_KEY set, so per-node latency metadata also
  lands in the LangSmith dashboard for each run (see point 5 above).
- Makes REAL calls -- not a unit test, not mocked, not run in CI. Costs
  a full pipeline's worth of API/LLM requests per company, 3 times.
  Expect the whole script to take a few minutes.

Exit code
---------
Returns 0 when both targets (p50 <90s, p95 <120s) are met, 1 otherwise
-- convenient for pasting into a PR description alongside `echo $?`, but
this script is never invoked by CI itself.

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- AIRP rule.
* Plain ASCII section comments (# ---).
* No bare ``# type: ignore``.
* Mirrors the structure of scripts/run_eval_fundamental.py and
  scripts/run_full_analysis.py: a fixed, documented, human-readable
  console report, not a silent pass/fail exit code alone.
* build_graph() is called once and reused across all 3 companies
  (unlike the mocked test suite, which rebuilds per test class to avoid
  lru_cache pollution across independently-patched mocks) -- there is
  no mocking here, so graph reuse is safe and avoids paying the graph
  compilation + Mermaid-export cost 3 times.
* Per-company failures do not abort the whole benchmark -- one company's
  pipeline error is recorded as a failed PipelineRunResult and the
  script proceeds to the next company, matching the AIRP-wide
  "independent failure never aborts the batch" principle.
"""

import logging
import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "development")

import sys  # noqa: E402
import time  # noqa: E402
from typing import Any  # noqa: E402
import uuid  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.evals.latency_eval_dataset import (  # noqa: E402
    LATENCY_EVAL_COMPANIES,
    LatencyEvalCompany,
)
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("scripts.run_eval_latency")


def _run_one_company(graph: Any, company: LatencyEvalCompany) -> PipelineRunResult:
    """
    Run the full pipeline once for one company, timing it and capturing
    every node's structured latency log line.

    Never raises -- any exception from graph.invoke() is caught and
    reported as a failed PipelineRunResult so one company's failure does
    not abort the rest of the benchmark.

    Args:
        graph:   The compiled LangGraph pipeline (build_graph() output).
        company: One row from LATENCY_EVAL_COMPANIES.

    Returns:
        A PipelineRunResult for this company.
    """
    job_id = str(uuid.uuid4())

    initial_state: InvestmentState = make_initial_state(
        job_id=job_id,
        company_name=company["company_name"],
        ticker=company["ticker"],
        exchange=company["exchange"],
        sector=company["sector"],
        raw_query=company["raw_query"],
        requested_by="latency-eval-script",
    )

    profiler_logger = logging.getLogger(NODE_PROFILER_LOGGER_NAME)
    capture = LatencyLogCapture()
    previous_level = profiler_logger.level
    profiler_logger.addHandler(capture)
    profiler_logger.setLevel(logging.INFO)

    logger.info(
        "Starting latency run: company=%r ticker=%r job_id=%s",
        company["company_name"],
        company["ticker"],
        job_id,
    )

    start = time.perf_counter()
    status = "failed"
    error: Any = None
    try:
        final_state: dict[str, Any] = graph.invoke(dict(initial_state))
        status = str(final_state.get("status", "unknown"))
        pipeline_error = final_state.get("pipeline_error")
        if pipeline_error:
            error = str(pipeline_error)
        elif status != "completed":
            error = f"pipeline finished with status={status!r}, not 'completed'"
    except Exception as exc:  # noqa: BLE001 -- report, never crash the batch
        logger.exception(
            "Latency run failed for company=%r: %s", company["company_name"], exc
        )
        status = "failed"
        error = str(exc)
    finally:
        elapsed_s = time.perf_counter() - start
        profiler_logger.removeHandler(capture)
        profiler_logger.setLevel(previous_level)

    result: PipelineRunResult = {
        "company_name": company["company_name"],
        "ticker": company["ticker"],
        "job_id": job_id,
        "status": "completed" if status == "completed" and error is None else "failed",
        "total_elapsed_s": elapsed_s,
        "node_latencies_ms": capture.node_latencies_ms(),
        "node_call_counts": capture.node_call_counts(),
        "error": error,
    }

    logger.info(
        "Finished latency run: company=%r elapsed=%.1fs status=%s",
        company["company_name"],
        elapsed_s,
        result["status"],
    )
    return result


def main() -> int:
    """Run the latency benchmark across all 3 companies and report the outcome."""
    logger.info(
        "Building compiled AIRP graph (real APIs and LLM will be called "
        "for %d companies)...",
        len(LATENCY_EVAL_COMPANIES),
    )
    graph: Any = build_graph()

    runs: list[PipelineRunResult] = []
    for company in LATENCY_EVAL_COMPANIES:
        runs.append(_run_one_company(graph, company))

    summary = summarize_latency_runs(runs)
    report = format_latency_report(summary, runs)

    print("\n" + report + "\n")

    if settings.tracing_enabled:
        print(
            "LangSmith tracing is active (LANGCHAIN_TRACING_V2=true + "
            "LANGSMITH_API_KEY configured) -- every node's latency from "
            "these 3 runs is also visible per-run in the LangSmith "
            "dashboard via node_profiler's existing metadata patching "
            "(T-036). No extra step needed to view the breakdown there.\n"
        )
    else:
        print(
            "LANGSMITH_API_KEY not configured -- per-node breakdown was "
            "still captured locally (see report above), but nothing was "
            "pushed to the LangSmith dashboard for this run. Set "
            "LANGSMITH_API_KEY in .env to also see it there.\n"
        )

    return 0 if meets_latency_targets(summary) else 1


if __name__ == "__main__":
    sys.exit(main())
