# T-032 -- Implement Conditional Routing Logic

**Phase:** 3 -- LangGraph Orchestration
**Week:** 8
**Branch:** `feat/graph-routing`
**Task status:** Ready to implement

---

## Overview

T-032 adds production-grade conditional routing to the AIRP LangGraph
StateGraph. Two new routing behaviours are introduced:

1. **Financials error path** -- if `fetch_financials` returns empty data
   (API rate limit, unknown ticker, network failure), `route_after_research`
   detects `fundamental["error"]` is non-null and routes to a dedicated
   `error_handler_node`. The error handler marks the pipeline as degraded
   (NOT failed -- the pipeline continues), writes flags to `risk_flags` and
   `critical_flags`, and forwards to the contrarian node so the committee
   can still produce a cautious memo.

2. **Negative sentiment escalation** -- if `sentiment["sentiment_score"] < -0.8`
   the news environment is severely negative. `route_after_research` routes
   to a `sentiment_escalation_node` which appends
   `NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH` to both `risk_flags`
   and `critical_flags`, then forwards to contrarian.

**Acceptance criteria (all must pass):**

- Error path routes correctly for mocked failures
  (`fundamental["error"]` non-null -> `error_handler` node -> continues)
- Escalation triggers on negative sentiment threshold
  (`sentiment_score < -0.8` -> `sentiment_escalation` node -> continues)
- All existing tests (test_graph_skeleton, test_parallel_research) still pass
- `build_graph()` compiles cleanly with 11 nodes (9 original + 2 new)
- Mermaid diagram contains both new node names

**Files produced / modified:**

| File                                           | Action | Description                                                                                                                                                             |
| ---------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/graph/routing.py`                     | Modify | Add `ROUTE_ERROR`, `ROUTE_ESCALATE_SENTIMENT`, `NEGATIVE_SENTIMENT_THRESHOLD`, `ESCALATION_FLAG_NEGATIVE_SENTIMENT`, and update `route_after_research` with T-032 logic |
| `backend/graph/nodes.py`                       | Modify | Add `NODE_ERROR_HANDLER`, `NODE_SENTIMENT_ESCALATION`, `error_handler_node`, `sentiment_escalation_node`                                                                |
| `backend/graph/graph.py`                       | Modify | Register 2 new nodes, wire conditional edges from research join, wire forward edges from routing nodes to contrarian                                                    |
| `backend/tests/unit/test_routing.py`           | Create | 100+ unit tests for T-032 routing logic, node functions, and end-to-end paths                                                                                           |
| `backend/tests/unit/test_graph_skeleton.py`    | Modify | Update node count assertions from 9 to 11; add new node names to `_ALL_NODE_NAMES`                                                                                      |
| `backend/tests/unit/test_parallel_research.py` | Modify | Update node count assertions from 9 to 11; add new node names to `_ALL_NODE_NAMES`                                                                                      |
| `docs/week-08/T-032-conditional-routing.md`    | Create | This file                                                                                                                                                               |

---

## Routing Logic

### Error Path (fetch_financials empty)

```
research join
  -> route_after_research()
     checks: fundamental["error"] is not None
  -> ROUTE_ERROR
  -> error_handler_node
       writes: pipeline_error (human-readable warning)
               risk_flags += ["FUNDAMENTAL_DATA_UNAVAILABLE"]
               critical_flags += ["FUNDAMENTAL_DATA_UNAVAILABLE"]
               current_node = "error_handler"
  -> edge -> contrarian_investor  (pipeline continues)
```

**Design rationale:** The Fundamental Analyst is the primary quantitative
anchor. Running valuation on top of missing fundamental data produces
unreliable output. The error_handler does NOT terminate -- it marks the
gap and lets the committee produce a memo flagged "data incomplete".

### Escalation Path (negative sentiment)

```
research join
  -> route_after_research()
     checks: sentiment["sentiment_score"] < -0.8
  -> ROUTE_ESCALATE_SENTIMENT
  -> sentiment_escalation_node
       writes: risk_flags += [ESCALATION_FLAG_NEGATIVE_SENTIMENT]
               critical_flags += [ESCALATION_FLAG_NEGATIVE_SENTIMENT]
               current_node = "sentiment_escalation"
  -> edge -> contrarian_investor  (pipeline continues with flag in state)
```

**Design rationale:** Score -0.8 is two standard deviations below the
typical range for Indian blue-chips. At this level the news environment
suggests active management misconduct, fraud allegations, or regulatory
action. The escalation flag causes downstream agents to apply maximum
caution without forking the pipeline.

### Priority: Error before Escalation

If both conditions are true (fundamental error AND sentiment < -0.8),
the error path takes priority. `route_after_research` checks fundamentals
first, sentiment second.

---

## New Constants

```python
# routing.py
ROUTE_ERROR = "error"                    # -> error_handler node
ROUTE_ESCALATE_SENTIMENT = "escalate_sentiment"   # -> sentiment_escalation node
NEGATIVE_SENTIMENT_THRESHOLD = -0.8     # strict less-than comparison
ESCALATION_FLAG_NEGATIVE_SENTIMENT = "NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH"

