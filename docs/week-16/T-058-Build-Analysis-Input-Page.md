# T-058 -- Build Analysis Input Page

**Phase:** 6 -- React Frontend
**Week:** 16
**Branch:** `feat/ui-analysis-input`
**Task status:** Complete

---

## Overview

T-058 replaces T-055's `/analysis` placeholder with the real input form:
a company autocomplete over a static top-50 NSE list, an optional PDF
upload (annual report), a "Start Analysis" button, and validation for
both fields. Submitting calls the already-existing
`POST /api/v1/analysis/start` (T-047) and, when a PDF is attached,
`POST /api/v1/documents/upload` (T-051) first.

**Acceptance criteria (all must pass):**

- Autocomplete works for top 50 NSE stocks
- PDF upload accepts <10MB
- Triggers `POST /analysis/start`

**Two things worth knowing before reviewing this, both explained in code comments too**

1. **The "top 50 NSE stocks" list is a static, hand-maintained dataset**
   (`src/data/nseTop50.ts`), not a live market-cap ranking pulled from an
   API. Checked the project's API list
   (`AIRP_Project_Overview_Updated.docx` section 6) first: yFinance gives
   price/financials for a symbol you already know, it is not a
   searchable ticker directory, and there is no other free API this
   stack already integrates with that lists NSE symbols by market cap.
   A fixed list of 50 large, well-known NSE companies is the pragmatic,
   zero-cost way to satisfy the literal acceptance criterion today. If
   market caps shift enough to matter, that file is a plain array to
   edit directly -- there is deliberately no dynamic fetch/cache layer
   for it.
2. **Selecting an autocomplete option sends `ticker`/`exchange`
   explicitly**, not just `company_name`. This matters because
   `backend.services.analysis`'s name-resolution table
   (`_COMPANY_NAME_OVERRIDES`) only covers about 15 companies -- but
   `AnalysisStartRequest`'s own docstring already anticipates exactly
   this case: _"ticker and exchange are optional overrides for callers
   (e.g. a future autocomplete-driven frontend) that already know the
   exact Yahoo Finance symbol and want to skip resolution entirely."_
   Sending the explicit ticker from the selected option means all 50
   companies resolve correctly, not just the ~15 already in the
   backend's lookup table.

**In scope:** `AnalysisPage` (rewritten), `CompanyAutocomplete`,
`PdfUploadField`, `src/data/nseTop50.ts`, `startAnalysis` /
`uploadDocument` added to `src/api/analysis.ts`, an
`analysisInputSchema` + PDF validation helpers, and tests for all of it.
`/analysis` is now wrapped in `ProtectedRoute` (starting an analysis
needs a Bearer token).

**Explicitly out of scope:**

- The live 8-agent progress viewer (WebSocket-driven) -- T-059. On
  success, this form navigates straight to the existing
  `/analysis/:jobId/result` placeholder from T-057; T-059/T-061 make
  that page actually show something while/after the pipeline runs.
- A real ticker-search/directory API -- see scope note 1 above.
- Making `GET /auth/me` or any other endpoint accept the httpOnly
  cookie -- unrelated to this task; still the known, documented T-056
  limitation.

---

## What Was Built

### `src/data/nseTop50.ts` (new)

50 large, well-known NSE-listed companies (`{ name, ticker, exchange }`),
`ticker` carrying the exact Yahoo Finance `.NS` suffix
`AnalysisStartRequest.ticker` expects. See scope note 1 above for why
this is static.

### `src/lib/validation/analysisSchemas.ts` (new)

`analysisInputSchema` -- a zod schema for just the company selection
(`{ company: {name, ticker, exchange: 'NSE'} | null }`), validated with
a plain boolean `.refine()` rather than a type-predicate refine
specifically so `z.infer` keeps `company: NseCompany | null` (a
type-predicate refine narrows the _inferred_ type to non-null, which
would make `defaultValues: { company: null }` a type error -- the same
class of subtlety `RegisterPage`'s `confirmPassword` refine in T-056
already sidestepped the same way). The optional PDF is validated
separately via two plain functions, `isPdfFile` and
`isPdfWithinSizeLimit` (`MAX_PDF_UPLOAD_BYTES = 10 * 1024 * 1024`) --
a `File` object doesn't bind to a zod schema through react-hook-form's
`register()` the way a text field does, and these two checks are simple
enough that a couple of functions read at least as clearly as a
`z.instanceof(File)` chain wired through a `Controller` for a field
this shape.

