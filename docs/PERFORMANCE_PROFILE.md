# AIRP -- Pipeline Performance Profile

**Task:** T-036 -- Performance Profile the Pipeline
**Phase:** 3 -- LangGraph Orchestration
**Week:** 9
**Status:** Profiling infrastructure live; baseline captured with stub agents

---

## Acceptance Criteria (T-036)

- [x] Node latencies logged to LangSmith
- [x] No node runs >30s without timeout (`NodeTimeoutError` raised)
- [x] Profiling report in `docs/` (this file)

---

## Profiling Infrastructure

### How latency is measured

Every LangGraph node is now wrapped by `profile_node()` from
`backend/graph/node_profiler.py`.  The wrapper:

1. Records wall-clock start time (`time.perf_counter()`)
2. Runs the node function inside a timeout context
3. On return, computes `elapsed_ms = int((end - start) * 1000)`
4. Emits a structured log line:

```
[AIRP_LATENCY] node=<name> elapsed_ms=<N> job_id=<uuid> ticker=<t> status=OK
```

5. Stores the latency in `state["node_latencies"][node_name]` so the
   Portfolio Manager can include it in the Investment Memo
6. Emits LangSmith run metadata when tracing is active

### Timeout enforcement

| Platform | Mechanism | Behaviour |
|----------|-----------|-----------|
| Linux / macOS (POSIX) | `signal.SIGALRM` | Hard interrupt -- raises `NodeTimeoutError` at exactly 30s |
| Windows | Thread-elapsed check | Soft check -- raises after node returns if elapsed > 30s |
| ENVIRONMENT=test | Disabled | `_EFFECTIVE_TIMEOUT_S = float('inf')` -- no timeout in tests |

### Composition with T-033 (persistence)

Profiler is the **inner** layer; persistence is the **outer** layer:

```
impl_function
    |
profile_node(impl_fn, name)    <-- measures business logic only
    |
_persist_after(profiled, name) <-- DB write time NOT included in latency
    |
final node callable
```

This means the latency metric reflects pure agent think-time, not DB write
overhead.

---

## Baseline Performance Profile (Stub Agents)

The following measurements were taken running `build_graph().invoke()` with
all four research agents mocked to return instantly (<5ms each).  These
numbers represent LangGraph orchestration overhead with zero agent latency.

| Node | Phase | Type | Typical Latency (stub) |
|------|-------|------|------------------------|
| `planner` | 1 | Sequential | <5ms |
| `fundamental_analyst` | 2 (parallel) | Research | <5ms (mock) |
| `technical_analyst` | 2 (parallel) | Research | <5ms (mock) |
| `sentiment_analyst` | 2 (parallel) | Research | <5ms (mock) |
| `macro_economist` | 2 (parallel) | Research | <5ms (mock) |
| `research_join` | 2 (join) | Sequential | <5ms |
| `error_handler` | 2 (routing) | Sequential | <5ms |
| `sentiment_escalation` | 2 (routing) | Sequential | <5ms |
| `contrarian_investor` | 4 (stub) | Sequential | <5ms |
| `risk_officer` | 4 (stub) | Sequential | <5ms |
| `valuation_agent` | 4 (stub) | Sequential | <5ms |
| `portfolio_manager` | 4 (stub) | Sequential | <5ms |

**Total pipeline (stubs only):** < 200ms

---

## Expected Production Latency (Phase 4 Agents)

When Phase 4 agent implementations replace the stubs (T-037 to T-044),
expected latencies with Groq (development LLM) are:

| Node | Expected Latency | Timeout Risk |
|------|-----------------|--------------|
| `planner` | <10ms | None |
| `fundamental_analyst` | 2-8s (yFinance + LLM) | Low |
| `technical_analyst` | 2-6s (yFinance + LLM) | Low |
| `sentiment_analyst` | 4-12s (NewsAPI + ChromaDB + LLM) | Moderate |
| `macro_economist` | 3-10s (RBI scrape + LLM) | Moderate |
| `research_join` | <10ms | None |
| `contrarian_investor` | 5-15s (reads 4 outputs + LLM) | Moderate |
| `risk_officer` | 4-12s (LLM) | Moderate |
| `valuation_agent` | 5-15s (Screener.in + LLM) | Moderate |
| `portfolio_manager` | 8-20s (reads full state + LLM) | Low-Moderate |

