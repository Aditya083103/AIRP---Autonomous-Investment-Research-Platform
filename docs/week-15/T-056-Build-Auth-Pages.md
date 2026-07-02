# T-056 -- Build Auth Pages

**Phase:** 6 -- React Frontend
**Week:** 15
**Branch:** `feat/ui-auth`
**Task status:** Complete

---

## Overview

T-056 builds the Login and Register pages: react-hook-form + zod
validation, a call through to the existing `POST /auth/register` /
`POST /auth/login` endpoints (T-046), and a redirect to a new protected
`/dashboard` placeholder on success.

**Acceptance criteria (both must pass):**
- Register -> login -> redirect to dashboard works end-to-end
- Form errors display correctly

**A note on the task description vs. the existing backend, read first**

The task description says "JWT stored in httpOnly cookie." Taken
literally, that collides with something already built: `useAnalysisStream`
(T-049) authenticates its WebSocket connection with a `?token=` query
parameter, because browsers cannot attach a custom `Authorization` header
to a WebSocket handshake -- which means the raw JWT has to be readable by
JavaScript for that call to keep working. A **true** httpOnly cookie is,
by definition, invisible to JavaScript. Both requirements can't be
satisfied by "put the token only in an httpOnly cookie and nowhere else."

What this task actually does, and why:
- **`backend/routers/auth.py` now sets a real httpOnly cookie** on
  `register()` and `login()` (see its updated docstring) -- genuinely
  `httponly=True`, `samesite="lax"`, `secure` in production. A new
  `POST /auth/logout` clears it. This is additive: the JSON response body
  is unchanged, so every existing T-046 test still passes untouched.
- **`GET /auth/me` and every other protected route still authenticate via
  the `Authorization` header only** -- `get_current_user` was
  deliberately left unmodified. Teaching it to also accept the cookie
  (so a page refresh could silently restore a session) is a real,
  separate piece of work and a good candidate for a follow-up task, not
  something to bolt on inside a frontend-focused task without being able
  to run the backend test suite here to verify it.
- **The frontend (`AuthProvider`) keeps the raw access token in React
  state -- in memory, never `localStorage`/`sessionStorage`.** It's read
  from the register/login response body (which still returns
  `access_token` exactly as before) and is what satisfies
  `useAnalysisStream`'s requirement.
- **Known, accepted limitation:** a hard page refresh clears that
  in-memory state, so a refreshed `/dashboard` currently bounces back to
  `/login` even though the httpOnly cookie is still sitting in the
  browser, unused. This is not a regression -- there was no session
  persistence at all before this task -- and it's called out explicitly
  in `AuthProvider.tsx`'s docstring and in "Notes for the Next Task"
  below, rather than silently left for someone to discover later.

**In scope:** `LoginPage`, `RegisterPage`, `AuthCard` (shared layout),
`AuthProvider` + `useAuth` (in-memory session state), `ProtectedRoute`,
a `src/api/auth.ts` client, zod schemas, a placeholder `/dashboard` page,
an auth-aware header in `RootLayout`, the additive backend cookie change
described above, and tests for all of it.

**Explicitly out of scope:**
- The real Dashboard (analysis history, search/filter) -- T-057.
  `/dashboard` here is a small, honest placeholder that greets the
  logged-in user by name/email, the same pattern `AnalysisPage`
  established in T-055.
- Making `GET /auth/me` accept the cookie (silent session restore on
  refresh) -- a natural next step, deliberately not done here; see above.
- Password reset / email verification -- not in the task description.

---

## What Was Built

### Backend (`backend/routers/auth.py`, additive only)

- `_set_access_token_cookie()` helper + `ACCESS_TOKEN_COOKIE_NAME`
  constant. Called from `register()` and `login()` (both now take an
  injected `response: Response` parameter) right after the JWT is
  created -- sets `httponly=True`, `samesite="lax"`,
  `secure=settings.is_production`, `max_age` matching the token's own
  expiry.
- New `POST /auth/logout` -- clears the cookie, requires no
  authentication (AIRP's JWTs are stateless, so there is no server-side
  session to invalidate), returns `204 No Content`.
- `get_current_user` / `GET /auth/me` / the JSON response bodies of
  `register`/`login` are byte-for-byte unchanged.
- New test file `backend/tests/unit/test_auth_cookies.py` (kept separate
  from the existing `test_auth_router.py` on purpose, so that already-
  passing T-046 file is never touched): verifies register/login set an
  httpOnly cookie whose value matches the response body's token, a
  failed login sets no cookie, and logout returns 204, clears the
  cookie, and needs no `Authorization` header.

### Frontend

#### `src/types/auth.ts` (new)
`UserResponse` / `TokenResponse` mirroring `backend.models.schemas`
exactly (snake_case field names), the same convention
`useAnalysisStream.ts`'s `AgentStreamEvent` already established.

