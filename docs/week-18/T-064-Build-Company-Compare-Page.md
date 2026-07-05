# T-064 — Build Company Compare page

**Phase 6 — React Frontend | Week 18**
**Branch:** `feat/ui-compare`
**Base branch:** `main`

---

## 1. Task summary

Build a Company Compare page: pick two NSE companies, run both through
the full analysis pipeline in parallel, and render every metric from
both completed analyses in a single side-by-side table with the better
value highlighted per row.

**Acceptance criteria:**

- [x] Two companies analysed in parallel (`POST /analysis/start` fired
      for both via `Promise.all`, not sequentially; each then streams
      its own live progress independently over its own WebSocket
      connection)
- [x] Comparison table renders (verdict, conviction score, price
      target, P/E, P/B, EV/EBITDA, news sentiment, risk score, latest
      revenue, latest net income)
- [x] Winner logic correct (higher/lower "better direction" per
      metric, ties declared explicitly, and a metric missing on either
      side never silently declares a winner)

---

## 2. Design notes

**No backend changes needed.** The compare flow is built entirely out
of endpoints that already exist and are already consumed elsewhere:
`POST /api/v1/analysis/start` (T-047), `GET /api/v1/analysis/{job_id}/result`
(T-050), and `GET /api/v1/analysis/{job_id}/charts` (T-062). This task
runs two independent instances of the exact same pipeline a single
analysis already uses -- there is no "compare" concept on the backend
at all, and none was needed.

- **Two parallel, fully independent runs, not a joint job.** `startAnalysis`
  is called twice via `Promise.all` rather than `await`ed one after the
  other -- both `POST /analysis/start` requests fire together, so the
  two pipelines' ~90-second runtimes overlap instead of stacking to
  ~180 seconds. Once started, each side is driven by its own
  `useAnalysisStream` / `useAnalysisResult` / `useAnalysisCharts` triple
  inside its own `CompanyAnalysisPanel` instance -- exactly the three
  hooks `AnalysisResultPage.tsx` (T-061/T-062) already composes for a
  single job, just mounted twice with two different `jobId`s. Neither
  side's WebSocket connection, result fetch, or chart fetch is gated on
  the other side finishing first; a slow News Sentiment agent on
  Company A never blocks Company B's board from completing.
- **`winnerLogic.ts` is a pure module, no React.** `compareNumeric`,
  `compareVerdict`, and `buildComparisonRows` take already-fetched
  `InvestmentDecisionResponse` + `AnalysisChartDataResponse` pairs and
  return a plain `ComparisonRow[]` -- no hooks, no fetch, no formatting
  decisions baked into a component. This is what makes "winner logic
  correct" directly testable in `winnerLogic.test.ts` against hand-built
  fixtures, with no rendering or network mocking involved.
- **Fixed "better direction" per metric**, not something inferred at
  comparison time: conviction score, news sentiment, and both
  fundamentals (revenue, net income) are "higher is better"; P/E, P/B,
  EV/EBITDA, and risk score are "lower is better"; verdict is ranked
  `BUY > HOLD > SELL`. Price target is deliberately excluded from
  winner logic -- it is a free-text field (e.g. "₹1,800 (12-month)"),
  not a plain number, and parsing it into one for comparison risks
  silently misreading a currency/timeframe string.
- **A missing metric on either side never declares a winner.**
  `GET /charts`'s own contract (documented on
  `AnalysisChartDataResponse` in `src/types/analysis.ts`) is that
  valuation/sentiment/risk/financials can each independently be
  null/empty per company. `compareNumeric` returns `null` (no winner)
  whenever either input is `null` -- a gap in one company's data is
  never read as evidence the other company "won" that metric.
  `latestFinancialValue` additionally walks backwards from the most
  recent fiscal year to the first one with a non-null value, so one
  company's latest quarter/year having a `null` revenue doesn't make
  the whole revenue row unavailable if an earlier year has real data.
- **`ComparisonTable` is a plain `<table>`**, not a custom grid --
  metric-by-metric comparison is inherently tabular (`<th scope="row">`
  per metric, `<th scope="col">` per company), and a semantic table
  gives correct screen-reader row/column navigation for free. The
  winning cell gets a green left border, a tinted background, and a
  "Winner" badge; a tie or a row with no declared winner renders both
  cells identically, so "no winner" is never visually confused with "a
  narrow win."
- **`CompareInputForm` reuses `CompanyAutocomplete` unmodified**, twice
  -- no compare-specific fork of the combobox was needed. The one new
  validation rule (`compareSchemas.ts`) is a `.refine` on the object
  schema rejecting identical `companyTickerA`/`companyTickerB` values,
  since comparing a company against itself is never useful.
