# T-096 — LiveGraphView.tsx wired to WebSocket stream

**Phase:** 9 — Live Graph Visualization
**Week:** 22
**Branch:** `feat/ui-live-graph-view`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 5

## Summary

T-094 built the static pipeline topology. T-095 gave the backend a real
NODE_STARTED event ahead of every completion event. T-096 is where those
two land together on screen: `LiveGraphView`, a component that consumes
`useAnalysisStream`'s raw `AgentStreamEvent[]` and renders the same
15-node topology with every node's real pending/running/done/failed
status, updating live as events arrive — no polling, no timers, just a
re-render driven by new events.

## Acceptance criteria (from task spec)

- [x] Nodes visibly pulse on start and flip to done on completion in
      real time during a live analysis run
- [x] Parallel nodes animate simultaneously

## Design decisions

- **`event_type` is now optional on `AgentStreamEvent`
  (`frontend/src/hooks/useAnalysisStream.ts`)**, not required. The real
  backend always sends it as of T-095, but making it required in the
  TypeScript type — and, more importantly, in `isAgentStreamEvent`'s
  runtime guard — would silently reject every hand-built event fixture
  written before T-096 across the existing test suite (`EVENT_1`/
  `EVENT_2` in `useAnalysisStream.test.ts`, none of which include it).
  Optional keeps every one of those tests passing unmodified and is
  itself the frontend half of "WS clients ignoring the new event type
  still work" — this hook is exactly such a client until this task.
  `EVENT_TYPE_NODE_STARTED`/`EVENT_TYPE_NODE_COMPLETED` are exported
  from the same file (mirroring `backend.services.ws_broadcaster`'s own
  two constants) so nothing downstream hardcodes the literal strings.
- **`deriveNodeStatuses` (`src/lib/graph/liveGraphState.ts`) needs no
  special-case code for "4 parallel nodes animate simultaneously".**
  Each node's status is derived independently from its own most recent
  event. Since the backend's real `Send` fan-out
  (`backend/graph/graph.py`) dispatches all 4 research nodes in the
  same LangGraph super-step, their real NODE_STARTED events arrive
  close together and each node flips to `"running"` the instant its own
  event lands — "simultaneous" falls out of correct per-node logic, not
  a coordinated timer. `liveGraphState.test.ts`'s dedicated test for
  this asserts exactly that: 4 independent `"node_started"` events in,
  4 independent `"running"` statuses out.
- **A missing/undefined `event_type` is treated as a completed event**,
  the same default `backend.services.ws_broadcaster.cast_event` itself
  applies. This matters concretely: without this fallback, an old-shaped
  event (or a test fixture that predates T-095) landing as a node's
  *most recent* event would leave that node stuck showing `"running"`
  forever, since there would be no way to tell it apart from a real
  started event. Falling through to `"done"` instead is the safe
  default — a node can go from `"pending"` straight to `"done"` if all
  we ever see is one old-shaped event, but it can never get stuck
  mid-pulse.
- **`__start__`/`__end__` (the two LangGraph sentinel nodes T-094 already
  renders) have no real backend event of their own**, so they need
  their own small rule rather than the per-node lookup every real node
  uses: `__start__` reads `"done"` the instant ANY event at all has
  arrived (that can only happen after LangGraph has traversed
  `START -> planner`); `__end__` reads `"done"` once the stream's
  `isComplete` flag is true, or `"failed"` instead if the stream's very
  last event's own `status` was `"failed"` — so a failed run's END node
  never shows a falsely-successful green checkmark.
- **A node this particular run never touched (`error_handler`,
  `sentiment_escalation` — the two T-032 conditional branches not taken
  this time) stays `"pending"` forever, even after `isComplete` is
  true.** This is deliberately different from
  `src/lib/agentProgress.ts`'s own `deriveAgentCards`, which flips an
  agent that never got a turn to a `"skipped"` state once the stream
  completes — that makes sense there because all 8 committee agents are
  EXPECTED to run in a normal pipeline, so "never ran, but the pipeline
  finished" is itself an anomaly worth flagging. For the two conditional
  routing branches, "never ran" is the normal, common outcome — most
  analyses take the `ROUTE_PROCEED` path, not `ROUTE_ERROR`/
  `ROUTE_ESCALATE_SENTIMENT` — so leaving them visually neutral
  (`"pending"`, i.e. never highlighted at all) is the CORRECT semantic,
  not a gap. No `"skipped"` status exists in this module at all.