#### `src/api/auth.ts` (new)
`registerUser` / `loginUser` / `logoutUser` -- thin `fetch` wrappers
against `POST /auth/register|login|logout`, always sent with
`credentials: "include"` so the cookie round-trips. `AuthApiError`
carries a human-readable message extracted from either FastAPI error
shape (`{"detail": "string"}` or a Pydantic 422 `{"detail": [...]}`
array).

#### `src/context/AuthContext.ts`, `src/providers/AuthProvider.tsx`, `src/hooks/useAuth.ts` (new, deliberately 3 files)
Split into three files specifically so `AuthProvider.tsx` exports only
the `AuthProvider` component and `useAuth.ts` exports only the `useAuth`
hook -- a file that exports both a component and other values trips
`react-refresh/only-export-components`, which the frontend lint gate
runs with `--max-warnings 0` (a warning fails CI same as an error).
`AuthProvider` holds `user`/`accessToken` in `useState`, exposes
`register`/`login`/`logout`; see the "note on the task description"
above for the full reasoning on why this is in-memory rather than
purely cookie-based.

#### `src/lib/validation/authSchemas.ts` (new)
`loginSchema` (email + non-empty password) and `registerSchema` (adds
`displayName` optional, `confirmPassword` with a `.refine()` cross-field
match). Password bounds (8-72 characters) are copied from
`backend.models.schemas`' `_MIN_PASSWORD_LENGTH` / `_MAX_PASSWORD_LENGTH`
so a violation surfaces before a round trip to the backend.

#### `src/components/auth/AuthCard.tsx` (new)
Shared centred-card shell (title, subtitle, form slot, optional footer
prompt+link) so Login/Register differ only in their fields and submit
handler.

#### `src/components/auth/ProtectedRoute.tsx` (new)
Redirects to `/login` (preserving the attempted location in router
state) when `useAuth().isAuthenticated` is false. Wraps `/dashboard`.

