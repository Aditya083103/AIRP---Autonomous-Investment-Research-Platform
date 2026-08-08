# T-087 — `verdict_outcomes` table + Alembic migration

**Phase:** 8 — Verdict Accuracy Tracker
**Week:** 20
**Branch:** `feat/accuracy-tracker-schema`
**Type:** Infrastructure
**Priority:** 🔴 Critical
**Est. hours:** 2

## Summary

Phase 8 kicks off the Verdict Accuracy Tracker — scoring the Portfolio
Manager's past BUY/HOLD/SELL calls against what the stock's price
actually did afterwards. T-087 lays the schema foundation for all of
Phase 8: a new `verdict_outcomes` table (ORM model + Alembic migration)
that records a verdict and its price at the moment it was issued, with
room for a later background job (a future task) to fill in the
evaluation-time columns once `evaluation_horizon_days` has elapsed.

One analysis can be tracked at more than one horizon (e.g. 30 days and
90 days out), so the natural key is `(analysis_id,
evaluation_horizon_days)` — not `analysis_id` alone. That is enforced
with a unique constraint, not just convention.

This task is schema-only. No router, service, or agent code reads or
writes `verdict_outcomes` yet — that lands in later Phase 8 tasks
(T-088+) once the evaluation job and API surface are built on top of
this table.

## Acceptance criteria (from task spec)

- [x] `alembic -c backend/alembic.ini upgrade head` creates `verdict_outcomes`
- [x] Model covered by SQLAlchemy ORM test

## Column spec (from task description)

| Column | Type | Nullable | Notes |
| --- | --- | --- | --- |
| `id` | UUID PK | No | `gen_random_uuid()` server default |
| `analysis_id` | UUID FK → `analyses.id` | No | `ON DELETE CASCADE`, indexed |
| `ticker` | `VARCHAR(40)` | No | yFinance ticker at verdict time, e.g. `TCS.NS` |
| `verdict` | `verdict` enum (reused) | No | `BUY` / `HOLD` / `SELL` |
| `conviction_score` | `INTEGER` | No | 1–10, copied from the memo at verdict time |
| `price_at_verdict` | `NUMERIC(12,4)` | No | Closing price on `verdict_date` |
| `verdict_date` | `TIMESTAMPTZ` | No | When the verdict was issued |
| `evaluation_horizon_days` | `INTEGER` | No | e.g. `30`, `90` |
| `price_at_evaluation` | `NUMERIC(12,4)` | Yes | Filled in by the (future) evaluation job |
| `price_change_pct` | `NUMERIC(8,4)` | Yes | Filled in by the (future) evaluation job |
| `directional_correct` | `BOOLEAN` | Yes | Filled in by the (future) evaluation job |
| `evaluated_at` | `TIMESTAMPTZ` | Yes | Filled in by the (future) evaluation job |

`verdict_outcomes` reuses the existing PostgreSQL `verdict` enum type
created in the initial schema (T-016) rather than defining a second
one — the migration references it with `create_type=False`.

## Files changed / created

### Backend — schema

- **`backend/models/orm.py`** (**MODIFY**) — new `VerdictOutcome` ORM
  class; new `Numeric`/`Boolean` imports; new
  `Analysis.verdict_outcomes` relationship
  (`cascade="all, delete-orphan"`); module docstring updated from
  "five core tables" to "six core tables".
- **`backend/models/__init__.py`** (**MODIFY**) — exports
  `VerdictOutcome` alongside the existing five models.
- **`backend/migrations/versions/20260801_0000_d4e5f6a7b8c9_add_verdict_outcomes_table.py`**
  (**CREATE**) — Alembic migration; `down_revision =
  "c3d4e5f6a7b8"` (chains onto the T-046 self-hosted-auth migration,
  the current head). Creates the table, its three supporting indexes
  (`analysis_id`, `ticker`, `verdict_date`), and the
  `uq_verdict_outcomes_analysis_horizon` unique constraint.
  `downgrade()` drops the indexes then the table; no enum type is
  touched since `verdict` is shared with `investment_memos` and must
  survive this migration's downgrade.

### Backend — tests

- **`backend/tests/unit/test_verdict_outcomes.py`** (**CREATE**) —
  dedicated ORM coverage for the new table (see "Testing" below).
