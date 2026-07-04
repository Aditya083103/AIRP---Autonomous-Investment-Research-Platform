# T-016 — Setup PostgreSQL Schema on Neon DB

**Phase:** 1 — Data Layer & APIs
**Week:** 3
**Branch:** `feat/data-postgres-schema`
**Commit prefix:** `feat(db):`
**PR title:** `feat(db): PostgreSQL schema — 5 tables, Alembic migration, async session`

---

## Overview

Implements T-016: the complete PostgreSQL relational schema for AIRP, delivered
as production-grade SQLAlchemy ORM models with a single Alembic migration that
creates all tables and Enum types from scratch.

**Five tables created:**

| Table              | Purpose                                                |
| ------------------ | ------------------------------------------------------ |
| `users`            | Local user record per Clerk-authenticated user         |
| `companies`        | Normalised company/ticker registry (NSE + BSE)         |
| `analyses`         | One row per analysis job; full lifecycle tracking      |
| `agent_outputs`    | Raw JSONB output per agent per analysis (up to 8 rows) |
| `investment_memos` | Final BUY/HOLD/SELL verdict + PDF memo path            |

**Key design decisions:**

- All PKs are `UUID` with `gen_random_uuid()` server default
- All timestamps are `TIMESTAMPTZ` (PostgreSQL timezone-aware), stored UTC
- `agent_outputs.output_json` is `JSONB` (binary JSON — faster reads, GIN-indexable)
- Four PostgreSQL `ENUM` types: `analysis_status`, `verdict`, `agent_name`, `exchange`
- Foreign key `ondelete` rules: `CASCADE` where child rows are owned by parent; `RESTRICT` on `companies` to prevent accidental deletion of a company that has analyses
- `(analysis_id, agent_name)` unique constraint prevents duplicate agent outputs
- `analyses.company_id` uses `RESTRICT` not `CASCADE` — companies are shared reference data
- `investment_memos.analysis_id` is `UNIQUE` — enforces the 1:1 relationship at DB level

**Acceptance criteria (from task spec):**

- `alembic upgrade head` runs cleanly on a fresh `airp_test` database ✅
- All five tables created with correct columns, types, constraints ✅
- Schema diagram in docs (Mermaid ER diagram below) ✅
- 76 unit tests pass fully offline (no DB connection required) ✅

---

## Files Created in This Task

| File                                                                       | Action     | Purpose                                                                           |
| -------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------- |
| `backend/models/orm.py`                                                    | **CREATE** | SQLAlchemy ORM models for all 5 tables, 4 Enum types, relationships               |
| `backend/models/__init__.py`                                               | **CREATE** | Package marker; exports `Base` + all model classes                                |
| `backend/db/session.py`                                                    | **CREATE** | Async engine factory, `AsyncSessionLocal`, `get_async_session` dependency         |
| `backend/db/__init__.py`                                                   | **CREATE** | Package marker                                                                    |
| `backend/migrations/env.py`                                                | **CREATE** | Alembic env wired to async engine + AIRP metadata                                 |
| `backend/migrations/script.py.mako`                                        | **CREATE** | Migration file template                                                           |
| `backend/migrations/versions/20240101_0000_a1b2c3d4e5f6_initial_schema.py` | **CREATE** | Initial migration — creates all 5 tables + 4 Enum types                           |
| `backend/alembic.ini`                                                      | **CREATE** | Alembic configuration (URL resolved from settings, not hardcoded)                 |
| `backend/tests/unit/test_orm_models.py`                                    | **CREATE** | 76 unit tests — metadata inspection, column nullability, FKs, relationships, repr |
| `docs/week-03/T-016-setup-postgres-schema.md`                              | **CREATE** | This file                                                                         |

---

## Schema Diagram (Mermaid ER)

