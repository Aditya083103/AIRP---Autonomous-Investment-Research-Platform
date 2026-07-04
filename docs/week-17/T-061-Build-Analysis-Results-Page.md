# T-061 — Build Analysis Results Page

**Phase 6 — React Frontend | Week 17**
**Branch:** `feat/ui-results`
**Base branch:** `main`

---

## 1. Task summary

Build the final Investment Memo results view for a completed analysis:
a verdict panel (BUY/HOLD/SELL with an animated conviction gauge),
bull case vs bear case side-by-side, a key risks list, price target,
and time horizon — every field on `InvestmentDecisionResponse`
(`GET /api/v1/analysis/{job_id}/result`, T-050) rendered somewhere on
the page.

**Acceptance criteria:**

- [x] All `InvestmentDecision` fields displayed (verdict, conviction
      score, price target, time horizon, executive summary, investment
      thesis, bull case, bear case, risk summary, valuation summary,
      key risks, key catalysts, contrarian response, debate rounds
      used, agent weights, company/ticker/generated-at)
- [x] Conviction gauge animates (semicircular SVG arc, animates from
      empty to the real score on mount via a CSS `stroke-dashoffset`
      transition)
- [x] Responsive layout (every panel uses a `grid` that collapses to a
      single column below the `md` breakpoint; no fixed-width elements)

---

## 2. Files added / changed

```
frontend/src/types/analysis.ts                       (modified — adds InvestmentDecisionResponse)
frontend/src/api/analysis.ts                          (modified — adds fetchAnalysisResult)
frontend/src/hooks/useAnalysisResult.ts                (new)
frontend/src/components/results/ConvictionGauge.tsx    (new)
frontend/src/components/results/VerdictPanel.tsx       (new)
frontend/src/components/results/BullBearPanel.tsx      (new)
frontend/src/components/results/KeyRisksList.tsx       (new)
frontend/src/components/results/MemoSection.tsx        (new)
frontend/src/components/results/AgentWeightsPanel.tsx  (new)
frontend/src/components/results/ResultsPanel.tsx       (new)
frontend/src/components/results/index.ts               (new)
frontend/src/pages/AnalysisResultPage.tsx              (modified — renders ResultsPanel on completion)
frontend/src/test/analysisApi.test.ts                  (modified — adds fetchAnalysisResult tests)
frontend/src/test/useAnalysisResult.test.tsx            (new)
frontend/src/test/ConvictionGauge.test.tsx              (new)
frontend/src/test/VerdictPanel.test.tsx                 (new)
frontend/src/test/BullBearPanel.test.tsx                (new)
frontend/src/test/KeyRisksList.test.tsx                 (new)
frontend/src/test/MemoSection.test.tsx                  (new)
frontend/src/test/AgentWeightsPanel.test.tsx            (new)
frontend/src/test/ResultsPanel.test.tsx                 (new)
frontend/src/test/AnalysisResultPage.test.tsx           (modified — wraps QueryClientProvider, adds result tests)
docs/week-17/T-061-Build-Analysis-Results-Page.md      (new, this file)
```

No backend changes — `GET /api/v1/analysis/{job_id}/result` and its
`InvestmentDecisionResponse` schema already shipped in T-050
(`backend/routers/analysis.py`, `backend/models/schemas.py`). T-061 is
a frontend-only consumer of that existing endpoint.

### Design notes

- **`InvestmentDecisionResponse`** (`types/analysis.ts`) mirrors
  `backend.models.schemas.InvestmentDecisionResponse` field-for-field,
  the same convention every other type in this file already follows
  (see the file's own docstring on why snake_case is kept as-is rather
  than remapped to camelCase).
- **`fetchAnalysisResult`** (`api/analysis.ts`) is a thin
  `GET /analysis/{job_id}/result` wrapper, identical in shape to
  `fetchAnalysisHistory` — same `AnalysisApiError`/`parseErrorDetail`
  machinery, same Bearer-token header pattern.
