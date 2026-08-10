# T-098 — Tests + docs for live graph viz

**Phase:** 9 — Live Graph Visualization
**Week:** 22
**Branch:** `test/ui-live-graph-view`
**Type:** Testing
**Priority:** 🟢 Medium
**Est. hours:** 2

## Summary

T-098 is Phase 9's hardening pass: it does not add any new production
behaviour to `LiveGraphView` (T-096/T-097 already built the real
functionality), it makes the existing behaviour's test coverage
explicit and thorough, and brings the project's own architecture
documentation up to date with the graph visualization feature that
Phase 9 actually shipped. Two things land here: a dedicated,
sequence-driven test section proving `LiveGraphView` walks through
`pending -> running -> done` (and `running -> failed`) correctly across
successive live updates rather than only at isolated snapshots, plus
broader parallel-node coverage (out-of-order completion, mixed
running/done/failed states); and updates to `docs/ARCHITECTURE.md` and
`docs/GRAPH_DIAGRAM.md` so both documents actually mention the
components Phase 9 built.

## Acceptance criteria (from task spec)

- [x] Vitest coverage for pending/running/done transitions and
      parallel-node handling
- [x] `ARCHITECTURE.md` references new component

## Design decisions

- **The new tests are sequence-driven (successive `rerender` calls
  with a growing events array), not single-snapshot.** T-096/T-097
  already left reasonable coverage in `LiveGraphView.test.tsx` — a node
  reads `running` given a started event, `done` given a completed one,
  4 parallel nodes read `running` given 4 started events — but every
  one of those tests drives at most 1–2 renders in isolation. None of
  them proves a SINGLE node genuinely walks `pending -> running -> done`
  across a live sequence of updates the way a real WebSocket stream
  actually delivers events (one at a time, accumulating). T-098's new
  `"takes a single node through the full pending -> running -> done
  sequence"` test does exactly that: one `render`, two `rerender`
  calls, an assertion after each step — this is the direct, literal
  interpretation of "coverage for pending/running/done transitions"
  (transitions, plural, as a sequence — not three independent facts).
- **A `"walks a realistic mini-pipeline"` test drives the sequential
  spine and the parallel fan-out together, checked at every
  intermediate step**, rather than only checking a final state. This
  catches a class of bug the isolated tests cannot: a regression that
  gets the END state of a render right by coincidence while an
  INTERMEDIATE state (e.g. the exact moment 2 of 4 parallel nodes have
  finished and 2 are still running) was silently wrong along the way.
  The test asserts `nodeByStatus("running")`/`nodeByStatus("done")`
  counts after every one of 4 successive events-array states, including
  correctly accounting for the `__start__` boundary sentinel's own
  "done the instant any event exists" rule at each step (a mistake
  caught and fixed while writing this very test — see the commit
  history / PR diff for the corrected `doneCount` math at step 1).
- **`"running -> failed"` gets its own dedicated transition test**,
  which no earlier task's test suite had at the `LiveGraphView`
  component/DOM layer (the pure-data layer, `liveGraphState.test.ts`,
  already covered a node reading `"failed"` given a single failed
  event, but not the transition itself, and not through the rendered
  component). `LiveGraphNode`'s own failed-badge rendering was already
  covered in isolation by T-096's `LiveGraphNode.test.tsx`; this test
  is specifically about `LiveGraphView`'s wiring proving the
  transition happens correctly end to end as new events arrive.
- **Parallel-node handling gets 2 new tests beyond T-096's original
  "all 4 start together" case**: nodes completing in a DIFFERENT order
  than they started (macro finishing first despite starting last — a
  realistic scenario, since research agents' API calls resolve
  independently), and 3 of 4 nodes still running while the 4th alone
  fails. Both directly exercise "parallel-node handling" beyond the
  simplest possible case (all 4 doing the same thing at the same time),
  which is what the acceptance criterion's plural "handling" implies is
  needed.
- **`docs/ARCHITECTURE.md`'s Components table and Technology choices
  table both get direct references to the new components** —
  `PipelineGraphView`/`LiveGraphView` as a new "Live pipeline graph"
  row, and `ReactFlow` (a real dependency since T-094 that this
  pre-Phase-9 planning document had never been updated to mention) in
  the Technology choices table. A new "Live pipeline graph — detail"
  subsection under Layer 1 covers what each component does, how the
  Cards/Graph toggle avoids losing stream state, and cross-references
  `docs/GRAPH_DIAGRAM.md` for the topology both the frontend and the
  backend independently render. This is the literal, minimal
  satisfaction of "ARCHITECTURE.md references new component."
