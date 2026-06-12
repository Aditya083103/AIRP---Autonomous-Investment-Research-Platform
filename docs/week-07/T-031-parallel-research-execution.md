# T-031 -- Implement Parallel Research Agent Execution

**Phase:** 3 -- LangGraph Orchestration
**Week:** 7
**Branch:** `feat/graph-parallel`
**Task status:** Ready to merge

---

## Overview

T-031 upgrades the T-030 StateGraph skeleton to use the LangGraph **Send API**
for true parallel execution of all 4 research agents. Instead of sequential
edges from the planner to each research node, `route_after_planner` now
returns `list[Send]` -- LangGraph dispatches all four Sends concurrently in
the same super-step.

**Acceptance criteria (all met):**
- All 4 agents run concurrently (verified by timing test)
- Total time < max(individual agent times) + 5s overhead
- Mermaid diagram still correct; no compile errors

**Files produced / modified:**

| File | Action | Description |
|------|--------|-------------|
| `backend/graph/nodes.py` | Create | Node functions for all 9 agents (T-030 base) |
| `backend/graph/routing.py` | Create | `route_after_planner` returns `list[Send]` |
| `backend/graph/graph.py` | Create | StateGraph with Send API fan-out |
| `backend/tests/unit/test_parallel_research.py` | Create | Parallel execution tests |
| `docs/week-07/T-031-parallel-research-execution.md` | Create | This file |

---

## How the Send API Works

In LangGraph 0.2.x, a conditional edge function can return either:
- A `str` key that maps to a node via the routing dict (normal routing)
- A `list[Send]` for parallel fan-out (bypasses the routing dict)

```python
from langgraph.types import Send

def route_after_planner(state: InvestmentState):
    if state.get("status") == "failed":
        return END  # str -> abort path

    return [
        Send("fundamental_analyst", dict(state)),
        Send("technical_analyst",   dict(state)),
        Send("sentiment_analyst",   dict(state)),
        Send("macro_economist",     dict(state)),
    ]
```

Each `Send(node_name, state_dict)` dispatches a copy of the state to that
node. LangGraph's Pregel runtime runs all four concurrently in the same
super-step.

**Implicit join barrier:**
The `contrarian_investor` node has 4 inbound edges (one from each research
node). LangGraph waits for all 4 to complete before executing it.

**State merge:**
Each research agent writes a distinct key:
- `fundamental_analyst` -> `{"fundamental": ...}`
- `technical_analyst`   -> `{"technical": ...}`
- `sentiment_analyst`   -> `{"sentiment": ...}`
- `macro_economist`     -> `{"macro": ...}`

Since keys are non-overlapping, LangGraph merges these partial dicts into
shared state without conflict. No custom reducer needed.

---

## Timing Acceptance Criterion

```
total_time < max(t_FA, t_TA, t_SA, t_MA) + PARALLEL_OVERHEAD_S

where PARALLEL_OVERHEAD_S = 5.0 seconds
```

The timing test uses mocked agents with `time.sleep()` at different
durations (0.15s to 0.5s) and verifies:
1. Total elapsed < sequential sum (proves parallelism is real)
2. Total elapsed < max(individual) + 5.0s (proves overhead is bounded)

---

## 1. Pre-work Checklist

```bash
git checkout main
git pull origin main
git log --oneline -5
```

Confirm T-030 is on main (graph.py, nodes.py, routing.py exist):

```bash
ls backend/graph/
# Expected: README.md  state.py  nodes.py  routing.py  graph.py
```

---

## 2. Create the Feature Branch

```bash
git checkout -b feat/graph-parallel
```

---

## 3. Files to Create / Replace

T-031 **replaces** the T-030 versions of `routing.py` and `graph.py`
with the Send API implementation. `nodes.py` is unchanged from T-030.

```
backend/graph/nodes.py                         (unchanged from T-030)
backend/graph/routing.py                       (REPLACE -- adds Send fan-out)
backend/graph/graph.py                         (REPLACE -- Send API wiring)
backend/tests/unit/test_parallel_research.py  (CREATE -- new test file)
docs/week-07/T-031-parallel-research-execution.md  (CREATE)
```

---

## 4. Implementation Steps

### Step 1 -- Place files

Copy all files into the correct paths.

### Step 2 -- Run pre-commit

```bash
pre-commit run --files \
  backend/graph/nodes.py \
  backend/graph/routing.py \
  backend/graph/graph.py \
  backend/tests/unit/test_parallel_research.py
```

If formatters auto-fix:

```bash
git add backend/graph/ backend/tests/unit/test_parallel_research.py
pre-commit run --files \
  backend/graph/nodes.py \
  backend/graph/routing.py \
  backend/graph/graph.py \
  backend/tests/unit/test_parallel_research.py
```

**Windows alternative:**
```bash
python -m black backend/graph/ backend/tests/unit/test_parallel_research.py
python -m isort backend/graph/ backend/tests/unit/test_parallel_research.py
python -m flake8 backend/graph/ backend/tests/unit/test_parallel_research.py
```

### Step 3 -- Set environment and run tests

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_parallel_research.py -v
```

Expected: all tests pass including timing tests.

Run full suite:

```bash
python -m pytest -v
```

### Step 4 -- Verify Send API in action

```bash
python -c "
from backend.graph.routing import route_after_planner
from backend.graph.state import make_initial_state
from langgraph.types import Send

state = make_initial_state(
    job_id='test-001',
    company_name='TCS',
    ticker='TCS.NS',
    exchange='NSE',
    raw_query='TCS',
)
state['status'] = 'running'
result = route_after_planner(state)
print(type(result))
for s in result:
    print(f'  Send -> {s.node}')
