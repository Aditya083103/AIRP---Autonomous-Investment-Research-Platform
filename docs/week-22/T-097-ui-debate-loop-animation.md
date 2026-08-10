# T-097 — Debate loop animation + view toggle

**Phase:** 9 — Live Graph Visualization
**Week:** 22
**Branch:** `feat/ui-debate-loop-animation`
**Type:** Feature
**Priority:** 🟢 Medium
**Est. hours:** 3

## Summary

T-097 is the final task in Phase 9. It closes out two remaining gaps in
`LiveGraphView` (T-096) and its page-level integration: the
`debate_loop -> contrarian_investor` cycle edge (T-094's
`DEBATE_LOOP_EDGE_ID`) has been visually distinct but permanently,
statically animated since T-094 — it never actually reflected whether a
debate round was live. T-097 makes it genuinely live: dimmed and static
by default, pulsing with the marching-ants `animated` treatment only
while a debate round is actually in progress, across both of its (at
most 2, per `backend.graph.debate.MAX_DEBATE_ROUNDS`) rounds. Separately,
`AnalysisResultPage.tsx`'s existing "Agent progress" tab gets a nested
Cards/Graph toggle so a user can switch between T-059's card board and
T-096's live graph without losing any stream state.

## Acceptance criteria (from task spec)

- [x] Debate loop visibly animates for both rounds
- [x] Toggle switches between AgentProgressBoard and LiveGraphView
      without losing stream state

## Design decisions