- **No PDF upload on this form**, unlike `AnalysisPage.tsx` -- there is
  no way to attribute one uploaded document to "company A" vs "company
  B" without a second upload control, and the T-064 acceptance criteria
  never asked for document-enriched comparisons, so that scope is left
  out rather than half-built.
- **A single `stage` state machine** (`"form" | "running" | "done"`)
  drives `ComparePage` rather than several independent booleans that
  could disagree with each other. The transition to `"done"` happens in
  a `useEffect` once both `CompanyAnalysisPanel`s have reported a
  settled result (success or failure) via their `onSettled` callback,
  each guarded by a `hasReportedRef` so it fires at most once per job
  regardless of how many times its own effect re-runs.

---

## 3. Files added / changed

```
frontend/src/lib/compare/winnerLogic.ts                 (new)
frontend/src/lib/validation/compareSchemas.ts            (new)
frontend/src/components/compare/CompareInputForm.tsx     (new)
frontend/src/components/compare/CompanyAnalysisPanel.tsx (new)
frontend/src/components/compare/ComparisonTable.tsx      (new)
frontend/src/components/compare/index.ts                 (new)
frontend/src/pages/ComparePage.tsx                        (new)
frontend/src/routes/AppRoutes.tsx                         (modified — /compare route)

frontend/src/test/winnerLogic.test.ts                     (new)
frontend/src/test/CompareInputForm.test.tsx               (new)
frontend/src/test/ComparisonTable.test.tsx                (new)
frontend/src/test/ComparePage.test.tsx                    (new)

docs/week-18/T-064-Build-Company-Compare-Page.md          (new, this file)
```

---

## 4. Full workflow — checkout to PR

### 4.1 Sync `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/ui-compare
```

### 4.2 Add the new/changed files

Copy the following into the working tree at the exact paths shown,
overwriting `frontend/src/routes/AppRoutes.tsx` in place:

```
frontend/src/lib/compare/winnerLogic.ts
frontend/src/lib/validation/compareSchemas.ts
frontend/src/components/compare/CompareInputForm.tsx
frontend/src/components/compare/CompanyAnalysisPanel.tsx
frontend/src/components/compare/ComparisonTable.tsx
frontend/src/components/compare/index.ts
frontend/src/pages/ComparePage.tsx
frontend/src/routes/AppRoutes.tsx
frontend/src/test/winnerLogic.test.ts
frontend/src/test/CompareInputForm.test.tsx
frontend/src/test/ComparisonTable.test.tsx
frontend/src/test/ComparePage.test.tsx
docs/week-18/T-064-Build-Company-Compare-Page.md
```

### 4.3 Verify locally before committing

This task is frontend-only -- no backend gate needed, but run it
anyway if any backend file has uncommitted changes from a prior
session:

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
auto-fix, then re-run `format:check` (this file's long docstring
comments and hand-wrapped test fixtures are the most likely source of
a few line-length reflows).

If `ComparePage.test.tsx` fails with "No FakeWebSocket connected for
\<jobId\>", confirm `vi.stubGlobal("WebSocket", FakeWebSocket)` is set
**before** `renderComparePage()` runs and before `submitComparison`
resolves -- both `CompanyAnalysisPanel` instances open their sockets
the moment they mount, right after the `startAnalysis` responses
resolve.

If `CompareInputForm.test.tsx`'s "same company" test is flaky, confirm
you are selecting two **different** display names before asserting the
identical-ticker case -- `selectCompany`'s `optionPattern` regex must
match exactly one option in the filtered listbox, or `user.click` will
throw on an ambiguous query instead of the assertion actually running.

### 4.4 Commit (two-commit pattern: content, then any auto-fixes)

```bash
git add frontend/src/lib/compare/ \
        frontend/src/lib/validation/compareSchemas.ts \
        frontend/src/components/compare/ \
        frontend/src/pages/ComparePage.tsx \
        frontend/src/routes/AppRoutes.tsx \
        frontend/src/test/winnerLogic.test.ts \
        frontend/src/test/CompareInputForm.test.tsx \
        frontend/src/test/ComparisonTable.test.tsx \
        frontend/src/test/ComparePage.test.tsx \
        docs/week-18/T-064-Build-Company-Compare-Page.md

git commit -m "feat(ui): add Company Compare page with winner-highlighted table"

# If a formatter/linter --fix step changed anything after the first
# commit, stage and recommit:
git add -A
git commit -m "chore: apply lint/format fixes for T-064" --allow-empty
```

Use `git commit --no-verify` only if Windows App Control blocks a
pre-commit hook shim (per the project's documented Windows
workaround) -- CI's Linux runners remain the real enforcement gate.

### 4.5 Push and open the PR

```bash
git push -u origin feat/ui-compare
```

Then open a PR from `feat/ui-compare` → `main` (squash and merge) with
the title and description below.

---

## 5. Pull Request

### Title

```
feat(ui): implement Company Compare page with parallel analysis and winner highlighting
```

### Description

```markdown
## Summary

