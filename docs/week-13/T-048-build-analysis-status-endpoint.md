# T-048 -- Build Analysis Status Endpoint

**Phase:** 5 -- FastAPI Backend
**Week:** 13
**Branch:** `feat/api-analysis-status`
**Task status:** Complete

---

## Overview

T-048 adds the read side of the analysis lifecycle: a polling endpoint
that lets a client follow an analysis job from `pending` through
`running` to `completed` (or `failed`), without needing the WebSocket
streaming endpoint that T-049/T-050 will add later. It reuses the exact
`analyses` row T-047's pipeline trigger created and T-033's
`StatePersistenceService` keeps updating after every LangGraph node.

**Acceptance criteria (all must pass):**

- Status updates reflect actual pipeline progress
- 404 for unknown job_id

**Explicitly out of scope for this task** (separate Phase 5 tasks, per
the master task list):

- `WS /api/v1/analysis/{job_id}/stream` -> **T-049/T-050** (real-time
  push; this task is poll-only)
- Document upload endpoint -> later T-05x
- Any change to how or when the pipeline itself writes
  `last_completed_node` / `status` -- T-033's `StatePersistenceService`
  already does this correctly; T-048 only _reads_ it

---

## What Was Built

### `backend/services/analysis.py` (modified -- additive only)

T-047's three functions (`resolve_company`, `get_or_create_company`,
`create_analysis_job`, `run_analysis_pipeline`) are untouched. T-048
adds:

- **`CANONICAL_NODE_SEQUENCE`** -- the 9-phase "happy path" through the
  real 15-node graph (`backend.graph.graph.build_graph`), used as the
  denominator for progress percentage. The 4 parallel research agents
  collapse into one phase (`research_join`, the node that actually gets
  a persistence checkpoint per `_persist_after`'s docstring); the two
  conditional detour nodes (`error_handler`, `sentiment_escalation`)
  are deliberately excluded from the denominator since they don't run
  on every analysis (`backend.graph.routing.route_after_research`) --
  including them would understate progress on the far more common path
  that skips them.
- **`PHASE_DISPLAY_NAMES`** -- human-readable label per node name,
  including the two detour nodes (so a job that _does_ take a detour
  still gets a sensible phase string instead of a bare technical name).
- **`compute_progress(last_completed_node, status)`** -- a pure
  function (no I/O) that derives `(current_phase, completed_nodes,
progress_percent)`. `status='completed'` always returns 100% and the
  full sequence, regardless of which node technically wrote the last
  checkpoint (the existing pipeline sets `status='completed'` as early
  as `portfolio_manager_node`, even though `report_generator` and
  `pdf_export` still run afterward -- see
  `backend.graph.nodes._portfolio_manager_impl`). `status='failed'`
  prefixes the phase with `"Failed after: "` (or substitutes a distinct
  "failed before the pipeline could start" message when no checkpoint
  exists yet) rather than reusing the plain in-progress phrasing, since
  `mark_failed` (T-033) does not change `last_completed_node` and
  showing the bare in-progress label for a dead job would read as
  "still running."
- **`AnalysisStatusResult`** -- a frozen dataclass holding everything
  the router needs, already derived; maps 1:1 onto
  `AnalysisStatusResponse`.
- **`get_analysis_status(session, job_id, user_id)`** -- reads exactly
  the columns needed in one raw SQL round trip (`last_completed_node`
  and `state_snapshot` are T-033-migration-only columns, never added to
  the `Analysis` ORM model -- the same reason
  `state_persistence.py`'s own status-reading code uses `text()`
  instead of `select(Analysis)`). Returns `None` both when no row
  exists for `job_id` and when a row exists but belongs to a different
  `user_id` -- deliberately not distinguishing the two so the router
  can return a 404 in both cases without ever revealing to a non-owner
  whether a given `job_id` is valid.

### `backend/routers/analysis.py` (modified -- additive only)

```
GET /api/v1/analysis/{job_id}/status
```

Added alongside the existing `POST /start` handler in the same router
module (not a new router file -- the analysis router already owns the
`/api/v1/analysis` prefix). Requires authentication via the existing
T-046 `get_current_user` dependency. Calls
`backend.services.analysis.get_analysis_status` and raises
`HTTPException(404)` when it returns `None`; otherwise maps the result
1:1 onto `AnalysisStatusResponse` and returns `200 OK`.

### `backend/models/schemas.py` (modified -- additive only)

Added **`AnalysisStatusResponse`**: `job_id`, `status`, `current_phase`,
`completed_nodes` (`list[str]`), `progress_percent` (`int`, constrained
`0 <= x <= 100` via Pydantic's `ge`/`le`), `error_message` (nullable),
and `requested_at` / `started_at` / `completed_at` (all nullable
`datetime`). T-046/T-047 schemas are untouched.

### `backend/main.py` / `backend/routers/__init__.py` (docstrings only)

No code change -- the new route lives on the _existing_ `analysis.router`
object, which `main.py` already registers via
`application.include_router(analysis.router)`. Only the module
docstrings were updated to record that T-048 is complete and to note
where the new route lives.

### Tests (modified -- additive only)

- **`backend/tests/unit/test_analysis_service.py`** -- new test classes
  `TestComputeProgressPending` / `Running` / `Completed` / `Failed`
  (covering every status value, every canonical node, the two
  conditional-detour nodes, monotonicity of the percentage as the
  pipeline advances through `CANONICAL_NODE_SEQUENCE`, and the
  99%-cap-while-running / 100%-only-when-completed contract) and
  `TestGetAnalysisStatusNotFound` / `Found` (no row, wrong-owner row,
  owner row, derived fields matching `compute_progress` called
  directly, error message pass-through, full-progress-on-completed).
  T-047's existing test classes for `resolve_company` /
  `get_or_create_company` / `create_analysis_job` /
  `run_analysis_pipeline` are untouched.
- **`backend/tests/unit/test_analysis_router.py`** -- new test classes
  `TestGetStatusNotFound` (unknown `job_id` -> 404, malformed `job_id`
  -> 422, another user's job -> 404, missing auth -> 401) and
  `TestGetStatusSuccess` (pending/running/completed/failed bodies, two
  consecutive polls with no progress returning byte-identical JSON, and
  -- the literal acceptance criterion -- progress increasing as
  `last_completed_node` advances between polls). The existing
  `_FakeAnalysisSession` fake (T-047) was extended with a
  `status_overrides` dict and a branch on `isinstance(statement,
TextClause)` so it can serve T-048's raw-SQL status query alongside
  the existing `select(Company)` ORM query it already handled; T-047's
  test classes (`TestStartAnalysisSuccess`, `TestJobPersistence`,
  `TestBackgroundScheduling`, `TestLatency`, etc.) are untouched and
  still pass against the extended fake.

---

## Files Changed

| File                                                   | Change                                                                                                                                    |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/services/analysis.py`                         | **Modified** -- added `CANONICAL_NODE_SEQUENCE`, `PHASE_DISPLAY_NAMES`, `compute_progress`, `AnalysisStatusResult`, `get_analysis_status` |
| `backend/routers/analysis.py`                          | **Modified** -- added `GET /{job_id}/status`                                                                                              |
| `backend/models/schemas.py`                            | **Modified** -- added `AnalysisStatusResponse`                                                                                            |
| `backend/main.py`                                      | **Modified** -- docstring only, no code change                                                                                            |
| `backend/routers/__init__.py`                          | **Modified** -- docstring only                                                                                                            |
| `backend/tests/unit/test_analysis_service.py`          | **Modified** -- added `compute_progress` / `get_analysis_status` test classes                                                             |
| `backend/tests/unit/test_analysis_router.py`           | **Modified** -- extended the fake session; added `GET /status` test classes                                                               |
| `docs/week-13/T-048-build-analysis-status-endpoint.md` | **New** -- this document                                                                                                                  |

No other files were modified. `backend/services/state_persistence.py`
(T-033) is reused as-is -- T-048 reads the exact same `last_completed_node`
/ `status` / `error_message` columns that module already writes; no
change to it was needed or made.

---

## Design Decisions & Rationale

**Why a new function in the same `services/analysis.py` module instead
of a new file?** `get_analysis_status` and `compute_progress` belong to
the same business domain as T-047's `resolve_company` /
`get_or_create_company` / `create_analysis_job` -- they all operate on
the same `analyses`/`companies` tables on behalf of the same router.
Splitting "trigger" and "status" into separate service modules would
mean importing across files for what is conceptually one workflow
(`POST /start` followed by repeated `GET /status` polls against the row
it created), with no testing or layering benefit to offset that split.

**Why is `compute_progress` a separate, pure function instead of being
inlined into `get_analysis_status`?** It has zero I/O and a small,
exhaustively enumerable input space (4 status values x ~12 possible
node names x None) -- exactly the kind of logic that benefits from
direct unit tests with no mocking at all. Keeping it separate means the
percentage/phase-label logic can be tested for every status/node
combination without touching a database mock even once.

**Why does `status='completed'` always report 100%, even if
`last_completed_node` is `'planner'`?** This mirrors a real, pre-existing
quirk in the pipeline rather than fighting it: `_portfolio_manager_impl`
(T-041) sets `status='completed'` on the `analyses` row as soon as the
Portfolio Manager's decision is in, even though `report_generator`
(T-042) and `pdf_export` (T-043) still run afterward to produce the
memo and PDF. From the caller's perspective, once `status='completed'`
the investment decision itself is final and the remaining two nodes are
best-effort artifact generation -- showing 100% the moment the decision
is final is the more honest signal than showing some intermediate
percentage while the _decision itself_ is already done.

**Why prefix `"Failed after: "` instead of just reusing the in-progress
phase label when `status='failed'`?** `StatePersistenceService.mark_failed`
(T-033) sets `status='failed'` and `error_message` but does **not**
touch `last_completed_node` -- so without a distinct failed-state label,
a failed job polled right after `mark_failed` ran would show e.g.
`"Running DCF valuation and peer comparison"`, which reads exactly like
the pipeline is still actively working, when it has actually stopped.

**Why raw SQL (`text()`) instead of extending the `Analysis` ORM model
to map `last_completed_node` / `state_snapshot`?** Those two columns
were deliberately added via a standalone Alembic migration (T-033) and
never added to `backend/models/orm.py`'s `Analysis` class -- changing
that now would be an unrelated, larger refactor (every other place that
constructs an `Analysis` ORM instance, including T-047's
`create_analysis_job`, would need re-auditing against the new mapped
columns) for a task whose entire job is to _read_ two columns that
already have a working read path (`state_persistence.py`'s own
`_SQL_LOAD_SNAPSHOT`) to copy the pattern from.

**Why does `get_analysis_status` return `None` for a wrong-owner job
instead of raising something the router could turn into a `403`?**
Returning a `403 Forbidden` would itself leak information: it tells an
attacker "this `job_id` exists, you just can't see it," which is enough
to confirm someone else's analyses are real UUIDs worth targeting
further. Folding "doesn't exist" and "not yours" into the identical
`404` response is the standard mitigation for this class of enumeration
risk, and costs nothing here since the endpoint has no legitimate use
case for telling a non-owner that a `job_id` is valid.

---

## How T-048 Was Implemented (full workflow)

### 1. Sync with `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/api-analysis-status
```

### 2. Confirm the starting point (T-047 already merged)

```bash
git log --oneline -5
cat backend/routers/analysis.py     # should show only POST /start so far
grep -n "last_completed_node" backend/services/state_persistence.py
```

The second command confirms T-033's `_SQL_LOAD_SNAPSHOT` /
`_SQL_UPSERT_SNAPSHOT` pattern is in place -- T-048 reuses that exact
approach for its own read query.

### 3. Add the new schema

Edit `backend/models/schemas.py`: add `AnalysisStatusResponse`
immediately after `AnalysisStartResponse`, and add the new name to the
module's `__all__` list. Do **not** add `from __future__ import
annotations` -- the existing project-wide rule.

### 4. Add the progress-computation and status-read functions

Edit `backend/services/analysis.py`: add `CANONICAL_NODE_SEQUENCE`,
`PHASE_DISPLAY_NAMES`, `compute_progress`, `AnalysisStatusResult`, and
`get_analysis_status` at the end of the file, after T-047's existing
functions. No changes to any existing function in this file.

### 5. Add the router endpoint

Edit `backend/routers/analysis.py`: add the `GET /{job_id}/status`
handler after the existing `POST /start` handler, in the same file, on
the same `router` object. Import `HTTPException` and `uuid` at the top.

### 6. Update docstrings only

Edit `backend/main.py` and `backend/routers/__init__.py` docstrings to
record T-048 as complete -- no executable code changes in either file,
since the new route is on the already-registered `analysis.router`.

### 7. Extend the test fake and write the tests

Edit `backend/tests/unit/test_analysis_service.py`: add the
`compute_progress` and `get_analysis_status` test classes at the end.

Edit `backend/tests/unit/test_analysis_router.py`: extend
`_FakeAnalysisSession` with `status_overrides` and the
`isinstance(statement, TextClause)` branch in `execute()`, add the
`_seed_status_row` helper, then add the `TestGetStatusNotFound` /
`TestGetStatusSuccess` classes at the end. Run T-047's existing classes
first to confirm the fake-session extension did not break them:

```bash
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_router.py::TestStartAnalysisSuccess -v
ENVIRONMENT=test pytest backend/tests/unit/test_analysis_router.py::TestJobPersistence -v
```

### 8. Run the full new test coverage

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

Auto-fix and re-stage if needed (standard AIRP two-commit pattern):

```bash
black backend/
isort backend/
```

### 11. Confirm coverage

```bash
ENVIRONMENT=test pytest --cov=backend --cov-report=term-missing -m "not integration" -q
```

`compute_progress` in particular should show 100% line coverage --
every branch (pending/running/completed/failed x in-sequence node /
detour node / `None`) has a dedicated test case.

### 12. Manual smoke test (optional, requires a running Postgres)

```bash
uvicorn backend.main:app --reload --port 8000
```

Trigger an analysis (T-047), then poll its status repeatedly:

```bash
TOKEN="<bearer token from /auth/login>"
JOB_ID="<job_id from POST /api/v1/analysis/start>"

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/analysis/$JOB_ID/status | python3 -m json.tool
```

Expect `status` to move `pending` -> `running` -> `completed` (or
`failed`) across repeated polls as the real LangGraph pipeline runs,
`progress_percent` to climb without ever stalling backward, and a
nonexistent or someone-else's `job_id` to return `404`:

```bash
curl -i -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/analysis/$(python3 -c "import uuid; print(uuid.uuid4())")/status
# expect: HTTP/1.1 404 Not Found
```

### 13. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/services/analysis.py \
        backend/routers/analysis.py \
        backend/models/schemas.py \
        backend/main.py \
        backend/routers/__init__.py \
        backend/tests/unit/test_analysis_service.py \
        backend/tests/unit/test_analysis_router.py \
        docs/week-13/T-048-build-analysis-status-endpoint.md
git commit -m "feat(api): add analysis status polling endpoint"
```

If black/isort auto-fix anything (standard AIRP two-commit pattern):

```bash
git add .
git commit -m "feat(api): add analysis status polling endpoint"
```

On Windows, if a pre-commit hook shim is blocked by Application
Control:

```bash
git commit --no-verify -m "feat(api): add analysis status polling endpoint"
```

### 14. Push and open PR

```bash
git push -u origin feat/api-analysis-status
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**

```
feat(api): implement GET /analysis/{job_id}/status with progress tracking
```

**PR description:**

```markdown
## Summary

Adds GET /api/v1/analysis/{job_id}/status: lets a client poll the
current lifecycle status, phase, completed nodes, and progress
percentage for an analysis job triggered by T-047's POST /start. Reads
directly from the same analyses row T-033's StatePersistenceService
updates after every LangGraph node completes, so status updates always
reflect the pipeline's actual progress rather than an estimate. Returns
404 for an unknown job_id, and -- to avoid leaking which job_id UUIDs
exist -- also returns 404 (not 403) when job_id belongs to a different
user.

## Changes

- `backend/services/analysis.py` -- added CANONICAL_NODE_SEQUENCE (the
  9-phase canonical path through the real 15-node graph) and
  PHASE_DISPLAY_NAMES; compute_progress (pure function deriving
  current_phase/completed_nodes/progress_percent from
  last_completed_node and status -- 100% only when status='completed',
  a distinct "Failed after: ..." phase when status='failed', monotonic
  percentage as the canonical sequence advances); AnalysisStatusResult
  dataclass; get_analysis_status (raw-SQL read scoped to the requesting
  user, returning None for both "does not exist" and "not yours" so
  the router can 404 either case identically)
- `backend/routers/analysis.py` -- added GET /{job_id}/status, requires
  authentication via the existing T-046 get_current_user dependency,
  returns 200 with AnalysisStatusResponse or 404 via HTTPException
- `backend/models/schemas.py` -- added AnalysisStatusResponse
- `backend/main.py`, `backend/routers/__init__.py` -- docstring updates
  only (the new route lives on the already-registered analysis router)
- `backend/tests/unit/test_analysis_service.py` -- new test classes
  covering every status/node combination for compute_progress and
  every not-found/found path for get_analysis_status
- `backend/tests/unit/test_analysis_router.py` -- extended the existing
  fake AsyncSession to also serve the raw-SQL status query (via a new
  status_overrides dict and a TextClause branch), then added test
  classes covering both acceptance criteria directly: 404 for unknown
  job_id, and progress increasing across polls as last_completed_node
  advances (plus the converse: two polls with no progress return
  byte-identical bodies)

## Testing

- `ENVIRONMENT=test pytest backend/tests/unit/test_analysis_service.py backend/tests/unit/test_analysis_router.py -v`
  -- new and existing suites; TestGetStatusNotFound/TestGetStatusSuccess
  cover both T-048 acceptance criteria directly
- `ENVIRONMENT=test pytest backend/tests/unit/test_analysis_router.py::TestStartAnalysisSuccess backend/tests/unit/test_analysis_router.py::TestJobPersistence -v`
  -- confirms extending the fake session for T-048 did not break any
  T-047 test
- `ENVIRONMENT=test pytest --tb=short -q` -- full existing suite, no
  regressions
- Manual smoke test: triggered a real analysis via POST /start, polled
  GET /status repeatedly while the pipeline ran, confirmed
  status/progress_percent advanced correctly through pending -> running
  -> completed; confirmed a random UUID returns 404
- `black --check`, `isort --check-only`, `flake8`, `mypy` all run
  locally against the new and modified files before pushing

## LangSmith Trace

Not applicable -- this PR adds a read-only status endpoint and does not
modify any agent or LangGraph node code. LangSmith tracing remains
disabled project-wide until T-067 (Phase 7 evaluation framework).

## Related Issues

Closes #48
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

With T-048 complete, a client can now both start an analysis (T-047)
and poll it to completion (T-048) entirely over plain HTTP request/
response -- enough to build a basic "refresh button" progress UI today,
even before the real-time WebSocket viewer exists.

Next task: **T-049 -- Build WebSocket streaming infrastructure**
(`WS /api/v1/analysis/{job_id}/stream`; pushes the same
phase/progress/error fields T-048 already computes, but live, without
the client needing to poll). `compute_progress` and
`get_analysis_status` built in this task should be directly reusable
as the data source for each WebSocket push event -- no new progress
logic should be required, only a way to call them on a timer or on
each `_persist_after` checkpoint and push the result over the socket.

Branch: `feat/api-websocket-stream`.

---

_End of Document | T-048 Workflow | AIRP Week 13_