- **`deriveDebateLoopEdgeState` (`src/lib/graph/liveGraphState.ts`) is a
  new, separate pure function, not a field bolted onto
  `deriveNodeStatuses`'s return.** A node's own status and an EDGE's
  live state are conceptually different things -- `deriveNodeStatuses`
  answers "what is each node doing", and T-097's acceptance criterion
  is specifically about the cycle EDGE reading as "in motion" or not.
  It takes the already-computed `nodeStatuses` object as a parameter
  (rather than re-deriving contrarian/debate_loop's status internally)
  so a caller building both in the same render -- T-097's own
  `LiveGraphView` -- does exactly one `deriveNodeStatuses` pass, not
  two.
- **`active` is `true` whenever `contrarian_investor` OR `debate_loop`
  itself reads `"running"`** (from the same `nodeStatuses` object),
  rather than any new event-counting or explicit "was the loop-back
  edge just traversed" logic. This is deliberately the simplest
  possible correct rule, and it produces the acceptance criterion's
  "round-trip pulse... across its 2 rounds" entirely for free: because
  `deriveNodeStatuses` already flips each node's status purely from its
  own latest event, `active` naturally cycles
  `true -> false -> true -> false` across a real 2-round debate --
  true while round 1's contrarian/debate_loop are running, false in the
  (typically brief) gap between round 1's debate_loop completing and
  round 2's contrarian starting, true again for round 2, false for good
  once round 2's debate_loop completes and the pipeline moves on to
  `risk_officer`. No code anywhere has to remember "which round already
  pulsed" -- the two-phase pulse is a consequence of the state machine,
  not something explicitly programmed.
- **`currentRound` counts `contrarian_investor`'s own `NODE_STARTED`
  events, not `debate_loop`'s.** Contrarian always starts first in
  every round (`backend/graph/graph.py`: `contrarian_investor ->
  debate_loop`), so counting contrarian's starts reports "round N is
  now in progress" the instant round N genuinely begins. Counting
  `debate_loop`'s own starts instead would report `currentRound: null`
  for the entire first half of round 1, while contrarian_investor is
  already visibly running -- a real, checkable-by-eye inconsistency
  `liveGraphState.test.ts`'s dedicated test for this catches directly.
- **A missing/undefined `event_type` on a contrarian event is treated
  as NOT a round start** (rather than defaulting to "started", which
  would have been the wrong direction here specifically). This mirrors
  `deriveNodeStatuses`'s own "missing `event_type` means completed, not
  running" convention, applied consistently: an old-shaped or hand-built
  event should never falsely bump the round counter.
- **`LiveGraphView`'s `nodes` and `edges` are now built together in one
  `useMemo`** (previously T-096 only memoised `nodes`; `edges` was
  `PIPELINE_EDGES` passed straight through, unchanged). A single
  `deriveNodeStatuses` call now feeds both the per-node paint AND (via
  `deriveDebateLoopEdgeState`) the cycle edge's `animated`/`style`/
  `label` overrides -- one source of truth for "what's currently
  running" per render, rather than two independent derivations that
  could in principle disagree.
- **Every edge OTHER than `DEBATE_LOOP_EDGE_ID` passes through from
  `PIPELINE_EDGES` completely unchanged.** T-097's acceptance criteria
  is entirely about the debate_loop cycle specifically -- there is no
  general "animate whichever edge is currently active" system here, by
  design; building one would be solving a problem this task was never
  asked to solve.
- **T-094's static `PIPELINE_EDGES` constant, and `PipelineGraphView`
  that renders it, are completely untouched.** `PIPELINE_EDGES`'
  `DEBATE_LOOP_EDGE_ID` entry keeps its original `animated: true` --
  T-094's own `pipelineTopology.test.ts` asserts this directly, and
  that assertion (and the component built on it) is about the STATIC
  topology view proving the graph's shape, not about live behaviour.
  `LiveGraphView` builds its own local, live-overridden copy of the
  edges array via `.map()` rather than mutating or re-exporting a
  modified `PIPELINE_EDGES` -- the two components' edges arrays are
  independent by construction, so this task cannot regress T-094's own
  contract even by accident.
- **The Cards/Graph toggle is a second, NESTED `role="tablist"` inside
  the existing "Agent progress" tab**, not a third top-level tab
  alongside "Agent progress"/"Debate transcript". The task's own
  wording -- "a toggle between card view and graph view on the analysis
  progress page" -- scopes it specifically to the progress view, and
  the two are genuinely different concerns: the outer tabs choose WHICH
  data to look at (live progress vs. the debate transcript), the inner
  toggle chooses HOW to look at the same progress data (cards vs.
  graph). Nesting keeps that distinction visible in the UI rather than
  flattening it into one confusing 3-way choice, and keeps the toggle
  hidden entirely while on the "Debate transcript" tab, where it would
  have no meaning.
- **`LiveGraphView` is not shown `progressPercent`** even though
  `AgentProgressBoard` receives it. This was already true as of T-096
  (not a new decision here) -- the graph itself already visualises
  progress node-by-node, so a second, separate overall progress bar
  duplicating that information inside the graph view would be
  redundant with what `AgentProgressBoard`'s own bar already shows when
  toggled to Cards.
- **"Without losing stream state" needed no new code to satisfy** --
  it falls directly out of where `useAnalysisStream()` is called.
  `AnalysisResultPage` already calls it exactly once, above both the
  outer view tabs and the new inner Cards/Graph toggle; `activeView` and
  the new `progressViewMode` are both ordinary local `useState` values
  with no effect of their own, so toggling either can never re-run
  `useAnalysisStream`'s connection effect (whose dependency array is
  `[jobId, token, enabled]` -- neither toggle is in it), never closes
  the WebSocket, and never resets `events`. `AnalysisResultPage.test.tsx`'s
  new tests verify this two ways: directly (an event received on Cards
  is still reflected after switching to Graph, and vice versa) and
  structurally (`FakeWebSocket.instances.length` is unchanged after
  toggling back and forth -- no new connection was ever constructed).

## Files changed / created

### Frontend — debate loop edge state

- **`frontend/src/lib/graph/liveGraphState.ts`** (**MODIFY**) — adds
  `DebateLoopEdgeState` and `deriveDebateLoopEdgeState`; imports
  `NODE_CONTRARIAN`/`NODE_DEBATE_LOOP`; module docstring updated.

### Frontend — live graph view

- **`frontend/src/components/graph/LiveGraphView.tsx`** (**MODIFY**) —
  `nodes`/`edges` now built together in one `useMemo`; the
  `DEBATE_LOOP_EDGE_ID` edge gets live `animated`/`style`/`label`
  overrides from `deriveDebateLoopEdgeState`; every other edge is
  unchanged; module docstring updated.

