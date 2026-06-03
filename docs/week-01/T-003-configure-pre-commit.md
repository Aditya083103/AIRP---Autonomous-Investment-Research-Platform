# T-003 — Configure Pre-commit Hooks

| Field | Detail |
|-------|--------|
| **Task ID** | T-003 |
| **Phase** | 0 — Project Setup & Standards |
| **Week** | 1 |
| **Branch** | `setup/pre-commit` |
| **Status** | ✅ Completed |
| **Merged into** | `main` |

---

## Objective

Install and configure pre-commit to enforce code quality automatically on every
`git commit`. Covers the full toolchain for both the Python backend (black,
isort, flake8, mypy) and the TypeScript frontend (eslint, prettier), plus
general repo hygiene hooks.

---

## Acceptance Criteria

| Criteria | Status |
|----------|--------|
| `pre-commit run --all-files` passes with zero errors | ✅ |
| black enforces line length 88 on all backend Python files | ✅ |
| isort sorts imports with black-compatible profile | ✅ |
| flake8 lints with bugbear + comprehensions plugins | ✅ |
| mypy runs in strict mode on backend | ✅ |
| ESLint runs on all `frontend/src/**/*.{ts,tsx}` files | ✅ |
| Prettier formats TS/TSX/JSON/CSS/MD files in frontend | ✅ |
| General hygiene hooks active (trailing whitespace, EOF, YAML, merge conflict detection) | ✅ |
| PR merged via squash and merge | ✅ |

---

## Files Created / Modified

| File | Action | Purpose |
|------|--------|---------|
| `.pre-commit-config.yaml` | Modified | Added ESLint + Prettier hooks for frontend; added `check-toml`, `check-added-large-files`, `mixed-line-ending` hygiene hooks |
| `.flake8` | Created | flake8 config at repo root — flake8 cannot read `pyproject.toml` natively; sets `max-line-length = 88` to match black; ignores E203/W503 (black conflicts) |
| `pyproject.toml` | Modified | Added `[[tool.mypy.overrides]]` blocks — relaxed strict checks for test files; silenced missing stubs for `chromadb`, `yfinance`, `weasyprint` |
| `backend/requirements-dev.txt` | Created | All dev-only Python dependencies: pre-commit, black, isort, flake8 + plugins, mypy, pytest stack, httpx |
| `backend/__init__.py` | Created | Makes `backend` a proper Python package so mypy resolves it correctly |
| `backend/py.typed` | Created | PEP 561 marker — tells mypy this package ships inline type annotations |
| `backend/tests/__init__.py` | Created | Makes `tests` a package; required for pytest discovery |
| `frontend/package.json` | Created | Full dependency list with `lint`, `lint:fix`, `format`, `format:check`, `type-check` npm scripts |
| `frontend/.eslintrc.cjs` | Created | Strict TypeScript + React rules; `@typescript-eslint/recommended-requiring-type-checking`; `import/order` with alphabetised groups; `prettier` last to disable conflicts |
| `frontend/.prettierrc.json` | Created | `printWidth: 100`, LF endings, trailing commas everywhere, `prettier-plugin-tailwindcss` for class sorting |
| `frontend/.prettierignore` | Created | Excludes `dist/`, `node_modules/` from Prettier |
| `frontend/tsconfig.json` | Created | `strict: true`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, path aliases (`@/*`, `@components/*`, etc.) — no `baseUrl` (not needed with `moduleResolution: bundler`) |
| `frontend/vite.config.ts` | Created | React plugin, ESM-compatible path aliases via `fileURLToPath + import.meta.url`, dev proxy to FastAPI on `:8000` |
| `frontend/tailwind.config.ts` | Created | Content paths for class purging; brand/buy/hold/sell colour tokens |
| `frontend/postcss.config.js` | Created | Tailwind + autoprefixer plugins; required by Vite |
| `frontend/index.html` | Created | HTML entry point required by Vite |
| `frontend/src/main.tsx` | Created | Minimal React entry point that passes strict ESLint and TypeScript cleanly |
| `frontend/src/App.tsx` | Created | Placeholder component; satisfies ESLint `react-refresh/only-export-components` |
| `frontend/src/index.css` | Created | Tailwind `@base`, `@components`, `@utilities` directives |
| `docs/CODING_STANDARDS.md` | Replaced stub | Complete reference: Python toolchain, TypeScript toolchain, branch naming, commit format, PR process, CI checks table |

---

## Problems Encountered & Solutions