- **`LiveGraphNode` (`src/components/graph/LiveGraphNode.tsx`) is a new
  sibling of T-094's `PipelineGraphNode`, not a modification of it.**
  `PipelineGraphNode`'s own module docstring is explicit that it stays
  permanently static — every node always renders in one
  undifferentiated visual state — specifically so T-096 would have a
  clean, known-correct topology to build on rather than a component
  that had grown ad hoc live-state branches. Both share their base
  colour-by-kind styling and 4 named Handles via the new
  `src/lib/graph/pipelineNodeStyles.ts` (extracted out of
  `PipelineGraphNode.tsx` — a mechanical, behaviour-preserving change;
  `PipelineGraphNode.test.tsx` needed no updates) so a future palette
  tweak never needs to be applied in two places and risk drifting apart.
- **The "pulse" is Tailwind's built-in `animate-pulse` utility on a
  ring/glow around the node**, plus a small bouncing-3-dots badge (the
  same visual language `src/components/progress/TypingIndicator.tsx`
  already established for a card's "thinking" state, reimplemented
  inline here at badge scale rather than imported, since
  `TypingIndicator` is sized for a card's inline text row, not a
  20×20px graph-node corner badge). No new `tailwind.config.ts`
  keyframe was needed for either. Every animated class is paired with
  `motion-reduce:animate-none`, respecting `prefers-reduced-motion`
  rather than pulsing regardless of the user's OS-level setting.
- **`done`/`failed` get a small corner badge (a checkmark / an
  exclamation mark) in addition to a static (non-pulsing) coloured
  ring**, so the difference between "running" and "done" is legible
  even to a reader who can't rely on the pulse animation itself (a
  screenshot, a reduced-motion session, or simply a glance that missed
  the transition) — the badge and the ring colour alone are enough.
- **`LiveGraphViewProps` is shaped identically to
  `AgentProgressBoardProps`** (`events`, `isComplete`, `connectionStatus`,
  `error`, plus this component's own `className`/`height` for its
  ReactFlow container) rather than a bespoke shape. Both components are
  two different renderings of the exact same `useAnalysisStream()`
  output, and T-097 ("view toggle") needs to swap between them with no
  adapter layer and no risk of losing stream state mid-toggle. Like
  `AgentProgressBoard`, `LiveGraphView` does not call `useAnalysisStream`
  itself — it is a pure, props-driven component, trivially testable with
  hand-built event fixtures (see `LiveGraphView.test.tsx`), with the one
  real subscription staying at the page level for T-097 to wire up.
  `progressPercent` is the one `AgentProgressBoardProps` field
  deliberately NOT included here — the graph itself already visualises
  progress node-by-node; a second, separate overall progress bar duplicating
  that information inside the graph view would be redundant with what
  `AgentProgressBoard`'s own bar already shows when toggled to.
- **`PIPELINE_EDGES` is untouched and unanimated in this task.**
  T-096's acceptance criteria is entirely about NODES; animating the
  `debate_loop -> contrarian_investor` cycle edge specifically while the
  debate loop is actually active is explicitly scoped to T-097
  ("Debate loop animation + view toggle") per the project plan. Keeping
  edges static here is a deliberate scope boundary, not an oversight.
- **No page-level wiring in this task.** `LiveGraphView` is demoed on the
  existing `/dev/components` preview route (an interactive, hand-scripted
  event-stream stepper — step to "Step 3" to see all 4 research nodes
  pulse together) rather than mounted on `AnalysisResultPage.tsx`. The
  task title itself is "LiveGraphView.tsx wired to WebSocket stream" —
  wired to the *stream's shape*, via props, not wired into a specific
  page — and T-097's own acceptance criteria is explicitly the page-level
  card/graph toggle. Mounting it prematurely on the real analysis page
  now would mean T-097 either throws away that wiring or fights an
  existing toggle-less integration instead of adding the toggle cleanly.

## Files changed / created

### Frontend — wire format

- **`frontend/src/hooks/useAnalysisStream.ts`** (**MODIFY**) — adds
  optional `event_type?: string` to `AgentStreamEvent`; exports
  `EVENT_TYPE_NODE_STARTED`/`EVENT_TYPE_NODE_COMPLETED`; the runtime
  guard accepts a missing OR string `event_type`.

### Frontend — shared node styling (extraction, no behaviour change)

- **`frontend/src/lib/graph/pipelineNodeStyles.ts`** (**CREATE**) —
  `PIPELINE_KIND_STYLES`/`PIPELINE_HANDLE_CLASS_NAME`, extracted out of
  `PipelineGraphNode.tsx`.
- **`frontend/src/components/graph/PipelineGraphNode.tsx`** (**MODIFY**)
  — imports the extracted styles instead of defining them locally;
  rendered output is unchanged.

### Frontend — live status derivation

