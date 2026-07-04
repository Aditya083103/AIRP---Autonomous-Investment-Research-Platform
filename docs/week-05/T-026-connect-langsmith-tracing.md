# T-026 — Connect LangSmith Tracing to All Agents

**Phase:** 2 — Research Agents
**Week:** 05
**Branch:** `feat/agent-langsmith`
**Task status:** Ready to merge

---

## Overview

T-026 connects all four Phase 2 research agents to LangSmith so that every
agent run is visible in the LangSmith dashboard with correct tags, metadata,
and latency measurements.

**Acceptance criteria:**

- All 4 agent runs visible in LangSmith with correct tags
- Tags include `agent_name` and `company_name` per run
- Latency per agent visible (automatic — LangSmith measures wall-clock time)
- Tracing disabled in test environment (no API calls in CI)

---

## 1. Pre-work Checklist

```bash
git checkout main
git pull origin main
git log --oneline -5
```

---

## 2. Create the Feature Branch

```bash
git checkout -b feat/agent-langsmith
```

---

## 3. How LangSmith Tracing Works in AIRP

### The gap this task fills

LangChain auto-traces all LLM calls when two OS environment variables are set:

```
LANGCHAIN_TRACING_V2=true
LANGSMITH_API_KEY=<your-key>
```

These values already live in `settings` (loaded from `.env`) but Pydantic
model attributes are **not** automatically mirrored to `os.environ`, which is
what LangChain's internals inspect.

`configure_tracing()` bridges that gap: reads from `settings`, writes to
`os.environ`. It is called inside `get_llm()` before every LLM construction.

### The `@traced_agent` decorator

Each LangGraph node function is wrapped with `@traced_agent("agent_name")`.
Under the hood this calls `langsmith.traceable(run_type="chain", name=...,
tags=[agent_name, company_name], metadata={...})`.

When `LANGCHAIN_TRACING_V2=false` or `LANGSMITH_API_KEY` is empty (i.e. in
tests and CI), `traceable` is a near-zero-cost no-op — no network calls, no
latency penalty.

### What appears in the LangSmith dashboard

For each agent run you will see:

```
Run name   : fundamental_analyst          ← from agent_name
Run type   : chain
Tags       : ["fundamental_analyst", "TCS"]   ← acceptance criteria
Metadata   : {"agent_name": "fundamental_analyst",
               "analysis_id": "uuid-...",
               "company_name": "TCS"}
Latency    : 4.2s                         ← automatic wall-clock
Children   :
  ├── fetch_financials (tool)             ← auto-traced LangChain tool
  ├── fetch_ratios (tool)
  └── ChatGroq (llm)                      ← auto-traced LLM call
        Input tokens : 1842
        Output tokens: 387
```

---

## 4. Files Changed

### New files

| File            | Path                                              |
| --------------- | ------------------------------------------------- |
| Tracing utility | `backend/agents/tracing.py`                       |
| Tests           | `backend/tests/unit/test_tracing.py`              |
| Docs            | `docs/week-05/T-026-connect-langsmith-tracing.md` |

### Modified files

| File                                    | Change                                                 |
| --------------------------------------- | ------------------------------------------------------ |
| `backend/agents/llm_factory.py`         | Add `configure_tracing()` call before LLM construction |
| `backend/agents/fundamental_analyst.py` | Add `@traced_agent("fundamental_analyst")` to node     |
| `backend/agents/technical_analyst.py`   | Add `@traced_agent("technical_analyst")` to node       |
| `backend/agents/sentiment_analyst.py`   | Add `@traced_agent("news_sentiment")` to node          |
| `backend/agents/macro_economist.py`     | Add `@traced_agent("macro_economist")` to node         |

---

## 5. Exact Changes for Each Agent File

Each agent needs **two changes** and nothing else:

### 5.1 Add the import (after existing imports)

```python
from backend.agents.tracing import traced_agent
```

### 5.2 Add the decorator to the node function

**`fundamental_analyst.py`** — find `def run_fundamental_analysis(state` and add:

```python
@traced_agent("fundamental_analyst")
def run_fundamental_analysis(state: dict[str, Any]) -> dict[str, Any]:
```

**`technical_analyst.py`** — find `def run_technical_analysis(state` and add:

```python
@traced_agent("technical_analyst")
def run_technical_analysis(state: dict[str, Any]) -> dict[str, Any]:
```

**`sentiment_analyst.py`** — find `def run_sentiment_analysis(state` and add:

```python
@traced_agent("news_sentiment")
def run_sentiment_analysis(state: dict[str, Any]) -> dict[str, Any]:
```

**`macro_economist.py`** — find `def run_macro_analysis(state` and add:

```python
@traced_agent("macro_economist")
def run_macro_analysis(state: dict[str, Any]) -> dict[str, Any]:
```

The agent_name strings match the `agent_name` field in each output model
(`FundamentalAnalysis.agent_name = "fundamental_analyst"`, etc.).

---

## 6. Run Pre-commit Hooks

```bash
black backend/agents/tracing.py backend/agents/llm_factory.py
black backend/agents/fundamental_analyst.py backend/agents/technical_analyst.py
black backend/agents/sentiment_analyst.py backend/agents/macro_economist.py
black backend/tests/unit/test_tracing.py

isort backend/agents/tracing.py backend/agents/llm_factory.py
isort backend/agents/fundamental_analyst.py backend/agents/technical_analyst.py
isort backend/agents/sentiment_analyst.py backend/agents/macro_economist.py
isort backend/tests/unit/test_tracing.py

flake8 backend/agents/tracing.py backend/agents/llm_factory.py
flake8 backend/agents/fundamental_analyst.py backend/agents/technical_analyst.py
flake8 backend/agents/sentiment_analyst.py backend/agents/macro_economist.py
flake8 backend/tests/unit/test_tracing.py
```

