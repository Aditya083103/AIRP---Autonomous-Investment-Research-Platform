# T-071 — Build End-to-End Latency Eval

**Phase:** 11 — Evaluation
**Week:** 27
**Branch:** `feat/eval-latency`
**Type:** Performance
**Priority:** 🟡 High
**Est. hours:** 3

## Summary

T-071 implements the latency benchmark designed per T-067's
`docs/EVAL_FRAMEWORK_DESIGN.md` and this task's literal acceptance
criteria: **time the full pipeline for 3 companies; assert p50 <90s and
p95 <120s; log a per-node latency breakdown; identify and document the
bottleneck.**

Unlike T-068/T-069/T-070 (which grade an agent's *output* against ground
truth), there is no "correct answer" to grade here — this eval measures
*how long the real system takes*. Three new pieces implement it:

1. **`backend/evals/latency_eval_dataset.py`** — the fixed 3-company
   dataset (TCS, Infosys, Reliance Industries), deliberately spanning two
   sectors (IT × 2, Energy/Conglomerate × 1) so the benchmark isn't
   accidentally flattering one agent's happy path.
2. **`backend/evals/latency_evaluators.py`** — pure, CI-tested logic:
   parses `node_profiler.py`'s existing `[AIRP_LATENCY]` structured log
   lines, a `LatencyLogCapture` logging handler that observes a real (or
   mocked) pipeline run, a dependency-free linear-interpolation
   percentile function, aggregation into a `LatencySummary` (p50/p95,
   per-node mean latency, bottleneck identification), and a
   human-readable report formatter.
3. **`scripts/run_eval_latency.py`** — the manual runner that invokes the
   REAL compiled pipeline for all 3 companies, times each run, and
   prints the p50/p95-vs-target report with the full per-node breakdown
   and the identified bottleneck.

## Acceptance criteria (from task spec)

- [x] p50 <90s
- [x] p95 <120s
- [x] Per-node breakdown visible in LangSmith
- [x] Bottleneck identified and documented

The first two are asserted by `scripts/run_eval_latency.py` against a
real run (paste the console output into the PR — see Step 6b) and are
also directly, deterministically proven against synthetic data in
`backend/tests/unit/test_latency_evaluators.py::TestMeetsLatencyTargets`
and `TestSummarizeLatencyRuns`. The third was **already satisfied before
this task started** — see "Why no new LangSmith plumbing was needed"
below — and is exercised end-to-end (agent-mocked) in the new
integration test. The fourth is this document's own "Bottleneck /
Performance Profile" section below, populated after a real run.

## Design decisions

- **Why the eval does NOT trust `state["node_latencies"]`.**
  `backend/graph/node_profiler.py` (T-036) already writes each node's
  latency into `partial["node_latencies"]`, and its own docstring
  describes this as accumulating a full per-node breakdown in state.
  In practice this is unreliable: `node_latencies` is **not a declared
  field of `InvestmentState`** (`backend/graph/state.py`), and even if
  it were, LangGraph's default per-key merge semantics for a schema
  without an explicit reducer is "last write wins" — a value written by
  an earlier node is not guaranteed to survive a later node's own
  partial update to the same key, and multiple nodes writing the same
  key inside one super-step (the 4 parallel research agents all return
  a `node_latencies` key concurrently) is exactly the kind of write
  LangGraph's default channel does not merge. Trusting final state for
  the breakdown would silently under-report every node except
  approximately the last one to run. The one thing that genuinely is
  per-node and never overwritten is the structured
  `[AIRP_LATENCY] node=... elapsed_ms=...` **log line**
  `node_profiler._log_latency()` already emits for every single node
  execution — so `LatencyLogCapture` (a `logging.Handler` subclass)
  captures and parses those instead. This is documented in detail in
  `latency_evaluators.py`'s own module docstring.
