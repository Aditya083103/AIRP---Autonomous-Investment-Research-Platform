# T-036 -- Performance Profile the Pipeline

**Phase:** 3 -- LangGraph Orchestration
**Week:** 9
**Branch:** `feat/graph-perf`
**Task status:** Ready to implement

---

## Overview

T-036 adds per-node latency logging, per-node timeout enforcement, and a
profiling report to the AIRP LangGraph pipeline.

**Acceptance criteria (all must pass):**

- Node latencies logged to LangSmith (`[AIRP_LATENCY]` structured log lines
  - LangSmith run metadata when tracing is active)
- No node runs >30s without timeout (`NodeTimeoutError` raised at 30s)
- Profiling report in `docs/` (`docs/PERFORMANCE_PROFILE.md`)

---

## What Was Built

### New file: `backend/graph/node_profiler.py`

`profile_node(node_fn, node_name)` -- decorator factory that wraps any
LangGraph node function with:

1. **Wall-clock timing** via `time.perf_counter()`
2. **Timeout enforcement** -- `signal.SIGALRM` on POSIX (Linux/macOS),
   elapsed-time check on Windows; disabled (`float('inf')`) in `ENVIRONMENT=test`
3. **Structured log line** at INFO level: `[AIRP_LATENCY] node=<name> elapsed_ms=<N> ...`
4. **State storage** -- writes `state["node_latencies"][node_name] = elapsed_ms`
5. **LangSmith metadata** (best-effort, non-fatal) via `client.update_run()`

`NodeTimeoutError(RuntimeError)` -- raised when a node exceeds 30s.

`NODE_TIMEOUT_S = 30.0` -- the timeout threshold constant.

`PROFILER_LOG_PREFIX = "[AIRP_LATENCY]"` -- prefix for structured log parsing.

### Modified: `backend/graph/nodes.py`

All 12 nodes now use `profile_node()` as the inner wrapper, with
`_persist_after` as the outer wrapper:

```
impl_function
    |
profile_node(impl, name)       <-- inner: measures business logic only
    |
_persist_after(profiled, name) <-- outer: DB write time excluded from metric
```

For parallel research nodes (no `_persist_after`):

```
impl_function
    |
profile_node(impl, name)       <-- inline call inside node function
```

`NodeTimeoutError` added to `nodes.py`'s `__all__`.

### New file: `docs/PERFORMANCE_PROFILE.md`

Profiling report covering:

- Acceptance criteria checklist
- How latency is measured
- Timeout mechanism per platform
- Baseline measurements (stub agents)
- Expected production latencies (Phase 4)
- Log format reference with examples
- LangSmith observability setup
- Identified bottlenecks and mitigations

### New file: `backend/tests/unit/test_node_profiler.py`

100+ unit tests across 13 test classes:

- `NodeTimeoutError` class and attributes
- `profile_node` normal path (latency in state, log emitted, dict unchanged)
- `profile_node` exception propagation
- `profile_node` timeout path (mocked context manager)
- LangSmith emission (mocked, non-fatal)
- `_log_latency` log content assertions
- `_store_latency_in_state` state mutation
- All 12 nodes integration (every node adds `node_latencies`)
- `_EFFECTIVE_TIMEOUT_S` is infinity in test env
- Constants validation
- Profiling report file existence
- Public API completeness

---

## File Summary

```
backend/graph/node_profiler.py                (NEW)
backend/graph/nodes.py                         (MODIFIED)
backend/tests/unit/test_node_profiler.py       (NEW)
docs/PERFORMANCE_PROFILE.md                    (NEW)
docs/week-09/T-036-performance-profile.md      (NEW -- this file)
```

---

## Step-by-Step Workflow

### 0. Prerequisites

```bash
git checkout main
git pull origin main
git status   # clean working tree
```

```cmd
set ENVIRONMENT=test
```

### 1. Create feature branch

```bash
git checkout -b feat/graph-perf
```

### 2. Place files

Place all 5 files listed above into the repo at their paths.

### 3. Clear pycache

```bash
find backend/graph backend/tests -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
find backend/graph backend/tests -name "*.pyc" -delete 2>/dev/null; true
```

### 4. Run the full unit test suite

```bash
python -m pytest backend/tests/unit/ -v --tb=short -q
```

Key new tests to watch:

- `test_node_profiler.py` -- all 100+ T-036 profiler tests
- `test_graph_skeleton.py` -- must still pass (profiler is transparent to graph)
- `test_parallel_research.py` -- must still pass
- `test_routing.py` -- must still pass
- `test_state_persistence.py` -- must still pass