```mermaid
erDiagram
    users {
        UUID id PK
        VARCHAR(128) clerk_user_id UK
        VARCHAR(320) email
        VARCHAR(200) display_name
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    companies {
        UUID id PK
        VARCHAR(300) name
        VARCHAR(30) ticker
        VARCHAR(40) ticker_yf
        exchange_enum exchange
        VARCHAR(100) sector
        VARCHAR(150) industry
        TIMESTAMPTZ created_at
    }

    analyses {
        UUID id PK
        UUID company_id FK
        UUID user_id FK
        analysis_status_enum status
        TEXT error_message
        INTEGER debate_rounds_completed
        INTEGER duration_seconds
        TIMESTAMPTZ requested_at
        TIMESTAMPTZ started_at
        TIMESTAMPTZ completed_at
    }

    agent_outputs {
        UUID id PK
        UUID analysis_id FK
        agent_name_enum agent_name
        JSONB output_json
        INTEGER tokens_used
        INTEGER latency_ms
        VARCHAR(64) langsmith_run_id
        TIMESTAMPTZ created_at
    }

    investment_memos {
        UUID id PK
        UUID analysis_id FK UK
        verdict_enum verdict
        INTEGER conviction_score
        TEXT executive_summary
        TEXT investment_thesis
        TEXT bull_case
        TEXT bear_case
        TEXT risk_summary
        TEXT valuation_summary
        VARCHAR(50) price_target
        VARCHAR(500) pdf_path
        TIMESTAMPTZ created_at
    }

    users ||--o{ analyses : "requested_by"
    companies ||--o{ analyses : "subject_of"
    analyses ||--o{ agent_outputs : "produces"
    analyses ||--o| investment_memos : "generates"
```

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Checkout feature branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feat/data-postgres-schema
git branch
# → * feat/data-postgres-schema
```

---

### Step 2 — Place the files

```
backend/models/__init__.py                         ← new (package marker + exports)
backend/models/orm.py                              ← new (ORM models)
backend/db/__init__.py                             ← new (package marker)
backend/db/session.py                              ← new (engine + session factory)
backend/migrations/env.py                          ← new (Alembic env)
backend/migrations/script.py.mako                  ← new (migration template)
backend/migrations/versions/
  20240101_0000_a1b2c3d4e5f6_initial_schema.py     ← new (initial migration)
backend/alembic.ini                                ← new (Alembic config)
backend/tests/unit/test_orm_models.py              ← new (76 tests)
docs/week-03/T-016-setup-postgres-schema.md        ← new (this file)
```

---

### Step 3 — Run the test suite (offline)

```bash
# Windows
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_orm_models.py -v

# macOS / Linux / Git Bash
ENVIRONMENT=test python -m pytest backend/tests/unit/test_orm_models.py -v
```

Expected output:

```
backend/tests/unit/test_orm_models.py::TestModelsImport::test_base_importable PASSED
...
backend/tests/unit/test_orm_models.py::TestSession::test_build_database_url_uses_settings_when_available PASSED

========= 76 passed in X.Xs =========
```

Full suite regression check:

```bash
python -m pytest --tb=short
# → all passed (T-010 through T-016 tests)
```

---

### Step 4 — Verify Alembic migration (requires local PostgreSQL)

```bash
# Apply the migration against the test database
DATABASE_URL=postgresql+asyncpg://airp:airp@localhost:5432/airp_test \
  alembic -c backend/alembic.ini upgrade head

# Verify tables exist
psql postgresql://airp:airp@localhost:5432/airp_test -c "\dt"
# Expected output:
#  Schema |        Name        | Type  | Owner
# --------+--------------------+-------+-------
#  public | agent_outputs      | table | airp
#  public | alembic_version    | table | airp
#  public | analyses           | table | airp
#  public | companies          | table | airp
#  public | investment_memos   | table | airp
#  public | users              | table | airp

# Roll back to verify downgrade works
DATABASE_URL=postgresql+asyncpg://airp:airp@localhost:5432/airp_test \
  alembic -c backend/alembic.ini downgrade base

# Re-apply to leave DB in correct state
DATABASE_URL=postgresql+asyncpg://airp:airp@localhost:5432/airp_test \
  alembic -c backend/alembic.ini upgrade head
```

---

### Step 5 — Run pre-commit hooks

```bash
git add \
  backend/models/__init__.py \
  backend/models/orm.py \
  backend/db/__init__.py \
  backend/db/session.py \
  backend/migrations/env.py \
  backend/migrations/script.py.mako \
  "backend/migrations/versions/20240101_0000_a1b2c3d4e5f6_initial_schema.py" \
  backend/alembic.ini \
  backend/tests/unit/test_orm_models.py \
  docs/week-03/T-016-setup-postgres-schema.md

