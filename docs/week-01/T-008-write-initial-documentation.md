# T-008 — Write Initial Documentation

| Field             | Detail                                                                                 |
| ----------------- | -------------------------------------------------------------------------------------- |
| **Task ID**       | T-008                                                                                  |
| **Phase**         | 0 — Project Setup & Standards                                                          |
| **Week**          | 1                                                                                      |
| **Branch**        | `setup/docs`                                                                           |
| **Commit prefix** | `docs: add initial project documentation`                                              |
| **PR Title**      | `docs: add architecture, contributing, and coding standards docs`                      |
| **Priority**      | 🟡 High                                                                                |
| **Est. Hours**    | 3                                                                                      |
| **Status**        | 🔲 To Do → ✅ Complete                                                                 |
| **Depends on**    | T-001 (repo), T-002 (folder structure), T-005 (.env.example), T-006 (APIS.md scaffold) |

---

## Objective

Create the four foundational documentation files that every contributor
(or recruiter reading the repo) needs to understand the system and the
development process. These docs must be filled with real content — not
placeholder stubs — so that the repository looks production-grade from
the first commit onwards.

Two of the four docs (`CODING_STANDARDS.md` and `APIS.md`) already exist
from earlier tasks (T-003 and T-006). This task creates the two missing ones
(`ARCHITECTURE.md` and `CONTRIBUTING.md`) and links all four from the README.

---

## Acceptance Criteria

| Criteria                                                                          | Status |
| --------------------------------------------------------------------------------- | ------ |
| `docs/ARCHITECTURE.md` exists and contains full system architecture               | 🔲     |
| `docs/CONTRIBUTING.md` exists and covers setup, workflow, branching, PRs, testing | 🔲     |
| `docs/CODING_STANDARDS.md` exists (already written in T-003)                      | ✅     |
| `docs/APIS.md` exists (already written in T-006)                                  | ✅     |
| All four docs are linked from `README.md` Documentation table                     | 🔲     |
| `README.md` Phase 0 status updated to ✅ Complete                                 | 🔲     |
| Task doc (`T-008-write-initial-documentation.md`) created in `docs/week-01/`      | 🔲     |
| PR merged via squash and merge; closes the T-008 issue                            | 🔲     |

---

## Files Produced by This Task

| File                                                | Action     | Description                                                                                                               |
| --------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| `docs/ARCHITECTURE.md`                              | **CREATE** | Full system architecture — 5 layers, 8 agents, request flow, InvestmentState design, debate engine, deployment            |
| `docs/CONTRIBUTING.md`                              | **CREATE** | Prerequisites, Docker setup, manual setup, workflow, branching, commits, PRs, testing, agent conventions, troubleshooting |
| `README.md`                                         | **UPDATE** | Add `CONTRIBUTING.md` to docs table; update Phase 0 status to ✅ Complete                                                 |
| `docs/week-01/T-008-write-initial-documentation.md` | **CREATE** | This file                                                                                                                 |

`docs/CODING_STANDARDS.md` and `docs/APIS.md` are **not modified** — they were
completed in T-003 and T-006 respectively and are already production-quality.

---

## Complete Step-by-Step Execution

### Step 1 — Checkout the branch from main

```bash
# Ensure main is clean and up to date
git checkout main
git pull origin main

# Create the task branch
git checkout -b setup/docs

# Verify
git branch
# Expected: * setup/docs
```

---

### Step 2 — Create `docs/ARCHITECTURE.md`

Create the file at `docs/ARCHITECTURE.md`.

The file must cover:

- **Architecture overview** — ASCII diagram of the 5 layers with technology labels
- **Layer 1 — Frontend** — component list, technology choices with rationale, state management strategy
- **Layer 2 — Backend API** — route structure table, FastAPI project structure, background task pattern, WebSocket streaming pattern
- **Layer 3 — Agent Orchestration** — why LangGraph over plain LangChain, the 8-agent committee table, pipeline execution flow diagram, conditional routing, state persistence
- **Layer 4 — Data & Storage** — PostgreSQL tables, ChromaDB collections, Redis cache key patterns and TTLs, market data API summary
- **Layer 5 — Observability & DevOps** — LangSmith tracing config, GitHub Actions CI checks, Docker services
- **Request flow** — numbered end-to-end trace from browser click to PDF download (14 steps)
- **InvestmentState** — complete TypedDict definition with field groupings
- **The Debate Engine** — how rounds work, termination condition, Portfolio Manager authority
- **Key design decisions** — why Claude, why multi-agent, why Pydantic v2, why PostgreSQL for state, why Redis for WebSocket events
- **Deployment architecture** — ASCII diagram of Vercel → Render → Neon/Redis/ChromaDB/Claude, environment variable table

> The full content is in the file created by this task. Copy it exactly.

---

### Step 3 — Create `docs/CONTRIBUTING.md`

Create the file at `docs/CONTRIBUTING.md`.

The file must cover:

- **Prerequisites** — Python 3.11, Node 20 LTS, Git, Docker with version check commands
- **Local setup (Docker)** — `docker compose up`, separate `npm run dev`
- **Local setup (manual)** — venv, pip install, pre-commit install, alembic, uvicorn
- **Verify setup** — health check curl, API docs URL, pytest run
- **Environment configuration** — `.env` handling, CI secrets, integration test keys
- **Development workflow** — numbered 10-step process from reading the task to merging
- **Branch strategy** — full table of patterns with examples and rules
- **Commit message format** — type/scope table, examples of good vs bad commits
- **Pull request process** — opening, description template, checklist, merge strategy (squash only)
- **Code quality gates** — pre-commit (local) and CI (remote) with pass conditions per check
- **Testing strategy** — test pyramid, unit test conventions, integration test conventions, fixtures
- **Working with agents** — adding a new agent checklist, prompt conventions, LangSmith tagging pattern
- **Troubleshooting** — pre-commit failures, mypy errors, pytest import errors, Docker DB issues, Redis errors, ChromaDB not found

> The full content is in the file created by this task. Copy it exactly.

---

### Step 4 — Update `README.md`

Two changes to `README.md`:

**Change 1 — Documentation table** (add CONTRIBUTING.md row):

```markdown
## Documentation

| Doc                                             | Contents                                                                        |
| ----------------------------------------------- | ------------------------------------------------------------------------------- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md)         | Full system architecture — layers, request flow, state design, design decisions |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md)         | Local setup, branch strategy, commit format, PR process, testing guide          |
| [CODING_STANDARDS.md](docs/CODING_STANDARDS.md) | Naming conventions, linting rules, pre-commit setup, CI checks                  |
| [AGENTS.md](docs/AGENTS.md)                     | Each agent's persona, tools, output schema, example output                      |
| [APIS.md](docs/APIS.md)                         | External APIs, free tier limits, env variable names, rate limit strategy        |
```

**Change 2 — Status table** (Phase 0 → ✅ Complete):

```markdown
| 0 | Project Setup & Standards | ✅ Complete |
```

---

### Step 5 — Create this task documentation file

Create `docs/week-01/T-008-write-initial-documentation.md` (the file you are reading).

---

### Step 6 — Run pre-commit

Documentation files only — no Python or TypeScript changed.
pre-commit will run `prettier` on the Markdown files if configured.

```bash
pre-commit run --all-files
```

Expected output: all checks passed (or only whitespace/trailing-newline
fixes which pre-commit auto-applies).

---

### Step 7 — Commit

