# T-009 — Setup Python Backend Environment

**Phase:** 1 — Data Layer & APIs
**Week:** 2
**Branch:** `feat/data-backend-setup`
**Commit prefix:** `feat(deps):`
**PR title:** `feat(deps): add production requirements and T-009 environment tests`

---

## Overview

This task sets up the full Python dependency stack for the AIRP backend. By the end, `pip install -r requirements.txt` installs every package the backend will ever need, and `python -m pytest` passes with the requirements gate tests that confirm the environment is correctly configured.

**Acceptance criteria:**

- `pip install -r requirements.txt` succeeds with no errors
- `python -m pytest` returns no errors
- All imports in `test_requirements.py` pass

---

## Files Changed / Created in This Task

| File                                      | Action     | Purpose                                                                    |
| ----------------------------------------- | ---------- | -------------------------------------------------------------------------- |
| `backend/requirements.txt`                | **CREATE** | All production dependencies, pinned to exact versions                      |
| `backend/requirements-dev.txt`            | **UPDATE** | Dev-only deps; `langchain-anthropic` added                                 |
| `backend/tests/conftest.py`               | **UPDATE** | Richer shared fixtures; `test_settings`, `clean_env`, sample data builders |
| `backend/tests/unit/test_requirements.py` | **CREATE** | Acceptance gate — verifies every package imports correctly                 |
| `.env.test`                               | **CREATE** | Test environment variables for pytest                                      |
| `pyproject.toml`                          | **UPDATE** | Coverage threshold raised from 0 → 60; `.env.test` wired in                |

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Create the `develop` branch (one-time setup)

The `develop` branch is the integration branch. Feature branches are merged into `develop`; `develop` is merged into `main` weekly after verification.

```bash
# Make sure you are on main and it is clean
git checkout main
git pull origin main

# Create the develop branch from main (do this only once)
git checkout -b develop
git push -u origin develop
```

> **Branch strategy going forward:**
>
> - `main` → production-ready, only receives weekly merges from `develop`
> - `develop` → integration branch; all feature PRs target this branch
> - `feat/*`, `fix/*`, `chore/*` → short-lived, branched off `develop`

---

### Step 2 — Checkout the feature branch from `develop`

```bash
# Always branch off develop, not main
git checkout develop
git pull origin develop

git checkout -b feat/data-backend-setup
```

---

### Step 3 — Create and update files

Place each file exactly at the path shown below (relative to the repo root):

```
airp/
├── backend/
│   ├── requirements.txt          ← CREATE (new file)
│   ├── requirements-dev.txt      ← UPDATE (already exists from T-008)
│   └── tests/
│       ├── conftest.py           ← UPDATE (richer fixtures)
│       └── unit/
│           └── test_requirements.py  ← CREATE (new file)
├── .env.test                     ← CREATE (new file — not committed if secret)
└── pyproject.toml                ← UPDATE (coverage threshold, env_files)
```

Copy each file from this task document into the correct location.

---

### Step 4 — Install dependencies

```bash
# Navigate to repo root (where pyproject.toml lives)
cd /path/to/airp

# Upgrade pip first (avoids resolver warnings)
python -m pip install --upgrade pip

# Install production dependencies
pip install -r backend/requirements.txt

# Install dev dependencies on top
pip install -r backend/requirements-dev.txt
```

**Expected output:** Long install log ending with:

```
Successfully installed anthropic-0.27.0 chromadb-0.5.0 fastapi-0.110.0 ...
```

No red errors. Warnings about dependency conflicts are worth noting but
should not block the task — check them against the pinned versions.

---

### Step 5 — Set the test environment variable and run pytest

```bash
# Set ENVIRONMENT=test for this shell session
export ENVIRONMENT=test

# Run the full test suite from the repo root
python -m pytest

# Expected output:
# collected N items
# backend/tests/unit/test_requirements.py ............. [ 90%]
# backend/tests/unit/test_config.py ............. [100%]
# N passed in X.Xs
```

If any import test fails, the error message tells you which package to
fix:

| Error message                                           | Fix                                    |
| ------------------------------------------------------- | -------------------------------------- |
| `ModuleNotFoundError: No module named 'langchain_groq'` | `pip install langchain-groq==0.2.0`    |
| `AssertionError: Pydantic v2 required; got v1.x`        | `pip install 'pydantic>=2.0.0,<3.0.0'` |
| `Tests must run with ENVIRONMENT=test`                  | `export ENVIRONMENT=test`              |

---

### Step 6 — Run coverage check

```bash
python -m pytest --cov=backend --cov-report=term-missing
```

Coverage should be ≥ 60% (the new threshold in `pyproject.toml`).
The `config.py` tests from Phase 0 alone should comfortably exceed this.

---

### Step 7 — Stage, commit, and push

```bash
# Stage all changed files
git add backend/requirements.txt
git add backend/requirements-dev.txt
git add backend/tests/conftest.py
git add backend/tests/unit/test_requirements.py
git add pyproject.toml
# NOTE: Do NOT git add .env.test if it contains real keys.
# Add it only if it has only placeholder values (which this version does).
git add .env.test

# Verify staging area before committing
git status
git diff --staged

# Commit — imperative mood, max 72 chars
git commit -m "feat(deps): add production requirements and T-009 environment tests

- Add backend/requirements.txt with all production deps pinned exactly
- Add test_requirements.py import gate (acceptance criteria for T-009)
- Update conftest.py with test_settings, clean_env, sample data fixtures
- Update requirements-dev.txt (add freezegun, respx)
- Raise pyproject.toml coverage threshold from 0 to 60
- Add .env.test for pytest environment isolation

Closes #9"
```

