# T-092 — AccuracyPage.tsx frontend

**Phase:** 8 — Verdict Accuracy Tracker
**Week:** 21
**Branch:** `feat/ui-accuracy-page`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 5

## Summary

T-091 shipped the read side of the Verdict Accuracy Tracker on the
backend: `GET /api/v1/accuracy/summary` and `GET /api/v1/accuracy/history`,
both public, unauthenticated endpoints. T-092 is the frontend that
finally makes that data visible: a public `/accuracy` route rendering
three Recharts visualisations plus a small stats overview, built
entirely from those two endpoints, reachable from the main nav without
signing in.

1. **Rolling accuracy trend line** — a windowed (not cumulative)
   directional-accuracy percentage over time, computed client-side from
   a page of `GET /accuracy/history` entries.
2. **Verdict-type bar chart** — one bar per BUY/HOLD/SELL, accuracy
   percentage from `GET /accuracy/summary`'s `by_verdict` breakdown.
3. **Conviction-vs-accuracy scatter** — one point per evaluated verdict,
   conviction score against the actual price-change outcome, coloured
   by whether the call was directionally correct.

## Acceptance criteria (from task spec)

- [x] `/accuracy` route renders three charts from live API data
- [x] Responsive
- [x] Loading/empty states handled

## Design decisions

- **The route is public — no `ProtectedRoute` wrapper, no
  `useAuth()` anywhere in the new code.** This mirrors the backend:
  `backend/routers/accuracy.py`'s `GET /summary` and `GET /history`
  (T-091) have no auth dependency at all, since `verdict_outcomes` is a
  platform-wide statistic, not scoped to a user. `AccuracyPage` is
  registered directly in `AppRoutes.tsx` alongside `login`/`register`,
  not inside a `<ProtectedRoute>` the way `/analysis`, `/dashboard`,
  `/compare`, and the two `/analysis/:jobId/*` routes are.
- **"Accuracy" was added to `RootLayout`'s always-visible
  `PRIMARY_NAV_LINKS`**, not gated behind `isAuthenticated` the way the
  other three links effectively are by their target route's own
  `ProtectedRoute`. A public dashboard with no link to it from the nav
  would only be reachable by typing the URL directly, which defeats the
  point of it being public.
- **Two independent `useQuery` calls** (`useAccuracySummary`,
  `useAccuracyHistory`), not one combined fetch — the same reasoning
  `AnalysisResultPage.tsx`'s own docstring gives for keeping
  `useAnalysisResult` and `useAnalysisCharts` separate: a slow or failed
  history fetch should never block the summary stats from rendering,
  and vice versa. `AccuracyPanel` is only rendered once **both** have
  resolved successfully — the trend line and scatter chart need
  history entries, the stat row and bar chart need the summary, so a
  panel built from just one of the two would either be half-empty or
  need every child chart to handle a missing prop. Given the two
  endpoints resolve within milliseconds of each other against the same
  backend in practice, that extra null-handling complexity was judged
  not worth it for this page.
- **`useAccuracyHistory` defaults to `limit=100`
  (`MAX_ACCURACY_HISTORY_PAGE_SIZE`, mirroring the backend's own
  `MAX_ACCURACY_HISTORY_PAGE_SIZE`), not the backend's own smaller
  `limit=20` default.** The two charts built from history data want as
  complete a picture as the API allows in one request, not just the
  newest page a caller gets by omitting `limit` — there is no visible
  history *table* on this page (unlike `DashboardPage`'s
  `HistoryTable`), only the two charts derived from it, so there is no
  competing "keep the page small" pressure the way a paginated table
  would create.
- **The rolling accuracy trend is a ROLLING window (10 verdicts,
  `ROLLING_WINDOW_SIZE`), not cumulative accuracy-to-date.** A
  cumulative line only ever moves slowly and monotonically converges —
  after a few hundred scored verdicts, one more correct or incorrect
  call barely nudges it, so it stops being informative about whether
  the committee is *currently* performing well. A rolling window stays
  responsive to recent performance at the cost of some noise while few
  verdicts have been scored, which is why every point also carries a
  `sample_size` the tooltip surfaces — an early, small-sample point is
  never silently presented as a stable trend. This computation lives in
  its own pure, framework-free module
  (`src/lib/accuracy/rollingAccuracy.ts`) rather than inline in the
  chart component, the same "computation separate from rendering" split
  `src/lib/compare/winnerLogic.ts` already establishes — it can be unit
  tested with plain fixture arrays, no rendering involved at all.
