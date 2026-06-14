# T-035 -- Write LangGraph Integration Tests

**Phase:** 3 -- LangGraph Orchestration
**Week:** 9
**Branch:** `feat/graph-tests`
**Task status:** Ready to implement

---

## Overview

T-035 adds end-to-end integration tests for the full AIRP LangGraph
StateGraph.  These tests call `build_graph().invoke()` on a real
compiled graph -- all 12 nodes, real routing functions, real state merging
-- with only the external API calls (research agents and DB persistence)
mocked.

**Acceptance criteria (all must pass):**
- Full pipeline runs in <2 minutes on mock data
- All state fields populated after pipeline completion
- Error routing verified:
  - `fetch_financials` empty -> `error_handler` node -> `FUNDAMENTAL_DATA_UNAVAILABLE` flag
  - `sentiment_score < -0.8` -> `sentiment_escalation` node -> `NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH` flag

---

## Test File

`backend/tests/integration/test_graph_integration.py`

Marked with `@pytest.mark.integration` (excluded from default pytest run).

### Test classes (7 classes, 86 test methods)

| Class | What it tests |
|-------|--------------|
| `TestHappyPath` | Full pipeline on clean mock data; all fields populated |
| `TestErrorRoutingFundamentals` | `fetch_financials` returns empty -> error path |
| `TestErrorRoutingNegativeSentiment` | `sentiment_score = -0.92` -> escalation path |
| `TestPipelineTiming` | All 3 paths complete in <120 seconds |
| `TestPlannerAbortPath` | Planner aborts when ticker is missing |
| `TestStateFieldPopulation` | Every state field present and has correct type |
| `TestMultipleRuns` | Two runs produce independent results (no state leakage) |

### What is mocked vs real

| Component | Mocked? | Reason |
|-----------|---------|--------|
| `run_fundamental_analysis` | Yes | No external APIs in integration tests |
| `run_technical_analysis` | Yes | No external APIs |
| `run_sentiment_analysis` | Yes | No external APIs |
| `run_macro_analysis` | Yes | No external APIs |
| `_run_persist` | Yes | No DB connection in tests |
| `export_mermaid_diagram` | Yes | No filesystem writes |
| `build_graph()` / LangGraph | **No** | Real graph compilation and execution |
| `planner_node` | **No** | Real validation logic |
| `research_join_node` | **No** | Real join barrier |
| `error_handler_node` | **No** | Real flag writing |
| `sentiment_escalation_node` | **No** | Real flag writing |
| `route_after_planner/research/contrarian` | **No** | Real routing thresholds |

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
git checkout -b feat/graph-tests
```

### 2. Place the file

```
backend/tests/integration/test_graph_integration.py  (NEW)
docs/week-09/T-035-graph-integration-tests.md        (NEW -- this file)
```

### 3. Clear stale pycache

```bash
find backend/tests -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
find backend/tests -name "*.pyc" -delete 2>/dev/null; true
```

### 4. Run the integration tests

Integration tests are excluded from the default pytest run.
Run them explicitly:

```bash
python -m pytest -m integration -v --tb=short
```

Expected output:
```
backend/tests/integration/test_graph_integration.py::TestHappyPath::... PASSED
...
86 passed in Xs
```

**Key timing check** -- the `TestPipelineTiming` class verifies <120s:
```bash
python -m pytest -m integration -v -k "Timing" --tb=short
```

### 5. Run the normal unit test suite (must still pass)

```bash
python -m pytest backend/tests/unit/ -v --tb=short -q
```

All existing unit tests must still pass (the new file adds no unit tests).

### 6. Pre-commit hooks

```bash
git add .
git commit -m "test(graph): add LangGraph end-to-end integration tests T-035"
# If formatters auto-fix:
git add .
git commit -m "test(graph): add LangGraph end-to-end integration tests T-035"
```

### 7. Push and open PR

```bash
git push -u origin feat/graph-tests
```

---

## PR Details

**PR Title:**

```
test(graph): add LangGraph end-to-end integration tests (T-035)
```

**PR Description:**

```markdown
## Summary

Implements T-035 LangGraph end-to-end integration tests. Tests run the
full compiled StateGraph (12 nodes, real routing, real state merging) with
mocked research agents and DB persistence. Verifies all 3 acceptance
criteria: <2min runtime, all state fields populated, error routing correct.

## Changes

