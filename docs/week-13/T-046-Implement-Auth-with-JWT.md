# T-046 -- Implement Auth with JWT

**Phase:** 5 -- FastAPI Backend
**Week:** 13
**Branch:** `feat/api-auth`
**Task status:** Complete

---

## Overview

T-046 implements self-hosted authentication: `POST /auth/register`,
`POST /auth/login`, `GET /auth/me`, bcrypt password hashing, and
self-issued JWT access tokens.

**Acceptance criteria (all must pass):**
- Register -> login -> access protected route works end-to-end
- Invalid token returns 401

---

## Important: a real architecture conflict was found and resolved before writing code

Before touching any code, the existing `User` ORM model, `config.py`,
and `.env.example` were inspected and found to be built entirely around
**Clerk** as the auth provider: `clerk_user_id` was the canonical,
unique identity column, `CLERK_SECRET_KEY`/`CLERK_PUBLISHABLE_KEY`/
`CLERK_JWT_ISSUER` were already wired in `config.py` with comments
explicitly stating Clerk is *"required in Phase 5"*, and there was no
`password_hash` column anywhere.

This directly conflicts with T-046's literal task description: bcrypt-
hashed passwords and self-issued JWTs are a *self-hosted* auth model,
incompatible with a `users` table designed around an external identity
provider owning authentication. Rather than silently picking one
interpretation, this was flagged explicitly and confirmed: **build
self-hosted JWT + bcrypt auth as the task describes, migrating the
`users` table away from Clerk.**

This means T-046's scope is larger than "add three endpoints" -- it
includes a real schema migration (drop `clerk_user_id`, add
`password_hash`, make `email` the unique identity column) and updates
to the existing `test_orm_models.py` assertions that tested the old
Clerk-shaped schema.

**If your project intends to use Clerk after all** (e.g. for the
Phase 6 React frontend, which still has `VITE_CLERK_PUBLISHABLE_KEY`
wired in `.env.example`), this is the moment to reconcile that --
shipping both a self-hosted JWT backend and a Clerk-authenticated
frontend in the same app is two different, non-interoperating auth
systems, not one.

---

## What Was Built

### Schema migration: `users` table, Clerk -> self-hosted

**`backend/models/orm.py`** -- `User` model rewritten:
- `clerk_user_id` removed entirely
- `email` is now `nullable=False, unique=True, index=True` -- the
  canonical login identity (previously this role belonged to
  `clerk_user_id`; `email` had no uniqueness constraint of its own)
- `password_hash: str` added (`String(255)`, bcrypt hash via passlib)
- `is_active: bool` added (`server_default="true"`) -- a soft-disable
  flag for future account suspension without deleting analysis history
- `Analysis.user_id`'s foreign key still points at `users.id` (the UUID
  primary key), which never changed -- this migration does not touch
  any FK relationship

**`backend/migrations/versions/20260624_0000_c3d4e5f6a7b8_migrate_users_to_self_hosted_auth.py`**
(new) -- the actual Alembic migration:
- Drops `ix_users_clerk_user_id` and the `clerk_user_id` column
- Drops the old non-unique `ix_users_email` index, replaces it with a
  unique constraint (`uq_users_email`) and a new unique index
- Adds `password_hash` (`NOT NULL`, no `server_default` -- there is no
  production data yet, pre-launch, so no backfill strategy is needed;
  a real production migration with existing rows would need one)
- Adds `is_active` (`NOT NULL`, `server_default='true'`)
- `downgrade()` reverses every change, including restoring
  `clerk_user_id` as `NOT NULL UNIQUE` -- this will legitimately fail
  on downgrade if any row was created under the new schema, since
  there is no Clerk ID to restore. This is intentional: a downgrade
  past this revision on a database with self-hosted-auth rows is a
  real contract violation and should fail loudly.

**`backend/tests/unit/test_orm_models.py`** -- `TestUserColumns`
rewritten to test the new schema (`email` unique/not-null/max-length,
`password_hash` not-null/max-length, `is_active` not-null/has-default)
instead of the removed `clerk_user_id` assertions.

