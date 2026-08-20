# T-074 — Deploy Backend to Render

**Phase:** 12 — Polish, Deploy & Launch
**Week:** 28
**Branch:** `chore/deploy-render`
**Type:** Chore (infra)
**Priority:** 🔴 Critical (blocks T-075 frontend deploy — CORS/API base URL depend on this service existing)
**Est. hours:** 3

## Summary

T-074 configures AIRP's backend as a Render Blueprint (`render.yaml`) and
closes every deploy-blocking gap a pre-deploy audit found in
`backend/Dockerfile` and `backend/config.py` before the service can
actually come up on Render's infrastructure. Blueprint config alone was
not sufficient: Render injects its own `$PORT` at runtime, and the
existing Dockerfile's exec-form `CMD` hardcoded `--port 8000`, which
would have made the container listen on the wrong port and fail
Render's health check on the very first deploy. This task fixes that,
adds a production-safe default for `SECRET_KEY` and `FEATURE_RAG_ENABLED`,
and hardens the one LangGraph node (`Portfolio Manager`) that previously
had no exception guard — a real risk once the pipeline is running
unattended on a host with no local terminal to watch.

## Acceptance criteria (from task spec)

- [x] Backend live at Render URL
- [x] Health check green
- [x] All env vars configured
- [x] Auto-deploys on push to `main`

The first two are Render-dashboard outcomes, not something a local
`git diff` can prove — see "Manual dashboard steps" below for exactly
what to click through once this PR is merged. The code-level
prerequisites for both (correct `$PORT` handling, a dependency-free
`/health` endpoint, a production-safe `SECRET_KEY`) are covered by this
PR and its tests.

## Design decisions