- **`backend/tests/unit/test_orm_models.py`** (**MODIFY**) —
  `TestMetadataTables` updated from five tables to six
  (`test_all_five_tables_in_metadata` → `test_all_six_tables_in_metadata`,
  `len(Base.metadata.tables) == 5` → `== 6`). This is the only change
  to this file; every other test in it is unaffected because none of
  the five original tables' columns, constraints, or relationships
  changed.

### Docs

- **`docs/week-20/T-087-verdict-outcomes-schema.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/accuracy-tracker-schema

git branch
# → * feat/accuracy-tracker-schema
```

### Step 2 — Add the ORM model changes

Edit `backend/models/orm.py`:

- Add `Numeric` and `Boolean` to the `sqlalchemy` import.
- Add the `VerdictOutcome` class (after `InvestmentMemo`).
- Add the `verdict_outcomes: Mapped[list[VerdictOutcome]]` relationship
  on `Analysis`.

Edit `backend/models/__init__.py` to import and export `VerdictOutcome`.

### Step 3 — Generate and fill in the Alembic migration

```bash
set ENVIRONMENT=test
alembic -c backend/alembic.ini revision -m "add verdict_outcomes table"
```

Rename the generated file to
`20260801_0000_d4e5f6a7b8c9_add_verdict_outcomes_table.py` (matching
the repo's `file_template` convention) and fill in `upgrade()` /
`downgrade()` as described above. Confirm the revision chain:

```bash
alembic -c backend/alembic.ini history
# ... c3d4e5f6a7b8 -> d4e5f6a7b8c9 (head), add verdict_outcomes table
```

### Step 4 — Run the migration against a local Postgres

```bash
alembic -c backend/alembic.ini upgrade head
```

Confirm the table exists:

```bash
psql "$DATABASE_URL" -c "\d verdict_outcomes"
```

Confirm downgrade is clean (then re-upgrade before continuing):

```bash
alembic -c backend/alembic.ini downgrade -1
alembic -c backend/alembic.ini upgrade head
```

### Step 5 — Add the tests

Create `backend/tests/unit/test_verdict_outcomes.py` and update the two
assertions in `backend/tests/unit/test_orm_models.py::TestMetadataTables`.

### Step 6 — Run the full verification gate locally

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

### Step 7 — Commit (two-commit pattern)

```bash
git add backend/models/orm.py backend/models/__init__.py
git add backend/migrations/versions/20260801_0000_d4e5f6a7b8c9_add_verdict_outcomes_table.py
git add backend/tests/unit/test_verdict_outcomes.py backend/tests/unit/test_orm_models.py
git add docs/week-20/T-087-verdict-outcomes-schema.md

git commit -m "feat(db): add verdict_outcomes table for accuracy tracking

- Add VerdictOutcome ORM model (analysis_id FK, ticker, verdict,
  conviction_score, price_at_verdict, verdict_date,
  evaluation_horizon_days, price_at_evaluation, price_change_pct,
  directional_correct, evaluated_at)
- Add Alembic migration d4e5f6a7b8c9 (down_revision c3d4e5f6a7b8)
- Reuse the existing verdict enum type; no new PG enum created
- Add uq_verdict_outcomes_analysis_horizon so one analysis can be
  tracked at multiple evaluation horizons
- Add dedicated ORM unit tests; update table-count assertions in
  test_orm_models.py from five tables to six

Closes #87"
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
git commit -m "style: apply black/isort formatting to T-087 files"
```

### Step 8 — Push and open the PR

```bash
git push -u origin feat/accuracy-tracker-schema
```

**Base branch:** `main`
**Compare branch:** `feat/accuracy-tracker-schema`

## Pull Request

**PR title:**

```
feat(db): add schema and migration for verdict outcome tracking
```

**PR description:**

```markdown
## Summary
Adds the `verdict_outcomes` table that Phase 8 (Verdict Accuracy
Tracker) is built on: one row per (analysis, evaluation horizon) pair,
recording the verdict and price at issue time so a later job can score
it against the real price outcome. Schema-only — no router, service,
or agent wiring yet (that's T-088+).

## Changes
- New `VerdictOutcome` SQLAlchemy ORM model in `backend/models/orm.py`,
  exported from `backend/models/__init__.py`
- New `Analysis.verdict_outcomes` relationship
  (`cascade="all, delete-orphan"`)
- New Alembic migration `d4e5f6a7b8c9` (down_revision `c3d4e5f6a7b8`)
  creating `verdict_outcomes` with 3 supporting indexes and a
  `(analysis_id, evaluation_horizon_days)` unique constraint
- Reuses the existing `verdict` PG enum — no new enum type
- New `backend/tests/unit/test_verdict_outcomes.py`
- Updated table-count assertions in `test_orm_models.py`
  (5 tables → 6)

## Testing
- `ENVIRONMENT=test python -m pytest backend/tests/unit -v` — all green,
  including the new `test_verdict_outcomes.py` and the updated
  `test_orm_models.py::TestMetadataTables`
- `alembic -c backend/alembic.ini upgrade head` confirmed locally
  against Postgres 16 — creates `verdict_outcomes` cleanly
- `alembic -c backend/alembic.ini downgrade -1` confirmed clean, then
  re-upgraded
- `black --check backend/`, `isort --check-only backend/`,
  `flake8 backend/`, `mypy backend/` all pass

## LangSmith Trace
N/A — schema-only change, no LLM-facing prompt content.

## Screenshots
N/A — no UI change.

## Related Issues
Closes #87
```

## Testing

Backend (`ENVIRONMENT=test python -m pytest backend/tests/unit -v`):

New file `test_verdict_outcomes.py`:

- `TestModelImport` — importable, correct `__tablename__`, present in
  `Base.metadata`.
- `TestPrimaryKey` — UUID PK with a server default.
- `TestAnalysisForeignKey` — FK target, not-nullable, `ON DELETE
  CASCADE`.
- `TestVerdictTimeColumns` — `ticker`, `verdict`, `conviction_score`,
  `price_at_verdict`, `verdict_date`, `evaluation_horizon_days` are all
  `NOT NULL`; `price_at_verdict` is `Numeric`.
- `TestOutcomeColumns` — `price_at_evaluation`, `price_change_pct`,
  `directional_correct`, `evaluated_at` are all nullable, with the
  correct SQLAlchemy types (`Numeric` / `Numeric` / `Boolean`).
- `TestConstraintsAndIndexes` —
  `uq_verdict_outcomes_analysis_horizon` exists and covers exactly
  `(analysis_id, evaluation_horizon_days)`; `ix_verdict_outcomes_ticker`
  and `ix_verdict_outcomes_verdict_date` exist.
- `TestRelationships` — `Analysis.verdict_outcomes` exists, is a list
  (`uselist is True`), cascades `delete-orphan`;
  `VerdictOutcome.analysis` back-reference exists.
- `TestReprAndConstruction` — `__repr__` includes ticker, verdict, and
  horizon; a `VerdictOutcome` can be constructed with only the
  verdict-time fields (outcome fields default to `None` pre-evaluation).

Modified `test_orm_models.py`:

- `TestMetadataTables.test_all_six_tables_in_metadata` (renamed from
  `test_all_five_tables_in_metadata`) — asserts the six expected table
  names, now including `verdict_outcomes`.
- `TestMetadataTables.test_no_extra_tables` — asserts
  `len(Base.metadata.tables) == 6`.

No other existing test file changes. `test_orm_models.py`'s
`TestUserColumns`, `TestCompanyColumns`, `TestAnalysisColumns`,
`TestAgentOutputColumns`, `TestInvestmentMemoColumns`,
`TestRelationships`, `TestReprMethods`, and `TestSession` classes are
untouched — none of the original five tables' columns or constraints
changed.

All tests in both files run fully offline (metadata inspection and
in-memory model construction only) — no live database connection is
needed to pass CI, matching the pattern already established by
`test_orm_models.py` for T-016. The `alembic upgrade head` acceptance
criterion is verified manually against a local/CI Postgres instance
per Step 4 above; CI's `backend` job does not currently invoke
`alembic` (it runs pytest only), so this is a manual verification step,
not an automated CI gate.

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

N/A — schema-only change; no agent, prompt, or LLM-facing code touched.

## Related Issues

Closes #87 (adjust to your actual issue number if different).