Adds a Company Compare page at /compare: pick two NSE companies, run
both through the full 8-agent pipeline in parallel (two independent
POST /analysis/start calls via Promise.all), and once both finish,
render every metric from both completed analyses in a single table
with the better value highlighted per row. No backend changes -- this
reuses POST /analysis/start, GET /analysis/{job_id}/result, and GET
/analysis/{job_id}/charts exactly as AnalysisResultPage already does,
just for two job_ids instead of one.

## Changes

- Add winnerLogic.ts (lib/compare/): pure functions -- compareNumeric
  (direction-aware, null-safe), compareVerdict (BUY > HOLD > SELL),
  and buildComparisonRows, which turns two completed
  InvestmentDecisionResponse + AnalysisChartDataResponse pairs into
  the full ComparisonRow[] (verdict, conviction score, price target,
  P/E, P/B, EV/EBITDA, sentiment, risk score, latest revenue, latest
  net income). A metric missing on either side never declares a
  winner.
- Add compareSchemas.ts (lib/validation/): companyTickerA/B required,
  plus a .refine rejecting identical selections.
- Add CompareInputForm (components/compare/): two
  CompanyAutocomplete instances (reused from T-058 unmodified) and a
  submit button.
- Add CompanyAnalysisPanel (components/compare/): one side of the
  parallel run -- composes useAnalysisStream / useAnalysisResult /
  useAnalysisCharts for one job_id, shows a compact progress bar +
  latest-agent line, and reports the settled result (or null on
  failure) to its parent exactly once via onSettled.
- Add ComparisonTable (components/compare/): a semantic <table>
  rendering every ComparisonRow, highlighting the winning cell with a
  border/tint/"Winner" badge; ties and null winners render both
  cells identically.
- Add ComparePage: the "form" -> "running" -> "done" state machine --
  starts both analyses together on submit, renders two
  CompanyAnalysisPanels side by side while running, and renders
  ComparisonTable (or a failure message naming which side didn't
  complete) once both panels settle. Includes a "Compare again"
  reset.
- Register /compare as a new protected route in AppRoutes.tsx.

## Testing

- Frontend: `npm run type-check`, `npm run lint`,
  `npm run format:check`, `npm run test:run`, `npm run build` -- all
  pass, including:
  - `winnerLogic.test.ts` -- compareNumeric in both directions plus
    ties and missing values, compareVerdict's BUY/HOLD/SELL ranking,
    formatMetricValue's "--" fallback, and buildComparisonRows'
    per-row winners including the "most recent non-null fiscal year"
    revenue/net-income lookup and the price-target row never
    declaring a winner
  - `CompareInputForm.test.tsx` -- validation errors for empty
    fields, rejecting an identical company on both sides, calling
    onSubmit with the two selected companies, external formError
    display, and the disabled/loading submit state
  - `ComparisonTable.test.tsx` -- renders every row and both company
    headers, shows a "Winner" badge only in the winning cell, and
    shows no badge for a tied or null-winner row
  - `ComparePage.test.tsx` -- starts two analyses in parallel (two
    independent WebSocket connections, one per job_id), renders the
    comparison table with correct winners once both jobs' final
    stream events arrive, and supports "Compare again" resetting
    back to the input form
  - All pre-existing AnalysisPage/AnalysisResultPage/MemoPage tests
    still pass unmodified -- CompanyAutocomplete, useAnalysisStream,
    useAnalysisResult, and useAnalysisCharts are reused as-is with no
    changes to their behaviour or public API

## LangSmith Trace

N/A -- no agent/graph behaviour touched; this page starts two
ordinary analysis pipelines (each already traced end-to-end by
LangSmith the same way a single analysis is) and only adds
frontend-side comparison/display logic on top of their results.

## Screenshots

_Add a screenshot of the Compare page (desktop and mobile 375px
width): the two-company input form, the side-by-side progress view
mid-run, and the completed comparison table with at least one
highlighted winner cell -- before merging._

## Related Issues

Closes #T-064
```

---

## 6. Post-merge checklist

- [ ] Confirm CI's `backend`, `frontend`, and `ci-pass` summary jobs
      are all green on the PR
- [ ] Delete `feat/ui-compare` after squash-merge
- [ ] Update local `main`: `git checkout main && git pull origin main`
- [ ] Next session: T-065, Phase 6, Week 18 (per the project plan)
