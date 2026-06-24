# T-047 -- Build Analysis Trigger Endpoint

**Phase:** 5 -- FastAPI Backend
**Week:** 13
**Branch:** `feat/api-analysis-start`
**Task status:** Complete

---

## Overview

T-047 is the first task that connects the FastAPI HTTP layer (T-045,
T-046) to the actual investment-analysis pipeline (Phases 1-4: data
layer, 8 agents, LangGraph orchestration, debate engine, PDF export).
Before this task, the only way to run an AIRP analysis was to call
`backend.graph.graph.get_compiled_graph().invoke(state)` directly from
a script or a test. After this task, an authenticated user can trigger
a full analysis with a single HTTP request.

**Acceptance criteria (all must pass):**
- Endpoint returns `job_id` in <200ms
- Pipeline starts in background
- Job record in DB

**Explicitly out of scope for this task** (separate Phase 5 tasks, per
the master task list):
- `GET /api/v1/analysis/{job_id}/status` -> **T-048**
- `WS /api/v1/analysis/{job_id}/stream` -> **T-049**
- Document upload endpoint -> later T-05x
- A general-purpose, NLP-driven ticker resolver for arbitrary free text
  -- this is a tracked gap in the Planner node design (the LangGraph
  `planner_node` already assumes `ticker`/`company_name` are present on
  `InvestmentState` before the graph runs; see
  `backend/graph/nodes.py::_planner_node_impl`). T-047 resolves company
  input with a small deterministic lookup table (the same pattern
  already used in `backend.agents.valuation_agent._SLUG_OVERRIDES`),
  which is sufficient to satisfy this task's acceptance criteria without
  silently expanding its scope into that separate, larger problem.

---

## What Was Built

### `backend/services/analysis.py` (new)

The business-logic layer backing the endpoint, with **no FastAPI
imports** -- mirrors the `backend/services/auth.py` split from T-046 so
it stays independently testable without an ASGI app.

- **`resolve_company()`** -- turns whatever the caller typed (a bare
  ticker, a company name, an explicit `TCS.NS`-style ticker, or an
  explicit ticker/exchange override) into a canonical
  `TickerResolution(company_name, ticker, exchange)`. Resolution order:
  explicit override -> existing exchange suffix -> known-name lookup
  table -> bare-symbol fallback. Deliberately NOT a general NLP
  resolver (see "Explicitly out of scope" above).
- **`get_or_create_company()`** -- looks up the `(ticker, exchange)`
  pair in the `companies` table (T-016 schema) and inserts a new row on
  first use, so repeat analyses of the same company reuse one `Company`
  row instead of re-resolving and re-inserting every time.
- **`create_analysis_job()`** -- inserts the `analyses` row with
  `status='pending'`. This plus the company lookup above is the *only*
  database work on the request's synchronous path -- what keeps the
  endpoint comfortably under the <200ms acceptance criterion.
- **`run_analysis_pipeline()`** -- the background-task entry point.
  Builds the initial `InvestmentState` (`backend.graph.state`) and runs
  the compiled LangGraph graph via `asyncio.to_thread`, since LangGraph
  nodes are synchronous (T-029 design decision) and the full pipeline
  can take up to ~90 seconds -- running it inline on the request's
  coroutine would block the event loop for every other concurrent
  request. Never raises: any exception escaping the graph is caught,
  logged, and persisted onto the `analyses` row via
  `StatePersistenceService.mark_failed` (already built in T-033),
  mirroring the project-wide "agent/node functions must never raise"
  rule.

### `backend/routers/analysis.py` (new)

```
POST /api/v1/analysis/start
```

HTTP-layer concerns only: validates the request body
(`AnalysisStartRequest`), requires authentication via the existing
T-046 `get_current_user` dependency, calls the three service functions
above in sequence, schedules `run_analysis_pipeline` via FastAPI's
`BackgroundTasks.add_task`, and returns `AnalysisStartResponse` with
`202 Accepted` (the request has been *accepted for processing*, not
completed -- the semantically correct status for an endpoint that
returns before the underlying work is done).

### `backend/models/schemas.py` (modified)

Added two schemas alongside the existing T-046 auth schemas:

- **`AnalysisStartRequest`** -- `company_name` (required, non-blank),
  optional `ticker` / `exchange` overrides. Field validators strip
  whitespace, reject blank `company_name`, normalise `ticker` to
  upper-case, and reject any `exchange` outside `{NSE, BSE}` with a 422.
- **`AnalysisStartResponse`** -- `job_id`, `status`, `company_name`,
  `ticker`, `exchange`. Returned the moment the `analyses` row is
  committed -- before any agent has run.

### `backend/main.py` (modified)