### 1. `pre-commit` not recognised on Windows
**Problem:** Running `pre-commit install` returned:
```
'pre-commit' is not recognized as an internal or external command
```
**Solution:** `pre-commit` is a Python package and must be installed inside an
activated virtual environment. The fix was:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements-dev.txt
pre-commit install
```
The venv only applies to the Python/backend side. The frontend uses Node and
`npm install` — no activation needed there.

### 2. `tsconfig.json` error with `baseUrl`
**Problem:** TypeScript errored on `"baseUrl": "."` when combined with
`"moduleResolution": "bundler"` and `"allowImportingTsExtensions": true`.
With the `bundler` resolution strategy, `baseUrl` is redundant — Vite handles
all path resolution, not `tsc`.

**Solution:** Removed `"baseUrl"` entirely. Updated `paths` entries to use
explicit relative prefixes (`"./src/*"` instead of `"src/*"`), which is
required when `baseUrl` is absent.

### 3. `vite.config.ts` — `__dirname` is undefined in ESM
**Problem:** The original config used:
```typescript
import path from "path";
alias: { "@": path.resolve(__dirname, "./src") }
```
This fails because the project uses `"type": "module"` in `package.json`,
making all files ES modules. `__dirname` is a CommonJS global — it does not
exist in ESM and TypeScript correctly errors on it.

**Solution:** Replaced with the ESM-native pattern:
```typescript
import { fileURLToPath, URL } from "node:url";
alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) }
```
`import.meta.url` is the ESM equivalent of `__filename`, and `fileURLToPath`
converts it to an absolute filesystem path. This works correctly on both
Windows and Unix.

### 4. Two-commit pattern with pre-commit hooks
**Problem:** First `git commit` attempt was aborted — black auto-formatted
several files and prettier reformatted `index.html` and `App.tsx`. Git
reported: `"files were modified by this hook"`.

**Solution:** Same pattern as T-002:
```bash
git add .
git commit -m "..."   # first attempt — hooks fix files, commit aborts
git add .             # re-stage the auto-fixed files
git commit -m "..."   # second attempt — all hooks pass
```
This is expected pre-commit behaviour, not an error.

---

## Key Decisions

**Why does `.flake8` exist at the root when `pyproject.toml` is already there?**
flake8 (as of v7.x) does not natively read `pyproject.toml`. It only reads
`setup.cfg`, `tox.ini`, or `.flake8`. Putting flake8 config in `pyproject.toml`
under `[tool.flake8]` silently does nothing — the config is ignored and flake8
falls back to its defaults. The `.flake8` file at the root is the correct and
only reliable home for flake8 configuration.

**Why `eslint-config-prettier` as the last extend?**
ESLint and Prettier overlap on formatting rules (indentation, quotes, trailing
commas, etc.). Without `eslint-config-prettier`, ESLint would flag code that
Prettier has already correctly formatted, causing an irreconcilable conflict.
Extending `"prettier"` last disables all ESLint rules that Prettier owns,
leaving ESLint responsible only for code quality (not style).

**Why `.eslintrc.cjs` instead of `.eslintrc.json` or `eslint.config.js`?**
The project uses `"type": "module"` in `package.json`, which makes all `.js`
files ES modules by default. ESLint v8 still loads config files as CommonJS
internally. Using `.cjs` explicitly marks the file as CommonJS, preventing
the `require is not defined` error that occurs with a plain `.eslintrc.js`
in an ESM project. ESLint v9's flat config (`eslint.config.js`) would resolve
this differently, but v8 is used here for ecosystem stability.

**Why `fileURLToPath` instead of `path.resolve` in `vite.config.ts`?**
`path.resolve(__dirname, ...)` is the CommonJS pattern. Since the project is
ESM (`"type": "module"`), `__dirname` is undefined. `fileURLToPath(new URL("./src",
import.meta.url))` is the idiomatic ESM replacement — it produces the same
absolute path, works on both Windows and Unix, and satisfies TypeScript's
strict mode without requiring `@types/node` workarounds.

**Why `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` in tsconfig?**
These are the two most commonly disabled strict flags because they require more
defensive code. They are enabled here deliberately:
- `noUncheckedIndexedAccess` — array access `items[0]` returns `T | undefined`,
  not `T`. This prevents runtime crashes when accessing out-of-bound indices,
  which is especially relevant for agent output arrays where the LLM could
  return fewer items than expected.
- `exactOptionalPropertyTypes` — `{ key?: string }` means the property can be
  absent, but if present it must be `string` (not `string | undefined`). This
  maps more accurately to how Pydantic's optional fields behave on the backend.

---

## Learnings

- The venv is Python-only. Frontend (Node/npm) is a completely separate
  ecosystem — never activate a venv for frontend work.
- `pre-commit run --all-files` is the acceptance criteria for tooling tasks,
  not running the actual application. The app has nothing to run yet.
- `__dirname` does not exist in ESM. Anytime you see `path.resolve(__dirname, ...)`
  in a modern TypeScript/Vite project, it needs replacing with
  `fileURLToPath(new URL(..., import.meta.url))`.
- flake8 silently ignores `[tool.flake8]` in `pyproject.toml`. Always use `.flake8`.
- The two-commit pattern after pre-commit hook auto-fixes is normal — not a bug.
  Build the habit: if a commit aborts with "files were modified by this hook",
  the response is always `git add . && git commit` again.