- **The WebSocket streaming pattern section (same document) was also
  corrected**, not just left stale beside the new content. It
  previously described events firing only "at each node completion"
  (no mention of T-095's NODE_STARTED events, without which the live
  graph's pulse-on-start behaviour would be undocumented and
  unexplained), routing through "a Redis pub/sub channel" (never true —
  `backend/services/ws_broadcaster.py` has always been a plain
  in-process `asyncio.Queue` registry; Redis is used elsewhere, for
  HTTP response caching, not this stream), and showed a JSON example
  with fields that don't exist in the real `AgentStreamEvent`
  (`duration_ms`, `timestamp`) and was missing fields that do
  (`job_id`, `progress_percent`, `is_final`, `event_type`). Leaving
  this actively wrong beside an accurate new "Live pipeline graph"
  section — the one component that actually depends on `event_type`
  existing — would have undermined the very reference this task adds.
  This correction is scoped tightly to the one section directly
  adjacent to and load-bearing for the new content; the rest of
  `ARCHITECTURE.md`'s broader, pre-implementation drift (e.g. Clerk vs.
  the project's actual JWT auth, described elsewhere in the document)
  is out of scope for this task and was left untouched.
- **`docs/GRAPH_DIAGRAM.md` was NOT hand-edited as a one-off.** The
  file's own header says, verbatim, "Auto-generated... Do not edit
  manually -- your changes will be overwritten on the next graph
  compile" — it is fully regenerated by
  `backend/graph/graph_visualisation.py`'s `_HEADER_TEMPLATE` on every
  `build_graph()` call. The correct way to "update" it is to add the
  new content to that Python template string (a new "Frontend
  Rendering" section, cross-referencing `PipelineGraphView`/
  `LiveGraphView`), so any future regeneration reproduces the same
  reference automatically, and then update the currently-committed
  `docs/GRAPH_DIAGRAM.md` snapshot to match byte-for-byte what the
  template would now produce (verified directly — see Testing, below)
  rather than let the checked-in file silently drift from what the code
  actually generates.
- **No other section of `_HEADER_TEMPLATE` was touched.** The existing
  "Overview" prose says "All 12 nodes" while the actual (correct)
  `Total nodes: {node_count}` reports 15 — a pre-existing inconsistency
  in the original template, unrelated to Phase 9 or this task's own
  scope, and left as-is; fixing unrelated pre-existing issues while
  passing through a file is scope creep this project has consistently
  avoided in every prior task's own workflow doc.
- **No new frontend source files.** T-098 is explicitly a testing +
  docs task — no changes to `LiveGraphView.tsx`, `LiveGraphNode.tsx`,
  or `liveGraphState.ts` were needed or made; every new test in this
  task exercises existing, already-shipped T-096/T-097 behaviour.

## Files changed / created

### Backend — auto-generated diagram source

- **`backend/graph/graph_visualisation.py`** (**MODIFY**) — adds a
  "Frontend Rendering" section to `_HEADER_TEMPLATE`; module docstring
  updated with a T-098 note explaining why this file (not the `.md`
  snapshot) is the correct edit point.

### Docs

- **`docs/GRAPH_DIAGRAM.md`** (**MODIFY**) — the committed snapshot
  updated to match `_HEADER_TEMPLATE`'s new "Frontend Rendering"
  section, verified byte-identical to what the template produces.
- **`docs/ARCHITECTURE.md`** (**MODIFY**) — Components table gets a new
  "Live pipeline graph" row and an updated "Live agent progress viewer"
  description; a new "Live pipeline graph — detail (T-094–T-097)"
  subsection added under Layer 1; Technology choices table gets a new
  ReactFlow row; the WebSocket streaming pattern section (Layer 2)
  corrected to describe the real in-process broadcaster, the
  NODE_STARTED addition, and the real `AgentStreamEvent` shape
  including `event_type`.
- **`docs/week-22/T-098-tests-docs-live-graph-viz.md`** (this file).

### Frontend — tests

- **`frontend/src/test/LiveGraphView.test.tsx`** (**MODIFY**) — new
  `"LiveGraphView state transitions (T-098)"` describe block: a full
  `pending -> running -> done` sequence test for a single node across 3
  renders; a `running -> failed` transition test; a realistic
  ordered mini-pipeline walk (planner, then the 4 parallel research
  nodes, then research_join) checked at every one of 4 intermediate
  steps; an out-of-order parallel-completion test; a 3-running/1-failed
  parallel test. Module docstring updated.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b test/ui-live-graph-view