- **Only EVALUATED entries (`directional_correct !== null`)
  participate in either the trend line or the scatter chart.** A
  pending `verdict_outcomes` row (T-089's "not yet reached its
  evaluation horizon" state) has no correctness or outcome to plot —
  counting it as neither a hit nor a miss inside a rolling window would
  silently distort the percentage either way, and it simply has no
  `price_change_pct` for the scatter chart's y-axis at all.
- **The scatter chart plots `conviction_score` (x) against
  `price_change_pct` (y), split into two `Scatter` series (Correct /
  Incorrect) by colour** — not a single homogeneous cloud, and not the
  bucketed low/medium/high rollup `AccuracySummaryResponse.by_conviction`
  already provides (that rollup has its own home: the stats row's
  numbers and, implicitly, informs the verdict bar chart). Recharts
  colours an entire `<Scatter>` by its own `fill` prop, not per point,
  so two series is the straightforward way to get a legend reading
  "green dots were right, red dots were wrong" plotted against the
  actual magnitude of the price move — a finer-grained picture than a
  bucketed average can show (e.g. whether a high-conviction miss still
  tends to be a smaller miss than a low-conviction one).
- **The verdict-type bar chart renders a null `accuracy_pct` as a
  zero-height bar with a "Not yet scored" tooltip**, not as a missing
  bar or a gap — `backend.services.accuracy_tracker.get_accuracy_summary`
  guarantees `by_verdict` always has exactly one entry per BUY/HOLD/SELL
  (T-091), even with zero scored rows for one of them, so this chart
  never needs to backfill a missing verdict itself, only decide how to
  render a null percentage once it gets one. An `!anyScored` footnote
  covers the all-three-empty case explicitly.
- **A small `AccuracySummaryStats` 3-tile row (overall accuracy, total
  scored, total pending) sits above the three named charts.** It is not
  one of the task's three required charts, but
  `GET /accuracy/summary`'s top-level fields would otherwise go
  completely unused despite being the first numbers a "public accuracy
  dashboard" visitor actually wants — the same reasoning
  `ChartsPanel.tsx`'s `data_warnings` banner sits above that page's own
  charts rather than being dropped for having no chart of its own.
- **Responsive layout mirrors `ChartsPanel`'s own breakpoint choice**:
  the trend line is full-width (reads best wide, same call as
  `StockPriceChart`/`RevenueProfitChart` on `AnalysisResultPage`), and
  the verdict bar chart + scatter chart share a `md:grid-cols-2` row
  that collapses to one stacked column below the `md` (768px)
  breakpoint — the same breakpoint every other Phase 6+ chart layout
  already treats as "mobile vs desktop". `AccuracyPanelSkeleton` mirrors
  this exact layout so the real panel replaces it without the page's
  height jumping around once data loads.
- **Loading is a single skeleton, not two independent ones.**
  `AccuracyPage` shows `AccuracyPanelSkeleton` whenever *either* query
  is still loading (`isSummaryLoading || isHistoryLoading`) rather than
  rendering, say, the bar chart the moment the summary resolves
  independently of history — consistent with the "both queries must
  resolve before the panel renders" decision above.
- **Loading/empty state coverage, precisely**: a full-page skeleton
  while either query is in flight; an inline `role="alert"` error
  message (matching `DashboardPage`'s own error-branch pattern) if
  either query fails, using whichever error arrives first
  (`summaryError ?? historyError`); and, for the "successful fetch,
  legitimately zero data" case (a brand-new deployment with an empty
  `verdict_outcomes` table), every chart renders its own honest
  empty-state fallback text rather than an error — `get_accuracy_summary`
  and `get_accuracy_history` both document an empty table as a normal,
  valid response (T-091), not something to treat as a failure here
  either.

## Files changed / created

### Frontend — types

- **`frontend/src/types/accuracy.ts`** (**CREATE**) — TypeScript types
  mirroring `backend.models.schemas`'s T-091 accuracy response schemas
  exactly (same snake_case-preserving convention as `types/analysis.ts`).

### Frontend — API client

- **`frontend/src/api/accuracy.ts`** (**CREATE**) — `fetchAccuracySummary`,
  `fetchAccuracyHistory`; neither sends an `Authorization` header.
  `AccuracyApiError` + `parseErrorDetail` duplicated from
  `api/analysis.ts`'s own pair, per that file's established
  "small enough to keep independently readable" precedent.

### Frontend — hooks

- **`frontend/src/hooks/useAccuracySummary.ts`** (**CREATE**) — React
  Query wrapper, no `enabled` gate or `accessToken` param (public
  endpoint).
- **`frontend/src/hooks/useAccuracyHistory.ts`** (**CREATE**) — same
  shape; exports `MAX_ACCURACY_HISTORY_PAGE_SIZE` (100), the default
  `limit` this page requests.

### Frontend — computation

- **`frontend/src/lib/accuracy/rollingAccuracy.ts`** (**CREATE**) —
  pure `buildRollingAccuracySeries()` plus `ROLLING_WINDOW_SIZE` (10).

### Frontend — chart components

- **`frontend/src/components/charts/AccuracyTrendChart.tsx`** (**CREATE**)
- **`frontend/src/components/charts/VerdictAccuracyChart.tsx`** (**CREATE**)
- **`frontend/src/components/charts/ConvictionAccuracyScatterChart.tsx`**
  (**CREATE**)
- **`frontend/src/components/charts/AccuracySummaryStats.tsx`** (**CREATE**)
- **`frontend/src/components/charts/AccuracyPanel.tsx`** (**CREATE**) —
  composes the four components above.
- **`frontend/src/components/charts/index.ts`** (**MODIFY**) — barrel
  export extended with the five new components.

### Frontend — skeleton

- **`frontend/src/components/skeletons/AccuracyPanelSkeleton.tsx`**
  (**CREATE**)
- **`frontend/src/components/skeletons/index.ts`** (**MODIFY**) — barrel
  export extended.

### Frontend — page, routing, navigation

- **`frontend/src/pages/AccuracyPage.tsx`** (**CREATE**)
- **`frontend/src/routes/AppRoutes.tsx`** (**MODIFY**) — registers
  `path="accuracy"` at the layout-route level, outside any
  `<ProtectedRoute>`.
- **`frontend/src/components/layout/RootLayout.tsx`** (**MODIFY**) —
  adds "Accuracy" to `PRIMARY_NAV_LINKS`.

### Frontend — tests

- **`frontend/src/test/accuracyApi.test.ts`** (**CREATE**)
- **`frontend/src/test/rollingAccuracy.test.ts`** (**CREATE**)
- **`frontend/src/test/useAccuracySummary.test.tsx`** (**CREATE**)
- **`frontend/src/test/useAccuracyHistory.test.tsx`** (**CREATE**)
- **`frontend/src/test/AccuracyTrendChart.test.tsx`** (**CREATE**)
- **`frontend/src/test/VerdictAccuracyChart.test.tsx`** (**CREATE**)
- **`frontend/src/test/ConvictionAccuracyScatterChart.test.tsx`**
  (**CREATE**)
- **`frontend/src/test/AccuracySummaryStats.test.tsx`** (**CREATE**)
- **`frontend/src/test/AccuracyPanel.test.tsx`** (**CREATE**)
- **`frontend/src/test/AccuracyPage.test.tsx`** (**CREATE**)
- **`frontend/src/test/RootLayout.test.tsx`** (**MODIFY**) — extends the
  existing primary-nav and mobile-panel tests to also assert the new
  "Accuracy" link; no existing assertion removed or weakened.

### Docs

- **`docs/week-21/T-092-ui-accuracy-page.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/ui-accuracy-page

git branch
# → * feat/ui-accuracy-page
```

### Step 2 — Add the types and API client

- `frontend/src/types/accuracy.ts`: new file.
- `frontend/src/api/accuracy.ts`: new file.

### Step 3 — Add the hooks and the rolling-accuracy computation

- `frontend/src/hooks/useAccuracySummary.ts`: new file.
- `frontend/src/hooks/useAccuracyHistory.ts`: new file.
- `frontend/src/lib/accuracy/rollingAccuracy.ts`: new file.

### Step 4 — Add the chart components and skeleton

- `frontend/src/components/charts/AccuracyTrendChart.tsx`
- `frontend/src/components/charts/VerdictAccuracyChart.tsx`
- `frontend/src/components/charts/ConvictionAccuracyScatterChart.tsx`
- `frontend/src/components/charts/AccuracySummaryStats.tsx`
- `frontend/src/components/charts/AccuracyPanel.tsx`
- `frontend/src/components/charts/index.ts`: extend the barrel export.
- `frontend/src/components/skeletons/AccuracyPanelSkeleton.tsx`
- `frontend/src/components/skeletons/index.ts`: extend the barrel export.

### Step 5 — Add the page, route, and nav link

- `frontend/src/pages/AccuracyPage.tsx`: new file.
- `frontend/src/routes/AppRoutes.tsx`: register `path="accuracy"`
  outside `<ProtectedRoute>`.
- `frontend/src/components/layout/RootLayout.tsx`: add "Accuracy" to
  `PRIMARY_NAV_LINKS`.

### Step 6 — Add the tests

Create all ten new test files listed above, and extend
`frontend/src/test/RootLayout.test.tsx` with the new nav-link
assertions.

### Step 7 — Run the full verification gate locally

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

If `format:check` reports files needing formatting, run
`npm run format` (Prettier `--write`) and re-stage before committing —
the same two-commit pattern the backend workflow docs already use for
Black/isort.

### Step 8 — Manual smoke test against a local dev server (optional)

```bash
# Terminal 1 -- backend
uvicorn backend.main:app --reload --port 8000

# Terminal 2 -- frontend
cd frontend
npm run dev
```

Then in a browser:

- Visit `http://localhost:3000/accuracy` **without logging in** —
  confirm the page loads and the "Accuracy" nav link is visible in the
  header alongside "New analysis" / "Compare" / "Dashboard".
- On a fresh local database (empty `verdict_outcomes` table), confirm
  the stats row shows `--` for overall accuracy and `0` for both
  counts, and all three charts show their own honest empty-state text
  rather than an error.
- Resize the browser below 768px width and confirm the verdict bar
  chart and scatter chart stack into a single column, and the mobile
  hamburger panel includes "Accuracy" among its links.
- (Optional, once some verdicts exist and have been scored via
  `POST /api/v1/accuracy/run` or the daily cron) confirm all three
  charts render real data points and the rolling-window footnote under
  the trend line shows a plausible scored-verdict count.

### Step 9 — Commit (two-commit pattern)

```bash
git add frontend/src/types/accuracy.ts
git add frontend/src/api/accuracy.ts
git add frontend/src/hooks/useAccuracySummary.ts frontend/src/hooks/useAccuracyHistory.ts
git add frontend/src/lib/accuracy/rollingAccuracy.ts
git add frontend/src/components/charts/AccuracyTrendChart.tsx
git add frontend/src/components/charts/VerdictAccuracyChart.tsx
git add frontend/src/components/charts/ConvictionAccuracyScatterChart.tsx
git add frontend/src/components/charts/AccuracySummaryStats.tsx
git add frontend/src/components/charts/AccuracyPanel.tsx
git add frontend/src/components/charts/index.ts
git add frontend/src/components/skeletons/AccuracyPanelSkeleton.tsx
git add frontend/src/components/skeletons/index.ts
git add frontend/src/pages/AccuracyPage.tsx
git add frontend/src/routes/AppRoutes.tsx
git add frontend/src/components/layout/RootLayout.tsx
git add frontend/src/test/accuracyApi.test.ts
git add frontend/src/test/rollingAccuracy.test.ts
git add frontend/src/test/useAccuracySummary.test.tsx frontend/src/test/useAccuracyHistory.test.tsx
git add frontend/src/test/AccuracyTrendChart.test.tsx
git add frontend/src/test/VerdictAccuracyChart.test.tsx
git add frontend/src/test/ConvictionAccuracyScatterChart.test.tsx
git add frontend/src/test/AccuracySummaryStats.test.tsx
git add frontend/src/test/AccuracyPanel.test.tsx
git add frontend/src/test/AccuracyPage.test.tsx
git add frontend/src/test/RootLayout.test.tsx
git add docs/week-21/T-092-ui-accuracy-page.md

git commit -m "feat(frontend): add public verdict accuracy dashboard

- Add public /accuracy route (AccuracyPage.tsx) -- no ProtectedRoute,
  no signed-in user required, matching backend/routers/accuracy.py's
  own public GET /summary + GET /history (T-091)
- Add three Recharts visualisations: a rolling (not cumulative)
  accuracy trend line, a verdict-type (BUY/HOLD/SELL) accuracy bar
  chart, and a conviction-vs-outcome scatter split by correct/incorrect
- Add a small AccuracySummaryStats overview row (overall accuracy,
  verdicts scored, verdicts pending) above the three named charts
- Add useAccuracySummary / useAccuracyHistory hooks and their backing
  api/accuracy.ts client (both deliberately send no Authorization
  header)
- Add src/lib/accuracy/rollingAccuracy.ts -- pure, independently unit-
  tested rolling-window accuracy computation
- Add AccuracyPanelSkeleton for the loading state; every chart handles
  its own empty/zero-data state honestly (not as an error)
- Add \"Accuracy\" to RootLayout's primary nav (desktop + mobile panel)
- Full test coverage: API client, pure rolling-accuracy logic, every
  hook, every chart component, the composed panel, and the page's
  loading/error/success/empty states

Closes #92"
```

If a formatter modifies files after staging (Prettier `--write` via
`npm run format`, or an editor auto-fix), re-stage and make a second,
separate commit rather than amending:

```bash
git add -A
git commit -m "style: apply prettier formatting to T-092 files"
```

### Step 10 — Push and open the PR

```bash
git push -u origin feat/ui-accuracy-page
```

**Base branch:** `main`
**Compare branch:** `feat/ui-accuracy-page`

## Pull Request

**PR title:**

```
feat(ui): build AccuracyPage with trend, breakdown, and conviction-correlation charts
```

**PR description:**

```markdown
## Summary
Adds the /accuracy route: a public, unauthenticated dashboard showing
how accurate AIRP's Portfolio Manager verdicts have actually been,
built entirely from T-091's two public backend endpoints
(GET /api/v1/accuracy/summary, GET /api/v1/accuracy/history).

## Changes
- Public /accuracy route (no ProtectedRoute) with an "Accuracy" link
  added to the main nav (desktop bar + mobile panel)
- Three Recharts visualisations: rolling accuracy trend line
  (windowed, not cumulative -- stays responsive to recent performance),
  verdict-type accuracy bar chart (BUY/HOLD/SELL, always 3 bars even
  with zero scored rows), conviction-vs-outcome scatter (one point per
  evaluated verdict, conviction score vs. actual price-change %,
  coloured correct/incorrect)
- A small stats row (overall accuracy, verdicts scored, verdicts
  pending) using GET /accuracy/summary's top-level fields
- useAccuracySummary / useAccuracyHistory (React Query, no auth gating
  -- both endpoints are public) and api/accuracy.ts
- src/lib/accuracy/rollingAccuracy.ts -- pure, independently testable
  rolling-window accuracy computation (10-verdict window; only
  evaluated, non-pending verdicts participate)
- AccuracyPanelSkeleton for the loading state, matching AccuracyPanel's
  real layout so nothing jumps once data loads
- Every chart renders its own honest empty-state text for a
  legitimately-empty verdict_outcomes table (not an error) --
  accuracy_pct is treated as unknown (not 0%) until at least one
  verdict has actually been scored
- Responsive: trend line full-width, verdict bar chart + scatter share
  a 2-column row on desktop (md:grid-cols-2) collapsing to one stacked
  column on mobile, matching ChartsPanel's own breakpoint convention
- Full test coverage across the API client, the pure rolling-accuracy
  function, every hook, every chart component, the composed panel, and
  the page itself (loading skeleton, both-succeed, either-fails,
  legitimately-empty-data cases)

## Testing
- `npm run test:run` -- all green, including the 10 new/modified test
  files listed in the task doc
- Manual smoke test: loaded /accuracy without being signed in against
  both a populated and an empty local verdict_outcomes table; resized
  below 768px to confirm the responsive collapse and the mobile nav
  panel includes "Accuracy"
- `npm run type-check`, `npm run lint`, `npm run format:check` all pass
- `npm run build` succeeds

## LangSmith Trace
N/A -- frontend-only change, no agent/LLM-facing code touched.

## Screenshots
_Attach a screenshot of the populated dashboard and the empty-state
dashboard here before opening the PR._

## Related Issues
Closes #92
```

## Testing

Frontend (`npm run test:run`):

- **`accuracyApi.test.ts`** — confirms neither `fetchAccuracySummary`
  nor `fetchAccuracyHistory` sends an `Authorization` header; query
  param forwarding for `limit`/`offset`; `AccuracyApiError` message
  extraction and status code for both the plain-string and
  validation-array FastAPI error-body shapes.
- **`rollingAccuracy.test.ts`** — empty input, all-pending input
  (excluded entirely), chronological sort order, 100%/0%/mixed rounded
  percentages, window sliding once it reaches full size, growing
  `sample_size` for early points, and pending entries correctly
  ignored when interleaved among evaluated ones.
- **`useAccuracySummary.test.tsx` / `useAccuracyHistory.test.tsx`** —
  fetch fires immediately with no `enabled`/`accessToken` gate;
  default `limit`/`offset` (history only); explicit params forwarded;
  success resolves with the typed response; failure surfaces as
  `isError`.
- **`AccuracyTrendChart.test.tsx`** — title, container, both empty-state
  paths (no entries at all; entries present but none evaluated), and
  the rolling-window footnote text (including singular "verdict" for
  a count of exactly one).
- **`VerdictAccuracyChart.test.tsx`** — title, container, empty
  `byVerdict` fallback, and the "not yet scored for any type" footnote
  appearing only when every verdict has zero evaluated rows.
- **`ConvictionAccuracyScatterChart.test.tsx`** — title, container with
  correct-only and incorrect-only data, both empty-state paths, and the
  defensive case of a null `price_change_pct` despite a non-null
  `directional_correct` (should not occur in practice, must not crash).
- **`AccuracySummaryStats.test.tsx`** — percentage formatting, localised
  counts, the `--` placeholder for a null `overall_accuracy_pct`, and
  all three tile labels.
- **`AccuracyPanel.test.tsx`** — confirms the stats row and all three
  charts are wired in, and that an empty history array still renders
  each chart's own fallback rather than crashing.
- **`AccuracyPage.test.tsx`** — page heading; skeleton while both
  queries are loading and while only one has resolved; all three charts
  render once both queries resolve with populated data; the panel's own
  empty states render for a legitimately all-zero platform; an error
  from either query surfaces as an inline alert and suppresses the
  panel; whichever error arrives first is the one shown.
- **`RootLayout.test.tsx`** (extended) — the new "Accuracy" link is
  asserted in both the always-visible desktop bar and the mobile panel,
  alongside the three pre-existing links; no existing assertion was
  removed.

All tests run fully offline against mocked `global.fetch` — no real
network call, no Recharts internals asserted on directly (only titles,
container `data-testid`s, and empty-state text, the same restraint
`StockPriceChart.test.tsx`'s own docstring documents for T-062's chart
tests).

"Responsive" and "loading/empty states handled" (the other two
acceptance criteria) are covered by: the Tailwind breakpoint classes
themselves (`md:grid-cols-2` on `AccuracyPanel`, verified by manual
resize per Step 8, since jsdom cannot assert on applied CSS media
queries) and the loading-skeleton/error-alert/empty-fallback test
coverage listed above, respectively.

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
frontend route, its supporting hooks/API client, and Recharts
visualisations only.

## Related Issues

Closes #92 (adjust to your actual issue number if different).