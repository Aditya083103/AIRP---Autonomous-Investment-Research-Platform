# T-063 — Build Investment Memo page

**Phase 6 — React Frontend | Week 17**
**Branch:** `feat/ui-memo`
**Base branch:** `main`

---

## 1. Task summary

Build a dedicated Investment Memo page: the full
`InvestmentDecisionResponse` rendered as formatted HTML with every
section collapsible, a "Download PDF" button that calls the existing
`GET /api/v1/analysis/{job_id}/memo/pdf` endpoint, and a "Share" button
that copies the page's URL to the clipboard.

**Acceptance criteria:**

- [x] Memo renders all sections (`VerdictPanel`, executive summary,
      investment thesis, bull/bear case, key risks & catalysts,
      valuation, contrarian resolution, agent weighting)
- [x] All sections collapsible (`CollapsibleSection`, defaulting open
      except "Agent weighting", which starts collapsed as the least
      load-bearing section for a first read)
- [x] PDF download triggers API (`useDownloadMemoPdf` calls
      `GET /api/v1/analysis/{job_id}/memo/pdf` with the Bearer token
      and drives a real browser download from the returned Blob)
- [x] Share URL works ("Share" copies `window.location.href` via
      `navigator.clipboard.writeText`, with a `document.execCommand`
      fallback and inline "Link copied!" confirmation)

---

## 2. Design notes

**No backend changes needed.** `GET /api/v1/analysis/{job_id}/memo/pdf`
already exists (T-050/T-043) and was sitting unused by the frontend --
`backend/routers/analysis.py`'s `download_analysis_memo_pdf` already
returns the branded PDF as a `FileResponse`, gated by the same
ownership check every other job-scoped route uses. This task is
frontend-only.

- **A new page, not a rewrite of `ResultsPanel`.**
  `AnalysisResultPage.tsx` (T-061) already renders every memo field
  via `<ResultsPanel>` the moment a pipeline finishes -- that page's
  job is "first look at the verdict while everything is still fresh
  from the live run." `MemoPage.tsx` is a different reading context:
  the polished, revisitable memo someone opens later, links to a
  colleague, or downloads as a PDF. Keeping it a separate route
  (`/analysis/:jobId/memo`) rather than bolting collapsibility and a
  toolbar onto `ResultsPanel` in place means none of T-061's existing,
  already-passing tests needed to change to accommodate this task --
  `ResultsPanel`, `MemoSection`, `VerdictPanel`, `BullBearPanel`,
  `KeyRisksList`, and `AgentWeightsPanel` are all reused as-is,
  unmodified. `AnalysisResultPage.tsx` gets one small addition: a
  "View full Investment Memo →" link to the new page once a decision
  has loaded.
- **`CollapsibleSection`** is a new design-system primitive
  (`components/ui/`), not a memo-specific component -- an
  uncontrolled, titled card whose body toggles via a header button
  (`aria-expanded`/`aria-controls`, collapsed content stays mounted but
  `hidden` rather than unmounting, since a memo section has no internal
  state worth preserving but keeping it in the DOM makes toggling
  instant and keeps tests simple). Defaults to open, matching how every
  memo section has always rendered -- collapsing is an explicit reader
  action, not a default state that could hide the memo's own content.
- **`MemoToolbar`** owns both actions and their own local feedback
  state (`isPending`/`isError` from the download mutation; a
  self-clearing `"copied" | "error"` state for Share) rather than
  lifting either up into `MemoPage` -- neither the PDF error message
  nor the "Link copied!" flash affects anything else on the page.
- **`useDownloadMemoPdf`** is a `useMutation`, not a `useQuery` -- a
  PDF download is a one-shot, user-triggered side effect with nothing
  to cache or refetch, not app state a component reads and re-renders
  against. On success it turns the fetched Blob into a `blob:` object
  URL, drives a synthetic `<a download>` click through it, and revokes
  the URL immediately after -- the standard "create, click, revoke"
  pattern a same-tab Blob download needs, required here specifically
  because this endpoint needs a Bearer `Authorization` header and so
  cannot be a plain `<a href>`.
- **Share** copies `window.location.href` (the current
  `/analysis/{jobId}/memo` URL) via `navigator.clipboard.writeText`,
  falling back to a hidden, immediately-removed `<textarea>` +
  `document.execCommand("copy")` for any environment without the
  Clipboard API. `MemoToolbar` accepts an optional `shareUrl` override
  for future use (e.g. a canonical/short link), defaulting to the
  page's own URL.
- **Agent weighting starts collapsed** (`defaultOpen={false}`) -- it is
  the one section that is supporting detail rather than something a
  reader needs on first render, the same reasoning `ResultsPanel`
  already applies by placing it last.

