# AIRP — Contributing Guide

> **Context:** AIRP is currently a solo portfolio project (Phase 0 of 8).
> This guide documents the development workflow so that:
> 1. The developer maintains consistent discipline across all 80 tasks
> 2. Any future collaborator can contribute without needing to ask questions
> 3. Technical reviewers and recruiters see a professional engineering process

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Local Development Setup](#2-local-development-setup)
3. [Environment Configuration](#3-environment-configuration)
4. [Development Workflow](#4-development-workflow)
5. [Branch Strategy](#5-branch-strategy)
6. [Commit Message Format](#6-commit-message-format)
7. [Pull Request Process](#7-pull-request-process)
8. [Code Quality Gates](#8-code-quality-gates)
9. [Testing Strategy](#9-testing-strategy)
10. [Working with Agents](#10-working-with-agents)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

Before setting up AIRP locally, ensure you have:

| Tool | Minimum version | Check |
|---|---|---|
| Python | 3.11 | `python --version` |
| Node.js | 20 LTS | `node --version` |
| Git | 2.40+ | `git --version` |
| Docker Desktop | 24+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |

You also need accounts and API keys for all services listed in [APIS.md](APIS.md).
Complete the sign-up checklist there before proceeding.

---

## 2. Local Development Setup

### Clone and configure

```bash
# Clone the repository
git clone https://github.com/<your-username>/airp.git
cd airp

# Copy environment template
cp .env.example .env
# → Open .env and fill in every value marked replace-with-*
```

### Option A — Docker (recommended, all services in one command)

```bash
docker compose up
```

This starts:
- FastAPI API server on http://localhost:8000
- PostgreSQL on port 5432
- Redis on port 6379
- ChromaDB on port 8001

The React frontend runs separately for hot reload:

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Option B — Without Docker (manual setup)

**Backend:**

```bash
# Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# Install all dependencies including dev tools
pip install -r backend/requirements-dev.txt

# Install pre-commit hooks (run once per clone)
pre-commit install

# Apply database migrations
alembic upgrade head

# Start the FastAPI development server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

**External services (manual):**
You will need to run PostgreSQL and Redis locally or use the cloud services
(Neon + Upstash) directly. ChromaDB can be started via:

```bash
pip install chromadb
chroma run --path ./data/chromadb
```

### Verify setup

```bash
# Backend health check
curl http://localhost:8000/health
# Expected: {"status": "ok"}

# API docs
open http://localhost:8000/docs

# Run tests
export ENVIRONMENT=test        # macOS / Linux
$env:ENVIRONMENT = "test"      # Windows PowerShell

pytest
# Expected: all unit tests pass
```

---

## 3. Environment Configuration

All configuration is loaded from environment variables. The `.env.example`
file documents every variable with a description and the service it belongs to.

**Never commit `.env` to version control.**

The `.gitignore` already excludes `.env`. Double-check with:

```bash
git status .env
# Expected: nothing shown (file is ignored)
```

For CI, secrets are set under **GitHub → Repository → Settings →
Secrets and variables → Actions**. Unit tests use mocked values and
do not require real API keys. Integration tests do — mark them
`@pytest.mark.integration` and they will be excluded from the default CI run.

---

## 4. Development Workflow

Every task (T-001 to T-080) follows this workflow. No exceptions.

```
1. Read the task description and acceptance criteria from the project plan
2. Create a GitHub Issue for the task (if not already created)
3. Create a branch from main (see Branch Strategy below)
4. Write the code + tests
5. Run pre-commit locally to verify before pushing
6. Push the branch and open a Pull Request
7. Verify CI passes
8. Squash and merge to main
9. Delete the branch
10. Create the task documentation file in docs/week-XX/
```

### Day-to-day commands

```bash
# Before starting any work — pull latest main
git checkout main
git pull origin main

# Create branch for your task
git checkout -b feat/agent-fundamental-analyst

# After making changes — let pre-commit check everything
pre-commit run --all-files

# Run tests locally before pushing
pytest

# Stage, commit, push
git add .
git commit -m "feat(agents): add Fundamental Analyst with financial scoring"
git push origin feat/agent-fundamental-analyst
```

---

## 5. Branch Strategy

All branches are created from `main`. There are no long-lived feature branches.

| Pattern | Example | Purpose |
|---|---|---|
| `feat/<area>-<description>` | `feat/agent-fundamental-analyst` | New functionality |
| `fix/<area>-<description>` | `fix/api-websocket-disconnect` | Bug fixes |
| `chore/<description>` | `chore/update-dependencies` | Config, tooling, deps |
| `docs/<description>` | `docs/add-architecture-diagram` | Documentation only |
| `perf/<area>-<description>` | `perf/graph-parallel-execution` | Performance improvements |
| `refactor/<area>-<description>` | `refactor/agents-base-class` | Restructuring, no feature change |
| `test/<area>-<description>` | `test/data-layer-integration` | Adding or updating tests |
| `ci/<description>` | `ci/add-coverage-report` | CI/CD pipeline changes |
| `setup/<description>` | `setup/pre-commit` | Project setup tasks (Phase 0) |

**Rules:**
- Lowercase only. Hyphens only. No underscores in branch names.
- Branch names must be self-explanatory — someone reading `git branch -a`
  should know what every branch is doing.
- Delete branches after merge. Keep the branch list clean.
- **No direct pushes to `main`** — ever. This rule applies even as a solo
  developer. It ensures every change has a CI gate and a PR record.

---

## 6. Commit Message Format

```
type(scope): short description

Optional longer body. Explain WHY this change was made,
not WHAT was changed (the diff shows that).
Wrap body at 72 characters.

Closes #<issue-number>
```

### Types and scopes

| Type | Use for |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation changes |
| `test` | Adding or updating tests |
| `chore` | Dependencies, tooling, config |
| `perf` | Performance improvements |
| `refactor` | Code restructuring without behaviour change |
| `ci` | CI/CD pipeline changes |
| `setup` | Project setup (Phase 0 tasks) |

Scopes map to the relevant system layer or module:

```
feat(agents):     → changes to agent code
feat(graph):      → changes to LangGraph orchestration
feat(api):        → changes to FastAPI routes/services
feat(data):       → changes to data tools
feat(ui):         → changes to React frontend
feat(rag):        → changes to ChromaDB/embedding pipeline
feat(db):         → changes to database schema/migrations
feat(cache):      → changes to Redis caching
feat(eval):       → changes to evaluation suites
feat(report):     → changes to Investment Memo generation
fix(api):         → bug fix in API layer
docs(readme):     → README update
chore(deps):      → dependency upgrade
```

### Examples

```bash
# ✅ Good commits
feat(agents): add Fundamental Analyst with financial scoring output
fix(api): handle WebSocket disconnect when client navigates away
test(data): add unit tests for fetch_ratios with mocked yfinance
perf(graph): run 4 research agents in parallel via LangGraph Send API
docs(agents): document Contrarian Investor persona and output schema
chore(deps): upgrade pydantic to 2.7.0

# ❌ Bad commits — will be flagged in code review
fix stuff
updates
WIP
asdf
final version
final final version
```

---

## 7. Pull Request Process

### Opening a PR

1. Push your branch to origin.
2. Open a Pull Request against `main`.
3. Fill in the PR description template (`.github/PULL_REQUEST_TEMPLATE.md`).
4. Wait for CI to pass.
5. Squash and merge.
6. Delete the branch.

### PR description template

```markdown
## Summary
2–3 sentences: what does this PR do and why was it needed?

## Changes
- Specific change 1 — what file/module and what it does
- Specific change 2
- Specific change 3

## Testing
- Which tests were added?
- What manual testing was done?
- What edge cases were considered?

## LangSmith Trace
<!-- Required only if this PR touches any agent code -->
[Link to LangSmith trace](https://smith.langchain.com/...)

## Screenshots
<!-- Required for UI changes; terminal output for backend changes -->

## Related Issues
Closes #<issue-number>
```

### PR checklist

Before marking a PR ready for merge:

- [ ] CI pipeline passes (all checks green)
- [ ] `pre-commit run --all-files` passes locally
- [ ] New code has corresponding tests
- [ ] Test coverage has not decreased from the 85% target
- [ ] PR description is complete (not left as template placeholders)
- [ ] Closes at least one GitHub Issue
- [ ] LangSmith trace linked (if agent code changed)
- [ ] No TODO comments left in production code (use GitHub Issues instead)

### Merge strategy

**Always squash and merge.** This keeps the `main` branch history clean —
one commit per PR, not ten "WIP" commits per feature. The squash commit
message is the PR title, which follows the same format as individual commits.

---

## 8. Code Quality Gates

### Pre-commit (local — blocks commit)

```bash
pre-commit run --all-files
```

Runs: `black`, `isort`, `flake8`, `mypy` (Python) · `eslint`, `prettier` (TypeScript)

If pre-commit fails, fix the reported issues before committing.
Do not use `--no-verify` unless you are in a genuine emergency and
immediately open a follow-up issue to fix the violation.

### CI (remote — blocks PR merge)

Every push triggers GitHub Actions. The pipeline runs:

| Check | Tool | Pass condition |
|---|---|---|
| Python format | `black --check` | Zero files would be reformatted |
| Python imports | `isort --check` | Zero files would be reordered |
| Python lint | `flake8` | Zero violations |
| Python types | `mypy` | Zero errors in strict mode |
| Python tests | `pytest --cov` | All pass, coverage ≥ 85% |
| TypeScript types | `tsc --noEmit` | Zero errors |
| TypeScript lint | `eslint --max-warnings 0` | Zero warnings or errors |
| Frontend build | `vite build` | Build succeeds |

A red CI check on a PR is a blocker. Do not merge with failing CI.

---

## 9. Testing Strategy

### Test pyramid

```
         ▲ E2E (manual only — no automated E2E suite in this project)
        ▲▲▲ Integration (real API calls, marked @pytest.mark.integration, skipped in CI)
       ▲▲▲▲▲ Unit (all mocked, fast, run on every commit)
```

### Unit tests

- All external calls (yFinance, NewsAPI, LLM) are mocked with `pytest-mock`
- Test every happy path and at least one error path per function
- Target: ≥ 85% coverage across all backend modules
- Location: `backend/tests/` mirroring the source structure

```python
# backend/tests/test_fundamental_analyst.py
import pytest
from unittest.mock import AsyncMock, patch

from agents.fundamental_analyst import FundamentalAnalystAgent


@pytest.mark.asyncio
async def test_fundamental_analyst_returns_valid_schema(mock_state):
    with patch("agents.fundamental_analyst.fetch_financials") as mock_fetch:
        mock_fetch.return_value = fake_financials_fixture()
        agent = FundamentalAnalystAgent()
        result = await agent.run(mock_state)
        assert result.score >= 1
        assert result.score <= 10
        assert len(result.strengths) > 0
```

### Integration tests

- Hit real external APIs — require a fully configured `.env`
- Marked with `@pytest.mark.integration` — excluded from CI by default
- Run manually before major merges: `pytest -m integration`
- Useful for verifying API contracts haven't changed

```python
@pytest.mark.integration
async def test_fetch_stock_price_real_api():
    result = await fetch_stock_price("INFY.NS")
    assert result.current_price > 0
```

### Test fixtures

Shared fixtures live in `backend/tests/conftest.py`. Add reusable mock objects
there rather than duplicating across test files.

---

## 10. Working with Agents

### Adding a new agent

1. Create `backend/agents/<agent_name>.py`
2. Define the agent's Pydantic output model in `backend/models/schemas.py`
3. Add the agent as a node in `backend/graph/graph.py`
4. Add the agent's output field to `InvestmentState` in `backend/graph/state.py`
5. Write unit tests in `backend/tests/test_<agent_name>.py`
6. Add the agent's LangSmith tag in the agent's `run()` method
7. Document the agent in `docs/AGENTS.md`

### Prompt engineering conventions

- System prompts live as class attributes on the agent, not in separate files
- Prompts reference `{ticker}` and `{company_name}` via Python f-strings
- Do not hardcode company names in prompts — always use state variables
- Keep system prompts under 2,000 tokens to leave room for context injection

### LangSmith tagging (required for all agents)

```python
with langsmith_client.trace(
    name=f"{self.agent_name}_{state['ticker']}",
    tags=[f"agent:{self.agent_name}", f"company:{state['ticker']}", f"env:{settings.ENVIRONMENT}"],
):
    result = await self._call_llm(prompt)
```

This tagging scheme enables filtering by agent and by company in the LangSmith UI.

---

## 11. Troubleshooting

### pre-commit fails on first run

```bash
# Reinstall hooks
pre-commit clean
pre-commit install
pre-commit run --all-files
```

### mypy errors after adding a new dependency

```bash
# Install type stubs if available
pip install types-<package-name>

# If no stubs exist, add to mypy ignore list in pyproject.toml:
# [[tool.mypy.overrides]]
# module = "some_package.*"
# ignore_missing_imports = true
```

### pytest import errors

```bash
# Ensure you are running pytest from the repo root with the venv active
# and PYTHONPATH includes the backend
PYTHONPATH=. pytest backend/tests/
```

### Docker database connection refused

```bash
# Check services are running
docker compose ps

# Check PostgreSQL logs
docker compose logs postgres

# Reset everything (WARNING: destroys local data)
docker compose down -v
docker compose up
```

### Redis connection error in local dev (without Docker)

Set `REDIS_URL` to your Upstash cloud Redis URL directly in `.env`.
Local Redis is optional — the cloud instance works for development.

### ChromaDB collection not found

```bash
# Re-run embedding pipeline to populate collections
python scripts/embed_seed_data.py
```

---

*Last updated: T-008 — Write initial documentation (Phase 0, Week 1)*