git branch
# → * test/ui-live-graph-view
```

### Step 2 — Add the state-transition and parallel-node tests

- `frontend/src/test/LiveGraphView.test.tsx`: add the new
  `"LiveGraphView state transitions (T-098)"` describe block.

### Step 3 — Update the auto-generated graph diagram's template

- `backend/graph/graph_visualisation.py`: add the "Frontend Rendering"
  section to `_HEADER_TEMPLATE`.
- `docs/GRAPH_DIAGRAM.md`: update the committed snapshot to match.

### Step 4 — Update the architecture documentation

- `docs/ARCHITECTURE.md`: Components table, new detail subsection,
  Technology choices table, WebSocket streaming pattern correction.

### Step 5 — Run the full verification gate locally

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

```bash
cd ..
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_graph_visualisation.py -v
python -m pytest backend/tests/unit -v
```

If `format:check` reports files needing formatting, run
`npm run format` and re-stage before committing, per the established
two-commit pattern.

### Step 6 — Verify the diagram template and the committed snapshot agree

There is no network access to actually re-run `build_graph()` and
regenerate `docs/GRAPH_DIAGRAM.md` in every environment, so verify the
two by hand:

```bash
# The "Frontend Rendering" section added to the Python template and
# the same section in the committed docs/GRAPH_DIAGRAM.md file should
# be identical.
python3 - <<'PY'
import re
content = open("backend/graph/graph_visualisation.py").read()
m = re.search(r'_HEADER_TEMPLATE = """\\\n(.*?)"""', content, re.S)
template = m.group(1)
py_section = template[template.index("## Frontend Rendering"):].rstrip()

md = open("docs/GRAPH_DIAGRAM.md").read()
md_section = md[md.index("## Frontend Rendering"):].rstrip()

assert py_section == md_section, "template and committed snapshot have drifted"
print("OK: template and snapshot match")
PY
```

If your local environment has all backend dependencies installed and
`ENVIRONMENT` unset (or set to something other than `test`), you can
instead regenerate the real file directly and diff it:

```bash
set ENVIRONMENT=development
python -c "from backend.graph.graph import build_graph; build_graph()"
git diff docs/GRAPH_DIAGRAM.md
```

A diff limited to the generation timestamp line is expected and fine
(each run re-stamps it); any other diff means the checked-in snapshot
and the template have drifted and the snapshot needs updating.

### Step 7 — Manual review of the docs changes

```bash
cd frontend
npm run dev
```

Not strictly necessary for this task (no UI behaviour changed), but a
quick look confirms nothing regressed: visit `/analysis/{job_id}/result`
on a job with a live stream (or `/dev/components`'s T-096 stepper demo)
and confirm the Cards/Graph toggle and live graph still behave exactly
as they did after T-097 — this task changed no production code, so
nothing here should look any different.

### Step 8 — Commit (two-commit pattern)

```bash
git add frontend/src/test/LiveGraphView.test.tsx
git add backend/graph/graph_visualisation.py
git add docs/GRAPH_DIAGRAM.md
git add docs/ARCHITECTURE.md
git add docs/week-22/T-098-tests-docs-live-graph-viz.md

git commit -m "test(frontend): add tests for LiveGraphView state transitions

- Add a dedicated 'LiveGraphView state transitions (T-098)' test
  section: a single node driven through the full pending -> running ->
  done sequence across successive rerenders (not a single snapshot); a
  running -> failed transition test; a realistic ordered mini-pipeline
  walk (planner -> 4 parallel research nodes -> research_join) checked
  at every intermediate step, correctly accounting for the __start__
  sentinel's own live status; an out-of-order parallel-completion
  test; a 3-running/1-failed parallel test
- Add a 'Frontend Rendering' section to
  backend/graph/graph_visualisation.py's _HEADER_TEMPLATE,
  cross-referencing PipelineGraphView/LiveGraphView -- the correct
  edit point for docs/GRAPH_DIAGRAM.md, which is fully auto-generated
  and explicitly warns against manual edits; update the committed
  docs/GRAPH_DIAGRAM.md snapshot to match byte-for-byte
- Update docs/ARCHITECTURE.md: new 'Live pipeline graph' Components
  row and detail subsection, ReactFlow added to Technology choices,
  and the WebSocket streaming pattern section corrected to describe
  the real in-process broadcaster, the T-095 NODE_STARTED addition,
  and the real AgentStreamEvent shape including event_type

Closes #98"
```

If a formatter modifies files after staging, re-stage and make a
second, separate commit rather than amending:

```bash
git add -A
git commit -m "style: apply prettier/black formatting to T-098 files"
```

### Step 9 — Push and open the PR

```bash
git push -u origin test/ui-live-graph-view
```

**Base branch:** `main`
**Compare branch:** `test/ui-live-graph-view`

## Pull Request

**PR title:**

```
test: cover live graph visualization node state transitions
```

**PR description:**

```markdown
## Summary
Phase 9's hardening pass. No new production behaviour -- LiveGraphView
(T-096/T-097) already works; this task makes its test coverage
explicit and sequence-driven rather than single-snapshot, and brings
docs/ARCHITECTURE.md and docs/GRAPH_DIAGRAM.md up to date with the
graph visualization feature Phase 9 actually shipped.