---

## 3. Files added / changed

```
frontend/src/components/ui/CollapsibleSection.tsx     (new)
frontend/src/components/ui/index.ts                    (modified — exports CollapsibleSection)
frontend/src/components/memo/MemoToolbar.tsx           (new)
frontend/src/components/memo/index.ts                  (new)
frontend/src/hooks/useDownloadMemoPdf.ts                (new)
frontend/src/api/analysis.ts                            (modified — adds fetchAnalysisMemoPdf)
frontend/src/pages/MemoPage.tsx                         (new)
frontend/src/pages/AnalysisResultPage.tsx               (modified — "View full Investment Memo" link)
frontend/src/routes/AppRoutes.tsx                       (modified — /analysis/:jobId/memo route)

frontend/src/test/CollapsibleSection.test.tsx           (new)
frontend/src/test/MemoToolbar.test.tsx                  (new)
frontend/src/test/useDownloadMemoPdf.test.tsx           (new)
frontend/src/test/MemoPage.test.tsx                     (new)
frontend/src/test/analysisApi.test.ts                   (modified — adds fetchAnalysisMemoPdf tests)

docs/week-17/T-063-Build-Investment-Memo-Page.md        (new, this file)
```

---

## 4. Full workflow — checkout to PR

### 4.1 Sync `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/ui-memo
```

### 4.2 Add the new/changed files

Copy the following into the working tree at the exact paths shown,
overwriting `frontend/src/api/analysis.ts`,
`frontend/src/components/ui/index.ts`,
`frontend/src/pages/AnalysisResultPage.tsx`,
`frontend/src/routes/AppRoutes.tsx`, and
`frontend/src/test/analysisApi.test.ts` in place:

```
frontend/src/components/ui/CollapsibleSection.tsx
frontend/src/components/ui/index.ts
frontend/src/components/memo/MemoToolbar.tsx
frontend/src/components/memo/index.ts
frontend/src/hooks/useDownloadMemoPdf.ts
frontend/src/api/analysis.ts
frontend/src/pages/MemoPage.tsx
frontend/src/pages/AnalysisResultPage.tsx
frontend/src/routes/AppRoutes.tsx
frontend/src/test/CollapsibleSection.test.tsx
frontend/src/test/MemoToolbar.test.tsx
frontend/src/test/useDownloadMemoPdf.test.tsx
frontend/src/test/MemoPage.test.tsx
frontend/src/test/analysisApi.test.ts
docs/week-17/T-063-Build-Investment-Memo-Page.md
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
auto-fix, then re-run `format:check`.

If `MemoToolbar.test.tsx`'s clipboard tests fail with a "Cannot
redefine property" error, another test in the same file redefined
`navigator.clipboard` without `configurable: true` -- confirm the
`afterEach` hook's `Reflect.deleteProperty(navigator, "clipboard")`
landed, so each test starts from a clean slate.

If `useDownloadMemoPdf.test.tsx` or `MemoToolbar.test.tsx`'s download
test hangs or throws on `URL.createObjectURL is not a function`, jsdom
does not implement Blob object URLs -- confirm the test stubs `URL`
with `createObjectURL`/`revokeObjectURL` mocks and spies on
`HTMLAnchorElement.prototype.click` before triggering the download.

### 4.4 Commit (two-commit pattern: content, then any auto-fixes)

```bash
git add frontend/src/components/ui/CollapsibleSection.tsx \
        frontend/src/components/ui/index.ts \
        frontend/src/components/memo/ \
        frontend/src/hooks/useDownloadMemoPdf.ts \
        frontend/src/api/analysis.ts \
        frontend/src/pages/MemoPage.tsx \
        frontend/src/pages/AnalysisResultPage.tsx \
        frontend/src/routes/AppRoutes.tsx \
        frontend/src/test/CollapsibleSection.test.tsx \
        frontend/src/test/MemoToolbar.test.tsx \
        frontend/src/test/useDownloadMemoPdf.test.tsx \
        frontend/src/test/MemoPage.test.tsx \
        frontend/src/test/analysisApi.test.ts \
        docs/week-17/T-063-Build-Investment-Memo-Page.md

git commit -m "feat(ui): add Investment Memo viewer page"

# If a formatter/linter --fix step changed anything after the first
# commit, stage and recommit:
git add -A
git commit -m "chore: apply lint/format fixes for T-063" --allow-empty
```

Use `git commit --no-verify` only if Windows App Control blocks a
pre-commit hook shim (per the project's documented Windows
workaround) -- CI's Linux runners remain the real enforcement gate.