- **`frontend/src/lib/graph/liveGraphState.ts`** (**CREATE**) —
  `PipelineNodeStatus`, `LiveGraphNodeData`, `deriveNodeStatuses`.

### Frontend — live graph components

- **`frontend/src/components/graph/LiveGraphNode.tsx`** (**CREATE**) —
  the live-status ReactFlow node renderer.
- **`frontend/src/components/graph/LiveGraphView.tsx`** (**CREATE**) —
  the task's actual deliverable.
- **`frontend/src/components/graph/index.ts`** (**MODIFY**) — barrel
  export for `LiveGraphNode`/`LiveGraphView`.

### Frontend — dev preview

- **`frontend/src/pages/ComponentsPreviewPage.tsx`** (**MODIFY**) — adds
  an interactive "Live pipeline graph (T-096)" section: a hand-scripted
  event-batch stepper so both acceptance criteria are visually
  checkable at `/dev/components` without a live backend connection.

### Frontend — tests

- **`frontend/src/test/liveGraphState.test.ts`** (**CREATE**) — pure
  derivation tests: pending/running/done/failed transitions, the
  debate-loop repeat-node case (most-recent-event-wins), the
  missing-`event_type` fallback, the 4-simultaneous-parallel-nodes case,
  a mixed 3-done/1-running case, the "never touched, stays pending"
  case, and START/END sentinel logic.
- **`frontend/src/test/LiveGraphNode.test.tsx`** (**CREATE**) — label/
  subtitle rendering; `data-node-status` marker per status; the
  running/done/failed badges appear only for their own status.
- **`frontend/src/test/LiveGraphView.test.tsx`** (**CREATE**) —
  container render; every node's label present; all-pending initial
  state; a node flips to running/done across a `rerender`; all 4
  parallel research nodes show `running` together; `className`/`height`
  props; connection status and error banner rendering.
- **`frontend/src/test/useAnalysisStream.test.ts`** (**MODIFY**) — new
  `event_type (T-096)` section: an event with no `event_type` field is
  still accepted (the existing `EVENT_1`/`EVENT_2` fixtures are
  deliberately left in their original, pre-T-095 shape to prove this);
  `event_type` passes through untouched when present; a non-string
  `event_type` is rejected by the runtime guard.

### Docs

- **`docs/week-22/T-096-ui-live-graph-view.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/ui-live-graph-view

git branch
# → * feat/ui-live-graph-view
```

### Step 2 — Extend the wire-format hook

- `frontend/src/hooks/useAnalysisStream.ts`: add `event_type`
  (optional), the two exported constants, and the guard update.

### Step 3 — Extract the shared node styling

- `frontend/src/lib/graph/pipelineNodeStyles.ts`: new file.
- `frontend/src/components/graph/PipelineGraphNode.tsx`: import from it
  instead of defining locally.

### Step 4 — Add the live status derivation module

- `frontend/src/lib/graph/liveGraphState.ts`: new file.

### Step 5 — Add the live graph components

- `frontend/src/components/graph/LiveGraphNode.tsx`
- `frontend/src/components/graph/LiveGraphView.tsx`
- `frontend/src/components/graph/index.ts`: barrel update.

### Step 6 — Wire the interactive demo into the dev preview page

- `frontend/src/pages/ComponentsPreviewPage.tsx`: add the "Live
  pipeline graph (T-096)" section.

### Step 7 — Add/extend the tests

Create the three new test files and extend
`useAnalysisStream.test.ts` as listed above.

### Step 8 — Run the full verification gate locally

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

If `format:check` reports files needing formatting, run
`npm run format` and re-stage before committing, per the established
two-commit pattern.

### Step 9 — Manual smoke test against a local dev server

```bash
cd frontend
npm run dev
```

Visit `http://localhost:3000/dev/components` and confirm, in the "Live
pipeline graph (T-096)" section:

- At Step 0, every node is dimmed ("pending") with no ring or badge.
- Click "Step forward" once: Planner gets a pulsing ring + bouncing-dots
  badge ("running").
- Step forward again: Planner's ring turns solid green with a checkmark
  badge ("done").
- Step forward to Step 3: all 4 research nodes (Fundamental Analyst,
  Technical Analyst, News Sentiment, Macro Economist) show the pulsing
  ring simultaneously — the literal second acceptance criterion.
- Continue stepping through to the end: every node in the sequential
  spine (research_join → contrarian_investor → debate_loop →
  risk_officer → valuation_agent → portfolio_manager →
  report_generator → pdf_export) transitions running → done in turn,
  and the graph reads "Analysis complete" once the final step is
  reached.
- "Back"/"Reset" correctly reverse/clear the demo state.