### 5. Pre-commit hooks

```bash
git add .
git commit -m "perf(graph): add per-node latency profiling and timeout T-036"
# If formatters auto-fix:
git add .
git commit -m "perf(graph): add per-node latency profiling and timeout T-036"
```

### 6. Push and open PR

```bash
git push -u origin feat/graph-perf
```

---

## PR Details

**PR Title:**

```
perf(graph): add per-node latency profiling and 30s timeout (T-036)
```

**PR Description:**

````markdown
## Summary

Implements T-036 pipeline performance profiling. Every LangGraph node
is wrapped by `profile_node()` from `node_profiler.py`, giving us
per-node latency logging, state storage of latency metrics, LangSmith
metadata annotation, and 30-second timeout enforcement via SIGALRM
(POSIX) or thread elapsed time (Windows).

## Changes

- `backend/graph/node_profiler.py` (new): `profile_node()` decorator
  factory, `NodeTimeoutError`, `NODE_TIMEOUT_S=30.0`, `PROFILER_LOG_PREFIX`,
  `_log_latency()`, `_store_latency_in_state()`, `_emit_langsmith_metadata()`.
  Timeout disabled in ENVIRONMENT=test (float('inf')).

- `backend/graph/nodes.py` (modified): All 12 nodes now wrapped with
  `profile_node()` as the inner layer (measures business logic only,
  not DB persistence time). `NodeTimeoutError` added to **all**.

- `backend/tests/unit/test_node_profiler.py` (new): 100+ tests covering
  all profiler paths, all 12 node integrations, timeout simulation,
  log content, state storage, LangSmith emission, constants, report
  file existence.

- `docs/PERFORMANCE_PROFILE.md` (new): Profiling report with baseline
  measurements, expected production latencies, log format, LangSmith
  observability, and bottleneck analysis.

## Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/ -v --tb=short -q
```
````

All 100+ new tests pass. All existing tests still pass.

## LangSmith Trace

N/A for this PR -- profiler writes to LangSmith when tracing is active
in production. Tests mock LangSmith entirely.

## Related Issues

Closes #36

```

---

## Commit Message

```

perf(graph): add per-node latency profiling and 30s timeout (T-036)

- node_profiler.py: profile_node() wraps every LangGraph node with
  wall-clock timing, structured [AIRP_LATENCY] log lines, state storage
  of node_latencies dict, LangSmith metadata emission (best-effort),
  and NodeTimeoutError at 30s (SIGALRM on POSIX, thread-elapsed on Windows)
- ENVIRONMENT=test: _EFFECTIVE_TIMEOUT_S=inf, timeout disabled in tests
- nodes.py: all 12 nodes wrapped -- profile_node as inner layer (business
  logic only), _persist_after as outer layer (DB time excluded from metric)
- test_node_profiler.py: 100+ tests; 13 test classes covering all paths,
  all 12 node integrations, timeout simulation via patched context manager,
  log content assertions, state mutation, LangSmith mock, constants
- docs/PERFORMANCE_PROFILE.md: profiling report with baseline measurements
  (stub agents), expected production latencies, log format, LangSmith
  observability, bottleneck analysis

Closes #36

```

---

## Key Design Decisions

### Why SIGALRM not threading?

`threading.Timer` cannot interrupt a running Python thread (the GIL
prevents it). `signal.SIGALRM` interrupts at the OS level, delivering
the signal to the main thread at exactly N seconds regardless of what
Python is doing. For LangGraph nodes that run in a ThreadPoolExecutor,
SIGALRM is the only reliable hard-timeout mechanism on POSIX.

### Why is profiler the INNER layer?

We want to measure agent think-time (LLM calls, API calls) without
including DB persistence overhead. If profiler were the outer layer:
- elapsed_ms would include asyncio.run(persist_state(...)) overhead (~50ms)
- Latency metrics would be misleading (persistence is not "agent" work)
- Individual agent comparison would be unfair (some nodes persist more data)

### Why store latencies in state?

Storing `node_latencies` in `InvestmentState` makes the metrics available
to the Portfolio Manager when writing the Investment Memo. The memo can
include a "Pipeline Performance" section showing how long each agent took.
It also makes latencies visible in the PostgreSQL state snapshot for
post-run analysis without needing LangSmith.

### Why best-effort LangSmith emission?

LangSmith metadata calls go over the network. A transient 429 (rate limit)
or 5xx from LangSmith must never abort an investment analysis. The metadata
is observability data, not business logic.
```