### 4.5 Push and open the PR

```bash
git push -u origin feat/ui-memo
```

Then open a PR from `feat/ui-memo` → `main` (squash and merge) with
the title and description below.

---

## 5. Pull Request

### Title

```
feat(ui): implement Investment Memo page with collapsible sections and PDF download
```

### Description

```markdown
## Summary

Adds a dedicated Investment Memo page at /analysis/:jobId/memo: the
full InvestmentDecisionResponse rendered with every section wrapped
in a new collapsible primitive, a "Download PDF" button that calls
the existing GET /api/v1/analysis/{job_id}/memo/pdf endpoint, and a
"Share" button that copies the page's URL to the clipboard. No
backend changes -- the PDF endpoint (T-050/T-043) already existed
and was previously unused by the frontend.

## Changes

- Add CollapsibleSection (components/ui/): an uncontrolled, titled
  card whose body toggles via its header button
  (aria-expanded/aria-controls), defaulting to open. Collapsed
  content stays mounted (hidden) rather than unmounting.
- Add fetchAnalysisMemoPdf (api/analysis.ts): GET
  /api/v1/analysis/{job_id}/memo/pdf with the Bearer Authorization
  header, resolving with a Blob.
- Add useDownloadMemoPdf: a useMutation wrapping
  fetchAnalysisMemoPdf that turns the Blob into a blob: object URL,
  drives a synthetic <a download> click, and revokes the URL
  immediately after.
- Add MemoToolbar (components/memo/): "Download PDF" (wired to
  useDownloadMemoPdf, shows a spinner while pending and an inline
  error on failure) and "Share" (copies window.location.href via
  navigator.clipboard.writeText, with a document.execCommand
  fallback, and a self-clearing "Link copied!" confirmation).
- Add MemoPage: fetches the decision via the existing
  useAnalysisResult hook and renders VerdictPanel (always expanded)
  plus every other memo section -- executive summary, investment
  thesis, bull/bear case, key risks & catalysts, valuation,
  contrarian resolution, and agent weighting (starts collapsed) --
  each wrapped in CollapsibleSection, reusing BullBearPanel,
  KeyRisksList, and AgentWeightsPanel from the T-061 results
  components unmodified.
- Register /analysis/:jobId/memo as a new protected route in
  AppRoutes.tsx.
- Add a "View full Investment Memo →" link from AnalysisResultPage
  once a decision has loaded.

## Testing

- Frontend: `npm run type-check`, `npm run lint`,
  `npm run format:check`, `npm run test:run`, `npm run build` -- all
  pass, including:
  - `CollapsibleSection.test.tsx` -- default-open rendering, the
    defaultOpen={false} override, toggle-closed-then-open behaviour,
    and optional header-extra content
  - `analysisApi.test.ts` -- fetchAnalysisMemoPdf's request shape
    (URL, method, Authorization header), Blob resolution on success,
    and AnalysisApiError on a 404 (no PDF generated)
  - `useDownloadMemoPdf.test.tsx` -- fetches with the Authorization
    header and drives a download click on success; surfaces the
    backend's error detail on failure
  - `MemoToolbar.test.tsx` -- Download PDF requests the right job's
    PDF and shows an inline error on failure; Share copies the
    current URL and shows/clears "Link copied!", and shows an error
    message if the clipboard write itself fails
  - `MemoPage.test.tsx` -- loading state, every section rendered
    once loaded (verdict, executive summary, thesis, bull/bear,
    risks/catalysts, valuation, contrarian resolution, agent
    weighting), the page heading showing company name and ticker,
    an error message on a failed fetch, and the agent-weighting
    section starting collapsed
  - All pre-existing AnalysisResultPage.test.tsx and
    ResultsPanel/MemoSection/VerdictPanel/BullBearPanel/
    KeyRisksList/AgentWeightsPanel tests still pass unmodified

## LangSmith Trace

N/A -- no agent/graph behaviour touched; this is a frontend-only,
pipeline-adjacent page consuming an already-completed analysis's
result and an existing PDF export endpoint.

## Screenshots

_Add a screenshot of the Investment Memo page (desktop and mobile
375px width) for a completed BUY analysis, with at least one section
shown collapsed, before merging._

## Related Issues

Closes #T-063
```

---

## 6. Post-merge checklist

- [ ] Confirm CI's `backend`, `frontend`, and `ci-pass` summary jobs
      are all green on the PR
- [ ] Delete `feat/ui-memo` after squash-merge
- [ ] Update local `main`: `git checkout main && git pull origin main`
- [ ] Next session: T-064, Phase 6, Week 18 (per the project plan)