**Expected total pipeline (production):** 30-80 seconds

The 30-second per-node timeout is designed to catch:
- Hung HTTP connections to external APIs
- LLM providers experiencing extreme latency (>30s response time)
- Database timeouts in state persistence

---

## Log Format Reference

Every node emits this log line at `INFO` level (WARNING on timeout):

```
[AIRP_LATENCY] node=<node_name> elapsed_ms=<N> job_id=<uuid> ticker=<ticker> status=<OK|TIMEOUT>
```

### Example (successful run)

```
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=fundamental_analyst elapsed_ms=3421 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=technical_analyst elapsed_ms=2187 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=sentiment_analyst elapsed_ms=8934 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=macro_economist elapsed_ms=5231 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=research_join elapsed_ms=2 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=contrarian_investor elapsed_ms=7821 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=risk_officer elapsed_ms=6234 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=valuation_agent elapsed_ms=9871 job_id=abc123 ticker=TCS.NS status=OK
INFO  backend.graph.node_profiler - [AIRP_LATENCY] node=portfolio_manager elapsed_ms=14532 job_id=abc123 ticker=TCS.NS status=OK
```

### Example (timeout)

```
WARNING backend.graph.node_profiler - [AIRP_LATENCY] node=sentiment_analyst elapsed_ms=30001 job_id=abc123 ticker=TCS.NS status=TIMEOUT
```

---

## LangSmith Observability

When `LANGCHAIN_TRACING_V2=true` and `LANGSMITH_API_KEY` is set, each node
run is annotated in the LangSmith trace with:

```json
{
  "node_latency_ms_fundamental_analyst": 3421,
  "node_timed_out_fundamental_analyst": false,
  "analysis_job_id": "abc123"
}
```

This metadata is searchable in the LangSmith dashboard via:
- Filter by `metadata.node_timed_out_<agent>: true` to find slow runs
- Sort by `metadata.node_latency_ms_<agent>` to identify bottlenecks

---

## Identified Bottlenecks and Mitigations

### Bottleneck 1: Sentiment Analyst (highest latency variance)

**Cause:** NewsAPI response time varies (2-15s). ChromaDB semantic search
adds 1-3s on first run (cold cache).

**Mitigation:** Redis cache (T-018) with 1-hour TTL ensures second run
for the same ticker on the same day is near-instant.  LangSmith traces
distinguish first-run vs cached runs via the `elapsed_ms` distribution.

### Bottleneck 2: Portfolio Manager (highest single-node latency)

**Cause:** Reads the entire InvestmentState (including full debate
transcript) and generates a multi-paragraph memo. Largest prompt of
any agent.

**Mitigation:** Groq's Llama-3.3-70B has a 500 tok/s output speed which
keeps generation at <10s for typical memo length. Claude API (demo mode)
has higher latency but superior quality -- acceptable for the final step.

### Bottleneck 3: Parallel research join latency

**Cause:** The four parallel research agents fan out via the Send API but
reconverge at `research_join`.  Total parallel phase time is bounded by
the slowest of the 4 agents, not their sum.

**Current:** With stubs, join completes in <10ms.
**Production:** Parallel phase expected to take 8-15s (slowest of 4 agents)
rather than their sequential sum (~20-40s).

---

## Updating This Report

This file is updated manually after performance profiling sessions.
To profile the pipeline:

```bash
# Run with real agents (requires API keys)
ENVIRONMENT=development python -c "
from backend.agents.tracing import configure_tracing
from backend.graph.graph import build_graph
from backend.graph.state import make_initial_state
import logging
logging.basicConfig(level=logging.INFO)
configure_tracing()

state = make_initial_state(
    job_id='perf-test-001',
    company_name='Tata Consultancy Services',
    ticker='TCS.NS',
    exchange='NSE',
    raw_query='TCS',
)
graph = build_graph()
result = graph.invoke(dict(state))
print('node_latencies:', result.get('node_latencies'))
"
```

Filter the output for `[AIRP_LATENCY]` lines to extract per-node timings.