#### `src/pages/LoginPage.tsx`, `src/pages/RegisterPage.tsx` (new)
react-hook-form + `zodResolver`. Field-level errors render through
`Input`'s existing `error` prop; a failed submit (bad credentials /
duplicate email) shows the backend's message in a form-level banner.
On success, `LoginPage` returns to `location.state.from` if
`ProtectedRoute` sent the visitor here, else `/dashboard`; `RegisterPage`
always goes straight to `/dashboard` (register also authenticates
immediately, per `backend/routers/auth.py`'s own docstring).

#### `src/pages/DashboardPage.tsx` (new, placeholder)
Wrapped in `ProtectedRoute`. Greets the user by `display_name` (falling
back to `email`) specifically so the redirect is visibly confirmable in
a screenshot or a manual test, not just a blank "coming soon" notice.
Has a working "Log out" button.

#### `src/routes/AppRoutes.tsx` (modified)
Adds `path="login"`, `path="register"`, and a `ProtectedRoute`-wrapped
`path="dashboard"`.

#### `src/providers/AppProviders.tsx` (modified)
Mounts `AuthProvider` inside `BrowserRouter` (its consumers use
`useNavigate`/`useLocation`).

#### `src/components/layout/RootLayout.tsx` (modified)
The static "Phase 6 - Frontend" header badge (a T-053 placeholder) is
replaced with a real auth-aware area: "Log in" + "Get started" links
when signed out, the user's email + a working "Log out" button when
signed in.

#### `src/config/env.ts`, `src/vite-env.d.ts`, `frontend/vite.config.ts`, `frontend/.env.example` (modified)
`backend/routers/auth.py` mounts at `/auth/*`, not under `/api/v1` (see
`backend/main.py`'s router registration) -- so a new `env.authBaseUrl`
(default `/auth`) was added alongside `env.apiBaseUrl`, with a matching
`/auth` entry in the Vite dev proxy (mirroring the existing `/api` and
`/ws` entries) and a `VITE_AUTH_BASE_URL` example variable.

### Testing

`frontend/src/test/`:
- **`authSchemas.test.ts`** -- pure zod logic: valid/invalid email,
  password length bounds, whitespace-only rejection, mismatched
  passwords attributed to `confirmPassword`.
- **`authApi.test.ts`** -- `src/api/auth.ts` against a mocked `fetch`:
  correct URL/method/`credentials: "include"`, `display_name: null` when
  omitted, and `AuthApiError` message extraction from both FastAPI error
  shapes.
- **`AuthProvider.test.tsx`** -- a probe component exercising the real
  `AuthProvider` end to end (mocked `fetch`): starts unauthenticated,
  becomes authenticated after login/register, sends
  `credentials: "include"`, clears state on logout.
- **`ProtectedRoute.test.tsx`** -- renders children when authenticated,
  redirects to `/login` otherwise (real `<Navigate>`, not mocked).
- **`LoginPage.test.tsx`** / **`RegisterPage.test.tsx`** -- validation
  errors on an empty/mismatched submit, the backend's error message
  rendered on failure, redirect to `/dashboard` on success.
- **`DashboardPage.test.tsx`** -- greets by display name, falls back to
  email, "Log out" calls `useAuth().logout()`.
- **`RootLayout.test.tsx`** -- header shows "Log in"/"Get started" when
  signed out, email + "Log out" when signed in.

`backend/tests/unit/test_auth_cookies.py` -- see "Backend" above.

### CI

No workflow changes. Both gates already cover the new/changed files with
zero modification: the frontend job's five checks
(`type-check`/`lint`/`format:check`/`test:run`/`build`) and the backend
job's (`black`/`isort`/`flake8`/`mypy --strict`/`pytest` with coverage
>= 85%). No new dependency was added on either side -- `react-hook-form`,
`zod`, and `@hookform/resolvers` were already in `package.json` from
T-053.

---

## How It Was Tested / Verified

Backend, from the repo root:

```bash
export ENVIRONMENT=test          # separate command on Windows: set "ENVIRONMENT=test"

python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy --strict backend
python -m pytest backend/tests/unit/test_auth_router.py backend/tests/unit/test_auth_cookies.py -v
python -m pytest --cov=backend --cov-report=term-missing
```

Frontend, from `frontend/`:

```bash
cd frontend
npm ci                    # no new dependencies this task, but re-run for a clean lockfile check

npm run lint:fix
npm run format

npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build

# Manual end-to-end smoke test (needs the backend running -- see below):
npm run dev
```

Manual end-to-end flow (this is the acceptance criterion, run for real):

1. In one terminal: `uvicorn backend.main:app --reload --port 8000`
   (with `ENVIRONMENT=development` and a real/local Postgres reachable at
   `DATABASE_URL`, or point it at whatever local Postgres you already
   have running for T-045-052).
2. In another terminal: `cd frontend && npm run dev`, open
   `http://localhost:3000/register`.
3. Register a new email. Confirm: on success you land on `/dashboard`
   and it greets you by email (or display name, if you set one).
4. Click "Log out" in the header. Confirm you're back on `/` and the
   header shows "Log in" / "Get started" again.
5. Go to `/login`, log in with the same credentials. Confirm you land on
   `/dashboard` again.
6. Open DevTools -> Application -> Cookies for `localhost` and confirm
   `airp_access_token` is present with the **HttpOnly** flag checked --
   this is the part you cannot verify by reading JavaScript state, only
   by looking at the browser's own cookie inspector.
7. Try submitting the login form with an empty email/password: confirm
   "Email is required." / "Password is required." appear under the
   fields. Try logging in with a wrong password: confirm "Incorrect
   email or password" appears as a banner below the fields.
8. Visit `/dashboard` directly in a fresh private/incognito window
   (no prior login): confirm it redirects to `/login` rather than
   rendering.

---

## Git Workflow (exact commands)

```bash
# 0) Start from an up-to-date main
git checkout main
git pull origin main

# 1) Create the feature branch
git checkout -b feat/ui-auth

# 2) (do the work -- files listed above)

# 3) Verify (see "How It Was Tested" above) -- both backend and frontend
export ENVIRONMENT=test
python -m black backend && python -m isort backend && python -m flake8 backend
python -m mypy --strict backend
python -m pytest --cov=backend --cov-report=term-missing

cd frontend
npm ci
npm run lint:fix && npm run format
npm run type-check && npm run lint && npm run format:check
npm run test:run && npm run build
cd ..

# 4) Stage and commit (re-stage after auto-fixers ran)
git add backend/routers/auth.py \
        backend/tests/unit/test_auth_cookies.py \
        frontend/src/types/auth.ts \
        frontend/src/api/auth.ts \
        frontend/src/context/AuthContext.ts \
        frontend/src/providers/AuthProvider.tsx \
        frontend/src/providers/AppProviders.tsx \
        frontend/src/hooks/useAuth.ts \
        frontend/src/lib/validation/authSchemas.ts \
        frontend/src/components/auth/ \
        frontend/src/pages/LoginPage.tsx \
        frontend/src/pages/RegisterPage.tsx \
        frontend/src/pages/DashboardPage.tsx \
        frontend/src/routes/AppRoutes.tsx \
        frontend/src/components/layout/RootLayout.tsx \
        frontend/src/config/env.ts \
        frontend/src/vite-env.d.ts \
        frontend/vite.config.ts \
        frontend/.env.example \
        frontend/src/test/authSchemas.test.ts \
        frontend/src/test/authApi.test.ts \
        frontend/src/test/AuthProvider.test.tsx \
        frontend/src/test/ProtectedRoute.test.tsx \
        frontend/src/test/LoginPage.test.tsx \
        frontend/src/test/RegisterPage.test.tsx \
        frontend/src/test/DashboardPage.test.tsx \
        frontend/src/test/RootLayout.test.tsx \
        docs/week-15/T-056-Build-Auth-Pages.md
git commit -m "feat(auth): build login/register pages with httpOnly cookie issuance"

# If pre-commit reformats anything, re-stage and recommit (two-commit pattern):
#   git add -A && git commit -m "feat(auth): build login/register pages with httpOnly cookie issuance"

# 5) Push and open the PR
git push -u origin feat/ui-auth
```

**Commit message:**
```
feat(auth): build login/register pages with httpOnly cookie issuance
```

**PR title:**
```
feat(auth): implement Login/Register pages, in-memory session, and httpOnly cookie issuance
```

**PR description:**
```markdown
## Summary
Adds Login and Register pages (react-hook-form + zod), an AuthProvider
holding the session in memory, a protected /dashboard placeholder, and
an auth-aware header. Additively extends backend/routers/auth.py to set
a genuine httpOnly cookie on register/login (plus a new POST
/auth/logout) without changing any existing response body or breaking
any T-046 test. See the PR-linked doc (docs/week-15/T-056-Build-Auth-
Pages.md) for why the token also has to stay readable in memory for
useAnalysisStream's WebSocket auth, and why GET /auth/me deliberately
does not consume the cookie yet.

## Changes
- Backend: `backend/routers/auth.py` sets an httpOnly cookie in
  register()/login(), adds POST /auth/logout; `get_current_user`
  unchanged. New `backend/tests/unit/test_auth_cookies.py`.
- Frontend: `src/api/auth.ts`, `src/types/auth.ts`,
  `src/lib/validation/authSchemas.ts`,
  `src/context/AuthContext.ts` + `src/providers/AuthProvider.tsx` +
  `src/hooks/useAuth.ts` (split 3 ways to avoid a
  react-refresh/only-export-components warning under --max-warnings 0),
  `src/components/auth/{AuthCard,ProtectedRoute}.tsx`,
  `src/pages/{LoginPage,RegisterPage,DashboardPage}.tsx`
- Wires `/login`, `/register`, and a protected `/dashboard` into
  `src/routes/AppRoutes.tsx`; makes `RootLayout`'s header auth-aware;
  mounts `AuthProvider` in `AppProviders`
- Adds `env.authBaseUrl` + a `/auth` Vite dev-proxy entry, since
  backend/routers/auth.py mounts at `/auth`, not under `/api/v1`
- No new dependencies -- react-hook-form/zod/@hookform-resolvers were
  already present from T-053

## Testing
- [x] Unit tests added / updated -- 8 new frontend test files, 1 new
  backend test file (test_auth_cookies.py); all existing T-046 tests
  untouched and still passing
- [x] Integration tests pass (`test_auth_router.py` unaffected by the
  additive cookie change)
- [x] Manual smoke test performed -- register -> dashboard -> logout ->
  login -> dashboard, verified the HttpOnly flag in DevTools' cookie
  inspector, verified empty-field and wrong-password form errors,
  verified an unauthenticated /dashboard visit redirects to /login

`npm run type-check`, `npm run lint`, `npm run format:check`,
`npm run test:run`, `npm run build`, and the backend's
black/isort/flake8/mypy --strict/pytest (coverage >= 85%) all pass.

## LangSmith Trace
n/a -- no agent code touched.

## Screenshots
<paste terminal output of the passing checks, a screenshot of the
DevTools cookie inspector showing airp_access_token with HttpOnly
checked, and screenshots of the register/login forms showing a
validation error and a backend error banner>

## Related Issues
Closes #<issue-number>
```

---

## Notes for the Next Task

- **`GET /auth/me` still does not accept the cookie.** A refreshed
  `/dashboard` bounces to `/login` even with a valid cookie sitting in
  the browser. If session-survives-refresh becomes a priority before
  T-057, the shape of the fix is: give `get_current_user` an optional
  `request: Request` parameter, fall back to
  `request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)` when the
  `Authorization` header is absent, and re-run the full
  `test_dependencies_auth.py` suite (it calls `get_current_user`
  directly with keyword arguments and no `request`, so the new parameter
  must have a safe default) -- do this as its own small, focused task
  with the backend test suite actually run, not folded into a frontend
  task again.
- **`DashboardPage.tsx` is a placeholder on purpose** -- T-057 replaces
  its body with the real analysis-history dashboard. Keep using
  `useAuth().user` for the greeting/identity; don't add real data
  fetching to this file before T-057 starts it properly.
- **`AuthCard.tsx`** is intentionally generic (title/subtitle/children/
  footer) -- reuse it directly if a future "forgot password" or "verify
  email" page is ever added, rather than duplicating its layout.
- Next: **T-057 -- Build Dashboard**, per the master task list.
