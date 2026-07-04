# T-049 -- Implement WebSocket for Live Streaming

**Phase:** 5 -- FastAPI Backend
**Week:** 14
**Branch:** `feat/api-websocket`
**Task status:** Complete

---

## Overview

T-049 adds the real-time push counterpart to T-048's poll-only status
endpoint: a WebSocket that streams one event per LangGraph node
completion, live, as the pipeline runs. A client can now watch an
analysis progress from `pending` to `completed` (or `failed`) without
ever issuing a second HTTP request.

**Acceptance criteria (all must pass):**

- WebSocket sends event per agent completion
- frontend receives and displays in order
- connection closes cleanly

**Explicitly out of scope for this task** (separate Phase 5 tasks, per
the master task list):

- `GET /analysis/{job_id}/result`, `GET /analysis/{job_id}/memo/pdf`,
  `GET /history` -> **T-050**
- Document upload endpoint -> later T-05x
- Any change to how LangGraph nodes compute their own output -- T-049
  only _reads_ the same state `_persist_after` (T-033) already builds
  and persists; no agent or routing logic changed

---

## What Was Built

### `backend/services/ws_broadcaster.py` (new)

An in-process publish/subscribe registry -- the piece that turns a
LangGraph node finishing (already a fire-and-forget event via T-033's
`_persist_after`) into a live push to a connected browser.

- **`AgentStreamEvent`** -- a `TypedDict` matching the acceptance
  criterion's literal shape (`{agent, status, output_preview}`) plus
  `job_id`, `progress_percent`, and `is_final` -- the extra fields a
  real client needs to route and terminate the stream correctly
  without a second `GET /status` call.
- **`cast_event(...)`** -- an explicitly-typed constructor so the two
  call sites that build outgoing events (`backend.graph.nodes` and
  `backend.routers.websocket`) cannot typo a key under `mypy --strict`.
- **`subscribe(job_id)` / `unsubscribe(job_id, queue)`** -- registry
  bookkeeping. Each subscriber is an `asyncio.Queue` paired with the
  event loop that created it (a `_Subscriber` dataclass), because...
- **`publish_event(job_id, event)`** -- fans an event out to every
  subscriber of `job_id` via `loop.call_soon_threadsafe(queue.put_nowait,
event)`. This is **not** `asyncio.Lock` + `asyncio.run()` (the first
  draft of this module): `publish_event` is called from a LangGraph
  node running on a worker thread, while `subscribe`/`unsubscribe` run
  on FastAPI's main event loop thread -- `asyncio.Lock`/`asyncio.Queue`
  are documented as not thread-safe and bound to whichever loop first
  awaits them, so a plain `threading.Lock` guards the registry dict and
  `call_soon_threadsafe` (asyncio's own cross-thread scheduling
  primitive) delivers to each subscriber's own loop.
- **`TERMINAL_STATUSES`** -- `frozenset({"completed", "failed"})`,
  shared by the broadcast-side `is_final` computation and the route's
  initial-snapshot logic so both agree on when a job is "done."

No Redis, no message broker -- AIRP's production target (Render free
tier) is a single process, and the LangGraph pipeline already runs
inside that same process via `BackgroundTasks` + `asyncio.to_thread`
(T-047), so a plain in-memory registry is correct and adds zero
network round-trips or Upstash command-budget cost.

### `backend/graph/nodes.py` (modified -- additive only)

`_persist_after` (T-033) now does a **second** fire-and-forget thing
after every sequential node completes, alongside the existing
`_run_persist` call:

- **`_run_broadcast(job_id, node_name, merged)`** -- builds an
  `AgentStreamEvent` from the same merged state `_run_persist` just
  wrote to PostgreSQL, and calls `ws_broadcaster.publish_event`.
  `progress_percent` is computed via
  `backend.services.analysis.compute_progress` -- the **exact same**
  function T-048's `GET /status` uses, so the live stream and the poll
  endpoint can never disagree about how far along a job is.
  `is_final` is `True` exactly when `node_name == NODE_PDF_EXPORT`
  (the true terminal node before `END` -- see `backend.graph.graph`'s
  `add_edge(NODE_PDF_EXPORT, END)`) or `status == "failed"`. Never
  raises -- lazily imports `backend.services.analysis` and
  `backend.services.ws_broadcaster`, mirroring `_run_persist`'s
  identical "never abort the pipeline" contract.