`application.include_router(analysis.router)` added alongside the
existing `health` and `auth` routers. This is the only change to this
file -- the task explicitly keeps router registration centralised here.

### `backend/routers/__init__.py` (modified)

Package docstring updated to list `analysis.py` as a current router
(was previously listed under "planned -- not yet present").

### Tests (new)

- **`backend/tests/unit/test_analysis_service.py`** -- `resolve_company`
  (override path, explicit-suffix path, name-lookup-table path,
  fallback path), `get_or_create_company` (existing-row /
  new-row paths), `create_analysis_job`, `run_analysis_pipeline`
  (success path, graph-raises-an-exception path, and the
  never-raises-even-if-mark_failed-also-raises path). All database
  interactions use mocked `AsyncSession` objects -- no real PostgreSQL
  connection, matching the existing `test_state_persistence.py` pattern.
- **`backend/tests/unit/test_analysis_router.py`** -- full HTTP tests
  via `httpx.ASGITransport` against the real app, with
  `get_async_session` overridden to an in-memory fake session (tracking
  real `Company`/`Analysis` inserts, mirroring T-046's
  `test_auth_router.py::_FakeAsyncSession`), `get_current_user`
  overridden to a fixed `User`, and an **autouse** fixture that patches
  `backend.routers.analysis.run_analysis_pipeline` to an `AsyncMock` for
  every single test in the module -- this guarantees no test in this
  file can ever accidentally trigger a real LangGraph pipeline
  invocation (which would transitively import all 8 agent modules and
  LangGraph itself, and could legitimately run for up to 90 seconds).
  Covers all three acceptance criteria directly: `TestLatency`,
  `TestBackgroundScheduling`, `TestJobPersistence`.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/services/analysis.py` | **New** -- ticker resolution, Company/Analysis persistence, background pipeline invocation |
| `backend/routers/analysis.py` | **New** -- `POST /api/v1/analysis/start` |
| `backend/models/schemas.py` | **Modified** -- added `AnalysisStartRequest` / `AnalysisStartResponse` |
| `backend/main.py` | **Modified** -- registered the analysis router |
| `backend/routers/__init__.py` | **Modified** -- package docstring updated |
| `backend/tests/unit/test_analysis_service.py` | **New** -- service-layer unit tests |
| `backend/tests/unit/test_analysis_router.py` | **New** -- router/HTTP-layer unit tests |
| `docs/week-13/T-047-build-analysis-trigger-endpoint.md` | **New** -- this document |

No other files were modified. `backend/services/state_persistence.py`
(T-033) and `backend/graph/graph.py` / `backend/graph/state.py` (T-029,
T-031-T-034) are reused as-is -- T-047 is the first caller of
`get_compiled_graph()` and `make_initial_state()` outside of tests, but
neither required any change.

---

## Design Decisions & Rationale

**Why a separate `backend/services/analysis.py` instead of putting the
logic directly in the router?** Identical reasoning to T-046's
auth router/service split: the service layer has no FastAPI imports, so
`resolve_company`, `get_or_create_company`, `create_analysis_job`, and
`run_analysis_pipeline` are each independently unit-testable without
spinning up an ASGI app, and the router stays a thin HTTP-translation
layer.

**Why `BackgroundTasks` instead of `asyncio.create_task` directly?**
Starlette's `BackgroundTasks` (the FastAPI-native mechanism) guarantees
the task runs *after* the response has already been sent to the client
-- which is exactly the "returns job_id in <200ms" / "pipeline starts in
background" contract this task's acceptance criteria describe. Calling
`asyncio.create_task` directly inside the handler would schedule the
coroutine on the same event loop without that "after the response" UI
contract, and would also produce a different shutdown/cancellation
story than the one FastAPI's test suite and production ASGI servers
already understand for `BackgroundTasks`.

**Why `asyncio.to_thread` inside `run_analysis_pipeline` instead of
calling `compiled.invoke(state)` directly?** `compiled.invoke()` is a
*blocking* call -- LangGraph nodes in this codebase are synchronous by
design (T-029), and the full 15-node pipeline takes up to ~90 seconds
(documented in `backend/graph/node_profiler.py`'s 30-second per-node
timeout x several sequential stages). If `run_analysis_pipeline`
awaited that blocking call directly on FastAPI's single event loop,
every other concurrent request -- including another user's
`POST /analysis/start`, or a `GET /health` check -- would be frozen for
up to 90 seconds. `asyncio.to_thread` dispatches the blocking call to a
worker thread, keeping the event loop free.

**Why `202 Accepted` instead of `200 OK` or `201 Created`?** The
request is accepted for asynchronous processing, not completed (`200`)
or itself fully representing the created resource's final state
(`201`, more appropriate once the analysis is actually finished).
`202` is the standard HTTP status for "I've queued this; check back
later," which is precisely what `GET /api/v1/analysis/{job_id}/status`
(T-048) and the WebSocket stream (T-049) exist to let the client do.

**Why duplicate the company-name override table instead of importing
`backend.agents.valuation_agent._SLUG_OVERRIDES`?** The `services`
package is a router-facing layer; `agents` is the LangGraph-internal
agent layer. Reaching from `services` into a private (`_`-prefixed)
helper inside a specific agent module would create a coupling between
two layers that have no other dependency on each other, for the sake of
~15 short dictionary entries. Keeping two small copies in sync is
cheaper than that coupling.

**Why does `get_or_create_company` skip the `IntegrityError` race
handling that `backend.routers.auth.register` has for duplicate
emails?** Two concurrent *first-time* analyses of the exact same
brand-new company is a vanishingly rare race for a portfolio project
(unlike duplicate signups, which are common and security-relevant for
auth). Adding the extra retry-on-conflict logic here would be defending
against a near-impossible scenario at the cost of a more complex,
harder-to-read function.

---

## How T-047 Was Implemented (full workflow)

### 1. Sync with `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/api-analysis-start
```

### 2. Confirm the starting point (T-046 already merged)

```bash
git log --oneline -5
ls backend/routers/         # health.py, auth.py, __init__.py
ls backend/dependencies/     # auth.py, common.py, __init__.py
```

`backend/main.py` should currently register only `health.router` and
`auth.router` -- if `analysis.router` already appears here, T-047 was
already merged; stop and check `git log`.

### 3. Add the new schemas

Edit `backend/models/schemas.py`: add `AnalysisStartRequest` and
`AnalysisStartResponse` immediately after the existing T-046 schemas,
and add both new names to the module's `__all__` list. Do **not** add
`from __future__ import annotations` to this file -- the existing
project-wide rule (this module already documents it) breaks Pydantic
v2 union resolution.

### 4. Add the service module

Create `backend/services/analysis.py` with `TickerResolution`,
`resolve_company`, `get_or_create_company`, `create_analysis_job`, and
`run_analysis_pipeline`. No FastAPI imports in this file.

### 5. Add the router

Create `backend/routers/analysis.py` with the `POST /start` handler.
Import `get_current_user` from `backend.dependencies.auth` (T-046) to
require authentication.

### 6. Wire the router into the app

Edit `backend/main.py`:

```python
from backend.routers import analysis, auth, health
...
application.include_router(analysis.router)
```

Edit `backend/routers/__init__.py`'s docstring to move `analysis.py`
from "planned" to "current routers".

### 7. Write the tests

Create `backend/tests/unit/test_analysis_service.py` and
`backend/tests/unit/test_analysis_router.py` following the patterns
established in `test_auth_router.py` / `test_dependencies_auth.py`
(T-046) and `test_state_persistence.py` (T-033). Confirm the
**autouse** `patched_pipeline` fixture in the router test file actually
intercepts `backend.routers.analysis.run_analysis_pipeline` -- run a
single test in isolation first to be sure:

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_router.py::TestLatency -v
```

