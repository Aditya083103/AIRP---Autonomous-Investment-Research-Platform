# T-090 — Scheduled evaluation via GitHub Actions

**Phase:** 8 — Verdict Accuracy Tracker
**Week:** 20
**Branch:** `feat/accuracy-scheduled-eval`
**Type:** DevOps
**Priority:** 🟡 High
**Est. hours:** 3

## Summary

T-089 built `run_due_evaluations()`; T-090 gives it a schedule and an
HTTP front door. This task adds:

1. **`POST /api/v1/accuracy/run`** — a machine-to-machine endpoint that
   runs one batch of `run_due_evaluations()` and returns the
   due/evaluated/skipped counts. Protected by a static shared secret
   (`X-Service-Token` header), not user JWT auth, since the caller is a
   scheduled job, not a logged-in person.
2. **`.github/workflows/evaluate-verdicts.yml`** — a cron workflow that
   calls that endpoint once a day, plus a `workflow_dispatch` trigger
   so it can be run on demand from the Actions tab for testing.

## Acceptance criteria (from task spec)

- [x] Workflow runs daily on schedule
- [x] Endpoint rejects unauthenticated calls
- [x] Manual `workflow_dispatch` trigger available for testing

## Design decisions

- **Service-token auth, not JWT.** `get_current_user` (T-046) verifies
  a JWT issued to a real, logged-in `User` row — there is no such user
  here; the caller is a GitHub Actions runner. A second, independent
  dependency, `verify_service_token`, checks a static shared secret in
  a custom `X-Service-Token` header instead, compared with
  `secrets.compare_digest` (constant-time, so the comparison itself
  can't leak the secret's length/prefix through timing).
