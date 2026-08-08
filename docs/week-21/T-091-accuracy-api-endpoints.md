# T-091 — GET /accuracy/summary and /accuracy/history endpoints

**Phase:** 8 — Verdict Accuracy Tracker
**Week:** 21
**Branch:** `feat/accuracy-api-endpoints`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 3

## Summary

T-087–T-090 built the write side of the Verdict Accuracy Tracker
(schema, recording, evaluation, and a scheduled job to run it). T-091
adds the read side: two public, unauthenticated GET endpoints that
aggregate and list `verdict_outcomes` rows for T-092's upcoming public
`AccuracyPage.tsx` dashboard.

1. **`GET /api/v1/accuracy/summary`** — overall accuracy percentage,
   plus a breakdown by verdict type (BUY/HOLD/SELL) and a breakdown by
   conviction-score bucket (Low 1-3 / Medium 4-6 / High 7-10).
2. **`GET /api/v1/accuracy/history`** — every tracked verdict outcome
   (evaluated or still pending), paginated, newest verdict first.

## Acceptance criteria (from task spec)

- [x] `/accuracy/summary` returns overall + by-verdict + by-conviction
      breakdowns
- [x] `/accuracy/history` paginated
- [x] Both covered by pytest

## Design decisions

- **Both endpoints are public — no `Depends(get_current_user)` and no
  `Depends(verify_service_token)`.** `GET /api/v1/analysis/history`
  (T-050) is scoped to `current_user.id` because it answers "what has
  *this* user run". These two endpoints answer "how accurate has
  AIRP's committee been overall" — a platform-wide statistic.
  `verdict_outcomes` rows aren't even owned by a user (their only FK is
  `analysis_id`, not `user_id`), and T-092's own task spec calls the
  page that consumes this data a "public accuracy dashboard". Putting
  auth on data that's meant to be publicly displayed would just be
  friction with no security benefit.
- **Three independent queries in `get_accuracy_summary`** (overall
  counts, `GROUP BY verdict`, `GROUP BY` a conviction-score bucket
  `CASE` expression) rather than one combined query — the same
  "several plain, independently-readable statements over one query
  trying to do everything at once" preference
  `get_analysis_history`'s own docstring documents (T-050). This is a
  page read by a human dashboard at human-interaction frequency, not a
  hot loop, so three small round trips cost nothing that matters next
  to the clarity win.
- **`by_verdict` and `by_conviction` always return exactly 3 entries
  each**, even for a brand-new, empty `verdict_outcomes` table — BUY,
  HOLD, SELL always appear (with zero counts if no rows of that verdict
  exist yet), and low/medium/high always appear the same way. The
  `GROUP BY` queries only return rows for keys that actually exist in
  the table; the service function fills in the missing keys with zero
  counts in Python rather than making the frontend chart handle a
  variable-length, key-optional response shape.
- **`accuracy_pct` is `None`, not `0.0`, when `evaluated_count` is
  0.** A verdict type or conviction bucket with no scored rows yet has
  an *unknown* accuracy, not a 0% (all-wrong) track record — collapsing
  the two would make a bucket that simply hasn't been scored yet look
  identical to one that has been scored and found completely wrong.
- **Conviction buckets are a fixed three-way split (1-3 / 4-6 /
  7-10), not one bucket per score or a configurable width.**
  Conviction scores are always integers 1–10
  (`InvestmentDecision.conviction_score`, enforced there and by
  `VerdictOutcome.conviction_score`'s `NOT NULL` column), so three
  buckets keep `GET /accuracy/summary`'s response a small, fixed shape
  a dashboard can render without knowing how many buckets to expect
  ahead of time. T-092's conviction-vs-accuracy *scatter plot* (one
  point per analysis, not a bucketed rollup) reads unbucketed
  `conviction_score` values straight off `GET /accuracy/history`
  instead.
- **`GET /accuracy/history` returns *every* row, evaluated or still
  pending** — not just scored ones. A still-pending row has `null` for
  `price_at_evaluation`/`price_change_pct`/`directional_correct`/
  `evaluated_at`, which is exactly what a "has this verdict been
  checked yet" column on the dashboard needs to render a pending state
  rather than silently omitting the row until it's scored.
- **Plain SQLAlchemy Core `select(...)` queries, not raw `text()`
  SQL.** `get_analysis_history`'s raw-SQL approach (T-050) exists
  specifically to reach into a JSONB column with Postgres's `->>`
  operator; `verdict_outcomes` has no such need — it's a plain
  relational table with typed columns — so a normal `select(...)`
  query gets the same result with full ORM type coercion (e.g.
  `Numeric(..., asdecimal=False)` → Python `float`, not `Decimal`)
  applied automatically, and mirrors the `select(VerdictOutcome)` style
  `run_due_evaluations` (T-089) already uses in this same module.
