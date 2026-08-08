# T-088 — `accuracy_tracker` service — recording

**Phase:** 8 — Verdict Accuracy Tracker
**Week:** 20
**Branch:** `feat/accuracy-tracker-record`
**Type:** Feature
**Priority:** 🔴 Critical
**Est. hours:** 4

## Summary

T-087 gave Phase 8 a place to store verdict outcomes; T-088 is the
first thing that actually writes to it. `record_pending_evaluations()`
is called from `run_analysis_pipeline` immediately after a LangGraph
run reaches `status == "completed"`, and inserts one `verdict_outcomes`
row per analysis: the verdict, the conviction score, the price at the
moment the verdict was made, and — the acceptance criterion this task
is really about — an `evaluation_horizon_days` derived from the
Portfolio Manager's `time_horizon` label.

The horizon mapping is deliberately simple: **90 days by default, 365
days only for a BUY verdict backed by a high margin of safety.**
`_determine_time_horizon` (in `backend/agents/portfolio_manager.py`)
produces four different free-text labels ("quarterly review (3
months)", "3-6 months (technically driven...)", "12 months", and "3-5
years (high margin of safety supports a long hold)"), but the accuracy
tracker only needs to answer one question — "did this call look right
after roughly one review cycle?" — so every label collapses to 90 days
except the one that explicitly represents a genuine multi-year
conviction call.

This task is recording only. Nothing yet reads back a
`verdict_outcomes` row and fills in `price_at_evaluation` /
`price_change_pct` / `directional_correct` / `evaluated_at` — that is
a later Phase 8 task, and those four columns are exactly why T-087 left
them nullable.

## Acceptance criteria (from task spec)

- [x] Row inserted into `verdict_outcomes` on every completed analysis
- [x] Horizon matches `decision.time_horizon` mapping

## Design decisions

- **Where it hooks in.** `run_analysis_pipeline` (backend/services/analysis.py)
  is the natural call site: it already awaits the graph's final state
  on the main event loop (not inside a LangGraph worker-thread node),
  so calling into the accuracy tracker here needs none of
  `state_persistence.py`'s "dedicated engine per call" workaround for
  cross-event-loop asyncpg connections — it can safely reuse the
  shared `backend.db.session.AsyncSessionLocal`, exactly like the
  existing `mark_failed` call in the same function's exception handler
  already does.
- **`price_at_verdict` comes from the Technical Analyst's own output**
  (`state["technical"]["current_price"]`), not a fresh yFinance call —
  the price used to *score* a verdict should be the exact price the
  committee actually saw when it made the call, not a slightly later
  live quote that could itself have moved.
- **The horizon mapping reads `time_horizon` as a string**, not
  `valuation.margin_of_safety` directly. `InvestmentDecision` (the
  Portfolio Manager's Pydantic output, persisted into
  `state["decision"]`) does not carry `margin_of_safety` as its own
  field — that value only ever surfaces baked into the `time_horizon`
  label via `_determine_time_horizon`'s `"... (high margin of safety
  supports a long hold)"` branch. Matching on that exact phrase
  (case-insensitively) is a direct, literal implementation of "derived
  from the decision's time_horizon", and needs no new field threaded
  through the Portfolio Manager or a second read of the Valuation
  Agent's raw output.
- **Idempotent by construction, not by a pre-check.** T-087's
  `uq_verdict_outcomes_analysis_horizon` unique constraint means a
  second call for the same `(analysis_id, evaluation_horizon_days)`
  fails at `commit()` with an `IntegrityError` rather than silently
  duplicating a row; `record_pending_evaluations` catches
  `SQLAlchemyError` around the insert, rolls back, logs it at `info`
  level (this is an expected, harmless case — not a real error), and
  returns `None`. No `SELECT ... WHERE analysis_id = ...` round trip is
  needed first.
- **Never raises.** Every missing/malformed input (no decision, an
  unrecognised verdict string, no ticker, no `technical.current_price`,
  a non-numeric conviction score, an unparsable `job_id`) is logged as
  a warning and turned into a `None` return, matching the project-wide
  "agent/node functions must never raise" rule. The pipeline wiring
  (`_record_pending_evaluations_safely`) adds a second layer of the
  same guarantee — a bug inside the accuracy tracker itself must never
  turn an otherwise-successful analysis into `status='failed'`.
- **`completed_at` parsing falls back to "now".** `state["completed_at"]`
  is always set by `portfolio_manager_node`/`report_generator_node`/
  `pdf_export_node` on the real happy path, but a missing or malformed
  timestamp gets a current-UTC-time fallback rather than blocking the
  insert — an accuracy-tracking row with a `verdict_date` off by a few
  seconds is far more useful than no row at all.

## Files changed / created

### Backend — service

- **`backend/services/accuracy_tracker.py`** (**CREATE**) —
  `DEFAULT_EVALUATION_HORIZON_DAYS` (90),
  `HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS` (365),
  `derive_evaluation_horizon_days(verdict, time_horizon)`,
  `record_pending_evaluations(session, job_id, state)`.