### 8. Run the full new test files

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_service.py -v
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_router.py -v
```

### 9. Run the full existing suite to confirm no regressions

```bash
ENVIRONMENT=test pytest --tb=short -q
```

### 10. Run lint and type checks exactly as CI does

```bash
black --check backend/
isort --check-only backend/
flake8 backend/
mypy backend/
```

If `black` or `isort` report formatting differences, run them without
`--check` once to auto-fix, then re-stage (the standard AIRP
two-commit pre-commit pattern):

```bash
black backend/
isort backend/
```

### 11. Confirm coverage

```bash
ENVIRONMENT=test pytest --cov=backend --cov-report=term-missing -m "not integration" -q
```

`fail_under = 75` is the project-wide gate (`pyproject.toml`). Two new,
fully-covered modules (`services/analysis.py`, `routers/analysis.py`)
backed by two thorough test files keep this comfortably above
threshold.

### 12. Manual smoke test (optional, requires a running Postgres)

```bash
uvicorn backend.main:app --reload --port 8000
```

Register and log in via `/docs` (T-046 endpoints), copy the access
token, then:

```bash
curl -X POST http://localhost:8000/api/v1/analysis/start \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"company_name\": \"TCS\"}"
```

Expect a `202` response with a `job_id` in well under 200ms, and a new
row visible in the `analyses` table with `status='pending'` (moving to
`'running'` once the Planner node starts, per T-030's
`_planner_node_impl`).

### 13. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/services/analysis.py \
        backend/routers/analysis.py \
        backend/routers/__init__.py \
        backend/models/schemas.py \
        backend/main.py \
        backend/tests/unit/test_analysis_service.py \
        backend/tests/unit/test_analysis_router.py \
        docs/week-13/T-047-build-analysis-trigger-endpoint.md
git commit -m "feat(api): add analysis start endpoint"
```