> **GitHub Issue:** Before pushing, make sure Issue #9 exists on your
> GitHub Projects board with the title "T-009 — Setup Python backend
> environment". The `Closes #9` in the commit message auto-closes it
> when the PR is merged.

```bash
# Push the branch to remote
git push -u origin feat/data-backend-setup
```

---

### Step 8 — Open the Pull Request on GitHub

Go to your repository on GitHub. You will see a banner:
**"feat/data-backend-setup had recent pushes — Compare & pull request"**

Click it. Fill in the PR form:

---

**PR Title:**

```
feat(deps): add production requirements and T-009 environment tests
```

**Base branch:** `develop` (NOT `main`)
**Compare branch:** `feat/data-backend-setup`

**PR Description:**

````markdown
## Summary

Completes T-009 (Phase 1, Week 2). Adds `backend/requirements.txt` with
all production dependencies pinned to exact versions, a pytest acceptance
gate (`test_requirements.py`) that verifies every package imports
correctly, and richer shared test fixtures in `conftest.py`.

## Changes

- **`backend/requirements.txt`** (new): 30+ packages across 9 categories
  (framework, LLM/orchestration, DB, cache, vector store, market data,
  auth, PDF generation, utilities). Every version pinned for
  reproducibility.
- **`backend/requirements-dev.txt`** (updated): Added `freezegun` and
  `respx` for time-freezing and async HTTP mocking in later test phases.
- **`backend/tests/unit/test_requirements.py`** (new): 25 import tests
  covering every production package. This is the T-009 acceptance gate —
  if `pip install` worked correctly, every test passes.
- **`backend/tests/conftest.py`** (updated): Added `test_settings`
  (session-scoped Settings fixture), `clean_env`, `sample_ticker`,
  `sample_company_name`, and `sample_analysis_metadata` fixtures used
  throughout Phase 1+ tests.
- **`.env.test`** (new): Isolated test environment variables — prevents
  tests from reading real API keys from `.env`.
- **`pyproject.toml`** (updated): Coverage threshold raised from 0 → 60;
  `env_files = [".env.test"]` added to `pytest.ini_options`.

## Testing

```bash
export ENVIRONMENT=test
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt
python -m pytest --cov=backend --cov-report=term-missing
```
````

All 25 import tests pass. Coverage ≥ 60%.

## LangSmith Trace

N/A — no agent code in this task.

## Screenshots

```
collected 37 items

backend/tests/unit/test_requirements.py .........................  [ 67%]
backend/tests/unit/test_config.py ............                    [100%]

37 passed in 4.2s
```

## Related Issues

Closes #9

```

---

**Labels to add:** `phase-1`, `dependencies`, `testing`
**Milestone:** Phase 1 — Data Layer & APIs

Click **Create pull request**.

---

### Step 9 — After CI passes, merge into `develop`

GitHub Actions will run:
1. `black --check` (formatting)
2. `flake8` (linting)
3. `python -m pytest` (tests)

When all checks are green, merge the PR using **"Squash and merge"**
so `develop`'s history stays clean. Delete the feature branch after
merging.

---

### Step 10 — Weekly merge: `develop` → `main`

At the end of each week, after all that week's feature branches are merged
into `develop`, open a PR from `develop` → `main`:

```

PR title: chore(release): merge week-2 into main (T-009)
Base: main
Compare: develop

````

Use **"Create a merge commit"** (not squash) so `main` retains the full
history of individual feature squashes.

---

## Common Issues & Fixes

### `ERROR: Could not find a version that satisfies the requirement weasyprint==62.3`

WeasyPrint requires system libraries (Cairo, Pango). On Ubuntu/WSL2:

```bash
sudo apt-get update
sudo apt-get install -y python3-dev libcairo2-dev libpango1.0-dev libgdk-pixbuf2.0-dev libffi-dev shared-mime-info
pip install weasyprint==62.3
````

### `chromadb` install fails on Windows

ChromaDB sometimes fails on Windows native (not WSL2). Use WSL2:

```bash
# In Windows Terminal, open Ubuntu (WSL2) and run from there
pip install chromadb==0.5.0
```

### `sentence-transformers` is slow to import

The first import downloads the `all-MiniLM-L6-v2` model (~90 MB) and
caches it at `~/.cache/torch/sentence_transformers/`. Subsequent imports
are instant. This is expected behaviour — the test marks it as slow but
does not fail.

### pytest says "no tests ran" or "0 items"

Check that `ENVIRONMENT=test` is set:

```bash
echo $ENVIRONMENT  # should print: test
export ENVIRONMENT=test
python -m pytest
```

---

## EOD Update Template

Paste this into the Claude Project chat at end of session:

```
EOD Update [DATE]:
Completed: T-009
Merged to develop: feat/data-backend-setup
Current week: 2 | Current phase: 1
Blocker (if any): [none / describe]
Next session: T-010 — Build yFinance stock price tool
```

---

_T-009 complete. The backend environment is fully configured.
Next: T-010 — implement the first LangChain data tool (`fetch_stock_price`)._