- **Fails closed on an unconfigured secret.** `accuracy_service_token`
  defaults to an empty string. If it is never set (a fresh deploy that
  forgot to configure it, or a `.env` that doesn't define it),
  `verify_service_token` rejects **every** request — including one
  that also sends no token — rather than treating "no secret
  configured" as "auth is off". An endpoint that scores real trading
  calls should never be reachable by accident.
- **`AccuracyRunResponse` mirrors `EvaluationBatchResult` field-for-
  field**, the same "service dataclass -> HTTP schema" boundary this
  project already draws for `InvestmentDecisionResponse` /
  `AnalysisChartDataResponse` — the router does no computation of its
  own.
- **No defensive try/except around `run_due_evaluations()` in the
  router.** T-089 documents that function as never raising; the router
  trusts that contract the same way `documents.py` trusts its own
  service layer to raise only the specific, already-handled exceptions
  it documents.
- **The workflow calls the deployed API over HTTPS — it does not
  check out the repository at all.** There is nothing in this
  workflow that needs the source tree; `actions/checkout` would only
  add unnecessary runtime. This also means the workflow works
  identically regardless of which branch triggered it (schedules
  always run against the default branch's workflow file, but the
  *endpoint being called* is whatever is currently deployed).
- **Cron time: `30 18 * * *` (18:30 UTC = 00:00 IST).** Comfortably
  after NSE/BSE market close (15:30 IST) and same-day settlement, and
  before the next trading day's pre-market session. The minute is
  `:30`, not `:00` — GitHub's own scheduling documentation notes
  on-the-hour schedules see the heaviest load platform-wide and can be
  delayed; offsetting by 30 minutes avoids piling onto that spike.
- **The workflow fails loudly on a non-200 response**, using
  `::error::` annotations and a non-zero exit code — a 401 here almost
  always means `ACCURACY_SERVICE_TOKEN` was rotated on one side (the
  GitHub secret or the deployed backend's env var) but not the other.
  Letting the workflow go green on a 401 would mean evaluations quietly
  stop happening with nothing to notice it.
- **`workflow_dispatch` accepts an optional free-text `reason` input**,
  logged at the top of the run — a small quality-of-life touch so a
  manually-triggered run in the Actions history says *why* it was run,
  not just that it was.

## Files changed / created

### Backend — config

- **`backend/config.py`** (**MODIFY**) — new `accuracy_service_token`
  setting (`Field(default="", ...)`, documented as fail-closed).
- **`.env.example`** (**MODIFY**) — documents `ACCURACY_SERVICE_TOKEN`,
  how to generate one, and where to store the matching GitHub secret.

### Backend — auth

- **`backend/dependencies/auth.py`** (**MODIFY**) — new
  `verify_service_token` dependency + `service_token_header`
  (`APIKeyHeader(name="X-Service-Token", auto_error=False)`). Module
  docstring updated to cover both auth mechanisms now living in this
  file.

### Backend — schema

- **`backend/models/schemas.py`** (**MODIFY**) — new
  `AccuracyRunResponse` (`due_count`, `evaluated_count`,
  `skipped_count`, `ran_at`), added to `__all__`.

### Backend — router

- **`backend/routers/accuracy.py`** (**CREATE**) —
  `POST /api/v1/accuracy/run`, `dependencies=[Depends(verify_service_token)]`,
  calls `run_due_evaluations(session)` and returns `AccuracyRunResponse`.
- **`backend/main.py`** (**MODIFY**) — imports and registers
  `accuracy.router`; module docstring's router list updated.

### Backend — tests

- **`backend/tests/conftest.py`** (**MODIFY**) — `test_settings` fixture
  now sets a deterministic `accuracy_service_token =
  "test-accuracy-service-token"` so router/dependency tests have a
  known-good value to send.
- **`backend/tests/unit/test_dependencies_auth.py`** (**MODIFY**) — new
  `TestVerifyServiceTokenSuccess` / `Failures` classes: correct token,
  missing header, empty header, wrong token, a token that is a prefix
  of the real one, and — the fail-closed guarantee — an unconfigured
  secret rejecting both a token-less and a token-bearing request.
- **`backend/tests/unit/test_accuracy_router.py`** (**CREATE**) —
  full HTTP-level coverage via `httpx.ASGITransport` (see "Testing"
  below).

### CI/CD

- **`.github/workflows/evaluate-verdicts.yml`** (**CREATE**) — the
  scheduled cron workflow described above.

### Docs

- **`docs/week-20/T-090-accuracy-scheduled-eval.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/accuracy-scheduled-eval

git branch
# → * feat/accuracy-scheduled-eval
```

### Step 2 — Add the service-token setting and dependency

- `backend/config.py`: add `accuracy_service_token`.
- `.env.example`: document `ACCURACY_SERVICE_TOKEN`.
- `backend/dependencies/auth.py`: add `service_token_header` and
  `verify_service_token`.

### Step 3 — Add the response schema and the router

- `backend/models/schemas.py`: add `AccuracyRunResponse`.
- `backend/routers/accuracy.py`: new file, `POST /api/v1/accuracy/run`.
- `backend/main.py`: register the router.

### Step 4 — Add the tests

- `backend/tests/conftest.py`: add `accuracy_service_token` to
  `test_settings`.
- `backend/tests/unit/test_dependencies_auth.py`: extend with
  `verify_service_token` coverage.
- `backend/tests/unit/test_accuracy_router.py`: new file.

### Step 5 — Add the scheduled workflow

Create `.github/workflows/evaluate-verdicts.yml`.

### Step 6 — Configure the two required GitHub repository secrets

Before this workflow can run for real (either scheduled or via manual
dispatch), set both secrets in **Settings → Secrets and variables →
Actions → Repository secrets**:

| Secret | Value |
| --- | --- |
| `AIRP_API_BASE_URL` | The deployed backend's base URL, no trailing slash (e.g. `https://airp-backend.onrender.com`) |
| `ACCURACY_SERVICE_TOKEN` | The **exact same** value as the deployed backend's `ACCURACY_SERVICE_TOKEN` environment variable |

Generate a token locally with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 7 — Run the full verification gate locally

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

### Step 8 — Manual smoke test against a local server (optional)

```bash
# Terminal 1
set ACCURACY_SERVICE_TOKEN=local-dev-secret
uvicorn backend.main:app --reload --port 8000

# Terminal 2 -- rejected (no token)
curl -i -X POST http://localhost:8000/api/v1/accuracy/run
# -> 401

# Terminal 2 -- accepted
curl -i -X POST http://localhost:8000/api/v1/accuracy/run \
  -H "X-Service-Token: local-dev-secret"
# -> 200 {"due_count": 0, "evaluated_count": 0, "skipped_count": 0, "ran_at": "..."}
```

### Step 9 — Commit (two-commit pattern)

```bash
git add backend/config.py .env.example
git add backend/dependencies/auth.py
git add backend/models/schemas.py
git add backend/routers/accuracy.py backend/main.py
git add backend/tests/conftest.py
git add backend/tests/unit/test_dependencies_auth.py
git add backend/tests/unit/test_accuracy_router.py
git add .github/workflows/evaluate-verdicts.yml
git add docs/week-20/T-090-accuracy-scheduled-eval.md

git commit -m "feat(ci): schedule daily verdict accuracy evaluation

- Add POST /api/v1/accuracy/run, protected by a new
  verify_service_token dependency (static X-Service-Token header,
  constant-time comparison, fails closed when unconfigured)
- Add AccuracyRunResponse schema and backend/routers/accuracy.py;
  register the router in main.py
- Add ACCURACY_SERVICE_TOKEN setting + .env.example documentation
- Add .github/workflows/evaluate-verdicts.yml: daily cron
  (18:30 UTC / 00:00 IST, after NSE/BSE close+settlement) plus a
  workflow_dispatch trigger for manual testing; fails the run loudly
  on any non-200 response
- Add full unit + HTTP-level test coverage for the new auth
  dependency and router

Closes #90"
```

If `pre-commit` auto-fixes formatting on commit (Windows App Control
blocks the hook shims per the established workaround), commit with
`--no-verify` and let CI's Linux runners be the real enforcement gate:

```bash
git commit --no-verify -m "..."
```

If a formatter modifies files after staging, re-stage and make a
second, separate commit rather than amending:

```bash
git add -A
git commit -m "style: apply black/isort formatting to T-090 files"
```

### Step 10 — Push and open the PR

```bash
git push -u origin feat/accuracy-scheduled-eval
```

**Base branch:** `main`
**Compare branch:** `feat/accuracy-scheduled-eval`

## Pull Request

**PR title:**

```
ci: add scheduled GitHub Actions workflow for verdict evaluation
```

**PR description:**

```markdown
## Summary
Adds POST /api/v1/accuracy/run (service-token protected) and a daily
GitHub Actions cron workflow that calls it, closing the loop T-087-
T-089 opened: verdicts are now scored automatically, on a schedule,
with no manual step required.

## Changes
- `verify_service_token` dependency (backend/dependencies/auth.py) --
  static X-Service-Token header, constant-time comparison, fails
  closed when ACCURACY_SERVICE_TOKEN is not configured
- `AccuracyRunResponse` schema + `backend/routers/accuracy.py` --
  POST /api/v1/accuracy/run, registered in main.py
- `ACCURACY_SERVICE_TOKEN` config setting + .env.example docs
- `.github/workflows/evaluate-verdicts.yml` -- daily cron
  (18:30 UTC / 00:00 IST) + workflow_dispatch for manual runs; fails
  the workflow run on any non-200 response so a rotated/mismatched
  token is never a silent no-op
- Full test coverage: unit tests for verify_service_token, HTTP-level
  tests for the router (auth rejection, success shape, fail-closed
  behaviour)

## Testing
- `ENVIRONMENT=test python -m pytest backend/tests/unit -v` -- all
  green, including the new test_accuracy_router.py and the extended
  test_dependencies_auth.py
- Manual smoke test: ran the app locally, confirmed
  POST /api/v1/accuracy/run returns 401 with no/wrong token and 200
  with the correct one
- `black --check backend/`, `isort --check-only backend/`,
  `flake8 backend/`, `mypy backend/` all pass
- Workflow YAML validated with `yaml.safe_load` and reviewed manually
  against GitHub Actions' documented schema (a real scheduled/
  dispatched run can only be confirmed once this PR merges to `main`
  and the two repository secrets are configured -- see the workflow
  doc's Step 6)

## LangSmith Trace
N/A -- no LLM-facing code; this task is auth, an HTTP endpoint, and a
CI workflow file.

## Screenshots
N/A -- no UI change.

## Related Issues
Closes #90
```

## Testing

Backend (`ENVIRONMENT=test python -m pytest backend/tests/unit -v`):

New/extended coverage:

- `test_dependencies_auth.py::TestVerifyServiceTokenSuccess` — the
  correct token returns `None` without raising.
- `test_dependencies_auth.py::TestVerifyServiceTokenFailures` — missing
  token, empty-string token, wrong token, a token that is a prefix of
  the real one (guards against an off-by-one comparison bug), and two
  fail-closed cases: an unconfigured secret rejects a request with no
  token AND a request that does supply some token.
- `test_accuracy_router.py::TestRunEndpointAuth` — no header → 401;
  wrong token → 401; empty token header → 401; an unauthenticated call
  never reaches `run_due_evaluations` at all; an unconfigured secret
  rejects even a token that would otherwise be "correct" for a
  different, properly-configured instance.
- `test_accuracy_router.py::TestRunEndpointSuccess` — correct token →
  200; the response body's `due_count`/`evaluated_count`/
  `skipped_count`/`ran_at` match `run_due_evaluations`'s returned
  `EvaluationBatchResult`; a zero-due-rows result still returns 200
  (not an error); `run_due_evaluations` is called with the request's
  session and no `now` override (letting T-089's own default-to-now
  behaviour apply); `ran_at` is a genuine current UTC timestamp bounded
  between the request's before/after wall-clock time.

No existing test file changes beyond `conftest.py` (one new field on
the shared `test_settings` fixture, additive and defaulted, so no
other test using that fixture is affected) and
`test_dependencies_auth.py` (new test classes only — every existing
`get_current_user` test in that file is untouched).

All tests run fully offline against a mocked `AsyncSession` and a
patched `run_due_evaluations` — no real database connection and no
real yFinance/network access — matching the pattern already
established by `test_documents_router.py` (T-051) for HTTP-level
router tests.

The workflow file itself is validated by `yaml.safe_load` for syntax
correctness (see Step 7 above) and by manual review against GitHub
Actions' `on.schedule` / `on.workflow_dispatch` / `jobs` schema; the
scheduled trigger and the manual `workflow_dispatch` button can only be
exercised for real once this PR is merged to `main` (GitHub only reads
`schedule` triggers from the workflow file on the default branch) and
the two repository secrets from Step 6 are configured.

## Verification gate run locally before pushing

Backend:

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

Frontend: unaffected — no frontend files touched by this task.

```bash
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

## LangSmith Trace

N/A — no agent, prompt, or LLM-facing code touched; this task adds an
HTTP endpoint, an auth dependency, and a CI workflow file only.

## Related Issues

Closes #90 (adjust to your actual issue number if different).