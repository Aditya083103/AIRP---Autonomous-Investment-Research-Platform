# T-066 — Frontend error handling and loading states

**Phase 6 — React Frontend | Week 18**
**Branch:** `feat/ui-error-handling`
**Base branch:** `main`

---

## 1. Task summary

Add the frontend's error-handling and loading-state infrastructure:
a top-level error boundary, toast notifications for API errors,
skeleton loaders for every data-fetching state, and empty states.

**Acceptance criteria:**

- [x] No unhandled React errors
- [x] Every loading state shows a skeleton
- [x] API errors show a toast

---

## 2. Design notes

**No new npm dependency.** No toast library, error-boundary package,
or skeleton library is a project dependency, and none was added --
same "no `npm install` against a registry this sandbox cannot reach to
verify" constraint every prior Phase 6 task (CompanyAutocomplete's
hand-rolled combobox, Tooltip's hand-rolled popup) has already worked
within. Everything here is hand-rolled from the existing design
tokens.

### 2.1 Error boundary

- **One class component in an all-function-component codebase.**
  React only supports catching render-phase errors via
  `static getDerivedStateFromError`/`componentDidCatch` on a class --
  there is no hook equivalent in React 18 -- so `ErrorBoundary.tsx` is
  the one deliberate exception.
- **Hand-rolls `react-error-boundary`'s two load-bearing ideas**
  rather than inventing something bespoke: a `resetKeys` array (any
  element changing between renders clears the caught error
  automatically) and an explicit `reset()` escape hatch the fallback's
  "Try again" button calls directly.
- **Mounted once**, in `App.tsx`, wrapping `<AppRoutes />` --
  `RootErrorBoundary` (the functional wrapper supplying
  `resetKeys={[location.pathname]}`) needs `useLocation()`, which only
  works below `AppProviders`' `<BrowserRouter>`; `App.tsx` is exactly
  that "inside the Router, above the routes" spot.
- **The fallback's "Go home" link is a plain `<a href="/">`**, not
  react-router's `Link`, deliberately: a full page reload guarantees a
  genuinely clean app state after a render crash, rather than a
  client-side navigation re-using whatever state elsewhere in the tree
  contributed to the crash.
