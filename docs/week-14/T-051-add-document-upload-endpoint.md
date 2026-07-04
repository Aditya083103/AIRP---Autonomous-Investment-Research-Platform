# T-051 -- Add Document Upload Endpoint

**Phase:** 5 -- FastAPI Backend
**Week:** 14
**Branch:** `feat/api-upload`
**Task status:** Complete

---

## Overview

T-051 adds the one remaining FastAPI capability Phase 5 needed before
the test-coverage pass in T-052: a way for a user to upload a PDF
(annual report or earnings-call transcript) so its content becomes
part of AIRP's RAG pipeline, the same `airp_documents` ChromaDB
collection the Phase 1 data layer (T-017) already defined but never
had a producer for until now.

**Acceptance criteria (all must pass):**

- PDF uploads
- text extracted
- embedded in ChromaDB
- queryable by agents in subsequent analyses

**Explicitly out of scope for this task** (separate task, per the
master task list):

- API test suite / coverage pass -> **T-052**

---

## What Was Built

### `POST /api/v1/documents/upload`

Accepts a PDF via `multipart/form-data`, extracts its text, embeds it
into ChromaDB's `airp_documents` collection, and links it to a
resolved `Company` row.

- **Request shape:** `file` (the PDF, `UploadFile`), `company_name`
  (required form field, e.g. `'TCS'` or `'Tata Consultancy
Services'`), plus optional `ticker`/`exchange` override fields --
  the same three-field shape `POST /api/v1/analysis/start` (T-047)
  accepts, deliberately, so "link to company" resolves identically
  for an upload and for an analysis trigger. No JSON request schema
  exists for this route (see `DocumentUploadResponse`'s docstring) --
  a PDF is binary content that does not benefit from a base64-encoded
  JSON envelope when FastAPI's `UploadFile` already streams it
  directly from the multipart body.
- **Text extraction** reuses the **existing**
  `backend.tools.earnings_transcript._extract_text_from_pdf_bytes`
  (T-015) -- pdfminer.six primary, PyPDF2 fallback -- rather than a
  second implementation. This is now the second of two PDF-upload
  entry points sharing the identical extraction code and the
  identical `PDFExtractionError` type.
- **ChromaDB ingestion** is a new function, `ingest_document`, added
  to `backend/db/chroma_client.py` (T-017's module) -- it generalises
  the existing `ingest_transcript`'s chunk-and-store flow to write
  into `COLLECTION_DOCUMENTS` (`airp_documents`) with a configurable
  `doc_type` (`DocumentType.ANNUAL_REPORT` by default, or
  `DocumentType.TRANSCRIPT` for an uploaded earnings call), both of
  which were defined back in T-017 but had no caller until this task.
- **Company linking** reuses the **existing**
  `backend.services.analysis.resolve_company` +
  `get_or_create_company` pair (T-047) -- the exact same resolver a
  later analysis trigger for the same company will use, so an upload
  for `'TCS'` and a subsequent analysis for `'Tata Consultancy
Services'` resolve to one `Company` row, not two.
- **"Queryable by agents in subsequent analyses"** required no new
  agent-facing code: `backend.agents.macro_economist` and
  `backend.agents.sentiment_analyst` already call
  `backend.db.chroma_client.semantic_search` against `COLLECTION_NEWS`
  for their own RAG context (T-021-T-028). This task's job was only to
  make an uploaded document embedded with the same `{company, ticker,
doc_type}` metadata shape that same `semantic_search` function
  already filters on -- a future agent task that wants uploaded annual
  reports calls `semantic_search(..., collection_name=
COLLECTION_DOCUMENTS, company_filter=ticker)` exactly the way the
  two existing agents already call it against `COLLECTION_NEWS`. The
  router/service test suites verify this end-to-end by calling
  `semantic_search` directly against the same collection right after
  an upload and asserting the content comes back.
- **413** (Content Too Large) for an upload exceeding the new
  `settings.max_upload_size_mb` (default 20 MB) -- checked before
  text extraction runs, so an oversized file never reaches the
  (comparatively expensive) pdfminer pass.
- **422** for a blank `company_name`, an unsupported content-type, an
  empty file body, or a well-formed PDF with no extractable text (a
  scanned, image-only document) -- four different "the request itself
  has a content problem, not a parsing failure" cases, distinguished
  from:
- **400** for a PDF that pdfminer/PyPDF2 cannot parse at all (corrupt,
  truncated, or not actually a PDF despite the content-type claiming
  otherwise).

---

## Files Changed

| File                                                 | Change                                                                                                                                                             |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `backend/db/chroma_client.py`                        | **Modified** -- added `ingest_document` (generalises `ingest_transcript` for `COLLECTION_DOCUMENTS`/configurable `DocumentType`)                                   |
| `backend/config.py`                                  | **Modified** -- added `max_upload_size_mb` setting (default 20)                                                                                                    |
| `backend/models/schemas.py`                          | **Modified** -- added `DocumentUploadResponse`                                                                                                                     |
| `backend/services/documents.py`                      | **New** -- `validate_upload_size`, `extract_pdf_text`, `link_document_to_company`, `ingest_uploaded_document`, `UploadResult`, `PDFTooLargeError`, `EmptyPDFError` |
| `backend/routers/documents.py`                       | **New** -- `POST /api/v1/documents/upload`                                                                                                                         |
| `backend/main.py`                                    | **Modified** -- registered the `documents` router                                                                                                                  |
| `backend/routers/__init__.py`                        | **Modified** -- docstring only, moved `documents.py` from "planned" to "current"                                                                                   |
| `backend/tests/conftest.py`                          | **Modified** -- added `max_upload_size_mb` to `test_settings`                                                                                                      |
| `backend/tests/unit/test_documents_service.py`       | **New** -- service-layer unit tests                                                                                                                                |
| `backend/tests/unit/test_documents_router.py`        | **New** -- HTTP-layer tests, including a real in-memory ChromaDB round-trip                                                                                        |
| `docs/week-14/T-051-add-document-upload-endpoint.md` | **New** -- this document                                                                                                                                           |

No other files were modified. `backend/tools/earnings_transcript.py`
(T-015) and `backend/services/analysis.py` (T-047) are reused as-is --
T-051 calls `_extract_text_from_pdf_bytes`, `resolve_company`, and
`get_or_create_company`, but neither module's own code changed.

---

## Design Decisions & Rationale

**Why a new `backend/services/documents.py` rather than adding to
`backend/services/analysis.py`?** Document upload and analysis
triggering are related (both resolve a company) but distinct
concerns. Keeping them in separate service modules mirrors the
existing `auth.py` / `analysis.py` split rather than letting one
service module grow to cover every router -- `documents.py` imports
_from_ `analysis.py` (`resolve_company`, `get_or_create_company`)
rather than duplicating that logic, the same reuse relationship
`routers/documents.py` has with `routers/analysis.py`'s established
patterns.

**Why generalise `ingest_transcript` into a new `ingest_document`
rather than calling `ingest_transcript` directly?**
`ingest_transcript` hard-codes `doc_type=DocumentType.TRANSCRIPT.value`
and writes to `COLLECTION_TRANSCRIPTS` -- the collection reserved for
Screener.in-scraped earnings calls (T-015's other data source).
`ingest_document` writes to the **separate** `COLLECTION_DOCUMENTS`
(`airp_documents`) with a caller-supplied `doc_type`, keeping
user-uploaded content (this task) distinguishable from scraped
content (T-015) at the collection level -- both already existed as
named constants since T-017, just without a producer for the second
one until now.

**Why reuse `_extract_text_from_pdf_bytes` instead of writing a new
PDF-extraction function?** `backend.tools.earnings_transcript`
already has a working, tested pdfminer.six-primary/PyPDF2-fallback
implementation (T-015) for its own `pdf_bytes` upload path. A second
implementation would mean two extraction code paths to keep in sync
and two slightly different failure modes for what is, functionally,
the identical operation: "give me the text inside these PDF bytes."
T-051's `extract_pdf_text` is a thin wrapper that adds exactly one
thing `earnings_transcript.py`'s own callers don't need: raising
`EmptyPDFError` for a no-text result, since a direct upload has no
"fall back to the next data source" option the way a blank Screener.in
transcript scrape does.

**Why does `ingest_uploaded_document` resolve+commit the `Company` row
_before_ calling ChromaDB, rather than the reverse?** If ChromaDB
ingestion ran first and the subsequent `Company` persistence then
failed, the vector store would contain an embedded document pointing
at a `ticker`/`company` that does not (yet, or ever) exist as a row in
PostgreSQL -- a later analysis querying ChromaDB by that ticker would
retrieve orphaned content with no corresponding `Company` to attach
it to in any response. Resolving the company first means the only way
ChromaDB ends up with a chunk is if the company it is linked to
already exists.

**Why 413, not 422, for an oversized upload?** RFC 9110 defines 413
Content Too Large specifically for "the request entity is larger than
limits the server is willing to process" -- exactly
`PDFTooLargeError`'s condition. 422 is reserved for a same-size,
well-formed request whose _content_ the server cannot act on (wrong
content-type, no extractable text) -- a different kind of problem from
a request that is simply too big to read in the first place.

**Why 422, not 400, for a PDF with no extractable text?** The file
itself parsed successfully -- it is well-formed, just commonly a
scanned/image-only document with no embedded text layer. 400 Bad
Request is reserved for `PDFExtractionError`, where the file could not
be parsed _at all_ (corrupt, truncated, or not really a PDF). 422
Unprocessable Entity describes "the request was well-formed but the
server cannot process the contained instructions" more precisely for
a structurally valid PDF that simply has nothing to embed.

**Why accept `application/octet-stream` alongside `application/pdf`?**
Some browsers/HTTP clients report PDFs under the generic binary MIME
type when there is no OS-level PDF file association configured.
Rejecting uploads purely on a client-reported content-type header
would reject genuinely valid PDFs from those clients; the content-type
check here is a cheap first filter, not the only gate -- a file that
is not actually a PDF still fails at the `_extract_text_from_pdf_bytes`
step with a `PDFExtractionError` regardless of what content-type it
claimed.

**Why does `validate_upload_size` run on the in-memory byte count
rather than a streamed partial read?** FastAPI's `UploadFile` does not
expose a reliable pre-read size across every ASGI server/client
combination, so the router reads the full body first (`await
file.read()`) and `ingest_uploaded_document` checks the resulting
`len(pdf_bytes)` as its very first step -- before the meaningfully
more expensive PDF extraction call, even though it is technically
after the read itself.

---

## How T-051 Was Implemented (full workflow)

### 1. Sync with `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/api-upload
```

### 2. Confirm the starting point (T-050 already merged)

```bash
git log --oneline -5
grep -n "COLLECTION_DOCUMENTS\|ANNUAL_REPORT" backend/db/chroma_client.py
grep -n "def resolve_company\|def get_or_create_company" backend/services/analysis.py
grep -n "_extract_text_from_pdf_bytes" backend/tools/earnings_transcript.py
grep -n "python-multipart" backend/requirements.txt
```

These four confirm the exact reuse points T-051 hooks into:
`COLLECTION_DOCUMENTS`/`DocumentType.ANNUAL_REPORT` (defined in T-017,
unused until now), T-047's company resolver, T-015's PDF extractor,
and that `python-multipart` (required for FastAPI file uploads) was
already pinned in `requirements.txt` ahead of this task.

### 3. Add `ingest_document` to `backend/db/chroma_client.py`

Generalises `ingest_transcript`'s chunk-and-store flow: writes to
`COLLECTION_DOCUMENTS` instead of `COLLECTION_TRANSCRIPTS`, accepts a
caller-supplied `doc_type` instead of hard-coding
`DocumentType.TRANSCRIPT`, and derives its deterministic chunk-ID base
from `(ticker, source_filename)` instead of `(ticker, date, source)`.

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_chroma_client.py -v
```

Confirms no regression in the existing T-017 suite (this file is
additive only -- no existing function signature changed).

### 4. Add `max_upload_size_mb` to `backend/config.py`

A new `Settings` field, default `20` (MB), following the exact
`Field(default=..., description=...)` pattern every other tunable in
that module already uses. Added the same field, value `20`, to
`backend/tests/conftest.py`'s `test_settings` fixture for explicitness
(though `model_construct()` would apply the field default either way).

### 5. Add `DocumentUploadResponse` to `backend/models/schemas.py`

No matching `*Request` schema -- the request body is
`multipart/form-data`, validated directly by the route handler's
`UploadFile`/`Form(...)` parameters, not a JSON Pydantic model. Updated
`__all__` and the module docstring's task-range header.

### 6. Write `backend/services/documents.py`

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_documents_service.py -v
```

`validate_upload_size`, `extract_pdf_text` (wraps
`backend.tools.earnings_transcript._extract_text_from_pdf_bytes`),
`link_document_to_company` (wraps `backend.services.analysis.
resolve_company` + `get_or_create_company`), and `ingest_uploaded_
document` (the full pipeline, calling `backend.db.chroma_client.
ingest_document` last). `PDFTooLargeError` and `EmptyPDFError` as the
two new exception types the router translates into HTTP responses.

### 7. Write `backend/routers/documents.py`

`POST /api/v1/documents/upload` -- `UploadFile` + three `Form(...)`
fields, `get_current_user` + `get_async_session` + `get_settings_
dependency` as the three existing dependencies every protected,
DB-touching route in this codebase already uses. Translates
`PDFTooLargeError` -> 413, `PDFExtractionError` -> 400,
`EmptyPDFError` -> 422, plus two router-level 422 checks (blank
`company_name`, unsupported content-type) that never reach the
service layer at all.

### 8. Register the router in `backend/main.py`

```bash
grep -n "include_router" backend/main.py
```

Added `from backend.routers import ... documents ...` and
`application.include_router(documents.router)` alongside the four
existing routers. Updated `backend/routers/__init__.py`'s docstring to
move `documents.py` from "planned" to "current".

### 9. Write the HTTP-layer tests

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_documents_router.py -v
```

Uses `httpx.AsyncClient` + `ASGITransport` (the established pattern)
with a small in-memory fake `AsyncSession`
(`_FakeDocumentsSession`, mirroring `test_analysis_router.py`'s
`_FakeAnalysisSession` for the identical `Company` select/insert
shape) and `backend.services.documents.build_chroma_client` patched to
return a `ChromaClient` backed by an in-memory `EphemeralClient`
(the exact `_MockEF` pattern `test_chroma_client.py` already
established) -- no real sentence-transformer model load, no real
ChromaDB instance, no real pdfminer/PyPDF2 call (that function is
patched per-test instead).

### 10. Run the full existing suite to confirm no regressions

```bash
ENVIRONMENT=test pytest --tb=short -q
```

### 11. Run lint and type checks exactly as CI does

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

### 12. Confirm coverage

```bash
ENVIRONMENT=test pytest --cov=backend --cov-report=term-missing -m "not integration" -q
```

### 13. Manual smoke test (optional, requires a running Postgres + ChromaDB)

```bash
uvicorn backend.main:app --reload --port 8000
```

```bash
TOKEN="<bearer token from POST /auth/login>"

curl -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/TCS_Annual_Report_FY24.pdf;type=application/pdf" \
  -F "company_name=Tata Consultancy Services" \
  http://localhost:8000/api/v1/documents/upload | jq .
```

Expect a `201` with `chunks_ingested > 0` and `characters_extracted`
matching the PDF's actual text length. A follow-up
`semantic_search(query, collection_name=COLLECTION_DOCUMENTS,
company_filter="Tata Consultancy Services")` call (e.g. from a Python
shell) should return the just-ingested chunks.

### 14. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/db/chroma_client.py \
        backend/config.py \
        backend/models/schemas.py \
        backend/services/documents.py \
        backend/routers/documents.py \
        backend/main.py \
        backend/routers/__init__.py \
        backend/tests/conftest.py \
        backend/tests/unit/test_documents_service.py \
        backend/tests/unit/test_documents_router.py \
        docs/week-14/T-051-add-document-upload-endpoint.md
git commit -m "feat(api): add document upload and RAG ingestion endpoint"
```

If black/isort auto-fix anything (standard AIRP two-commit pattern):

```bash
git add .
git commit -m "feat(api): add document upload and RAG ingestion endpoint"
```

On Windows, if a pre-commit hook shim is blocked by Application
Control:

```bash
git commit --no-verify -m "feat(api): add document upload and RAG ingestion endpoint"
```

### 15. Push and open PR

```bash
git push -u origin feat/api-upload
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**

```
feat(api): implement PDF upload with automatic ChromaDB RAG ingestion
```

**PR description:**

```markdown
## Summary

Adds POST /api/v1/documents/upload: accepts a PDF (annual report or
earnings transcript), extracts its text via the existing T-015
pdfminer.six/PyPDF2 extractor, embeds it into ChromaDB's
airp_documents collection (T-017's COLLECTION_DOCUMENTS, unused until
now), and links it to a Company row resolved via the same T-047
resolve_company/get_or_create_company pair POST /analysis/start uses.

## Changes

- backend/db/chroma_client.py -- added ingest_document, generalising
  ingest_transcript's chunk-and-store flow for COLLECTION_DOCUMENTS
  with a configurable DocumentType (ANNUAL_REPORT default, or
  TRANSCRIPT for an uploaded earnings call)
- backend/config.py -- added max_upload_size_mb setting (default 20 MB)
- backend/models/schemas.py -- added DocumentUploadResponse (no
  matching *Request schema -- multipart/form-data, not JSON)
- backend/services/documents.py (new) -- validate_upload_size,
  extract_pdf_text (wraps the existing
  backend.tools.earnings_transcript._extract_text_from_pdf_bytes),
  link_document_to_company (wraps backend.services.analysis.
  resolve_company + get_or_create_company), ingest_uploaded_document
  (full pipeline), PDFTooLargeError, EmptyPDFError
- backend/routers/documents.py (new) -- POST /api/v1/documents/upload;
  413 for oversized uploads, 422 for blank company_name/unsupported
  content-type/empty file/no-extractable-text PDF, 400 for a PDF that
  fails to parse at all
- backend/main.py -- registered the documents router
- backend/routers/**init**.py -- docstring only, documents.py moved
  from "planned" to "current"
- backend/tests/conftest.py -- added max_upload_size_mb to test_settings
- backend/tests/unit/test_documents_service.py (new) -- service-layer
  tests, including a REAL in-memory ChromaDB round-trip (ingest, then
  semantic_search) proving the "queryable by agents" criterion, not
  just a mocked ingest call
- backend/tests/unit/test_documents_router.py (new) -- HTTP-layer
  tests via httpx.AsyncClient + ASGITransport with multipart file
  upload; same real in-memory ChromaDB pattern

## Testing

- `ENVIRONMENT=test pytest backend/tests/unit/test_documents_service.py backend/tests/unit/test_documents_router.py -v`
  -- new suites; directly exercise all four T-051 acceptance criteria
- `ENVIRONMENT=test pytest backend/tests/unit/test_chroma_client.py backend/tests/unit/test_analysis_service.py backend/tests/unit/test_analysis_router.py backend/tests/unit/test_config.py -v`
  -- confirms the additive changes to chroma_client.py and config.py
  do not break any existing T-017/T-047 test
- `ENVIRONMENT=test pytest --tb=short -q` -- full existing suite, no
  regressions
- Manual smoke test: uploaded a real annual report PDF, confirmed
  chunks_ingested > 0 and characters_extracted matched, then ran
  semantic_search against COLLECTION_DOCUMENTS and got the uploaded
  content back
- black --check, isort --check-only, flake8, mypy all run locally
  against new and modified files before pushing

## LangSmith Trace

Not applicable -- this PR adds a plain CRUD/ingestion HTTP endpoint
with no LLM call anywhere in its path (PDF extraction is pdfminer/
PyPDF2, not an agent). LangSmith tracing remains disabled
project-wide until T-067 (Phase 7 evaluation framework).

## Related Issues

Closes #51
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

With T-051 complete, Phase 5's full endpoint surface is in place:
auth (T-046), analysis trigger/status/stream/result/PDF/history
(T-047-T-050), and now document upload (T-051). Only the
acceptance-test pass remains before Phase 5 closes out.

Next task: **T-052 -- Write API tests with pytest** (pytest + httpx:
test all endpoints, auth flows, WebSocket connection, error cases --
invalid ticker, rate limits; target >85% coverage). Branch:
`feat/api-tests`.

---

_End of Document | T-051 Workflow | AIRP Week 14_
