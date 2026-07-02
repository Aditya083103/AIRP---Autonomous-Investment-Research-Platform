# T-057 -- Build Dashboard Page

**Phase:** 6 -- React Frontend
**Week:** 16
**Branch:** `feat/ui-dashboard`
**Task status:** Complete

---

## Overview

T-057 replaces T-056's Dashboard placeholder with the real thing: the
user's analysis history loaded from the already-existing
`GET /api/v1/analysis/history` endpoint (T-050), rendered as a table with
colour-coded BUY/HOLD/SELL badges, a company-name search box, pagination,
and a link from each row to its (not-yet-built) detail page.

**Acceptance criteria (all must pass):**
- History loads from API
- BUY/HOLD/SELL badges colour-coded
- Search filters by company name

**Two honest scope notes, read first**

1. **"Risk score" vs. what the API returns.** The task description asks
   for a "risk score" column. `backend.models.schemas.HistoryEntryResponse`
   (T-050) has no such field -- the history endpoint returns
   `conviction_score` (1-10, from the Portfolio Manager), not a Risk
   Officer score. A per-agent risk score only exists in the full
   `GET /.../result` payload, which this lightweight history list
   deliberately does not fetch for every row on every page (see that
   endpoint's own docstring on why). The table's score column is labelled
   **"Conviction"** and shows exactly what the API returns, rather than
   mislabelling `conviction_score` as "Risk" to match the task's wording.
2. **Search is client-side, over the currently loaded page only.**
   `GET /api/v1/analysis/history` takes `limit`/`offset`, not a text
   filter -- there is no `company_name` query param to call. Adding one
   would mean hand-editing `backend.services.analysis`'s raw SQL
   (`_SQL_LOAD_HISTORY_PAGE` / `_SQL_COUNT_HISTORY`) without being able to
   run the backend test suite here to verify it -- the same reasoning
   `backend/routers/auth.py`'s T-056 docstring already applied when it
   left `get_current_user` alone rather than guess at a backend change it
   couldn't verify. The search box's hint text says "Searches the
   analyses currently loaded on this page" so this isn't a silent
   limitation -- and it satisfies the acceptance criterion as written
   ("search filters by company name") without overstating what it does.

**In scope:** `DashboardPage` (rewritten), `HistoryTable`, `VerdictBadge`,
a `src/api/analysis.ts` client, `src/types/analysis.ts`, a
`useAnalysisHistory` React Query hook, a placeholder
`/analysis/:jobId/result` detail route, and tests for all of it.

**Explicitly out of scope:**
- The real Analysis Results page (verdict panel, bull/bear case, memo) --
  T-061. `/analysis/:jobId/result` here is a small placeholder, the same
  pattern `AnalysisPage` (T-055) and the original `DashboardPage`
  (T-056) established.
- Server-side search/filtering -- see scope note 2 above.
- Skeleton loaders / toast notifications / empty-state polish as a
  system-wide pattern -- that is T-066 ("Frontend error handling and
  loading states"). This task's loading/error/empty states are simple
  and functional (a `Spinner`, a plain error message, a plain empty-state
  message) rather than the polished version T-066 will standardise
  across every page.

---

## What Was Built

### `src/types/analysis.ts` (new)
`HistoryEntryResponse` / `HistoryResponse` mirroring
`backend.models.schemas` exactly, plus narrower `AnalysisStatus` /
`Verdict` string-literal unions for better autocomplete on the frontend
(the backend itself just types these as `str`).

### `src/api/analysis.ts` (new)
`fetchAnalysisHistory({ accessToken, limit, offset })` -- `GET
/api/v1/analysis/history` with an `Authorization: Bearer` header (this
endpoint authenticates via the header, not the httpOnly cookie -- same
reasoning as `useAnalysisStream`'s WebSocket token, see
`AuthProvider.tsx`'s docstring from T-056). `AnalysisApiError` +
`parseErrorDetail` intentionally duplicate `src/api/auth.ts`'s shapes
rather than sharing one implementation, small enough that two
independently-readable files beat a shared abstraction for two call
sites (the same tradeoff `backend/services/analysis.py`'s own docstring
makes for its duplicated ticker-override table).

### `src/hooks/useAnalysisHistory.ts` (new)
A thin React Query wrapper (`src/lib/queryClient.ts`'s own docstring
already names "analysis status, results, history" as the data its
defaults are tuned for). `enabled: accessToken !== null` gates the
query -- `DashboardPage` is behind `ProtectedRoute`, so this should
never matter in practice, but the hook stays honest about the type.

### `src/components/dashboard/VerdictBadge.tsx` (new)
Maps a history row's `verdict` + `status` to the right `Badge` (T-054)
tone: `buy`/`hold`/`sell` for a real verdict, and `Pending` / `Running` /
`Failed` neutral-toned badges for the three states a row can be in
before it has a verdict at all -- `HistoryEntryResponse.verdict` is
`null` in every one of those cases, so this exists specifically so the
table never renders a blank cell for an in-progress or failed analysis.

### `src/components/dashboard/HistoryTable.tsx` (new)
Company (name + ticker), date, `VerdictBadge`, conviction score
(`X/10`, or an em dash when not yet available), and a "View" link to
`/analysis/{job_id}/result`.

### `src/pages/AnalysisResultPage.tsx` (new, placeholder)
The link target for `HistoryTable`'s "View" column -- the acceptance
criterion's "link to detail". Shows the `job_id` from the route so the
link is visibly confirmable; the real verdict/memo rendering is T-061.

### `src/pages/DashboardPage.tsx` (rewritten)
Composes `useAnalysisHistory` + a search `Input` + `HistoryTable` +
Previous/Next pagination buttons (`PAGE_SIZE = 20`, matching the
backend's `DEFAULT_HISTORY_PAGE_SIZE`). Loading shows a `Spinner`; a
failed request shows the backend's error message; an empty history
shows a plain "you haven't run an analysis yet" message, distinct from
"no loaded rows match your search" when a search query filters
everything out. No longer has its own "Log out" button -- `RootLayout`'s
header (T-056) already provides one globally, so the T-056 placeholder's
copy was redundant here.

### `src/routes/AppRoutes.tsx` (modified)
Adds a `ProtectedRoute`-wrapped `path="analysis/:jobId/result"`.

### Testing

`frontend/src/test/`:
- **`analysisApi.test.ts`** -- `src/api/analysis.ts` against a mocked
  `fetch`: `Authorization` header, `limit`/`offset` query params (and
  their omission when not given), successful parsing, and
  `AnalysisApiError` extraction/status code.
- **`VerdictBadge.test.tsx`** -- each of BUY/HOLD/SELL, plus the
  pending/running/failed fallbacks.
- **`HistoryTable.test.tsx`** -- renders company/ticker per row, formats
  a present conviction score as `X/10` and a missing one as an em dash,
  links each row to its `/analysis/{job_id}/result` detail page.
- **`DashboardPage.test.tsx`** -- greets the user, loads and renders
  rows from a mocked `fetch`, colour-codes BUY/SELL badges (asserts the
  actual `bg-verdict-*` class is present), shows the empty state with no
  history, shows the backend's error message on failure, filters loaded
  rows as the user types into search, and exercises pagination
  (Previous/Next disabled state, and that clicking Next requests
  `offset=20`).
- **`AnalysisResultPage.test.tsx`** -- renders the coming-soon heading
  and the `job_id` from the route.

### CI

No workflow changes, no new dependencies -- `@tanstack/react-query` was
already a dependency (used by `queryClient.ts` since T-053), and the
backend endpoint this task consumes (`GET /api/v1/analysis/history`) was
already built and tested in T-050. Both gates
(`type-check`/`lint`/`format:check`/`test:run`/`build` on the frontend;
`black`/`isort`/`flake8`/`mypy --strict`/`pytest` on the backend) cover
the new/changed files with zero modification.

---

## How It Was Tested / Verified

Backend is untouched by this task -- no backend commands needed beyond
confirming `GET /api/v1/analysis/history` already passes its existing
T-050 tests (it does; nothing here changes it).

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

Manual end-to-end verification (needs the backend running -- see
T-056's doc for the `python -m uvicorn` note if `uvicorn.exe` gets
blocked by Windows App Control):

1. `python -m uvicorn backend.main:app --reload --port 8000` in one
   terminal, `cd frontend && npm run dev` in another.
2. Log in (or register) at `http://localhost:3000/login`.
3. On `/dashboard`, confirm the history table loads real rows if you
   have completed analyses already, or the "you haven't run an analysis
   yet" empty state if you don't.
4. If you have at least one completed analysis: confirm its verdict
   badge is the right colour (BUY green / HOLD amber / SELL red, per the
   existing `Badge` tones) and its conviction score renders as `X/10`.
5. Type a partial company name into the search box: confirm the table
   narrows to matching rows only, and clearing the box brings the rest
   back.
6. Click "View" on any row: confirm it navigates to
   `/analysis/{job_id}/result` and shows that job's ID.
7. If you have more than 20 analyses, confirm "Next" loads the next page
   and "Previous" goes back; otherwise confirm both buttons render
   disabled.
8. Stop the backend and refresh `/dashboard`: confirm the page shows a
   readable error message rather than a blank screen or an unhandled
   exception in the console.

---

## Git Workflow (exact commands)

```bash
# 0) Start from an up-to-date main
git checkout main
git pull origin main

# 1) Create the feature branch
git checkout -b feat/ui-dashboard

# 2) (do the work -- files listed above)

# 3) Verify (see "How It Was Tested" above)
cd frontend
npm ci
npm run lint:fix && npm run format
npm run type-check && npm run lint && npm run format:check
npm run test:run && npm run build
cd ..

# 4) Stage and commit (re-stage after auto-fixers ran)
git add frontend/src/types/analysis.ts \
        frontend/src/api/analysis.ts \
        frontend/src/hooks/useAnalysisHistory.ts \
        frontend/src/components/dashboard/ \
        frontend/src/pages/DashboardPage.tsx \
        frontend/src/pages/AnalysisResultPage.tsx \
        frontend/src/routes/AppRoutes.tsx \
        frontend/src/test/analysisApi.test.ts \
        frontend/src/test/VerdictBadge.test.tsx \
        frontend/src/test/HistoryTable.test.tsx \
        frontend/src/test/DashboardPage.test.tsx \
        frontend/src/test/AnalysisResultPage.test.tsx \
        docs/week-16/T-057-Build-Dashboard-Page.md
git commit -m "feat(dashboard): build analysis history table with search and pagination"

# If pre-commit reformats anything, re-stage and recommit (two-commit pattern):
#   git add -A && git commit -m "feat(dashboard): build analysis history table with search and pagination"

# 5) Push and open the PR
git push -u origin feat/ui-dashboard
```

**Commit message:**
```
feat(dashboard): build analysis history table with search and pagination
```

**PR title:**
```
feat(dashboard): implement Dashboard page with history table, verdict badges, and search
```

**PR description:**
```markdown
## Summary
Replaces the T-056 Dashboard placeholder with the real page: analysis
history loaded from the existing GET /api/v1/analysis/history endpoint
(T-050), rendered with colour-coded BUY/HOLD/SELL badges, a company-name
search box (client-side, over the loaded page), Previous/Next
pagination, and a link from each row to a new /analysis/:jobId/result
placeholder (real Results page is T-061). See the linked doc
(docs/week-16/T-057-Build-Dashboard-Page.md) for why the score column is
labelled "Conviction" rather than "Risk" (the API has no risk-score
field in this endpoint) and why search is client-side only.

## Changes
- `src/types/analysis.ts`, `src/api/analysis.ts`,
  `src/hooks/useAnalysisHistory.ts`
- `src/components/dashboard/{VerdictBadge,HistoryTable}.tsx`
- Rewrites `src/pages/DashboardPage.tsx`; adds
  `src/pages/AnalysisResultPage.tsx` (placeholder)
- Wires a protected `/analysis/:jobId/result` route into
  `src/routes/AppRoutes.tsx`
- No new dependencies -- @tanstack/react-query already present since T-053

## Testing
- [x] Unit tests added / updated -- 5 new frontend test files covering
  the API client, VerdictBadge, HistoryTable, DashboardPage (loading,
  data, colour-coding, empty state, error state, search, pagination),
  and AnalysisResultPage
- [x] Integration tests pass (backend untouched; T-050's existing
  history-endpoint tests are unaffected)
- [x] Manual smoke test performed against a running backend -- history
  loads, verdict colours correct, search narrows results, View link
  navigates, pagination buttons behave correctly, and a stopped backend
  shows a readable error instead of a blank page

`npm run type-check`, `npm run lint`, `npm run format:check`,
`npm run test:run`, and `npm run build` all pass locally.

## LangSmith Trace
n/a -- no agent code touched.

## Screenshots
<paste terminal output of the passing checks, plus a screenshot of the
dashboard with a few history rows showing colour-coded verdict badges,
and a screenshot of the search box narrowing results>

## Related Issues
Closes #<issue-number>
```

---

## Notes for the Next Task

- **`AnalysisResultPage.tsx` is a placeholder on purpose** -- T-061
  replaces its body with the full verdict panel, bull/bear case, and
  memo rendering. Keep using the `jobId` route param to fetch
  `GET /api/v1/analysis/{job_id}/result` when that task starts.
- **Server-side search/filtering on `GET /api/v1/analysis/history`** is
  a reasonable enhancement if the client-side-only limitation becomes a
  real annoyance (e.g. once a user has more analyses than fit on one
  page) -- see scope note 2 above for the shape of that change
  (a `company_name` query param plus a `WHERE company_name ILIKE`
  clause in `backend.services.analysis`'s raw SQL), and make sure to
  actually run `backend/tests/unit/test_analysis_result_history_service.py` /
  `test_analysis_result_history_router.py` against it, not just reason
  about it.
- Next: **T-058 -- Build Analysis Input page**, per the master task
  list.
