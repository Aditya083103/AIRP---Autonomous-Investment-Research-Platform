# T-050 -- Build Result and PDF Endpoints

**Phase:** 5 -- FastAPI Backend
**Week:** 14
**Branch:** `feat/api-results`
**Task status:** Complete

---

## Overview

T-050 closes out the "read side" of the analysis lifecycle that T-047
(trigger), T-048 (poll status), and T-049 (live stream) started: once
a client knows a job has reached `status='completed'`, it now has
three ways to get the actual output.

**Acceptance criteria (all must pass):**
- PDF downloads correctly
- result JSON matches InvestmentDecision schema
- history paginates

**Explicitly out of scope for this task** (separate task, per the
master task list):
- Document upload endpoint (`POST /api/v1/documents/upload`) -> **T-051**

---

## What Was Built

### `GET /api/v1/analysis/{job_id}/result`

Returns the full `InvestmentDecision` produced by the Portfolio
Manager agent -- verdict, conviction score, price target, every
Investment Memo section (executive summary, thesis, bull/bear case,
risk summary, valuation summary), the structured `key_risks`/
`key_catalysts` lists, and the debate-resolution fields
(`contrarian_response`, `debate_rounds_used`, `agent_weights`).

- **Source of truth:** the same `analyses.state_snapshot` JSONB column
  T-033's `_persist_after` already writes after every node. No new
  persistence path -- `portfolio_manager_node` already puts the
  complete `InvestmentDecision.model_dump()` dict into
  `state["decision"]` in the same return value that sets
  `status='completed'`, so this endpoint only ever *reads* something
  that already exists.
- **404** when `job_id` doesn't exist or belongs to a different user
  -- identical not-found semantics to T-048's `GET /status`, for the
  identical reason (never reveal job_id validity to a non-owner).
- **409 Conflict** (not 404) when the job is real and owned by the
  caller but hasn't reached `status='completed'` yet (`pending`,
  `running`, or `failed` before a decision was produced). The response
  body names the actual status so a client doesn't need a second call
  to `GET /status` to understand why.
- **500** (extremely defensive, should never trigger in practice) if
  a `status='completed'` row's snapshot is somehow missing a required
  field (`verdict`, `conviction_score`, `generated_at`) -- logged with
  the job_id and the missing field rather than surfacing a bare
  `KeyError` traceback.

### `GET /api/v1/analysis/{job_id}/memo/pdf`

Streams the branded Investment Memo PDF (T-043) as an
`application/pdf` download with `Content-Disposition: attachment`.

- Reuses T-048's `get_analysis_status` purely as an ownership/existence
  check -- no separate query of its own for that part.
- Resolves the PDF's deterministic on-disk path via the **existing**
  `backend.services.pdf_export.resolve_memo_pdf_path(job_id)` (T-043)
  and checks `Path.is_file()` directly -- filesystem reality is the
  source of truth for "can this be downloaded right now," not
  `state["memo_pdf_path"]` from a potentially-stale snapshot.
- **404** for the same not-found/not-yours reasons as every other
  job_id-scoped route, **and also** when the analysis is real and
  owned but no PDF exists on disk yet -- which can legitimately happen
  even for a `completed` analysis, since T-043's `pdf_export_node`
  degrades to `memo_pdf_path=None` (not a pipeline failure) when
  WeasyPrint isn't installed or rendering itself failed. The Markdown
  memo content remains fully available via `GET /result` regardless.

### `GET /api/v1/analysis/history`

Paginated list of the caller's own past analyses, newest first.

- Defaults to **20** results per page (the acceptance criterion's own
  wording: "user's past 20 analyses"), accepts `limit`
  (1-100)/`offset` query parameters for further pages.
- Joins `analyses` to `companies` for display name/ticker/exchange in
  one round trip, and pulls `verdict`/`conviction_score` straight out
  of the JSONB `state_snapshot` via Postgres's `->>` operator rather
  than loading and `json.loads`-ing the full snapshot in Python for
  every row on a page -- a history list only ever needs two scalar
  fields out of the ~20-field decision dict.
- Each entry includes `verdict`/`conviction_score` as `null` for any
  analysis that hasn't produced a decision yet (pending, running, or
  failed) -- Postgres's `->>` on a path that doesn't exist yields SQL
  `NULL`, which the response surfaces honestly rather than
  fabricating a placeholder.
- Response includes `total_count` and a computed `has_more` boolean so
  a client can render "page X of Y" or disable a "next" control
  without separately re-deriving that arithmetic.