- **Result rows are read by tuple index (`row[0]`, `row[1]`, ...), not
  by attribute name off the `Row` object**, even where a column is
  `.label()`-ed for SQL readability. This sidesteps a `mypy --strict`
  complaint about accessing a dynamically-named attribute on a
  generically-typed `Row[Any]` without a bare `type: ignore` — a rule
  this project never breaks — and matches the "asyncpg-style tuple"
  convention `get_analysis_history`'s own docstring already
  establishes for raw-SQL rows.
- **`func.count(...).filter(...)` (Postgres `FILTER (WHERE ...)`) is
  an acceptable Postgres-only dependency** here the same way
  `get_analysis_history` already depends on Postgres-only JSONB `->>`
  — this project's only deployed and only CI-tested database is
  PostgreSQL (Neon in production, the `postgres:16-alpine` service
  container in CI), and every test in this task mocks `AsyncSession`
  directly rather than exercising a live database.
- **No defensive `try/except` in either new route.**
  `get_accuracy_summary` and `get_accuracy_history` are documented as
  never raising an exception these routes would need to translate into
  an HTTP error code — the same contract `run_due_evaluations` (T-089)
  already established and `POST /run`'s router code already trusts.

## Files changed / created

### Backend — service

- **`backend/services/accuracy_tracker.py`** (**MODIFY**) — adds
  `get_accuracy_summary()`, `get_accuracy_history()`, their supporting
  dataclasses (`VerdictAccuracyBreakdown`, `ConvictionAccuracyBreakdown`,
  `AccuracySummary`, `AccuracyHistoryEntry`, `AccuracyHistoryPage`), and
  the `DEFAULT_ACCURACY_HISTORY_PAGE_SIZE` / `MAX_ACCURACY_HISTORY_PAGE_SIZE`
  pagination constants. `__all__` extended.

### Backend — schema

- **`backend/models/schemas.py`** (**MODIFY**) — new
  `VerdictAccuracyBreakdownResponse`, `ConvictionAccuracyBreakdownResponse`,
  `AccuracySummaryResponse`, `AccuracyHistoryEntryResponse`,
  `AccuracyHistoryResponse`; all added to `__all__`.

### Backend — router

- **`backend/routers/accuracy.py`** (**MODIFY**) — adds
  `GET /api/v1/accuracy/summary` and `GET /api/v1/accuracy/history`
  alongside the existing `POST /api/v1/accuracy/run`; module docstring
  updated to cover all three routes. No change needed in
  `backend/main.py` — the router is already registered from T-090.

### Backend — tests

- **`backend/tests/unit/test_accuracy_summary_history.py`**
  (**CREATE**) — service-layer tests for `get_accuracy_summary()` /
  `get_accuracy_history()` against a mocked `AsyncSession`, plus
  HTTP-level router tests via `httpx.ASGITransport` for both new
  routes (see "Testing" below).

### Docs

- **`docs/week-21/T-091-accuracy-api-endpoints.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/accuracy-api-endpoints

git branch
# → * feat/accuracy-api-endpoints
```

### Step 2 — Add the read-side aggregation functions to the service

Edit `backend/services/accuracy_tracker.py`:

- Add `DEFAULT_ACCURACY_HISTORY_PAGE_SIZE` / `MAX_ACCURACY_HISTORY_PAGE_SIZE`.
- Add `VerdictAccuracyBreakdown`, `ConvictionAccuracyBreakdown`,
  `AccuracySummary` dataclasses and `get_accuracy_summary(session)`.
- Add `AccuracyHistoryEntry`, `AccuracyHistoryPage` dataclasses and
  `get_accuracy_history(session, limit, offset)`.
- Extend `__all__`.

### Step 3 — Add the response schemas

Edit `backend/models/schemas.py`:

- Add `VerdictAccuracyBreakdownResponse`, `ConvictionAccuracyBreakdownResponse`,
  `AccuracySummaryResponse`.
- Add `AccuracyHistoryEntryResponse`, `AccuracyHistoryResponse`.
- Extend `__all__`.

### Step 4 — Add the two router endpoints

Edit `backend/routers/accuracy.py`:

- Add `GET /summary` calling `get_accuracy_summary` and returning
  `AccuracySummaryResponse`.
- Add `GET /history` with `limit`/`offset` `Query(...)` params (same
  clamping pattern as `GET /analysis/history`) calling
  `get_accuracy_history` and returning `AccuracyHistoryResponse`.
