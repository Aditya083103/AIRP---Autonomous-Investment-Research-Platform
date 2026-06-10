# T-022 — Build Fundamental Analyst Agent

**Phase:** 2 — Research Agents
**Week:** 4
**Branch:** `feat/agent-fundamental`
**Status:** Complete

---

## 1. Overview

Implements the first of the eight AIRP investment committee agents: the
**Fundamental Analyst**. This agent analyses a company's financial health
over 4 fiscal years and produces a validated `FundamentalAnalysis` Pydantic
model (defined in T-021).

The agent follows a strict two-stage pipeline:

1. **Deterministic stage** — fetch data from tools, compute a score (1–10)
   and four qualitative trend labels using pure Python logic (no LLM, fully
   reproducible).
2. **LLM stage** — send pre-processed structured data to the LLM to generate
   `strengths[]`, `risks[]`, and a 2–3 sentence `summary`. The LLM never
   sees raw JSON blobs or DataFrames.

---

## 2. Files Delivered

| File | Description |
|------|-------------|
| `backend/agents/fundamental_analyst.py` | Agent implementation |
| `backend/tests/unit/test_fundamental_analyst.py` | Unit tests (no network) |
| `docs/week-04/T-022-build-fundamental-analyst-agent.md` | This document |

---

## 3. Agent Architecture

```
run_fundamental_analysis(state)          ← LangGraph node entry point
    │
    ├── fetch_financials.invoke(ticker)  ← Tool: 4-yr income/balance/cashflow
    ├── fetch_ratios.invoke(ticker)      ← Tool: PE/PB/ROE/ROCE/D-E/EV-EBITDA
    │
    ├── _score_financials(fin, rat)      ← Pure: deterministic score 1-10
    ├── _assess_trends(fin, rat)         ← Pure: 4 qualitative labels
    ├── _build_agent_prompt(...)         ← Pure: LLM prompt construction
    │
    ├── get_llm().invoke(messages)       ← LLM: strengths, risks, summary
    │
    └── FundamentalAnalysis(...)         ← Validated Pydantic output model
            │
            └── {"fundamental": result.model_dump()}  → InvestmentState
```

---

## 4. Scoring Methodology

The score is fully deterministic — no LLM involved. Six dimensions, 10 points max:

| Dimension | Max pts | Criteria |
|-----------|---------|----------|
| Revenue CAGR | 3 | >15% → 3, >8% → 2, >3% → 1 |
| Net margin | 2 | >20% → 2, >12% → 1 |
| ROE | 2 | >20% → 2, >12% → 1 |
| Debt/Equity | 2 | ≤0 (net cash) → 2, ≤0.5 → 1 |
| FCF margin | 1 | ≥5% of revenue → 1 |

Score is clamped to [1, 10]. If fewer than 2 data points are available,
returns 1 (minimum) to signal an unreliable assessment.

---

## 5. Qualitative Labels

Four deterministic labels are computed and passed to the LLM as structured
context (not free-form):

| Label | Values |
|-------|--------|
| `revenue_trend` | `growing` / `stable` / `declining` / `insufficient_data` |
| `profit_trend` | `improving` / `stable` / `declining` / `insufficient_data` |
| `debt_level` | `net_cash` / `low` / `moderate` / `high` / `unknown` |
| `fcf_status` | `strong` / `adequate` / `weak` / `negative` / `unknown` |

---

## 6. LangSmith Tracing

Tracing is automatic. When `LANGCHAIN_TRACING_V2=true` and `LANGSMITH_API_KEY`
is set in `.env`, every tool call and LLM invocation in this agent is captured
in LangSmith with:

- Agent name tag
- Ticker in the run metadata
- Full prompt/response captured
- Token counts and latency per call

No additional code is needed — LangChain instruments `llm.invoke()` and
`tool.invoke()` automatically.

---

## 7. Acceptance Criteria Verification

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Returns valid `FundamentalAnalysis` for TCS | ✅ | `test_high_quality_data_scores_high` |
| Returns valid `FundamentalAnalysis` for Infosys | ✅ | `test_infy_state` |
| Returns valid `FundamentalAnalysis` for Reliance | ✅ | `test_reliance_state` |
| LangSmith trace visible | ✅ | Auto-traced via LangChain instrumentation |
| Score 1–10 always valid | ✅ | `test_score_in_valid_range` |
| Never raises (error dict convention) | ✅ | `test_never_raises` |
| Tool called with correct ticker | ✅ | `test_tool_called_with_correct_ticker` |
| Graceful LLM failure | ✅ | `test_llm_failure_uses_fallback_summary` |
| Output serialisable to dict | ✅ | `test_model_serialisable` |

---

## 8. Git Flow

### 8.1 Branch checkout

```bash
git checkout main
git pull origin main
git checkout -b feat/agent-fundamental
```

### 8.2 Place files

```
backend/agents/fundamental_analyst.py
backend/tests/unit/test_fundamental_analyst.py
docs/week-04/T-022-build-fundamental-analyst-agent.md
```