```bash
git add docs/ARCHITECTURE.md
git add docs/CONTRIBUTING.md
git add docs/week-01/T-008-write-initial-documentation.md
git add README.md

git status
# Verify: only the four files above are staged

git commit -m "docs: add architecture, contributing, and coding standards docs

- Add docs/ARCHITECTURE.md: full 5-layer system architecture, 8-agent
  committee, end-to-end request flow, InvestmentState design, debate
  engine mechanics, key design decisions, deployment diagram
- Add docs/CONTRIBUTING.md: prerequisites, Docker and manual setup,
  10-step dev workflow, branch strategy, commit format, PR process,
  test pyramid, agent conventions, troubleshooting guide
- Update README.md: add CONTRIBUTING.md to documentation table;
  update Phase 0 status to Complete
- Add T-008 task doc to docs/week-01/

Closes #8"
```

---

### Step 8 — Push and open the Pull Request

```bash
git push origin setup/docs
```

Open a PR on GitHub with the following details.

---

## Pull Request

### Title

```
docs: add architecture, contributing, and coding standards docs
```

### Description

```markdown
## Summary

Creates the two missing foundational documentation files for AIRP:
`ARCHITECTURE.md` (full 5-layer system design, agent pipeline, request flow,
InvestmentState schema, debate engine, deployment) and `CONTRIBUTING.md`
(local setup, development workflow, branching, commits, PRs, testing, agent
conventions, troubleshooting). Updates the README documentation table and
marks Phase 0 as complete.

## Changes

- `docs/ARCHITECTURE.md` — created (new file, ~400 lines)
  - 5-layer architecture overview with ASCII diagram
  - 8-agent investment committee table with tools and output types
  - Pipeline execution flow diagram (Planner → parallel research → debate → decision)
  - Complete InvestmentState TypedDict definition
  - 14-step end-to-end request flow trace
  - Debate engine mechanics and Portfolio Manager authority
  - Key design decisions with rationale (Claude, multi-agent, Pydantic v2, Redis pub/sub)
  - Deployment architecture with environment variable table

- `docs/CONTRIBUTING.md` — created (new file, ~350 lines)
  - Prerequisites table with version check commands
  - Docker setup (one command) and manual setup (step by step)
  - 10-step development workflow
  - Branch naming strategy table
  - Commit message format with good/bad examples
  - PR description template and pre-merge checklist
  - Code quality gates (pre-commit and CI) with pass conditions
  - Test pyramid and unit/integration test conventions
  - New agent checklist and LangSmith tagging pattern
  - Troubleshooting section for 6 common failure modes

- `README.md` — updated
  - Added CONTRIBUTING.md row to Documentation table with description
  - Updated Phase 0 status from 🟡 In progress to ✅ Complete

- `docs/week-01/T-008-write-initial-documentation.md` — created (this doc)

## Testing

Documentation-only PR — no source code changed. CI passes because:

- No Python files modified (black, isort, flake8, mypy, pytest not affected)
- No TypeScript files modified (tsc, eslint, vite build not affected)
- pre-commit Markdown checks pass

## LangSmith Trace

N/A — no agent code in this PR.

## Screenshots

N/A — documentation files; review by reading the rendered Markdown on GitHub.

## Related Issues

Closes #8
```

### Merge strategy

Squash and merge. Delete branch after merge.

---

## Post-Merge Checklist

After the PR is merged:

- [ ] Verify all five docs render correctly on GitHub (check for broken links)
- [ ] Verify Phase 0 shows ✅ Complete in the README status table
- [ ] Move to T-009 — Setup Python backend environment (Phase 1 begins)
- [ ] Update `.env` with any new variables added during documentation review

---

## Notes

`docs/ARCHITECTURE.md` will need to be updated as the system is built.
Key update points:

- **After T-029** — update InvestmentState TypedDict definition with real field types
- **After T-034** — replace ASCII pipeline diagram with the auto-exported Mermaid diagram
- **After T-073** — update deployment section with real Render and Vercel URLs
- **After T-076** — link the comprehensive README from the architecture doc

Do not let the architecture doc fall more than one phase behind the actual code.
It is the primary reference for technical reviewers visiting the repo.

---

_End of T-008 — AIRP Project Documentation | Phase 0, Week 1_