- Update the module docstring's route list and acceptance-criteria
  section.

### Step 5 — Add the tests

Create `backend/tests/unit/test_accuracy_summary_history.py`:

- Service-layer tests for `get_accuracy_summary` (empty table, all
  three verdicts/buckets always present, accuracy_pct math and
  rounding, a verdict/bucket with rows but none evaluated yet, query
  order).
- Service-layer tests for `get_accuracy_history` (pagination,
  `has_more`, field mapping for pending vs. evaluated rows, query
  order).
- HTTP-level tests for both new routes (no auth required, response
  shape matches the service return value, `Query` validation errors
  for out-of-range `limit`/`offset`).

### Step 6 — Run the full verification gate locally

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

### Step 7 — Manual smoke test against a local server (optional)

```bash
# Terminal 1
uvicorn backend.main:app --reload --port 8000

# Terminal 2 -- summary (no auth header needed)
curl -s http://localhost:8000/api/v1/accuracy/summary | python -m json.tool

# Terminal 2 -- history, first page
curl -s http://localhost:8000/api/v1/accuracy/history | python -m json.tool

# Terminal 2 -- history, a smaller page further in
curl -s "http://localhost:8000/api/v1/accuracy/history?limit=5&offset=10" \
  | python -m json.tool

# Terminal 2 -- out-of-range limit is rejected by FastAPI's own
# Query(ge=1, le=100) validation, no service code involved
curl -i "http://localhost:8000/api/v1/accuracy/history?limit=500"
# -> 422
```

On a fresh local database (no rows in `verdict_outcomes` yet),
`/summary` should return `total_evaluated: 0`, `total_pending: 0`,
`overall_accuracy_pct: null`, and both breakdown lists still populated
with all 3 entries at zero counts; `/history` should return
`items: []`, `total_count: 0`, `has_more: false`.

### Step 8 — Commit (two-commit pattern)

```bash
git add backend/services/accuracy_tracker.py
git add backend/models/schemas.py
git add backend/routers/accuracy.py
git add backend/tests/unit/test_accuracy_summary_history.py
git add docs/week-21/T-091-accuracy-api-endpoints.md

git commit -m "feat(api): add verdict accuracy summary and history endpoints

- Add GET /api/v1/accuracy/summary -- overall accuracy percentage plus
  breakdowns by verdict type (BUY/HOLD/SELL) and conviction-score
  bucket (Low 1-3 / Medium 4-6 / High 7-10); every entry always
  present even with zero scored rows, accuracy_pct is null (not 0%)
  when nothing has been evaluated yet
- Add GET /api/v1/accuracy/history -- every verdict_outcomes row,
  evaluated or still pending, paginated newest-first (same
  limit/offset shape as GET /analysis/history)
- Add get_accuracy_summary() / get_accuracy_history() to
  backend.services.accuracy_tracker plus their supporting dataclasses
- Add AccuracySummaryResponse / AccuracyHistoryResponse and their
  nested schemas to backend.models.schemas
- Both endpoints are intentionally public (no auth dependency) --
  verdict_outcomes is a platform-wide statistic, not scoped to a user,
  and feeds T-092's public AccuracyPage.tsx dashboard
- Full unit + HTTP-level test coverage in
  test_accuracy_summary_history.py

Closes #91"
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
git commit -m "style: apply black/isort formatting to T-091 files"
```

### Step 9 — Push and open the PR

```bash
git push -u origin feat/accuracy-api-endpoints
```

**Base branch:** `main`
**Compare branch:** `feat/accuracy-api-endpoints`

## Pull Request

**PR title:**

```
feat(api): expose verdict accuracy summary and history via REST
```

**PR description:**

