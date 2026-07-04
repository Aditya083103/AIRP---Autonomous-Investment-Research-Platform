# T-060 — Build Debate Viewer

**Phase 6 — React Frontend | Week 17**
**Branch:** `feat/ui-debate-viewer`
**Base branch:** `main`

---

## 1. Task summary

Build a timeline/chat UI that shows the 8-agent committee "speaking" in
order, colour-coded per agent, with expandable messages and round
indicators. This is a second, transcript-style view of the exact same
`AgentStreamEvent` stream `useAnalysisStream` (T-049) already exposes —
no new backend contract is introduced.

**Acceptance criteria:**

- [x] All debate rounds visible (all 3 round sections always render, even empty)
- [x] Agent colours consistent (one stable accent per committee seat)
- [x] Messages expand/collapse (long messages collapse by default with a toggle)
- [x] Works on mobile (single-column vertical timeline, no fixed-width grid)

---

## 2. Files added / changed

```
frontend/src/lib/debateTranscript.ts                 (new)
frontend/src/components/debate/DebateMessageCard.tsx (new)
frontend/src/components/debate/DebateViewer.tsx       (new)
frontend/src/pages/AnalysisResultPage.tsx             (modified — adds tab switch)
frontend/src/test/debateTranscript.test.ts            (new)
frontend/src/test/DebateMessageCard.test.tsx          (new)
frontend/src/test/DebateViewer.test.tsx               (new)
frontend/src/test/AnalysisResultPage.test.tsx         (modified — adds tab tests)
docs/week-17/T-060-Build-Debate-Viewer.md             (new, this file)
```

### Design notes

- **`debateTranscript.ts`** is the pure-function counterpart to
  `lib/agentProgress.ts` (T-059). Where `agentProgress.ts` collapses
  each agent down to its _latest_ event (for a progress card),
  `debateTranscript.ts` keeps **every** event as its own message, in
  arrival order — a debate-loop agent (Risk Officer, Contrarian
  Investor) that speaks twice must appear as two transcript entries,
  not overwrite itself. Both modules read the same
  `COMMITTEE_ROSTER` so seat numbers, display names, and round
  assignment never drift between the progress board and the debate
  viewer.
- **Colour-per-agent** is a dedicated palette (`AGENT_ACCENTS` in
  `DebateMessageCard.tsx`) distinct from `AgentCard.tsx`'s
  per-_round_ accent — the whole point of the debate viewer is telling
  8 individual voices apart _within_ a round, so agents sharing a
  round must not share a colour the way they intentionally do on the
  progress board.
- **Expand/collapse** triggers only past a 160-character threshold
  (`PREVIEW_CHAR_LIMIT`) — short previews render in full with no
  redundant toggle.