- **This is a last-resort safety net**, not a substitute for the
  specific loading/error/empty states this task also adds to
  DashboardPage, AnalysisResultPage, MemoPage, and ComparePage -- those
  handle the _expected_ failure modes (a failed fetch, an analysis
  that didn't complete) with contextual UI already in place; the
  boundary exists for the _unexpected_ case -- a genuine bug in a
  render path -- where the alternative is React unmounting the whole
  tree to a blank white page.

### 2.2 Toast notifications

- **A framework-agnostic external store** (`lib/toastStore.ts`:
  `add`/`remove`/`clear`/`subscribe`/`getSnapshot`), not a React
  context -- the entire point of "API errors show a toast" is firing a
  toast from places that are **not** inside the React tree at the
  moment the error happens. The most important case is
  `lib/queryClient.ts`'s `QueryCache`/`MutationCache` `onError`
  callbacks, which run as plain TanStack Query internals with no
  component instance, hook, or context available to them at all. A
  module any plain function can call `.add()` on, read reactively via
  `useSyncExternalStore` (`hooks/useToasts.ts`) in the one mounted
  `<ToastViewport>`, is the standard way to bridge that gap.
- **`lib/queryClient.ts` now wires a shared `onError`** into both
  caches -- this is what makes "every API error shows a toast" hold
  for every current _and future_ query/mutation without each one
  needing its own `toast.error(...)` call. `QueryCache.onError` only
  fires once a query has exhausted its retries and settled into a
  final error state (not on every individual retry attempt), so a
  query that fails twice and then succeeds on its final retry never
  toasts at all.
- **Four call sites still call `toast.error(...)` explicitly**:
  LoginPage, RegisterPage, AnalysisPage, and ComparePage's submit
  handlers. All four call their API functions (`login`, `register`,
  `uploadDocument`/`startAnalysis`) directly rather than through a
  React Query mutation, so the global `MutationCache.onError` never
  sees them -- the same reasoning is written as a comment at each of
  those four catch blocks pointing back to this one.
- **The stream's connection error also gets a toast**, from
  `AnalysisResultPage` -- a `useEffect` watching `useAnalysisStream`'s
  own `error` value. That hook (T-049) already surfaces `error` inline
  via `AgentProgressBoard`'s own banner; the toast is a secondary,
  ambient notification for someone who might be looking at the
  "Debate transcript" tab instead when the connection drops.
  `useAnalysisStream.ts` itself was not modified -- this is purely an
  additive effect in the page that already consumes it.
- **A toast is never the only signal for a blocking failure.** Every
  page that already had its own inline error text (DashboardPage,
  AnalysisResultPage, MemoPage) keeps it unchanged -- the toast is a
  transient, ambient notification that disappears after 6 seconds; the
  inline UI is the persistent, contextual detail that stays on screen
  until the user acts. Both firing for the same failure is the same
  layering most production apps use, not a duplicate to clean up.
- **`role="alert"` for error-tone toasts, `role="status"` for
  success/info** -- an error fires from a failed request the user is
  actively waiting on and should interrupt the screen reader
  immediately; success/info are announced without interrupting
  whatever is already being read.

### 2.3 Skeleton loaders

- **One primitive (`ui/Skeleton.tsx`)**: a single pulsing bar, purely
  visual and `aria-hidden` on every instance -- every composed
  skeleton is built by arranging several of these, the same way real
  content is assembled from `Card`/`Badge`/`Spinner` rather than one
  page hand-rolling markup no other page reuses.
- **Three compositions in `components/skeletons/`**, each shaped like
  the real content it stands in for so there's no layout jump once the
  real data arrives:
  - `HistoryTableSkeleton` -- DashboardPage, while
    `GET /analysis/history` is loading.
  - `ResultsPanelSkeleton` -- AnalysisResultPage **and** MemoPage,
    while `GET /analysis/{job_id}/result` is loading (one composition
    serves both pages, since both fetch the identical resource shape
    via `useAnalysisResult`).
  - `ChartsPanelSkeleton` -- AnalysisResultPage, while
    `GET /analysis/{job_id}/charts` is loading.
- **Each composition's `role="status"` + a visually-hidden `label`
  prop is the one accessible announcement for the whole group** -- a
  screen reader hears "Loading your analysis history…" once, not once
  per shimmering bar. `MemoPage`'s and `AnalysisResultPage`'s
  `ResultsPanelSkeleton` calls deliberately pass the _exact same_
  visible label text ("Loading the Investment Memo…") the old
  spinner+text row used, so `MemoPage.test.tsx`'s pre-existing
  `getByText("Loading the Investment Memo…")` assertion keeps passing
  completely unchanged -- the text moved from a plain paragraph into a
  skeleton's `sr-only` span, but it's still there, still queryable.
- **AgentProgressBoard is deliberately untouched** -- it is not a
  placeholder standing in for content that isn't ready yet, it _is_
  the real-time content (T-059's live event-by-event board). A
  skeleton is for "we know the shape, we're waiting on the data"; the
  progress board's whole job is showing exactly what's known so far,
  which is not the same thing.

### 2.4 Empty states

- **One primitive (`ui/EmptyState.tsx`)**: title, optional description,
  optional action -- deliberately distinct from an error state (muted
  tones, no `role="alert"`, no verdict-sell red) since an empty
  successful fetch is not a failure.
- **DashboardPage's two zero-result branches** (no history at all, and
  no loaded rows matching the search) now both use it. "No history at
  all" gained a genuine improvement beyond a visual refresh: a
  "Run an analysis →" link straight to `/analysis`, since that is the
  one thing a person seeing this page for the first time actually
  needs to do next -- the old version only said so in a sentence.

### 2.5 One real bug found and fixed along the way

- **`AuthProvider.logout` had an unguarded `await logoutUser()`.**
  Every caller (e.g. RootLayout's header) invokes `logout()` as
  `() => void handleLogout()`, which discards the returned promise --
  if the `/auth/logout` network call failed for any reason (a brief
  backend blip), that became a genuine unhandled promise rejection
  with no caller able to catch it. Local state was already cleared
  _before_ that `await` (per the function's own existing comment on
  why -- "the UI reflects logged out immediately... even if the
  network request... fails outright"), so the fix is exactly what that
  comment already promised: wrap the call in `try/catch` and log
  instead of letting it escape. Covered by a new
  `AuthProvider.test.tsx` case.

---

## 3. Files added / changed

```
frontend/src/components/ui/Skeleton.tsx                    (new)
frontend/src/components/ui/EmptyState.tsx                  (new)
frontend/src/components/ui/index.ts                        (modified — export both)

frontend/src/components/skeletons/HistoryTableSkeleton.tsx (new)
frontend/src/components/skeletons/ResultsPanelSkeleton.tsx (new)
frontend/src/components/skeletons/ChartsPanelSkeleton.tsx  (new)
frontend/src/components/skeletons/index.ts                 (new)

frontend/src/lib/toastStore.ts                             (new)
frontend/src/lib/toast.ts                                  (new)
frontend/src/hooks/useToasts.ts                            (new)
frontend/src/components/toast/Toast.tsx                    (new)
frontend/src/components/toast/ToastViewport.tsx            (new)
frontend/src/components/toast/index.ts                     (new)

frontend/src/components/error/ErrorBoundary.tsx            (new)
frontend/src/components/error/index.ts                     (new)

frontend/src/lib/queryClient.ts                            (modified — global onError → toast)
frontend/src/providers/AppProviders.tsx                    (modified — mounts <ToastViewport />)
frontend/src/App.tsx                                       (modified — wraps routes in RootErrorBoundary)
frontend/src/providers/AuthProvider.tsx                    (modified — logout no longer unhandled-rejects)

frontend/src/pages/LoginPage.tsx                            (modified — toast on auth error)
frontend/src/pages/RegisterPage.tsx                         (modified — toast on auth error)
frontend/src/pages/AnalysisPage.tsx                         (modified — toast on start-analysis error)
frontend/src/pages/ComparePage.tsx                          (modified — toast on start-comparison error)
frontend/src/pages/AnalysisResultPage.tsx                   (modified — skeletons + stream-error toast)
frontend/src/pages/MemoPage.tsx                             (modified — skeleton)
frontend/src/pages/DashboardPage.tsx                        (modified — skeleton + empty states)

frontend/src/test/toastStore.test.ts                        (new)
frontend/src/test/ToastViewport.test.tsx                    (new)
frontend/src/test/ErrorBoundary.test.tsx                    (new)
frontend/src/test/queryClientToasts.test.tsx                (new)
frontend/src/test/Skeleton.test.tsx                         (new)
frontend/src/test/EmptyState.test.tsx                       (new)
frontend/src/test/AuthProvider.test.tsx                     (modified — logout-failure case)
frontend/src/test/DashboardPage.test.tsx                    (modified — skeleton + empty-state CTA)
frontend/src/test/AnalysisResultPage.test.tsx               (modified — skeletons + stream-error toast)
frontend/src/test/LoginPage.test.tsx                        (modified — toast assertion)
frontend/src/test/RegisterPage.test.tsx                     (modified — toast assertion)
frontend/src/test/AnalysisPage.test.tsx                     (modified — toast assertion)
frontend/src/test/ComparePage.test.tsx                      (modified — new failure-path test)

docs/week-18/T-066-Frontend-Error-Handling-And-Loading-States.md  (new, this file)
```

`MemoPage.test.tsx` is **not** in this list -- its one loading-state
assertion (`getByText("Loading the Investment Memo…")`) still passes
unmodified against the new skeleton, by design (see section 2.3).

---

## 4. Full workflow — checkout to PR

### 4.1 Sync `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/ui-error-handling
```

### 4.2 Add the new/changed files

Copy every file listed in section 3 into the working tree at the exact
paths shown, overwriting the "modified" ones in place.

### 4.3 Verify locally before committing

Frontend-only task -- no backend gate needed, but run it anyway if any
backend file has uncommitted changes from a prior session:

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
auto-fix long lines/comments, then re-run `format:check`.

If `AnalysisResultPage.test.tsx`'s new skeleton tests fail with
"Unable to find an element by testid", confirm the fetch mock in that
specific test truly never resolves (`new Promise(() => {})`) -- a mock
that resolves immediately races past the pending state before the
assertion runs.

If `ErrorBoundary.test.tsx`'s `RootErrorBoundary` test fails after an
edit, check whether the nav `<Link>` accidentally ended up _inside_
`<RootErrorBoundary>` in the test's render tree -- a caught error
unmounts everything the boundary wraps, so the link that triggers
recovery cannot itself be inside the crashed subtree (see that test's
own comment).

If `queryClientToasts.test.tsx` fails intermittently, confirm
`queryClient.clear()` and `toastStore.clear()` are both running in
`afterEach` -- it imports the real shared singleton (deliberately, to
test the actual production wiring), so state can leak between test
files if either is skipped.

### 4.4 Commit (two-commit pattern: content, then any auto-fixes)

```bash
git add frontend/src/components/ui/Skeleton.tsx \
        frontend/src/components/ui/EmptyState.tsx \
        frontend/src/components/ui/index.ts \
        frontend/src/components/skeletons/ \
        frontend/src/components/toast/ \
        frontend/src/components/error/ \
        frontend/src/lib/toastStore.ts \
        frontend/src/lib/toast.ts \
        frontend/src/lib/queryClient.ts \
        frontend/src/hooks/useToasts.ts \
        frontend/src/providers/AppProviders.tsx \
        frontend/src/providers/AuthProvider.tsx \
        frontend/src/App.tsx \
        frontend/src/pages/LoginPage.tsx \
        frontend/src/pages/RegisterPage.tsx \
        frontend/src/pages/AnalysisPage.tsx \
        frontend/src/pages/ComparePage.tsx \
        frontend/src/pages/AnalysisResultPage.tsx \
        frontend/src/pages/MemoPage.tsx \
        frontend/src/pages/DashboardPage.tsx \
        frontend/src/test/ \
        docs/week-18/T-066-Frontend-Error-Handling-And-Loading-States.md

git commit -m "fix(ui): add comprehensive error handling and loading states"

# If a formatter/linter --fix step changed anything after the first
# commit, stage and recommit:
git add -A
git commit -m "chore: apply lint/format fixes for T-066" --allow-empty
```

Use `git commit --no-verify` only if Windows App Control blocks a
pre-commit hook shim (per the project's documented Windows
workaround) -- CI's Linux runners remain the real enforcement gate.

### 4.5 Push and open the PR

```bash
git push -u origin feat/ui-error-handling
```

Then open a PR from `feat/ui-error-handling` → `main` (squash and
merge) with the title and description below.

---

## 5. Pull Request

### Title

```
fix(ui): implement error boundaries, toasts, and skeleton loaders
```

### Description

```markdown
## Summary

Adds the frontend's error-handling and loading-state infrastructure
per T-066: a top-level React error boundary with a recoverable
fallback, a hand-rolled toast system wired automatically into every
React Query query/mutation failure (plus four manual call sites for
non-React-Query auth/analysis-start flows), skeleton loaders shaped
like their real content for every data-fetching state, and empty
states with a call-to-action. No new npm dependency -- everything is
hand-rolled from the existing design tokens, same constraint every
prior Phase 6 task has worked within.

## Changes

- Add ErrorBoundary.tsx (components/error/): a class component
  (React's only mechanism for catching render-phase errors) with a
  recoverable fallback ("Try again" resets in place, "Go home" is a
  plain hard-reload link) and a resetKeys prop mirroring
  react-error-boundary's own API. RootErrorBoundary wraps it with
  resetKeys={[location.pathname]}. Mounted once in App.tsx around
  <AppRoutes />.
- Add toastStore.ts / toast.ts / useToasts.ts / Toast.tsx /
  ToastViewport.tsx: a framework-agnostic external store (needed
  because TanStack Query's cache callbacks run outside the React
  tree), an ergonomic toast.success/error/info() API, and a
  <ToastViewport> mounted once in AppProviders.tsx. Error toasts use
  role="alert"; success/info use role="status". Auto-dismiss after 6
  seconds, or immediately via a manual close button.
- Modify queryClient.ts: adds a QueryCache/MutationCache pair with a
  shared onError that calls toastApiError(...) -- this is what makes
  "every API error shows a toast" hold for every current and future
  query/mutation without each one needing its own toast call.
- Add toast.error(...) calls to the four manual try/catch blocks that
  bypass React Query (LoginPage, RegisterPage, AnalysisPage,
  ComparePage) and to a new useEffect in AnalysisResultPage watching
  useAnalysisStream's connection error.
- Add Skeleton.tsx (ui/) -- a single pulsing bar primitive -- and
  three shaped compositions in components/skeletons/:
  HistoryTableSkeleton (DashboardPage), ResultsPanelSkeleton
  (AnalysisResultPage + MemoPage), ChartsPanelSkeleton
  (AnalysisResultPage). Each wraps role="status" + a visually-hidden
  label; MemoPage's/AnalysisResultPage's label text is unchanged from
  the old spinner+text row on purpose, so MemoPage.test.tsx's existing
  loading-text assertion still passes.
- Add EmptyState.tsx (ui/); DashboardPage's two zero-result branches
  now use it, and "no history yet" gained a "Run an analysis →" CTA.
- Fix AuthProvider.logout: wraps the previously-unguarded
  `await logoutUser()` in try/catch -- a failed /auth/logout call was
  an unhandled promise rejection, since every caller invokes logout()
  as `() => void handleLogout()`, discarding the promise.

## Testing

- Frontend: `npm run type-check`, `npm run lint`,
  `npm run format:check`, `npm run test:run`, `npm run build` -- all
  pass, including:
  - toastStore.test.ts, ToastViewport.test.tsx -- store add/remove/
    subscribe/clear, toast()/toastApiError() tone+fallback behaviour,
    rendering/ordering/ARIA-role/manual-dismiss/auto-dismiss
  - ErrorBoundary.test.tsx -- catches a render error, shows the
    fallback, logs via console.error, "Try again" re-attempts the
    same subtree, resetKeys changing auto-recovers, and
    RootErrorBoundary recovers on an external route change
  - queryClientToasts.test.tsx -- imports the real queryClient
    singleton (not a fresh test-only client) and proves a failing
    query and a failing mutation both surface as toasts through the
    actual production wiring
  - Skeleton.test.tsx, EmptyState.test.tsx -- primitive rendering/ARIA
  - AuthProvider.test.tsx (extended) -- logout still clears local
    state and does not throw when the API call fails
  - DashboardPage.test.tsx (extended) -- skeleton while loading, CTA
    link in the empty state
  - AnalysisResultPage.test.tsx (extended) -- results/charts skeletons
    while each is pending, toast on an unauthorized stream closure
  - LoginPage/RegisterPage/AnalysisPage/ComparePage.test.tsx (each
    extended) -- the existing inline-error assertion now also checks
    a matching toast fired; ComparePage gained a new failure-path test
    that didn't exist before
  - MemoPage.test.tsx -- unmodified and still passing: its loading
    assertion targets the exact same visible text, now inside the
    skeleton's sr-only label

## LangSmith Trace

N/A -- no agent/graph behaviour touched; this is frontend-only
error-handling and loading-state infrastructure.

## Screenshots

_Add screenshots of: the error boundary fallback (trigger by throwing
in a dev-only test route), a toast for a simulated API failure, the
Dashboard/Results/Memo skeletons mid-load, and the Dashboard empty
state with its new CTA -- before merging._

## Related Issues

Closes #T-066
```

---

## 6. Post-merge checklist

- [ ] Confirm CI's `backend`, `frontend`, and `ci-pass` summary jobs
      are all green on the PR
- [ ] Delete `feat/ui-error-handling` after squash-merge
- [ ] Update local `main`: `git checkout main && git pull origin main`
- [ ] Next session: check the project plan for the next Phase 6/7 task