### `backend/models/schemas.py` (new)

Pydantic v2 request/response schemas, kept separate from `orm.py`
deliberately -- these are the API contract, not the database schema,
and mixing them invites accidentally serialising `password_hash` into
a response:
- `UserRegisterRequest` -- email (`EmailStr`), password (8-72 chars,
  rejects whitespace-only), optional display_name
- `UserLoginRequest` -- email, password
- `UserResponse` -- `from_attributes=True` so it builds directly off a
  `User` ORM instance via `model_validate(user)`; has no `password_hash`
  field at all, so there is no field to accidentally leak even if a
  future edit passed the whole ORM object through carelessly
- `TokenResponse` -- `access_token`, `token_type`, `expires_in_minutes`,
  nested `user: UserResponse`; identical shape returned by both
  `/register` and `/login`
- `TokenPayload` -- decoded JWT claims (`sub`, `exp`), used internally
  by `get_current_user`, never returned in any response

### `backend/services/auth.py` (new)

Pure business logic, no FastAPI imports, fully testable in isolation:
- `hash_password()` / `verify_password()` -- bcrypt via passlib's
  `CryptContext`; `verify_password` catches `ValueError` on a malformed
  hash and returns `False` rather than raising, so a corrupted
  `password_hash` value degrades to "login failed", not a 500
- `create_access_token()` -- issues an HS256 JWT with `sub` (user UUID
  as string) and `exp` claims; `exp` is a real `datetime`, which
  `python-jose` converts to a Unix timestamp internally
- `decode_access_token()` -- verifies signature + expiry, returns
  `TokenPayload`; every failure mode (bad signature, expired, malformed,
  missing claims) raises one exception type, `InvalidTokenError` --
  deliberately not distinguished from each other, since a client should
  not be able to tell "expired" from "tampered" from the response
- `InvalidCredentialsError` -- raised conceptually by the router for
  bad email/password (the router constructs its own `HTTPException`
  directly rather than catching this, but the type exists for any
  future caller that wants to catch it programmatically)

### `backend/dependencies/auth.py` (new)

`get_current_user()` -- the dependency every protected route adds to
its signature:
- Uses `fastapi.security.OAuth2PasswordBearer(tokenUrl="/auth/login")`,
  which wires up the "Authorize" button in Swagger UI at `/docs` so the
  full flow is testable interactively in the browser, not just via
  `curl`
- Verifies the token via `decode_access_token`, explicitly parses the
  `sub` claim as `uuid.UUID(payload.sub)` before querying (rather than
  relying on the database driver to safely reject a malformed string
  passed where a UUID column is expected), queries `User` by `id`,
  checks `is_active`
- Every failure path -- missing token, malformed token, expired token,
  user not found, deactivated user -- raises the exact same
  `HTTPException(401, ..., headers={"WWW-Authenticate": "Bearer"})`

### `backend/routers/auth.py` (new)

- `POST /auth/register` (201) -- checks for an existing email first,
  then handles the `IntegrityError` race condition (two concurrent
  registrations for the same email both passing the initial check)
  as defense-in-depth, returning 409 either way; returns the same
  `TokenResponse` shape as login, so a newly registered user is
  immediately authenticated
- `POST /auth/login` (200) -- "no such user" and "wrong password"
  return the identical 401 response (same status, same `detail`
  string) so a caller cannot enumerate registered emails by observing
  different error messages
- `GET /auth/me` (200) -- the canonical protected-route example;
  depends on `get_current_user`, returns `UserResponse`

### `backend/main.py` (modified)

`auth.router` registered alongside `health.router`. Module docstring
updated -- T-046 auth is no longer "out of scope," only T-047 onward
remains future work.

### `backend/requirements.txt` (modified)

Added `passlib[bcrypt]==1.7.4` and pinned `bcrypt==4.0.1` explicitly.