- **Round indicators** reuse the same 3-round structure
  (`COMMITTEE_ROSTER`'s `round: 1 | 2 | 3`) as `AgentProgressBoard`,
  labelled "Round 1 — Research findings", "Round 2 — Debate &
  challenge", "Round 3 — Final decision". All three sections always
  render; an empty round shows "No messages yet in this round."
  instead of disappearing, matching the acceptance criterion.
- **Mobile:** the viewer is a single vertical flex column with no
  fixed-width or multi-column grid, so it reflows correctly at any
  viewport width without extra breakpoint classes.
- **Wiring:** `AnalysisResultPage.tsx` gained a lightweight two-tab
  switch ("Agent progress" / "Debate transcript") over local
  `useState`, defaulting to the existing "Agent progress" view so all
  pre-existing T-059 tests keep passing unmodified.

---

## 3. Full workflow — checkout to PR

### 3.1 Sync `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/ui-debate-viewer
```

### 3.2 Add the new files

Copy the following into the working tree at the exact paths shown,
overwriting `frontend/src/pages/AnalysisResultPage.tsx` and
`frontend/src/test/AnalysisResultPage.test.tsx` in place:

```
frontend/src/lib/debateTranscript.ts
frontend/src/components/debate/DebateMessageCard.tsx
frontend/src/components/debate/DebateViewer.tsx
frontend/src/pages/AnalysisResultPage.tsx
frontend/src/test/debateTranscript.test.ts
frontend/src/test/DebateMessageCard.test.tsx
frontend/src/test/DebateViewer.test.tsx
frontend/src/test/AnalysisResultPage.test.tsx
docs/week-17/T-060-Build-Debate-Viewer.md
```

### 3.3 Verify locally before committing

Run the full frontend gate exactly as CI does — every one of these
must pass before pushing:

```bash
cd frontend

npm ci
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

If `format:check` fails, run `npm run format` once to let Prettier
fix whitespace/quote-style, then re-run `format:check`.

If `lint` reports `import/order` issues, sort the flagged import
block alphabetically within its group (builtin → external → internal
`@/...` → relative) — this is the one rule most likely to catch a
manually-typed import list.

### 3.4 Commit (two-commit pattern: content, then any auto-fixes)

```bash
git add frontend/src/lib/debateTranscript.ts \
        frontend/src/components/debate/DebateMessageCard.tsx \
        frontend/src/components/debate/DebateViewer.tsx \
        frontend/src/pages/AnalysisResultPage.tsx \
        frontend/src/test/debateTranscript.test.ts \
        frontend/src/test/DebateMessageCard.test.tsx \
        frontend/src/test/DebateViewer.test.tsx \
        frontend/src/test/AnalysisResultPage.test.tsx \
        docs/week-17/T-060-Build-Debate-Viewer.md

git commit -m "feat(frontend): add debate viewer timeline (T-060)"

# If a formatter/linter --fix step changed anything after the first
# commit, stage and recommit:
git add -A
git commit -m "chore(frontend): apply lint/format fixes for T-060" --allow-empty
```

Use `git commit --no-verify` only if Windows App Control blocks a
pre-commit hook shim (per the project's documented Windows
workaround) — CI's Linux runners remain the real enforcement gate.

### 3.5 Push and open the PR

```bash
git push -u origin feat/ui-debate-viewer
```

Then open a PR from `feat/ui-debate-viewer` → `main` (squash and
merge) with the title and description below.

---

## 4. Pull Request

### Title

```
feat(frontend): add Debate Viewer timeline (T-060)
```

### Description

```markdown
## Summary

Adds the Debate Viewer — a timeline/chat UI that shows the 8-agent
committee "speaking" in arrival order, colour-coded per agent, grouped
into the same 3 execution rounds AgentProgressBoard uses, with
expand/collapse for long messages. Wired into AnalysisResultPage
behind a new "Agent progress" / "Debate transcript" tab switch.

## Changes

- Add `lib/debateTranscript.ts`: pure derivation of an ordered,
  per-round transcript from the existing `AgentStreamEvent[]` stream
  (keeps every event, unlike `agentProgress.ts`'s "latest per agent"
  view — needed so a debate-loop agent's multiple turns all show up).
- Add `components/debate/DebateMessageCard.tsx`: single expandable
  message bubble with a per-agent accent colour, avatar initials, and
  a status pill.
- Add `components/debate/DebateViewer.tsx`: renders all 3 round
  sections (always visible, even empty) with per-round message lists.
- Update `pages/AnalysisResultPage.tsx`: adds a lightweight tab switch
  between the existing live progress board and the new debate
  transcript, both reading the same `useAnalysisStream` event array.
  Defaults to "Agent progress" so existing behaviour is unchanged.
- Add unit/component tests for all three new modules plus two new
  tab-switch tests in `AnalysisResultPage.test.tsx`.

## Testing

- `npm run type-check` — passes
- `npm run lint` (`--max-warnings 0`) — passes
- `npm run format:check` — passes
- `npm run test:run` — passes, including:
  - `debateTranscript.test.ts` — transcript derivation, round
    filtering, non-committee node filtering, multi-turn agents
  - `DebateMessageCard.test.tsx` — per-agent colour, expand/collapse
  - `DebateViewer.test.tsx` — all rounds always render, per-round
    empty state, debate-loop agents shown as multiple messages
  - `AnalysisResultPage.test.tsx` — default tab, tab switch, stream
    events carried into the debate tab (all pre-existing T-059 tests
    left unmodified and passing)
- `npm run build` — passes

## LangSmith Trace

N/A — frontend-only change, no agent/graph behaviour touched.

## Screenshots

_Add a screenshot of the "Debate transcript" tab with a few completed
agent events, and one at mobile width (375px), before merging._

## Related Issues

Closes #T-060
```

---

## 5. Post-merge checklist

- [ ] Confirm CI's `frontend` job and `ci-pass` summary job are both green on the PR
- [ ] Delete `feat/ui-debate-viewer` after squash-merge
- [ ] Update local `main`: `git checkout main && git pull origin main`
- [ ] Next session: T-061 (Investment Memo viewer / verdict panel), Phase 6, Week 17