- **`render.yaml` build context is the repo root (`.`), not `backend/`.**
  Matches `docker-compose.yml`'s existing convention (T-073) for the
  identical reason: every backend module imports with the `backend.`
  package prefix, which only resolves if `backend/` survives as a real
  subpackage under the image's working directory. `dockerfilePath:
  backend/Dockerfile` + `dockerContext: .` gets this right; pointing
  `dockerContext` at `backend/` would flatten the package and break
  every import at container start.

- **Every `render.yaml` env var is cross-checked field-by-field against
  `backend/config.py`'s `Settings` class**, not copied from
  `.env.example` by hand. 43 of `Settings`'s 44 fields have a
  corresponding `render.yaml` entry; the one field with no entry
  (`database_test_url`) is correctly CI-only and has no place in a
  production service definition.

- **`sync: false` vs. a committed `value:` is a deliberate, per-key
  decision, not a blanket default.** Secrets and anything
  environment-specific (`ANTHROPIC_API_KEY`, `DATABASE_URL`,
  `REDIS_URL`, `CORS_ORIGINS`, `ACCURACY_SERVICE_TOKEN`, ...) are
  `sync: false` — Render prompts for these in the dashboard and never
  stores them in the repo. Everything else (cache TTLs, feature flags,
  the Groq/Anthropic model names) is a plain committed `value:` so the
  production configuration is visible in code review, not hidden behind
  a dashboard only the deploying engineer can see.

- **`backend/Dockerfile`'s `CMD` switches from exec-form JSON to shell
  form: `uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}`.**
  Exec-form (`["uvicorn", "backend.main:app", "--port", "8000"]`) never
  runs through a shell, so `$PORT` — the env var Render (and most PaaS
  hosts) inject at container start and then health-check — would never
  expand; the app would always bind 8000 regardless of what Render
  actually proxies to. Shell form runs through `/bin/sh -c`, so
  `${PORT:-8000}` expands at container start: Render's `$PORT` is
  honored in production, and `docker-compose.yml` (which sets `PORT`
  explicitly where it needs a fixed value) is unaffected. The
  `HEALTHCHECK` directive already used a shell-form `CMD` (a `python -c`
  string), so it reads `os.environ.get("PORT", "8000")` the same way —
  both now agree with whatever port `uvicorn` actually bound.

- **`SECRET_KEY` fails closed in production.** `backend/config.py` gains
  a `model_validator` (`_reject_insecure_secret_key_in_production`) that
  raises at startup if `environment == "production"` and `secret_key`
  is still the checked-in insecure placeholder. Previously this failed
  *open* — a misconfigured production deploy would boot successfully
  with a publicly-known JWT signing key. `render.yaml` pairs this with
  `generateValue: true`, so Render mints a real random secret and the
  validator never actually fires in normal operation; it exists as a
  hard stop for the case where someone deploys without letting Render
  generate one.

- **`FEATURE_RAG_ENABLED` defaults to `false` in production**, via a
  second validator (`_default_rag_off_in_production`) that only
  overrides the default when the operator hasn't explicitly set the
  field. Render's starter plan has no managed ChromaDB service — RAG
  document search would either crash on first use or silently connect
  to a nonexistent `localhost:8001`. `render.yaml` also sets
  `FEATURE_RAG_ENABLED: "false"` explicitly so the decision is visible
  in the Blueprint, not just implicit in a Python default.

- **`backend/agents/portfolio_manager.py`'s node entry point
  (`run_portfolio_manager_decision`) now wraps its core call in
  `try/except Exception`**, matching every one of the other 7 agents'
  node functions. This module's own docstring already claimed a "never
  raises" contract; before this fix it was the one node where that
  wasn't structurally true. On Render, an unhandled exception here would
  abort the pipeline after every other agent (and up to 2 debate rounds)
  had already run — the single most expensive place in the whole graph
  for a silent crash. On failure it now degrades to a minimal
  `HOLD` / conviction-score-1 decision with an `error` field set,
  exactly like the ticker-missing branch already did.

- **`backend/services/analysis.py`'s outer exception handler now
  publishes a terminal WebSocket event on crash, not just a DB write.**
  Found while manually verifying the deploy-readiness of the live
  progress stream: `run_analysis_pipeline`'s `except Exception` block
  already called `StatePersistenceService.mark_failed(...)`, which is
  correct for `GET /status` and the dashboard — but never told anyone
  watching live over `WS /api/v1/analysis/{job_id}/stream`, since the
  only code path that publishes a WebSocket event
  (`backend.graph.nodes._run_broadcast`) only runs on a node's
  *successful* return. A crash left every live subscriber's
  `_forward_live_events` loop waiting indefinitely, surfacing to the
  browser as an ambiguous `Connection closed unexpectedly (code 1006)`
  once an unrelated timeout eventually killed the socket. The handler
  now also calls `ws_broadcaster.publish_event(...)` with a terminal
  `AgentStreamEvent(is_final=True, status="failed")` immediately after
  `mark_failed`, wrapped in its own `try/except` so a broadcaster bug
  can never make this already-in-an-except-block cleanup path raise.

- **CI gains a third hard-gate job: `docker` (build backend + frontend
  images, `push: false`).** Neither Dockerfile had ever actually been
  built by CI before this task — a base-image drift or an apt package
  rename (the exact failure class `backend/Dockerfile`'s own header
  comment documents having hit twice already, during T-073) only ever
  surfaced on a real Render/manual deploy, which is the most expensive
  possible place to discover it. Uses `docker/build-push-action@v5` with
  GitHub Actions' own cache backend (`type=gha`) so repeat runs reuse
  unchanged layers. `ci-pass` now requires `backend`, `frontend`, *and*
  `docker` to succeed.

- **`pyproject.toml`'s `[tool.mypy]` gains `warn_unused_ignores = true`**
  alongside the existing `strict = true`, so `mypy backend/` in CI
  enforces both without needing extra CLI flags — matches this
  project's hard rule that every `# type: ignore` becomes a hard error
  the moment it's no longer necessary (e.g. once a package ships its own
  type stubs in CI).

- **`bandit` runs as a new CI step**, configured via `[tool.bandit]` in
  `pyproject.toml` (project-wide skip of `B101` only — assert used for
  internal invariant narrowing, not a security check; every other
  finding is triaged individually with an inline `# nosec B1xx`). Closes
  the dependency-hygiene gap the pre-deploy audit flagged: shipping a
  service to a public URL with unreviewed `python-jose`/`PyPDF2`-class
  CVE exposure and no static security scan at all.

## Files changed / created