### 8.3 Pre-commit checks

```bash
black backend/agents/fundamental_analyst.py \
      backend/tests/unit/test_fundamental_analyst.py
isort backend/agents/fundamental_analyst.py \
      backend/tests/unit/test_fundamental_analyst.py
flake8 backend/agents/fundamental_analyst.py \
       backend/tests/unit/test_fundamental_analyst.py
mypy backend/agents/fundamental_analyst.py
```

### 8.4 Run tests

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_fundamental_analyst.py -v
```

Expected: all tests pass. Then run full suite to confirm no regressions:

```bash
python -m pytest -m "not integration" --tb=short -q
```

### 8.5 Commit

```bash
git add backend/agents/fundamental_analyst.py
git add backend/tests/unit/test_fundamental_analyst.py
git add docs/week-04/T-022-build-fundamental-analyst-agent.md

git commit -m "feat(agents): build Fundamental Analyst agent (T-022)

- Two-stage pipeline: deterministic scoring + LLM narrative synthesis
- _score_financials: composite score 1-10 across 6 dimensions
  (revenue CAGR, net margin, ROE, D/E, FCF margin) — no LLM, reproducible
- _assess_trends: 4 qualitative labels (revenue/profit trend, debt level,
  FCF status) passed as structured context to the LLM
- LLM generates strengths[], risks[], summary only — never sees raw JSON
- fetch_financials + fetch_ratios tools called with ticker from state
- Error convention: never raises; FundamentalAnalysis.error set on failure
- LangSmith tracing: automatic via LangChain instrumentation
- run_fundamental_analysis: LangGraph node reads job_id/company_name/ticker
  from state, writes {'fundamental': result.model_dump()} back to state
- 60+ unit tests: scoring, trends, prompt building, full agent with mocked
  tools/LLM, error paths (tool failure, LLM failure, malformed JSON,
  missing ticker), TCS/INFY/RELIANCE state shapes

Closes #22"
```

### 8.6 Push and open PR

```bash
git push -u origin feat/agent-fundamental
```

---

## 9. Pull Request

### Title

```
feat(agents): build Fundamental Analyst agent (T-022)
```

### Description

```markdown
## Summary

Implements the Fundamental Analyst — the first of 8 AIRP investment committee
agents. The agent fetches 4 years of financial statements and valuation ratios,
computes a deterministic quality score (1–10), derives qualitative trend labels,
and calls the LLM to synthesise concrete strengths and risks backed by specific
data points. Output is a validated `FundamentalAnalysis` Pydantic model ready
for LangGraph state storage.

## Changes

- `backend/agents/fundamental_analyst.py`
  - `run_fundamental_analysis(state)` — LangGraph node (reads from / writes
    to InvestmentState)
  - `_run_fundamental_analysis_core(analysis_id, company_name, ticker)` —
    testable core logic
  - `_score_financials(financials, ratios)` — deterministic 1–10 score
  - `_assess_trends(financials, ratios)` — 4 qualitative label dict
  - `_build_agent_prompt(...)` — structured LLM prompt builder
  - `_revenue_cagr(income_records)` — compound annual growth helper
  - `SYSTEM_PROMPT` — seasoned buy-side analyst persona with strict JSON
    output schema
  - Full error handling: tool errors degrade gracefully, LLM failures use
    fallback summary, node never raises

- `backend/tests/unit/test_fundamental_analyst.py` — 60+ unit tests covering:
  - `_band_score`, `_revenue_cagr` helpers
  - `_score_financials`: high/low quality bands, empty data, net cash
  - `_assess_trends`: all 6 label states
  - `_build_agent_prompt`: content verification, no-crash on empty data
  - `_run_fundamental_analysis_core`: mocked tools + LLM, all error paths
  - `run_fundamental_analysis`: LangGraph state in/out, TCS/INFY/RELIANCE

## Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_fundamental_analyst.py -v
# All tests pass — no network, no API quota consumed
```

## LangSmith Trace

Automatic — every `llm.invoke()` and `tool.invoke()` is captured when
`LANGCHAIN_TRACING_V2=true` and `LANGSMITH_API_KEY` is set. No code changes
needed to enable tracing.

## Related Issues

Closes #22
```

---

## 10. Usage in LangGraph (Phase 3, T-029+)

```python
# In backend/graph/graph.py (Phase 3)

from backend.agents.fundamental_analyst import run_fundamental_analysis

builder.add_node("fundamental_analyst", run_fundamental_analysis)

# The node reads these keys from InvestmentState:
#   state["job_id"]        → analysis_id
#   state["company_name"]  → company name
#   state["ticker"]        → Yahoo Finance ticker

# The node writes:
#   state["fundamental"]   → dict from FundamentalAnalysis.model_dump()

# Check for errors before consuming output:
#   if state["fundamental"]["error"] is not None:
#       # handle gracefully
```