- Never returns another user's analyses -- there is no cross-user
  history endpoint; `user_id` is always the authenticated caller's own.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/services/analysis.py` | **Modified** -- added `AnalysisNotReadyError`, `AnalysisResultData`, `get_analysis_result`, `HistoryEntry`, `HistoryPage`, `get_analysis_history`, `DEFAULT_HISTORY_PAGE_SIZE`, `MAX_HISTORY_PAGE_SIZE` |
| `backend/models/schemas.py` | **Modified** -- added `InvestmentDecisionResponse`, `HistoryEntryResponse`, `HistoryResponse` |
| `backend/routers/analysis.py` | **Modified** -- added `GET /{job_id}/result`, `GET /{job_id}/memo/pdf`, `GET /history` |
| `backend/main.py` | **Modified** -- docstring only (no router-list change; T-050 extends the existing `analysis` router, same as T-048) |
| `backend/tests/unit/test_analysis_result_history_service.py` | **New** -- service-layer unit tests |
| `backend/tests/unit/test_analysis_result_history_router.py` | **New** -- HTTP-layer tests, including a real on-disk PDF via `tmp_path` |
| `docs/week-14/T-050-build-result-and-pdf-endpoints.md` | **New** -- this document |

No other files were modified. `backend/services/pdf_export.py` (T-043)
and `backend/services/state_persistence.py` (T-033) are reused as-is
-- T-050 calls `resolve_memo_pdf_path` and reads `state_snapshot`, but
neither module's own code changed.

---

## Design Decisions & Rationale

