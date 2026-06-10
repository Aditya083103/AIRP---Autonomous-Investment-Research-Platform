# T-021 — Define Pydantic Output Models for All Agents

**Phase:** 2 — Research Agents
**Week:** 4
**Branch:** `feat/agent-output-models`
**Status:** Complete

---

## 1. Overview

This task defines the canonical Pydantic v2 output models for every agent in the AIRP investment committee. These models are the typed contracts that:

- Agents return as their output
- LangGraph stores in `InvestmentState`
- The ORM persists as `JSONB` in `agent_outputs.output_json`
- The Portfolio Manager and Contrarian Investor read to make decisions

No agent code is written here — only the **output schemas**. This is a foundational task: every subsequent Phase 2 agent task (T-022 through T-028) depends on these models existing.

---

## 2. Files Delivered

| File | Description |
|------|-------------|
| `backend/agents/output_models.py` | All 9 models (1 base + 8 concrete) |
| `backend/tests/unit/test_output_models.py` | 60+ unit tests covering all models |
| `docs/week-04/T-021-define-agent-output-models.md` | This document |

---

## 3. Model Hierarchy

```
AgentOutput (base — frozen, shared fields)
├── FundamentalAnalysis    (Agent 1 — Fundamental Analyst)
├── TechnicalAnalysis      (Agent 2 — Technical Analyst)
├── SentimentAnalysis      (Agent 3 — News Sentiment)
├── MacroAnalysis          (Agent 4 — Macro Economist)
├── RiskAnalysis           (Agent 5 — Risk Officer)
├── ContrarianReport       (Agent 6 — Contrarian Investor)
├── ValuationOutput        (Agent 7 — Valuation Agent)
└── InvestmentDecision     (Agent 8 — Portfolio Manager)
```

### Base class fields (all models inherit these)

| Field | Type | Description |
|-------|------|-------------|
| `agent_name` | `str` | Canonical agent ID (matches `AgentNameEnum` in ORM) |
| `analysis_id` | `str` | UUID of the parent Analysis job |
| `company_name` | `str` | Human-readable company name |
| `ticker` | `str` | Yahoo Finance ticker with suffix (`TCS.NS`) |
| `generated_at` | `datetime` | UTC timestamp when output was produced |
| `error` | `Optional[str]` | `None` on success; error message on failure |

---

## 4. Design Decisions

### 4.1 No `from __future__ import annotations`

Deliberately omitted. It breaks Pydantic v2 union type resolution — forward references become strings at evaluation time, which Pydantic cannot resolve for `model_json_schema()` and `model_validate()`. This is a known AIRP-wide rule established in T-010.

### 4.2 `frozen=True` on base model

All output models are immutable once created (`model_config = ConfigDict(frozen=True)`). This prevents agents from mutating each other's outputs via shared state references in LangGraph, which would be a hard-to-debug bug.

### 4.3 Error dict convention preserved

The `error` field on `AgentOutput` follows the established AIRP tool convention: agents never raise exceptions; they return a model with `error` set. LangGraph routing logic checks `result.error is not None` to detect and handle failures gracefully.

### 4.4 Pydantic `Field(description=...)` on every field

All fields have a `description` argument. This is not just documentation — it populates the `description` key in the JSON schema produced by `model_json_schema()`. The FastAPI OpenAPI docs and LangSmith's structured output display both consume this schema automatically.

### 4.5 `Optional` fields for data that may be unavailable

API rate limits and data gaps are real. Fields like `rsi_14`, `pe_ratio`, and `gdp_growth_pct` are `Optional[float]` so an agent can return a valid, well-formed model even when a specific data point could not be fetched. The `error` field is reserved for catastrophic failures only.

---

## 5. Acceptance Criteria Verification

| Criterion | Status | Evidence |
|-----------|--------|----------|
| All models importable | ✅ | `from backend.agents.output_models import FundamentalAnalysis` etc. — verified in `test_all_models_importable` |
| JSON serialisation round-trips | ✅ | Every model has a `test_json_round_trip` / `test_model_dump` test |
| Schema auto-generated | ✅ | Every model has a `test_json_schema_generated` test calling `model_json_schema()` |
| `__all__` exports all 9 classes | ✅ | `test_all_exports_in_dunder_all` verifies exact set |
| Validation rejects bad values | ✅ | `test_score_lower_bound`, `test_score_upper_bound`, `test_sentiment_score_bounds`, etc. |
| Frozen — immutable after creation | ✅ | `test_frozen_prevents_mutation` |
| All 8 concrete agents covered | ✅ | Dedicated test class per model |

---

## 6. Git Flow

### 6.1 Branch checkout

```bash
# From main (confirmed clean)
git checkout main
git pull origin main

git checkout -b feat/agent-output-models
```

### 6.2 Place the files

```
backend/agents/output_models.py
backend/tests/unit/test_output_models.py
docs/week-04/T-021-define-agent-output-models.md
```

### 6.3 Pre-commit checks (run manually first)

