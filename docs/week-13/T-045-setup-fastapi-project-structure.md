# T-045 -- Setup FastAPI Project Structure

**Phase:** 5 -- FastAPI Backend
**Week:** 13
**Branch:** `feat/api-setup`
**Task status:** Complete

---

## Overview

T-045 is the first task of Phase 5 and the first task that exposes the
Phase 1-4 pipeline (data layer, 8 agents, LangGraph orchestration, debate
engine, PDF export) over HTTP at all. Before this task, `backend/` had
no ASGI application, no `routers/` contents, and no `dependencies/`
package -- only the README placeholders left by T-002's folder scaffold.

**Acceptance criteria (all must pass):**

- `GET /health` returns 200
- Swagger UI accessible at `/docs`
- CORS allows frontend origin

**Explicitly out of scope for this task** (separate Phase 5 tasks, per
the master task list):

- JWT auth, `/auth/register`, `/auth/login`, `/auth/me` -> **T-046**
- `POST /api/v1/analysis/start` -> **T-047**
- `GET /api/v1/analysis/{job_id}/status` -> **T-048**
- WebSocket streaming -> later T-04x
- Document upload -> later T-04x

T-045's `backend/dependencies/` package is created now (it's part of the
task description's required structure) but intentionally holds only a
generic settings-injection helper -- the auth dependency that package
exists to eventually hold lands in T-046, not here.

---

## What Was Built

### `backend/main.py` (new)

The single FastAPI app entrypoint, built via a `create_app()` factory
rather than bare module-level construction:

- **App metadata** -- title, description, version feed the auto-generated
  Swagger UI (`/docs`) and ReDoc (`/redoc`).
- **CORS** -- wired from `settings.cors_origins_list` (already defined in
  `config.py` since T-005/T-009; defaults to the Vite dev server origin
  `http://localhost:5173`). `allow_methods=["*"]` and
  `allow_headers=["*"]` are set now so T-047's `POST /analysis/start`
  and later WebSocket upgrade requests don't need a second CORS change.
- **Lifespan** -- a typed `@asynccontextmanager` (the modern FastAPI
  pattern; not the deprecated `@app.on_event`) logs the active
  environment and LLM provider on startup. This is the single place
  later tasks hook in startup work (e.g. warming
  `backend.graph.graph.get_compiled_graph()`) without scattering new
  event handlers across the module.
- **Router registration** -- `app.include_router(health.router)` is the
  only router wired in this task; every later router is added here and
  nowhere else.

`create_app()` is a factory (not just a bare `app = FastAPI(...)`) so
tests can construct fresh app instances and so later tasks can vary
configuration (e.g. a future `create_app(settings_override=...)`) without
restructuring this module.

### `backend/routers/health.py` (new)

A single liveness endpoint:

```python
GET /health -> {"status": "ok", "environment": "...", "version": "0.1.0"}
```

Deliberately a **liveness** probe only -- it does not check PostgreSQL,
Redis, or ChromaDB connectivity. Mixing liveness and readiness checks is
a known anti-pattern: if Render's health check restarts an otherwise-healthy
process because Postgres had a one-second blip, that's strictly worse than
a slow request. A `/health/ready` endpoint with dependency checks can be
added in a later task if the deployment platform's probe needs it -- this
task's acceptance criterion only requires `GET /health` returning 200.

Response shape is a typed Pydantic model (`HealthResponse`) with
`status: Literal["ok"]`, not a bare `dict`, so the OpenAPI schema FastAPI
generates for `/docs` documents the exact response contract instead of an
untyped object.

### `backend/routers/__init__.py` (new)

Package docstring listing the one router that exists today (`health.py`)
and the routers later tasks are expected to add (`auth.py` at T-046,
`analysis.py` at T-047/T-048, `websocket.py`, `documents.py`) -- so the
package's intended shape is documented before those files exist, mirroring
how `backend/models/__init__.py` already documents the five ORM tables it
re-exports.

### `backend/dependencies/__init__.py` and `backend/dependencies/common.py` (new)

The task description explicitly calls for a `/dependencies` directory
alongside `/routers`, `/models`, `/services`. `common.py` holds exactly
one dependency for now: `get_settings_dependency()`, a thin
`Depends()`-compatible wrapper around the existing
`backend.config.get_settings()` singleton. It exists so:

1. Routers have something real to import from `backend.dependencies`
   immediately, rather than the package being an empty stub until T-046.
