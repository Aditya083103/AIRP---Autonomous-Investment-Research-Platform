# T-089 — `accuracy_tracker` service — evaluation + scoring rule

**Phase:** 8 — Verdict Accuracy Tracker
**Week:** 20
**Branch:** `feat/accuracy-tracker-evaluate`
**Type:** Feature
**Priority:** 🔴 Critical
**Est. hours:** 4

## Summary

T-088 wrote the "pending evaluation" row; T-089 is the job that closes
the loop. `run_due_evaluations()` loads every `verdict_outcomes` row
where `evaluated_at IS NULL`, keeps the ones whose
`verdict_date + evaluation_horizon_days` has already passed, fetches
each one's current price via the existing T-010 `fetch_stock_price`
tool, computes `price_change_pct`, and scores `directional_correct`
using a **+-5% dead-zone rule** that is intentionally asymmetric per
verdict type.

This task is scoring only — nothing yet schedules `run_due_evaluations`
to run periodically (a cron trigger, a management command, an API
endpoint). That wiring is left for a later task; T-089's acceptance
criteria are about the function's correctness, not its schedule.

## Acceptance criteria (from task spec)

- [x] Rows past their `evaluation_horizon_days` are scored
- [x] `directional_correct` set correctly for BUY/HOLD/SELL per
      dead-zone rule
- [x] Unit tests cover all three verdict types

## The dead-zone scoring rule

A flat +-5% band absorbs ordinary price noise so a verdict is not
penalised for a move too small to represent a real directional
outcome. The rule is **asymmetric per verdict type** — each verdict
only fails when the price moves *against* what it predicted by more
than the dead zone:

| Verdict | Wrong when... | Correct when... |
| --- | --- | --- |
| **BUY** | price fell 5% or more (`price_change_pct <= -5.0`) | flat, or **any** rise, or a fall under 5% |
| **SELL** | price rose 5% or more (`price_change_pct >= 5.0`) | flat, or **any** fall, or a rise under 5% |
| **HOLD** | price moved 5% or more in **either** direction | stayed strictly inside (-5%, +5%) |

Boundary semantics: the dead zone is the **open** interval
`(-5.0, 5.0)`. A move of *exactly* +-5.0% counts as having left the
zone — a HOLD at exactly +5.0% is wrong; a BUY at exactly -5.0% is
wrong. 5% is the point the move stops being noise, not one step short
of it, so the boundary itself belongs to the "meaningfully moved" side.

Why asymmetric rather than "correct only inside the zone" for BUY/SELL
too: a BUY thesis is not falsified by the stock going up *more* than
expected, or by it drifting sideways within noise — it is falsified
only by the stock actually falling against the call. Scoring a flat
BUY as "wrong" (the way a HOLD would be) would penalise a directionally
correct-so-far call for not yet being big enough, which is a different
(and much stricter) question than "was the direction right".

## Design decisions

- **`run_due_evaluations` loads all pending rows, then filters "due" in
  Python**, rather than pushing the interval arithmetic into the SQL
  `WHERE` clause. `verdict_outcomes` is not expected to grow large
  enough in this project for that to matter, and doing the comparison
  in Python keeps `_is_due` a small, independently unit-testable pure
  function instead of a Postgres-specific `INTERVAL` expression that
  can only be exercised against a real database.
- **Each due row is scored and committed individually**, not batched
  into one transaction. If the job is interrupted partway through (a
  bad ticker, a dropped connection), every row already scored before
  the interruption stays scored — the next run only needs to reprocess
  whatever is still `evaluated_at IS NULL` and due. This mirrors
  T-088's per-row-is-independent design for `record_pending_evaluations`.
- **The live price fetch uses `period="1mo"`, not the pipeline's
  original `"1y"`** — only `stats.current_price` is needed, there is no
  cache to reuse either way (yFinance's 15-minute TTL is long expired
  by the time a 90-365 day-later evaluation runs), and a 1-month candle
  series is a much smaller fetch for a job that may score many rows per
  run. The call is offloaded via `asyncio.to_thread`, mirroring the
  existing "blocking yFinance call MUST run through asyncio.to_thread"
  contract `backend.services.analysis._fetch_price_history_sync`
  already documents for the sibling `fetch_ohlcv` tool.
- **Never raises, at two levels.** A failure fetching one ticker's
  price, or a DB error committing one row, is logged and counted in
  `skipped_count` — it does not stop the rest of the batch. A failure
  loading the initial pending-rows query itself returns an all-zero
  `EvaluationBatchResult` rather than propagating, matching the
  project-wide "agent/service functions must never raise" rule T-088
  already applies to `record_pending_evaluations`.
- **`_compute_price_change_pct` rounds to 4 decimal places** to match
  `VerdictOutcome.price_change_pct`'s `Numeric(8, 4)` column precision
  from T-087, and returns `0.0` (logging a warning) rather than
  dividing by zero in the pathological case of `price_at_verdict == 0`.
- **An unrecognised verdict string degrades to the HOLD rule** (the
  strictest of the three) rather than raising. `VerdictOutcome.verdict`
  is DB-enum-constrained to BUY/HOLD/SELL so this should never actually
  happen, but a scoring function returning a definite `bool` for any
  input is cheaper to guarantee than tracking down every call site that
  assumes it always will.