```bash
# Windows Git Bash
set ENVIRONMENT=test

black backend/agents/output_models.py backend/tests/unit/test_output_models.py
isort backend/agents/output_models.py backend/tests/unit/test_output_models.py
flake8 backend/agents/output_models.py backend/tests/unit/test_output_models.py
mypy backend/agents/output_models.py
```

### 6.4 Run the tests

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_output_models.py -v
```

Expected output (abbreviated):

```
PASSED tests/unit/test_output_models.py::TestAgentOutput::test_base_fields_present_on_subclass
PASSED tests/unit/test_output_models.py::TestAgentOutput::test_error_field_defaults_to_none
...
PASSED tests/unit/test_output_models.py::TestCrossModel::test_all_exports_in_dunder_all
60+ passed in ~0.5s
```

### 6.5 Run full unit suite

```bash
set ENVIRONMENT=test
python -m pytest -m "not integration" --tb=short -q
```

All prior tests (T-010 through T-020) must still pass — no regressions.

### 6.6 Commit

```bash
git add backend/agents/output_models.py
git add backend/tests/unit/test_output_models.py
git add docs/week-04/T-021-define-agent-output-models.md

git commit -m "feat(agents): define Pydantic output models for all 8 agents

- Add AgentOutput frozen base with agent_name, analysis_id, ticker,
  generated_at, and error fields
- Add FundamentalAnalysis, TechnicalAnalysis, SentimentAnalysis,
  MacroAnalysis, RiskAnalysis, ContrarianReport, ValuationOutput,
  InvestmentDecision concrete models
- All models: frozen=True, Field(description=...), Optional for
  data-availability gaps, error dict convention preserved
- 60+ unit tests: instantiation, validation, serialisation,
  schema auto-generation, immutability, __all__ completeness
- No from __future__ import annotations (breaks Pydantic v2 unions)

Closes #21"
```

### 6.7 Push and open PR

```bash
git push -u origin feat/agent-output-models
```

Then open a PR on GitHub targeting `main`.

---

## 7. Pull Request

### Title

```
feat(agents): define Pydantic output models for all 8 agents (T-021)
```

### Description

```markdown
## Summary

Defines the canonical Pydantic v2 output schemas for every agent in the
AIRP investment committee. These models are the typed contracts that agents
return, LangGraph stores in `InvestmentState`, and the ORM persists as JSONB.
This is the prerequisite for all Phase 2 agent tasks (T-022–T-028).

## Changes

- `backend/agents/output_models.py` — 9 models (1 base + 8 concrete):
  - `AgentOutput` — frozen base class with shared fields and error convention
  - `FundamentalAnalysis` — score 1–10, revenue/margin/FCF/balance sheet fields
  - `TechnicalAnalysis` — signal BUY/HOLD/SELL, MA50/200, RSI, momentum
  - `SentimentAnalysis` — sentiment_score -1 to +1, red_flags, article stats
  - `MacroAnalysis` — RBI rate, inflation, GDP, sector tailwinds/headwinds
  - `RiskAnalysis` — composite risk_score 1–10, governance/regulatory/financial subscores, risk_flags
  - `ContrarianReport` — counter_arguments, bear_conviction, overlooked_risks
  - `ValuationOutput` — DCF intrinsic value, PE/PB/EV-EBITDA vs peers
  - `InvestmentDecision` — final verdict BUY/HOLD/SELL, conviction 1–10, full memo sections

- `backend/tests/unit/test_output_models.py` — 60+ unit tests:
  - Instantiation with minimal required fields
  - Validation rejects out-of-range values (ge/le bounds)
  - `model_dump()` and `model_dump_json()` round-trips
  - `model_json_schema()` auto-generation for all models
  - `frozen=True` immutability enforcement
  - `__all__` completeness check
  - Cross-model inheritance and `agent_name` default verification

## Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_output_models.py -v
# 60+ passed
```

Full unit suite passes with no regressions.

## LangSmith Trace

Not applicable — no LLM calls in this task (pure schema definitions).

## Related Issues

Closes #21
```

---

## 8. Key Implementation Notes for Future Agents

When implementing Phase 2 agents (T-022–T-028), use the models like this:

```python
# In backend/agents/fundamental_analyst.py

from agents.output_models import FundamentalAnalysis

def run_fundamental_analysis(state: InvestmentState) -> dict:
    # ... fetch data, call LLM ...

    result = FundamentalAnalysis(
        analysis_id=state["job_id"],
        company_name=state["company_name"],
        ticker=state["ticker"],
        score=8,
        revenue_growth_pct=12.5,
        summary="TCS demonstrates strong fundamental quality...",
    )

    # Store in state as dict (LangGraph requires serialisable state)
    return {"fundamental": result.model_dump()}
```

On error:

```python
    result = FundamentalAnalysis(
        analysis_id=state["job_id"],
        company_name=state["company_name"],
        ticker=state["ticker"],
        score=1,  # required field — use sentinel value
        error="yFinance timeout after 3 retries: ConnectionError",
    )
    return {"fundamental": result.model_dump()}
```

The router in LangGraph checks `state["fundamental"]["error"]` before passing the output to downstream agents.