- **`useAnalysisResult`** (new hook) wraps that fetch in React Query
  with `staleTime: Infinity` — once a decision is fetched it never
  needs a background refetch, because the backend never mutates a
  completed analysis's result (see the hook's own docstring). The
  caller (the page) is responsible for computing `enabled` from the
  live WebSocket stream; the hook has no opinion on `is_final` itself.
- **`ConvictionGauge`** is a hand-rolled semicircular SVG gauge rather
  than a `recharts` radial chart — a single static arc with one
  animated value is simpler as plain SVG + a CSS
  `transition-[stroke-dashoffset]` than as a full chart-library
  instance. The arc starts fully empty on first render and a
  `useEffect` commits the real `stroke-dashoffset` one paint later,
  the standard "animate on mount" pattern — no `requestAnimationFrame`
  is used since it isn't reliably available in the Vitest/jsdom test
  environment and isn't needed for the effect-after-mount trick to
  work.
- **`VerdictPanel`** is the top-of-page summary: verdict badge +
  conviction gauge + one-sentence dashboard summary + price
  target/time horizon pair, designed to be legible even if the reader
  never scrolls further.
- **`BullBearPanel`** and **`KeyRisksList`** both use the same
  `grid md:grid-cols-2` responsive pattern already established by
  `CommitteeSection.tsx` (T-055) — two columns on desktop, a single
  stacked column on mobile, with an honest fallback message for any
  empty string/array rather than a blank card.
- **`MemoSection`** is a single reusable "title + paragraph" card used
  for every free-text field that doesn't need bespoke layout
  (executive summary, investment thesis, valuation summary, contrarian
  resolution) — one parameterised component instead of four
  near-identical ones.
- **`AgentWeightsPanel`** reuses the existing `ProgressBar` primitive
  (T-054) to visualise `agent_weights` — a weight is conceptually
  identical to the "N% complete" value `ProgressBar` already renders.
  Display names are looked up from `lib/agentProgress.ts`'s
  `COMMITTEE_ROSTER`, the same lookup `AgentProgressBoard` and
  `DebateViewer` already use, so names stay consistent everywhere in
  the app.
- **`ResultsPanel`** is the top-level composition: verdict first, then
  every Investment Memo prose section, bull/bear case, risks/
  catalysts, valuation, the contrarian resolution, agent weights, and
  finally a small company/ticker/generated-at meta line — literally
  every `InvestmentDecisionResponse` field lands somewhere on the page.
- **Wiring:** `AnalysisResultPage.tsx` now also calls
  `useAnalysisResult`, gated on `isComplete && !hasFailed` — a failed
  job never reaches `status='completed'` on the backend, so
  `GET /result` would only ever return 409 for it; there is no
  decision to fetch for a failed run. A loading spinner shows while
  the fetch is in flight, an inline error message shows if it fails,
  and `<ResultsPanel>` renders once the decision arrives. The existing
  progress/debate tab switch (T-059/T-060) is untouched.

---

## 3. Full workflow — checkout to PR

### 3.1 Sync `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/ui-results
```

### 3.2 Add the new files

Copy the following into the working tree at the exact paths shown,
overwriting `frontend/src/types/analysis.ts`,
`frontend/src/api/analysis.ts`, `frontend/src/pages/AnalysisResultPage.tsx`,
`frontend/src/test/analysisApi.test.ts`, and
`frontend/src/test/AnalysisResultPage.test.tsx` in place:

```
frontend/src/types/analysis.ts
frontend/src/api/analysis.ts
frontend/src/hooks/useAnalysisResult.ts
frontend/src/components/results/ConvictionGauge.tsx
frontend/src/components/results/VerdictPanel.tsx
frontend/src/components/results/BullBearPanel.tsx
frontend/src/components/results/KeyRisksList.tsx
frontend/src/components/results/MemoSection.tsx
frontend/src/components/results/AgentWeightsPanel.tsx
frontend/src/components/results/ResultsPanel.tsx
frontend/src/components/results/index.ts
frontend/src/pages/AnalysisResultPage.tsx
frontend/src/test/analysisApi.test.ts
frontend/src/test/useAnalysisResult.test.tsx
frontend/src/test/ConvictionGauge.test.tsx
frontend/src/test/VerdictPanel.test.tsx
frontend/src/test/BullBearPanel.test.tsx
frontend/src/test/KeyRisksList.test.tsx
frontend/src/test/MemoSection.test.tsx
frontend/src/test/AgentWeightsPanel.test.tsx
frontend/src/test/ResultsPanel.test.tsx
frontend/src/test/AnalysisResultPage.test.tsx
docs/week-17/T-061-Build-Analysis-Results-Page.md
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