`mypy` runs at the `manual` stage in pre-commit (Windows Application
Control blocks unsigned `.exe` shims per the established AIRP
workaround), so it will not block this local commit; CI's Linux runner
is the real enforcement gate for it. If black/isort auto-fix anything:

```bash
git add .
git commit -m "feat(api): add analysis start endpoint"
```

If pre-commit's auto-fixing hooks cause the first commit attempt to
abort (the standard AIRP two-commit pattern), simply re-run:

```bash
git add .
git commit -m "feat(api): add analysis start endpoint"
```

On Windows, if a pre-commit hook shim is blocked by Application
Control:

```bash
git commit --no-verify -m "feat(api): add analysis start endpoint"
```

### 14. Push and open PR

```bash
git push -u origin feat/api-analysis-start
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**
```
feat(api): implement POST /analysis/start with background pipeline trigger
```

**PR description:**

```markdown
## Summary

Adds POST /api/v1/analysis/start: the first endpoint that connects the
FastAPI HTTP layer to the actual 8-agent LangGraph investment-analysis
pipeline. Validates the company input, creates an analysis job record
in PostgreSQL with status='pending', and schedules the LangGraph
pipeline to run in the background via FastAPI's BackgroundTasks --
returning the new job_id immediately, well under the 200ms acceptance
criterion.

## Changes

- `backend/services/analysis.py` -- new service module: resolve_company
  (deterministic company-name -> Yahoo Finance ticker resolution,
  same lookup-table pattern as backend.agents.valuation_agent),
  get_or_create_company (find-or-create against the companies table),
  create_analysis_job (inserts the analyses row with status='pending'),
  run_analysis_pipeline (background-task entry point; builds the
  initial InvestmentState and invokes the compiled LangGraph graph via
  asyncio.to_thread so the up-to-90-second pipeline never blocks the
  event loop; never raises -- any failure is persisted via the
  existing T-033 StatePersistenceService.mark_failed)
- `backend/routers/analysis.py` -- new router: POST /start, requires
  authentication via the existing T-046 get_current_user dependency,
  returns 202 Accepted with AnalysisStartResponse
- `backend/models/schemas.py` -- added AnalysisStartRequest (validated
  company_name/ticker/exchange) and AnalysisStartResponse
- `backend/main.py` -- registered the new analysis router
- `backend/routers/__init__.py` -- docstring updated
- `backend/tests/unit/test_analysis_service.py`,
  `test_analysis_router.py` -- new unit test suites covering ticker
  resolution, company/job persistence, background pipeline scheduling
  (with an autouse fixture guaranteeing no test can accidentally invoke
  the real LangGraph pipeline), and the <200ms latency criterion

## Testing

- `ENVIRONMENT=test pytest backend/tests/unit/test_analysis_service.py backend/tests/unit/test_analysis_router.py -v`
  -- new suites, cover all three acceptance criteria directly
  (TestLatency, TestBackgroundScheduling, TestJobPersistence)
- `ENVIRONMENT=test pytest --tb=short -q` -- full existing suite, no
  regressions
- Manual smoke test: registered a user via /auth/register, called
  POST /api/v1/analysis/start with a bearer token, confirmed a 202
  response with job_id in well under 200ms and a new `analyses` row
  with status='pending'
- `black --check`, `isort --check-only`, `flake8`, `mypy` all run
  locally against the new and modified files before pushing

## LangSmith Trace

Not applicable -- this PR adds the HTTP trigger for the pipeline but
does not modify any agent or LangGraph node code. LangSmith tracing
remains disabled project-wide until T-067 (Phase 7 evaluation
framework), per the existing LANGCHAIN_TRACING_V2=false setting.

## Related Issues

Closes #47
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

With T-047 complete, AIRP has its first real end-to-end trigger path:
an authenticated HTTP request now creates a database-backed job and
starts the full 8-agent investment committee pipeline in the
background. The job itself is still a black box to the caller once
started -- there is no way yet to check its progress or retrieve its
result over HTTP.

Next task: **T-048 -- Build analysis status endpoint**
(`GET /api/v1/analysis/{job_id}/status`; returns current phase,
completed nodes, progress percentage, and errors if any; 404 for an
unknown `job_id`). This will read the same `analyses.status`,
`analyses.last_completed_node`, and `analyses.state_snapshot` columns
that T-033's `StatePersistenceService` already writes after every node
-- no new persistence logic should be required, only a read-side
endpoint.

Branch: `feat/api-analysis-status`.

---

*End of Document | T-047 Workflow | AIRP Week 13*
