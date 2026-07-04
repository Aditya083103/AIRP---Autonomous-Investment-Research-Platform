# T-028 — Document Agent System Prompts and Design

**Phase:** 2 — Research Agents
**Week:** 05
**Branch:** `feat/agent-docs`
**Task status:** Ready to merge

---

## Overview

T-028 produces the authoritative `docs/AGENTS.md` reference — the
complete design documentation for all 8 agents in the AIRP investment
committee. The file covers persona, tools, scoring logic, output schema,
example JSON output, and known limitations for each agent.

**Acceptance criteria:**

- `AGENTS.md` has a section for each agent
- Example JSON output included for each Phase 2 agent
- Existing empty stub replaced with complete content

**Note:** T-028 is a **documentation-only task**. No Python source files
are modified. There are no new tests to write (the CI gate for docs is
that existing tests continue to pass unchanged). The file goes in
`docs/AGENTS.md` — replacing the empty stub that was created in Phase 0.

---

## 1. Pre-work Checklist

```bash
git checkout main
git pull origin main
git log --oneline -5
```

Confirm the current stub is empty:

```bash
cat docs/AGENTS.md
```

---

## 2. Create the Feature Branch

```bash
git checkout -b feat/agent-docs
```

---

## 3. File to Create / Replace

| Action                | Path                                          |
| --------------------- | --------------------------------------------- |
| Replace existing stub | `docs/AGENTS.md`                              |
| New workflow doc      | `docs/week-05/T-028-document-agent-system.md` |

The `docs/week-05/` folder already exists from T-024 through T-027.

---

## 4. Content Summary

`AGENTS.md` contains 10 sections:

| Section                      | Content                                                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| 1. System Overview           | Agent table with state keys and LangGraph nodes                                                        |
| 2. Agent Base Contract       | `AgentOutput` fields, error convention, serialisation                                                  |
| 3. Fundamental Analyst       | Persona, tools, scoring logic, full schema table, example JSON, limitations                            |
| 4. Technical Analyst         | Persona, tools, indicator computation table, schema table, example JSON, limitations                   |
| 5. News Sentiment Agent      | Persona, tools, three-layer scoring architecture, schema table, example JSON, limitations              |
| 6. Macro Economist           | Persona, tools, classification tables, sector impact rules, schema table, 2× example JSON, limitations |
| 7. Agents 5–8 Stubs          | Mandate and output model descriptions for Risk Officer, Contrarian, Valuation, Portfolio Manager       |
| 8. LangGraph Execution Order | ASCII pipeline diagram + state key table                                                               |
| 9. Error Handling Convention | Six rules covering never-raise, ChromaDB non-fatal, LLM fallback                                       |
| 10. LangSmith Tracing Tags   | Tags, metadata, and `.env` setup                                                                       |

---

## 5. No Tests Required

T-028 is documentation only. The acceptance criteria are verified by
reading the file. The CI gate is:

```bash
python -m pytest backend/tests/unit/ -v --tb=short
```

All existing tests must continue to pass (no Python files changed).

---

## 6. Place the File

Replace `docs/AGENTS.md` with the new file. The existing stub was created
in T-003 (Phase 0 documentation scaffolding) and intentionally left empty
until the agents were built.

---

## 7. Commit

```bash
git add docs/AGENTS.md
git add docs/week-05/T-028-document-agent-system.md
```

```bash
git commit -m "docs(agents): complete AGENTS.md with all 4 research agent designs and example outputs"
```

---

## 8. Push

```bash
git push origin feat/agent-docs
```

---

## 9. Pull Request

- **Base branch:** `main`
- **Compare branch:** `feat/agent-docs`
- **Title:** `docs(agents): T-028 — Complete AGENTS.md documentation`

**PR Description:**

```
## Summary

Replaces the empty AGENTS.md stub (created T-003) with the complete
authoritative reference for the AIRP investment committee agent system.
Documents all 4 Phase 2 research agents with their exact personas,
LangChain tools, scoring logic, Pydantic output schemas, real example
JSON outputs, and known limitations. Includes stubs for Phase 4 agents
(5-8), the LangGraph execution order diagram, error handling convention,
and LangSmith tracing tag reference.

## Changes

- `docs/AGENTS.md` — complete agent documentation (10 sections,
  4 full agent descriptions, 5 example JSON blocks)

## Testing

Documentation-only change. All existing tests pass unchanged:

```

python -m pytest backend/tests/unit/ -v --tb=short

```

No Python source files modified.

## Related Issues

Closes #28
```

---

## 10. CI Gate

**Backend CI:** mypy, flake8, pytest — all must pass (no Python changes).
**Frontend CI:** `continue-on-error: true` — does not block merge.

The YAML linter check in pre-commit (`check yaml`) does not apply to
`.md` files. The `check json` hook does not apply to fenced code blocks
inside markdown.

---

## 11. Merge

1. Squash and merge
2. Squash commit: `docs(agents): T-028 — Complete AGENTS.md documentation (#28)`
3. Delete branch

```bash
git checkout main
git pull origin main
git branch -d feat/agent-docs
```

---

## 12. Acceptance Criteria Mapping

| Criterion                             | How verified                                        |
| ------------------------------------- | --------------------------------------------------- |
| Section for each agent                | Sections 3–6 (Phase 2) + Section 7 (Phase 4 stubs)  |
| Example JSON output included          | Sections 3–6 each have `json` code block            |
| Banking rate-hike headwind documented | Section 6 sector impact table + second example JSON |
| Known limitations documented          | Each agent section has explicit limitations list    |
| Error convention documented           | Section 9                                           |
| LangSmith tracing documented          | Section 10                                          |

---

_T-028 complete. Phase 2 documentation is done._
_Phase 2 is now fully complete (T-021 through T-028)._
_Next: T-029 — LangGraph Planner node (Phase 3 begins)._