If a real backend + real analysis run is available, the more valuable
end-to-end check is wiring `LiveGraphView` temporarily into
`AnalysisResultPage.tsx` in place of (or alongside) `AgentProgressBoard`
and watching a real job run through it live — but that wiring itself is
T-097's job, not something to leave merged into `main` from this branch.

### Step 10 — Commit (two-commit pattern)

```bash
git add frontend/src/hooks/useAnalysisStream.ts
git add frontend/src/lib/graph/pipelineNodeStyles.ts
git add frontend/src/components/graph/PipelineGraphNode.tsx
git add frontend/src/lib/graph/liveGraphState.ts
git add frontend/src/components/graph/LiveGraphNode.tsx
git add frontend/src/components/graph/LiveGraphView.tsx
git add frontend/src/components/graph/index.ts
git add frontend/src/pages/ComponentsPreviewPage.tsx
git add frontend/src/test/liveGraphState.test.ts
git add frontend/src/test/LiveGraphNode.test.tsx
git add frontend/src/test/LiveGraphView.test.tsx
git add frontend/src/test/useAnalysisStream.test.ts
git add docs/week-22/T-096-ui-live-graph-view.md

git commit -m "feat(frontend): render live LangGraph execution as an animated graph

- Add optional event_type field to AgentStreamEvent (useAnalysisStream)
  plus EVENT_TYPE_NODE_STARTED/EVENT_TYPE_NODE_COMPLETED constants --
  optional so every pre-T-096 event fixture stays valid, the literal
  'WS clients ignoring the new event type still work' criterion applied
  frontend-side
- Add src/lib/graph/liveGraphState.ts: deriveNodeStatuses turns the raw
  event stream into one pending/running/done/failed status per node,
  keyed off each node's own most recent event (no special-case code
  needed for the 4 parallel research nodes animating simultaneously --
  it falls out of correct per-node logic); missing event_type defaults
  to 'done', matching cast_event's own backend default
- Extract PIPELINE_KIND_STYLES/PIPELINE_HANDLE_CLASS_NAME out of
  PipelineGraphNode.tsx into pipelineNodeStyles.ts (mechanical,
  behaviour-preserving) so the new live node renderer shares the exact
  same base look
- Add LiveGraphNode: pulsing ring + bouncing-dots badge for running,
  checkmark/warning corner badge for done/failed, dimmed for pending,
  motion-reduce:animate-none on every animated class
- Add LiveGraphView: the task's deliverable, props-shaped identically
  to AgentProgressBoardProps so T-097's view toggle needs no adapter
  layer; PIPELINE_EDGES stay untouched (debate_loop edge animation is
  T-097's scope)
- Add an interactive event-stream stepper demo to /dev/components so
  both acceptance criteria are visually checkable without a live
  backend
- Full test coverage: pure derivation logic, per-status node rendering,
  the composed live graph view (including a real rerender proving the
  running -> done transition), and useAnalysisStream's new optional
  event_type handling

Closes #96"
```

If a formatter modifies files after staging, re-stage and make a
second, separate commit rather than amending:

```bash
git add -A
git commit -m "style: apply prettier formatting to T-096 files"
```

### Step 11 — Push and open the PR

```bash
git push -u origin feat/ui-live-graph-view
```

**Base branch:** `main`
**Compare branch:** `feat/ui-live-graph-view`

## Pull Request

**PR title:**

```
feat(ui): build LiveGraphView component driven by WebSocket events
```

**PR description:**

```markdown
## Summary
Adds LiveGraphView -- a live, WebSocket-driven rendering of the T-094
pipeline topology where every node's pending/running/done/failed
status is derived from useAnalysisStream's real event stream (T-095's
NODE_STARTED events in particular). Nodes pulse the instant their
started event arrives and flip to a checkmarked "done" on completion,
in real time; the 4 parallel research nodes animate simultaneously,
falling naturally out of each node deriving its status independently
from its own latest event.

## Changes
- event_type added (optional) to AgentStreamEvent, plus
  EVENT_TYPE_NODE_STARTED/EVENT_TYPE_NODE_COMPLETED constants --
  optional so every pre-existing event fixture in the test suite stays
  valid unmodified
- New src/lib/graph/liveGraphState.ts: deriveNodeStatuses, pure and
  fully unit tested, including the debate-loop repeat-node case and the
  4-simultaneous-parallel-nodes case
- PIPELINE_KIND_STYLES/PIPELINE_HANDLE_CLASS_NAME extracted from
  PipelineGraphNode.tsx into a shared module (mechanical change, no
  behaviour change, existing PipelineGraphNode tests untouched)
- New LiveGraphNode (pulsing ring + dots badge for running, checkmark/
  warning badge for done/failed) and LiveGraphView (the actual
  deliverable) components
- LiveGraphViewProps intentionally mirrors AgentProgressBoardProps so
  T-097's card/graph view toggle needs no adapter layer
- Interactive demo added to /dev/components (event-batch stepper) so
  both acceptance criteria are checkable without a live backend
- Full test coverage across 3 new test files plus an extension to
  useAnalysisStream's existing test suite

## Testing
- `npm run test:run` -- all green, including the new/updated T-096 test
  files
- Manual smoke test: stepped through the /dev/components demo,
  confirmed the running pulse, the done checkmark, and all 4 research
  nodes pulsing together at Step 3
- `npm run type-check`, `npm run lint`, `npm run format:check` all pass
- `npm run build` succeeds

## LangSmith Trace
N/A -- frontend-only change, no agent/LLM-facing code touched.

## Screenshots
_Attach a screenshot (or short screen recording) of the /dev/components
demo mid-Step-3, showing all 4 research nodes pulsing simultaneously,
before opening the PR._

## Related Issues
Closes #96 (adjust to your actual issue number if different)
```

