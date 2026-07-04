# T-040 -- Implement Multi-Round Debate Loop

**Phase:** 4 -- Debate Engine & Advanced Agents
**Week:** 11
**Branch:** `feat/debate-loop`
**Task status:** Complete

---

## Overview

T-040 closes the gap left by T-032 (conditional routing skeleton) and T-038
(Contrarian Investor agent): both already existed, but neither of them
actually built the **debate transcript**. T-032's `route_after_contrarian`
could already decide to loop, and T-038's Contrarian could already compute
a `bear_conviction` score -- but `state["debate_rounds"]` stayed empty
forever, because nothing ever wrote to it.

T-040 adds the missing **`debate_loop` LangGraph node**. It runs
immediately after `contrarian_node` on every round and deterministically
builds the round's transcript: what each research agent's stance is after
hearing the Contrarian's challenge, plus the Contrarian's own
strongest argument. That transcript entry is appended to
`state["debate_rounds"]`. Routing (debate again vs proceed) is still
decided by the existing `route_after_contrarian` function -- T-040 does
not change that decision logic, it only relocates the edge that calls it
so it now fires after `debate_loop` instead of directly after
`contrarian_node`.

**Acceptance criteria (all must pass):**

- 2 debate rounds complete in <3 minutes
- `debate_rounds[]` contains responses from each agent
- No infinite loops

---

## Files Changed

| File                                        | Change                                                                                                                                |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/graph/nodes.py`                    | **Modified** -- added `NODE_DEBATE_LOOP`, `debate_loop_node`, and its deterministic helper functions                                  |
| `backend/graph/routing.py`                  | **Modified** -- promoted `MAX_DEBATE_ROUNDS` to a module constant; updated `route_after_contrarian` docstring (logic unchanged)       |
| `backend/graph/graph.py`                    | **Modified** -- registered `debate_loop` node; rewired `contrarian -> debate_loop -> route_after_contrarian` (13 nodes total, was 12) |
| `backend/tests/unit/test_debate_loop.py`    | **New** -- 62 unit tests covering the new node, helpers, graph wiring, timing, and a no-infinite-loop regression suite                |
| `backend/tests/unit/test_graph_skeleton.py` | **Modified** -- node count assertion updated from 12 to 13; added `test_debate_loop_registered`                                       |

---

## What Was Built

### Modified: `backend/graph/nodes.py`

Three new pure helper functions plus the node itself, all deterministic
(zero additional LLM calls):

| Function                      | Purpose                                                                                                                                                                                                                                                                                        |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_agent_response_text(...)`   | Builds one sentence describing a single agent's stance this round: "no position" if the agent's output is missing/errored, "reaffirms" if it was not challenged by the Contrarian, "concedes" or "maintains" if it was challenged (depending on `bear_conviction` vs `_CONCEDE_THRESHOLD = 7`) |
| `_build_agent_responses(...)` | Calls `_agent_response_text` for all 5 agents (fundamental, technical, sentiment, macro, risk) and returns the combined dict                                                                                                                                                                   |
| `_debate_loop_impl(...)`      | Core node logic: reads the Contrarian's current-round output, builds `agent_responses`, appends one `{round_number, agent_responses, contrarian, completed_at}` dict to `state["debate_rounds"]`                                                                                               |
| `debate_loop_node`            | `_debate_loop_impl` wrapped with `profile_node()` (T-036 latency tracking) then `_persist_after()` (T-033 state persistence) -- identical composition pattern to every other sequential node in the graph                                                                                      |

**Why no LLM call in `debate_loop_node`?**
The Contrarian agent (T-038) already pays the LLM cost for this round when
it produces `bear_conviction`, `challenged_agents`, and
`strongest_argument`. `debate_loop_node` only transforms data that already
exists in state. This is what keeps 2 full debate rounds well under the
3-minute acceptance budget -- the only LLM round-trip per round is the one
the Contrarian already makes.