- **`_build_output_preview(node_name, merged)`** -- a short,
  human-readable summary of what each node produced, reading the same
  agent-output dicts already sitting in state (no new computation, no
  extra LLM call). Surfaces an agent's `error` field instead of a
  zero/default headline value when one failed. Bespoke branches for
  `report_generator` (memo drafted), `pdf_export` (PDF path),
  `research_join` (fixed message), and `planner` (resolved company
  name); a generic `"<node_name> completed"` fallback for anything
  else.
- **`_summarise_agent_output(node_name, output)`** -- a small per-node
  dispatch table picking the single most decision-relevant field per
  agent (risk score + flag count, bear conviction, valuation verdict,
  final verdict + conviction) rather than a generic field dump.

Existing T-033 tests that patch only `backend.graph.nodes._run_persist`
to a no-op (the established pattern across 6+ test files) are
unaffected: `_run_broadcast` touches no DB and no network, and a
`job_id` with zero subscribers -- true for every existing test, none of
which ever calls `ws_broadcaster.subscribe` -- is a guaranteed no-op
there regardless.

### `backend/routers/websocket.py` (new)

```
WS /api/v1/analysis/{job_id}/stream
```

On connect:

1. Authenticates via a `token` query parameter (browsers cannot set
   custom WebSocket handshake headers, so the existing
   `OAuth2PasswordBearer`-based `get_current_user` dependency is
   unreachable here; this route calls
   `backend.services.auth.decode_access_token` directly).
2. Confirms `job_id` exists and belongs to the caller via the exact
   same `backend.services.analysis.get_analysis_status` T-048 already
   uses. Closes with application-specific code `4401` (bad/missing
   token) or `4404` (not found / not yours) on failure -- never `403`,
   for the same enumeration-prevention reason T-048's `404` already
   chose.
3. Sends one event immediately reflecting the job's **current**
   status -- covers the race where the pipeline finishes before the
   client's socket finishes connecting. If that snapshot is already
   terminal, closes right away (code `1000`).
4. Otherwise subscribes to `ws_broadcaster` and forwards every
   subsequent event, in publish order, until the one marked
   `is_final=True`, then closes cleanly (code `1000`).

The database session is **not** injected via `Depends(get_async_session)`
for the connection's full lifetime -- that would hold a pooled Neon
connection open for the entire ~90 second streaming duration even
though the DB is only touched once, up front. Instead it's a narrow,
manually-scoped `async with AsyncSessionLocal()` block around just the
auth + snapshot phase. `settings` _is_ injected via the normal
`Depends(get_settings_dependency)`, since it's an immutable in-memory
value with no pooled resource behind it.

A best-effort disconnect probe (`asyncio.wait_for(websocket.receive(),
timeout=0.01)`, the documented Starlette/FastAPI community workaround
for the platform's lack of a native "is this socket still connected"
check) runs whenever the broadcaster queue goes quiet for more than 2
seconds, so a dead connection's subscriber is cleaned up promptly
instead of lingering for the full pipeline runtime.

### `backend/models/schemas.py` (modified -- additive only)

Added **`AgentStreamEventResponse`**, mirroring
`ws_broadcaster.AgentStreamEvent` field-for-field -- documents the
WebSocket message contract in the same `/docs` surface every other
AIRP response schema does, even though the route itself sends the
TypedDict directly via `send_json` for minimal per-event overhead.

### `backend/main.py` / `backend/routers/__init__.py` (modified)

Registered the new `websocket.router` alongside `health`, `auth`, and
`analysis`; docstrings updated to record T-049 as complete.

### Frontend (new -- ahead of Phase 6)

