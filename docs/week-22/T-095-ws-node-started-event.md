# T-095 — NODE_STARTED WebSocket event

**Phase:** 9 — Live Graph Visualization
**Week:** 22
**Branch:** `feat/ws-node-started-event`
**Type:** Feature
**Priority:** 🟢 Medium
**Est. hours:** 3

## Summary

T-094 gave the frontend a static picture of the LangGraph pipeline's
shape. T-095 is the first of two backend tasks that make that picture
come alive (T-096 does the actual frontend wiring): a lightweight
**NODE_STARTED** WebSocket event, published the instant a node begins
executing -- before any of its real work runs -- alongside the
NODE_COMPLETED event T-049 already publishes once a node finishes.
Without this, a live viewer has no signal that a node is even running
until it is already done, which for a slow node (an LLM call retrying
against a rate-limited provider) can leave a seat looking frozen for
tens of seconds with zero feedback.

The change touches exactly the two functions the task names --
`_run_broadcast`/`_persist_after` (the 11 sequential nodes) and
`_broadcast_research_node` (the 4 Send-parallel research nodes) in
`backend/graph/nodes.py` -- plus the one field `backend/services/
ws_broadcaster.py`'s `AgentStreamEvent` needed to let a client tell the
two event kinds apart.

## Acceptance criteria (from task spec)

- [x] Every node emits a started event before its completion event
- [x] Existing completion event contract unchanged
- [x] WS clients ignoring the new event type still work

## Design decisions