**Why Risk Officer is included in `agent_responses` even though it runs
after the debate loop?**
On round 1, `state["risk"]` is not populated yet (Risk Officer runs
sequentially after the debate loop in the existing T-032/T-038 topology),
so `_agent_response_text` correctly reports "no position (data
unavailable)" for `risk` on round 1. This is intentional graceful
degradation, not a bug -- it is exercised explicitly by
`test_missing_risk_output_round_one_is_no_position`.

### Modified: `backend/graph/routing.py`

- `MAX_DEBATE_ROUNDS: int = 2` is now a module-level constant (previously
  a local `max_rounds = 2` literal inside `route_after_contrarian`).
  `debate_loop_node` and tests import the same constant -- no duplicated
  magic numbers.
- `route_after_contrarian`'s decision logic is **byte-for-byte unchanged**
  from T-032/T-038. Only its docstring was updated to reflect that it now
  fires after `debate_loop_node` in the graph topology.

### Modified: `backend/graph/graph.py`

Topology change, fully additive:

```
Before (T-032/T-038):
  contrarian_investor --route_after_contrarian--> contrarian_investor (loop)
                                              \--> risk_officer

After (T-040):
  contrarian_investor --(always)--> debate_loop --route_after_contrarian--> contrarian_investor (loop)
                                                                       \--> risk_officer
```

`contrarian_node` now has a single unconditional edge to `debate_loop`.
`debate_loop` carries the conditional edge that used to sit on
`contrarian_node` directly. The routing function itself did not move
logically -- only its position in the graph did. Total node count: 13
(was 12 after T-032).

---

## Tests

