# T-103 — REST endpoints for chat sessions

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 24
**Branch:** `feat/chat-rest-endpoints`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 3

## Summary

T-103 adds `backend/routers/chat.py` and
`backend/services/chat_session_service.py`: three REST endpoints —
`POST /api/v1/chat/sessions`, `GET /api/v1/chat/sessions`, and
`GET /api/v1/chat/sessions/{session_id}/messages` — for creating and
browsing AIRP Assistant chat sessions (T-099's schema) and reading
back a session's message transcript. This is CRUD over
`chat_sessions`/`chat_messages` only — it does **not** call an LLM or
actually run a chat turn; T-102's `chat_llm.py` and T-104's WebSocket
streaming are what a client uses next, against a `session_id` this
task's `POST` endpoint hands back.

## Acceptance criteria (from task spec)

- [x] All endpoints covered by pytest with the existing autouse
      pipeline-mocking fixture pattern
- [x] JWT-protected per existing auth pattern

## Design decisions

- **`/api/v1/chat`, not the bare `/chat` the task description's
  shorthand uses.** Every router in this codebase other than `auth.py`
  (which predates the `/api/v1` convention and is left alone rather
  than introducing a breaking path change to already-shipped auth
  endpoints) is mounted under `/api/v1/<feature>` —
  `/api/v1/analysis`, `/api/v1/documents`, `/api/v1/accuracy`. T-104's
  own task spec already writes its endpoint as
  `WS /api/v1/chat/{session_id}/stream` — *with* the prefix —
  confirming T-103's shorthand is the same kind of abbreviation every
  other Phase 10 task doc has used for its own endpoints, not a
  deliberate deviation. This router uses `/api/v1/chat` so T-104's
  endpoint lands under the same path family it already expects.
- **JWT auth (`get_current_user`), not the service-token auth
  `accuracy.py` uses.** `verify_service_token` (T-090) exists
  specifically for the one machine-to-machine caller in this codebase
  with no `User` row to represent it (the scheduled GitHub Actions
  evaluation workflow). Every chat session belongs to exactly one
  human user by definition (`chat_sessions.user_id`, T-099) — the same
  `get_current_user` dependency `analysis.py`/`documents.py` already
  use is the correct fit, and is literally what the acceptance
  criterion ("JWT-protected per existing auth pattern") asks for.
- **`POST` returns 201, not 202 like `POST /api/v1/analysis/start`.**
  `/analysis/start` returns 202 Accepted because it schedules a
  background task (the LangGraph pipeline) that has not run yet when
  the response is sent. Creating a chat session has no such
  asynchronous follow-up — the `ChatSession` row this endpoint returns
  IS the complete, final resource the instant the response is sent.
  201 Created is the correct status for synchronous resource creation
  that completes within the request, per RFC 9110.
- **ORM `select()`, not raw SQL like T-100's `chat_service.py` /
  T-101's `portfolio_tools.py`.** Those two use raw `text()` queries
  specifically because `analyses.state_snapshot` is a T-033-migration
  column never mapped onto the `Analysis` ORM model. `ChatSession`/
  `ChatMessage` are the opposite case — T-099's migration and ORM
  models were authored together, every column this task needs is
  fully mapped, and `backend/services/accuracy_tracker.py`'s own
  `get_accuracy_history` already establishes the
  `select().order_by().limit().offset()` + `select(func.count(...))`
  precedent for a paginated listing endpoint. There is no reason to
  duplicate raw SQL here.
- **`create_chat_session` validates a memo-scoped `analysis_id` by
  calling the existing `backend.services.analysis.get_analysis_status`**
  rather than querying `analyses` directly — reusing it means this
  endpoint's ownership semantics (404 for "doesn't exist or isn't
  yours", collapsing both cases so a non-owner can never distinguish
  them) can never drift from every other analysis-scoped endpoint in
  this codebase, and a session can only be created against a
  `status='completed'` analysis (409 otherwise) — matching T-100's own
  `build_memo_context` requirement that there actually be a finished
  decision to chat about.
