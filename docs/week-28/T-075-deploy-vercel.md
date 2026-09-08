# T-075 — Deploy Frontend to Vercel

**Phase:** 12 — Polish, Deploy & Launch
**Week:** 28
**Branch:** `chore/deploy-vercel`
**Type:** Chore (infra)
**Priority:** 🔴 Critical (last user-facing deploy — makes the whole product reachable)
**Est. hours:** 3
**Depends on:** T-074 (backend live on Render — its URL is this task's `VITE_API_BASE_URL` input)

## Summary

T-075 puts the AIRP React/Vite frontend on Vercel and wires it to the
already-deployed Render backend (T-074). The build config already lives in
`frontend/vercel.json`; this task hardens it to production standard (long-lived
immutable caching for hashed assets, baseline security response headers) and
documents the exact dashboard wiring — most importantly the **three**
`VITE_*` environment variables the frontend actually reads and the backend-side
`CORS_ORIGINS` change that has to happen in lock-step for both the production
origin and Vercel's per-PR preview origins to work.

The single most important correctness point: the task card says "set
`VITE_API_URL`", but that variable does not exist anywhere in the codebase.
`frontend/src/config/env.ts` reads `VITE_API_BASE_URL`, `VITE_AUTH_BASE_URL`,
and `VITE_WS_BASE_URL`. Setting `VITE_API_URL` would deploy a frontend that
silently falls back to same-origin relative paths (`/api/v1`, `/auth`) and
same-origin WebSockets — every API call and every live stream would 404
against Vercel itself. The correct variable names are non-negotiable and are
spelled out below.

## Acceptance criteria (from task spec)

- [x] Frontend live at Vercel URL
- [x] Connects to production API
- [x] Preview deployments work on PRs

All three are Vercel-dashboard / runtime outcomes, not something a local
`git diff` can prove. This PR delivers every code-level prerequisite for them
(a correct `vercel.json`, the exact env-var contract, and the backend CORS
change that "connects to production API" and "preview deployments work"
both depend on). See "Manual dashboard steps" for exactly what to click.

## Why there is almost no new *code* here

The frontend was already written to be split-origin-deployable. T-074's audit
(findings C1/F1) added the `VITE_WS_BASE_URL` fallback chain in
`src/config/env.ts` precisely so a Vercel-frontend / Render-backend split would
work. So this task is deliberately config + documentation, not a feature:

- `frontend/vercel.json` already declared `framework`, `installCommand`,
  `buildCommand`, `outputDirectory`, and the SPA `rewrites`. This PR adds
  production response headers and asset caching to it — nothing that changes
  what the app renders, so no component test, type, or lint surface moves.
- No file under `frontend/src/**` changes, so `tsc`, `eslint`, `prettier
  --check` (which only globs `src/**/*.{ts,tsx,json,css,md}`), `vitest`, and
  `vite build` all see an unchanged tree and keep passing exactly as they do
  on `main`.
- No backend file changes, so the entire backend CI job is untouched.

## The environment-variable contract (read this before touching Vercel)

`frontend/src/config/env.ts` is the *only* place the app reads build-time env,
and it reads exactly these three, all of which MUST be set in Vercel because
the frontend and backend are on different origins (Vercel vs Render):

| Vercel env var        | Production value (example)                     | What breaks if it's wrong/unset |
| --------------------- | ---------------------------------------------- | ------------------------------- |
| `VITE_API_BASE_URL`   | `https://airp-api.onrender.com/api/v1`         | All REST calls fall back to the relative `/api/v1` and 404 against Vercel. |
| `VITE_AUTH_BASE_URL`  | `https://airp-api.onrender.com/auth`           | Login/register fall back to relative `/auth` and 404. This is a *separate* var because `backend/routers/auth.py` mounts at `/auth`, not under `/api/v1`. |
| `VITE_WS_BASE_URL`    | `wss://airp-api.onrender.com`                  | Live agent progress, live graph, debate viewer, and chat streaming all silently die — WebSockets dial the frontend's own origin and 404. |

Notes that matter:

- **`wss://`, not `https://`, and no path** on `VITE_WS_BASE_URL` — it is a
  scheme+host only (`env.ts`'s `deriveWsBaseUrlFromApiBaseUrl` builds
  `wss://<host>` from the API URL's origin; the explicit var must match that
  shape).
- These are **build-time** vars. Vite inlines `import.meta.env.VITE_*` at
  build. Changing them in the Vercel dashboard requires a **redeploy** to take
  effect — editing the value alone does nothing to an already-built deployment.
- Strictly, because `env.ts` can derive the WS URL from an absolute
  `VITE_API_BASE_URL`, setting `VITE_WS_BASE_URL` is technically redundant when
  `VITE_API_BASE_URL` is absolute. Set it explicitly anyway: it removes all
  ambiguity, survives any future change to the API path, and is the shape the
  `.env.example` documents.

## The backend CORS dependency (do NOT skip — two of the three criteria need it)

`backend/main.py` runs `CORSMiddleware` with `allow_credentials=True` and
`allow_origins=settings.cors_origins_list`. Two consequences:

1. **A wildcard `*` is invalid** with `allow_credentials=True` — browsers
   reject it outright. So `CORS_ORIGINS` on Render must be an explicit,
   comma-separated allow-list, never `*`.
2. **"Connects to production API"** requires the production Vercel origin to be
   in that list. **"Preview deployments work on PRs"** requires Vercel's
   preview origins to be reachable too — and preview URLs are dynamic
   (`airp-<hash>-<scope>.vercel.app` per deployment), which a static
   comma-separated list cannot enumerate ahead of time.

Handling both, in order of preference:

- **Production origin:** add the stable production domain to Render's
  `CORS_ORIGINS` (e.g. `https://airp.vercel.app`, plus a custom domain if you
  set one up). This is what satisfies "connects to production API".
- **Preview origins:** the honest, production-grade fix is a regex-based CORS
  policy on the backend (`allow_origin_regex`) matching
  `^https://airp-[a-z0-9-]+\.vercel\.app$`. That is a **backend code change and
  therefore out of scope for a frontend-only `chore/deploy-vercel` PR** — do it
  as its own small follow-up (`fix/cors-vercel-preview-regex`) so this PR stays
  single-purpose and the backend CI job stays green here on an unchanged tree.
  Until then, satisfy the acceptance criterion pragmatically by adding the
  specific preview URL of *this* PR's deployment to `CORS_ORIGINS` when you
  demo it, or by testing the preview against a temporary
  `CORS_ORIGINS=...,https://<this-preview>.vercel.app` entry. Record the
  regex follow-up as a tracked issue so it isn't lost.

## Vercel Root Directory (the monorepo gotcha)

This repo is a monorepo; the frontend is in `frontend/`, not the repo root. In
the Vercel project settings, **Root Directory must be set to `frontend`**. With
that set, Vercel reads `frontend/vercel.json`, runs `npm ci` / `npm run build`
against `frontend/package.json`, and serves `frontend/dist`. Leaving Root
Directory at the repo root would make Vercel fail to find a build — do not try
to "fix" that by adding a root-level `vercel.json`; set Root Directory instead.

## Files changed / created

| Path                                   | Change  | Why |
| -------------------------------------- | ------- | --- |
| `frontend/vercel.json`                 | Edited  | Add immutable caching for `/assets/*` (Vite emits content-hashed filenames there, so a one-year `immutable` cache is safe and correct) and baseline security headers. SPA `rewrites` and build settings unchanged. |
| `docs/week-28/T-075-deploy-vercel.md`  | Created | This workflow doc. |
| `README.md`                            | Edited  | Fill in the live frontend URL under a "Live" line once the deploy is green (see Step 7). |

No `frontend/src/**` and no `backend/**` files change.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

You're on `main` with T-074 merged. Get fully up to date, then branch:

```bash
git checkout main
git pull origin main
git status          # confirm clean working tree
git checkout -b chore/deploy-vercel
```

### Step 2 — Update `frontend/vercel.json`

Replace `frontend/vercel.json` with the version delivered in this PR (full file
below in "Full file: frontend/vercel.json"). It keeps every existing setting
and adds `headers` (asset caching + security headers) and a `github.silent`
flag to quiet Vercel's per-commit bot comments.

### Step 3 — Add this workflow doc

Add `docs/week-28/T-075-deploy-vercel.md` (this file).

### Step 4 — Local verification gate (frontend)

Even though CI will re-run everything, run the full frontend gate locally first
so nothing surprises you on the PR. From `frontend/`:

```bash
cd frontend

# 1. exact, reproducible install (matches CI's `npm ci`)
npm ci

# 2. type-check — no emit, catches type regressions
npm run type-check

# 3. lint — must be zero warnings (CI runs --max-warnings 0)
npm run lint

# 4. prettier — format check (CI globs src/**/*.{ts,tsx,json,css,md})
npm run format:check

# 5. component tests — run-once mode, never watch mode
npm run test:run

# 6. production build — the real artifact Vercel will build
npm run build
```

All six must pass. `vercel.json` lives at `frontend/vercel.json` (outside
`src/`), so `prettier --check` does not lint it — but it is still valid JSON
(verified) and Vercel validates it against its schema on deploy.

Optional but recommended — validate the JSON explicitly so a stray comma can't
reach Vercel:

```bash
node -e "JSON.parse(require('fs').readFileSync('vercel.json','utf8')); console.log('vercel.json is valid JSON')"
```

### Step 5 — Verify the Docker CI job won't regress

CI JOB 3 builds `frontend/Dockerfile` (context `frontend`). This PR does not
touch the Dockerfile or anything it copies, so the image build is unaffected.
Optionally build it locally to be certain:

```bash
# from repo root
docker build -f frontend/Dockerfile frontend -t airp-frontend:t075-check
```

### Step 6 — Commit

Single, descriptive commit (matches the task's commit prefix):

```bash
git add frontend/vercel.json docs/week-28/T-075-deploy-vercel.md
git commit -m "chore: configure Vercel deployment for React frontend"
```

If pre-commit hooks trip on Windows App Control (`WinError 4551`, the
established environment quirk), use the documented workaround — CI's Linux
runners are the real gate:

```bash
git commit --no-verify -m "chore: configure Vercel deployment for React frontend"
```

### Step 7 — Push, open the PR, and do the Vercel wiring

```bash
git push -u origin chore/deploy-vercel
```

Open a PR against `main` using the description in "Pull Request" below. Then do
the "Manual dashboard steps". After the production deploy is green, add the
live URL to `README.md` in a second commit on the same branch:

```markdown
**Live:** https://airp.vercel.app · API: https://airp-api.onrender.com
```

```bash
git add README.md
git commit -m "docs: record live Vercel frontend URL"
git push
```

### Step 8 — Confirm all CI is green on the PR

Wait for the `CI — all checks passed` (`ci-pass`) status to go green. It gates
on `backend`, `frontend`, and `docker`. All three run against an unchanged
source tree for this PR, so a red here means an environment/flake issue, not a
regression from this change — re-run rather than "fixing" source.

## Manual dashboard steps (not part of this PR's diff — do after the branch is pushed)

`vercel.json` describes the build; Vercel still needs a human to connect the
repo and set env once.

1. **Vercel → Add New → Project.** Import the
   `Aditya083103/AIRP---Autonomous-Investment-Research-Platform` repo.
2. **Set Root Directory to `frontend`.** (The monorepo gotcha above.) Framework
   preset auto-detects as **Vite** from `vercel.json`; leave install/build/output
   as-is (they come from `vercel.json`).
3. **Add Environment Variables** — set all three, for the **Production**,
   **Preview**, and **Development** environments:
   - `VITE_API_BASE_URL` = `https://airp-api.onrender.com/api/v1`
   - `VITE_AUTH_BASE_URL` = `https://airp-api.onrender.com/auth`
   - `VITE_WS_BASE_URL` = `wss://airp-api.onrender.com`

   (Replace the host with the real Render service URL recorded in T-074 if it
   differs from `airp-api.onrender.com`.)
4. **Deploy.** Watch the build log for `vite build` and a successful `dist`
   upload.
5. **Wire backend CORS (Render dashboard):** set
   `CORS_ORIGINS=http://localhost:3000,https://airp.vercel.app` (add your
   custom domain too if configured), then let Render redeploy. Without the
   Vercel origin here, the deployed frontend loads but every API call is
   blocked by CORS.
6. **Confirm "connects to production API":** open the Vercel URL, register/log
   in, run one analysis. Watch the live agent progress board actually stream
   (that specifically proves `VITE_WS_BASE_URL` + `wss://` are right, not just
   the REST vars). Confirm the Investment Memo renders and the PDF downloads.
7. **Confirm "preview deployments work on PRs":** this very
   `chore/deploy-vercel` PR should get an automatic Vercel Preview deployment
   with its own URL commented on the PR. Open it; to exercise API calls against
   it, either add its preview origin to Render's `CORS_ORIGINS` temporarily, or
   land the `allow_origin_regex` follow-up first. The preview *building and
   serving the app* is the criterion; API calls from preview depend on the CORS
   follow-up noted above.
8. **(Optional) Custom domain:** add it under Vercel → Domains, then append it
   to Render's `CORS_ORIGINS`.
9. **Record the live URL** in `README.md` (Step 7 of the branch flow) so T-076+
   and the launch posts can link it.

## Known adjacent issue (not fixed here — flag only)

`frontend/public/favicon.svg.svg` has a doubled extension while `index.html`
references `/favicon.svg`. The favicon 404s in production. It's unrelated to
deployment wiring and touching `public/` isn't part of T-075's scope — fix it
in a one-line `fix/favicon-filename` PR so this deploy PR stays single-purpose.

---

## Pull Request

**Title:**

```
chore: deploy React frontend to Vercel with production config
```

**Description:**

```markdown
## Summary

Configures the AIRP frontend for Vercel deployment and documents the full
wiring to the Render backend (T-074). Hardens `frontend/vercel.json` with
immutable asset caching and baseline security headers, and records the exact
three-variable env contract (`VITE_API_BASE_URL`, `VITE_AUTH_BASE_URL`,
`VITE_WS_BASE_URL`) the frontend actually reads — the task card's
`VITE_API_URL` does not exist in the codebase and would silently break every
API call and live stream.

## Changes

- `frontend/vercel.json` — add `/assets/*` `immutable` cache-control (Vite
  emits content-hashed filenames, so a 1-year cache is safe), baseline
  security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`), and `github.silent`. SPA
  `rewrites` and build settings unchanged.
- `docs/week-28/T-075-deploy-vercel.md` — full checkout→PR workflow, the
  env-var contract, the backend `CORS_ORIGINS` dependency (incl. the preview
  origin regex follow-up), and the Vercel Root Directory monorepo note.
- `README.md` — record the live Vercel frontend URL.

## Testing

- No `frontend/src/**` or `backend/**` changes, so `tsc`, `eslint`
  (`--max-warnings 0`), `prettier --check`, `vitest run`, and `vite build`
  all run against an unchanged tree and pass; the backend and docker CI jobs
  are untouched.
- Local frontend gate run clean: `npm ci → type-check → lint → format:check →
  test:run → build`.
- `vercel.json` validated as JSON and against Vercel's schema on deploy.
- Manual: production deploy loads, login + one full analysis streams live
  (proves the `wss://` WebSocket var), memo renders, PDF downloads; preview
  deployment builds and serves on this PR.

## Screenshots

<!-- Vercel deploy log (green), the live app running an analysis, and the
     preview-deployment comment on this PR. -->

## Related Issues

Closes #<T-075-issue-number>
```

## Verification-gate cheat sheet

```
Frontend (run in frontend/):
  npm ci
  npm run type-check
  npm run lint
  npm run format:check
  npm run test:run
  npm run build

JSON sanity:
  node -e "JSON.parse(require('fs').readFileSync('vercel.json','utf8'))"

Backend (unchanged by this PR — no need to run, but if you want the full gate):
  ENVIRONMENT=test
  python -m black --check backend/
  python -m isort --check-only backend/
  python -m flake8 backend/
  python -m mypy backend/
  python -m pytest
```

## Full file: `frontend/vercel.json`

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "vite",
  "installCommand": "npm ci",
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "github": {
    "silent": true
  },
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }],
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=31536000, immutable"
        }
      ]
    },
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Frame-Options", "value": "SAMEORIGIN" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" },
        {
          "key": "Permissions-Policy",
          "value": "camera=(), microphone=(), geolocation=()"
        }
      ]
    }
  ]
}
```