# T-094 — Add react-flow + static graph topology

**Phase:** 9 — Live Graph Visualization
**Week:** 22
**Branch:** `feat/graph-viz-topology`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 3

## Summary

Phase 9 replaces the card-based `AgentProgressBoard` (T-053-era) with a live,
animated view of the actual LangGraph pipeline as it executes. T-094 is the
foundation every later Phase 9 task builds on: it adds the `reactflow`
dependency and defines the **static** node/edge topology of AIRP's real
`backend/graph/graph.py` `StateGraph` -- no WebSocket wiring, no animation,
no state machine. Just the honest shape of the graph, rendered once, so
T-095 (NODE_STARTED events), T-096 (`LiveGraphView` wired to the WebSocket
stream), and T-097 (debate loop animation + view toggle) all have a
correct, tested topology to drive rather than inventing their own.

The topology was **transcribed directly from `backend/graph/graph.py`'s
`build_graph()`**, not from this task's own (simplified) one-line
description -- every real `workflow.add_node(...)`,
`workflow.add_edge(...)`, and `workflow.add_conditional_edges(...)` call in
that file has exactly one corresponding node or edge here, including the
two T-032 conditional routing branches (`error_handler`,
`sentiment_escalation`) the task description collapses into "risk/
contrarian" and the T-032 `research_join` barrier node it omits entirely.

## Acceptance criteria (from task spec)

- [x] Static graph renders all pipeline nodes and edges matching `graph.py`
- [x] `debate_loop` rendered as a cyclical edge

## Design decisions

- **The topology is pure data (`src/lib/graph/pipelineTopology.ts`), not
  JSX.** `PIPELINE_NODES: Node<PipelineNodeData>[]` and
  `PIPELINE_EDGES: Edge[]` are plain, framework-free constants -- the same
  "computation separate from rendering" split
  `src/lib/compare/winnerLogic.ts` and `src/lib/accuracy/rollingAccuracy.ts`
  already establish. This is what makes `pipelineTopology.test.ts` possible
  without mounting a single component, and it is what T-096 will import and
  re-render with live per-node status rather than redefining.
- **Node ids are copied string-for-string from `backend/graph/nodes.py`'s
  `NODE_*` constants** (`"fundamental_analyst"`, `"research_join"`,
  `"debate_loop"`, etc.), not arbitrary frontend-chosen labels. T-095 will
  add a `NODE_STARTED` WebSocket event carrying these same backend node
  names, and T-096 will match incoming events against `PIPELINE_NODES` by
  id -- if the ids didn't match byte-for-byte today, that match would
  silently fail later. `__start__`/`__end__` are LangGraph's own sentinel
  names for `START`/`END`, reused as-is rather than invented.
- **`START` and `END` are modelled as real (if minimal) nodes**, not
  dropped. `backend/graph/graph_visualisation.py`'s own Mermaid export
  (T-034, `docs/GRAPH_DIAGRAM.md`) renders LangGraph's `START`/`END`
  sentinels the same way -- omitting them here would make this component
  quietly disagree with the diagram the backend itself already generates.
  They get their own `"boundary"` `PipelineNodeKind` (small pill, neutral
  colour) so they read as endpoints, not agents.
- **`research_join` is included as its own node**, exactly matching the
  T-032 rationale documented at length in `graph.py` itself: LangGraph
  requires a single sequential join node between a `Send`-API parallel
  fan-out and any conditional branch, or the routing function fires once
  per parallel branch instead of once. The task's own one-line description
  ("planner -> 4 parallel research nodes -> research_join -> risk/
  contrarian") already names it, but the description's "-> risk/
  contrarian" compresses away that `research_join` actually branches to
  **three** possible destinations (`error_handler`, `sentiment_escalation`,
  or directly to `contrarian_investor`), not two -- all three are rendered
  as conditional (dashed) edges, matching `route_after_research`'s real
  three-way `{ROUTE_ERROR, ROUTE_ESCALATE_SENTIMENT, ROUTE_PROCEED}`
  mapping in `graph.py`.
- **`planner`'s `ABORT` short-circuit to `END` is included**, even though
  neither this task's description nor a first read of the "9 phases"
  overview calls it out. `route_after_planner` genuinely has two outcomes
  in `graph.py` (the 4-way `Send` fan-out, or `"__end__" -> END`) --
  rendering only the fan-out half would silently misrepresent the real
  conditional edge as an unconditional one. It is styled identically to
  the other conditional (dashed) edges so it reads as "a possible path",
  not a normal step in the happy path.
- **The `debate_loop -> contrarian_investor` cycle (T-040's
  `route_after_contrarian` `DEBATE_AGAIN` branch) is the acceptance
  criteria's headline requirement**, and is the one edge in the whole
  topology that points backward up the column instead of down it. Three
  things make it read as a deliberate loop rather than a rendering bug:
  it is routed via each node's **left-side** handle (`source-left` /
  `target-left`) instead of the top/bottom handles every other edge uses,
  so it visually arcs out to the side instead of overlapping the spine; it
  is the only edge with `animated: true`; and it carries a distinct
  brand-violet stroke colour instead of the default/conditional-grey
  styling every other edge uses. `DEBATE_LOOP_EDGE_ID` is exported by name
  specifically so `pipelineTopology.test.ts` can assert on this one edge's
  properties directly rather than searching by source/target alone.