- `backend/tests/integration/test_graph_integration.py` (new):
  7 test classes, 86 test methods covering:
  - Happy path: full pipeline, all fields populated
  - Error routing: `fetch_financials` empty -> `error_handler` ->
    `FUNDAMENTAL_DATA_UNAVAILABLE` flag in `risk_flags` + `critical_flags`
  - Escalation routing: `sentiment_score=-0.92` -> `sentiment_escalation`
    -> `NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH` flag
  - Timing: all 3 paths complete in <120 seconds
  - Planner abort: empty ticker -> `status='failed'`
  - Field population: every state field present with correct type
  - Multiple runs: independent results, no shared state

## Testing

```bash
# Integration tests (excluded from default run)
set ENVIRONMENT=test
python -m pytest -m integration -v --tb=short

# Unit tests must still pass
python -m pytest backend/tests/unit/ -v --tb=short -q
```

## LangSmith Trace

N/A -- no live LLM calls. LANGCHAIN_TRACING_V2=false recommended.

## Related Issues

Closes #35
```

---

## Commit Message

```
test(graph): add LangGraph end-to-end integration tests (T-035)

- test_graph_integration.py: 7 test classes, 86 tests
- TestHappyPath: full pipeline on clean mock data, all 12 nodes execute,
  all state fields populated (fundamental/technical/sentiment/macro/
  contrarian/risk/valuation/decision/final_verdict/conviction_score)
- TestErrorRoutingFundamentals: fetch_financials empty -> error_handler
  path -> FUNDAMENTAL_DATA_UNAVAILABLE in risk_flags + critical_flags;
  pipeline still completes (not aborted)
- TestErrorRoutingNegativeSentiment: sentiment_score=-0.92 < -0.8 ->
  sentiment_escalation path -> NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH
  in risk_flags + critical_flags
- TestPipelineTiming: all 3 paths complete in <120s on mock data
- TestPlannerAbortPath: empty ticker -> status='failed', no research runs
- TestStateFieldPopulation: every state field present with correct type
- TestMultipleRuns: 2 independent invocations have independent results
- All mocking via unittest.mock.patch at function level (independent tests)
- @pytest.mark.integration: excluded from default run, explicit -m required

Closes #35
```

---

## Running the tests

### Default (unit tests only -- integration excluded)
```bash
python -m pytest backend/tests/unit/ -v -q
```

### Integration tests only
```bash
python -m pytest -m integration -v --tb=short
```

### Specific test class
```bash
python -m pytest -m integration -v -k "TestHappyPath" --tb=short
python -m pytest -m integration -v -k "TestErrorRoutingFundamentals" --tb=short
python -m pytest -m integration -v -k "TestPipelineTiming" --tb=short
```

### CI behaviour
Integration tests are excluded from CI by the `addopts` in `pyproject.toml`:
```toml
addopts = "-m 'not integration' --tb=short -q"
```
CI only runs unit tests. Integration tests run locally before PRs.

---

## Key Design Decisions

### Why not mark as `@pytest.mark.unit`?

These tests call `build_graph().invoke()` which is the real LangGraph
execution engine. That's not a unit -- it's an orchestration integration
test. The `integration` marker correctly signals that:
1. It tests multiple components working together
2. It's slower than unit tests (graph compilation + execution)
3. It should be run before merging, not on every file save

### Why mock research agents?

The acceptance criterion says "on mock data" -- not real APIs. Real yFinance
/ NewsAPI / Alpha Vantage calls would make the test suite:
- Slow (network latency)
- Flaky (API rate limits, network outages)
- Non-deterministic (real data changes daily)

Mocking at the agent function level (`run_fundamental_analysis` etc.) gives
us controlled, deterministic inputs that test the ROUTING logic -- not the
data quality.

### Why mock `_run_persist` but not the node functions?

`_run_persist` opens a real asyncpg database connection. That would fail
without a running PostgreSQL. The node *functions* (planner, error_handler,
etc.) don't touch the DB directly -- they just compute and return dicts.
So we mock only the persistence layer, not the node logic itself.

### Why 120 seconds?

The acceptance criterion says "<2 minutes". With mocked agents that return
in <5ms each, the pipeline should complete in <5 seconds in practice. The
120-second budget is deliberately generous to account for:
- Cold start / JIT compilation of LangGraph internals
- Test environment overhead
- Slow CI machines

If the test actually takes more than 5 seconds on a modern machine with
mocked agents, that signals a real performance problem.