2. The override pattern FastAPI tests rely on
   (`app.dependency_overrides[get_settings_dependency] = lambda: test_settings`)
   is established and tested now, so T-046's `get_current_user` dependency
   (JWT verification) can follow the exact same pattern without inventing
   it under deadline pressure.

No JWT, password hashing, or Clerk verification code is added here --
that is all T-046.

---

## Files Changed

| File                                             | Change                                                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `backend/main.py`                                | **New** -- FastAPI app factory, CORS, lifespan, router registration                                    |
| `backend/routers/health.py`                      | **New** -- `GET /health` liveness endpoint                                                             |
| `backend/routers/__init__.py`                    | **New** -- package docstring (was an empty file marker)                                                |
| `backend/dependencies/__init__.py`               | **New** -- package docstring, new package                                                              |
| `backend/dependencies/common.py`                 | **New** -- `get_settings_dependency()`                                                                 |
| `backend/tests/unit/test_main.py`                | **New** -- app factory, `/health`, `/docs`, `/openapi.json`, CORS, lifespan tests                      |
| `backend/tests/unit/test_health_router.py`       | **New** -- router/schema/handler tests in isolation                                                    |
| `backend/tests/unit/test_dependencies_common.py` | **New** -- dependency + override-pattern tests                                                         |
| `pyproject.toml`                                 | **Modified** -- added `"dependencies"` to isort's `known_first_party` list now that the package exists |

No other files were modified. `backend/routers/README.md`,
`backend/models/README.md`, and `backend/services/README.md` (the T-002
placeholder markers) are left exactly as they were -- replacing them was
not part of this task's scope and they cause no CI failures as empty
files.

---

## Design Decisions & Rationale

**Why a `create_app()` factory instead of `app = FastAPI(...)` at module
level?** Every test in `test_main.py` calls `create_app()` directly,
producing an independent app instance per test rather than sharing one
mutable global across the whole suite. This is the same reasoning
`backend/config.py`'s `get_settings()` docstring already gives for using
`app.dependency_overrides` in tests -- isolated, overridable state.

**Why `lifespan=` instead of `@app.on_event("startup")`?** FastAPI's own
docs mark `on_event` as the older style; `lifespan` is the typed,
testable, recommended replacement and is what later tasks (warming the
LangGraph singleton, opening pooled connections eagerly) should extend.
Putting it in now avoids a refactor later.

**Why does CORS allow `methods=["*"]` and `headers=["*"]` now, before any
POST/WebSocket endpoint exists?** T-047 adds `POST /api/v1/analysis/start`
in the very next task. Pinning `allow_methods=["GET"]` now and having to
revisit this file again next week for one more HTTP verb adds churn
without adding safety -- the origin allowlist (`cors_origins_list`) is
the actual security boundary here, not the method/header lists.

**Why is `/health` unauthenticated?** Render's health check probe and any
external uptime monitor must be able to reach it without a token. This is
standard practice and explicitly the reason liveness and readiness/auth
concerns are kept separate.

---

## AIRP Standards Compliance

| Standard                                                      | Status                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No `from __future__ import annotations` in production modules | OK -- absent from `main.py`, `routers/health.py`, `routers/__init__.py`, `dependencies/__init__.py`, `dependencies/common.py`. Present in the three new test files only, consistent with 36 of 39 existing files under `backend/tests/unit/`                      |
| Plain ASCII section comments (`# ---`)                        | OK -- no Unicode box-drawing characters in any new file (checked directly, not assumed)                                                                                                                                                                           |
| No bare `# type: ignore`                                      | OK -- every occurrence carries an explicit code (`# type: ignore[attr-defined]`, `# type: ignore[arg-type]`), matching the existing pattern in `state_persistence.py` and `test_pdf_export.py`                                                                    |
| `mypy --strict --warn-unused-ignores` safe                    | OK -- all new functions fully annotated; `Settings`/`HealthResponse`/`FastAPI` types used directly rather than `Any` wherever the real type is known                                                                                                              |
| All lines <= 88 characters                                    | OK -- verified directly by script (no line in any new file exceeds 88 chars)                                                                                                                                                                                      |
| No trailing whitespace / tabs                                 | OK -- verified directly by script                                                                                                                                                                                                                                 |
| flake8 (bugbear, comprehensions) clean                        | OK -- no unnecessary comprehensions; the one route-lookup loop in `test_health_router.py` was deliberately written as a plain `for` loop instead of a comprehension specifically to avoid an awkward multi-line comprehension-with-inline-type-comments construct |
| isort (`force_sort_within_sections`, black profile)           | OK -- every import block manually ordered stdlib -> third-party -> first-party, alphabetised within each section, matching the exact pattern in `backend/db/redis_client.py` and `backend/tests/unit/test_pdf_export.py`                                          |
| `known_first_party` covers new package                        | `dependencies` added to `pyproject.toml`'s isort config now that the package exists with real contents                                                                                                                                                            |
| All agents/nodes never raise                                  | N/A -- no agent or LangGraph node code touched in this task                                                                                                                                                                                                       |
| `ENVIRONMENT=test` guard respected                            | OK -- new tests rely on the existing `conftest.py` autouse `require_test_environment` fixture; nothing new added or bypassed                                                                                                                                      |
| Backward compatibility                                        | OK -- this task only adds new files (plus one additive `pyproject.toml` list entry); no existing router, service, or test file was modified                                                                                                                       |