# nodes.py
NODE_ERROR_HANDLER = "error_handler"
NODE_SENTIMENT_ESCALATION = "sentiment_escalation"

# graph.py
ROUTING_NODE_NAMES = ("error_handler", "sentiment_escalation")
```

---

## Graph Topology Change (T-032)

Before T-032 the research nodes had direct edges to contrarian:

```
[fundamental] -+
[technical]   -+-> [contrarian_investor]
[sentiment]   -+
[macro]       -+
```

After T-032 the research nodes have conditional edges with 3 branches:

```
[fundamental] -+
[technical]   -+-> route_after_research() -> ROUTE_ERROR       -> [error_handler]         -> [contrarian]
[sentiment]   -+                          -> ROUTE_ESCALATE    -> [sentiment_escalation]   -> [contrarian]
[macro]       -+                          -> ROUTE_PROCEED     ->                          -> [contrarian]
```

---

## Step-by-Step Workflow

### 0. Prerequisites

Ensure you are on `main` with a clean working tree:

```bash
git checkout main
git pull origin main
git status   # must show nothing to commit
```

Set the test environment (Windows CMD):

```cmd
set ENVIRONMENT=test
```

Or Git Bash / macOS / Linux:

```bash
export ENVIRONMENT=test
```

### 1. Create the feature branch

```bash
git checkout -b feat/graph-routing
```

### 2. Apply the file changes

Copy the four files produced by this task into the repo:

```
backend/graph/routing.py        (replace existing)
backend/graph/nodes.py          (replace existing)
backend/graph/graph.py          (replace existing)
backend/tests/unit/test_routing.py            (new file)
backend/tests/unit/test_graph_skeleton.py     (replace existing)
backend/tests/unit/test_parallel_research.py  (replace existing)
docs/week-08/T-032-conditional-routing.md     (new file -- this file)
```

### 3. Clear stale pycache

```bash
find backend/graph backend/tests -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
find backend/graph backend/tests -name "*.pyc" -delete 2>/dev/null; true
```

### 4. Run the full unit test suite

```bash
python -m pytest backend/tests/unit/ -v --tb=short -q
```

Expected: all tests pass, no failures. Key tests to watch:

- `test_routing.py` -- all 100+ T-032 routing tests
- `test_graph_skeleton.py::TestNodeRegistration::test_exactly_nine_content_nodes`
  (now asserts 11 nodes)
- `test_parallel_research.py::TestGraphStructure::test_nine_content_nodes_registered`
  (now asserts 11 nodes)
- End-to-end path tests:
  - `TestGraphEndToEndErrorPath::test_error_path_pipeline_completes`
  - `TestGraphEndToEndEscalationPath::test_escalation_path_pipeline_completes`
  - `TestGraphEndToEndNormalPath::test_normal_path_completes`

### 5. Run pre-commit hooks (first attempt -- formatters may auto-fix)

```bash
git add .
git commit -m "feat(graph): implement conditional routing logic T-032"
```

If pre-commit auto-fixes formatting (black / isort / prettier):

```bash
git add .
git commit -m "feat(graph): implement conditional routing logic T-032"
```

### 6. Verify CI passes locally (optional but recommended)

```bash
python -m pytest backend/tests/unit/ -q --tb=short
```

All tests must pass with 0 failures before pushing.

### 7. Push and open PR

```bash
git push -u origin feat/graph-routing
```

Then open a PR on GitHub from `feat/graph-routing` -> `main`.

---

## PR Details

**PR Title:**

```
feat(graph): implement conditional routing logic (T-032)
```

**PR Description:**

````markdown
## Summary

Implements T-032 conditional routing logic in the AIRP LangGraph StateGraph.
Adds two new routing paths after the research phase: an error handler for
failed fundamental data fetches, and a sentiment escalation node for severely
negative news environments (score < -0.8).

## Changes

- `routing.py`: Added `ROUTE_ERROR`, `ROUTE_ESCALATE_SENTIMENT`,
  `NEGATIVE_SENTIMENT_THRESHOLD` (-0.8), `ESCALATION_FLAG_NEGATIVE_SENTIMENT`,
  and rewrote `route_after_research` with T-032 branching logic.

- `nodes.py`: Added `NODE_ERROR_HANDLER`, `NODE_SENTIMENT_ESCALATION`,
  `error_handler_node` (writes FUNDAMENTAL_DATA_UNAVAILABLE flag, pipeline
  continues), `sentiment_escalation_node` (writes NEGATIVE_SENTIMENT flag).

- `graph.py`: Registered 2 new routing nodes (11 total). Changed research
  node outbound edges from direct -> contrarian to conditional edges routing
  through error_handler or sentiment_escalation as needed. Added forward
  edges from both routing nodes back to contrarian.

- `test_routing.py`: 100+ unit tests covering error path, escalation path,
  normal path, boundary values (threshold at exactly -0.8 vs -0.801),
  priority (error beats escalation), robustness (never raises on corrupt
  state), end-to-end graph invocation for all three paths.

- `test_graph_skeleton.py`, `test_parallel_research.py`: Updated node count
  assertions from 9 to 11 and added new node names to `_ALL_NODE_NAMES`.

## Testing

```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/ -v --tb=short
```
````

All 100+ new tests pass. All existing T-030 and T-031 tests still pass.
graph compilation succeeds with 11 content nodes. Mermaid diagram updated.

## LangSmith Trace

N/A -- no live LLM calls; all agents mocked in tests.

## Screenshots

Run `build_graph().get_graph().draw_mermaid()` after applying changes to
see the updated topology with `error_handler` and `sentiment_escalation`
nodes wired between the research join and the contrarian node.

## Related Issues

Closes #32

```

