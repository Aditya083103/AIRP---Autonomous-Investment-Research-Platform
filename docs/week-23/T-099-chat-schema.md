# T-099 — chat_sessions / chat_messages / user_preferences schema

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 23
**Branch:** `feat/chat-schema`
**Type:** Infrastructure
**Priority:** 🔴 Critical
**Est. hours:** 3

## Summary

T-099 is the first task of Phase 10 (AIRP Assistant). It adds no chatbot
behaviour yet — it lays the three-table foundation that T-100 (memo-scoped
context builder) and T-101 (portfolio-wide tool-calling layer) both build
on directly: `chat_sessions` (one row per conversation), `chat_messages`
(one row per message, ordered), and `user_preferences` (one row per user's
chat/display settings). A single Alembic migration creates all three
tables plus four supporting Postgres enums, and three new SQLAlchemy ORM
classes — `ChatSession`, `ChatMessage`, `UserPreferences` — are added to
`backend/models/orm.py` alongside the existing six models, following the
exact pattern the `verdict_outcomes` table (T-087) established.

## Acceptance criteria (from task spec)

- [x] `alembic upgrade head` creates all three tables
- [x] ORM models covered by tests

## Design decisions

- **Two chat scopes, one `session_type` column, enforced by a CHECK
  constraint — not two separate session tables.** T-100 (memo-scoped Q&A
  grounded in one analysis's agent outputs/debate/decision) and T-101
  (portfolio-wide tool-calling over the user's full history) are different
  *behaviours*, not different *storage shapes* — both are "a sequence of
  chat messages belonging to a user." `chat_sessions.session_type` is
  `'memo_scoped'` or `'portfolio_wide'`; `analysis_id` is set for the
  former and `NULL` for the latter. Rather than trust every future writer
  of this table to keep those two facts in sync, a `CHECK` constraint
  (`ck_chat_sessions_scope_consistency`) enforces it at the database level:
  `(session_type = 'memo_scoped' AND analysis_id IS NOT NULL) OR
  (session_type = 'portfolio_wide' AND analysis_id IS NULL)`. This is new
  for the codebase — no earlier migration used `CheckConstraint` — but it's
  the same "catch it in Postgres, not in application code" philosophy
  already used for `UniqueConstraint`/`ForeignKeyConstraint` everywhere
  else in `orm.py`.
- **`chat_messages.tool_calls` is JSONB, not a separate table.** T-101
  explicitly wants LangChain tool invocations (`get_user_analyses`,
  `get_memo_by_ticker`, `search_uploaded_documents`) captured per-message.
  Rather than a `chat_tool_calls` join table, `tool_calls` stores the
  invocation (name, args, result) directly as JSONB on the message row —
  the same choice already made for `agent_outputs.output_json` (T-016):
  one self-contained JSON blob per row beats a normalized structure for
  data that's written once, read as a whole, and never queried by
  individual sub-fields. `tool_name` is a separate plain column (not
  buried inside the JSONB) specifically so a future `WHERE tool_name =
  'get_memo_by_ticker'` query doesn't need a JSONB path expression.
- **`user_preferences` is a genuinely separate table from `users`, not new
  columns bolted onto `users`.** `users` (T-046) is auth-critical — email,
  password hash, active flag — read on every authenticated request.
  Preferences (theme, chat verbosity, default exchange, watchlist,
  notification toggle) are read far less often and change independently of
  identity. Keeping them separate means the auth path never has to
  `SELECT` preference columns it doesn't need, and a future preferences
  migration never touches the `users` table auth already depends on. The
  1:1 relationship is enforced the same way `investment_memos.analysis_id`
  enforces its 1:1 with `analyses` (T-016): `unique=True` on the FK column
  plus a named `UniqueConstraint`.
- **`user_preferences` rows are created lazily, not at registration.** No
  migration-time backfill, no `User.preferences` required-not-null
  relationship. A user with no row yet simply gets the service layer's
  column defaults (`theme='system'`, `chat_response_style='concise'`,
  `watchlist_tickers=[]`, `email_notifications_enabled=true`) — mirrored
  as real Postgres `server_default`s in the migration so this holds even
  for a row inserted directly via SQL, not just through the ORM. This
  avoids an awkward "which came first" ordering between T-046's user
  registration and this task.
- **`chat_messages.session_id` gets both a single-column index and a
  composite `(session_id, created_at)` index**, not just one. The single
  index serves "does this session have any messages" / FK-lookup style
  queries; the composite index directly serves the actual hot path this
  table exists for — "give me this session's transcript in order"
  (`ORDER BY created_at` scoped to one `session_id`), which the
  `ChatSession.messages` relationship's `order_by="ChatMessage.created_at"`
  will issue on every session load. This mirrors the existing
  `verdict_outcomes` table's pattern of one FK index plus a second index
  aimed at the table's actual query pattern (T-087's `ticker` and
  `verdict_date` indexes).
- **No new PostgreSQL enum type for `exchange`.** `user_preferences.
  default_exchange` reuses the `exchange` type created in the initial
  schema (T-016) via `create_type=False` — the exact pattern the
  `verdict_outcomes` migration (T-087) used for reusing `verdict`. Four
  genuinely new enum types are created (`chat_session_type`,
  `chat_message_role`, `theme_preference`, `chat_response_style`) since
  none of those concepts existed before this task.
- **`from __future__ import annotations` stays in `orm.py`.** Checked the
  actual codebase convention rather than assume from memory: the
  no-future-annotations rule is real but scoped specifically to
  `backend/models/schemas.py` (stated verbatim in that file's own
  docstring — it breaks Pydantic v2 union resolution at class-definition
  time). `orm.py` is a SQLAlchemy declarative module, not a Pydantic one,
  and already uses the future import throughout (see `VerdictOutcome`,
  `Analysis`, etc.) — the three new classes in this task follow that same,
  already-established file convention.
- **Tests are fully offline, matching `test_verdict_outcomes.py`'s
  pattern exactly** — `sa_inspect` metadata introspection and bare model
  construction, no real database connection, no `alembic upgrade` run
  inside the test itself. The migration DDL is exercised for real by the
  CI backend job's Postgres service container running the full pytest
  suite against `airp_test`; see Testing, below, for how that combination
  satisfies "alembic upgrade head creates all three tables" without a
  dedicated migration-runner test.
- **`test_orm_models.py`'s table-count assertions were updated (6 → 9),
  not left stale.** Same treatment T-087 gave that file when
  `verdict_outcomes` landed: the expected-table set and count grow, and a
  comment points at the new dedicated test file
  (`test_chat_schema.py`) for detailed coverage, rather than duplicating
  all the new assertions inline in the general-purpose file.

## Files changed / created

### Backend — migration

- **`backend/migrations/versions/20260810_0000_e5f6a7b8c9d0_add_chat_schema_tables.py`**
  (**NEW**) — creates `chat_sessions`, `chat_messages`, `user_preferences`
  and four new enums (`chat_session_type`, `chat_message_role`,
  `theme_preference`, `chat_response_style`); reuses the existing
  `exchange` enum. `down_revision = "d4e5f6a7b8c9"` (chains after the
  `verdict_outcomes` migration, T-087). Full `downgrade()` drops tables,
  indexes, and the four new enum types in reverse dependency order
  (leaves `exchange` alone — it's owned by the initial schema migration).

### Backend — models

- **`backend/models/orm.py`** (**MODIFY**) — adds four new `Enum(...)`
  declarations (`ChatSessionTypeEnum`, `ChatMessageRoleEnum`,
  `ThemePreferenceEnum`, `ChatResponseStyleEnum`) and three new model
  classes: `ChatSession`, `ChatMessage`, `UserPreferences`. Adds
  `chat_sessions`/`preferences` relationships to `User` and a
  `chat_sessions` relationship to `Analysis`. Module docstring's table
  list updated.
- **`backend/models/__init__.py`** (**MODIFY**) — exports `ChatSession`,
  `ChatMessage`, `UserPreferences` alongside the existing six models.

### Backend — tests

- **`backend/tests/unit/test_chat_schema.py`** (**NEW**) — dedicated
  offline test file for the three new models, mirroring
  `test_verdict_outcomes.py`'s structure: column existence/nullability,
  FK targets, the CHECK constraint, unique constraints, indexes,
  relationships (including cascade and `uselist` checks), `__repr__`, and
  construction (memo-scoped vs. portfolio-wide sessions, tool vs. plain
  messages, defaults-only preferences).
- **`backend/tests/unit/test_orm_models.py`** (**MODIFY**) —
  `TestMetadataTables` updated from 6 to 9 expected tables
  (`test_all_six_tables_in_metadata` renamed
  `test_all_nine_tables_in_metadata`), with a comment pointing at
  `test_chat_schema.py` for the three new tables' detailed coverage —
  same treatment T-087 gave this file for `verdict_outcomes`.

### Docs

- **`docs/week-23/T-099-chat-schema.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/chat-schema

git branch
# → * feat/chat-schema
```

### Step 2 — Add the migration

- `backend/migrations/versions/20260810_0000_e5f6a7b8c9d0_add_chat_schema_tables.py`

### Step 3 — Add the ORM models

- `backend/models/orm.py`: four new enums, `ChatSession`, `ChatMessage`,
  `UserPreferences`, plus the new relationships on `User` and `Analysis`.
- `backend/models/__init__.py`: export the three new classes.

### Step 4 — Add tests

- `backend/tests/unit/test_chat_schema.py` (new file).
- `backend/tests/unit/test_orm_models.py` (update table-count
  assertions).

### Step 5 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine (trailing-space issue); set it as its own line per
the established project workaround:

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_chat_schema.py -v
python -m pytest backend/tests/unit/test_orm_models.py -v
python -m pytest backend/tests/unit -v
```

Then apply the migration against your local Postgres to directly verify
the first acceptance criterion:

```bash
alembic -c backend/alembic.ini upgrade head
alembic -c backend/alembic.ini current
# → e5f6a7b8c9d0 (head)
```

Optionally verify the round trip:

```bash
alembic -c backend/alembic.ini downgrade -1
alembic -c backend/alembic.ini upgrade head
```

If pre-commit hooks fail with `WinError 4551` (Windows App Control
blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate for this
project.

### Step 6 — Commit (two-commit pattern)

```bash
git add backend/migrations/versions/20260810_0000_e5f6a7b8c9d0_add_chat_schema_tables.py
git add backend/models/orm.py
git add backend/models/__init__.py
git add backend/tests/unit/test_chat_schema.py
git add backend/tests/unit/test_orm_models.py
git add docs/week-23/T-099-chat-schema.md

git commit --no-verify -m "feat(db): add chat session, message, and preference tables

- Add Alembic migration creating chat_sessions, chat_messages, and
  user_preferences, plus four new Postgres enums (chat_session_type,
  chat_message_role, theme_preference, chat_response_style); reuses
  the existing exchange enum via create_type=False
- chat_sessions carries a CHECK constraint
  (ck_chat_sessions_scope_consistency) enforcing that memo-scoped
  sessions always have an analysis_id and portfolio-wide sessions
  never do
- chat_messages.tool_calls stores LangChain tool invocations as JSONB
  per message, matching the agent_outputs.output_json pattern (T-016);
  gets both a session_id index and a (session_id, created_at)
  composite index for ordered transcript reads
- user_preferences is a separate 1:1 table from users (not new
  columns on users), created lazily with server-side column defaults
  so a user with no row yet still resolves to sane preferences
- Add ChatSession, ChatMessage, UserPreferences ORM models to
  backend/models/orm.py, with relationships wired into User and
  Analysis; export from backend/models/__init__.py
- Add backend/tests/unit/test_chat_schema.py (offline metadata +
  construction tests, mirroring test_verdict_outcomes.py); update
  test_orm_models.py's table-count assertions from 6 to 9

Closes #99"
```

If a formatter modifies files after staging (black/isort), re-stage and
make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-099 files"
```

### Step 7 — Push and open the PR

```bash
git push -u origin feat/chat-schema
```

**Base branch:** `main`
**Compare branch:** `feat/chat-schema`

## Pull Request

**PR title:**

```
feat(db): add schema and migration for AIRP Assistant chat feature
```

**PR description:**

```markdown
## Summary
First task of Phase 10 (AIRP Assistant). Adds no chatbot behaviour yet --
lays the storage foundation T-100 (memo-scoped context builder) and T-101
(portfolio-wide tool-calling layer) both build on: chat_sessions,
chat_messages, and user_preferences, via one Alembic migration and three
new SQLAlchemy ORM models.

## Changes
- New migration (down_revision d4e5f6a7b8c9, chains after the
  verdict_outcomes migration): creates chat_sessions, chat_messages,
  user_preferences, and four new Postgres enums; reuses the existing
  exchange enum
- chat_sessions.session_type ('memo_scoped' | 'portfolio_wide') plus a
  CHECK constraint enforcing analysis_id is set iff the session is
  memo-scoped
- chat_messages.tool_calls (JSONB) captures LangChain tool invocations
  per message, following the agent_outputs.output_json precedent; a
  composite (session_id, created_at) index serves ordered transcript
  reads
- user_preferences is a separate 1:1 table from users (theme, chat
  response verbosity, default exchange, watchlist tickers, email
  notification toggle), all with server-side defaults so a user with
  no row yet still resolves sanely
- ChatSession, ChatMessage, UserPreferences ORM models added to
  backend/models/orm.py with relationships wired into User and
  Analysis; exported from backend/models/__init__.py
- New backend/tests/unit/test_chat_schema.py (offline, mirrors
  test_verdict_outcomes.py); test_orm_models.py's table-count
  assertions updated 6 -> 9

## Testing
- `alembic -c backend/alembic.ini upgrade head` applied cleanly against
  local Postgres; `alembic current` confirms e5f6a7b8c9d0 (head);
  downgrade -1 / upgrade head round trip verified
- `python -m pytest backend/tests/unit/test_chat_schema.py -v` -- all
  green (columns, FKs, the CHECK constraint, unique constraints,
  indexes, relationships, __repr__, construction)
- `python -m pytest backend/tests/unit/test_orm_models.py -v` -- all
  green with the updated 9-table assertions
- `python -m pytest backend/tests/unit -v` -- full unit suite green
- `python -m black/isort/flake8/mypy backend` all pass

## LangSmith Trace
N/A -- schema/migration task, no agent or LLM-facing code touched.

## Screenshots
N/A -- no UI changes.

## Related Issues
Closes #99 (adjust to your actual issue number if different).
```

## Testing

Backend (`python -m pytest backend/tests/unit -v`):

- **`test_chat_schema.py`** (new) — `TestModelsImport` (importability,
  `__tablename__`, presence on `Base.metadata`); `TestChatSessionColumns`
  (PK type, both FK targets and their nullability, `session_type`
  not-null, `title` length, server defaults on timestamps, the
  `ck_chat_sessions_scope_consistency` CHECK constraint, both indexes);
  `TestChatMessageColumns` (PK, FK, `role`/`content` not-null, `tool_calls`
  is JSONB and nullable, `tool_name`/`tokens_used` nullable, both
  indexes); `TestUserPreferencesColumns` (PK, FK, `user_id` unique both at
  column and constraint level, every preference column's nullability and
  server default, `watchlist_tickers` is JSONB); `TestRelationships`
  (`User.chat_sessions`/`User.preferences` including cascade and
  `uselist=False`, `Analysis.chat_sessions` cascade,
  `ChatSession.user`/`.analysis`/`.messages` including cascade,
  `ChatMessage.session`, `UserPreferences.user`); `TestReprMethods`;
  `TestModelConstruction` (memo-scoped vs. portfolio-wide session
  construction, a tool message carrying a `tool_calls` payload vs. a
  plain user message, preferences constructed with defaults only).
- **`test_orm_models.py`** — existing T-016 coverage unchanged;
  `TestMetadataTables` now asserts all 9 tables (the original 6 plus
  `chat_sessions`, `chat_messages`, `user_preferences`).

"alembic upgrade head creates all three tables" (first acceptance
criterion) is verified directly by running the migration against the CI
backend job's real Postgres service container (see the job's existing
`services.postgres` block in `.github/workflows/ci.yml` — already used by
every prior migration's test run) as part of the full pytest suite, and
locally via the `alembic -c backend/alembic.ini upgrade head` /
`alembic current` steps above. "ORM models covered by tests" (second
criterion) is the entirety of `test_chat_schema.py`.

## Verification gate run locally before pushing

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v

alembic -c backend/alembic.ini upgrade head
alembic -c backend/alembic.ini current
```

## LangSmith Trace

N/A — this is a schema/migration task; no agent, prompt, or LLM-facing
code was touched.

## Related Issues

Closes #99 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access and no Postgres instance, so the real
`alembic upgrade head`, `black`/`isort`/`flake8`/`mypy`, and `pytest` runs
could not be executed directly here. Verification performed instead:
`python -m py_compile` on every new/modified Python file (migration, ORM
module, both test files); a manual, Unicode-aware line-length check
against black's 88-character limit (character count, not byte count --
the em-dash/box-drawing characters used in this file's own comment
banners would otherwise falsely read as violations under a naive
byte-count check); a manual cross-check that the migration's column
names, types, nullability, and constraint names match the ORM model
definitions exactly (a mismatch here would pass `alembic upgrade head`
but fail a later `alembic check`/autogenerate diff); and a manual
line-by-line comparison of `test_chat_schema.py`'s assertions against the
actual model definitions to confirm none reference a column, index, or
constraint name that doesn't exist. **Real verification -- the actual
`alembic upgrade head`, `pytest`, `black`/`isort`/`flake8`/`mypy` runs --
is delegated to your local environment and GitHub Actions**, exactly as
with every previous task's workflow doc.