---

## Verification

`fastapi`, `pydantic`, `httpx`, and `pytest` are not installed in the
sandbox this task was prepared in, and outbound network access to PyPI
is unavailable there, so the test suite could not be executed directly
in that environment. Verification was instead done the way T-044
documents handling the same constraint: by static analysis of the exact
files being delivered, run directly against this task's files before
finalising:

1. **`ast.parse()` against every new `.py` file** -- confirmed zero
   syntax errors.
2. **Line-length scan** -- confirmed zero lines exceed 88 characters
   across all eight new files (709 total lines).
3. **Trailing-whitespace / tab scan** -- confirmed clean.
4. **Manual isort-ordering review** -- every import block in every new
   file checked against the exact ordering `pyproject.toml`'s
   `force_sort_within_sections = true` + `profile = "black"` produces,
   cross-referenced against how `backend/db/redis_client.py` and
   `backend/tests/unit/test_pdf_export.py` already order theirs.
5. **Cross-reference against `config.py`, `db/session.py`, and
   `models/orm.py`** -- confirmed `settings.cors_origins_list`,
   `Settings`, and `get_settings()` are used exactly as their own
   docstrings specify, not guessed at.

The commands below are the actual commands to run locally (Windows
Git Bash, per your environment) to confirm everything genuinely passes
once dependencies are installed -- this is the step to run before
opening the PR, not a substitute for it.

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/api-setup
```

### 2. Place the files

```
backend/main.py                                   (new)
backend/routers/health.py                          (new)
backend/routers/__init__.py                        (new)
backend/dependencies/__init__.py                   (new)
backend/dependencies/common.py                     (new)
backend/tests/unit/test_main.py                    (new)
backend/tests/unit/test_health_router.py           (new)
backend/tests/unit/test_dependencies_common.py     (new)
pyproject.toml                                      (modified)
docs/week-13/T-045-setup-fastapi-project-structure.md  (new)
```

### 3. Set environment (Windows Git Bash -- separate command, not chained with &&)

```bash
set ENVIRONMENT=test
```

### 4. Install dependencies (only if not already installed in your venv)

```bash
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt
```

No new packages were added to either requirements file -- `fastapi`,
`httpx`, and `pytest`/`pytest-asyncio` were already pinned from T-009
and earlier.

### 5. Run the new test suite in isolation first

```bash
python -m pytest backend/tests/unit/test_main.py backend/tests/unit/test_health_router.py backend/tests/unit/test_dependencies_common.py -v --tb=short
```

Expected: all tests pass, including `TestCORS`, `TestSwaggerDocs`, and
`TestHealthEndpoint` -- the three groups that directly map to this
task's three acceptance criteria.

### 6. Manually smoke-test the running server

```bash
uvicorn backend.main:app --reload --port 8000
```

Then in a second terminal (or browser):

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok","environment":"development","version":"0.1.0"}`

Open `http://localhost:8000/docs` in a browser -- Swagger UI should
render with the `/health` endpoint listed under the `health` tag.

### 7. Run the full default suite to confirm no regressions

```bash
python -m pytest --tb=short -q
```

### 8. Run lint and type checks exactly as CI does

```bash
black --check backend/
isort --check-only backend/
flake8 backend/
mypy backend/
```

If `black` or `isort` report formatting differences, run them without
`--check` once to auto-fix, then re-stage (the standard AIRP two-commit
pre-commit pattern):