**Why the explicit bcrypt pin:** `passlib==1.7.4` (the last released
version; upstream is stalled) reads `bcrypt.__about__.__version__`
internally to detect the backend version. That attribute was removed
in `bcrypt==4.1.0`, producing a harmless but noisy
`"(trapped) error reading bcrypt version"` warning on every hash/verify
call. Worse, `bcrypt>=5.0.0` breaks passlib's 72-byte truncation
handling outright, raising `ValueError: password cannot be longer than
72 bytes` on **ordinary passwords** under certain conditions
(documented at github.com/pyca/bcrypt/issues/1079 and #1082). Pinning
to `4.0.1` -- the last version shipping `__about__` -- avoids both the
cosmetic warning and the functional break, exactly mirroring the
existing `pydyf==0.10.0` pin already in this file for the analogous
WeasyPrint/pydyf compatibility break.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/models/orm.py` | **Modified** -- `User` model: drop `clerk_user_id`, add `password_hash`/`is_active`, `email` becomes unique |
| `backend/migrations/versions/20260624_..._migrate_users_to_self_hosted_auth.py` | **New** -- Alembic migration for the above |
| `backend/models/schemas.py` | **New** -- Pydantic request/response schemas |
| `backend/services/auth.py` | **New** -- password hashing + JWT issuance/verification |
| `backend/dependencies/auth.py` | **New** -- `get_current_user` dependency |
| `backend/routers/auth.py` | **New** -- `/auth/register`, `/auth/login`, `/auth/me` |
| `backend/main.py` | **Modified** -- register `auth.router`; docstring update |
| `backend/routers/__init__.py` | **Modified** -- `auth.py` moved from "planned" to "current" |
| `backend/dependencies/__init__.py` | **Modified** -- `auth.py` moved from "planned" to "current" |
| `backend/requirements.txt` | **Modified** -- added `passlib[bcrypt]==1.7.4`, `bcrypt==4.0.1` |
| `backend/tests/unit/test_orm_models.py` | **Modified** -- `TestUserColumns` rewritten for the new schema |
| `backend/tests/unit/test_auth_service.py` | **New** -- password hashing + JWT unit tests |
| `backend/tests/unit/test_dependencies_auth.py` | **New** -- `get_current_user` unit tests, mocked session |
| `backend/tests/unit/test_auth_router.py` | **New** -- end-to-end HTTP tests, fake in-memory session |

---

## Design Decisions & Rationale

**Why catch `IntegrityError` in `register` when there's already a
pre-check `SELECT`?** The `SELECT` then `INSERT` pattern has a real
TOCTOU race: two concurrent registration requests for the same email
can both pass the `SELECT` before either commits. The unique
constraint on `users.email` is the actual source of truth; the
pre-check exists purely to return a fast, clean 409 in the overwhelmingly
common non-race case without needing to inspect a `DBAPIError`'s
driver-specific error code.

**Why does `decode_access_token` raise one exception type
(`InvalidTokenError`) for every failure mode, never distinguishing
expired from malformed from wrong-signature?** A client has no
legitimate use for that distinction -- the correct client behavior is
identical in every case ("re-authenticate"). Distinguishing them would
only help an attacker calibrate an attack against the token scheme.

**Why parse `sub` as `uuid.UUID(payload.sub)` explicitly in
`get_current_user` instead of passing the raw string to
`User.id == user_id`?** `User.id` is a native PostgreSQL `UUID` column
via `asyncpg`. Relying on the driver to safely reject a malformed
string is fragile for a security-critical identity comparison; parsing
explicitly makes the failure mode an immediate, well-understood
`ValueError` caught right where the assumption is made, not a
driver-specific exception surfacing several calls later.

**Why is `login`'s "no such user" and "wrong password" response
byte-for-byte identical?** Distinguishing them lets a caller enumerate
registered emails by observing which error they get back -- a textbook
information-disclosure issue with no benefit to a legitimate caller.

---

## AIRP Standards Compliance

| Standard | Status |
|----------|--------|
| No `from __future__ import annotations` in production modules | OK -- absent from `schemas.py`, `services/auth.py`, `dependencies/auth.py`, `routers/auth.py`. Present in `orm.py` (pre-existing from T-016, predates this rule; SQLAlchemy 2.0 declarative `Mapped[...]` annotations are not affected the way Pydantic v2 unions are, so left as-is) and in the three new test files, consistent with the majority of existing test files |
| Plain ASCII section comments | OK -- no Unicode box-drawing characters in any new file |
| No bare `# type: ignore` | OK -- none needed in any new file this task |
| `mypy --strict` safe | OK -- `Settings \| None` (PEP 604) used instead of `Optional[Settings]` throughout the new service/dependency modules; valid at runtime and under mypy on Python 3.11 without the future-annotations import |
| All lines <= 88 characters | OK -- verified directly by script across all new/modified files |
| No trailing whitespace / tabs | OK -- verified directly by script |
| isort (`force_sort_within_sections`, black profile) | OK -- every import block manually ordered stdlib -> third-party -> first-party, alphabetised within each section |
| Agent/node functions never raise | N/A -- no agent or LangGraph node code touched in this task |
| `ENVIRONMENT=test` guard respected | OK -- new tests rely on the existing `conftest.py` autouse fixture |
| Backward compatibility | **Deliberately broken for `users.clerk_user_id`** -- this is a real, intentional schema migration, not an additive change. Every other file change is additive |

---

## Verification

`fastapi`, `sqlalchemy`, `passlib`, `python-jose`, and `pytest` are not
installed in the sandbox this task was prepared in, and outbound
network access is unavailable there, so the test suite could not be
executed directly. Verification was done by:

1. **`ast.parse()` against every new/modified `.py` file** -- zero
   syntax errors.
2. **Line-length / trailing-whitespace / tab scan** -- zero issues
   across every new/modified file.
3. **AST-based unused-import scan** -- zero unused imports in any new
   module.
4. **Manual isort-ordering review** against the established
   `force_sort_within_sections` + `profile = "black"` convention.
5. **Direct verification of third-party library behavior via official
   documentation and source code** for every non-obvious API surface
   used, rather than assuming from memory:
   - `python-jose`'s `jwt.encode`/`jwt.decode` exception hierarchy
     (`ExpiredSignatureError` is a subclass of `JWTError`) and its
     automatic `datetime` -> Unix-timestamp conversion for `exp`/`iat`/
     `nbf` claims, confirmed against the library's actual source.
   - The `passlib` + `bcrypt>=4.1.0` compatibility break (cosmetic
     warning) and the more severe `bcrypt>=5.0.0` break (functional
     `ValueError` on ordinary passwords), confirmed against multiple
     upstream GitHub issues, before pinning `bcrypt==4.0.1`.
   - SQLAlchemy's documented bind-parameter auto-naming convention
     (`<column>_1`) used by the fake in-memory session in
     `test_auth_router.py`, confirmed against SQLAlchemy's own
     documentation across multiple versions.
   - `sqlalchemy.exc.IntegrityError`'s real constructor signature,
     confirmed against SQLAlchemy 2.0's actual exception reference,
     before using it to simulate a unique-constraint violation in the
     fake session.
6. **A genuine bug found and fixed during this process**: the first
   draft of `get_current_user` passed the JWT `sub` claim (a string)
   directly into `User.id == user_id` without parsing it to a
   `uuid.UUID` first. This was caught while writing the corresponding
   test and fixed before finalising (see "Design Decisions" above).

The commands below are the real commands to run locally before opening
the PR -- this is the step to actually confirm everything passes, not
a substitute for it.

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/api-auth
```

### 2. Place the files

```
backend/models/orm.py                                                  (modified)
backend/migrations/versions/20260624_0000_c3d4e5f6a7b8_migrate_users_to_self_hosted_auth.py  (new)
backend/models/schemas.py                                              (new)
backend/services/auth.py                                               (new)
backend/dependencies/auth.py                                           (new)
backend/routers/auth.py                                                (new)
backend/main.py                                                        (modified)
backend/routers/__init__.py                                            (modified)
backend/dependencies/__init__.py                                       (modified)
backend/requirements.txt                                               (modified)
backend/tests/unit/test_orm_models.py                                  (modified)
backend/tests/unit/test_auth_service.py                                (new)
backend/tests/unit/test_dependencies_auth.py                           (new)
backend/tests/unit/test_auth_router.py                                 (new)
docs/week-13/T-046-implement-auth-with-jwt.md                          (new)
```

### 3. Set environment (Windows Git Bash -- separate command, not chained with &&)

```bash
set ENVIRONMENT=test
```

### 4. Install the two new dependencies

```bash
pip install -r backend/requirements.txt
```

`passlib[bcrypt]==1.7.4` and `bcrypt==4.0.1` are new in this task;
everything else in `requirements.txt` is unchanged. If you already
have a different `bcrypt` version installed from a previous project,
pip will downgrade it to the pinned `4.0.1` -- this is intentional,
see the rationale above.

### 5. Apply the database migration

```bash
cd backend
alembic upgrade head
cd ..
```

This drops `clerk_user_id` and adds `password_hash`/`is_active` to
your local/Neon `users` table. **If you already have rows in `users`
from earlier manual testing, this migration will fail** -- there is no
`password_hash` to backfill for existing Clerk-style rows. For a local
dev database with no real users yet, the simplest fix is to drop and
recreate the table, or drop the whole local database and re-run
`alembic upgrade head` from scratch.

### 6. Run the new test suite in isolation first

```bash
python -m pytest backend/tests/unit/test_auth_service.py backend/tests/unit/test_dependencies_auth.py backend/tests/unit/test_auth_router.py backend/tests/unit/test_orm_models.py -v --tb=short
```

Expected: all tests pass, including `TestRegister`, `TestLogin`,
`TestMe` in `test_auth_router.py` -- these three classes directly
exercise the acceptance criterion "register -> login -> access
protected route works end-to-end" -- and every `test_*_returns_401`
test across all three new test files, which exercise "invalid token
returns 401."

### 7. Manually smoke-test the running server

```bash
uvicorn backend.main:app --reload --port 8000
```

In a second terminal:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"correct-horse-battery-staple"}'
```

Expected: `201`, a JSON body with `access_token`, `token_type: bearer`,
`user.email`. Then:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"correct-horse-battery-staple"}'
```

Copy the `access_token` from the response, then:

```bash
curl http://localhost:8000/auth/me -H "Authorization: Bearer <paste-token-here>"
```

Expected: `200`, the same user's email. Then confirm the negative case:

```bash
curl -i http://localhost:8000/auth/me -H "Authorization: Bearer not-a-real-token"
```

Expected: `401`.

You can also do all of this interactively at `http://localhost:8000/docs`
-- click "Authorize," paste a token obtained from `/auth/login`'s
response, and `GET /auth/me` will now succeed directly from Swagger UI.