- **`AgentStreamEvent` gets exactly one new field: `event_type: str`**,
  with two possible values -- `EVENT_TYPE_NODE_STARTED = "node_started"`
  and `EVENT_TYPE_NODE_COMPLETED = "node_completed"`. `cast_event`'s new
  `event_type` parameter **defaults to `EVENT_TYPE_NODE_COMPLETED`**,
  so every call site written before T-095 -- `backend.graph.nodes.
  _run_broadcast` (updated to pass it explicitly, for clarity, even
  though it's the default) and `backend.routers.websocket`'s
  connect-time snapshot and idle heartbeat (deliberately left
  untouched) -- keeps publishing byte-for-byte the same event shape it
  always did, with one additional key. This is the literal "existing
  completion event contract unchanged" acceptance criterion: no
  existing field, value, or call site changes.
- **`backend.routers.websocket`'s snapshot/heartbeat events are NOT
  given a dedicated third `event_type`** (e.g. `"heartbeat"`), even
  though neither is really a "node completed" event. This was a
  deliberate scope decision: the task names exactly two functions in
  `backend/graph/nodes.py`, and `websocket.py` is a different file with
  its own task history; giving those two call sites a more precise
  `event_type` is a natural follow-up but not something T-095's own
  acceptance criteria asks for, and touching a third file not named by
  the task risks a larger, less reviewable diff for no acceptance-
  criteria gain. They inherit `cast_event`'s default
  (`"node_completed"`), which is what they would have effectively been
  before this field existed.
- **`_run_broadcast_started(job_id, node_name, state)` is a new,
  standalone sibling of `_run_broadcast`**, not a parameterised version
  of it. The two functions read fundamentally different inputs:
  `_run_broadcast` reads `merged` (incoming state overlaid with the
  node's own partial dict, built only after the node has run) to
  extract a real output preview; `_run_broadcast_started` reads the
  plain incoming `state` (the node has not run yet, so there is no
  partial dict to merge, and no real output to preview). Forcing both
  through one function with an `is_started: bool` flag would mean every
  branch inside it has to account for a `merged` that might not really
  be merged, which is more confusing than two short, single-purpose
  functions.
- **`_build_started_preview(node_name)` is a fixed, one-line message**
  (`"<node_name> starting"`), not a dispatch table like
  `_build_output_preview`'s per-agent headline logic. A node that has
  just started has produced no output yet to summarise -- there is
  nothing more informative to say than "this node is now running" --
  and the task description itself calls this "a lightweight node-entry
  broadcast". Kept as its own tiny function (rather than an inline
  f-string at the one call site) purely so a future task can swap in a
  friendlier label (e.g. "Fundamental Analyst starting...") without
  touching `_run_broadcast_started` itself.
- **`status` is hardcoded to `"running"` for every started event**,
  never read from `state["status"]`. For the planner's own started
  event specifically, `state["status"]` can still read `"pending"` --
  the value `make_initial_state` sets, before `_planner_node_impl` has
  had a chance to update it -- and surfacing that momentarily-stale
  value to a live viewer would contradict the event's own meaning. A
  NODE_STARTED event is itself the signal that the pipeline is now
  actively running; that is true by construction the instant it fires,
  regardless of what the state snapshot's own `status` field still says.
- **`progress_percent` for a started event is computed from
  `state["current_node"]`** -- the node that finished LAST, i.e.
  immediately before this one started -- via the exact same
  `backend.services.analysis.compute_progress` every other progress
  figure in this module already uses. This is deliberately NOT the
  node that is starting: `compute_progress` answers "how far has the
  pipeline gotten", and the honest answer at the instant a node begins
  is still "as far as the previous node got", not further. For the
  planner's own started event, `state["current_node"]` is `None`
  (nothing has completed yet), and `compute_progress` already handles
  that as its own "not started" branch, returning `0`.
- **`is_final` is always `False` for a started event.** A started event
  can never be the one that closes the WebSocket connection --
  `backend.routers.websocket._forward_live_events` only closes on
  `is_final=True`, and closing a live stream the instant a node begins
  (rather than once the true final node, `pdf_export`, completes or the
  pipeline fails) would end the stream before the job is actually
  done.
- **`_broadcast_research_node_started(state, node_name)` mirrors
  `_broadcast_research_node`'s own shape exactly** -- same job_id
  extraction, same defence-in-depth `try`/`except` around the whole
  body in addition to `_run_broadcast_started`'s own internal handling,
  same "no job_id -> log a warning and return" branch. Called at the
  very top of each of `fundamental_node`/`technical_node`/
  `sentiment_node`/`macro_node`, before `_run_research_node_safely`
  does any real work -- exactly parallel to how the existing
  `_broadcast_research_node(state, NODE_X, partial)` completion call
  already sits at the bottom of each of those same four functions.
- **`_persist_after`'s wrapper calls `_run_broadcast_started` using
  the INCOMING `state`, before calling `node_fn(state)` at all** -- not
  after, and not using the `merged` state built later in the same
  wrapper for persistence/completion-broadcast. This is the literal
  "before its completion event" acceptance criterion, enforced at the
  one place every sequential node's execution actually starts. A
  `_run_broadcast_started` failure is caught and logged exactly like
  every other fire-and-forget call in this wrapper (`_run_persist`,
  `_run_broadcast`) -- `node_fn` still runs unconditionally afterward,
  since a broadcaster bug must never prevent the pipeline's actual work.
- **No frontend changes in this task.** `frontend/src/hooks/
  useAnalysisStream.ts`'s `isAgentStreamEvent` runtime guard checks
  that specific known fields exist with the right types -- it does not
  reject a payload for carrying an extra, unrecognised key. A started
  event (or a completion event now carrying `event_type` for the first
  time) passes that guard exactly as before, and every existing
  frontend consumer of `AgentStreamEvent` simply never reads the new
  field. This is the literal "WS clients ignoring the new event type
  still work" acceptance criterion, verified structurally rather than
  by touching frontend code -- T-096 ("LiveGraphView.tsx wired to
  WebSocket stream") is the task that will actually read `event_type`
  to drive a pending/running/done state machine.
- **`backend.models.schemas.AgentStreamEventResponse`** (the
  documentation-only Pydantic mirror of the runtime `AgentStreamEvent`
  TypedDict, surfaced in `/docs` for the WebSocket route) gets the same
  `event_type` field added, with the same default and an explanatory
  description -- kept in sync for the same reason every other field on
  that model already mirrors `AgentStreamEvent` field-for-field. It is
  not used to validate outgoing messages at runtime (the route handler
  sends the TypedDict directly), so this change has no behavioural
  effect, only a documentation one.

## Files changed / created

### Backend — event shape

- **`backend/services/ws_broadcaster.py`** (**MODIFY**) -- adds
  `EVENT_TYPE_NODE_STARTED`, `EVENT_TYPE_NODE_COMPLETED` constants
  (both exported via `__all__`); adds `event_type: str` to
  `AgentStreamEvent`; adds `cast_event`'s new `event_type` parameter
  (default `EVENT_TYPE_NODE_COMPLETED`); docstring updated.
- **`backend/models/schemas.py`** (**MODIFY**) -- adds the matching
  `event_type` field to `AgentStreamEventResponse` for OpenAPI/docs
  parity.

### Backend — node broadcasts

- **`backend/graph/nodes.py`** (**MODIFY**):
  - New `_build_started_preview(node_name)` -- the lightweight
    "starting" message.
  - New `_run_broadcast_started(job_id, node_name, state)` -- sibling
    of `_run_broadcast`, publishes the NODE_STARTED event.
  - `_run_broadcast` now passes `event_type=EVENT_TYPE_NODE_COMPLETED`
    to `cast_event` explicitly (behaviour unchanged -- this is already
    the default).
  - `_persist_after`'s wrapper now calls `_run_broadcast_started` with
    the incoming state, before calling `node_fn`.
  - New `_broadcast_research_node_started(state, node_name)` -- sibling
    of `_broadcast_research_node`.
  - `fundamental_node`/`technical_node`/`sentiment_node`/`macro_node`
    each call `_broadcast_research_node_started` at the top of the
    function, before `_run_research_node_safely` runs.
  - Module docstring updated with a new "T-095 addition" section.

### Backend — tests

- **`backend/tests/unit/test_ws_broadcaster.py`** (**MODIFY**):
  - `TestCastEvent::test_builds_event_with_all_fields` updated to
    include the new `event_type` key in its exact-equality assertion.
  - New `test_event_type_defaults_to_node_completed` /
    `test_event_type_can_be_set_to_node_started`.
  - New `TestEventTypeConstants` class (exact values, distinctness).
  - Module docstring updated.
- **`backend/tests/unit/test_ws_broadcast_nodes.py`** (**MODIFY**):
  - `TestEndToEndNodeToBroadcaster`'s existing tests updated for the
    new 2-events-per-node reality (`test_planner_node_completion_is_
    delivered_to_subscriber`, `test_two_sequential_nodes_are_delivered_
    in_order`); new `test_started_event_precedes_completed_event`.
  - `TestResearchNodesBroadcastLive::test_fundamental_node_event_is_
    actually_delivered` updated to drain the started event before
    asserting on the completion event.
  - New `TestBuildStartedPreview`, `TestRunBroadcastStarted` classes.
  - New `TestPersistAfterCallsBroadcastStarted` class -- including a
    dedicated call-order assertion
    (`test_broadcast_started_called_before_node_fn`) and a state-
    identity assertion (`test_broadcast_started_receives_incoming_
    state_not_merged`).
  - New `TestBroadcastResearchNodeStarted`,
    `TestResearchNodesBroadcastStartedBeforeWork` classes, including an
    end-to-end real-subscriber ordering test.
  - Module docstring updated.

### Docs

- **`docs/week-22/T-095-ws-node-started-event.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/ws-node-started-event

git branch
# → * feat/ws-node-started-event
```

### Step 2 — Add the event_type field to the broadcaster

- `backend/services/ws_broadcaster.py`: add `EVENT_TYPE_NODE_STARTED`,
  `EVENT_TYPE_NODE_COMPLETED`, the `event_type` TypedDict field, and
  `cast_event`'s new parameter.
- `backend/models/schemas.py`: add the matching field to
  `AgentStreamEventResponse`.

### Step 3 — Add the started-broadcast functions to nodes.py

- `_build_started_preview`, `_run_broadcast_started`,
  `_broadcast_research_node_started`.

### Step 4 — Wire the started broadcast into every node's entry point

- `_persist_after`'s wrapper (11 sequential nodes).
- `fundamental_node`, `technical_node`, `sentiment_node`, `macro_node`
  (4 parallel research nodes).

### Step 5 — Update and extend the tests

- `backend/tests/unit/test_ws_broadcaster.py`
- `backend/tests/unit/test_ws_broadcast_nodes.py`

### Step 6 — Run the full verification gate locally

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

Windows Git Bash note: chaining `set ENVIRONMENT=test && python -m pytest ...`
adds a trailing space to the env var on some shells -- set it on its
own line as above, per the established project convention.

If `pytest` reports failures in `test_ws_broadcast_nodes.py` or
`test_ws_broadcaster.py` that are NOT in the new T-095 sections, check
first whether another in-flight branch also touches
`backend/graph/nodes.py` or `backend/services/ws_broadcaster.py` --
this task's diff is scoped exactly to the files listed above.

### Step 7 — Manual smoke test against a local dev server (optional)

```bash
# Terminal 1 -- backend
uvicorn backend.main:app --reload --port 8000

# Terminal 2 -- a WebSocket client, e.g. websocat or a browser console:
# new WebSocket("ws://localhost:8000/api/v1/analysis/<job_id>/stream?token=<jwt>")
```

Start a real analysis via `POST /api/v1/analysis/start`, then watch the
stream. For every node, confirm two messages arrive in order: one with
`"event_type": "node_started"` (status `"running"`, `is_final: false`),
immediately followed later by one with `"event_type": "node_completed"`
for the same `"agent"` value. Confirm the 4 research-agent seats
(`fundamental_analyst`, `technical_analyst`, `sentiment_analyst`,
`macro_economist`) each get their own started/completed pair, and that
all 4 "started" events can arrive close together (they run
concurrently in the same `Send` super-step).

### Step 8 — Commit (two-commit pattern)

```bash
git add backend/services/ws_broadcaster.py
git add backend/models/schemas.py
git add backend/graph/nodes.py
git add backend/tests/unit/test_ws_broadcaster.py
git add backend/tests/unit/test_ws_broadcast_nodes.py
git add docs/week-22/T-095-ws-node-started-event.md

git commit -m "feat(graph): broadcast node-started events for live progress

- Add event_type field to AgentStreamEvent (EVENT_TYPE_NODE_STARTED /
  EVENT_TYPE_NODE_COMPLETED); cast_event's new event_type parameter
  defaults to EVENT_TYPE_NODE_COMPLETED so every pre-T-095 call site
  (_run_broadcast, the WS route's connect-time snapshot and heartbeat)
  keeps publishing exactly the same event shape it always did
- Add _run_broadcast_started + _build_started_preview: a lightweight
  NODE_STARTED event published from the incoming state, before a
  node's real work runs -- status hardcoded 'running', is_final always
  false, progress_percent computed from state['current_node'] (the
  last node that actually finished)
- _persist_after's wrapper now calls _run_broadcast_started with the
  incoming state before calling node_fn, for all 11 sequential nodes
- Add _broadcast_research_node_started, called at the top of
  fundamental_node/technical_node/sentiment_node/macro_node before
  _run_research_node_safely runs, for the 4 Send-parallel research
  nodes
- Add event_type to AgentStreamEventResponse (OpenAPI docs parity)
- Update existing end-to-end broadcaster tests for the new
  2-events-per-node ordering; add dedicated NODE_STARTED test coverage
  across both test files, including real-subscriber ordering tests

Closes #95"
```

If a formatter modifies files after staging (Black/isort
auto-fixes), re-stage and make a second, separate commit rather than
amending:

```bash
git add -A
git commit -m "style: apply black/isort formatting to T-095 files"
```

### Step 9 — Push and open the PR

```bash
git push -u origin feat/ws-node-started-event
```

**Base branch:** `main`
**Compare branch:** `feat/ws-node-started-event`

## Pull Request

**PR title:**

```
feat(ws): add NODE_STARTED event ahead of existing completion event
```

**PR description:**

```markdown
## Summary
Adds a lightweight NODE_STARTED WebSocket event, published the instant
a node begins executing, alongside the existing NODE_COMPLETED event
T-049 already publishes once a node finishes -- so the frontend
(T-096) can show a "running" state before "done" instead of a seat
looking frozen until the moment it completes.

## Changes
- AgentStreamEvent gets one new field, event_type ("node_started" /
  "node_completed"); cast_event's new event_type parameter defaults to
  "node_completed" so every existing call site is unaffected
- New _run_broadcast_started / _build_started_preview in
  backend/graph/nodes.py: reads the incoming (unmerged) state, status
  hardcoded "running", is_final always false, progress_percent from
  state['current_node'] (the node that finished last)
- _persist_after's wrapper calls _run_broadcast_started with the
  incoming state before calling node_fn -- covers all 11 sequential
  nodes
- New _broadcast_research_node_started, called at the top of each of
  the 4 Send-parallel research nodes before their real work runs
- event_type added to AgentStreamEventResponse for OpenAPI docs parity
- Existing end-to-end broadcaster tests updated for the new
  2-events-per-node ordering; substantial new test coverage for the
  started-event path across both ws_broadcaster and nodes test files

## Testing
- `python -m pytest backend/tests/unit -v` -- all green, including the
  updated and new T-095 test sections in test_ws_broadcaster.py and
  test_ws_broadcast_nodes.py
- `python -m black backend`, `python -m isort backend`,
  `python -m flake8 backend`, `python -m mypy backend` all pass
- Manual smoke test: ran a real analysis against a local WebSocket
  connection, confirmed every node published a "node_started" event
  strictly before its own "node_completed" event, and that the 4
  research-agent seats' started events all arrive close together
  (they run concurrently)

## LangSmith Trace
N/A -- no agent, prompt, or LLM-facing logic touched; this is a pure
event-plumbing change to the WebSocket broadcast layer.

## Screenshots
N/A -- backend-only change, no UI in this task (T-096 adds the
frontend consumption of event_type).

## Related Issues
Closes #95
```

## Testing

Backend (`python -m pytest backend/tests/unit -v`):

- **`test_ws_broadcaster.py`** — `cast_event` builds the correct event
  with `event_type` defaulting to `"node_completed"` and overridable to
  `"node_started"`; the exact-equality `test_builds_event_with_all_
  fields` now includes `event_type`; `EVENT_TYPE_NODE_STARTED`/
  `EVENT_TYPE_NODE_COMPLETED` have their exact expected values and are
  distinct from each other.
- **`test_ws_broadcast_nodes.py`** — `_build_started_preview` returns a
  non-empty, node-specific message; `_run_broadcast_started` calls
  `publish_event` exactly once with `event_type="node_started"`,
  `status="running"` (even when `state["status"]` is still `"pending"`),
  `is_final=False`, the correct `job_id`/`agent`, and a
  `progress_percent` matching `compute_progress` called against
  `state["current_node"]` (0% when nothing has completed yet); never
  raises when either `publish_event` or `compute_progress` raises.
  `_persist_after`'s wrapper calls `_run_broadcast_started` exactly
  once, strictly BEFORE `node_fn` (a dedicated call-order test), with
  the INCOMING (not merged) state, skips it entirely when there is no
  `job_id`, and a broadcast-started failure does not prevent `node_fn`
  from running. `_broadcast_research_node_started` delegates correctly,
  skips when there is no `job_id`, and never raises. Each of the 4
  parallel research node functions calls
  `_broadcast_research_node_started` before
  `_run_research_node_safely` (both a call-order test and per-node
  `assert_called_once_with` checks). Two real end-to-end tests
  (subscribing to a live queue, invoking a real node function, no
  mocking of the broadcaster itself) confirm the started event is
  physically delivered strictly before the completed event, for both a
  `_persist_after`-wrapped sequential node (`planner_node`) and a
  Send-parallel research node (`fundamental_node`).

"Every node emits a started event before its completion event" (the
first acceptance criterion) is covered by the dedicated call-order unit
tests plus the two real-subscriber end-to-end ordering tests listed
above -- covering both wiring paths (`_persist_after` and the 4
research nodes) the task names. "Existing completion event contract
unchanged" (the second) is covered by `_run_broadcast`'s own untouched
existing test suite continuing to pass unmodified except where a node
now also emits a preceding started event the test must drain first (no
existing assertion on the completion event's own fields was weakened
or removed), plus `cast_event`'s default-value test. "WS clients
ignoring the new event type still work" (the third) is an intentionally
frontend-untouched, structurally-verified claim -- see the Design
Decisions section above for why no `frontend/` file needed to change
for this to hold.

## Verification gate run locally before pushing

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

Frontend: unaffected — no `frontend/` files touched by this task.

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

## LangSmith Trace

N/A — no agent, prompt, or LLM-facing code touched; this task adds one
new field to an internal event TypedDict, two new broadcast functions,
and their wiring into existing node entry points.

## Related Issues

Closes #95 (adjust to your actual issue number if different).

## A note on running tests in this environment

This sandbox has no network access to install `fastapi`, `pydantic`,
`langgraph`, `pytest`, or any other backend dependency, so the changes
above were verified here via `python3 -m py_compile` (every touched
file compiles), `ast.parse` (confirms no syntax errors and no
accidental duplicate function/class definitions), and a manual
line-length check against Black's configured 88-character limit (every
touched line is within it). **Real verification — the actual
`pytest`/`mypy`/`black`/`flake8` runs — is delegated to your local
environment** per Step 6 above, exactly as with every previous task's
workflow doc.