### `src/components/analysis/CompanyAutocomplete.tsx` (new)

A hand-rolled ARIA combobox (the W3C APG combobox-with-listbox pattern)
-- no combobox/autocomplete package was already a dependency, and
`npm install`-ing one is not verifiable in this environment (same
constraint every earlier AIRP frontend task has worked within). Arrow
keys move a highlighted option, Enter selects it, Escape closes the
popup, and option clicks use `onMouseDown` + `preventDefault` (not
`onClick` alone) so the input never blurs before the click registers --
the standard fix for a classic combobox bug. Filters by name or ticker
substring, capped at 8 visible results. Visually matches
`src/components/ui/Input.tsx`'s label/box/error layout without
extending `Input` itself (`Input` has no concept of a popup listbox).

### `src/components/analysis/PdfUploadField.tsx` (new)

A visually-hidden native `<input type="file">` behind a styled
`<label>` trigger ("Choose PDF"), a filename + size preview once a file
is chosen, a Remove action, and an inline error slot. Contains no
validation logic itself -- `AnalysisPage.tsx` calls `isPdfFile` /
`isPdfWithinSizeLimit` on selection and passes the resulting error
string down.

### `src/api/analysis.ts` (extended)

Two new functions alongside T-057's `fetchAnalysisHistory`:

- **`startAnalysis`** -- `POST /api/v1/analysis/start` with
  `company_name`/`ticker`/`exchange`, `Authorization: Bearer` header.
- **`uploadDocument`** -- `POST /api/v1/documents/upload` as
  `multipart/form-data`. Deliberately does **not** set a `Content-Type`
  header by hand -- the browser fills in the `multipart/form-data;
boundary=...` value itself when given a `FormData` body, and
  overriding that by hand is a classic bug (the boundary actually
  written into the body would no longer match a hand-set header, and
  the backend's multipart parser would see zero parts).

### `src/pages/AnalysisPage.tsx` (rewritten)

`react-hook-form` + `Controller` wires `CompanyAutocomplete` to
`analysisInputSchema`; the PDF file is separate local component state
(not part of the RHF-managed values), validated on selection. Submit
order when a PDF is attached: **upload first, then start the
analysis** -- see the file's own docstring for why (a race between the
pipeline's News Sentiment/Macro Economist agents querying ChromaDB and
the upload finishing embedding), and the form refuses to start the
analysis at all if the upload the user explicitly asked for fails. On
success, navigates to `/analysis/{job_id}/result` (T-057's placeholder;
T-059/T-061 make it real).

### `src/routes/AppRoutes.tsx` (modified)

`path="analysis"` is now wrapped in `ProtectedRoute`. A logged-out
visitor clicking "Run a live analysis" (the T-055 landing-page CTA) now
redirects to `/login` and returns to `/analysis` automatically after
logging in, via the same `location.state.from` mechanism `LoginPage`
already implements from T-056 -- no changes needed there.

### Testing

`frontend/src/test/`:

- **`nseTop50.test.ts`** -- exactly 50 entries, unique tickers, every
  ticker `.NS`-suffixed, every entry has `exchange: 'NSE'` and a
  non-empty name.
- **`analysisSchemas.test.ts`** -- the company schema accepts a
  selection and rejects `null`/a non-NSE exchange; `isPdfFile` accepts
  `application/pdf` and `application/octet-stream`, rejects other
  types; `isPdfWithinSizeLimit` accepts exactly the 10MB boundary and
  rejects one byte over.
- **`CompanyAutocomplete.test.tsx`** -- shows options on focus, filters
  by name and by ticker, selecting by click or by keyboard (arrow +
  Enter) calls `onChange` with the full company object, renders a given
  error.
- **`PdfUploadField.test.tsx`** -- empty state, filename/size preview,
  Remove clears the file, selecting via the native input calls
  `onChange`, a given error replaces the default hint.