## Testing

Frontend (`npm run test:run`):

- **`liveGraphState.test.ts`** — every node pending with no events; a
  node running the instant its own started event exists; done once its
  completed event lands; failed when the completed event's status is
  `"failed"`; always uses the node's MOST RECENT event, not its first
  (the debate-loop repeat-node case); a missing `event_type` defaults to
  done, never running; all 4 parallel research nodes running
  simultaneously given 4 independent started events; a mixed 3-done/
  1-still-running case; a node never touched this run stays pending even
  after the pipeline completes; START done the instant any event
  exists; END pending while the stream is open, done once complete and
  the run succeeded, failed once complete and the run's last event
  failed.
- **`LiveGraphNode.test.tsx`** — label/subtitle render; `data-node-status`
  marker present and correct for each of the 4 `PipelineNodeStatus`
  values; the "Running" status badge (role="status") appears only for
  running; "Completed"/"Failed" labelled badges appear only for
  done/failed respectively; no badge at all for pending.
- **`LiveGraphView.test.tsx`** — container renders; every real node's
  label reaches the DOM; all 17 nodes read pending before any event;
  exactly one node flips to running given its started event; a
  `rerender` with the completion event added proves the running -> done
  transition happens live, not just on initial mount; all 4 parallel
  research nodes read running together given their 4 started events;
  END reads done once `isComplete` is true after a successful run;
  connecting indicator and error banner render correctly;
  `className`/`height` props apply.
- **`useAnalysisStream.test.ts`** (extended) — a message with no
  `event_type` field at all is still accepted (using the file's
  existing, deliberately pre-T-095-shaped `EVENT_1`/`EVENT_2` fixtures);
  `event_type` passes through untouched when a message does carry it;
  a message where `event_type` is present but not a string is rejected
  by the runtime guard, exactly like every other malformed-field case
  this hook already handles.

"Nodes visibly pulse on start and flip to done on completion in real
time during a live analysis run" (the first acceptance criterion) is
covered by `LiveGraphNode.test.tsx`'s per-status badge assertions and,
critically, `LiveGraphView.test.tsx`'s `rerender`-based test proving the
running -> done transition happens from new events arriving, not only
on first mount. "Parallel nodes animate simultaneously" (the second) is
covered at both the pure-data layer (`liveGraphState.test.ts`) and the
rendered-DOM layer (`LiveGraphView.test.tsx`), each asserting all 4
research nodes read `"running"` given their 4 independent started
events.

## Verification gate run locally before pushing

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

Backend: unaffected — no backend files touched by this task.

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

## LangSmith Trace

N/A — no agent, prompt, or LLM-facing code touched; this task adds a
frontend field, a pure derivation module, two new components, and their
tests.

## Related Issues

Closes #96 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `node_modules` is not installed
here and the real `npm run type-check`/`lint`/`format:check`/
`test:run`/`build` could not be executed directly. Verification here
was `tsc --noEmit` run standalone against each touched file (module-
resolution errors for `reactflow`/`react`/etc. are expected and were
filtered out; no other errors were found beyond two pre-existing,
untouched `useState`-inference artifacts already present in
`ComponentsPreviewPage.tsx` and `useAnalysisStream.ts` before this
task), a brace/paren balance check, and a manual line-length check
against Prettier's configured 100-character `printWidth`. **Real
verification — the actual `npm run test:run`/`type-check`/`lint` runs —
is delegated to your local environment** per Step 8 above, exactly as
with every previous task's workflow doc.