All must produce zero output.

---

## 7. Run the Tests

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_tracing.py -v
```

Key tests to verify (acceptance criteria):

```
TestConfigureTracing::test_sets_tracing_false_when_key_absent           PASSED
TestConfigureTracing::test_sets_tracing_true_when_key_present           PASSED
TestConfigureTracing::test_disabled_overrides_stale_env                 PASSED
TestTracingIsActive::test_in_test_env_is_false                          PASSED
TestTracedAgent::test_tags_include_agent_name_and_company               PASSED
TestTracedAgent::test_metadata_contains_agent_name                      PASSED
TestAgentNodesAreTraced::test_fundamental_analyst_has_wrapped_attribute PASSED
TestAgentNodesAreTraced::test_technical_analyst_has_wrapped_attribute   PASSED
TestAgentNodesAreTraced::test_sentiment_analyst_has_wrapped_attribute   PASSED
TestAgentNodesAreTraced::test_macro_economist_has_wrapped_attribute     PASSED
TestTracingDisabledInTests::test_tracing_disabled_when_key_empty        PASSED
```

Run the full unit suite to confirm no regressions:

```bash
python -m pytest backend/tests/unit/ -v --tb=short
```

---

## 8. Verify in LangSmith Dashboard (Manual — dev environment only)

After merging and running in dev with a real `LANGSMITH_API_KEY` in `.env`:

1. Run any agent: `python -c "from backend.agents.fundamental_analyst import run_fundamental_analysis; run_fundamental_analysis({'job_id': 'test', 'company_name': 'TCS', 'ticker': 'TCS.NS'})"`
2. Open https://smith.langchain.com → project `airp-dev`
3. Verify: run named `fundamental_analyst` appears
4. Verify: tags include `fundamental_analyst` and `TCS`
5. Verify: latency column shows wall-clock time
6. Verify: child runs for tool calls and LLM call are nested under the agent run

---

## 9. Commit

```bash
git add backend/agents/tracing.py
git add backend/agents/llm_factory.py
git add backend/agents/fundamental_analyst.py
git add backend/agents/technical_analyst.py
git add backend/agents/sentiment_analyst.py
git add backend/agents/macro_economist.py
git add backend/tests/unit/test_tracing.py
git add docs/week-05/T-026-connect-langsmith-tracing.md
```

```bash
git commit -m "feat(tracing): connect LangSmith tracing to all four research agents"
```

---

## 10. Push

```bash
git push origin feat/agent-langsmith
```

---

## 11. Pull Request

- **Base branch:** `main`
- **Compare branch:** `feat/agent-langsmith`
- **Title:** `feat(tracing): T-026 — LangSmith tracing for all research agents`

**PR Description:**

```
## Summary

Connects all four Phase 2 research agents to LangSmith tracing.
Introduces `backend/agents/tracing.py` which provides `configure_tracing()`
(mirrors settings into os.environ at startup) and `@traced_agent` (wraps
LangGraph node functions with langsmith.traceable, attaching agent_name and
company_name tags). `get_llm()` now calls `configure_tracing()` before
constructing the LLM object so LangChain's auto-tracing activates in time
to capture every tool call and LLM invocation.

## Changes

- `backend/agents/tracing.py` — new module: configure_tracing(),
  tracing_is_active(), traced_agent() decorator
- `backend/agents/llm_factory.py` — call configure_tracing() before
  LLM construction
- `backend/agents/fundamental_analyst.py` — @traced_agent on node
- `backend/agents/technical_analyst.py` — @traced_agent on node
- `backend/agents/sentiment_analyst.py` — @traced_agent on node
- `backend/agents/macro_economist.py` — @traced_agent on node
- `backend/tests/unit/test_tracing.py` — full test suite

## Testing

All tracing tests pass; all existing agent tests continue to pass.
Tracing is a no-op in tests (LANGSMITH_API_KEY="" in conftest).

## Related Issues

Closes #26
```

---

## 12. Merge

1. Squash and merge on GitHub
2. Squash commit: `feat(tracing): T-026 — LangSmith tracing for all research agents (#26)`
3. Delete branch

```bash
git checkout main
git pull origin main
git branch -d feat/agent-langsmith
```

---

## 13. Acceptance Criteria Mapping

| Criterion                                    | Test(s)                                                             | Status       |
| -------------------------------------------- | ------------------------------------------------------------------- | ------------ |
| All 4 agent runs visible (decorator applied) | `test_*_has_wrapped_attribute` × 4                                  | Verified     |
| Correct tags (agent_name + company_name)     | `test_tags_include_agent_name_and_company`                          | Verified     |
| Latency per agent                            | Automatic (LangSmith wall-clock)                                    | N/A in tests |
| Tracing disabled in tests                    | `test_tracing_disabled_when_key_empty`, `test_in_test_env_is_false` | Verified     |
| configure_tracing called before LLM          | `test_configure_tracing_called_before_llm_construction`             | Verified     |
| Stale env var overridden                     | `test_disabled_overrides_stale_env`                                 | Verified     |

---

_T-026 complete. Next: T-027 or T-028 (remaining Phase 2 tasks)._