```markdown
## Summary
Adds the read side of the Verdict Accuracy Tracker (T-087-T-090 built
the write side): GET /api/v1/accuracy/summary and GET /api/v1/accuracy
/history, both public endpoints feeding T-092's upcoming public
AccuracyPage.tsx dashboard.

## Changes
- GET /api/v1/accuracy/summary -- total_evaluated, total_pending,
  overall_accuracy_pct, by_verdict (BUY/HOLD/SELL, always 3 entries),
  by_conviction (Low 1-3 / Medium 4-6 / High 7-10, always 3 entries).
  accuracy_pct is null rather than 0% when nothing has been evaluated
  yet for that verdict/bucket.
- GET /api/v1/accuracy/history -- paginated (limit/offset, same shape
  as GET /analysis/history), newest verdict first, every
  verdict_outcomes row including still-pending ones.
- get_accuracy_summary() / get_accuracy_history() added to
  backend.services.accuracy_tracker (three independent aggregate
  queries for summary; two queries -- count + page -- for history,
  mirroring get_analysis_history's own established pattern).
- New response schemas in backend.models.schemas.
- Neither endpoint requires authentication -- verdict_outcomes is a
  platform-wide statistic with no user_id column, and both feed a
  public dashboard page by design (see the task doc's Design
  decisions section for the full rationale).
- Full test coverage: mocked-session unit tests for both service
  functions, HTTP-level tests for both routes via httpx.ASGITransport.

## Testing
- `ENVIRONMENT=test python -m pytest backend/tests/unit -v` -- all
  green, including the new test_accuracy_summary_history.py
- Manual smoke test: ran the app locally against an empty
  verdict_outcomes table, confirmed /summary returns all-zero/null
  breakdowns (not errors) and /history returns an empty, well-formed
  page
- `black --check backend/`, `isort --check-only backend/`,
  `flake8 backend/`, `mypy backend/` all pass

## LangSmith Trace
N/A -- no LLM-facing code; this task adds two read-only REST endpoints
and their backing aggregation queries.

## Screenshots
N/A -- no UI change (T-092 builds the frontend that consumes these
endpoints).

## Related Issues
Closes #91
```

## Testing

Backend (`ENVIRONMENT=test python -m pytest backend/tests/unit -v`):

New coverage in `test_accuracy_summary_history.py`:

- **`TestGetAccuracySummaryEmpty`** — an empty `verdict_outcomes` table
  produces `total_evaluated=0`, `total_pending=0`,
  `overall_accuracy_pct=None`, and `by_verdict`/`by_conviction` each
  populated with all 3 expected entries at zero counts and `None`
  accuracy — never an empty list.
- **`TestGetAccuracySummaryPopulated`** — `overall_accuracy_pct`
  computed and rounded correctly (including a repeating-decimal case,
  66.67%); per-verdict and per-bucket counts/percentages match the
  underlying `GROUP BY` rows; a verdict with *no* rows in the DB at all
  (e.g. no SELL verdicts issued yet) still appears with zero counts
  rather than being omitted; a verdict with rows but none evaluated
  yet gets `accuracy_pct=None`, not a fabricated 0%.
- **`TestGetAccuracySummaryQueryOrder`** — exactly 3
  `session.execute()` calls per `get_accuracy_summary()` invocation.
- **`TestAccuracyBreakdownDataclasses`** — direct construction/field
  checks for `VerdictAccuracyBreakdown`, `ConvictionAccuracyBreakdown`,
  and `AccuracySummary`'s frozen-dataclass immutability.
- **`TestGetAccuracyHistoryEmpty` / `Pagination` / `EntryShape` /
  `QueryOrder`** — mirrors `test_analysis_result_history_service.py`'s
  own `TestGetAnalysisHistory*` structure (T-050) applied to
  `verdict_outcomes`: empty page, `has_more` arithmetic for
  under/over/beyond-total offsets, a still-pending row's four
  evaluation-time fields all coming through as `None`, an evaluated
  row's fields passing through unchanged, and exactly 2
  `session.execute()` calls in order (count, then page).
- **`TestSummaryEndpoint`** — `GET /accuracy/summary` returns 200 with
  zero headers (no auth required at all); response body matches
  `get_accuracy_summary()`'s return value field-for-field including
  breakdown ordering; the service is called with the request's
  session.
- **`TestHistoryEndpoint`** — `GET /accuracy/history` returns 200 with
  zero headers; default `limit`/`offset` applied when omitted;
  explicit `limit`/`offset` forwarded correctly;
  `limit > MAX_ACCURACY_HISTORY_PAGE_SIZE`, `limit < 1`, and
  `offset < 0` all return `422` from FastAPI's own `Query(...)`
  validation before the service is ever called; response body
  (including `has_more`) matches the service return value.

No existing test file changes -- `backend/routers/accuracy.py`'s
existing `POST /run` behaviour and `test_accuracy_router.py`'s
existing coverage of it are both untouched by this task.

All tests run fully offline against a mocked `AsyncSession` (service
layer) or a patched `get_accuracy_summary`/`get_accuracy_history`
(router layer via `httpx.ASGITransport`) -- no real database
connection and no real yFinance/network access, matching the pattern
already established by `test_accuracy_router.py` (T-090) and
`test_analysis_result_history_service.py` (T-050).

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

Frontend: unaffected -- no frontend files touched by this task (that's
T-092).

```bash
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

## LangSmith Trace

N/A — no agent, prompt, or LLM-facing code touched; this task adds two
read-only REST endpoints and their backing aggregation queries.

## Related Issues

Closes #91 (adjust to your actual issue number if different).