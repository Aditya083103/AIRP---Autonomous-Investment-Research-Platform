# T-073 — Dockerize the Full Stack

**Phase:** 12 — Polish, Deploy & Launch
**Week:** 28
**Branch:** `chore/docker`
**Type:** Chore (infra)
**Priority:** 🔴 Critical (blocks all other Phase 12 deploy tasks)
**Est. hours:** 4

## Summary

T-073 containerizes the entire AIRP stack: a production-grade multi-stage
`Dockerfile` for the FastAPI backend, both a dev (`Dockerfile.dev`, hot
reload) and production (`Dockerfile`, nginx-served static build) image
for the React frontend, and a corrected `docker-compose.yml` that brings
up all five services — `api`, `frontend`, `postgres`, `redis`, `chromadb`
— with a single `docker-compose up`, per the task's literal acceptance
criteria.

The existing `docker-compose.yml` (present since Phase 0 scaffolding)
referenced a `backend/Dockerfile` and `frontend/Dockerfile.dev` that
never existed, and — more importantly — was structurally broken even as
a spec: it built the `api` image with `context: ./backend`, which
flattens `backend/`'s contents into `/app`. Every backend module imports
with the `backend.` package prefix (`from backend.config import
settings`, see `backend/main.py` and `backend/alembic.ini`'s
`prepend_sys_path`), so a build that doesn't keep `backend/` as a real
subpackage under the image's working directory would fail on the very
first import. This task rebuilds the compose file with the correct
build context (repo root) and adds the two missing Dockerfiles it always
depended on.

## Acceptance criteria (from task spec)

- [x] `docker-compose up` starts all services
- [x] App fully functional at `http://localhost:3000`
- [x] README shows the command

All three are addressed directly — see "Design decisions" and "Files
changed / created" below — plus two pre-existing bugs this task's scope
made unavoidable to fix (see next section), without which "fully
functional at localhost:3000" would not actually be true.

## Design decisions

- **Backend build context must be the repo root, not `backend/`.**
  `backend/Dockerfile`'s own header comment documents this at length.
  `docker-compose.yml`'s `api` service now sets `context: .` /
  `dockerfile: backend/Dockerfile`, and the Dockerfile's `COPY backend/
  backend/` preserves the package layout every `from backend.X import Y`
  import in the codebase (136 files) already assumes.

- **Two-stage backend build.** Stage 1 (`builder`) installs
  `build-essential`/`libpq-dev`/`libffi-dev` and compiles
  `requirements.txt` into an isolated venv. Stage 2 (`runtime`) copies
  only that venv plus the app source — no compiler toolchain, no pip
  cache, no apt lists ship in the final image. `requirements-dev.txt`
  (black/isort/flake8/mypy/pytest/...) is never installed in the image;
  those tools run in CI on the GitHub-hosted runner, not inside the
  shipped container.

- **WeasyPrint's system libraries belong in the runtime stage, not just
  documented as a prerequisite.** `weasyprint==62.3`
  (`backend/requirements.txt`) links against Pango/Cairo/GDK-Pixbuf at
  **import time**, not at `pip install` time — the wheel installs
  cleanly without them, then the Portfolio Manager's Investment Memo PDF
  export (T-044) crashes on the very first `/health`-passing container's
  first real request with `OSError: cannot load library
  'libpango-1.0.so.0'`. `backend/Dockerfile`'s runtime stage installs
  `libpango-1.0-0`, `libpangocairo-1.0-0`, `libgdk-pixbuf2.0-0`,
  `libcairo2`, `shared-mime-info`, and `fonts-liberation` explicitly so
  this can't silently regress.

- **Migrations run in the entrypoint, not the app's lifespan.**
  `backend/docker-entrypoint.sh` runs `alembic -c backend/alembic.ini
  upgrade head` and only then `exec`s the CMD (`uvicorn`). This
  guarantees migrations complete — or the container fails loudly and
  exits — before the app binds a port and starts accepting traffic,
  rather than racing migrations against request handling inside
  `main.py`'s lifespan context manager. Both the production `CMD`
  (`uvicorn backend.main:app ...`) and `docker-compose.yml`'s dev
  override (same command plus `--reload`) get this for free without
  duplicating the migration step in two places.

- **Non-root runtime user.** The final backend image creates and runs as
  `airp` (uid 1000), not root — a basic container-security default that
  costs nothing here since nothing in the app needs root.

- **`/health`-based `HEALTHCHECK`, no new dependency.** Uses
  `python -c "import urllib.request; ..."` against the existing T-045
  `/health` endpoint rather than adding `curl`/`wget` to the runtime
  image purely for this one check.

- **Fixed the frontend dev-proxy's hardcoded `localhost` target.**
  `frontend/vite.config.ts`'s dev proxy (`/api`, `/auth`) hardcoded
  `http://localhost:8000` as its target. That's correct for `npm run dev`
  on the host, but inside the `frontend` container, `localhost` resolves
  to the frontend container itself, not the sibling `api` container —
  every proxied request would fail with `ECONNREFUSED` even though the
  backend is healthy, which would have directly violated the "fully
  functional at localhost:3000" acceptance criterion. Introduced a
  `DOCKER_BACKEND_URL` env var (Node-side only — read in
  `vite.config.ts`, never bundled into client code, so it doesn't need a
  `VITE_` prefix) that `docker-compose.yml`'s `frontend` service sets to
  `http://api:8000`; every other case (bare `npm run dev`, CI, Vitest
  importing this config) falls back to the original
  `http://localhost:8000`, so this is additive, not a behavior change
  for anyone not running Docker.