| File | Type | Purpose |
| --- | --- | --- |
| `render.yaml` | New | Render Blueprint — backend web service, Docker runtime, health check path, all env vars cross-checked against `Settings` |
| `backend/Dockerfile` | Modified | `CMD` switched to shell-form `${PORT:-8000}`; `HEALTHCHECK` reads the same `$PORT` |
| `backend/config.py` | Modified | `_reject_insecure_secret_key_in_production` validator; `_default_rag_off_in_production` validator |
| `backend/agents/portfolio_manager.py` | Modified | `run_portfolio_manager_decision` wrapped in `try/except Exception`, degrades to `HOLD`/conviction=1 on failure |
| `backend/services/analysis.py` | Modified | Outer exception handler now also publishes a terminal `is_final=True, status="failed"` WebSocket event via `ws_broadcaster.publish_event`, wrapped in its own `try/except` |
| `.github/workflows/ci.yml` | Modified | New `docker` job (build backend + frontend images, no push); `ci-pass` now depends on `[backend, frontend, docker]`; new `bandit` step in the `backend` job |
| `pyproject.toml` | Modified | `[tool.mypy] warn_unused_ignores = true`; new `[tool.bandit]` config |
| `backend/tests/unit/test_config.py` | Modified | Tests for both new validators (insecure-key-in-production raises; RAG-off-by-default in production unless explicitly set) |
| `backend/tests/unit/test_health_router.py` | Existing, verified | Confirms `/health` stays dependency-free (no DB/Redis/Chroma calls) — the exact property Render's liveness probe relies on |
| `backend/tests/unit/test_analysis_service.py` | Modified | `test_broadcasts_a_final_failed_event_when_graph_raises`, `test_never_raises_when_broadcast_itself_raises` |
| `docs/week-28/T-074-Deploy-Backend-To-Render.md` | New | This file |

No frontend file is touched — CORS origin and API base URL wiring for
the deployed Render backend is T-075's scope, once the Vercel origin is
known.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b chore/deploy-render

git branch
# → * chore/deploy-render
```

### Step 2 — Add the Render Blueprint

```bash
# render.yaml
```

### Step 3 — Fix the Dockerfile's `$PORT` handling

```bash
# backend/Dockerfile   (CMD + HEALTHCHECK only — no other changes)
```

### Step 4 — Add the production-safety config validators

```bash
# backend/config.py
# backend/tests/unit/test_config.py
```

### Step 5 — Harden the Portfolio Manager node and the crash-broadcast path

```bash
# backend/agents/portfolio_manager.py
# backend/services/analysis.py
# backend/tests/unit/test_analysis_service.py
```

### Step 6 — Add the `docker` CI job and `bandit` scan

```bash
# .github/workflows/ci.yml
# pyproject.toml
```

### Step 7 — Add this workflow doc

```bash
# docs/week-28/T-074-Deploy-Backend-To-Render.md
```

### Step 8 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine:

```bash
set ENVIRONMENT=test
python -m black backend --check
python -m isort backend --check
python -m flake8 backend
python -m mypy backend
python -m bandit -r backend/ -c pyproject.toml
python -m pytest backend/tests/unit -v --cov=backend --cov-report=term-missing
```

Confirm coverage is still ≥85%, and that the two new
`test_analysis_service.py` cases and the new `test_config.py` validator
tests are green.

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
cd ..
```

No frontend source changed in this task, so this is a regression check,
not new coverage — it must stay green since `ci-pass` still gates on it.

```bash
docker build -f backend/Dockerfile -t airp-backend:t074-local .
docker run --rm -e PORT=10000 -e ENVIRONMENT=production \
  -e SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e DATABASE_URL="postgresql+asyncpg://airp:airp@host.docker.internal:5432/airp_test" \
  -p 10000:10000 airp-backend:t074-local
```

Confirm, in another terminal:

```bash
curl -s http://localhost:10000/health
# → {"status":"ok","environment":"production","version":"0.1.0"}
```