### 8. Run the full default suite to confirm no regressions

```bash
python -m pytest --tb=short -q
```

### 9. Run lint and type checks exactly as CI does

```bash
black --check backend/
isort --check-only backend/
flake8 backend/
mypy backend/
```

### 10. Confirm coverage

```bash
pytest --cov=backend --cov-report=term-missing -m "not integration" -q
```

### 11. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/models/orm.py \
        backend/migrations/versions/20260624_0000_c3d4e5f6a7b8_migrate_users_to_self_hosted_auth.py \
        backend/models/schemas.py \
        backend/services/auth.py \
        backend/dependencies/auth.py \
        backend/routers/auth.py \
        backend/main.py \
        backend/routers/__init__.py \
        backend/dependencies/__init__.py \
        backend/requirements.txt \
        backend/tests/unit/test_orm_models.py \
        backend/tests/unit/test_auth_service.py \
        backend/tests/unit/test_dependencies_auth.py \
        backend/tests/unit/test_auth_router.py \
        docs/week-13/T-046-implement-auth-with-jwt.md
git commit -m "feat(api): implement self-hosted JWT auth with bcrypt"
```

If black/isort auto-fix anything:

```bash
git add .
git commit -m "feat(api): implement self-hosted JWT auth with bcrypt"
```

### 12. Push and open PR

```bash
git push -u origin feat/api-auth
```

---

## PR Details

**PR title:**
```
feat(api): implement self-hosted JWT auth with bcrypt password hashing
```

**PR description:**

```markdown
## Summary