| Test class                          | Count  | What it covers                                                                                                                                                                                                                                                                   |
| ----------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TestAgentResponseText`             | 9      | Per-agent response sentence: missing/errored agent, unchallenged reaffirm (with/without summary), challenged concede/maintain, threshold boundary (7 vs 6), always non-empty                                                                                                     |
| `TestBuildAgentResponses`           | 6      | Full 5-agent dict shape, round-1 risk-missing case, mixed challenged/unchallenged, never raises on empty state                                                                                                                                                                   |
| `TestDebateLoopImpl`                | 19     | Core node: dict shape, list growth, round numbers, agent_responses contents, contrarian text fallback chain, timestamp format, never raises on missing/malformed input, two sequential rounds grow the list correctly                                                            |
| `TestDebateLoopNode`                | 4      | Persistence-wrapped public node behaves like the impl function                                                                                                                                                                                                                   |
| `TestGraphWiring`                   | 4      | Node registered, 13 total nodes, Mermaid diagram contains `debate_loop`                                                                                                                                                                                                          |
| `TestRouteAfterContrarianUnchanged` | 7      | Regression suite -- every pre-existing T-032/T-038 routing assertion re-verified after the topology change                                                                                                                                                                       |
| `TestMultiRoundIntegration`         | 6      | Full compiled-graph runs (research agents mocked, Contrarian mocked with a controllable conviction sequence): 2-round forced termination, 1-round early termination, increasing round numbers, every round has all 5 agent responses, pipeline always reaches `status=completed` |
| `TestDebateLoopTiming`              | 2      | 2 rounds complete in well under budget; `_debate_loop_impl` alone runs 50x in under 1 second (zero LLM calls)                                                                                                                                                                    |
| `TestPublicAPI`                     | 6      | All new symbols importable and present in `__all__`                                                                                                                                                                                                                              |
| **Total**                           | **62** |                                                                                                                                                                                                                                                                                  |

Plus 1 new test added to the existing `test_graph_skeleton.py`
(`test_debate_loop_registered`) and 1 existing assertion updated
(`test_exactly_nine_content_nodes`: 12 -> 13).

---

## Design Decisions

**Why a separate node instead of folding this into `contrarian_node`?**
Single responsibility. `contrarian_node`'s T-038 test suite (its own
~30+ tests) asserts on the exact shape of its return dict
(`{"contrarian": ..., "debate_round_count": ...}`). Changing that
contract to also carry `debate_rounds` would have required touching and
re-verifying every one of those pre-existing tests. Keeping
`debate_loop_node` separate means T-038's contract -- and every test
that pins it -- is completely untouched by this task.

**Why didn't `route_after_contrarian`'s logic change?**
The acceptance criteria for T-040 ask for the transcript-building
mechanism and the round cap, not a new termination heuristic. T-032/T-038
already implemented a correct, tested termination rule
(`bear_conviction >= 7` and `rounds < MAX_DEBATE_ROUNDS`). Re-deriving
that logic inside the new node would have either duplicated it (drift
risk) or required deleting and rewriting a dozen passing tests for no
behavioural gain. T-040 is additive by design.

**Why is there no automatic "consensus reached" early-exit?**
This mirrors `docs/ARCHITECTURE.md` section 9 exactly: termination is
either `MAX_DEBATE_ROUNDS` or a conviction drop below the threshold --
never a deliberate consensus vote. The Portfolio Manager (T-042) is the
single final authority that resolves disagreement; building an automatic
consensus detector into the debate loop would pre-empt that and was
explicitly ruled out at the architecture stage.

**Why is `_CONCEDE_THRESHOLD` (7) the same value as the routing
threshold in `route_after_contrarian`?**
So the transcript language stays consistent with the actual routing
outcome the reader sees immediately afterward in the logs / DB record:
if an agent's response says it "concedes," the very next routing
decision is, by construction, also going to be `ROUTE_DEBATE_AGAIN`.

**Why no infinite loop is possible:**
`debate_round_count` is incremented unconditionally inside
`contrarian_node` (T-038, unchanged) every time it runs, and
`route_after_contrarian` hard-caps at `MAX_DEBATE_ROUNDS` regardless of
conviction. Since LangGraph re-evaluates the conditional edge from a
strictly increasing counter with a fixed ceiling, the loop is bounded by
construction -- verified explicitly by
`test_two_rounds_run_when_conviction_stays_high` and
`test_pipeline_reaches_completed_status`.

---

## AIRP Standards Compliance

| Standard                                                      | Status                                                                                                                          |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| No `from __future__ import annotations` in production modules | OK -- not present in `nodes.py` / `routing.py` / `graph.py`                                                                     |
| Plain ASCII section comments (`# ---`)                        | OK -- no Unicode box-drawing, no rupee signs, no em-dashes, no arrows                                                           |
| No bare `# type: ignore`                                      | OK -- none added; existing `[literal-required]` pattern in test helper reused as-is                                             |
| `mypy --strict` / `--warn-unused-ignores` safe                | OK -- every new function fully annotated; no ignores added at all                                                               |
| Tools/agents never raise -- graceful degradation on bad input | OK -- `_debate_loop_impl` never raises, verified on empty state, missing contrarian, and malformed `bear_conviction`            |
| `@traced_agent` / LangSmith                                   | N/A -- `debate_loop_node` makes no LLM calls, nothing to trace                                                                  |
| Persistence wrapper applied (T-033 pattern)                   | OK -- `_persist_after(profile_node(...))` composition, identical to every other sequential node                                 |
| All lines <= 88 chars                                         | OK                                                                                                                              |
| flake8 (bugbear, comprehensions) clean                        | OK -- no `getattr` with constant, no bare `pytest.raises(Exception)`, no generator-inside-`set()`                               |
| `ENVIRONMENT=test` guard respected                            | OK -- new test file uses the same `os.environ.setdefault` + autouse `_no_db_persist` fixture pattern as every other test module |

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/debate-loop
```

### 2. Place the files

Copy the following files into your local repository (paths relative to
repo root):

```
backend/graph/nodes.py                    (modified)
backend/graph/routing.py                  (modified)
backend/graph/graph.py                    (modified)
backend/tests/unit/test_debate_loop.py    (new)
backend/tests/unit/test_graph_skeleton.py (modified)
docs/week-11/T-040-debate-loop.md         (new)
```

### 3. Set environment and run the new test file

**Windows CMD:**

```cmd
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_debate_loop.py -v --tb=short
```

**Git Bash / Mac / Linux:**

```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_debate_loop.py -v --tb=short
```

Expected: **62 passed**.

### 4. Run the previously-touched file to confirm no regressions there

```bash
python -m pytest backend/tests/unit/test_graph_skeleton.py -v --tb=short
```

Expected: all passed, including the updated 13-node assertion and the new
`test_debate_loop_registered`.

### 5. Run the full unit suite to confirm no regressions anywhere

```bash
python -m pytest --tb=short -q
```

Expected: all existing tests continue to pass (T-021 through T-039 suites
untouched in behaviour; `test_routing.py`'s `route_after_contrarian`
assertions pass unmodified since that function's logic did not change).

### 6. (Optional) Run the integration suite

```bash
python -m pytest -m integration -v --tb=short
```

This calls the real Groq LLM for Risk Officer / Contrarian / Valuation
(pre-existing behaviour from T-037/T-038/T-039, unrelated to this task --
requires `GROQ_API_KEY` to be set; skip if you don't want to spend Groq
quota in this session).

### 7. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/graph/nodes.py \
        backend/graph/routing.py \
        backend/graph/graph.py \
        backend/tests/unit/test_debate_loop.py \
        backend/tests/unit/test_graph_skeleton.py \
        docs/week-11/T-040-debate-loop.md
git commit -m "feat(graph): T-040 implement multi-round debate loop node"
```