## Files changed / created

### Backend — service

- **`backend/services/accuracy_tracker.py`** (**MODIFY**) — adds:
  - `DEAD_ZONE_PCT = 5.0`
  - `score_directional_correctness(verdict, price_change_pct) -> bool`
  - `_compute_price_change_pct(price_at_verdict, current_price) -> float`
  - `_fetch_current_price_sync(ticker) -> tuple[Optional[float], Optional[str]]`
    (blocking; callers must run it through `asyncio.to_thread`)
  - `EvaluationBatchResult` dataclass (`due_count`, `evaluated_count`,
    `skipped_count`)
  - `_is_due(row, reference_time) -> bool`
  - `run_due_evaluations(session, now=None) -> EvaluationBatchResult`

  Module docstring rewritten to cover both T-088 and T-089 (the
  recording side and the evaluation side of the same tracker), with a
  new "The dead-zone scoring rule" section spelling out the boundary
  semantics precisely. `__all__` and the "Public API" docstring section
  extended with the four new public names.

### Backend — tests

- **`backend/tests/unit/test_accuracy_tracker.py`** (**MODIFY**) —
  four new test classes for `score_directional_correctness` (one per
  verdict type plus an unrecognised-verdict class), one for
  `_compute_price_change_pct`, and six for `run_due_evaluations` (see
  "Testing" below). Module docstring's "Test strategy" section extended
  to items 3-5.

### Docs

- **`docs/week-20/T-089-accuracy-tracker-evaluate.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/accuracy-tracker-evaluate

git branch
# → * feat/accuracy-tracker-evaluate
```

### Step 2 — Add the scoring rule and evaluation function

Edit `backend/services/accuracy_tracker.py`:

- Add `DEAD_ZONE_PCT`, `_moved_up_meaningfully`,
  `_moved_down_meaningfully`, `score_directional_correctness`.
- Add `_compute_price_change_pct`.
- Add `_fetch_current_price_sync` (imports `fetch_stock_price` from
  `backend.tools.stock_price` at module level, matching how
  `backend/services/analysis.py` already imports its sibling tools).
- Add `EvaluationBatchResult`, `_is_due`, and `run_due_evaluations`.
- Extend the module docstring and `__all__`.

### Step 3 — Add the tests

Extend `backend/tests/unit/test_accuracy_tracker.py` with the new test
classes described above.

### Step 4 — Run the full verification gate locally

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

### Step 5 — Manual smoke test against a local Postgres (optional)

Confirms the acceptance criterion end-to-end, beyond the mocked unit
tests. Requires at least one `verdict_outcomes` row whose
`verdict_date + evaluation_horizon_days` is already in the past — the
quickest way to get one locally is to insert a test row directly, or
temporarily back-date an existing row:

```sql
UPDATE verdict_outcomes
   SET verdict_date = NOW() - INTERVAL '100 days',
       evaluation_horizon_days = 90
 WHERE id = '<some-row-id>';
```

```python
# From a Python shell with the app's async session available:
from backend.services.accuracy_tracker import run_due_evaluations
result = await run_due_evaluations(session)
print(result)  # EvaluationBatchResult(due_count=1, evaluated_count=1, skipped_count=0)
```

```bash
psql "$DATABASE_URL" -c "SELECT ticker, verdict, price_at_verdict, \
  price_at_evaluation, price_change_pct, directional_correct, evaluated_at \
  FROM verdict_outcomes WHERE evaluated_at IS NOT NULL \
  ORDER BY evaluated_at DESC LIMIT 5;"
```

### Step 6 — Commit (two-commit pattern)

```bash
git add backend/services/accuracy_tracker.py
git add backend/tests/unit/test_accuracy_tracker.py
git add docs/week-20/T-089-accuracy-tracker-evaluate.md

git commit -m "feat(services): evaluate due verdict outcomes against live price

- Add score_directional_correctness(): +-5% dead-zone rule, asymmetric
  per verdict type -- BUY only fails on a >=5% fall, SELL only fails
  on a >=5% rise, HOLD fails on a >=5% move in either direction
- Add run_due_evaluations(): loads verdict_outcomes rows with
  evaluated_at IS NULL, filters to those past
  verdict_date + evaluation_horizon_days, fetches each ticker's
  current price via fetch_stock_price (period=1mo, offloaded via
  asyncio.to_thread), and commits price_at_evaluation /
  price_change_pct / directional_correct / evaluated_at per row
- Each row is scored and committed independently -- a bad ticker or a
  failed commit on one row never aborts the rest of the batch, and
  the function itself never raises
- Add full unit coverage: all three verdict types x dead-zone
  boundaries, price-change-pct rounding and zero-division guard, and
  the full run_due_evaluations batch behaviour (due filtering,
  boundary inclusivity, multi-row independence, price-fetch failure,
  and DB-error paths)

Closes #89"
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
git commit -m "style: apply black/isort formatting to T-089 files"
```

### Step 7 — Push and open the PR

```bash
git push -u origin feat/accuracy-tracker-evaluate
```