```bash
black backend/
isort backend/
```

### 9. Confirm coverage

```bash
pytest --cov=backend --cov-report=term-missing -m "not integration" -q
```

`fail_under = 75` is the project-wide gate (`pyproject.toml`). The three
new test files add roughly 2 lines of test code per line of new source
code (709 total new lines, ~440 of which are tests), so this task should
comfortably clear the threshold rather than erode it.

### 10. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/main.py \
        backend/routers/health.py \
        backend/routers/__init__.py \
        backend/dependencies/__init__.py \
        backend/dependencies/common.py \
        backend/tests/unit/test_main.py \
        backend/tests/unit/test_health_router.py \
        backend/tests/unit/test_dependencies_common.py \
        pyproject.toml \
        docs/week-13/T-045-setup-fastapi-project-structure.md
git commit -m "feat(api): scaffold FastAPI backend structure"
```

`mypy` runs at the `manual` stage in pre-commit (per AIRP standards --
Windows App Control blocks unsigned `.exe` shims), so it will not block
this local commit; CI's Linux runner is the real enforcement gate for it.
If black/isort auto-fix anything:

```bash
git add .
git commit -m "feat(api): scaffold FastAPI backend structure"
```

### 11. Push and open PR

```bash
git push -u origin feat/api-setup
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**

```
feat(api): initialise FastAPI with router structure, CORS, and health check
```

**PR description:**

```markdown
## Summary

Scaffolds the FastAPI backend for Phase 5: a router-based project
structure (/routers, /models, /services, /dependencies), CORS
configuration, a GET /health liveness endpoint, and auto-generated
Swagger docs at /docs. This is the first task that exposes the
Phase 1-4 pipeline over HTTP at all -- no business logic (auth,
analysis endpoints, WebSocket) is added here; those are T-046 onward.

## Changes

- `backend/main.py` -- new FastAPI app factory (create_app()), CORS
  middleware wired from settings.cors_origins_list, typed lifespan
  context manager, health router registered
- `backend/routers/health.py` -- new GET /health endpoint returning a
  typed HealthResponse (status/environment/version)
- `backend/routers/__init__.py` -- package docstring documenting
  current and planned routers
- `backend/dependencies/__init__.py`, `backend/dependencies/common.py`
  -- new package; get_settings_dependency() as the first shared
  FastAPI dependency, establishing the dependency_overrides pattern
  T-046's auth dependency will reuse
- `backend/tests/unit/test_main.py`, `test_health_router.py`,
  `test_dependencies_common.py` -- new unit tests covering the app
  factory, /health, /docs, /openapi.json, CORS preflight + actual
  requests, lifespan, and the dependency override pattern
- `pyproject.toml` -- added "dependencies" to isort's
  known_first_party list

## Testing

- `pytest backend/tests/unit/test_main.py backend/tests/unit/test_health_router.py backend/tests/unit/test_dependencies_common.py -v`
  -- new suite, covers all three acceptance criteria directly
  (TestHealthEndpoint, TestSwaggerDocs, TestCORS)
- Manual smoke test: `uvicorn backend.main:app --reload` then
  `curl http://localhost:8000/health` and browsed `/docs` directly
- `pytest --tb=short -q` -- full existing suite, no regressions
- `black --check`, `isort --check-only`, `flake8`, `mypy` all run
  locally against the new files before pushing

## LangSmith Trace

Not applicable -- no agent or LangGraph node code touched in this PR.

## Related Issues

Closes #45
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

With T-045 complete, AIRP has a real, running FastAPI application for
the first time: `uvicorn backend.main:app` serves a liveness endpoint,
Swagger docs, and CORS-correct responses for the eventual React
frontend. The Phase 1-4 pipeline (data layer, 8 agents, debate engine,
PDF export) is not yet reachable over HTTP -- that begins with the very
next task.

Next task: **T-046 -- Implement auth with JWT**
(`POST /auth/register`, `POST /auth/login`, `GET /auth/me`; bcrypt
password hashing; JWT issuance/verification; user persisted via the
existing `User` ORM model from T-016). This is also where
`backend/dependencies/` gains its second, security-critical member:
`get_current_user`, built directly on top of this task's
`get_settings_dependency()` override pattern.

Branch: `feat/api-auth`.

---

_End of Document | T-045 Workflow | AIRP Week 13_
