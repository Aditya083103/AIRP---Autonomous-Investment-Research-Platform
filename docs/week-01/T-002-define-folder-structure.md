# T-002 — Define Folder Structure

| Field | Detail |
|-------|--------|
| **Task ID** | T-002 |
| **Phase** | 0 — Project Setup & Standards |
| **Week** | 1 |
| **Branch** | `setup/folder-structure` |
| **Status** | ✅ Completed |
| **Merged into** | `main` |

---

## Objective

Establish the complete AIRP monorepo folder structure as defined in the project
overview (Section 9). Every folder must be tracked by Git — either with a
`README.md` stub explaining what belongs there, or a `.gitkeep` placeholder for
folders that will be populated in later phases.

---

## Acceptance Criteria

| Criteria | Status |
|----------|--------|
| All folders present per project spec | ✅ |
| Each folder has a `.gitkeep` or README stub | ✅ |
| README stubs describe what each folder contains | ✅ |
| pre-commit hooks pass cleanly | ✅ |
| PR merged via squash and merge | ✅ |

---

## Folder Structure Created

```
airp/
├── backend/
│   ├── agents/         README.md — 8 agent files, added Phase 2 & 4
│   ├── graph/          README.md — LangGraph StateGraph + routing
│   ├── routers/        README.md — FastAPI route handlers
│   ├── models/         README.md — SQLAlchemy ORM + Pydantic schemas
│   ├── services/       README.md — Business logic layer
│   ├── tools/          README.md — LangChain tool definitions
│   ├── db/             README.md — PostgreSQL, ChromaDB, Redis clients
│   └── tests/
│       ├── unit/       .gitkeep — fast mocked tests (Phase 1+)
│       └── integration/ .gitkeep — real API tests (Phase 1+)
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── ui/     README.md — primitive components
│       │   ├── layout/ README.md — structural components
│       │   └── charts/ README.md — Recharts wrappers
│       ├── pages/      README.md — page-level components
│       ├── hooks/      README.md — custom React hooks
│       ├── api/        README.md — API client functions
│       └── types/      README.md — TypeScript type definitions
├── docs/
│   ├── dev-log/        This folder — task-by-task development journal
│   └── *.md            Architecture, Agents, APIs, Coding Standards stubs
└── scripts/            README.md — dev utility scripts
```

---

## Files Created

| File | Type | Purpose |
|------|------|---------|
| `backend/agents/README.md` | README stub | Documents all 8 agent files and their structure |
| `backend/graph/README.md` | README stub | Documents LangGraph state and routing files |
| `backend/routers/README.md` | README stub | Documents all FastAPI route handlers |
| `backend/models/README.md` | README stub | Documents ORM models and Pydantic schemas |
| `backend/services/README.md` | README stub | Documents business logic layer |
| `backend/tools/README.md` | README stub | Documents LangChain tool definitions per data source |
| `backend/db/README.md` | README stub | Documents database client files |
| `backend/tests/README.md` | README stub | Documents test structure and how to run tests |
| `backend/tests/unit/.gitkeep` | Placeholder | Tracks empty folder until Phase 1 tests are added |
| `backend/tests/integration/.gitkeep` | Placeholder | Tracks empty folder until Phase 1 tests are added |
| `frontend/src/components/README.md` | README stub | Documents component sub-folder structure |
| `frontend/src/components/ui/README.md` | README stub | Primitive UI components |
| `frontend/src/components/layout/README.md` | README stub | Structural layout components |
| `frontend/src/components/charts/README.md` | README stub | Recharts data visualisation components |
| `frontend/src/pages/README.md` | README stub | All page routes documented |
| `frontend/src/hooks/README.md` | README stub | Custom React hooks documented |
| `frontend/src/api/README.md` | README stub | API client functions documented |
| `frontend/src/types/README.md` | README stub | TypeScript types documented |
| `frontend/public/README.md` | README stub | Static assets folder |
| `scripts/README.md` | README stub | Dev utility scripts |
| `docs/CODING_STANDARDS.md` | Updated stub | Branch naming, commit format, file naming conventions |
| `docs/AGENTS.md` | Updated stub | Agent committee table with phase timeline |
| `docs/APIS.md` | Updated stub | All external APIs with free limits and env var names |
| `docs/ARCHITECTURE.md` | Updated stub | System layer overview |

---

## Problems Encountered & Solutions

### 1. Uncommitted changes in source control before starting
**Problem:** After copying files from T-001, source control showed modified files
before the T-002 branch was even created. This was caused by the `end-of-file-fixer`
hook from T-001 modifying files after staging but before the commit completed —
leaving auto-fixed versions unstaged.

**Solution:** Always run `git add .` followed by a second `git commit` after
seeing `"files were modified by this hook"`. The two-attempt pattern is normal
pre-commit behaviour.

### 2. `end-of-file-fixer` aborting the T-002 commit
**Problem:** Same as above — 7 README stubs were missing trailing newlines,
causing the first commit attempt to abort.

**Solution:** Ran `git add .` and `git commit` a second time with the same
message. All hooks passed on the second attempt.

### 3. LF/CRLF line ending warnings on Windows
**Problem:** Git warned about LF being replaced by CRLF on multiple files.
While harmless, it creates noise in every `git add` output.

**Solution:** Set the global Git config once:
```bash
git config --global core.autocrlf true
```
This tells Git to automatically convert LF to CRLF on checkout (Windows) and
back to LF on commit — the correct setting for Windows developers working on
a cross-platform project.

---

## Key Decisions

**Why README stubs instead of `.gitkeep` everywhere?**
Every folder's README explains *what belongs there*, *when it gets populated*,
and *what naming conventions to follow*. This means any engineer (or future-you
returning after a break) can navigate the repo without needing external context.
`.gitkeep` is used only for the `tests/unit/` and `tests/integration/` folders
where a README in the parent `tests/` already explains the structure.

**Why a `dev-log/` folder inside `docs/`?**
A task-by-task development log serves three purposes:
1. Documents decisions and problems encountered for future reference
2. Demonstrates engineering discipline to recruiters reviewing the repo
3. Provides context for AI coding sessions — paste the relevant task log
   to resume with full context after any break

**Branching strategy decision made during this task:**
Decided to merge Phase 0 tasks (T-001 to T-008) directly into `main`, and
introduce a `develop` branch at the start of Phase 1 (T-009). From Phase 1
onwards, all feature branches will merge into `develop` first, with
`develop → main` merges happening once per phase when everything is stable.

---

## Learnings

- The `squash and merge` strategy on GitHub is the right default for solo
  projects — it keeps `git log` on `main` readable as one commit per task.
- Empty folders cannot be tracked by Git. Every folder needs at least one
  tracked file. README stubs are preferable to `.gitkeep` wherever meaningful
  documentation can be added.
- The two-commit pattern with pre-commit hooks (`commit → hooks fix files →
  add → commit again`) will happen frequently. It is not an error — it is the
  hooks doing their job.