Implements POST /auth/register, POST /auth/login, and GET /auth/me
with bcrypt-hashed passwords and self-issued JWT access tokens. This
required migrating the `users` table away from its original
Clerk-based design (clerk_user_id as canonical identity) to a
self-hosted email/password model, since the existing schema had no
password_hash column and was architecturally incompatible with this
task's literal requirements. See the linked task doc for the full
rationale on this discrepancy and the migration it required.

## Changes

- `backend/models/orm.py` -- User model: drop clerk_user_id, add
  password_hash + is_active, email becomes the unique identity column
- New Alembic migration for the above (drops/adds columns and
  constraints; downgrade() intentionally fails if any row was created
  under the new schema, since there's no Clerk ID to restore)
- `backend/models/schemas.py` -- new Pydantic schemas:
  UserRegisterRequest, UserLoginRequest, UserResponse, TokenResponse,
  TokenPayload
- `backend/services/auth.py` -- new: bcrypt hashing (passlib) + JWT
  issuance/verification (python-jose), no FastAPI dependency, fully
  unit-testable in isolation
- `backend/dependencies/auth.py` -- new: get_current_user, the
  protected-route dependency; wires OAuth2PasswordBearer so Swagger
  UI's "Authorize" button works against /auth/login
- `backend/routers/auth.py` -- new: the three endpoints; login's
  "wrong password" and "no such user" responses are identical by
  design to avoid email enumeration
- `backend/requirements.txt` -- added passlib[bcrypt]==1.7.4,
  bcrypt==4.0.1 (explicit pin -- bcrypt>=4.1.0 breaks passlib's
  version detection; bcrypt>=5.0.0 breaks password truncation
  handling outright, see github.com/pyca/bcrypt/issues/1079)
- `backend/tests/unit/test_orm_models.py` -- TestUserColumns rewritten
  for the new schema
- Three new test files: test_auth_service.py (hashing + JWT, no DB),
  test_dependencies_auth.py (get_current_user, mocked session),
  test_auth_router.py (full HTTP register->login->me flow against a
  fake in-memory session)

## Testing

- New test files cover both acceptance criteria directly: the full
  register -> login -> protected-route flow (test_auth_router.py's
  TestRegister/TestLogin/TestMe), and every invalid-token path across
  all three new files (garbage token, expired token, wrong signature,
  missing token, deactivated user, non-existent user -- each asserts
  exactly 401)
- Manual smoke test via curl and Swagger UI's interactive "Authorize"
  flow
- `pytest --tb=short -q` -- full existing suite, no regressions
- `black --check`, `isort --check-only`, `flake8`, `mypy` all run
  locally before pushing

## LangSmith Trace

Not applicable -- no agent or LangGraph node code touched in this PR.

## Related Issues

Closes #46
```

**Squash merge** to main.

---

## After Merge

AIRP now has working self-hosted authentication: register, log in, and
call a protected route with a bearer token, all the way through to
database persistence. The Phase 1-4 analysis pipeline is still not
reachable over HTTP -- T-047 begins exposing it.

Next task: **T-047 -- POST /api/v1/analysis/start**
(creates a DB record, triggers the LangGraph pipeline as a background
task, returns a `job_id`; the route will be the second consumer of
`get_current_user`, associating each analysis with the authenticated
user via `Analysis.user_id`).

Branch: `feat/api-analysis-start`.

---

*End of Document | T-046 Workflow | AIRP Week 13*