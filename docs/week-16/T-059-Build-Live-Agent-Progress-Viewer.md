# T-059 -- Build Live Agent Progress Viewer

**Phase:** 6 -- React Frontend
**Week:** 16
**Branch:** `feat/ui-agent-progress`
**Task status:** Complete

---

## Overview

T-059 gives `AnalysisResultPage` (T-057's placeholder, the redirect
target of T-058's "Start Analysis" button) its real first job: connect
to the already-existing `WS /api/v1/analysis/{job_id}/stream`
(`useAnalysisStream`, T-049) and render one animated card per committee
agent, transitioning Waiting -> Thinking -> Complete as real events
arrive.

**Acceptance criteria (all must pass):**

- Cards animate in real time
- Each agent card shows its output on completion
- No race conditions

**The one thing worth understanding before reading the code**

`backend.services.ws_broadcaster.AgentStreamEvent`'s own docstring says
`agent` is _"the LangGraph node name that just **completed**"_ -- there
is no corresponding "node X has **started**" event. The backend only
ever announces completions. That means "Thinking" cannot be read off
the wire; it has to be **inferred**. This viewer infers it from round
order, mirroring the exact three-round grouping
`CommitteeSection.tsx` (T-055) already established on the marketing
page: once every agent in every earlier round has a completion event,
every not-yet-completed agent in the current round is shown as
"Thinking". This is documented in three places in the code
(`src/lib/agentProgress.ts`'s module docstring is the canonical one) so
nobody mistakes "Thinking" for a literal signal the backend sent.

**In scope:** `src/lib/agentProgress.ts` (pure derivation logic),
`AgentCard`, `TypingIndicator`, `AgentProgressBoard`, wiring all of it
into `AnalysisResultPage`, a new test file for `useAnalysisStream`
itself (T-049's hook had none), and removing the T-049 throwaway demo
component it explicitly said Phase 6 should delete.

**Explicitly out of scope:**

- The full verdict panel, bull/bear case, and Investment Memo -- T-061.
  `AnalysisResultPage` shows a "what happens next" note once the job
  terminates, not the memo itself.
- Visually round-tripping the debate loop if Risk Officer/Contrarian
  Investor fire a second event for a second debate round -- a card
  always shows its **latest** output and stays "Complete" rather than
  regressing to "Thinking"; see `agentProgress.ts`'s docstring for the
  reasoning.
- Cards for non-committee pipeline nodes (`planner`, `research_join`,
  `error_handler`, `sentiment_escalation`, `debate_loop`,
  `report_generator`, `pdf_export`) -- the task description and
  `CommitteeSection.tsx` both scope "agent" to the 8 committee members;
  the other 7 graph nodes exist in the raw event stream but are not
  rendered as their own cards.

---

## What Was Built

### `src/lib/agentProgress.ts` (new)

`deriveAgentCards(events, isComplete)` -- a pure function, no React, no
timers, no subscriptions. Given the exact same inputs it always
produces the exact same output, which is what makes "no race
conditions" directly testable: two different arrival orders of the
same events must produce an identical board (see
`agentProgress.test.ts`'s explicit forward/reverse-order test). Per
agent: `"complete"`/`"failed"` once its own event arrives (using that
event's `output_preview`), `"thinking"` once every earlier round has
fully completed, `"waiting"` otherwise, and `"skipped"` if the job has
already terminated (`isComplete`) but this agent never got a turn (an
early pipeline failure, most commonly) -- so a card never spins on
"Waiting" forever after the job is already over.

### `src/components/progress/TypingIndicator.tsx` (new)

Three dots, `animate-bounce` with a staggered `animationDelay`, wrapped
in `role="status" aria-label="Thinking"` so a screen reader announces
it once rather than three unlabelled bouncing elements. Pure CSS --
costs nothing to leave running for as long as a card stays "Thinking".

### `src/components/progress/AgentCard.tsx` (new)

Seat number, display name, a state badge, and body content that
depends on state: `TypingIndicator` + "Working…" when thinking, the
`output_preview` when complete/failed, plain copy for waiting/skipped.
Top-border accent colour reuses the exact hex values
`CommitteeSection.tsx` (T-055) already assigned per round
(`#1D4ED8`/`#B91C1C`/`#065F46`), so this card and its marketing-page
counterpart read as the same agent.

### `src/components/progress/AgentProgressBoard.tsx` (new)

Composes the 8 `AgentCard`s into the same three round groupings
(`CommitteeSection.tsx`'s grid layout, T-055), plus an overall
`ProgressBar` (reusing `progress_percent` from the stream -- no new
progress math) and a connection-status line covering
`connecting`/`open`/`closed`/`error`. Takes `events`/`isComplete`/etc.
as plain props rather than calling `useAnalysisStream` itself, which is
what makes it fully testable with hand-built event arrays and zero
WebSocket mocking (`AgentProgressBoard.test.tsx`).

### `src/pages/AnalysisResultPage.tsx` (rewritten)

Calls `useAnalysisStream({ jobId, token: accessToken, enabled: ... })`
and renders `AgentProgressBoard`. Once `isComplete` is true, shows
either a completion note (pointing at T-061 for the real memo) or a
failure note (using the terminal event's `output_preview` as the
explanation) -- distinguished by the last event's `status`.

### Removed: `src/components/AgentProgressDemo.tsx`

Its own T-049 docstring said exactly this: _"Phase 6 can delete or
replace this file outright once the real dashboard lands."_ Confirmed
nothing else imported it before removing. `useAnalysisStream.ts`, the
part that docstring called out as "the reusable part worth keeping", is
untouched and is exactly what this task builds on.

### Testing

`frontend/src/test/`:

- **`useAnalysisStream.test.ts`** (new -- T-049's hook had no test file
  before this task) -- a `FakeWebSocket` class substituted via
  `vi.stubGlobal` drives it deterministically: correct connection URL
  (jobId + token), events append in arrival order, `isComplete` flips
  on the `is_final` event, the 4401 application-specific close code
  produces a readable error, a malformed message doesn't crash, and
  the socket closes on unmount.
- **`agentProgress.test.ts`** -- the core of this task's "no race
  conditions" claim: one card per roster entry; Round 1 starts
  "thinking" immediately; later rounds start "waiting"; an agent's own
  event marks it complete/failed with that event's output; Round
  2/Round 3 promotion only after every earlier round's agents have all
  completed; **forward vs. reverse event order within the same round
  produces an identical result**; not-yet-reached agents become
  "skipped" once the job terminates; a completed agent is never
  reverted to "skipped"; a second event for the same agent updates its
  output without regressing its state.
- **`AgentCard.test.tsx`** -- each of the 5 states renders its label
  and the right body content.
- **`TypingIndicator.test.tsx`** -- accessible `status` role, exactly 3
  dots.
- **`AgentProgressBoard.test.tsx`** -- all three round headings, all 8
  cards, the overall percentage, each connection-status message, a
  completed agent's output reflected on its card, and the error banner.
- **`AnalysisResultPage.test.tsx`** (rewritten) -- connects with the
  route's `jobId` and the in-memory `accessToken`; renders the full
  board; shows the completion note on a successful final event and the
  failure note (with the backend's message) on a failed one; shows
  neither while still running; reflects an in-progress agent's output
  live.

### CI

No workflow changes, no new dependencies. `useAnalysisStream.ts`
(T-049) and the WebSocket backend it consumes (T-049 backend side) are
both unchanged -- this task is pure frontend consumption plus one new
test file for a hook that already existed.

---

## How It Was Tested / Verified

Backend is untouched -- no backend commands needed.

Frontend, from `frontend/`:

```bash
cd frontend
npm ci                # no new dependencies this task

npm run lint:fix
npm run format

npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

Manual end-to-end verification (needs the backend running):

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

1. `cd frontend && npm run dev`, log in, go to `/analysis`, pick a
   company, and click "Start Analysis" (see T-058's doc for the
   sample-PDF walkthrough if you want to test with a document attached
   too).
2. Confirm you land on `/analysis/{job_id}/result` and the connection
   line shows "Connecting to the committee…", then "Live — streaming
   agent updates".
3. Watch the four Round 1 cards (Fundamental Analyst, Technical
   Analyst, News Sentiment Agent, Macro Economist) show the animated
   typing-dots indicator together, then flip to "Complete" with real
   output text as each one finishes -- confirm they don't all have to
   finish in the same order you'd expect (parallel execution means
   whichever agent's API call responds first completes first).
4. Confirm Round 2's cards (Risk Officer, Contrarian Investor,
   Valuation Agent) stay on "Waiting" until all four Round 1 cards are
   "Complete", then flip to "Thinking" together.
5. Confirm the Portfolio Manager card stays "Waiting" until Round 2 is
   fully done, then shows its own output once the pipeline finishes.
6. Confirm the overall progress bar advances as events arrive and the
   page shows "Analysis complete." once the final event lands.
7. To see the failure path: stop the backend mid-run (or use an invalid
   ticker if you have one handy) and confirm the page shows "This
   analysis did not complete." with a real error message, and that any
   committee member that never got a turn shows "Skipped" rather than
   spinning on "Waiting"/"Thinking" forever.
8. Refresh the page mid-run: confirm the socket reconnects (a fresh
   `useAnalysisStream` effect run) and does not duplicate any
   already-rendered card state.

---

## Git Workflow (exact commands)

```bash
# 0) Start from an up-to-date main
git checkout main
git pull origin main

# 1) Create the feature branch
git checkout -b feat/ui-agent-progress

# 2) (do the work -- files listed above)

# 3) Verify (see "How It Was Tested" above)
cd frontend
npm ci
npm run lint:fix && npm run format
npm run type-check && npm run lint && npm run format:check
npm run test:run && npm run build
cd ..

# 4) Stage and commit (re-stage after auto-fixers ran)
git add frontend/src/lib/agentProgress.ts \
        frontend/src/components/progress/ \
        frontend/src/pages/AnalysisResultPage.tsx \
        frontend/src/test/useAnalysisStream.test.ts \
        frontend/src/test/agentProgress.test.ts \
        frontend/src/test/AgentCard.test.tsx \
        frontend/src/test/TypingIndicator.test.tsx \
        frontend/src/test/AgentProgressBoard.test.tsx \
        frontend/src/test/AnalysisResultPage.test.tsx \
        docs/week-16/T-059-Build-Live-Agent-Progress-Viewer.md
git rm frontend/src/components/AgentProgressDemo.tsx
git commit -m "feat(progress): build live agent progress viewer with animated cards"

# If pre-commit reformats anything, re-stage and recommit (two-commit pattern):
#   git add -A && git commit -m "feat(progress): build live agent progress viewer with animated cards"

# 5) Push and open the PR
git push -u origin feat/ui-agent-progress
```

**Commit message:**

```
feat(progress): build live agent progress viewer with animated cards
```

**PR title:**

```
feat(progress): implement live Agent Progress viewer (Waiting -> Thinking -> Complete)
```

**PR description:**

```markdown
## Summary

Gives AnalysisResultPage its real first job: connect to the existing
WS /api/v1/analysis/{job_id}/stream (useAnalysisStream, T-049) and
render one animated card per committee agent, transitioning
Waiting -> Thinking -> Complete as real completion events arrive.
Removes the T-049 throwaway demo component (AgentProgressDemo.tsx),
whose own docstring said Phase 6 should delete it once this landed.
See the linked doc (docs/week-16/T-059-Build-Live-Agent-Progress-
Viewer.md) for why "Thinking" has to be inferred from round order
rather than read directly off the wire -- the backend only emits
completion events, never "started" events.

## Changes

- `src/lib/agentProgress.ts` (new) -- pure Waiting/Thinking/Complete/
  Failed/Skipped derivation from the raw event stream
- `src/components/progress/{TypingIndicator,AgentCard,
AgentProgressBoard}.tsx` (new)
- Rewrites `src/pages/AnalysisResultPage.tsx` to render the live board
  and a completion/failure summary
- Removes `src/components/AgentProgressDemo.tsx` (superseded)
- New `src/test/useAnalysisStream.test.ts` -- T-049's hook had no test
  file before this task
- No new dependencies

## Testing

- [x] Unit tests added / updated -- 6 new/rewritten test files,
      including an explicit forward-vs-reverse event-order test in
      agentProgress.test.ts that is the direct check for the "no race
      conditions" acceptance criterion
- [x] Integration tests pass (backend untouched)
- [x] Manual smoke test performed against a running backend -- see the
      8-step walkthrough in the doc (round-by-round card transitions,
      overall progress, completion and failure paths, mid-run refresh)

`npm run type-check`, `npm run lint`, `npm run format:check`,
`npm run test:run`, and `npm run build` all pass locally.

## LangSmith Trace

n/a -- no agent code touched.

## Screenshots

<paste terminal output of the passing checks, plus a screenshot of the
board mid-run (some cards Thinking, some Complete) and one screenshot
of the completed state>

## Related Issues

Closes #<issue-number>
```

---

## Notes for the Next Task

- **T-061 (Analysis Results page)** replaces `AnalysisResultPage`'s
  post-`isComplete` note with the real verdict panel, bull/bear case,
  and Investment Memo download. Keep `AgentProgressBoard` rendering
  above it (or collapse it once complete) rather than replacing it
  outright -- a user who watched the committee work still benefits from
  seeing the trail that led to the verdict.
- **The debate loop's second-pass visualization is still unaddressed.**
  If Risk Officer/Contrarian Investor firing twice (two debate rounds)
  ever needs its own visual treatment (e.g. "Round 2 of 2" on the
  card), that is a deliberate scope decision to make explicitly, not an
  oversight -- see `agentProgress.ts`'s docstring for exactly what was
  skipped and why.
- Next per the master task list: **T-060 -- Build Debate Viewer**
  (timeline/chat UI showing agents responding to each other in order,
  colour-coded per agent, expandable messages, round indicators), then
  **T-061 -- Build Analysis Results page**.