No backend files changed in this task, but if any other branch work is
staged alongside it, the backend gate is:

```bash
cd backend
black --check .
isort --check-only .
flake8 .
mypy .
pytest --tb=short --cov=backend --cov-report=term-missing -v
```

If `format:check` fails, run `npm run format` once to let Prettier fix
whitespace/quote-style, then re-run `format:check`.

If `lint` reports `import/order` issues, sort the flagged import block
alphabetically within its group (builtin → external → internal `@/...`
→ relative) — this is the one rule most likely to catch a
manually-typed import list. Note that inline `type` specifiers (e.g.
`import { type Foo } from "@/types/analysis"`) stay in the normal
group with their siblings; only a whole `import type { ... }`
declaration is treated as the separate "type" group.

If `lint` reports `react/no-unescaped-entities` on an apostrophe in
JSX text, wrap the whole string in a JS expression instead of an HTML
entity — e.g. `{"How the committee's evidence was weighted"}` — the
convention `DashboardPage.tsx`'s empty-state message already
established, not `&apos;`.

### 3.4 Commit (two-commit pattern: content, then any auto-fixes)

```bash
git add frontend/src/types/analysis.ts \
        frontend/src/api/analysis.ts \
        frontend/src/hooks/useAnalysisResult.ts \
        frontend/src/components/results/ConvictionGauge.tsx \
        frontend/src/components/results/VerdictPanel.tsx \
        frontend/src/components/results/BullBearPanel.tsx \
        frontend/src/components/results/KeyRisksList.tsx \
        frontend/src/components/results/MemoSection.tsx \
        frontend/src/components/results/AgentWeightsPanel.tsx \
        frontend/src/components/results/ResultsPanel.tsx \
        frontend/src/components/results/index.ts \
        frontend/src/pages/AnalysisResultPage.tsx \
        frontend/src/test/analysisApi.test.ts \
        frontend/src/test/useAnalysisResult.test.tsx \
        frontend/src/test/ConvictionGauge.test.tsx \
        frontend/src/test/VerdictPanel.test.tsx \
        frontend/src/test/BullBearPanel.test.tsx \
        frontend/src/test/KeyRisksList.test.tsx \
        frontend/src/test/MemoSection.test.tsx \
        frontend/src/test/AgentWeightsPanel.test.tsx \
        frontend/src/test/ResultsPanel.test.tsx \
        frontend/src/test/AnalysisResultPage.test.tsx \
        docs/week-17/T-061-Build-Analysis-Results-Page.md

git commit -m "feat(frontend): add Analysis Results page (T-061)"

# If a formatter/linter --fix step changed anything after the first
# commit, stage and recommit:
git add -A
git commit -m "chore(frontend): apply lint/format fixes for T-061" --allow-empty
```

Use `git commit --no-verify` only if Windows App Control blocks a
pre-commit hook shim (per the project's documented Windows
workaround) — CI's Linux runners remain the real enforcement gate.

### 3.5 Push and open the PR

```bash
git push -u origin feat/ui-results
```

Then open a PR from `feat/ui-results` → `main` (squash and merge) with
the title and description below.

---

## 4. Pull Request

### Title