- **`backend/services/analysis.py`** (**MODIFY**) — `run_analysis_pipeline`
  now captures `_invoke_graph_sync`'s return value as `final_state` and,
  when `final_state["status"] == "completed"`, calls a new private
  helper `_record_pending_evaluations_safely(job_id, final_state)`.
  That helper lazily imports `AsyncSessionLocal` and
  `record_pending_evaluations` (same lazy-import pattern the function
  already uses for `StatePersistenceService`) and swallows any
  exception. Module docstring's item 4 updated to mention the new
  T-088 call.

### Backend — tests

- **`backend/tests/unit/test_accuracy_tracker.py`** (**CREATE**) —
  full coverage of `derive_evaluation_horizon_days` and
  `record_pending_evaluations` (see "Testing" below).
- **`backend/tests/unit/test_analysis_service.py`** (**MODIFY**) —
  `TestRunAnalysisPipelineSuccess`'s two existing tests now also patch
  `backend.services.accuracy_tracker.record_pending_evaluations` (it
  would otherwise run for real, harmlessly, against `{"status":
  "completed"}` with no `decision` key — but pinning it down with an
  explicit mock keeps the test from depending on that early-exit
  behaviour as an implementation detail). New
  `TestRunAnalysisPipelineAccuracyTrackerWiring` class added with three
  tests: called on `status == "completed"`, not called otherwise, and
  an accuracy-tracker exception never reaches
  `StatePersistenceService.mark_failed`.

### Docs

- **`docs/week-20/T-088-accuracy-tracker-record.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/accuracy-tracker-record

git branch
# → * feat/accuracy-tracker-record
```

### Step 2 — Create the accuracy tracker service

Create `backend/services/accuracy_tracker.py` with
`derive_evaluation_horizon_days` and `record_pending_evaluations` as
described above.

### Step 3 — Wire it into `run_analysis_pipeline`

Edit `backend/services/analysis.py`:

- Capture the return value of `_invoke_graph_sync` as `final_state`.
- Add the private `_record_pending_evaluations_safely` helper just
  above `run_analysis_pipeline`.
- Call it inside the existing `try` block, gated on
  `final_state.get("status") == "completed"`.

### Step 4 — Add the tests

Create `backend/tests/unit/test_accuracy_tracker.py`. Update
`backend/tests/unit/test_analysis_service.py`'s
`TestRunAnalysisPipelineSuccess` class and add
`TestRunAnalysisPipelineAccuracyTrackerWiring`.

### Step 5 — Run the full verification gate locally

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

### Step 6 — Manual smoke test against a local Postgres (optional)

Confirms the acceptance criterion end-to-end, beyond the mocked unit
tests:

```bash
# Trigger one real analysis against your local stack, then:
psql "$DATABASE_URL" -c "SELECT ticker, verdict, conviction_score, \
  price_at_verdict, evaluation_horizon_days FROM verdict_outcomes \
  ORDER BY verdict_date DESC LIMIT 1;"
```

### Step 7 — Commit (two-commit pattern)

```bash
git add backend/services/accuracy_tracker.py
git add backend/services/analysis.py
git add backend/tests/unit/test_accuracy_tracker.py
git add backend/tests/unit/test_analysis_service.py
git add docs/week-20/T-088-accuracy-tracker-record.md

git commit -m "feat(services): record verdict outcomes pending future evaluation

- Add backend/services/accuracy_tracker.py:
  derive_evaluation_horizon_days() (90d default, 365d for BUY +
  high margin of safety) and record_pending_evaluations()
- Wire record_pending_evaluations() into run_analysis_pipeline via a
  new _record_pending_evaluations_safely() helper, called once the
  graph's final state reports status='completed'
- price_at_verdict is read from technical.current_price -- the exact
  price the committee saw, not a fresh live quote
- Insert failures (including the expected duplicate-insert case from
  T-087's uq_verdict_outcomes_analysis_horizon constraint) are caught,
  rolled back, logged, and never propagate -- accuracy tracking is a
  downstream enrichment, not a pipeline correctness requirement
- Add full unit coverage in test_accuracy_tracker.py; update
  test_analysis_service.py's success-path tests and add a dedicated
  wiring test class

Closes #88"
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
git commit -m "style: apply black/isort formatting to T-088 files"
```

### Step 8 — Push and open the PR

```bash
git push -u origin feat/accuracy-tracker-record
```

**Base branch:** `main`
**Compare branch:** `feat/accuracy-tracker-record`

## Pull Request

**PR title:**

```
feat(accuracy): record each verdict for later outcome evaluation
```

**PR description:**