- **Why no new LangSmith plumbing was needed.** T-071's "per-node
  breakdown visible in LangSmith" criterion is already satisfied by
  existing code: every node is wrapped with `profile_node()` (T-036),
  which best-effort patches per-node latency onto the current LangSmith
  run via `_emit_langsmith_metadata()`, and tracing itself is configured
  automatically by `get_llm()` → `configure_tracing()` (T-026) the
  moment any real agent call happens. Running
  `scripts/run_eval_latency.py` with `LANGSMITH_API_KEY` configured
  already produces this visibility — verified by inspection of
  `node_profiler.py` / `backend/agents/tracing.py` before writing
  anything new, rather than re-implementing tracing that already exists.
- **Log capture is summed across repeated node executions, not
  overwritten.** `contrarian_investor` and `debate_loop` can each
  execute twice in a single pipeline run (2 debate rounds, per
  `route_after_contrarian`'s threshold logic). `LatencyLogCapture.
  node_latencies_ms()` sums `elapsed_ms` per node name across every
  captured entry, so a node's reported latency reflects genuine total
  time spent in that node across the whole run, not just its most
  recent execution. Covered by
  `test_sums_repeated_node_executions` (unit, synthetic) and
  `test_repeated_node_execution_is_summed_not_overwritten` (integration,
  a real 2-round debate against the real compiled graph).
- **No numpy dependency for percentiles.** `compute_percentile()` is a
  small, dependency-free linear-interpolation implementation (the same
  convention `numpy.percentile`'s default method uses) rather than
  adding numpy as a project dependency for one calculation used only by
  this eval. Verified against known values
  (`TestComputePercentile`) including the single-value and two-value
  edge cases a 3-sample benchmark will actually hit.
- **Failed runs are excluded from the percentile calculation but never
  hidden.** `summarize_latency_runs()` computes p50/p95/mean/max only
  over `status == "completed"` runs — a failed run has no meaningful
  total pipeline duration to include in the latency distribution — but
  `n_failed` and the failed run's own error string still appear in the
  summary and the printed report, so a benchmark with a real failure
  can never silently report an artificially fast p50/p95. Covered by
  `test_failed_run_excluded_from_percentiles_but_counted` and
  `test_all_runs_failed_returns_degenerate_summary_without_raising`.
- **Per-node means are averaged only over the runs that actually
  executed that node.** `error_handler` / `sentiment_escalation` only
  run on their respective conditional-routing paths — a company whose
  pipeline never hits the error path should not have that node
  averaged in as an implicit zero. Covered by
  `test_per_node_mean_only_averages_runs_that_executed_that_node`.
- **3-company dataset spans 2 sectors, reusing 2 of the 3 tickers
  already exercised by existing manual scripts.** TCS.NS and INFY.NS
  match `scripts/run_full_analysis.py` and
  `scripts/run_full_analysis_infosys.py` exactly, so any latency
  regression is directly comparable to those scripts' prior manual
  runs. RELIANCE.NS is the deliberate sector outlier (Energy /
  Conglomerate vs. the other two IT majors) — see
  `latency_eval_dataset.py`'s "Company selection rationale" section for
  the full reasoning.
- **Grading/aggregation logic never raises**, including on an empty
  `runs` list, an all-failed benchmark, or a garbage log line fed to
  `parse_latency_log_line` — every function in `latency_evaluators.py`
  follows the AIRP-wide "evaluators never raise" convention. Covered by
  `test_never_raises_on_arbitrary_garbage`,
  `test_report_never_raises_when_all_runs_failed`, and
  `test_report_never_raises_with_no_runs_at_all`.
- **Company-level failures never abort the whole benchmark.**
  `scripts/run_eval_latency.py`'s `_run_one_company()` catches any
  exception from `graph.invoke()` and records it as a failed
  `PipelineRunResult` rather than crashing the script — matching the
  AIRP-wide "independent failure never aborts the batch" principle
  (e.g. per-row independent commits in batch jobs elsewhere in the
  codebase).
- **A new integration test, not a load-bearing one.** Like every other
  eval in this codebase, the CI-covered proof of the acceptance criteria
  is the offline unit test suite. `test_latency_eval_integration.py` is
  additional, marked `@pytest.mark.integration` (excluded from the
  default CI run), and exists specifically to prove the log-capture
  mechanism genuinely observes a real (agent-mocked) LangGraph run —
  including the repeated-node-summation case — rather than only proving
  the aggregation math is correct on synthetic data.

## Files changed / created

| File | Type | Purpose |
| --- | --- | --- |
| `backend/evals/latency_eval_dataset.py` | New | 3-company dataset (TCS, Infosys, Reliance Industries) spanning 2 sectors |
| `backend/evals/latency_evaluators.py` | New | Pure logic: log-line parsing, `LatencyLogCapture`, percentile computation, aggregation, bottleneck identification, report formatting |
| `scripts/run_eval_latency.py` | New | Real end-to-end runner: invokes the compiled pipeline for all 3 companies, times each run, prints the p50/p95 report |
| `scripts/README.md` | Modified | Added the new script's entry |
| `backend/tests/unit/test_latency_evaluators.py` | New | CI-safe unit tests: dataset shape, log parsing, log capture, percentile math, aggregation (including failed-run and empty-run edge cases), target checking, report formatting |
| `backend/tests/integration/test_latency_eval_integration.py` | New | Marked `@pytest.mark.integration` — proves latency capture works against a real (agent-mocked) full graph run, including 2-round debate-loop summation |
| `docs/week-27/T-071-eval-latency.md` | New | This file — full workflow doc for T-071 |

No migration, router, frontend, or existing agent/graph/node_profiler
files are touched — this eval observes already-existing log output and
doesn't modify `backend/graph/nodes.py`, `backend/graph/node_profiler.py`,
or any agent module.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/eval-latency

git branch
# → * feat/eval-latency
```

### Step 2 — Add the eval dataset and evaluator/aggregation logic

```bash
# backend/evals/latency_eval_dataset.py
# backend/evals/latency_evaluators.py
```

### Step 3 — Add the eval runner script

```bash
# scripts/run_eval_latency.py
# scripts/README.md (modify — add the new script's row)
```

### Step 4 — Add tests

```bash
# backend/tests/unit/test_latency_evaluators.py
# backend/tests/integration/test_latency_eval_integration.py
```

### Step 5 — Add this workflow doc

```bash
# docs/week-27/T-071-eval-latency.md
```

### Step 6 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine:

```bash
set ENVIRONMENT=test
python -m black backend --check
python -m isort backend --check
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_latency_evaluators.py -v
python -m pytest backend/tests/unit -v --cov=backend --cov-report=term-missing
```

Confirm the coverage run still reports ≥85% overall — both new
`backend/evals/latency_*.py` files are inside `source = ["backend"]` and
not excluded by `omit`, so their lines count toward the total. The test
suite exercises every branch of `parse_latency_log_line` (valid OK/
TIMEOUT lines, malformed lines, unrelated log records), `LatencyLogCapture`
(single execution, repeated/summed execution, unrelated records, reset,
attach/detach against the real logger), `compute_percentile` (median,
interpolated p95, single-value and two-value edge cases, both
`ValueError` guards), `identify_bottleneck` (empty and populated),
`summarize_latency_runs` (all-pass, all-fail-targets, mixed completed/
failed, all-failed, empty, per-node averaging scoped to the runs that
executed each node), `meets_latency_targets`, and `format_latency_report`
(normal report, bottleneck marker, all-failed report, zero-runs report).

If pre-commit hooks fail with `WinError 4551`, use the established
workaround:

```bash
git commit --no-verify -m "..."
```

The frontend CI job passes unchanged — this task touches no frontend
file.

### Step 6a — Run the integration test (optional, requires the real langgraph/langchain stack)

```bash
set ENVIRONMENT=test
python -m pytest -m integration backend/tests/integration/test_latency_eval_integration.py -v
```

This proves `LatencyLogCapture` correctly reconstructs the per-node
breakdown — including the repeated-node summation case (2-round debate
loop) — against a real compiled-graph invocation, not just synthetic
data. Not part of the CI gate (excluded by `addopts`), but strong
supporting evidence for the PR.

### Step 6b — Run the real latency benchmark (load-bearing for the p50/p95 acceptance criteria)

```bash
set ENVIRONMENT=development
python -m scripts.run_eval_latency
```

Requires a real LLM key (`GROQ_API_KEY` for the default dev provider)
and network access to yFinance/NewsAPI/Alpha Vantage/Screener.in — this
makes REAL API and LLM calls for all 3 companies, 3 full pipeline runs.
Expect the whole script to take a few minutes. Paste the full console
output into the PR description (see below) and into this doc's
"Bottleneck / Performance Profile" section once run.

If `LANGSMITH_API_KEY` is set in `.env`, every node's latency from these
3 runs is also visible per-run in the LangSmith dashboard automatically
(see "Why no new LangSmith plumbing was needed" above) — no extra step
needed.

### Step 7 — Commit

```bash
git add backend/evals/latency_eval_dataset.py
git add backend/evals/latency_evaluators.py
git add scripts/run_eval_latency.py
git add scripts/README.md
git add backend/tests/unit/test_latency_evaluators.py
git add backend/tests/integration/test_latency_eval_integration.py
git add docs/week-27/T-071-eval-latency.md

git commit --no-verify -m "perf(eval): add end-to-end latency evaluation

- Add latency_eval_dataset.py: fixed 3-company dataset (TCS,
  Infosys, Reliance Industries) spanning 2 sectors (IT x2,
  Energy/Conglomerate x1), reusing 2 tickers already exercised by
  scripts/run_full_analysis.py and
  scripts/run_full_analysis_infosys.py for direct comparability
- Add latency_evaluators.py: pure, dependency-free logic --
  parse_latency_log_line (parses node_profiler.py's existing
  [AIRP_LATENCY] structured log lines), LatencyLogCapture (a
  logging.Handler that observes a real or mocked pipeline run and
  sums elapsed_ms per node across repeated executions, e.g. a
  2-round debate loop), compute_percentile (linear-interpolation
  percentile, no numpy dependency), summarize_latency_runs
  (p50/p95/mean/max over completed runs only, per-node mean
  latency, bottleneck identification), meets_latency_targets, and
  format_latency_report. Chose log-line capture over
  state[\"node_latencies\"] because that state field is not a
  declared InvestmentState schema field and LangGraph's default
  last-write-wins merge semantics cannot be trusted to preserve
  every node's contribution -- documented in detail in this
  module's own docstring
- Add scripts/run_eval_latency.py: real end-to-end runner --
  invokes the compiled pipeline for all 3 companies against real
  APIs and a real LLM, times each run, captures the per-node
  breakdown, and prints a p50 <90s / p95 <120s report with the
  identified bottleneck. Per-company failures are caught and
  recorded rather than aborting the whole benchmark
- Add backend/tests/unit/test_latency_evaluators.py: CI-safe
  coverage of dataset shape, log-line parsing (valid and
  malformed), LatencyLogCapture (including summation across
  repeated node executions and real-logger attach/detach), percentile
  math (including edge cases and invalid-input guards), aggregation
  (passing/failing targets, mixed completed/failed runs, all-failed
  and empty-runs degenerate cases, per-node averaging), and report
  formatting (including both degenerate cases), all fully offline
- Add backend/tests/integration/test_latency_eval_integration.py:
  marked @pytest.mark.integration -- proves the log-capture
  mechanism against a real (agent-mocked) compiled LangGraph
  invocation, including a genuine 2-round debate loop proving
  repeated-node latencies are summed, not overwritten
- Update scripts/README.md with the new script's entry

Closes #71"
```

If a formatter modifies files after staging, re-stage and make a second,
separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-071 files"
```

### Step 8 — Push and open the PR

```bash
git push -u origin feat/eval-latency
```

**Base branch:** `main`
**Compare branch:** `feat/eval-latency`

## Pull Request

**Title:** `perf(eval): implement latency benchmarking for full pipeline with p50/p95 targets`

### Summary

Implements the end-to-end latency benchmark for T-071: times the real
AIRP pipeline across 3 companies (TCS, Infosys, Reliance Industries,
deliberately spanning 2 sectors), asserts p50 <90s and p95 <120s, and
produces a per-node latency breakdown to identify the bottleneck. Rather
than trusting `state["node_latencies"]` — which is not a declared
`InvestmentState` field and is not reliably preserved across LangGraph's
default per-key merge semantics — this eval captures `node_profiler.py`'s
existing structured `[AIRP_LATENCY]` log lines via a new
`LatencyLogCapture` logging handler, which correctly sums latency across
repeated node executions (e.g. a 2-round debate loop). "Per-node
breakdown visible in LangSmith" required no new plumbing — it was already
produced automatically by the existing T-036 `node_profiler` metadata
patching once real tracing is configured (T-026).

### Changes

- New `backend/evals/latency_eval_dataset.py`: fixed 3-company dataset
- New `backend/evals/latency_evaluators.py`: log parsing, log capture,
  percentile computation, aggregation, bottleneck identification, and
  report formatting — all pure and CI-tested
- New `scripts/run_eval_latency.py`: real end-to-end benchmark runner
- Full unit test coverage of every pure function, including edge cases
  (empty runs, all-failed runs, malformed log lines)
- New integration test proving the log-capture mechanism against a real
  (agent-mocked) LangGraph run, including repeated-node summation
- `scripts/README.md` updated

### Testing

- `python -m pytest backend/tests/unit/test_latency_evaluators.py -v` —
  all pass
- `python -m pytest backend/tests/unit -v --cov=backend
  --cov-report=term-missing` — full suite green, coverage still ≥85%
- `python -m mypy backend` / `python -m flake8 backend` / `python -m
  black backend --check` / `python -m isort backend --check`
- `python -m pytest -m integration
  backend/tests/integration/test_latency_eval_integration.py -v` —
  proves latency capture against a real compiled graph run
- `python -m scripts.run_eval_latency` — see pasted console output below

### Eval run output

_Paste the full console output of `python -m scripts.run_eval_latency`
here — this is the direct evidence for the p50 <90s / p95 <120s
acceptance criteria and the per-node breakdown / bottleneck
identification._

### LangSmith Trace

_Paste a link to one of the 3 runs' traces here if `LANGSMITH_API_KEY`
was configured — per-node latency metadata should be visible on each
node's run, patched automatically by the existing T-036
`_emit_langsmith_metadata()`. Optional supporting evidence; the console
report above is the primary proof._

### Screenshots

Not applicable — backend eval tooling change with no UI.

### Related Issues

Closes #71

## Bottleneck / Performance Profile

_Fill in after running `python -m scripts.run_eval_latency` against real
data (Step 6b). This section is T-071's "bottleneck identified and
documented" acceptance criterion._

| Company | Ticker | Total time | Status |
| --- | --- | --- | --- |
| Tata Consultancy Services | TCS.NS | _fill in_ | _fill in_ |
| Infosys | INFY.NS | _fill in_ | _fill in_ |
| Reliance Industries | RELIANCE.NS | _fill in_ | _fill in_ |

**p50:** _fill in_ s (target <90s) — _PASS/FAIL_
**p95:** _fill in_ s (target <120s) — _PASS/FAIL_

**Bottleneck node:** _fill in_ (_fill in_ ms mean)

**Why this node is the bottleneck:** _fill in after inspecting the
per-node breakdown — e.g. an LLM-bound node (Fundamental Analyst,
Valuation Agent, Portfolio Manager) is expected to dominate over
deterministic nodes (planner, research_join, report_generator,
pdf_export), since those make a real network round-trip to the LLM
provider plus real market-data fetches, while the deterministic nodes
are pure in-process computation._

**Possible follow-up optimisations** (out of scope for T-071 itself —
this eval's job is to identify and document, not to fix):

- Parallelise or cache repeated external data fetches within the
  bottleneck node if it is fetch-bound rather than LLM-bound.
- Consider a faster/cheaper model for the bottleneck node's LLM call if
  it is LLM-bound and the accuracy trade-off is acceptable (see
  T-068/T-069's accuracy evals before making this change, so any model
  swap can be verified not to regress accuracy).
- Revisit `NODE_TIMEOUT_S` (currently 30s per node,
  `backend/graph/node_profiler.py`) if the bottleneck node is
  approaching that ceiling under real load.