**Why 409, not 404, for a job that exists but isn't finished?**
RFC 9110 reserves 404 for "the origin server did not find a current
representation for the target resource" -- which describes the
unknown/not-yours case exactly, but not a job the caller legitimately
owns that simply hasn't reached the requested state yet. 409 Conflict
("the request could not be completed due to a conflict with the
current state of the resource") better describes "ask again once
`status='completed'`" -- a condition the caller resolves by waiting,
not by trying a different `job_id`.

**Why does `GET /memo/pdf` use a plain 404 for "not ready" instead of
mirroring `GET /result`'s 409?** A PDF either exists on disk right now
or it doesn't -- there's no equivalent "the resource exists but lacks
this representation" nuance worth a second status code, since the
file's mere absence is itself indistinguishable from "doesn't exist"
at the filesystem layer this endpoint actually checks.

**Why no new persistence path for the decision?** `state_snapshot`
already contains the complete `InvestmentDecision.model_dump()` the
moment `portfolio_manager_node` runs (T-033/T-041) -- this endpoint
adds zero new writes, only a read of data that already exists for an
entirely different reason (pipeline resumption on failure).

**Why `Path.is_file()` instead of trusting `state["memo_pdf_path"]`?**
The snapshot is a point-in-time JSON blob; the file on disk is ground
truth for "can this be served right now." Checking the filesystem
directly also means this endpoint needs no extra database read beyond
the ownership check `GET /status` already performs --
`resolve_memo_pdf_path` is a pure, deterministic function of `job_id`
alone.

**Why `limit`/`offset` instead of a cursor for history pagination?**
This is a single user's own analyses, paginated for a dashboard table
-- a collection size where `limit`/`offset`'s well-known performance
cliff (the database scanning and discarding every skipped row) never
becomes a practical concern for a portfolio project's realistic usage,
and `limit`/`offset` lets a client jump directly to an arbitrary page,
the natural UI for a table rather than an infinite-scroll feed.

**Why does the history query extract `verdict`/`conviction_score` via
SQL instead of loading the full snapshot in Python?** A history list
only ever needs two scalar fields out of the ~20-field
`InvestmentDecision` dict; letting Postgres's `->>` operator extract
just those two avoids up to 20 wasted `json.loads` calls per page for
fields the response never uses, and Postgres safely returns `NULL`
(not an error) for any row whose snapshot doesn't have a `decision`
key yet.

---

## How T-050 Was Implemented (full workflow)

### 1. Sync with `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/api-results
```

### 2. Confirm the starting point (T-049 already merged)

```bash
git log --oneline -5
grep -n "state_snapshot" backend/services/state_persistence.py
grep -n "resolve_memo_pdf_path" backend/services/pdf_export.py
grep -n "class InvestmentDecision" backend/agents/output_models.py
```

These three confirm the exact reuse points T-050 hooks into: T-033's
JSONB snapshot column, T-043's deterministic PDF path resolver, and
the Portfolio Manager's existing output schema -- none of which T-050
modifies.

### 3. Add the new service-layer functions first, in isolation

Edit `backend/services/analysis.py`:
- Add `AnalysisNotReadyError` (mirrors `backend.services.auth`'s
  existing `InvalidCredentialsError`/`InvalidTokenError` pattern).
- Add `AnalysisResultData`, `_SQL_LOAD_RESULT`, `get_analysis_result`,
  `_extract_decision_from_snapshot`.
- Add `DEFAULT_HISTORY_PAGE_SIZE`, `MAX_HISTORY_PAGE_SIZE`,
  `HistoryEntry`, `HistoryPage`, `_SQL_LOAD_HISTORY_PAGE`,
  `_SQL_COUNT_HISTORY`, `get_analysis_history`.
- Update `__all__` and the module docstring's "What this module does"
  / "Public API" sections.

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_result_history_service.py -v
```

Write `test_analysis_result_history_service.py` alongside it -- mocked
`AsyncSession` objects only, no FastAPI yet.

### 4. Confirm no regression in the existing T-047/T-048 service tests

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_service.py -v
```

This file imports a strict subset of `backend.services.analysis`'s
names, all unchanged -- must still pass unmodified.

### 5. Add the three new Pydantic response schemas

Edit `backend/models/schemas.py`: add `InvestmentDecisionResponse`
(field-for-field matching `backend.agents.output_models.
InvestmentDecision`), `HistoryEntryResponse`, `HistoryResponse`. Update
`__all__`.

### 6. Add the three new router endpoints

Edit `backend/routers/analysis.py`:
- `GET /history` -- `Query(ge=1, le=MAX_HISTORY_PAGE_SIZE)` for
  `limit`, `Query(ge=0)` for `offset`.
- `GET /{job_id}/result` -- catches `AnalysisNotReadyError` -> 409;
  `None` -> 404; defensive `KeyError` catch around
  `InvestmentDecisionResponse` construction -> 500 with a clear log.
- `GET /{job_id}/memo/pdf` -- reuses `get_analysis_status` for the
  ownership check, then `resolve_memo_pdf_path` + `Path.is_file()`,
  then `fastapi.responses.FileResponse`.

Update the module docstring's endpoint list and "why" sections.

### 7. Update `backend/main.py`'s docstring

No router-list change needed (T-050 extends the existing `analysis`
router, identical to how T-048 did) -- only the module docstring's
task-range comment.

### 8. Write the HTTP-layer tests

Create `backend/tests/unit/test_analysis_result_history_router.py`
using `httpx.AsyncClient` + `ASGITransport` (the established pattern),
with a small in-memory fake session
(`_FakeResultHistorySession`) that branches on a distinguishing
substring of each raw `text()` query's own SQL, since this router now
issues four different `text()` queries total (T-048's
`_SQL_LOAD_STATUS` plus T-050's three). `GET /memo/pdf` is tested
against a **real** file written to pytest's `tmp_path`, with
`resolve_memo_pdf_path` monkeypatched to resolve into it -- `FileResponse`
reads an actual file from disk, so a mocked filesystem would not
exercise the real code path.

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_result_history_router.py -v
```

### 9. Run the full existing suite to confirm no regressions

```bash
ENVIRONMENT=test pytest --tb=short -q
```

### 10. Run lint and type checks exactly as CI does

```bash
black backend/
isort backend/
flake8 backend/
mypy backend/
```

Auto-fix and re-stage if needed (standard AIRP two-commit pattern):

```bash
black backend/
isort backend/
```

### 11. Confirm coverage

```bash
ENVIRONMENT=test pytest --cov=backend --cov-report=term-missing -m "not integration" -q
```

### 12. Manual smoke test (optional, requires a running Postgres + a
completed analysis)

```bash
uvicorn backend.main:app --reload --port 8000
```

```bash
TOKEN="<bearer token from POST /auth/login>"
JOB_ID="<a job_id with status=completed, from POST /analysis/start>"

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/analysis/$JOB_ID/result | jq .

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/analysis/$JOB_ID/memo/pdf \
  -o memo.pdf && file memo.pdf

curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/analysis/history?limit=5&offset=0" | jq .
```

Expect: `result` returns the full decision JSON; `memo.pdf` is
identified as a valid PDF; `history` returns up to 5 entries with
`total_count`/`has_more` populated.

### 13. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/services/analysis.py \
        backend/models/schemas.py \
        backend/routers/analysis.py \
        backend/main.py \
        backend/tests/unit/test_analysis_result_history_service.py \
        backend/tests/unit/test_analysis_result_history_router.py \
        docs/week-14/T-050-build-result-and-pdf-endpoints.md