Phase 6 (T-053+) has not started, so there is no dashboard yet to wire
this into. To give the second acceptance criterion ("frontend receives
and displays in order") a genuine, runnable consumer today:

- **`frontend/src/hooks/useAnalysisStream.ts`** -- a self-contained
  React hook that opens the WebSocket, runtime-validates each message
  against the `AgentStreamEvent` shape, and appends (never replaces)
  to an `events` array -- preserving arrival order for any consumer.
  Cleans up the socket on unmount or whenever `jobId`/`token`/`enabled`
  change, guarded against a stale prior-effect's socket delivering a
  late message after a new one has started.
- **`frontend/src/components/AgentProgressDemo.tsx`** -- a minimal
  demo viewer rendering `events` as an ordered list. Not the real
  Phase 6 dashboard (no design system, no routing, no React Query) --
  intended to be deleted or replaced outright once T-053+ lands;
  `useAnalysisStream` is the reusable part worth keeping.

### Tests (new)

- **`backend/tests/unit/test_ws_broadcaster.py`** -- the broadcaster
  module in isolation: `cast_event`, subscribe/unsubscribe registry
  bookkeeping, delivery (single + multiple subscribers, publish order,
  no-subscriber no-op, cross-job isolation), and error tolerance (a
  subscriber whose loop raises on `call_soon_threadsafe` never blocks
  delivery to others or escapes `publish_event`).
- **`backend/tests/unit/test_ws_broadcast_nodes.py`** -- the
  `backend.graph.nodes` additions: every `_build_output_preview`
  branch, `_summarise_agent_output`'s per-node dispatch and fallback,
  `_run_broadcast`'s event shape and `is_final` logic (including
  "never raises even when `publish_event`/`compute_progress` raise"),
  `_persist_after` now calling both `_run_persist` and `_run_broadcast`
  independently (one failing doesn't block the other), and an
  end-to-end test subscribing to the real broadcaster and invoking a
  real sequential node function to confirm delivery and ordering.
- **`backend/tests/unit/test_websocket_router.py`** -- the route
  itself via `starlette.testclient.TestClient` (the documented way to
  test WebSocket routes; `httpx.AsyncClient` + `ASGITransport` has no
  WebSocket support). Covers both acceptance criteria directly:
  auth failures close with `4401`, unknown/foreign jobs close with
  `4404`, the initial snapshot event arrives immediately and is
  `is_final` when the job is already terminal, and -- the core of the
  task -- events published after connect are forwarded **in publish
  order**, the connection closes with code `1000` after the final
  event, and events for a _different_ job_id never leak into the
  wrong subscriber's stream.

---

## Files Changed

| File                                                  | Change                                                                                                                     |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `backend/services/ws_broadcaster.py`                  | **New** -- in-process pub/sub registry                                                                                     |
| `backend/graph/nodes.py`                              | **Modified** -- `_run_broadcast`, `_build_output_preview`, `_summarise_agent_output`; `_persist_after` now also broadcasts |
| `backend/routers/websocket.py`                        | **New** -- `WS /{job_id}/stream`                                                                                           |
| `backend/models/schemas.py`                           | **Modified** -- added `AgentStreamEventResponse`                                                                           |
| `backend/main.py`                                     | **Modified** -- registers the new router                                                                                   |
| `backend/routers/__init__.py`                         | **Modified** -- docstring only                                                                                             |
| `frontend/src/hooks/useAnalysisStream.ts`             | **New** -- WebSocket-consuming React hook                                                                                  |
| `frontend/src/components/AgentProgressDemo.tsx`       | **New** -- minimal demo viewer                                                                                             |
| `backend/tests/unit/test_ws_broadcaster.py`           | **New**                                                                                                                    |
| `backend/tests/unit/test_ws_broadcast_nodes.py`       | **New**                                                                                                                    |
| `backend/tests/unit/test_websocket_router.py`         | **New**                                                                                                                    |
| `docs/week-14/T-049-implement-websocket-streaming.md` | **New** -- this document                                                                                                   |

No other files were modified. `backend/services/state_persistence.py`
(T-033) and `backend/services/analysis.py` (T-047/T-048) are reused
as-is -- T-049 calls `compute_progress` and shares `_persist_after`'s
merged-state computation, but neither was changed.

---

## Design Decisions & Rationale

**Why an in-process registry instead of Redis pub/sub?** AIRP's
free-tier deployment target (Render) runs one process, and the
LangGraph pipeline already executes inside that same process via
`BackgroundTasks` + `asyncio.to_thread`. Reaching for Upstash Redis
pub/sub would add a network round-trip and consume part of the
10,000-commands/day free-tier budget to solve a multi-process fan-out
problem AIRP does not currently have. If the LangGraph workers ever
move to a separate process, only `ws_broadcaster.py`'s `subscribe`/
`publish_event` internals would need to change -- every caller depends
on those two functions, never on the registry's storage.

**Why `threading.Lock` instead of `asyncio.Lock` for the registry?**
`publish_event` runs on whichever worker thread LangGraph happens to
be executing a node on; `subscribe`/`unsubscribe` run on FastAPI's main
event loop thread. `asyncio.Lock` and `asyncio.Queue` are documented as
not thread-safe and bind to the loop that first awaits them -- calling
either from a second thread (or via a fresh `asyncio.run()` each time,
which spins up a brand-new loop) risks a `RuntimeError` or silent
misbehaviour the moment more than one node has run. A plain
`threading.Lock` has no such restriction and is the correct primitive
for a dict mutated from multiple OS threads.

**Why pair each subscriber with its own event loop instead of a
shared one?** `loop.call_soon_threadsafe(queue.put_nowait, event)` is
asyncio's own documented mechanism for scheduling a callback onto a
_specific_ loop from any other thread -- captured once, at subscribe
time, via `asyncio.get_running_loop()` (which always runs on the route
handler's loop). This avoids ever touching an `asyncio.Queue` directly
from the wrong thread.

**Why query-param auth instead of reusing `get_current_user`?**
Browsers cannot set custom headers on a WebSocket handshake --
`get_current_user`'s `OAuth2PasswordBearer` dependency reads an
`Authorization` header, which is simply unreachable from
`new WebSocket(url)` in a browser. A `token` query parameter is the
standard, documented workaround; `settings` is still injected the
normal way via `Depends(get_settings_dependency)` since per-route
`Depends()` parameters work identically on WebSocket and HTTP routes
in FastAPI (only _global_ `dependencies=[...]` on the app/router
constructor fail to propagate to WebSocket routes, which this router
does not use).

**Why scope the DB session manually instead of `Depends(get_async_session)`?**
A FastAPI dependency resolved on a WebSocket route is held open for the
connection's entire lifetime, not re-resolved per message. The session
here is only needed once, up front, for auth and the initial status
read -- holding a pooled Neon connection for the full ~90-second
streaming duration to cover a few milliseconds of actual DB work would
needlessly compete with every other concurrent analysis for the
free-tier connection cap.

**Why `is_final` on `pdf_export`, not on `status == "completed"` alone?**
`status` flips to `"completed"` as early as `portfolio_manager_node`
(T-041's existing design -- the investment decision itself is final
before the memo/PDF finish rendering), but `report_generator` and
`pdf_export` still run afterward. Closing the WebSocket the moment
`status` says `"completed"` would cut the stream off before those two
nodes' own completion events ever arrive. `pdf_export` is the actual
last node before `END` in the graph topology, so it -- not the status
string -- is the correct close signal; `status == "failed"` is ORed in
separately since a failure can occur at any node and has no later
"final" node of its own to wait for.

**Why a custom close code (4404) instead of denying the handshake
outright?** Starlette supports rejecting a WebSocket connection before
`accept()`, but the browser-side `WebSocket` API surfaces almost no
detail about _why_ a handshake was denied. Accepting first and closing
with an application-specific code in the 4000-4999 range (reserved by
the WebSocket spec for exactly this) lets a future frontend distinguish
"bad token" from "not found" from a normal, successful completion.

---

## How T-049 Was Implemented (full workflow)

### 1. Sync with `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/api-websocket
```

### 2. Confirm the starting point (T-048 already merged)

```bash
git log --oneline -5
cat backend/routers/__init__.py     # should already mention T-049/T-050 as "planned"
grep -n "_persist_after" backend/graph/nodes.py
grep -n "compute_progress" backend/services/analysis.py
```

The last two commands confirm the exact two extension points T-049
hooks into: T-033's persistence wrapper, and T-048's progress
computation -- both reused, neither modified in their existing behavior.

### 3. Build the broadcaster module first, in isolation

Create `backend/services/ws_broadcaster.py`: `AgentStreamEvent`,
`cast_event`, `TERMINAL_STATUSES`, the `_Subscriber` dataclass, the
module-level `_subscribers` dict + `threading.Lock`, and
`subscribe`/`unsubscribe`/`publish_event`. No FastAPI, no LangGraph
imports -- this module must be independently testable.

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_ws_broadcaster.py -v
```

Write `test_ws_broadcaster.py` alongside it before moving on -- the
registry's thread-safety contract is exactly the kind of logic that
should be nailed down with direct tests before anything else depends
on it.

### 4. Wire the broadcaster into `backend/graph/nodes.py`

Edit `backend/graph/nodes.py`:

- Add `_NODE_OUTPUT_STATE_FIELD`, `_OUTPUT_PREVIEW_MAX_CHARS`,
  `_truncate_preview`, `_build_output_preview`,
  `_summarise_agent_output`, and `_run_broadcast` immediately after
  the existing `_run_persist` function.
- Edit `_persist_after`'s `wrapper` closure to add a second
  `try`/`except` block calling `_run_broadcast`, immediately after the
  existing `_run_persist` call -- same fire-and-forget, non-fatal
  contract, logged separately.
- Update the module docstring's "T-033 additions" section and "Design
  decisions" list to mention the new broadcast call.

No changes to any node's `_impl` function, to `NODE_*` constants, or
to graph topology (`backend/graph/graph.py` is untouched).

### 5. Confirm no regression in existing persistence tests

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_state_persistence.py -v
ENVIRONMENT=test pytest backend/tests/unit/test_graph_skeleton.py -v
ENVIRONMENT=test pytest backend/tests/unit/test_parallel_research.py -v
```

These patch only `_run_persist`; `_run_broadcast` runs for real (it's
pure in-memory) and must not break anything.

### 6. Write the node-level broadcast tests

Create `backend/tests/unit/test_ws_broadcast_nodes.py` covering
`_build_output_preview`, `_summarise_agent_output`, `_run_broadcast`,
the `_persist_after` integration, and the end-to-end
subscribe-then-invoke-a-real-node test.

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_ws_broadcast_nodes.py -v
```

### 7. Add the schema and the router

Edit `backend/models/schemas.py`: add `AgentStreamEventResponse` after
`AnalysisStatusResponse`, add it to `__all__`.

Create `backend/routers/websocket.py`: `_authenticate`,
`_snapshot_to_event`, `stream_analysis_progress`,
`_forward_live_events`, `_client_still_connected`.

Edit `backend/main.py`: import and register `websocket.router`. Edit
`backend/routers/__init__.py`: docstring update.

### 8. Write the router tests

Create `backend/tests/unit/test_websocket_router.py` using
`fastapi.testclient.TestClient` (not `httpx.AsyncClient` --
WebSocket testing needs Starlette's dedicated test transport). Cover
both acceptance criteria directly: ordered forwarding and clean
closure, plus the auth/not-found failure paths.

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_websocket_router.py -v
```

### 9. Add the frontend consumer

Create `frontend/src/hooks/useAnalysisStream.ts` and
`frontend/src/components/AgentProgressDemo.tsx`. Not wired into
`App.tsx` (Phase 6 owns routing/layout); these exist standalone so the
"frontend receives and displays in order" criterion has a real,
runnable consumer ahead of the full dashboard.

### 10. Run the full existing suite to confirm no regressions

```bash
ENVIRONMENT=test pytest --tb=short -q
```

### 11. Run lint and type checks exactly as CI does

```bash
black backend/
isort backend/
flake8 backend/
mypy backend/
```

Auto-fix and re-stage if needed (standard AIRP two-commit pattern):

```bash
black backend/
isort backend/
```

### 12. Confirm coverage

```bash
ENVIRONMENT=test pytest --cov=backend --cov-report=term-missing -m "not integration" -q
```

### 13. Manual smoke test (optional, requires a running Postgres)

```bash
uvicorn backend.main:app --reload --port 8000
```

In one terminal, trigger an analysis (T-047) and grab its `job_id` and
your bearer token (T-046). In a Python shell or any WebSocket client:

```python
import asyncio
import websockets

async def main() -> None:
    url = f"ws://localhost:8000/api/v1/analysis/{JOB_ID}/stream?token={TOKEN}"
    async with websockets.connect(url) as ws:
        async for message in ws:
            print(message)

asyncio.run(main())
```

Expect one JSON line per node completion, in execution order, ending
with an `is_final: true` event and a clean server-side close.

### 14. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/services/ws_broadcaster.py \
        backend/graph/nodes.py \
        backend/routers/websocket.py \
        backend/models/schemas.py \
        backend/main.py \
        backend/routers/__init__.py \
        frontend/src/hooks/useAnalysisStream.ts \
        frontend/src/components/AgentProgressDemo.tsx \
        backend/tests/unit/test_ws_broadcaster.py \
        backend/tests/unit/test_ws_broadcast_nodes.py \
        backend/tests/unit/test_websocket_router.py \
        docs/week-14/T-049-implement-websocket-streaming.md
git commit -m "feat(api): add WebSocket live agent streaming"
```

If black/isort auto-fix anything (standard AIRP two-commit pattern):

```bash
git add .
git commit -m "feat(api): add WebSocket live agent streaming"
```

On Windows, if a pre-commit hook shim is blocked by Application
Control:

```bash
git commit --no-verify -m "feat(api): add WebSocket live agent streaming"
```

### 15. Push and open PR

```bash
git push -u origin feat/api-websocket
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**

```
feat(api): implement WebSocket endpoint for real-time agent progress streaming
```

**PR description:**

```markdown
## Summary

Adds WS /api/v1/analysis/{job_id}/stream: a live, push-based companion
to T-048's poll-only GET /status. As each LangGraph node completes,
the server pushes {agent, status, output_preview, progress_percent,
is_final} over the socket, in execution order, and closes cleanly once
the pipeline reaches its true terminal node (pdf_export) or fails.

## Changes

- backend/services/ws_broadcaster.py (new) -- in-process pub/sub
  registry. AgentStreamEvent TypedDict + cast_event constructor;
  subscribe/unsubscribe/publish_event; threading.Lock-guarded registry
  (not asyncio.Lock -- publish_event runs on a LangGraph worker thread,
  subscribe/unsubscribe run on the main event loop thread); delivery
  via loop.call_soon_threadsafe per-subscriber, asyncio's documented
  cross-thread scheduling primitive
- backend/graph/nodes.py -- _persist_after now also calls the new
  _run_broadcast (fire-and-forget, non-fatal, mirrors _run_persist's
  contract exactly) after every sequential node. _build_output_preview
  and _summarise_agent_output build a short per-node summary from
  state already in memory -- no new agent calls. progress_percent
  reuses backend.services.analysis.compute_progress verbatim, so the
  live stream and GET /status can never disagree
- backend/routers/websocket.py (new) -- the WS route. Query-param
  token auth (browsers can't set WS handshake headers); ownership
  check via the same get_analysis_status T-048 uses; sends the job's
  current snapshot immediately on connect (covers fast pipelines that
  finish before the client connects); closes with 4401/4404 on auth/
  not-found failures, 1000 on clean completion; DB session is scoped
  manually to the auth+snapshot phase only, not held open via Depends
  for the full streaming duration
- backend/models/schemas.py -- added AgentStreamEventResponse
  (documents the WS message contract in /docs; the route itself sends
  the TypedDict directly for minimal per-event overhead)
- backend/main.py, backend/routers/**init**.py -- register the new
  router
- frontend/src/hooks/useAnalysisStream.ts (new) -- WebSocket-consuming
  React hook with runtime payload validation, ahead of the Phase 6
  dashboard
- frontend/src/components/AgentProgressDemo.tsx (new) -- minimal demo
  viewer proving events render in arrival order
- backend/tests/unit/test_ws_broadcaster.py,
  test_ws_broadcast_nodes.py, test_websocket_router.py (new) --
  broadcaster unit tests, nodes.py integration tests, and full route
  tests via starlette.testclient.TestClient covering both acceptance
  criteria directly (ordered forwarding, clean closure, auth/
  not-found failure codes, cross-job isolation)

## Testing

- `ENVIRONMENT=test pytest backend/tests/unit/test_ws_broadcaster.py backend/tests/unit/test_ws_broadcast_nodes.py backend/tests/unit/test_websocket_router.py -v`
  -- new suites; directly exercise both T-049 acceptance criteria
- `ENVIRONMENT=test pytest backend/tests/unit/test_state_persistence.py backend/tests/unit/test_graph_skeleton.py backend/tests/unit/test_parallel_research.py -v`
  -- confirms the new _run_broadcast call inside _persist_after does
  not break any existing T-033 test that only patches _run_persist
- `ENVIRONMENT=test pytest --tb=short -q` -- full existing suite, no
  regressions
- Manual smoke test: connected a real WebSocket client to a running
  analysis job, confirmed events arrived in order ending in
  is_final=true and a clean server close; confirmed a bad token and an
  unknown job_id close with 4401/4404 respectively
- black --check, isort --check-only, flake8, mypy all run locally
  against new and modified files before pushing

## LangSmith Trace

Not applicable -- this PR adds a read-only streaming endpoint and does
not modify any agent or LangGraph node business logic. LangSmith
tracing remains disabled project-wide until T-067 (Phase 7 evaluation
framework).

## Related Issues

Closes #49
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

With T-049 complete, a client can follow an analysis job two ways:
poll `GET /status` (T-048) or open `WS /stream` (T-049) for live
push -- both backed by the exact same `compute_progress` calculation,
so they can never disagree.

Next task: **T-050 -- Build result and PDF endpoints**
(`GET /analysis/{job_id}/result`, `GET /analysis/{job_id}/memo/pdf`,
`GET /history`). Branch: `feat/api-results`.

---

_End of Document | T-049 Workflow | AIRP Week 14_