- **Frontend dev image uses the real Vite dev server, not a static
  build.** `frontend/Dockerfile.dev` runs `npm run dev -- --host 0.0.0.0
  --port 3000` with the source bind-mounted by `docker-compose.yml`, so
  `docker-compose up` gives the identical hot-reload edit loop as
  running `npm run dev` directly on the host — matching the acceptance
  criterion's implicit expectation that the containerized app is usable
  for active development, not just a frozen build.

- **Frontend production image is separate and NOT wired into
  `docker-compose.yml`.** `frontend/Dockerfile` (multi-stage: `npm run
  build` → nginx) is a standalone deployable artifact for containerized
  deployment as an alternative to Vercel, and for verifying a real
  production build locally. It stays out of the dev compose stack
  because AIRP's actual frontend deploy target is Vercel directly from
  Git (see README's Tech stack table) — bringing up an nginx container
  alongside a live-reloading Vite dev server on the same port would
  only create ambiguity about which one "localhost:3000" means during
  `docker-compose up`.

- **`docker-compose.yml` includes a standalone `chromadb` service, per
  the task's literal acceptance criteria** ("`api` + `postgres` + `redis`
  + `chromadb`"), even though — as documented directly in the compose
  file's comments — `backend/db/chroma_client.py`'s existing routing
  logic (from T-017/T-018, unchanged by this task) means the `api`
  container actually talks to ChromaDB via a local on-disk
  `PersistentClient` when `ENVIRONMENT=development` (the compose
  default), not to this container. The standalone service exists so the
  stack is ready for `ENVIRONMENT=production`'s `HttpClient` path
  without further Docker changes, and is health-checked so `api`'s
  `depends_on` ordering is meaningful.

- **CORS default and Vite port were already out of sync before this
  task — fixed as part of making "functional at localhost:3000" true.**
  `backend/config.py`'s `cors_origins` default was still
  `http://localhost:5173` (Vite's stock default), while
  `frontend/vite.config.ts`'s `server.port` has been `3000` since
  earlier in Phase 6. This was latent and harmless for the Docker
  dev-proxy path (server-to-server proxying isn't subject to browser
  CORS), but it's directly wrong for anyone running the backend without
  Docker against a host `npm run dev` frontend, and would have been a
  confusing default to ship alongside this task's `README.md` Docker
  instructions. Updated the class default, `.env.example`, and one
  descriptive comment in `backend/main.py` to `3000`. **Not a breaking
  change to any test**: `backend/tests/conftest.py`'s `test_settings`
  fixture pins `cors_origins="http://localhost:5173"` explicitly and
  every `TestCORS` assertion in `test_main.py` reads
  `test_settings.cors_origins_list[0]` rather than hardcoding a port, so
  the CI-covered tests are already independent of the class-level
  default — confirmed by inspection before making the change, not
  assumed.

## Files changed / created

| File | Type | Purpose |
| --- | --- | --- |
| `backend/Dockerfile` | New | Multi-stage production backend image (builder + slim runtime, non-root, WeasyPrint system libs, `/health` healthcheck) |
| `backend/docker-entrypoint.sh` | New | Runs `alembic upgrade head` before exec'ing the CMD |
| `frontend/Dockerfile.dev` | New | Dev image — real Vite dev server, hot reload, used by `docker-compose.yml` |
| `frontend/Dockerfile` | New | Production image — multi-stage `npm run build` → nginx, standalone deploy artifact |
| `frontend/nginx.conf.template` | New | nginx config for the production image: SPA fallback, `/api`/`/auth`/WebSocket proxying via `${BACKEND_UPSTREAM}` |
| `.dockerignore` | New | Root — scopes the backend build context (repo root) |
| `frontend/.dockerignore` | New | Scopes the frontend build context |
| `docker-compose.yml` | Modified | Fixed build context (`context: .` for `api`), added `frontend` + `chromadb` services, healthchecks, named volumes, port 3000 |
| `frontend/vite.config.ts` | Modified | Dev proxy target reads `DOCKER_BACKEND_URL` (falls back to `localhost:8000`) instead of a hardcoded host target |
| `backend/config.py` | Modified | `cors_origins` default `5173` → `3000`, matching Vite's actual configured port |
| `backend/main.py` | Modified | Updated a stale comment referencing the old CORS default |
| `.env.example` | Modified | `CORS_ORIGINS` default `5173` → `3000`, with an explanatory comment |
| `backend/tests/unit/test_main.py` | Modified | Corrected a docstring that referenced the old CORS default (no assertion changes — tests already read the value from the `test_settings` fixture, not the class default) |
| `README.md` | Modified | Docker quick-start section (correct ports, five services, migration-on-boot note), project structure tree |
| `docs/week-28/T-073-dockerize.md` | New | This file |

No agent, graph, router, model, or migration file is touched — this task
is purely infra/packaging.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b chore/docker

git branch
# → * chore/docker
```

### Step 2 — Add the backend Docker image

```bash
# backend/Dockerfile
# backend/docker-entrypoint.sh
# .dockerignore
```

### Step 3 — Add the frontend Docker images

```bash
# frontend/Dockerfile.dev
# frontend/Dockerfile
# frontend/nginx.conf.template
# frontend/.dockerignore
```

### Step 4 — Rewrite docker-compose.yml

```bash
# docker-compose.yml
```

### Step 5 — Fix the dev-proxy target and the stale CORS default

```bash
# frontend/vite.config.ts
# backend/config.py
# backend/main.py
# .env.example
# backend/tests/unit/test_main.py   (docstring only)
```

### Step 6 — Update README and add this workflow doc

```bash
# README.md
# docs/week-28/T-073-dockerize.md
```

### Step 7 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine:

```bash
set ENVIRONMENT=test
python -m black backend --check
python -m isort backend --check
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v --cov=backend --cov-report=term-missing
```

Confirm coverage is still ≥85% — this task adds no new backend `.py`
logic (only `config.py`/`main.py` string/comment edits and one docstring
fix in an existing test file), so no new lines need new tests, and the
existing `TestCORS` suite continues to pass unchanged against the
`test_settings` fixture's explicit `5173` override.

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
cd ..
```

`vite.config.ts` is included in `tsc`'s type-check scope
(`tsconfig.json`'s `include`), so `npm run type-check` directly proves
the `DOCKER_BACKEND_URL` change type-checks. It is **not** covered by
`npm run lint` (ESLint only lints `src/`) or `npm run format:check`
(Prettier only checks `src/**/*.{ts,tsx,json,css,md}`), so it was
formatted by hand to match the file's existing style (2-space indent,
double quotes, trailing semicolons) rather than relying on a tool to
catch a mismatch.

If pre-commit hooks fail with `WinError 4551`, use the established
workaround:

```bash
git commit --no-verify -m "..."
```

### Step 8 — Verify the actual acceptance criteria: bring up the full stack

```bash
cp .env.example .env
# fill in real GROQ_API_KEY / NEWS_API_KEY / ALPHA_VANTAGE_KEY etc.

docker-compose up --build
```

Confirm, in order:

1. `postgres` and `redis` report healthy, then `chromadb` reports
   healthy (its healthcheck has a 15s `start_period`).
2. `api` logs `[entrypoint] Running Alembic migrations...` followed by
   `Migrations complete. Starting application: uvicorn ...`, then
   `AIRP backend starting -- environment=development llm_provider=...`.
3. `frontend` logs Vite's ready message (`VITE vX.X.X ready in ...ms`,
   `➜ Local: http://localhost:3000/`).
4. `http://localhost:8000/health` returns `{"status": "ok", ...}`.
5. `http://localhost:3000` loads the AIRP UI, and an action that hits
   the backend (e.g. registering a user, or starting an analysis)
   succeeds — proving the `/api` and `/auth` proxy paths correctly
   reach the `api` container over the compose network, not
   `ECONNREFUSED` against the frontend container's own `localhost`.
6. `docker-compose down` cleans up; `docker-compose up` a second time
   starts faster (layers cached) and Postgres data persists (named
   volume) across the restart.

Paste a trimmed version of this console output into the PR description
(see below).

### Step 9 — Commit

```bash
git add backend/Dockerfile backend/docker-entrypoint.sh .dockerignore
git add frontend/Dockerfile frontend/Dockerfile.dev frontend/nginx.conf.template frontend/.dockerignore
git add docker-compose.yml
git add frontend/vite.config.ts backend/config.py backend/main.py .env.example
git add backend/tests/unit/test_main.py
git add README.md docs/week-28/T-073-dockerize.md

git commit --no-verify -m "chore(docker): dockerize the full stack

- Add backend/Dockerfile: multi-stage production image (builder +
  slim runtime). Build context is the repo root, not backend/, so
  \`backend/\` survives as a real subpackage under /app -- required
  by every \`from backend.X import Y\` import in the codebase. Runtime
  stage installs WeasyPrint's Pango/Cairo/GDK-Pixbuf system libs
  (missing them fails PDF export at first use, not at build time),
  runs as a non-root user, and ships a /health-based HEALTHCHECK
- Add backend/docker-entrypoint.sh: runs \`alembic -c
  backend/alembic.ini upgrade head\` before exec'ing the CMD, so
  migrations always complete before the app accepts traffic
- Add frontend/Dockerfile.dev: real Vite dev server (--host 0.0.0.0
  --port 3000) with source bind-mounted by docker-compose.yml, for
  the same hot-reload workflow as \`npm run dev\` on the host
- Add frontend/Dockerfile + nginx.conf.template: standalone
  multi-stage production image (npm run build -> nginx), for
  containerized deployment outside Vercel; not wired into the dev
  compose stack
- Add .dockerignore (root) and frontend/.dockerignore
- Rewrite docker-compose.yml: fix the api service's build context
  (was ./backend, which flattened the backend package and broke
  every \`backend.\` import at runtime -- now repo root); add the
  frontend and chromadb services; healthchecks + depends_on
  ordering across postgres/redis/chromadb/api/frontend; named
  volumes for Postgres, Redis, standalone Chroma storage, and the
  api container's local ChromaDB PersistentClient directory;
  frontend now correctly maps port 3000 (was a stale 5173)
- Fix frontend/vite.config.ts: dev proxy target for /api and /auth
  now reads DOCKER_BACKEND_URL (set only by docker-compose.yml's
  frontend service, to http://api:8000) instead of a hardcoded
  http://localhost:8000 -- inside the frontend container,
  'localhost' resolved to the frontend container itself, not the
  sibling api container, silently breaking every proxied request
- Fix backend/config.py's cors_origins default and .env.example's
  CORS_ORIGINS (5173 -> 3000) to match vite.config.ts's actual
  configured dev server port; update one stale comment in
  backend/main.py and one stale docstring in
  backend/tests/unit/test_main.py to match -- no test assertions
  changed, TestCORS already reads the origin from the test_settings
  fixture, not the class default
- Update README.md: corrected Docker quick-start (5 services, real
  ports, migration-on-boot note) and project structure tree

Closes #73"
```

If a formatter modifies files after staging, re-stage and make a second,
separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply prettier formatting to T-073 files"
```

### Step 10 — Push and open the PR

```bash
git push -u origin chore/docker
```

**Base branch:** `main`
**Compare branch:** `chore/docker`

## Pull Request

**Title:** `chore(docker): dockerize the full stack (backend, frontend, docker-compose)`

### Summary

Containerizes the full AIRP stack for T-073: a production-grade
multi-stage `Dockerfile` for the FastAPI backend (non-root, WeasyPrint
system libs, migration-on-boot via a dedicated entrypoint), a dev
(`Dockerfile.dev`, hot-reload Vite dev server) and production
(`Dockerfile`, nginx) image pair for the React frontend, and a corrected
`docker-compose.yml` bringing up `api` + `frontend` + `postgres` +
`redis` + `chromadb` with a single `docker-compose up`. The previous
compose file referenced two Dockerfiles that never existed and built the
backend from the wrong context (`./backend`, which would have broken
every `backend.`-prefixed import at runtime) — this PR replaces it
entirely rather than patching around the missing pieces.

### Changes

- New `backend/Dockerfile` (multi-stage) + `backend/docker-entrypoint.sh`
  (runs Alembic migrations before serving)
- New `frontend/Dockerfile.dev` (dev, hot reload) and `frontend/Dockerfile`
  + `nginx.conf.template` (production, standalone)
- New root `.dockerignore` and `frontend/.dockerignore`
- Rewritten `docker-compose.yml`: correct backend build context,
  `frontend` + `chromadb` services added, healthchecks/`depends_on`
  ordering, named volumes, frontend correctly on port 3000
- `frontend/vite.config.ts`: dev proxy target configurable via
  `DOCKER_BACKEND_URL` so the containerized frontend can actually reach
  the containerized backend
- `backend/config.py` / `.env.example` / `backend/main.py`: CORS default
  corrected from Vite's stock 5173 to the project's actual 3000
  (`test_main.py` docstring updated to match; no assertions changed)
- `README.md` Docker quick-start and project structure updated

### Testing

- `python -m pytest backend/tests/unit -v --cov=backend
  --cov-report=term-missing` — full suite green, coverage still ≥85%
  (no new backend logic; `TestCORS` unaffected — it reads the origin
  from the `test_settings` fixture's explicit override, not the class
  default)
- `python -m mypy backend` / `python -m flake8 backend` / `python -m
  black backend --check` / `python -m isort backend --check` — clean
- `cd frontend && npm run type-check && npm run lint && npm run
  format:check && npm run test:run && npm run build` — all green
  (`vite.config.ts` is in `tsc`'s type-check scope per `tsconfig.json`,
  so the `DOCKER_BACKEND_URL` change is directly type-checked)
- `docker-compose up --build` — all five services reach healthy/ready;
  API migrations run automatically on boot; `http://localhost:8000/health`
  returns 200; `http://localhost:3000` loads the UI and successfully
  proxies a real request through to the `api` container
- `docker-compose down && docker-compose up` — Postgres data persists
  across restart via the named volume; rebuild uses cached layers

### LangSmith Trace

Not applicable — no agent or graph code changed.

### Related Issues

Closes #73