```
feat(frontend): add Analysis Results page (T-061)
```

### Description

```markdown
## Summary

Adds the Analysis Results page — the final Investment Memo view shown
once an analysis pipeline completes. Renders every
`InvestmentDecisionResponse` field: a verdict panel with an animated
conviction gauge, price target and time horizon, executive summary and
investment thesis, bull case vs bear case side-by-side, structured key
risks and catalysts, valuation summary, the Portfolio Manager's
resolution of the Contrarian's strongest argument, and how much weight
each committee member's output received.

## Changes

- Add `InvestmentDecisionResponse` to `types/analysis.ts`, mirroring
  `backend.models.schemas.InvestmentDecisionResponse` field-for-field.
- Add `fetchAnalysisResult` to `api/analysis.ts` —
  `GET /api/v1/analysis/{job_id}/result`, same
  `AnalysisApiError`/`parseErrorDetail` pattern as the existing
  history/start/upload clients.
- Add `hooks/useAnalysisResult.ts`: a React Query wrapper with
  `staleTime: Infinity` (a completed decision never changes).
- Add `components/results/`: `ConvictionGauge` (animated semicircular
  SVG gauge), `VerdictPanel`, `BullBearPanel`, `KeyRisksList`,
  `MemoSection` (reusable prose card), `AgentWeightsPanel` (reuses the
  existing `ProgressBar` primitive), and `ResultsPanel` (top-level
  composition), plus a barrel `index.ts`.
- Update `pages/AnalysisResultPage.tsx`: fetches the result once the
  live stream reports completion (`isComplete && !hasFailed`) and
  renders `<ResultsPanel>` below the existing progress/debate tab
  switch, with a loading spinner and inline error state.
- Add unit/component tests for every new module, plus new
  `AnalysisResultPage.test.tsx` cases covering the result panel
  appearing on success, staying absent on failure, and surfacing a
  fetch error — wrapped in a `QueryClientProvider` since the page now
  uses React Query.

## Testing

- `npm run type-check` — passes
- `npm run lint` (`--max-warnings 0`) — passes
- `npm run format:check` — passes
- `npm run test:run` — passes, including:
  - `analysisApi.test.ts` — `fetchAnalysisResult` request shape,
    success, 409/404 error handling
  - `useAnalysisResult.test.tsx` — disabled when `enabled: false` or
    `accessToken: null`, resolves with the decision, surfaces a 409
    as an error
  - `ConvictionGauge.test.tsx` — score clamping, accessible label,
    per-verdict colour, animated transition class, fill proportional
    to score
  - `VerdictPanel.test.tsx`, `BullBearPanel.test.tsx`,
    `KeyRisksList.test.tsx`, `MemoSection.test.tsx`,
    `AgentWeightsPanel.test.tsx` — every field renders, every empty
    case shows an honest fallback
  - `ResultsPanel.test.tsx` — full composition, every
    `InvestmentDecisionResponse` field reaches the page
  - `AnalysisResultPage.test.tsx` — all pre-existing T-059/T-060 tests
    still pass, plus: results panel appears on success, absent and no
    fetch fires on failure, error message shows on a failed fetch
- `npm run build` — passes

## LangSmith Trace

N/A — frontend-only change, consuming an existing endpoint
(`GET /analysis/{job_id}/result`, T-050). No agent/graph behaviour
touched.

## Screenshots

_Add a screenshot of the completed results page (desktop and mobile
375px width) with a sample BUY verdict, before merging._

## Related Issues

Closes #T-061
```

---

## 5. Post-merge checklist

- [ ] Confirm CI's `frontend` job and `ci-pass` summary job are both green on the PR
- [ ] Delete `feat/ui-results` after squash-merge
- [ ] Update local `main`: `git checkout main && git pull origin main`
- [ ] Next session: T-062 (Build charts and visualisations — Recharts
      stock price chart, revenue/profit trend bars, P/E vs peers,
      sentiment gauge, risk radar), Phase 6, Week 17