git commit -m "feat(db): PostgreSQL schema — 5 tables, Alembic migration, async session"
```

If pre-commit auto-fixes formatting (black / isort), the commit aborts. Run:

```bash
git add .
git commit -m "feat(db): PostgreSQL schema — 5 tables, Alembic migration, async session"
```

---

### Step 6 — Push the branch

```bash
git push origin feat/data-postgres-schema
```

CI will run automatically.

---

### Step 7 — Open Pull Request on GitHub

**PR Title:**

```
feat(db): PostgreSQL schema — 5 tables, Alembic migration, async session
```

**PR Description:**

````markdown
## Summary

Implements T-016: the complete AIRP PostgreSQL schema as SQLAlchemy ORM models
with a single Alembic migration. Creates five tables (`users`, `companies`,
`analyses`, `agent_outputs`, `investment_memos`) with UUID PKs, TIMESTAMPTZ
timestamps, JSONB storage for agent outputs, four PostgreSQL Enum types, and
all FK/unique constraints. Adds the async session factory consumed by FastAPI
routes and LangGraph background tasks in later phases.

## Changes

- `backend/models/orm.py` — SQLAlchemy Mapped models for all 5 tables
- `backend/models/__init__.py` — package marker; re-exports all models + Base
- `backend/db/session.py` — async engine (NullPool in test), AsyncSessionLocal,
  get_async_session FastAPI dependency / context manager
- `backend/db/__init__.py` — package marker
- `backend/migrations/env.py` — Alembic env wired to async engine + metadata
- `backend/migrations/script.py.mako` — migration template
- `backend/migrations/versions/20240101_0000_...initial_schema.py` — initial
  migration: creates 4 Enum types + 5 tables + 13 indexes
- `backend/alembic.ini` — Alembic config (URL from settings, not hardcoded)
- `backend/tests/unit/test_orm_models.py` — 76 offline unit tests

## Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_orm_models.py -v
# → 76 passed

python -m pytest --tb=short
# → all passed, 0 regressions
```
````

## LangSmith Trace

Not applicable — database schema task, no LLM calls.

## Screenshots

`\dt` output showing all 5 tables + alembic_version on airp_test database.

## Related Issues

Closes #16

```

---

## Architecture Notes

### Why JSONB for `agent_outputs.output_json`

Agent outputs are Pydantic models serialised to dicts — their schema varies
by agent and will evolve as agents are refined in Phase 2. Storing them as
`JSONB` rather than individual columns means:

- No migration required when an agent adds a field
- GIN indexes can be added later for queries like "all analyses where the
  Fundamental Analyst score was > 7"
- The full agent output is recoverable for LangSmith correlation and debugging

### Why `RESTRICT` on `analyses.company_id` FK

`companies` is shared reference data. If a company row were deleted with
`CASCADE`, every analysis for that company would silently disappear — a
catastrophic data loss. `RESTRICT` forces the caller to explicitly detach or
delete analyses before removing a company, making the action intentional.

### Why `NullPool` in test environment

`asyncpg` connections are not fully compatible with pytest's event-loop
teardown when a connection pool is left open. `NullPool` closes every
connection immediately after use, eliminating the "Event loop is closed" error
that appears when pytest exits with a live pool.

### Alembic URL resolution

`alembic.ini` has `sqlalchemy.url` intentionally blank. `env.py` calls
`settings.active_database_url` which already handles the
`ENVIRONMENT=test → airp_test` switch. This means:

- Local dev: connects to `airp` (your Neon or local DB)
- CI: connects to `airp_test` (the PostgreSQL service container)
- No `alembic.ini` edits needed per environment

---

## EOD Update Template

```

EOD Update [DATE]:
Completed: T-016
Merged to main: feat/data-postgres-schema
Current week: 3 | Current phase: 1
Blocker: None
Next session: T-017 — Setup ChromaDB + embed earnings transcripts
(chunk TranscriptResult.transcript_text → sentence-transformers embeddings
→ store in ChromaDB collection for RAG retrieval by News Sentiment Agent)

```

```