```markdown
## Summary
Implements `record_pending_evaluations()`, called from
`run_analysis_pipeline` right after a LangGraph run completes. Inserts
one `verdict_outcomes` row (T-087 schema) per analysis with the
verdict, conviction score, and price at verdict time, plus an
`evaluation_horizon_days` derived from the decision's `time_horizon`
label: 90 days by default, 365 days only for a BUY backed by a high
margin of safety. This is the write side only -- reading these rows
back and filling in the outcome columns is a later Phase 8 task.

## Changes
- New `backend/services/accuracy_tracker.py`:
  `derive_evaluation_horizon_days(verdict, time_horizon)` and
  `record_pending_evaluations(session, job_id, state)`
- `run_analysis_pipeline` (`backend/services/analysis.py`) now calls
  the tracker via a new `_record_pending_evaluations_safely` helper
  once the graph's final state reports `status='completed'`
- `price_at_verdict` sourced from `technical.current_price` (no extra
  live price fetch)
- Insert failures -- including duplicate inserts caught by T-087's
  `uq_verdict_outcomes_analysis_horizon` constraint -- are rolled back,
  logged, and never propagate
- New `test_accuracy_tracker.py`; updated
  `test_analysis_service.py`'s success-path tests + new wiring test
  class

## Testing
- `ENVIRONMENT=test python -m pytest backend/tests/unit -v` -- all
  green, including the new `test_accuracy_tracker.py` and the updated/
  new tests in `test_analysis_service.py`
- Manual smoke test: one real analysis run against a local Postgres,
  confirmed a matching `verdict_outcomes` row appears with the correct
  horizon for both a plain BUY and a high-margin-of-safety BUY
- `black --check backend/`, `isort --check-only backend/`,
  `flake8 backend/`, `mypy backend/` all pass

## LangSmith Trace
N/A -- no new LLM-facing prompt content; this is deterministic
service-layer code reading an already-produced decision.

## Screenshots
N/A -- no UI change.

## Related Issues
Closes #88
```

## Testing

Backend (`ENVIRONMENT=test python -m pytest backend/tests/unit -v`):

New file `test_accuracy_tracker.py`:

- `TestDeriveEvaluationHorizonDays` — BUY + high margin of safety
  phrase → 365 (including a case-insensitivity check); BUY without the
  phrase → 90; the "technically driven" BUY branch → 90; HOLD → 90;
  SELL → 90; SELL that happens to contain the phrase → still 90 (the
  365-day horizon is BUY-only by spec); empty `time_horizon` string
  does not raise.
- `TestRecordPendingEvaluationsHappyPath` — a `VerdictOutcome` is
  added and its fields (`analysis_id`, `ticker`, `verdict`,
  `conviction_score`, `price_at_verdict`) match the input state;
  `session.commit()`/`session.refresh()` are awaited and `rollback()`
  is not; the default 90-day horizon on a plain BUY vs. the 365-day
  horizon on a high-margin-of-safety BUY; `verdict_date` correctly
  parsed from `completed_at`.
- `TestRecordPendingEvaluationsMissingData` — missing/empty decision,
  unrecognised verdict, missing conviction_score, missing ticker,
  missing/empty `technical`/`current_price`, non-numeric
  conviction_score/current_price, an invalid (non-UUID) `job_id` — all
  return `None` and never call `session.add`. Unparsable or missing
  `completed_at` falls back to the current UTC time rather than
  raising or blocking the insert.
- `TestRecordPendingEvaluationsDbErrors` — an `IntegrityError` on
  `commit()` (the expected duplicate-insert case) triggers
  `rollback()` and returns `None`; the call never raises.

Modified `test_analysis_service.py`:

- `TestRunAnalysisPipelineSuccess`'s two tests now patch
  `backend.services.accuracy_tracker.record_pending_evaluations`
  directly rather than relying on it harmlessly no-op'ing against a
  `decision`-less mock state.
- New `TestRunAnalysisPipelineAccuracyTrackerWiring` —
  `record_pending_evaluations` is awaited with the correct `job_id`/
  `state` kwargs when the final state's `status` is `"completed"`; it
  is *not* awaited when `status` is anything else; and when it raises,
  `StatePersistenceService.mark_failed` is still never called (the
  accuracy tracker's failure is not reported as a pipeline failure).

No other existing test file changes. `TestRunAnalysisPipelineFailure`'s
two tests are untouched -- `_invoke_graph_sync`'s `side_effect` raises
before the code ever reaches the new `status == "completed"` check, so
neither test needed a `record_pending_evaluations` mock.

All tests run fully offline against mocked `AsyncSession`/
`AsyncSessionLocal` objects -- no real database connection is needed to
pass CI, matching the pattern already established by
`test_state_persistence.py` (T-033) and `test_analysis_service.py`
(T-047/T-048).

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

N/A — no agent, prompt, or LLM-facing code touched; `record_pending_evaluations`
only reads an already-produced `InvestmentDecision.model_dump()` dict.

## Related Issues

Closes #88 (adjust to your actual issue number if different).