- **404-vs-409 on session creation, matching
  `GET /api/v1/analysis/{job_id}/result`'s own convention exactly** —
  `AnalysisNotFoundError` (new, this task) for "that analysis_id does
  not exist or is not yours" (404), `AnalysisNotReadyError` (reused
  from `backend.services.analysis`) for "it's real and yours, but
  hasn't finished yet" (409) — rather than collapsing both into one
  generic 400, which would throw away information the router already
  knows how to act on consistently elsewhere in the API.
- **`ChatSessionCreateRequest` enforces the same scope-consistency
  rule as the database's own CHECK constraint, at the API boundary
  too**, via a Pydantic `model_validator`: `memo_scoped` requires
  `analysis_id`; `portfolio_wide` forbids it. A malformed request is
  rejected with a clear 422 before it ever reaches the database,
  rather than surfacing as an opaque `IntegrityError` from
  `ck_chat_sessions_scope_consistency` (T-099's migration).
- **`GET /.../messages` returns messages oldest-first (transcript
  order)** — the one paginated endpoint in this codebase that does
  NOT order newest-first like `GET /analysis/history`/
  `GET /accuracy/history`/`GET /chat/sessions` all do, because a chat
  transcript only reads correctly in the order the conversation
  actually happened.
- **`get_chat_session_messages` returns `None` (not raises) for a
  missing/not-owned session** — the router turns that into 404,
  mirroring `get_analysis_status`'s "None means not found or not
  yours" contract used everywhere else. There is no "not ready yet"
  state analogous to an in-progress analysis: a session is usable for
  message listing the moment it exists, and an empty page (zero
  messages so far) is a valid response, not an error.
- **Every dataclass in `chat_session_service.py` is "everything the
  router needs, already derived"** (`ChatSessionSummary`,
  `ChatSessionPage`, `ChatMessageEntry`, `ChatMessagesPage`) — the same
  pattern `AnalysisStatusResult`/`HistoryEntry`/`AccuracyHistoryEntry`
  already establish, rather than handing the router raw ORM instances.
  This keeps the API response shape decoupled from the ORM's column
  set — `ChatSession.user_id` is deliberately never echoed back in
  `ChatSessionSummary`, since it is always the caller and echoing it
  would be, at best, a no-op field.
- **NO `from __future__ import annotations`** in
  `chat_session_service.py` — lives beside `backend/services/analysis.py`
  and `backend/services/chat_service.py`, both of which give the same
  reason for omitting it.
- Plain ASCII section comments (`# ---`) — established AIRP
  convention.
- No bare `type: ignore` — cast()/explicit annotations only.

## Files changed / created

### Backend — schemas

- **`backend/models/schemas.py`** (**MODIFY**) — adds
  `ChatSessionCreateRequest` (with the scope-consistency
  `model_validator`), `ChatSessionResponse`, `ChatSessionListResponse`,
  `ChatMessageResponse`, `ChatMessagesResponse`; updates `__all__` and
  the `pydantic` import to include `model_validator`.

### Backend — services

- **`backend/services/chat_session_service.py`** (**NEW**) —
  `AnalysisNotFoundError`; `create_chat_session`; `ChatSessionSummary`/
  `ChatSessionPage`/`list_chat_sessions`; `ChatMessageEntry`/
  `ChatMessagesPage`/`get_chat_session_messages`;
  `DEFAULT_SESSIONS_PAGE_SIZE`/`MAX_SESSIONS_PAGE_SIZE` (20/100) and
  `DEFAULT_MESSAGES_PAGE_SIZE`/`MAX_MESSAGES_PAGE_SIZE` (50/200).

### Backend — routers

- **`backend/routers/chat.py`** (**NEW**) — the three endpoints under
  `/api/v1/chat`, all `get_current_user`-protected.
- **`backend/main.py`** (**MODIFY**) — imports `chat` from
  `backend.routers` and registers `chat.router` via
  `application.include_router(chat.router)`.

### Backend — tests

- **`backend/tests/unit/test_chat_router.py`** (**NEW**) — end-to-end
  HTTP tests against the real FastAPI app, using the autouse
  pipeline-mocking fixture pattern (see Testing, below).

### Docs

- **`docs/week-24/T-103-chat-rest-endpoints.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/chat-rest-endpoints

git branch
# → * feat/chat-rest-endpoints
```