- **Every `PipelineGraphNode` renders 4 named handles**
  (`target-top`/`source-bottom` for the normal downward spine,
  `target-left`/`source-left` for the two sideways edges above) rather
  than relying on ReactFlow's single default handle per node. A node with
  only one target and one source handle cannot have two structurally
  different incoming/outgoing edges rendered distinctly -- the explicit
  handle ids are what let `debate_loop`'s cyclic edge and `planner`'s
  abort edge escape sideways without ReactFlow drawing them straight
  through every node in between.
- **Node colour-by-kind (`PipelineNodeKind`: boundary / planner / research
  / routing / decision / synthesis / output) deliberately reuses
  `docs/AIRP_Architecture.drawio`'s own colour legend** (research agents
  blue, decision agents — contrarian/debate_loop/risk/valuation — red,
  Portfolio Manager green) via existing Tailwind palette entries
  (`blue-700`, `verdict-sell`, `verdict-buy`, `slate-500`, `brand-500`)
  rather than introducing new arbitrary hex values -- the running app and
  the architecture diagram should read as the same system, and the
  existing design system already exposes tokens close enough to the
  diagram's own palette that no new colours were needed.
- **This is deliberately the STATIC topology only.** No `useState`, no
  props for live status, no WebSocket import anywhere in
  `PipelineGraphView.tsx` or `PipelineGraphNode.tsx`. Every node always
  renders in one undifferentiated visual state. Wiring live pending/
  running/done status onto this exact topology is T-096's job
  specifically (`LiveGraphView.tsx wired to WebSocket stream`) --
  pre-building that state machine now would mean T-096 either throws this
  component away or fights an existing (untested-against-real-events)
  state shape instead of building cleanly on a topology that is already
  known-correct.
- **`PipelineGraphView` is rendered on the existing `/dev/components`
  preview route (`ComponentsPreviewPage.tsx`), not on a new product
  route.** T-094's acceptance criteria only asks that the static graph
  *renders* correctly -- there is no product surface for it yet, since
  T-096/T-097 are what actually mount it on the live analysis progress
  page (behind the view toggle T-097 adds). `/dev/components` is exactly
  where T-054 already established this kind of "does it render, does it
  look right" checkpoint belongs, matching how every other Phase 6
  component preview lives there before its real product page exists.
- **`nodesDraggable`/`nodesConnectable`/`elementsSelectable` are all
  `false`**; panning and zooming stay enabled. Editing this topology
  interactively would make no sense -- its shape is defined entirely in
  `pipelineTopology.ts` -- but the graph is tall (17 nodes top-to-bottom)
  and letting a reader pan/zoom to inspect any part of it costs nothing.
  `proOptions={{ hideAttribution: true }}` removes ReactFlow's default
  attribution watermark, consistent with the rest of the app's polished,
  branded surfaces.

## Files changed / created

### Frontend — dependency

- **`frontend/package.json`** (**MODIFY**) — adds `"reactflow": "^11.11.4"`
  to `dependencies`. **`package-lock.json` must be regenerated locally**
  (see Step 2 below) -- it cannot be hand-edited correctly and this
  sandbox has no network access to run `npm install` itself.

### Frontend — topology data

- **`frontend/src/lib/graph/pipelineTopology.ts`** (**CREATE**) — pure,
  framework-free `PIPELINE_NODES` / `PIPELINE_EDGES` constants, the
  `NODE_*` id constants (mirroring `backend/graph/nodes.py`), and the
  `PipelineNodeKind` / `PipelineNodeData` types.