git commit -m "feat(api): add result, PDF, and history endpoints"
```

If black/isort auto-fix anything (standard AIRP two-commit pattern):

```bash
git add .
git commit -m "feat(api): add result, PDF, and history endpoints"
```

On Windows, if a pre-commit hook shim is blocked by Application
Control:

```bash
git commit --no-verify -m "feat(api): add result, PDF, and history endpoints"
```

### 14. Push and open PR

```bash
git push -u origin feat/api-results
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**
```
feat(api): implement analysis result, PDF download, and history endpoints
```

**PR description:**

```markdown
## Summary

Adds the three remaining read endpoints for the analysis lifecycle:
GET /analysis/{job_id}/result (full InvestmentDecision JSON),
GET /analysis/{job_id}/memo/pdf (PDF download), and
GET /analysis/history (paginated, newest-first list of the caller's
own past analyses, defaulting to 20 per page).

## Changes

- backend/services/analysis.py -- added AnalysisNotReadyError,
  AnalysisResultData, get_analysis_result (reads InvestmentDecision
  out of the existing state_snapshot JSONB column, T-033 -- no new
  persistence path); HistoryEntry, HistoryPage,
  DEFAULT_HISTORY_PAGE_SIZE, MAX_HISTORY_PAGE_SIZE, get_analysis_history
  (joins analyses->companies, extracts verdict/conviction_score via
  Postgres's JSONB ->> operator rather than parsing the full snapshot
  per row)
- backend/models/schemas.py -- added InvestmentDecisionResponse
  (field-for-field matching backend.agents.output_models.
  InvestmentDecision), HistoryEntryResponse, HistoryResponse
- backend/routers/analysis.py -- GET /{job_id}/result (404 not-found-
  or-not-yours, 409 if not yet completed, defensive 500 + logged
  KeyError guard for a malformed snapshot); GET /{job_id}/memo/pdf
  (404 either for ownership or for "no PDF on disk yet" -- reuses
  T-043's resolve_memo_pdf_path + Path.is_file() as the source of
  truth rather than trusting a potentially-stale state["memo_pdf_path"]);
  GET /history (Query-validated limit/offset, 1-100 range)
- backend/main.py -- docstring only; no router list change, T-050
  extends the existing analysis router exactly as T-048 did
- backend/tests/unit/test_analysis_result_history_service.py (new) --
  service-layer tests against mocked AsyncSession objects
- backend/tests/unit/test_analysis_result_history_router.py (new) --
  HTTP-layer tests via httpx.AsyncClient + ASGITransport; GET /memo/pdf
  is tested against a REAL file on pytest's tmp_path (FileResponse
  reads actual bytes off disk, so a mock would not exercise the real
  path)

## Testing

- `ENVIRONMENT=test pytest backend/tests/unit/test_analysis_result_history_service.py backend/tests/unit/test_analysis_result_history_router.py -v`
  -- new suites; directly exercise all three T-050 acceptance criteria
- `ENVIRONMENT=test pytest backend/tests/unit/test_analysis_service.py backend/tests/unit/test_analysis_router.py -v`
  -- confirms the additive changes to services/analysis.py and
  routers/analysis.py do not break any existing T-047/T-048 test
- `ENVIRONMENT=test pytest --tb=short -q` -- full existing suite, no
  regressions
- Manual smoke test: triggered a real analysis, waited for
  status=completed, fetched /result (verdict/conviction_score/memo
  sections all present), downloaded /memo/pdf (valid PDF, opens
  correctly), and paged through /history with limit=5
- black --check, isort --check-only, flake8, mypy all run locally
  against new and modified files before pushing

## LangSmith Trace

Not applicable -- this PR adds read-only endpoints over data already
persisted by existing nodes (T-033, T-041, T-043) and does not modify
any agent or LangGraph node business logic. LangSmith tracing remains
disabled project-wide until T-067 (Phase 7 evaluation framework).

## Related Issues

Closes #50
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

With T-050 complete, the full analysis lifecycle now has a read path
for every stage: trigger (T-047), poll (T-048), live stream (T-049),
and final output -- JSON, PDF, or paginated history (T-050).

Next task: **T-051 -- Add document upload endpoint**
(`POST /api/v1/documents/upload`: accept a PDF annual report or
earnings transcript, extract text, embed into ChromaDB, link to the
company so subsequent analyses can retrieve it via RAG). Branch:
`feat/api-upload`.

---

*End of Document | T-050 Workflow | AIRP Week 14*