- **`analysisApi.test.ts`** (extended) -- `startAnalysis`'s request
  body/headers and error handling; `uploadDocument`'s `FormData` fields,
  the _absence_ of a hand-set `Content-Type` header, and error handling
  (including a 413-style oversized-upload response).
- **`AnalysisPage.test.tsx`** (rewritten) -- validation error with no
  company selected; a successful submit posts the right body and
  navigates to the result page; the backend's error message renders on
  failure; an oversized PDF shows its error and disables the submit
  button; attaching a valid PDF uploads it _before_ starting the
  analysis (asserted via call order); a failed upload prevents
  `startAnalysis` from being called at all.

### CI

No workflow changes, no new dependencies (`react-hook-form`, `zod`,
`@hookform/resolvers` were already present from T-053; the combobox is
hand-rolled specifically to avoid needing a new package -- see
`CompanyAutocomplete.tsx`'s docstring). Both endpoints this task
consumes (`POST /api/v1/analysis/start`, T-047;
`POST /api/v1/documents/upload`, T-051) already exist and are already
tested; nothing backend changes here.

---

## How It Was Tested / Verified

Backend is untouched -- no backend commands needed beyond confirming
`POST /api/v1/analysis/start` and `POST /api/v1/documents/upload`
already pass their existing T-047/T-051 tests (they do; nothing here
changes them).

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

(Use `python -m uvicorn`, not the `uvicorn.exe` shim, if Windows App
Control blocks it -- see T-056's doc.)

1. `cd frontend && npm run dev`, log in, navigate to `/analysis`.
2. Type "info" into the company field: confirm "Infosys" appears in the
   dropdown. Clear it and type "TCS": confirm "Tata Consultancy
   Services" appears. Use the arrow keys + Enter to select an option
   without touching the mouse.
3. Click "Start Analysis" with no company selected: confirm "Select a
   company from the list." appears under the field and no request is
   sent (check the Network tab).
4. Select a company and click "Start Analysis" with no PDF attached:
   confirm a `POST /api/v1/analysis/start` request fires in the Network
   tab and you're redirected to `/analysis/{job_id}/result`.
5. Attach a PDF larger than 10MB: confirm "PDF must be smaller than
   10MB." appears and the "Start Analysis" button is disabled.
6. Attach a real PDF under 10MB, select a company, and submit: confirm
   in the Network tab that `POST /api/v1/documents/upload` fires
   _before_ `POST /api/v1/analysis/start`, and both succeed.
7. Stop the backend and try submitting: confirm a readable error message
   appears in the form rather than a blank screen or unhandled
   exception.
8. Log out, then click "Run a live analysis" on the landing page
   (`/`): confirm you're redirected to `/login`, and that logging in
   from there sends you to `/analysis` (not `/dashboard`).

---

## Git Workflow (exact commands)

```bash
# 0) Start from an up-to-date main
git checkout main
git pull origin main

# 1) Create the feature branch
git checkout -b feat/ui-analysis-input

# 2) (do the work -- files listed above)

# 3) Verify (see "How It Was Tested" above)
cd frontend
npm ci
npm run lint:fix && npm run format
npm run type-check && npm run lint && npm run format:check
npm run test:run && npm run build
cd ..

# 4) Stage and commit (re-stage after auto-fixers ran)
git add frontend/src/data/nseTop50.ts \
        frontend/src/types/analysis.ts \
        frontend/src/api/analysis.ts \
        frontend/src/lib/validation/analysisSchemas.ts \
        frontend/src/components/analysis/ \
        frontend/src/pages/AnalysisPage.tsx \
        frontend/src/routes/AppRoutes.tsx \
        frontend/src/test/nseTop50.test.ts \
        frontend/src/test/analysisSchemas.test.ts \
        frontend/src/test/CompanyAutocomplete.test.tsx \
        frontend/src/test/PdfUploadField.test.tsx \
        frontend/src/test/AnalysisPage.test.tsx \
        frontend/src/test/analysisApi.test.ts \
        docs/week-16/T-058-Build-Analysis-Input-Page.md
git commit -m "feat(analysis): build analysis input page with company autocomplete and PDF upload"

# If pre-commit reformats anything, re-stage and recommit (two-commit pattern):
#   git add -A && git commit -m "feat(analysis): build analysis input page with company autocomplete and PDF upload"

# 5) Push and open the PR
git push -u origin feat/ui-analysis-input
```

**Commit message:**

```
feat(analysis): build analysis input page with company autocomplete and PDF upload
```

**PR title:**

```
feat(analysis): implement Analysis Input page with NSE autocomplete, PDF upload, and validation
```

**PR description:**

```markdown
## Summary

Replaces the T-055 /analysis placeholder with the real input form: an
accessible company-search combobox over a static top-50 NSE list, an
optional PDF upload (<=10MB, validated client-side), and a "Start
Analysis" button that calls the existing POST /api/v1/analysis/start
(T-047) -- uploading the PDF to POST /api/v1/documents/upload (T-051)
first when one is attached. /analysis is now a protected route. See the
linked doc (docs/week-16/T-058-Build-Analysis-Input-Page.md) for why the
top-50 list is a static dataset and why selecting an option sends an
explicit ticker/exchange override rather than relying on the backend's
~15-company name-resolution table.

## Changes

- `src/data/nseTop50.ts` (new static dataset)
- `src/lib/validation/analysisSchemas.ts` (company schema + PDF
  validation helpers)
- `src/components/analysis/{CompanyAutocomplete,PdfUploadField}.tsx`
  (new, hand-rolled -- no new dependency)
- `src/api/analysis.ts` -- adds `startAnalysis` and `uploadDocument`
- Rewrites `src/pages/AnalysisPage.tsx`; wraps `path="analysis"` in
  `ProtectedRoute` in `src/routes/AppRoutes.tsx`
- No new dependencies -- react-hook-form/zod/@hookform-resolvers already
  present since T-053

## Testing

- [x] Unit tests added / updated -- 6 new/extended frontend test files
      covering the dataset, schema/validation helpers, both new components,
      the extended API client, and the full page (validation, success path,
      error path, oversized-PDF gating, upload-before-start ordering,
      upload-failure short-circuit)
- [x] Integration tests pass (backend untouched; T-047/T-051's existing
      tests are unaffected)
- [x] Manual smoke test performed against a running backend -- see the
      8-step walkthrough in the doc (autocomplete filtering, keyboard
      selection, empty-selection validation, successful start + redirect,
      oversized-PDF rejection, upload-then-start Network-tab ordering,
      backend-down error handling, and the logged-out redirect round-trip)

`npm run type-check`, `npm run lint`, `npm run format:check`,
`npm run test:run`, and `npm run build` all pass locally.

## LangSmith Trace

n/a -- no agent code touched.

## Screenshots

<paste terminal output of the passing checks, a screenshot of the
autocomplete dropdown open with a filtered result, and a screenshot of
the oversized-PDF error state>

## Related Issues

Closes #<issue-number>
```

---

## Notes for the Next Task

- **T-059 (live Agent Progress viewer)** is this form's natural next
  consumer: once `startAnalysis` returns `job_id`, the WebSocket hook
  already built in T-049 (`useAnalysisStream`) can open
  `WS /api/v1/analysis/{job_id}/stream` using the same in-memory
  `accessToken` this page already reads from `useAuth()`. Consider
  whether `AnalysisPage`'s post-submit `navigate()` target should change
  from `/analysis/{job_id}/result` to a dedicated progress route once
  that task starts, or whether `/result` itself grows a "still running"
  state that renders the live viewer until the job completes -- either
  is reasonable, but decide it explicitly rather than defaulting to
  whichever placeholder happens to exist first.
- **`src/data/nseTop50.ts` is a static list.** If a real ticker-search
  API is ever integrated (see scope note 1), replace the list's role in
  `CompanyAutocomplete` with a debounced query against it, but keep the
  component's `options`/`onChange` contract the same so
  `AnalysisPage.tsx` doesn't need to change.
- Next: **T-059 -- Build live Agent Progress viewer**, per the master
  task list.