---

## Commit Message

```

feat(graph): implement conditional routing logic (T-032)

- route_after_research routes to error_handler when fundamental["error"]
  is non-null (fetch_financials empty path)
- route_after_research routes to sentiment_escalation when
  sentiment_score < -0.8 (negative sentiment escalation path)
- error_handler_node marks pipeline degraded, writes
  FUNDAMENTAL_DATA_UNAVAILABLE to risk_flags and critical_flags,
  does NOT terminate pipeline -- forwards to contrarian
- sentiment_escalation_node writes NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH
  flag, forwards to contrarian
- graph.py: 11 nodes (9 + 2 T-032 routing nodes), conditional edges
  from all 4 research nodes through route_after_research, forward edges
  from both routing nodes to contrarian
- 100+ unit tests in test_routing.py covering all three routing paths,
  boundary values, priority, and end-to-end graph invocation

Closes #32

```

---

## Key Design Decisions

### Why separate nodes for error and escalation?

LangGraph routing functions are pure -- they read state and return a
route key, but cannot write to state.  Separate nodes are needed to
actually write the flags to `risk_flags` and `critical_flags`.  This
also makes the LangSmith trace fully explicit: you can see exactly when
and why the flag was written, and what state looked like at that moment.

### Why does error_handler NOT set status=failed?

Setting `status="failed"` would terminate the pipeline (route_after_planner
and the graph's terminal condition check for this value).  The Fundamental
Analyst returning empty data is serious but not fatal -- the committee can
still produce a memo marked "quantitative data unavailable, proceed with
caution".  The `FUNDAMENTAL_DATA_UNAVAILABLE` flag in `critical_flags`
is the Portfolio Manager's signal to reduce conviction score and mandate
explicit data-gap disclosure in the memo.

### Why -0.8 as the threshold?

Indian blue-chip stocks typically have sentiment scores in the [-0.3, 0.5]
range during normal operation.  A score below -0.8 is two standard
deviations outside this range and reliably indicates active crisis-level
coverage: management fraud, regulatory raids, or catastrophic operational
failures.  This matches the project plan acceptance criterion literally:
`sentiment.score < -0.8`.

### Boundary: exactly -0.8 is NOT an escalation

The condition is strict less-than (`< -0.8`), not less-than-or-equal.
A score of exactly -0.8 takes the normal proceed path.  This matches
standard financial threshold conventions where the boundary value itself
is not considered "breaching" the threshold.

---

## Files Summary

| File | Lines Changed | Key Additions |
|------|--------------|---------------|
| `backend/graph/routing.py` | +80 | `ROUTE_ERROR`, `ROUTE_ESCALATE_SENTIMENT`, `NEGATIVE_SENTIMENT_THRESHOLD`, `ESCALATION_FLAG_NEGATIVE_SENTIMENT`, `route_after_research` rewrite |
| `backend/graph/nodes.py` | +90 | `NODE_ERROR_HANDLER`, `NODE_SENTIMENT_ESCALATION`, `error_handler_node`, `sentiment_escalation_node` |
| `backend/graph/graph.py` | +35 | 2 new node registrations, conditional edges from research join, forward edges to contrarian |
| `backend/tests/unit/test_routing.py` | +500 | 21 test classes, 100+ test cases |
| `backend/tests/unit/test_graph_skeleton.py` | +10 | Node count 9->11, new node names in `_ALL_NODE_NAMES` |
| `backend/tests/unit/test_parallel_research.py` | +10 | Node count 9->11, new node names in `_ALL_NODE_NAMES` |
| `docs/week-08/T-032-conditional-routing.md` | New | This document |
```