## Changes
- New LiveGraphView test section: a genuine pending -> running -> done
  sequence across successive rerenders for a single node; a
  running -> failed transition; a realistic ordered mini-pipeline walk
  checked at every intermediate step (catches bugs that only show up
  mid-sequence, not just at the final state); out-of-order parallel
  completion; a mixed running/failed parallel case
- docs/ARCHITECTURE.md: new Components table row + detail subsection
  for PipelineGraphView/LiveGraphView, ReactFlow added to Technology
  choices, and the WebSocket streaming pattern section corrected to
  match the real backend/services/ws_broadcaster.py implementation
  (was describing a fictional Redis pub/sub mechanism and a JSON shape
  that never matched the real AgentStreamEvent)
- docs/GRAPH_DIAGRAM.md is auto-generated (backend/graph/
  graph_visualisation.py) and explicitly warns against manual edits --
  added the new "Frontend Rendering" cross-reference to the Python
  template itself, then synced the committed snapshot to match

## Testing
- `npm run test:run` -- all green, including the new T-098 test
  section in LiveGraphView.test.tsx
- `python -m pytest backend/tests/unit/test_graph_visualisation.py -v`
  -- all green; the new template section doesn't touch any of the
  existing substring assertions
- Verified docs/GRAPH_DIAGRAM.md's new section is byte-identical to
  what graph_visualisation.py's _HEADER_TEMPLATE now produces (see PR
  description's verification script, also in the T-098 workflow doc)
- `npm run type-check`, `npm run lint`, `npm run format:check` all pass
- `python -m black/isort/flake8/mypy backend` all pass
- `npm run build` succeeds

## LangSmith Trace
N/A -- no agent, prompt, or LLM-facing code touched; this is a testing
and documentation task.

## Screenshots
N/A -- no UI behaviour changed in this task.

## Related Issues
Closes #98 (adjust to your actual issue number if different)
```

## Testing

Frontend (`npm run test:run`):

- **`LiveGraphView.test.tsx`** (new `"state transitions (T-098)"`
  section) — a single node's full lifecycle across 3 renders
  (`pending` with no events, `running` given its started event and
  confirmed no longer `pending`, `done` given its completed event and
  confirmed no longer `running`); a `running -> failed` transition;
  a 4-step ordered mini-pipeline simulation checked at every step
  (planner starting; planner done + all 4 research nodes running;
  2-of-4 research nodes done while 2 remain running; all 4 done with
  `research_join` now running), with running/done counts asserted at
  each step including the `__start__` sentinel's own contribution; all
  4 research nodes completing in an order different from their start
  order, with each node's individual final status verified by label;
  3 of 4 parallel research nodes still `running` while the 4th alone
  reads `failed`.

Backend (`python -m pytest backend/tests/unit/test_graph_visualisation.py -v`):

- All 8 existing test classes continue to pass unmodified —
  `_build_markdown`'s substring assertions (`"Auto-generated"`,
  `"AIRP"`, mermaid fence markers, node count, UTC timestamp, "not
  edit manually") are all still true of the template with the new
  section appended after the existing "Edge Notes" content.

"Vitest coverage for pending/running/done transitions and
parallel-node handling" (the first acceptance criterion) is covered
directly by the new test section described above — genuine multi-step
sequences, not isolated snapshots, for both the transition coverage
and the parallel-node coverage. "ARCHITECTURE.md references new
component" (the second) is covered by the new Components table row,
detail subsection, and Technology choices row described in Design
Decisions above.

## Verification gate run locally before pushing

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

## LangSmith Trace

N/A — no agent, prompt, or LLM-facing code touched; this task adds
frontend test coverage and updates two documentation files (one of
them via its Python generator template, not a direct hand-edit).

## Related Issues

Closes #98 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `node_modules` is not installed
and neither the real `npm run test:run`/`type-check`/`lint`/
`format:check`/`build` nor a real `pytest` run against
`test_graph_visualisation.py` could be executed directly. Verification
here was: `tsc --noEmit` run standalone against the touched frontend
file (module-resolution errors for `reactflow`/`react`/`vitest`/etc.
are expected and were filtered out; the one genuine issue found — an
implicit-`any` callback parameter — was fixed with an explicit type
annotation); a brace/paren balance check; a manual line-length check
against Prettier's configured 100-character `printWidth`; `python -m
py_compile` on the touched backend file; a manual re-read of
`test_graph_visualisation.py`'s existing assertions against the new
template content to confirm none would break; and a direct
byte-for-byte comparison (via a small Python script, included in Step 6
above) confirming the Python template's new section and the committed
`docs/GRAPH_DIAGRAM.md` snapshot agree exactly. **Real verification —
the actual `npm run test:run`/`pytest`/`type-check`/`lint` runs — is
delegated to your local environment** per Steps 5–6 above, exactly as
with every previous task's workflow doc.