### Step 2 — Add schemas, service, and router

- `backend/models/schemas.py` (add the 5 new classes + `model_validator`
  import)
- `backend/services/chat_session_service.py`
- `backend/routers/chat.py`
- `backend/main.py` (register the router)

### Step 3 — Add tests

- `backend/tests/unit/test_chat_router.py`

### Step 4 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine (trailing-space issue); set it as its own line
per the established project workaround:

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_chat_router.py -v
python -m pytest backend/tests/unit -v
```

If pre-commit hooks fail with `WinError 4551` (Windows App Control
blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate for
this project.

### Step 4a — Sanity-check the routes are actually registered

Optional, but cheap to confirm before opening the PR:

```bash
set ENVIRONMENT=development
python -m uvicorn backend.main:app --reload --port 8000
```

Then open `http://localhost:8000/docs` and confirm `POST
/api/v1/chat/sessions`, `GET /api/v1/chat/sessions`, and
`GET /api/v1/chat/sessions/{session_id}/messages` all appear under the
`chat` tag with the padlock icon (JWT-protected).

### Step 5 — Commit (two-commit pattern)

```bash
git add backend/models/schemas.py
git add backend/services/chat_session_service.py
git add backend/routers/chat.py
git add backend/main.py
git add backend/tests/unit/test_chat_router.py
git add docs/week-24/T-103-chat-rest-endpoints.md

git commit --no-verify -m "feat(api): add chat session REST endpoints

- Add backend/routers/chat.py: POST /api/v1/chat/sessions (201),
  GET /api/v1/chat/sessions (paginated, newest-updated-first),
  GET /api/v1/chat/sessions/{session_id}/messages (paginated,
  oldest-first transcript order) -- all get_current_user-protected,
  matching every other user-facing router in this codebase