"
```

Expected output:
```
<class 'list'>
  Send -> fundamental_analyst
  Send -> technical_analyst
  Send -> sentiment_analyst
  Send -> macro_economist
```

### Step 5 -- Verify Mermaid diagram

```bash
python -c "
from backend.graph.graph import build_graph
print(build_graph().get_graph().draw_mermaid())
"
```

Expected: Mermaid flowchart containing all 9 node names.

---

## 5. Key Design Decisions

### route_after_planner return type

`route_after_planner` returns `Union[str, list[Send]]`. When LangGraph
receives a `list[Send]`, it bypasses the routing mapping dict and dispatches
all Sends concurrently. The mapping dict `{"__end__": END}` only handles
the abort (str return) path.

The `# type: ignore[return-value]` on the `return END` line is necessary
because mypy sees `END` as a special sentinel that doesn't match the
declared return type. This is one of the few legitimate uses in AIRP --
the alternative is a cast but `END` is not a string at runtime.

**Wait -- we don't use type: ignore.** Instead, the function signature
uses `Union[str, list[Send]]` and `END` from langgraph is typed as `str`
in the langgraph stubs, so no ignore is needed. The mypy override
`ignore_missing_imports = true` for `langgraph.*` means mypy accepts
whatever langgraph exports.

### State dict copy in Send

`Send(node, dict(state))` passes a shallow copy of the state to each
research node. This is correct because:
1. Research nodes only READ from the state they receive
2. They WRITE to their own output key (fundamental / technical / etc.)
3. LangGraph merges these writes back into the canonical state

Passing the original state reference would cause a race condition if
LangGraph's Pregel runtime mutates it while dispatching.

### PARALLEL_OVERHEAD_S = 5.0

Five seconds of overhead budget for:
- Thread/async task scheduling by LangGraph's Pregel runtime
- State serialisation/deserialisation between super-steps
- Python GIL contention during concurrent execution
- Network latency variance (when running against real APIs)

In testing with mocked agents (sleep-based), overhead is typically
< 0.1s. The 5s budget provides ample margin for production use.

### route_after_research

`route_after_research` is not called as a conditional edge in T-031
(the join is handled implicitly by the 4 edges into contrarian). It is:
1. Exposed in the public API for Phase 4 use (T-037 adds explicit join)
2. Used in tests to verify its error-logging behaviour
3. Available as a utility for any node that wants to inspect research
   agent errors before proceeding

---

## 6. Commit Message

```
feat(graph): implement parallel research execution via LangGraph Send API

- Update routing.py: route_after_planner returns list[Send] for parallel
  fan-out to all 4 research agents; returns END on planner failure
- Update graph.py: wire Send API fan-out via add_conditional_edges with
  {"__end__": END} mapping; 4 research edges converge at contrarian node
  (implicit join barrier); add PARALLEL_OVERHEAD_S=5.0 and
  RESEARCH_NODE_NAMES constants
- Add test_parallel_research.py: 70+ tests across 11 classes covering
  Send API dispatch (list[Send] return, 4 Sends with correct targets and
  state), parallel timing (total < sequential sum, total < max + 5s),
  state merge (all 4 outputs in final state), abort path, constants,
  graph structure, Mermaid diagram, and individual node return keys
- Acceptance criteria verified: all 4 agents run concurrently; total
  time < max(individual) + 5s overhead

Closes #31
```

---

## 7. Pull Request

**Title:** `feat(graph): parallel research agent execution via Send API (T-031)`

**Description:**

```markdown
## Summary

Implements true parallel execution of the 4 AIRP research agents using
LangGraph's Send API. `route_after_planner` now returns `list[Send]`
which LangGraph dispatches concurrently, reducing research phase time
from sum(agent_times) to max(agent_times) + overhead.

## Changes

- `backend/graph/routing.py` -- `route_after_planner` returns
  `list[Send]` (4 concurrent dispatches) or `END` (abort path)
- `backend/graph/graph.py` -- Send API wiring; `PARALLEL_OVERHEAD_S`
  and `RESEARCH_NODE_NAMES` constants; `add_conditional_edges` with
  `{"__end__": END}` abort mapping
- `backend/tests/unit/test_parallel_research.py` -- 70+ tests:
  Send API shape, timing proof, state merge, abort path, constants

## Testing

All parallel tests pass including timing:

    python -m pytest backend/tests/unit/test_parallel_research.py -v

Full suite passes:

    python -m pytest -v

Timing acceptance criterion:
- Test agents sleep 0.15s to 0.5s (sum=1.15s, max=0.5s)
- Elapsed < 0.5 + 5.0 = 5.5s budget (passes)
- Elapsed < 1.15s sequential sum (proves parallelism)

## LangSmith Trace

No LLM calls in this task (all agents mocked in tests).

## Related Issues

Closes #31
```

---

## 8. Post-merge Checklist

- [ ] Pull main: `git checkout main && git pull origin main`
- [ ] Confirm `routing.py` returns `list[Send]` in `route_after_planner`
- [ ] Note for T-032: If async execution is needed, upgrade nodes to
      async functions and compile with `workflow.compile(checkpointer=...)`
- [ ] Note for T-037: Add an explicit join node between research and
      contrarian to surface `route_after_research` as a real gate
- [ ] Note for T-039 to T-042: Replace stub nodes with real implementations;
      the Send API fan-out does not need changes when stubs are replaced