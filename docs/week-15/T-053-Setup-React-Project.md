# T-053 -- Setup React Project

**Phase:** 6 -- React Frontend
**Week:** 15
**Branch:** `feat/ui-setup`
**Task status:** Complete

---

## Overview

T-053 turns the placeholder `frontend/` scaffold (left from earlier phases
so T-049's WebSocket demo had a real consumer) into a fully wired,
production-grade React application and flips the frontend CI job from a
non-blocking placeholder into a hard gate.

After this task the app runs (`npm run dev`), builds (`npm run build`),
lints clean (`npm run lint`, `--max-warnings 0`), is Prettier-clean
(`npm run format:check`), type-checks under strict TypeScript
(`npm run type-check`), and has a Vercel deploy configuration.

**Acceptance criteria (all must pass):**
- `npm run dev` serves the app
- `npm run build` succeeds
- ESLint passes
- Vercel deployment configured

**In scope:** Vite + React 18 + TypeScript, Tailwind CSS design tokens,
React Query client + provider, React Router with a layout route and a
404, ESLint + Prettier wiring completed, Vercel config, and the CI
frontend gate.

**Explicitly out of scope** (separate Phase 6 tasks, per the master task
list):
- Design-system primitives (Button, Card, Badge, ...) -> later T-05x
- Landing page, auth pages, dashboard, live progress, debate viewer,
  results/memo pages, compare page -> T-054-T-066
- Any API client functions or real data fetching (only the React Query
  client and its provider are set up here; no queries are issued yet)
- A frontend unit-test runner (Vitest). The frontend CI job gates on
  type-check + lint + format + build, which is the T-053 contract; a test
  runner is introduced when there is component behaviour worth testing.

> **Note on dependencies:** every library this task uses
> (`@tanstack/react-query`, `react-router-dom`, `tailwindcss`,
> `autoprefixer`, `postcss`, `clsx`, `tailwind-merge`, ...) was already
> present in `frontend/package.json` and `frontend/package-lock.json`
> from the earlier scaffold. **No dependency was added**, so `npm ci`
> stays reproducible and the lockfile is untouched.

---

## What Was Built

### Build & tooling configuration

#### `frontend/postcss.config.js` (new)
PostCSS pipeline wiring Tailwind + Autoprefixer. ESM syntax because the
package is `"type": "module"`. Lives outside `src/`, so it is neither
linted nor Prettier-checked.

#### `frontend/tailwind.config.ts` (filled -- was an empty 0-byte file)
The design-token source of truth: `content` globs, and a `theme.extend`
defining the AIRP palette (`ink`, `canvas`, `surface`, `muted`, `line`,
the `brand` violet scale, and semantic `verdict.buy/hold/sell`), the type
stacks (`sans` Inter / `display` Fraunces / `mono` JetBrains Mono),
`rounded-card`, `shadow-card`, and `max-w-memo`. The `brand` violet is
chosen deliberately to match the "Frontend" layer colour in
`AIRP_Architecture.drawio`; `verdict` encodes the product's core
BUY/HOLD/SELL output as first-class colour. Type-checked by tsc (it is in
`tsconfig` `include`) but not linted/Prettier-checked.

#### `frontend/vercel.json` (new)
Vercel project config for the `frontend/` root: `framework: vite`,
`installCommand: npm ci`, `buildCommand: npm run build`,
`outputDirectory: dist`, and the SPA rewrite
(`/(.*) -> /index.html`) so client-side routes resolve on hard refresh.

#### `frontend/.gitignore`, `frontend/.prettierignore`, `frontend/.env.example` (new)
- `.gitignore` -- Vite-local artifacts (`dist`, `*.local`, `.vite`); the
  repo-root `.gitignore` already covers `node_modules/` and
  `frontend/dist/`.
- `.prettierignore` -- keeps Prettier off `dist`, `node_modules`,
  `package-lock.json`.
- `.env.example` -- documents `VITE_API_BASE_URL` (left blank in dev so
  the Vite proxy handles `/api`; set in Vercel for production).

#### `frontend/.eslintrc.cjs` (modified -- two additive changes)
- `settings."import/internal-regex": "^@/"` -- classifies `@/...` path
  aliases as the `internal` import group so `import/order` gives them
  their own block after external packages instead of mixing them in with
  `node_modules`.
- A new `overrides` entry for `*.d.ts` turning off
  `@typescript-eslint/triple-slash-reference` -- the
  `/// <reference types="vite/client" />` directive in `vite-env.d.ts` is
  the canonical Vite pattern and cannot be expressed as an `import`.

#### `frontend/index.html` (modified)
Adds the SVG favicon, `theme-color`, a meta description, and the Google
Fonts links for the three token typefaces.

#### `frontend/public/favicon.svg` (new)
Small AIRP monogram (violet "A" on the ink square) so dev/prod don't 404
on the favicon.

### Application source

#### `frontend/src/index.css` (new)
Tailwind's three layers plus a small `base` layer: `body` defaults to the
token background/text/font, a global `:focus-visible` ring (accessibility
floor), and a `prefers-reduced-motion` guard.

#### `frontend/src/vite-env.d.ts` (new)
Augments `ImportMetaEnv` with `VITE_API_BASE_URL` so `import.meta.env` is
typed rather than `any`.

#### `frontend/src/lib/cn.ts` (new)
`cn(...)` -- `clsx` + `tailwind-merge`, the class-composition helper every
later component uses so prop-driven Tailwind overrides win predictably.

#### `frontend/src/lib/queryClient.ts` (new)
The single shared `QueryClient` with defaults tuned for AIRP's
read-mostly data (short `staleTime`, low `retry`, `refetchOnWindowFocus`
off).

#### `frontend/src/config/env.ts` (new)
Typed, centralised `env` object. Everything reads `env.apiBaseUrl`
(default `/api/v1`) instead of touching `import.meta.env` directly.

#### `frontend/src/providers/AppProviders.tsx` (new)
Single composition point for app-wide providers:
`QueryClientProvider` (outermost) wrapping `BrowserRouter`. Exports only
the component (keeps `react-refresh/only-export-components` happy).

#### `frontend/src/routes/AppRoutes.tsx` (new)
The route table: one `RootLayout` route with a `HomePage` index and a
catch-all `NotFoundPage`. Phase 6 nests its real pages here.

#### `frontend/src/components/layout/RootLayout.tsx` (new)
The persistent shell (slim top bar + footer) wrapping routed pages via
`<Outlet />`.

#### `frontend/src/pages/HomePage.tsx`, `NotFoundPage.tsx` (new)
A small, on-brand home that confirms the stack is wired (and shows the
BUY/HOLD/SELL verdict palette as the signature element), and a directive
404.

#### `frontend/src/App.tsx`, `frontend/src/main.tsx` (replaced)
`App` now mounts `<AppRoutes />` only (providers live in
`AppProviders`). `main.tsx` imports `./index.css`, then renders
`<AppProviders><App /></AppProviders>` in `StrictMode`.

### CI

#### `.github/workflows/ci.yml` (modified)
- Removed `continue-on-error: true` from the `frontend` job -- it is now
  a hard gate (type-check, eslint, prettier `--check`, vite build).
- `ci-pass` now `needs: [backend, frontend]` and fails if either job is
  not `success`.

---

## How It Was Tested / Verified

Backend is untouched by this task, so the backend gate (black, isort,
flake8, mypy, pytest, coverage >= 85) is unaffected.

Frontend, from the `frontend/` directory:

```bash
cd frontend

# 1) Auto-fixers FIRST (writes import order + Prettier formatting).
#    This is the frontend equivalent of the backend's two-commit pattern.
npm run lint:fix
npm run format

# 2) Then the exact checks CI runs -- all must exit 0:
npm run type-check      # tsc --noEmit (strict)
npm run lint            # eslint, --max-warnings 0
npm run format:check    # prettier --check src/**
npm run build           # tsc && vite build

# 3) Manual smoke test:
npm run dev             # open http://localhost:3000 -> home renders,
                        # /nonexistent -> 404 page, "Back to home" works
```

> Run step 1 before committing. The pre-commit Prettier hook also
> rewrites files on commit (the established two-commit flow), but on
> Windows the hook shims can be blocked by App Control -- running
> `npm run format` / `npm run lint:fix` by hand guarantees the committed
> files are clean regardless, and the CI `*:check` jobs are the real gate.

---

## Git Workflow (exact commands)

```bash
# 0) Start from an up-to-date main
git checkout main
git pull origin main

# 1) Create the feature branch
git checkout -b feat/ui-setup

# 2) (do the work — files listed above)

# 3) Run auto-fixers, then verify (see "How It Was Tested" above)
cd frontend
npm ci                  # only if node_modules is stale
npm run lint:fix && npm run format
npm run type-check && npm run lint && npm run format:check && npm run build
cd ..

# 4) Stage and commit (re-stage after auto-fixers ran)
git add frontend/ .github/workflows/ci.yml docs/week-15/T-053-setup-react-project.md
git commit -m "feat(frontend): set up Vite + React 18 + TS + Tailwind app shell"

# If the pre-commit Prettier/ESLint hook reformats anything, re-stage and
# commit again (two-commit pattern):
#   git add -A && git commit -m "feat(frontend): set up Vite + React 18 + TS + Tailwind app shell"

# 5) Push and open the PR
git push -u origin feat/ui-setup
```

**Commit message:**
```
feat(frontend): set up Vite + React 18 + TS + Tailwind app shell
```

**PR title:**
```
feat(frontend): set up Vite + React 18 + TS + Tailwind app shell (T-053)
```

**PR description:**
```markdown
## Summary
Sets up the AIRP frontend as a production-grade Vite + React 18 +
TypeScript app: Tailwind design tokens, a shared React Query client,
React Router (layout route + 404), completed ESLint/Prettier wiring, and
a Vercel deploy config. Also flips the frontend CI job from a
non-blocking placeholder into a hard gate. No dependencies were added —
the lockfile is unchanged.

## Changes
- Add `postcss.config.js`; fill `tailwind.config.ts` with AIRP design
  tokens (palette, type, radius, shadow); add `src/index.css`
- Add React Query client (`src/lib/queryClient.ts`) + `AppProviders`,
  React Router routes (`AppRoutes`, `RootLayout`, `HomePage`,
  `NotFoundPage`)
- Add `src/lib/cn.ts`, `src/config/env.ts`, `src/vite-env.d.ts`
- Rework `App.tsx` / `main.tsx` to mount providers + routes + Tailwind CSS
- Add `vercel.json` (SPA rewrites), `.gitignore`, `.prettierignore`,
  `.env.example`, favicon, fonts in `index.html`
- ESLint: classify `@/` imports as internal; allow triple-slash in
  `*.d.ts`
- CI: remove `continue-on-error` from the frontend job; `ci-pass` now
  needs `[backend, frontend]`

## Testing
- [ ] Unit tests added / updated (n/a — setup task; no test runner yet)
- [x] Integration tests pass (backend untouched; backend gate unaffected)
- [x] Manual smoke test performed (`npm run dev`, home + 404 routes)

`npm run type-check`, `npm run lint`, `npm run format:check`, and
`npm run build` all pass locally; `npm run dev` serves the app.

## LangSmith Trace
n/a — no agent code touched.

## Screenshots
<paste terminal output of the four passing npm checks, and a screenshot
of the running home page>

## Related Issues
Closes #<issue-number>
```

---

## Notes for the Next Task

- `prettier-plugin-tailwindcss` is installed but intentionally **not**
  enabled in `.prettierrc.json` yet (no `plugins` field), so class order
  is not auto-sorted. If you want automatic Tailwind class sorting in
  Phase 6, add it to the Prettier `plugins` array in its own small
  chore PR and run `npm run format` once across `src/` so the bulk
  reformat lands in a single, reviewable commit.
- Standardise new imports on the `@/` alias (now the dedicated `internal`
  import group). The other aliases (`@components`, `@pages`, ...) still
  resolve via tsconfig/vite if you prefer them.
- Next: **T-054** (the design-system primitives / first real page, per
  the master task list).