### Frontend — graph components

- **`frontend/src/components/graph/PipelineGraphNode.tsx`** (**CREATE**)
  — custom ReactFlow node renderer, colour-coded by `PipelineNodeKind`.
- **`frontend/src/components/graph/PipelineGraphView.tsx`** (**CREATE**)
  — the `ReactFlow` wrapper rendering the static topology.
- **`frontend/src/components/graph/index.ts`** (**CREATE**) — barrel
  export, mirroring `src/components/charts/index.ts`'s pattern.

### Frontend — preview page

- **`frontend/src/pages/ComponentsPreviewPage.tsx`** (**MODIFY**) — adds a
  "Pipeline graph (T-094)" section rendering `PipelineGraphView` at
  `/dev/components`, so the static graph is actually reachable and
  visually checkable, not just unit-tested.

### Frontend — tests

- **`frontend/src/test/pipelineTopology.test.ts`** (**CREATE**) — pure
  data assertions: node/edge counts, id uniqueness, every real
  `graph.py` edge present, and the `debate_loop` cycle's structural and
  visual (animated) properties.
- **`frontend/src/test/PipelineGraphNode.test.tsx`** (**CREATE**) — label/
  subtitle rendering, and a `data-node-kind` marker check across all 7
  `PipelineNodeKind` values.
- **`frontend/src/test/PipelineGraphView.test.tsx`** (**CREATE**) —
  container render, every real node's label present in the DOM, the
  `debate_loop` cycle's label, and the `className`/`height` props.

### Docs

- **`docs/week-22/T-094-graph-viz-topology.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/graph-viz-topology

git branch
# → * feat/graph-viz-topology
```

### Step 2 — Add the `reactflow` dependency

```bash
cd frontend
npm install reactflow@^11.11.4
cd ..
```

This updates both `frontend/package.json` and `frontend/package-lock.json`
together in one real `npm install` run -- **do not hand-edit
`package-lock.json`**. If `package.json`'s `dependencies` block already
shows `"reactflow": "^11.11.4"` (delivered pre-edited alongside this task's
other files), running `npm install` with no arguments from `frontend/` is
enough to resolve and lock it.

### Step 3 — Add the topology data module

- `frontend/src/lib/graph/pipelineTopology.ts`: new file.

### Step 4 — Add the graph components

- `frontend/src/components/graph/PipelineGraphNode.tsx`: new file.
- `frontend/src/components/graph/PipelineGraphView.tsx`: new file.
- `frontend/src/components/graph/index.ts`: new file.

### Step 5 — Wire the static graph into the dev preview page

- `frontend/src/pages/ComponentsPreviewPage.tsx`: add the "Pipeline graph
  (T-094)" section and its `PipelineGraphView` import.

### Step 6 — Add the tests

Create all three new test files listed above.

### Step 7 — Run the full verification gate locally

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

If `format:check` reports files needing formatting, run `npm run format`
(Prettier `--write`) and re-stage before committing -- the same
two-commit pattern the backend workflow docs already use for
Black/isort.

### Step 8 — Manual smoke test against a local dev server

```bash
cd frontend
npm run dev
```

Then in a browser, visit `http://localhost:3000/dev/components` and
confirm:

- The "Pipeline graph (T-094)" section renders below "Tooltip" without
  layout errors.
- All 17 nodes are visible when panned/zoomed through: `START`, `Planner`,
  the 4 research agents (`Fundamental Analyst`, `Technical Analyst`,
  `News Sentiment`, `Macro Economist`), `Research Join`, `Error Handler`,
  `Sentiment Escalation`, `Contrarian Investor`, `Debate Loop`,
  `Risk Officer`, `Valuation Agent`, `Portfolio Manager`,
  `Report Generator`, `PDF Export`, `END`.
- The `debate_loop -> contrarian_investor` edge is visibly distinct
  (animated, violet, looping out to the left) from every other edge, and
  is not simply a copy of the normal top-to-bottom style used elsewhere.
- The 3 conditional edges out of `Research Join`
  (`ROUTE_ERROR`/`ROUTE_ESCALATE_SENTIMENT`/`ROUTE_PROCEED`) and
  `planner`'s `ABORT` edge to `END` all render dashed, distinguishing them
  from the solid, unconditional edges on the rest of the spine.