Black / isort may auto-fix formatting on the first attempt. If the commit
is rejected by pre-commit hooks (the two-commit pattern from AIRP
standards):

```bash
git add .
git commit -m "feat(graph): T-040 implement multi-round debate loop node"
```

### 8. Push and open PR

```bash
git push -u origin feat/debate-loop
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**

```
feat(graph): T-040 implement multi-round debate loop node
```

**PR description:**

```markdown
## Summary

Implements the multi-round debate loop (T-040) -- a new `debate_loop`
LangGraph node that runs after the Contrarian Investor on every debate
round and appends a structured entry to `state["debate_rounds"]`. Closes
the gap between T-032's routing skeleton and T-038's Contrarian agent,
neither of which actually populated the debate transcript.

## Changes

- `backend/graph/nodes.py` -- added `NODE_DEBATE_LOOP`, `debate_loop_node`,
  and three deterministic helper functions (`_agent_response_text`,
  `_build_agent_responses`, `_debate_loop_impl`). Zero additional LLM
  calls -- reuses the Contrarian's already-paid-for LLM output.
- `backend/graph/routing.py` -- promoted `MAX_DEBATE_ROUNDS` to a shared
  module constant. `route_after_contrarian`'s decision logic is
  unchanged.
- `backend/graph/graph.py` -- registered the new node and rewired
  `contrarian_investor -> debate_loop -> route_after_contrarian`
  (13 nodes total, was 12).
- `backend/tests/unit/test_debate_loop.py` -- new file, 62 tests.
- `backend/tests/unit/test_graph_skeleton.py` -- node count assertion
  updated 12 -> 13; one new registration test added.

## Testing

- 62 new unit tests: `pytest backend/tests/unit/test_debate_loop.py -v`
- Full suite regression: `pytest --tb=short -q`
- Explicit regression class (`TestRouteAfterContrarianUnchanged`)
  re-verifies every pre-existing T-032/T-038 routing assertion still
  holds after the topology change
- Timing test confirms 2 mocked debate rounds run in well under the
  3-minute acceptance budget
- All external calls (LLM, APIs, DB) mocked -- no network required

## LangSmith Trace

Not applicable -- `debate_loop_node` makes no LLM calls, so there is
nothing new to trace. The Contrarian's existing `@traced_agent` trace
already covers the LLM cost for the round.

## Related Issues

Closes #40
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

Next task: **T-041** -- (if not already covered by the existing T-039
Valuation Agent implementation, confirm scope with the project plan
before starting) or proceed to **T-042** -- Portfolio Manager agent,
which will read the full `debate_rounds[]` transcript built in this task
and produce the final `InvestmentDecision` with verdict and conviction
score.

Branch: `feat/portfolio-manager` (or equivalent per the project plan).

The Portfolio Manager is the final authority that resolves the bull/bear
disagreement recorded across every `debate_rounds[]` entry -- this is the
last piece of Phase 4 before the FastAPI backend (Phase 5) can be built
on top of a complete agent pipeline.

---

_End of Document | T-040 Workflow | AIRP Week 11_
