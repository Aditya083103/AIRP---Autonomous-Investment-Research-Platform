# AIRP — Coding Standards

> **These standards are enforced automatically.**
> pre-commit blocks any commit that violates them.
> CI (GitHub Actions) blocks any PR that violates them.
> Read this once; let the tools do the rest.

---

## Table of Contents

1. [Pre-commit Setup](#1-pre-commit-setup)
2. [Python Standards](#2-python-standards)
3. [TypeScript / React Standards](#3-typescript--react-standards)
4. [Branch Naming](#4-branch-naming)
5. [Commit Message Format](#5-commit-message-format)
6. [Pull Request Standards](#6-pull-request-standards)
7. [File & Folder Naming](#7-file--folder-naming)
8. [What the CI Pipeline Checks](#8-what-the-ci-pipeline-checks)

---

## 1. Pre-commit Setup

Run **once** after cloning:

```bash
# Backend / Python tooling
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r backend/requirements-dev.txt
pre-commit install            # installs hooks into .git/hooks/

# Frontend / Node tooling (separate — no venv needed)
cd frontend
npm install
cd ..
```

Verify everything passes on the current codebase:

```bash
pre-commit run --all-files
```

From this point on, hooks run automatically on every `git commit`.
To skip in an emergency (never for main): `git commit --no-verify`.

---

## 2. Python Standards

### Formatter — black

- **Config:** `pyproject.toml → [tool.black]`
- Line length: **88** (black's default)
- Target version: Python 3.11
- Black is non-negotiable. Do not fight it. If a line looks ugly after black formats it, the code structure is the problem — not black.

```bash
# Format all backend files
black backend/

# Check without modifying (what CI runs)
black --check backend/
```

### Import sorter — isort

- **Config:** `pyproject.toml → [tool.isort]`
- Profile: `black` (fully compatible, no conflicts)
- Known first-party packages: `agents`, `graph`, `routers`, `models`, `services`, `tools`, `db`
- Import order: stdlib → third-party → first-party → relative

```python
# Correct order
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from agents.base import BaseAgent
from .utils import format_ticker
```

### Linter — flake8

- **Config:** `.flake8` (root level — flake8 does not read pyproject.toml)
- Max line length: 88 (matches black)
- Plugins active: `flake8-bugbear`, `flake8-comprehensions`, `flake8-docstrings`
- Ignored: E203, W503 (black conflicts), D100–D107 (docstrings — re-enable in Phase 2+)

```bash
flake8 backend/
```

Common violations to avoid:

```python
# B006 — mutable default argument (bugbear catches this)
def bad(items: list = []) -> None: ...      # ❌
def good(items: list | None = None) -> None: ...  # ✅

# C401 — unnecessary generator in list()
list(x for x in items)   # ❌
[x for x in items]       # ✅
```

### Type checker — mypy

- **Config:** `pyproject.toml → [tool.mypy]`
- Mode: **strict** — `disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`, etc.
- Plugin: `pydantic.mypy` (understands Pydantic v2 model fields)
- Test files are relaxed (see `[[tool.mypy.overrides]]`)

```bash
mypy backend/
```

Every function must have full type annotations:

```python
# ❌ mypy will reject this
def fetch_price(ticker):
    return yf.Ticker(ticker).fast_info["last_price"]

# ✅
def fetch_price(ticker: str) -> float:
    return float(yf.Ticker(ticker).fast_info["last_price"])
```

### Testing — pytest

- **Config:** `pyproject.toml → [tool.pytest.ini_options]`
- Default run: unit tests only (`-m 'not integration'`)
- Coverage target: **≥ 85%** (`--cov-fail-under=85`)
- Test file location: `backend/tests/` (mirrors source structure)

```bash
# Run unit tests (default)
pytest

# Run with coverage report
pytest --cov=backend --cov-report=term-missing

# Run integration tests (hits real APIs — run sparingly)
pytest -m integration
```

Test file naming: `test_<module_name>.py`

```
backend/
  agents/
    fundamental_analyst.py
  tests/
    test_fundamental_analyst.py   ✅
```

---

## 3. TypeScript / React Standards

### Formatter — Prettier

- **Config:** `frontend/.prettierrc.json`
- Print width: 100, single quotes: false (double quotes), trailing commas: all, LF line endings
- Plugin: `prettier-plugin-tailwindcss` (auto-sorts Tailwind class names)

```bash
# Format all frontend files
cd frontend && npm run format

# Check without modifying (what CI runs)
npm run format:check
```

### Linter — ESLint

- **Config:** `frontend/.eslintrc.cjs`
- Extends: `@typescript-eslint/recommended-requiring-type-checking` + `react-hooks` + `import/order` + `prettier` (last, disables conflicting rules)
- Max warnings: **0** — warnings are errors in CI

```bash
cd frontend && npm run lint         # check
cd frontend && npm run lint:fix     # auto-fix where possible
```

Key rules enforced:

```typescript
// ❌ no-explicit-any
const data: any = response.data;

// ✅ type it properly
const data: AnalysisResult = response.data as AnalysisResult;

// ❌ missing type-only import
import { AnalysisResult } from "@types/analysis";

// ✅ consistent-type-imports
import { type AnalysisResult } from "@types/analysis";

// ❌ floating promise (no-floating-promises)
fetchAnalysis();

// ✅
void fetchAnalysis();
// or
await fetchAnalysis();
```

Import order (enforced by `import/order`):

```typescript
// 1. External packages
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";

// 2. Internal aliases (blank line between groups)
import { AgentCard } from "@components/AgentCard";
import { useAnalysis } from "@hooks/useAnalysis";

// 3. Relative imports
import "./Analysis.css";
```

### Type checking — tsc

```bash
cd frontend && npm run type-check
```

tsconfig enforces `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`.
This means array access `items[0]` returns `T | undefined`, not `T` — handle it:

```typescript
const first = items[0];        // type: AgentOutput | undefined
if (!first) return null;       // ✅ guard before use
```

### Component conventions

- **File name:** PascalCase — `AgentProgressCard.tsx`
- **One component per file** (except small co-located sub-components)
- **No default export for named components** in library code — use named exports
- **Props interface** defined above the component, named `<ComponentName>Props`

```typescript
interface AgentProgressCardProps {
  agentName: string;
  status: "pending" | "running" | "complete" | "error";
  durationMs?: number;
}

export function AgentProgressCard({
  agentName,
  status,
  durationMs,
}: AgentProgressCardProps): React.JSX.Element {
  // ...
}
```

---

## 4. Branch Naming

| Pattern | Example | Use for |
|---|---|---|
| `feat/<area>-<description>` | `feat/agent-fundamental-analyst` | New functionality |
| `fix/<area>-<description>` | `fix/api-websocket-disconnect` | Bug fixes |
| `chore/<description>` | `chore/update-dependencies` | Config, deps, tooling |
| `docs/<description>` | `docs/add-architecture-diagram` | Documentation only |
| `perf/<area>-<description>` | `perf/graph-parallel-execution` | Performance improvements |
| `refactor/<area>-<description>` | `refactor/agents-base-class` | Code restructuring |
| `test/<area>-<description>` | `test/data-layer-integration` | Adding/updating tests |
| `ci/<description>` | `ci/add-coverage-report` | CI/CD pipeline changes |
| `setup/<description>` | `setup/pre-commit` | Project setup tasks (Phase 0) |

**Rules:**
- All lowercase, hyphens only (no underscores, no slashes except the prefix separator)
- No direct pushes to `main` — ever. Even as a solo developer.
- Delete branch after PR is merged.

---

## 5. Commit Message Format

```
type(scope): short description

Optional longer body explaining WHY, not what.
Wrap at 72 characters.
```

| Type | Meaning | Example |
|---|---|---|
| `feat` | New feature | `feat(agents): add Fundamental Analyst with scoring` |
| `fix` | Bug fix | `fix(api): handle WebSocket disconnect gracefully` |
| `docs` | Documentation | `docs(readme): add architecture diagram` |
| `test` | Tests added/updated | `test(data): add unit tests for fetch_ratios tool` |
| `chore` | Maintenance | `chore(deps): upgrade langchain to 0.3.0` |
| `perf` | Performance | `perf(graph): run research agents in parallel via Send API` |
| `refactor` | Code restructure | `refactor(agents): extract base agent class` |
| `ci` | CI/CD changes | `ci: add pytest coverage report to Actions` |
| `setup` | Project setup | `setup(pre-commit): configure black, flake8, eslint` |

**Rules:**
- Subject line: max 72 characters, imperative mood ("add" not "added")
- Never: `fix stuff`, `updates`, `wip`, `asdf`
- Every commit must be meaningful enough to understand from `git log --oneline` alone

---

## 6. Pull Request Standards

Every change — even solo — goes through a PR. No direct pushes to `main`.

**PR title:** same format as commit message — `feat(agents): add Fundamental Analyst`

**PR description template** (`.github/PULL_REQUEST_TEMPLATE.md`):

```markdown
## Summary
2–3 sentences: what this PR does and why.

## Changes
- Specific change 1
- Specific change 2

## Testing
How it was tested. Which tests were added.

## LangSmith Trace
Link to trace (required if this PR touches any agent code).

## Screenshots
Terminal output or UI screenshot for visual changes.

## Related Issues
Closes #<issue-number>
```

**PR checklist before merge:**
- [ ] CI passes (lint + type-check + pytest)
- [ ] `pre-commit run --all-files` passes locally
- [ ] Closes at least one GitHub Issue
- [ ] LangSmith trace linked (agent changes only)

---

## 7. File & Folder Naming

| Type | Convention | Example |
|---|---|---|
| Python source files | `snake_case` | `fundamental_analyst.py` |
| Python test files | `test_<module>.py` | `test_fundamental_analyst.py` |
| Python classes | `PascalCase` | `FundamentalAnalystAgent` |
| Python constants | `SCREAMING_SNAKE_CASE` | `MAX_DEBATE_ROUNDS = 2` |
| TypeScript React components | `PascalCase` | `AgentProgressCard.tsx` |
| TypeScript hooks | `camelCase` with `use` prefix | `useWebSocket.ts` |
| TypeScript utilities | `camelCase` | `formatConvictionScore.ts` |
| TypeScript types/interfaces | `PascalCase` | `InvestmentState.ts` |
| Folders | `kebab-case` | `agent-progress/` |
| Environment variables | `SCREAMING_SNAKE_CASE` | `LANGSMITH_API_KEY` |

---

## 8. What the CI Pipeline Checks

Every push to every branch runs `.github/workflows/ci.yml`:

| Check | Tool | Fails if |
|---|---|---|
| Python format | `black --check` | Any file would be reformatted |
| Python imports | `isort --check` | Import order differs from isort output |
| Python lint | `flake8` | Any violation not in ignore list |
| Python types | `mypy` | Any type error in strict mode |
| Python tests | `pytest --cov` | Any test fails OR coverage < 85% |
| TS types | `tsc --noEmit` | Any TypeScript error |
| TS lint | `eslint --max-warnings 0` | Any ESLint warning or error |
| Frontend build | `vite build` | Build fails for any reason |

PRs to `main` must pass all checks. There are no exceptions.