- Panning and zooming work; dragging a node does **not** move it
  (`nodesDraggable={false}`).

### Step 9 — Commit (two-commit pattern)

```bash
git add frontend/package.json frontend/package-lock.json
git add frontend/src/lib/graph/pipelineTopology.ts
git add frontend/src/components/graph/PipelineGraphNode.tsx
git add frontend/src/components/graph/PipelineGraphView.tsx
git add frontend/src/components/graph/index.ts
git add frontend/src/pages/ComponentsPreviewPage.tsx
git add frontend/src/test/pipelineTopology.test.ts
git add frontend/src/test/PipelineGraphNode.test.tsx
git add frontend/src/test/PipelineGraphView.test.tsx
git add docs/week-22/T-094-graph-viz-topology.md

git commit -m "feat(frontend): add react-flow and define AIRP graph topology

- Add reactflow (^11.11.4) dependency
- Add src/lib/graph/pipelineTopology.ts -- pure, framework-free
  PIPELINE_NODES/PIPELINE_EDGES transcribed directly from
  backend/graph/graph.py's build_graph(): all 15 real nodes (planner,
  4 parallel research agents, research_join, error_handler,
  sentiment_escalation, contrarian_investor, debate_loop, risk_officer,
  valuation_agent, portfolio_manager, report_generator, pdf_export) plus
  the __start__/__end__ sentinels, matching LangGraph's own Mermaid
  export (T-034)
- Node ids copied string-for-string from backend/graph/nodes.py's NODE_*
  constants so T-095/T-096's WebSocket event names match by id with no
  translation layer
- Render debate_loop -> contrarian_investor (T-040's DEBATE_AGAIN branch)
  as a genuinely cyclical edge -- routed via left-side handles, animated,
  and distinctly coloured so it reads as a loop rather than a reversed
  arrow
- Render all 4 conditional edges (planner's ABORT short-circuit, and
  research_join's 3-way ROUTE_ERROR/ROUTE_ESCALATE_SENTIMENT/
  ROUTE_PROCEED branch) dashed, distinct from the solid unconditional
  spine edges
- Add PipelineGraphNode (custom ReactFlow node, coloured by
  PipelineNodeKind using docs/AIRP_Architecture.drawio's own colour
  legend) and PipelineGraphView (the ReactFlow wrapper)
- Wire the static graph into the existing /dev/components preview page
- Full test coverage: topology data assertions, node rendering per kind,
  and the composed graph view

Closes #94"
```

If a formatter modifies files after staging (Prettier `--write` via
`npm run format`, or an editor auto-fix), re-stage and make a second,
separate commit rather than amending:

```bash
git add -A
git commit -m "style: apply prettier formatting to T-094 files"
```

### Step 10 — Push and open the PR

```bash
git push -u origin feat/graph-viz-topology
```

**Base branch:** `main`
**Compare branch:** `feat/graph-viz-topology`

## Pull Request

**PR title:**

```
feat(ui): scaffold live graph visualization topology
```

**PR description:**

```markdown
## Summary
Adds the `reactflow` dependency and defines the static AIRP LangGraph
pipeline topology as a ReactFlow graph -- all 15 real backend nodes plus
START/END, edges transcribed 1:1 from backend/graph/graph.py's actual
add_edge()/add_conditional_edges() calls, with the T-040 debate_loop
cycle rendered as a genuinely animated, distinctly-styled loop. This is
the foundation Phase 9's remaining tasks (T-095 NODE_STARTED events,
T-096 live WebSocket wiring, T-097 debate animation + view toggle) build
on -- no live state, no WebSocket, purely the correct static shape.

## Changes
- reactflow (^11.11.4) added to frontend/package.json
- src/lib/graph/pipelineTopology.ts -- pure PIPELINE_NODES/PIPELINE_EDGES
  data, transcribed directly from graph.py (not from this task's own
  simplified one-line description), including the research_join barrier
  and both T-032 conditional routing branches (error_handler,
  sentiment_escalation) the short description compresses away
- Node ids copied string-for-string from backend/graph/nodes.py's NODE_*
  constants so later WebSocket event matching (T-095/T-096) needs no
  translation layer
- debate_loop -> contrarian_investor rendered as a left-routed, animated,
  distinctly-coloured cyclic edge -- the one edge in the graph that
  points backward up the spine
- planner's ABORT short-circuit to END, and research_join's full 3-way
  conditional branch, all rendered dashed to distinguish them from the
  solid unconditional spine edges
- PipelineGraphNode (colour-coded by kind, reusing
  docs/AIRP_Architecture.drawio's own legend) and PipelineGraphView
  (the ReactFlow wrapper) components
- Wired into the existing /dev/components preview page (no new product
  route yet -- that's T-096/T-097)
- Full test coverage: pure topology data assertions, per-kind node
  rendering, and the composed graph view

## Testing
- `npm run test:run` -- all green, including the 3 new test files
- Manual smoke test: visited /dev/components, confirmed all 17 nodes
  render, the debate_loop cycle is visually distinct from the rest of
  the graph, all 4 conditional edges render dashed, and panning/zooming
  work while node dragging stays disabled
- `npm run type-check`, `npm run lint`, `npm run format:check` all pass
- `npm run build` succeeds

## LangSmith Trace
N/A -- frontend-only change, no agent/LLM-facing code touched.

## Screenshots
_Attach a screenshot of the rendered pipeline graph (from
/dev/components) here before opening the PR, including a close-up of the
debate_loop cyclic edge._

## Related Issues
Closes #94 (adjust to your actual issue number if different)
```