**Base branch:** `main`
**Compare branch:** `feat/accuracy-tracker-evaluate`

## Pull Request

**PR title:**

```
feat(accuracy): score verdict correctness with a 5% dead-zone rule
```

**PR description:**

```markdown
## Summary
Implements `run_due_evaluations()`, the read-back half of the Verdict
Accuracy Tracker T-088 started. Loads every `verdict_outcomes` row past
its `evaluation_horizon_days`, fetches the current price via the
existing `fetch_stock_price` tool, and scores `directional_correct`
using a +-5% dead-zone rule that is asymmetric per verdict type: BUY
only fails on a meaningful fall, SELL only fails on a meaningful rise,
HOLD fails on a meaningful move in either direction. Scoring only --
scheduling this to run periodically is a separate task.

## Changes
- `DEAD_ZONE_PCT` + `score_directional_correctness(verdict,
  price_change_pct)` in `backend/services/accuracy_tracker.py`
- `_compute_price_change_pct` (rounds to the column's 4-dp precision;
  guards divide-by-zero)
- `_fetch_current_price_sync` -- blocking `fetch_stock_price` call
  (period="1mo"), run via `asyncio.to_thread`
- `EvaluationBatchResult` + `run_due_evaluations(session, now=None)`
  -- per-row independent scoring and commit; never raises
- Full unit test coverage for the scoring rule (all three verdict
  types, exact dead-zone boundaries) and the batch job (due filtering,
  boundary inclusivity, multi-row independence, price-fetch failure,
  DB-error paths)

## Testing
- `ENVIRONMENT=test python -m pytest backend/tests/unit -v` -- all
  green, including the new test classes in `test_accuracy_tracker.py`
- Manual smoke test: back-dated a local `verdict_outcomes` row past its
  horizon, ran `run_due_evaluations` against a local Postgres, confirmed
  all four evaluation columns were filled in correctly
- `black --check backend/`, `isort --check-only backend/`,
  `flake8 backend/`, `mypy backend/` all pass

## LangSmith Trace
N/A -- no LLM-facing code; this is a deterministic price-comparison
and scoring job.

## Screenshots
N/A -- no UI change.

## Related Issues
Closes #89
```

## Testing

Backend (`ENVIRONMENT=test python -m pytest backend/tests/unit -v`):

New/extended coverage in `test_accuracy_tracker.py`:

- `TestScoreDirectionalCorrectnessBuy` / `...Sell` / `...Hold` — the
  exact dead-zone boundary for each verdict type: a move of precisely
  +-5% (wrong for the relevant direction), a move just inside the zone
  (correct), flat (correct), and a large move in the "safe" direction
  for BUY/SELL (always correct, however large).
- `TestScoreDirectionalCorrectnessUnrecognisedVerdict` — an
  unrecognised verdict string is scored with the HOLD rule rather than
  raising.
- `TestComputePriceChangePct` — rise, fall, flat, a case that requires
  rounding to 4 decimal places, and the `price_at_verdict == 0` guard.
- `TestRunDueEvaluationsNoPendingRows` — an empty pending set returns
  an all-zero `EvaluationBatchResult`.
- `TestRunDueEvaluationsDueFiltering` — a row not yet due is excluded
  entirely (no price fetch, no commit); a row exactly at its horizon
  boundary IS due (inclusive); a row well past its horizon is due; a
  row with a naive (tz-unaware) `verdict_date` is still compared
  correctly instead of raising.
- `TestRunDueEvaluationsHappyPath` — one due row is fetched, scored,
  and committed correctly end-to-end; two due rows (one BUY, one SELL)
  are scored independently with different, verdict-appropriate
  outcomes from the same underlying price moves.
- `TestRunDueEvaluationsPriceFetchFailure` — a `fetch_stock_price`
  error dict, and a response missing `stats.current_price`, both leave
  the row unevaluated and counted in `skipped_count` without touching
  `commit`.
- `TestRunDueEvaluationsDbErrors` — a `commit()` failure on one row
  triggers `rollback()` for that row only and does not stop a
  subsequent row from being scored; an unexpected (non-SQLAlchemy)
  exception during one row's scoring is caught and skipped rather than
  propagating; a failure in the initial pending-rows query itself
  returns an all-zero result rather than raising.
- `TestRunDueEvaluationsDefaultNow` — omitting the `now` argument
  correctly defaults to the current UTC time.

No existing test file changes beyond `test_accuracy_tracker.py` itself
-- T-089 adds no new call sites into `run_analysis_pipeline` or any
other already-tested module, so `test_analysis_service.py` and every
other existing suite are unaffected.

All tests run fully offline against mocked `AsyncSession` objects and a
mocked `fetch_stock_price` tool -- no real database connection and no
real yFinance/network access is needed to pass CI, matching the
pattern already established by `test_state_persistence.py` (T-033) and
`test_accuracy_tracker.py`'s own T-088 tests.

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

N/A — no agent, prompt, or LLM-facing code touched; `run_due_evaluations`
only reads already-persisted `verdict_outcomes` rows and a live stock
price.

## Related Issues

Closes #89 (adjust to your actual issue number if different).