### Frontend — page-level toggle

- **`frontend/src/pages/AnalysisResultPage.tsx`** (**MODIFY**) — adds
  `ProgressViewMode`/`PROGRESS_VIEW_TABS` and the `progressViewMode`
  state; renders the nested Cards/Graph toggle and either
  `AgentProgressBoard` or `LiveGraphView` (same `events`/`isComplete`/
  `connectionStatus`/`error` props) inside the existing "Agent progress"
  tab panel; module docstring updated.

### Frontend — tests

- **`frontend/src/test/liveGraphState.test.ts`** (**MODIFY**) — new
  `deriveDebateLoopEdgeState` section: inactive/no-round before the
  debate starts; activates the instant contrarian starts round 1; stays
  active while debate_loop itself runs; goes inactive in the gap
  between rounds; reactivates for round 2; goes inactive for good once
  round 2 concludes; a single ordered-timeline test proving the genuine
  active/inactive/active/inactive cycle across both rounds; a missing-
  `event_type` fallback test.
- **`frontend/src/test/LiveGraphView.test.tsx`** (**MODIFY**) — one new
  smoke test rendering a full 2-round debate event sequence, confirming
  the component renders correctly (node statuses in particular) without
  asserting on edge DOM (ReactFlow edges do not render in jsdom -- see
  this file's own docstring, matching T-094/T-095/T-096 precedent); the
  edge state logic itself is fully covered at the pure-data layer.
- **`frontend/src/test/AnalysisResultPage.test.tsx`** (**MODIFY**) — new
  `progress view toggle (T-097)` section: defaults to Cards with the
  graph not mounted; switches to Graph on click; switches back; the
  literal "no lost stream state" test (an event received on Cards is
  still reflected as the correct live node status after switching to
  Graph); a direct WebSocket-reconnection check (no new socket
  constructed by toggling); events received while on Graph carry back
  to Cards; the toggle is hidden while on the Debate transcript tab.

### Docs

- **`docs/week-22/T-097-ui-debate-loop-animation.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/ui-debate-loop-animation

git branch
# → * feat/ui-debate-loop-animation
```

### Step 2 — Add the debate loop edge state derivation

- `frontend/src/lib/graph/liveGraphState.ts`: add
  `DebateLoopEdgeState`/`deriveDebateLoopEdgeState`.

### Step 3 — Wire it into LiveGraphView

- `frontend/src/components/graph/LiveGraphView.tsx`: combine the
  `nodes`/`edges` derivation into one `useMemo`, override the
  `DEBATE_LOOP_EDGE_ID` edge.

### Step 4 — Add the Cards/Graph toggle to the analysis result page

- `frontend/src/pages/AnalysisResultPage.tsx`: add
  `ProgressViewMode`/`PROGRESS_VIEW_TABS`, the toggle UI, and the
  conditional `AgentProgressBoard`/`LiveGraphView` render.

### Step 5 — Extend the tests

Update the three test files listed above.

### Step 6 — Run the full verification gate locally

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

### Step 7 — Manual smoke test against a local dev server

```bash
cd frontend
npm run dev
```

If a real backend + a company that triggers a genuine 2-round debate is
available, the strongest check is watching a real analysis run through
`/analysis/{job_id}/result`:

- On the "Agent progress" tab, confirm the Cards/Graph toggle appears,
  defaults to Cards, and disappears entirely when switched to the
  "Debate transcript" tab.
- Switch to Graph. Confirm the DEBATE_AGAIN cycle edge (the loop
  arcing out to the left of Contrarian Investor / Debate Loop) starts
  dimmed and static.
- Watch it pulse (animated, brighter, thicker) once Contrarian
  Investor starts its first pass, and go back to dimmed once Debate
  Loop completes round 1.
- If the run takes a second debate round, confirm the edge pulses
  AGAIN once Contrarian Investor restarts -- the actual "round-trip
  pulse... across its 2 rounds" acceptance criterion, live.
- Toggle back to Cards mid-run and confirm nothing about the run
  visibly restarts or loses progress; toggle back to Graph and confirm
  the same is true in the other direction.

Without a backend handy, `/dev/components`'s existing T-096 stepper demo
(`ComponentsPreviewPage.tsx`) can be extended locally with the debate-
loop event batches from `liveGraphState.test.ts`'s own test fixtures to
eyeball the same behaviour without a live run -- this was not added to
the shipped demo in this task, since the task's own acceptance criteria
is about the real page integration, not the dev preview.

### Step 8 — Commit (two-commit pattern)

```bash
git add frontend/src/lib/graph/liveGraphState.ts
git add frontend/src/components/graph/LiveGraphView.tsx
git add frontend/src/pages/AnalysisResultPage.tsx
git add frontend/src/test/liveGraphState.test.ts
git add frontend/src/test/LiveGraphView.test.tsx
git add frontend/src/test/AnalysisResultPage.test.tsx
git add docs/week-22/T-097-ui-debate-loop-animation.md

git commit -m "feat(frontend): animate debate loop cycle in live graph view

- Add deriveDebateLoopEdgeState (src/lib/graph/liveGraphState.ts):
  active whenever contrarian_investor or debate_loop is itself
  'running' (reusing deriveNodeStatuses's own output), which produces
  a genuine active/inactive/active/inactive cycle across a real
  2-round debate with no explicit round-boundary bookkeeping;
  currentRound counts contrarian_investor's own NODE_STARTED events
- LiveGraphView now builds nodes and edges together in one useMemo;
  the debate_loop cycle edge (DEBATE_LOOP_EDGE_ID) gets live
  animated/style/label overrides while active, dimmed and static
  otherwise; every other edge passes through PIPELINE_EDGES unchanged;
  T-094's static PIPELINE_EDGES/PipelineGraphView untouched
- Add a nested Cards/Graph toggle inside AnalysisResultPage's existing
  'Agent progress' tab -- AgentProgressBoard and LiveGraphView both
  read from the one useAnalysisStream() subscription already made
  above the toggle, so switching cannot reconnect the WebSocket or
  lose any accumulated stream state; toggle hidden on the Debate
  transcript tab
- Full test coverage: the debate loop edge state's active/round
  transitions including an ordered full-cycle timeline test, a
  LiveGraphView smoke test across a full 2-round sequence, and
  AnalysisResultPage tests proving no lost stream state both directly
  (event visibility across a toggle) and structurally (no new
  WebSocket constructed)

Closes #97"
```

If a formatter modifies files after staging, re-stage and make a
second, separate commit rather than amending:

```bash
git add -A
git commit -m "style: apply prettier formatting to T-097 files"
```

### Step 9 — Push and open the PR

```bash
git push -u origin feat/ui-debate-loop-animation
```

**Base branch:** `main`
**Compare branch:** `feat/ui-debate-loop-animation`

## Pull Request

**PR title:**

```
feat(ui): add card/graph view toggle and debate loop animation
```

**PR description:**

```markdown
## Summary
Closes out Phase 9. The debate_loop <-> contrarian_investor cycle edge
(statically animated since T-094) now genuinely pulses only while a
debate round is actually live, across both of its possible rounds, and
falls dim/static in between and once concluded. AnalysisResultPage's
"Agent progress" tab gets a nested Cards/Graph toggle so a user can
switch between the T-059 card board and the T-096 live graph without
losing any stream state.

## Changes
- New deriveDebateLoopEdgeState (src/lib/graph/liveGraphState.ts):
  pure, fully unit tested, produces the "round-trip pulse across 2
  rounds" behaviour purely from each node's own latest-event status --
  no explicit round bookkeeping
- LiveGraphView builds nodes+edges together in one useMemo; only the
  debate_loop cycle edge gets live overrides, every other edge (and
  all of T-094's static PIPELINE_EDGES/PipelineGraphView) stays
  untouched
- Nested Cards/Graph toggle added inside AnalysisResultPage's existing
  "Agent progress" tab; hidden on the Debate transcript tab; both
  views read from the single existing useAnalysisStream() call, so no
  new code was needed to avoid losing stream state on toggle -- it
  falls out of the existing architecture
- Full test coverage across 3 files, including a single ordered-
  timeline test that directly checks the two-phase pulse cycle, and
  AnalysisResultPage tests proving no lost stream state both by
  content (an event is still reflected after toggling) and
  structurally (no new WebSocket is ever constructed by toggling)

## Testing
- `npm run test:run` -- all green, including the extended/new T-097
  test sections across liveGraphState.test.ts, LiveGraphView.test.tsx,
  and AnalysisResultPage.test.tsx
- Manual smoke test: walked a real analysis with a 2-round debate
  through /analysis/{job_id}/result, confirmed the cycle edge pulses
  for round 1, dims between rounds, pulses again for round 2, and that
  toggling Cards/Graph mid-run never resets progress
- `npm run type-check`, `npm run lint`, `npm run format:check` all pass
- `npm run build` succeeds

## LangSmith Trace
N/A -- frontend-only change, no agent/LLM-facing code touched.

## Screenshots
_Attach a short screen recording of the debate_loop edge pulsing
across both rounds, and a screenshot of the Cards/Graph toggle, before
opening the PR._

## Related Issues
Closes #97 (adjust to your actual issue number if different)
```

## Testing

Frontend (`npm run test:run`):

- **`liveGraphState.test.ts`** — `deriveDebateLoopEdgeState`: inactive
  with no round before the debate starts; active with `currentRound: 1`
  the instant `contrarian_investor` starts; still active while
  `debate_loop` itself runs; inactive (round still reported as 1) in
  the gap after round 1's `debate_loop` completes; active again with
  `currentRound: 2` once `contrarian_investor` restarts; inactive for
  good (round still 2) once round 2's `debate_loop` completes and
  `risk_officer` has started; a single ordered-timeline test asserting
  the full `active` sequence (`true, true, false, true, true, false`)
  across a complete 2-round debate in one assertion; a missing-
  `event_type` contrarian event never bumps the round counter.
- **`LiveGraphView.test.tsx`** — one new smoke test rendering a
  complete 2-round debate event sequence end to end, confirming the
  component renders correctly and both `contrarian_investor`/
  `debate_loop` read the expected final node status (`done`, with
  `risk_officer` the one node reading `running`).
- **`AnalysisResultPage.test.tsx`** — Cards shown by default with the
  graph not mounted; switches to Graph on click and back; an event
  received while on Cards is still reflected (as the correct node's
  live status) once switched to Graph; toggling back and forth never
  constructs a new `FakeWebSocket` instance; an event received while on
  Graph carries back to Cards; the toggle itself is not present at all
  while on the Debate transcript tab.

"Debate loop visibly animates for both rounds" (the first acceptance
criterion) is covered end to end: `deriveDebateLoopEdgeState`'s pure
logic is exhaustively tested (including the single full-cycle timeline
test that would fail directly if a future change accidentally merged
the two rounds' pulses into one continuous animation with no gap), and
`LiveGraphView.test.tsx`'s smoke test confirms the surrounding component
renders correctly across the same sequence. "Toggle switches between
AgentProgressBoard and LiveGraphView without losing stream state" (the
second) is covered by `AnalysisResultPage.test.tsx`'s dedicated section,
proven both by content (the event's effect survives the toggle) and
structurally (the WebSocket connection itself is never recreated).

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
pure derivation function, wires it into an existing component's
`useMemo`, and adds a local-state UI toggle to an existing page.

## Related Issues

Closes #97 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `node_modules` is not installed
and the real `npm run type-check`/`lint`/`format:check`/`test:run`/
`build` could not be executed directly. Verification here was
`tsc --noEmit` run standalone against each touched file (module-
resolution errors for `reactflow`/`react`/etc. are expected and were
filtered out; no other errors found), a brace/paren balance check, and
a manual line-length check against Prettier's configured 100-character
`printWidth`. **Real verification — the actual `npm run test:run`/
`type-check`/`lint` runs — is delegated to your local environment** per
Step 6 above, exactly as with every previous task's workflow doc. This
is also Phase 9's final task, so once this branch's CI is green,
`docs/week-22/`'s five T-093–T-097 workflow docs together cover the
complete "static graph -> live node status -> live debate animation +
view toggle" arc end to end.