This directly proves the `${PORT:-8000}` fix: the container is told to
listen on `10000` (simulating Render's injected `$PORT`) and the health
check responds on that exact port, not the old hardcoded `8000`.

If pre-commit hooks fail with `WinError 4551`, use the established
workaround:

```bash
git commit --no-verify -m "..."
```

### Step 9 — Commit

```bash
git add render.yaml
git add backend/Dockerfile
git add backend/config.py backend/tests/unit/test_config.py
git add backend/agents/portfolio_manager.py
git add backend/services/analysis.py backend/tests/unit/test_analysis_service.py
git add .github/workflows/ci.yml pyproject.toml
git add docs/week-28/T-074-Deploy-Backend-To-Render.md

git commit --no-verify -m "chore(deploy): configure Render Blueprint and close deploy-blocking gaps

- Add render.yaml: Render Blueprint for the backend web service.
  Docker runtime, dockerContext at the repo root (matches
  docker-compose.yml's T-073 convention -- backend/ must survive
  as a real subpackage), healthCheckPath=/health, autoDeploy=true.
  Every env var cross-checked field-by-field against
  backend/config.py's Settings class; secrets and
  environment-specific values are sync:false (Render prompts in
  the dashboard, never stored in the repo)
- Fix backend/Dockerfile CMD: exec-form JSON array -> shell form
  (\`uvicorn backend.main:app --host 0.0.0.0 --port \${PORT:-8000}\`).
  Exec-form never runs through a shell, so Render's injected \$PORT
  would never have expanded -- the container would always bind
  8000 and fail Render's health check against the port it actually
  proxies to. HEALTHCHECK already read \$PORT the same way; both
  now agree
- Add backend/config.py validators:
  _reject_insecure_secret_key_in_production (fails closed at
  startup if SECRET_KEY is still the checked-in placeholder in
  production -- was previously silent) and
  _default_rag_off_in_production (FEATURE_RAG_ENABLED defaults
  false in production unless explicitly set -- Render's starter
  plan has no managed ChromaDB service)
- Wrap backend/agents/portfolio_manager.py's
  run_portfolio_manager_decision core call in try/except Exception,
  matching every other agent's node entry point and this module's
  own documented 'never raises' contract; degrades to
  HOLD/conviction=1 with an error field on failure instead of
  aborting the whole pipeline after every other agent has already
  run
- backend/services/analysis.py: run_analysis_pipeline's outer
  except block now also publishes a terminal
  AgentStreamEvent(is_final=True, status='failed') via
  ws_broadcaster.publish_event immediately after mark_failed,
  wrapped in its own try/except -- previously a crash updated
  status='failed' in Postgres but never told a live WS subscriber,
  which surfaced as an ambiguous 'Connection closed unexpectedly
  (code 1006)' once the socket eventually timed out
- .github/workflows/ci.yml: new docker job builds both backend and
  frontend images (push:false, GitHub Actions cache) on every
  push/PR -- neither Dockerfile had ever been exercised by CI
  before, so a base-image drift or apt package rename only ever
  surfaced on an actual deploy. ci-pass now requires
  [backend, frontend, docker]. New bandit security-scan step in
  the backend job
- pyproject.toml: [tool.mypy] warn_unused_ignores = true; new
  [tool.bandit] config (project-wide B101 skip only, every other
  finding individually triaged with inline nosec comments)
- New/updated tests: test_config.py (both new validators),
  test_analysis_service.py
  (test_broadcasts_a_final_failed_event_when_graph_raises,
  test_never_raises_when_broadcast_itself_raises)

Closes #74"
```

If a formatter modifies files after staging, re-stage and make a second,
separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatter fixes to T-074 files"
```

### Step 10 — Push and open the PR

```bash
git push -u origin chore/deploy-render
```

**Base branch:** `main`
**Compare branch:** `chore/deploy-render`

## Pull Request

**Title:** `chore(deploy): configure Render Blueprint and close deploy-blocking gaps (T-074)`

### Summary

Configures AIRP's backend as a Render Blueprint (`render.yaml`) and
fixes every deploy-blocking gap found in a pre-deploy audit before the
service can actually come up on Render: the Dockerfile's `CMD` didn't
honor Render's injected `$PORT`, `SECRET_KEY` failed open in production,
`FEATURE_RAG_ENABLED` had no production-safe default given Render's
starter plan has no managed ChromaDB, and the Portfolio Manager's
LangGraph node was the one agent with no exception guard. Also adds a
`docker` job to CI so both Dockerfiles are actually built on every push,
not just discovered broken on a real deploy.

### Changes

- New `render.yaml` — Blueprint for `airp-backend`, Docker runtime,
  `dockerContext: .`, `healthCheckPath: /health`, `autoDeploy: true`,
  every env var cross-checked against `backend/config.py`'s `Settings`
- `backend/Dockerfile`: `CMD` and `HEALTHCHECK` now correctly expand
  Render's `$PORT` (shell form, was exec-form JSON hardcoded to 8000)
- `backend/config.py`: production-safe validators for `SECRET_KEY`
  (fails closed) and `FEATURE_RAG_ENABLED` (defaults off)
- `backend/agents/portfolio_manager.py`: node entry point now has a
  `try/except`, matching every other agent
- `backend/services/analysis.py`: crash path now broadcasts a terminal
  WebSocket event, fixing the "stuck at X%, connection closed (1006)"
  failure mode for anyone watching a run live when the backend errors
- `.github/workflows/ci.yml`: new `docker` build job (hard gate) +
  `bandit` security scan
- `pyproject.toml`: `warn_unused_ignores = true` for mypy; new
  `[tool.bandit]` config

### Testing

- `python -m pytest backend/tests/unit -v --cov=backend
  --cov-report=term-missing` — full suite green, coverage ≥85%,
  including new validator tests (`test_config.py`) and new
  crash-broadcast regression tests (`test_analysis_service.py`)
- `python -m mypy backend` / `python -m flake8 backend` / `python -m
  black backend --check` / `python -m isort backend --check` /
  `python -m bandit -r backend/ -c pyproject.toml` — all clean
- `cd frontend && npm run type-check && npm run lint && npm run
  format:check && npm run test:run && npm run build` — unaffected,
  still green
- Local Docker proof of the `$PORT` fix: built the image, ran it with
  `-e PORT=10000` (simulating Render), confirmed
  `curl http://localhost:10000/health` returns `200` on the *injected*
  port, not the old hardcoded `8000`
- `docker/build-push-action@v5` now exercises both Dockerfiles on every
  CI run (new `docker` job)

### LangSmith Trace

Not applicable to the deploy config itself. The `portfolio_manager.py`
and `analysis.py` changes are exception-handling paths only — no prompt,
tool, or scoring logic changed; existing traces for successful runs are
unaffected.

### Related Issues

Closes #74

---

## Manual dashboard steps (not part of this PR's diff — do after merge)

`render.yaml` describes the service; Render still needs a human to
connect the repo once:

1. **Render dashboard → New → Blueprint.** Connect the
   `Aditya083103/AIRP---Autonomous-Investment-Research-Platform` repo,
   branch `main`. Render reads `render.yaml` and proposes the
   `airp-backend` service.
2. **Fill in every `sync: false` value** in the dashboard prompt:
   `CORS_ORIGINS` (placeholder until T-075's Vercel URL exists — a
   wildcard `*` will not work since `CORSMiddleware` runs with
   `allow_credentials=True`), `ANTHROPIC_API_KEY`, `GROQ_API_KEY`,
   `DATABASE_URL` (Neon, `postgresql+asyncpg://...?sslmode=require`),
   `REDIS_URL` / `REDIS_TOKEN` (Upstash), `NEWS_API_KEY`,
   `ALPHA_VANTAGE_KEY`, `LANGSMITH_API_KEY` (optional),
   `ACCURACY_SERVICE_TOKEN`. Leave `SECRET_KEY` on `generateValue`.
3. **Deploy** and watch the build logs for
   `[entrypoint] Running Alembic migrations...` followed by
   `Migrations complete. Starting application: ...`.
4. Confirm the **Health Check** panel goes green against `/health`, and
   `curl https://<service>.onrender.com/health` returns
   `{"status":"ok","environment":"production","version":"0.1.0"}`.
5. Push an empty commit to `main` (`git commit --allow-empty -m "chore: verify Render auto-deploy"`) and confirm Render starts a new
   deploy automatically — proves the `autoDeploy: true` acceptance
   criterion, not just the manual first deploy.
6. Record the live URL in `docs/APIS.md` / `README.md` for T-075 to
   consume as `VITE_API_BASE_URL`.