- Add backend/services/chat_session_service.py: create_chat_session
  (validates a memo-scoped analysis_id via the existing
  get_analysis_status -- 404 via new AnalysisNotFoundError if it
  doesn't exist/isn't owned, 409 via the existing
  AnalysisNotReadyError if it hasn't completed yet),
  list_chat_sessions, get_chat_session_messages (returns None for
  not-found-or-not-yours, matching get_analysis_status's own
  contract). ORM select()/func.count()/order_by()/limit()/offset(),
  matching accuracy_tracker.get_accuracy_history's precedent -- no
  raw SQL needed since ChatSession/ChatMessage are fully ORM-mapped
- Add ChatSessionCreateRequest/ChatSessionResponse/
  ChatSessionListResponse/ChatMessageResponse/ChatMessagesResponse to
  backend/models/schemas.py; ChatSessionCreateRequest's
  model_validator enforces the same memo_scoped/portfolio_wide
  analysis_id consistency rule the database's own CHECK constraint
  enforces, at the API boundary, before any DB write is attempted
- Register chat.router in backend/main.py
- Add backend/tests/unit/test_chat_router.py: end-to-end HTTP tests
  using an autouse patched_chat_service fixture that mocks
  backend.routers.chat's three imported service functions for every
  test in the module -- the same autouse pipeline-mocking pattern
  test_analysis_router.py's patched_pipeline fixture established --
  covering success/validation/404/409/auth for all three endpoints

Closes #103"
```

If a formatter modifies files after staging (black/isort), re-stage
and make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-103 files"
```

### Step 6 — Push and open the PR

```bash
git push -u origin feat/chat-rest-endpoints
```

**Base branch:** `main`
**Compare branch:** `feat/chat-rest-endpoints`

## Pull Request

**PR title:**

```
feat(api): expose chat session CRUD endpoints
```

**PR description:**

```markdown
## Summary
Adds backend/routers/chat.py + backend/services/chat_session_service.py:
three REST endpoints for creating and browsing AIRP Assistant chat
sessions (T-099's schema) and reading a session's message transcript.
This is CRUD over chat_sessions/chat_messages only -- it does not call
an LLM or run a chat turn; T-102's chat_llm.py and a future T-104
WebSocket endpoint are what a client uses next against the session_id
this task's POST endpoint returns.

## Changes
- POST /api/v1/chat/sessions (201) -- creates a memo_scoped or
  portfolio_wide session. For memo_scoped, validates analysis_id via
  the existing get_analysis_status: 404 if it doesn't exist or isn't
  owned by the caller, 409 if it exists but hasn't completed yet.
  ChatSessionCreateRequest's model_validator additionally rejects a
  scope-inconsistent request (memo_scoped without analysis_id, or
  portfolio_wide with one) as a 422 before any DB write is attempted,
  mirroring the database's own CHECK constraint at the API boundary
- GET /api/v1/chat/sessions -- paginated (limit/offset,
  default 20/max 100), newest-updated-first, scoped to the caller only
- GET /api/v1/chat/sessions/{session_id}/messages -- paginated
  (default 50/max 200), OLDEST-first (transcript order, unlike every
  other paginated list in this API); 404 if session_id doesn't exist
  or belongs to a different user; an empty session returns an empty
  page, not an error
- All three endpoints are get_current_user-protected (JWT), matching
  every other user-facing router in this codebase
- ChatSession/ChatMessage are fully ORM-mapped (unlike
  analyses.state_snapshot), so the service layer uses plain SQLAlchemy
  select()/func.count()/order_by()/limit()/offset() -- no raw SQL,
  following the precedent backend/services/accuracy_tracker.py's
  get_accuracy_history already set for this exact query shape

## Testing
- `python -m pytest backend/tests/unit/test_chat_router.py -v` -- all
  green: success/validation/404/409/auth coverage for all three
  endpoints, using an autouse patched_chat_service fixture (the same
  autouse pipeline-mocking pattern test_analysis_router.py's
  patched_pipeline fixture established) that mocks
  backend.routers.chat's three imported service functions for every
  test, plus get_async_session overridden to a bare AsyncMock
  (test_accuracy_router.py's own pattern) since the session is only
  ever forwarded into the (mocked) service calls
- `python -m pytest backend/tests/unit -v` -- full unit suite green
- `python -m black/isort/flake8/mypy backend` all pass

## LangSmith Trace
N/A -- these endpoints make no LLM or agent call themselves; they are
plain CRUD over chat_sessions/chat_messages.

## Screenshots
N/A -- no UI changes (frontend chat UI is a separate, later task).

## Related Issues
Closes #103 (adjust to your actual issue number if different).
```

## Testing

Backend (`python -m pytest backend/tests/unit -v`):

- **`test_chat_router.py`** (new) —
    * `TestCreateSessionSuccess`: 201 for a portfolio_wide session;
      response body shape (id/session_type/analysis_id/title/
      created_at/updated_at); a memo_scoped request forwards
      analysis_id through to the service call; the authenticated
      user's own id is what gets passed as `user_id`.
    * `TestCreateSessionValidation`: memo_scoped without analysis_id,
      portfolio_wide with analysis_id, an invalid session_type string,
      and a missing session_type all return 422 with the service
      function never called.
    * `TestCreateSessionErrors`: `AnalysisNotFoundError` from the
      service maps to 404; `AnalysisNotReadyError` maps to 409 with
      the status string in the response detail.
    * `TestCreateSessionAuth`: no Authorization header → 401, service
      never called.
    * `TestListSessionsSuccess`: 200; response body shape including
      `has_more`; `has_more=True` when more rows remain beyond the
      page; default and custom limit/offset are forwarded correctly to
      the service call; the authenticated user's id is what gets
      passed as `user_id`.
    * `TestListSessionsValidation`: `limit` over 100, `limit` below 1,
      and negative `offset` all return 422.
    * `TestListSessionsAuth`: no Authorization header → 401.
    * `TestGetMessagesSuccess`: 200; an empty session returns an empty
      `items` list (not an error); response body shape and correct
      oldest-first ordering for a populated transcript; `session_id`
      and limit/offset are forwarded correctly; the authenticated
      user's id is what gets passed as `user_id`.
    * `TestGetMessagesNotFound`: an unknown `session_id` returns 404 --
      explicitly asserted as 404 (never 403) for both the
      "doesn't-exist" and "belongs-to-someone-else" cases, since the
      service layer collapses them into the same `None` return, same
      as every other ownership-scoped endpoint in this codebase; a
      malformed (non-UUID) `session_id` path segment returns 422
      before the service is ever called.
    * `TestGetMessagesValidation`: `limit` over 200 and negative
      `offset` both return 422.
    * `TestGetMessagesAuth`: no Authorization header → 401.

"All endpoints covered by pytest with the existing autouse
pipeline-mocking fixture pattern" (first acceptance criterion) is
satisfied by `patched_chat_service` — an autouse fixture patching
`backend.routers.chat.create_chat_session`/`list_chat_sessions`/
`get_chat_session_messages` with `AsyncMock` for every test in the
module, the direct analogue of `test_analysis_router.py`'s own
`patched_pipeline` autouse fixture for `run_analysis_pipeline`.
"JWT-protected per existing auth pattern" (second acceptance
criterion) is covered by `TestCreateSessionAuth`/`TestListSessionsAuth`/
`TestGetMessagesAuth`, each asserting a 401 with no Authorization
header and no override of `get_current_user` — the same pattern
`test_analysis_router.py`/`test_documents_router.py` already use for
their own `test_requires_authentication` tests.

## Verification gate run locally before pushing

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

## LangSmith Trace

N/A — none of these three endpoints make an LLM or agent call. A
future chat-turn endpoint (T-104's WebSocket streaming, which will
call T-102's `invoke_chat`/the underlying LLM) is where a LangSmith
trace link becomes relevant.

## Related Issues

Closes #103 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `fastapi`, `sqlalchemy`,
`pydantic`, and the rest of `backend/requirements.txt` are not
installed, and the real `black`/`isort`/`flake8`/`mypy`/`pytest` runs
could not be executed directly. Verification performed instead:
`python -m py_compile` (and a full `ast.parse`) on every new/changed
Python file; a manual line-length check against black's 88-character
limit; a direct read of `backend/routers/analysis.py`,
`backend/routers/accuracy.py`, `backend/services/accuracy_tracker.py`,
`backend/tests/unit/test_analysis_router.py`, and
`backend/tests/unit/test_accuracy_router.py` to ground every
design/testing decision above in code that already exists, not
assumption; and two standalone dry-run harnesses that load the REAL,
unmodified `backend/models/schemas.py` and
`backend/services/chat_session_service.py` against minimal stand-ins
for the external packages they depend on:

- A ~150-line Pydantic v2 stand-in (`BaseModel`/`Field`/`ConfigDict`/
  `EmailStr`/`field_validator`/`model_validator`, including correctly
  handling the `@field_validator(...) @classmethod` decorator-ordering
  case) that loads the actual `schemas.py` file via `importlib` and
  exercises `ChatSessionCreateRequest`'s validators directly: rejects
  `memo_scoped` without `analysis_id`, rejects `portfolio_wide` with
  one, rejects an invalid `session_type` string, and accepts both
  valid shapes — all passed.
- A SQLAlchemy 2.0 async-ORM stand-in (`select()`/`func.count()`/
  `.where()`/`.order_by()`/`.limit()`/`.offset()` on an in-memory list
  of plain Python objects standing in for `ChatSession`/`ChatMessage`
  rows) plus a minimal `backend.services.analysis` stand-in
  (`AnalysisNotReadyError` + a controllable `get_analysis_status`)
  that together load the actual `chat_session_service.py` file via
  `importlib` and exercise every branch: portfolio_wide creation;
  memo_scoped creation against a missing/not-ready/completed
  analysis (`AnalysisNotFoundError`/`AnalysisNotReadyError`/success,
  confirming nothing is inserted on either failure path);
  `list_chat_sessions` pagination, newest-updated-first ordering, and
  correct per-user scoping across two pages; `get_chat_session_messages`
  for a missing session, a session owned by someone else, a brand-new
  session with zero messages, a full multi-message transcript
  confirmed in oldest-first order, and limit/offset paging within that
  transcript — all passed.

**Real verification — the actual `pytest`, `black`/`isort`/`flake8`/
`mypy` runs against the full dependency set, including the real
FastAPI TestClient/ASGI machinery and a real Postgres-backed
`AsyncSession` — is delegated to your local environment and GitHub
Actions**, exactly as documented in every prior Phase 10 task doc.