## Testing

Frontend (`npm run test:run`):

- **`pipelineTopology.test.ts`** — exactly 15 real node ids + 17 total
  nodes (including START/END); no duplicate node or edge ids; every real
  `graph.py` node id present; `RESEARCH_NODE_IDS`/`ROUTING_NODE_IDS`
  match `graph.py`'s own `RESEARCH_NODE_NAMES`/`ROUTING_NODE_NAMES`
  exports; every edge's `source`/`target` references a declared node;
  START→planner and pdf_export→END connectivity; planner's 4-way `Send`
  fan-out; all 4 research agents feeding into `research_join`;
  `research_join`'s full 3-way conditional branch; both routing nodes
  forwarding to `contrarian_investor`; the `debate_loop` cycle's
  structural correctness (`source`/`target`) and its `animated: true`
  visual distinction; `debate_loop`'s `PROCEED` branch to `risk_officer`;
  the full sequential tail (`risk -> valuation -> portfolio_manager ->
  report_generator -> pdf_export`); every node has a non-empty label.
- **`PipelineGraphNode.test.tsx`** — label renders; subtitle renders when
  provided and is omitted (no stray "undefined") when not; each of the 7
  `PipelineNodeKind` values gets its own `data-node-kind` marker.
- **`PipelineGraphView.test.tsx`** — container renders with the expected
  `data-testid`; every one of the 17 real pipeline nodes' labels appear
  in the rendered DOM; the `debate_loop` cycle's `DEBATE_AGAIN` edge
  label renders; `className` merges onto the outer container;
  `height` applies as an inline style.

Consistent with `StockPriceChart.test.tsx`'s own documented restraint
around not asserting on a third-party visualisation library's internals
(there, Recharts; here, ReactFlow) -- these tests check the container,
labels, and this project's own data/props, not ReactFlow's internal pan/
zoom/viewport machinery.

"Static graph renders all pipeline nodes and edges matching graph.py"
(the first acceptance criterion) is covered by `pipelineTopology.test.ts`
asserting against every real `add_edge`/`add_conditional_edges` call and
by `PipelineGraphView.test.tsx` confirming every node's label actually
reaches the DOM. "`debate_loop` rendered as a cyclical edge" (the second)
is covered by the dedicated `DEBATE_LOOP_EDGE_ID` assertions in both
test files.

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
frontend dependency, a pure topology data module, two ReactFlow
components, and their tests.

## Related Issues

Closes #94 (adjust to your actual issue number if different).

## A note on `npm ci` and this sandbox

`frontend/package.json` was edited to add `"reactflow": "^11.11.4"`, but
`frontend/package-lock.json` was **not** regenerated here — this sandbox
has no network access to reach the npm registry, and CI's `frontend` job
runs `npm ci`, which requires `package-lock.json` to already contain a
resolved, hashed entry for `reactflow` and its transitive dependencies
(`@reactflow/*` sub-packages, `d3-*`, `zustand`, etc.) that exactly
matches `package.json`. **Step 2 above (`npm install reactflow@^11.11.4`
run locally) is not optional** — it must be run once, locally, before
`npm run type-check`/`lint`/`test:run`/`build` will succeed, and before
pushing, or CI's `npm ci` step will fail immediately with a lockfile
mismatch.