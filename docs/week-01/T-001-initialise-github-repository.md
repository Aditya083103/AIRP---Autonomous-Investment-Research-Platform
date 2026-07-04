# T-001 — Initialise GitHub Repository

| Field           | Detail                        |
| --------------- | ----------------------------- |
| **Task ID**     | T-001                         |
| **Phase**       | 0 — Project Setup & Standards |
| **Week**        | 1                             |
| **Branch**      | `setup/init-repo`             |
| **Status**      | ✅ Completed                  |
| **Merged into** | `main`                        |

---

## Objective

Create the GitHub repository for the AIRP monorepo with a production-grade
`.gitignore`, CI pipeline, pre-commit hooks, and the correct folder skeleton —
so that every subsequent task has a clean, standards-enforced foundation to
build on.

---

## Acceptance Criteria

| Criteria                            | Status |
| ----------------------------------- | ------ |
| Repo visible on GitHub              | ✅     |
| `.gitignore` ignores `.env`         | ✅     |
| `.gitignore` ignores `__pycache__`  | ✅     |
| `.gitignore` ignores `node_modules` | ✅     |
| `.gitignore` ignores `dist`         | ✅     |
| CI pipeline wired up and running    | ✅     |
| pre-commit hooks installed locally  | ✅     |

---

## Files Created

| File                               | Purpose                                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `.gitignore`                       | Excludes secrets, build artefacts, caches, IDE files, ChromaDB local storage                            |
| `.env.example`                     | Template for all 15 environment variables with descriptions — safe to commit                            |
| `.github/workflows/ci.yml`         | GitHub Actions: black + flake8 + mypy + pytest (backend), tsc + eslint + build (frontend) on every push |
| `.github/PULL_REQUEST_TEMPLATE.md` | Enforces Summary, Changes, Testing, LangSmith Trace, Screenshots, Related Issues on every PR            |
| `.pre-commit-config.yaml`          | black → isort → flake8 → mypy + trailing whitespace + YAML check + detect-private-key                   |
| `pyproject.toml`                   | Central config for black, isort, mypy, pytest, and coverage thresholds                                  |
| `docker-compose.yml`               | One-command local stack: FastAPI + PostgreSQL 16 + Redis 7 + ChromaDB + React                           |
| `README.md`                        | Project overview, tech stack table, quick-start guide, phase tracker                                    |
| `backend/**/__init__.py`           | All 9 backend packages initialised                                                                      |
| `docs/*.md`                        | Stub files for all 8 documentation pages                                                                |

---

## Problems Encountered & Solutions

### 1. `pre-commit: command not found` on Windows

**Problem:** `pip install pre-commit` succeeded but the `pre-commit` executable
was not on the Windows PATH.

**Solution:** Use the module syntax instead:

```bash
python -m pre_commit install
python -m pre_commit run --all-files
```

### 2. CI pipeline failing with red ❌ on first push

**Problem:** The CI workflow referenced `requirements.txt` and `requirements-dev.txt`
which don't exist yet (they are created in Phase 1).

**Solution:** Rewrote the CI to be phase-aware — each step checks whether the
relevant file exists before running, and skips gracefully with a log message if not.
The CI will become progressively stricter as dependencies are added in later phases.

### 3. `end-of-file-fixer` aborts first commit

**Problem:** pre-commit's `end-of-file-fixer` hook adds a trailing newline to files
that are missing one, which modifies files after staging — causing the commit to abort.

**Solution:** This is expected pre-commit behaviour. The fix is to always run
`git add .` and re-commit after seeing `"files were modified by this hook"`.

---

## Key Decisions

**Why phase-aware CI over a strict CI from day one?**
A CI that fails on every push because `requirements.txt` doesn't exist yet would
be noise, not signal. The CI grows stricter automatically as each phase adds the
files it checks for. This mirrors how real projects bootstrap their pipelines.

**Why `squash and merge` for all PRs?**
Each task produces one logical change. Squash merge means `git log` on `main`
reads as one line per task — clean, navigable, and professional.

---

## Learnings

- Pre-commit hooks follow a two-attempt pattern on Windows: first commit triggers
  auto-fixes, second commit succeeds. This is by design.
- GitHub Actions for public repos gets 2,000 free CI minutes per month —
  more than enough for the entire 24-week project.
- The `detect-private-key` hook is a critical safety net — it blocks any commit
  containing what looks like a private key or API token.
