# T-037 -- Build Risk Officer Agent

**Phase:** 4 -- Debate Engine & Advanced Agents
**Week:** 10
**Branch:** `feat/debate-risk-officer`
**Task status:** Complete

---

## Overview

T-037 builds the **Risk Officer agent** -- the fifth of eight investment
committee agents in AIRP.  The Risk Officer is a paranoid risk manager who
reads all four research agent outputs (Fundamental, Technical, Sentiment,
Macro) and produces a structured `RiskAnalysis` with named risk flags,
sub-scores, and a recommendation to the Portfolio Manager.

**Acceptance criteria (all must pass):**
- Agent correctly flags known-risky companies (SEBI keyword, fraud probe,
  high D/E, negative FCF)
- Outputs structured `RiskAnalysis` Pydantic model with all required fields
- `risk_score` in `[1, 10]`; all four sub-scores in `[1, 10]`
- LangSmith trace visible (`@traced_agent` applied, `__wrapped__` present)
- 76 unit tests pass; all passing before PR merge

---

## Files Changed

| File | Change |
|------|--------|
| `backend/agents/risk_officer.py` | **New** -- full Risk Officer agent |
| `backend/tests/unit/test_risk_officer.py` | **New** -- 76 unit tests |
| `backend/graph/nodes.py` | **Modified** -- replaced stub `_risk_impl` with real delegate |

---

## What Was Built

### New file: `backend/agents/risk_officer.py`

Two-stage pipeline (same pattern as all AIRP research agents):

**Stage 1 -- Deterministic scoring (no LLM)**

| Function | Purpose |
|----------|---------|
| `_collect_all_text(...)` | Flattens all research dicts into one lowercase string for keyword scanning |
| `_extract_sentinel_flags(...)` | Keyword-based detection of fraud, regulatory, governance signals |
| `_score_risk(...)` | Computes four sub-scores + weighted composite `risk_score` |
| `_determine_concentration_flags(...)` | Extracts concrete concentration risk flags |
| `_determine_risk_recommendation(...)` | Maps `risk_score` → `proceed_with_caution` / `monitor_closely` / `avoid` |

**Scoring logic (`_score_risk`):**

```
governance_risk   = min(10, 2 + red_flag_count*2 + (2 if gov_keywords))
regulatory_risk   = min(10, 2 + regulatory_keyword_matches*2)
financial_risk    = 3 (base)
                  + 3 if D/E > 1.0  |  +2 if D/E 0.5-1.0  |  -1 if net cash
                  + 2 if FCF negative/weak
                  + 1 if fundamental_score <= 4
concentration_risk = 3 (base)
                   + 2 if >= 3 macro headwinds  |  +1 if >= 1 headwind
                   + 2 if SELL signal with strength >= 6

risk_score = round(
    governance_risk  * 0.30
  + regulatory_risk  * 0.25
  + financial_risk   * 0.30
  + concentration_risk * 0.15
)
```

**Stage 2 -- LLM narrative synthesis**

The LLM (Groq in dev, Claude in demo) receives pre-computed scores and
sentinel flags.  It synthesises:
- `governance_flags[]` -- specific governance concerns with evidence
- `regulatory_risks[]` -- regulatory / legal exposures
- `fraud_indicators[]` -- accounting or conduct red flags
- `concentration_risks[]` -- customer/geo/revenue dependency flags
- `risk_recommendation` -- validated against allowed values
- `summary` -- 2-3 sentence PM-ready risk summary

LLM output is merged (union, deduplicated) with pre-detected sentinel flags
so the output is always enriched by deterministic detection regardless of
LLM availability.

**Sentinel keyword sets (pure Python, no external deps):**

- `_FRAUD_KEYWORDS`: fraud, scam, restatement, whistleblower, insider
  trading, manipulation, round-tripping, money laundering ...
- `_REGULATORY_KEYWORDS`: sebi, investigation, probe, notice, fine, penalty,
  nclt, cci, rbi directive, ed raid, cbi ...
- `_GOVERNANCE_KEYWORDS`: promoter pledge, related party, auditor resignation,
  ceo resign, rights issue dilution, preferential allotment ...

**Error convention:**
Never raises.  On any failure, `RiskAnalysis.error` is set and
`risk_score` defaults to 5 (unknown/neutral).

---

### Modified: `backend/graph/nodes.py`

Replaced the Phase 3 stub `_risk_impl` with a real delegate:

```python
# Before (stub):
def _risk_impl(state: InvestmentState) -> dict[str, Any]:
    logger.info("risk_node: STUB -- Risk Officer not yet implemented (T-039)")
    return {"risk": {"error": "not_implemented: risk_officer stub (T-039)", ...}}

# After (T-037):
def _risk_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = run_risk_analysis(state)
    partial["current_node"] = NODE_RISK
    return partial
```

Added import:
```python
from backend.agents.risk_officer import run_risk_analysis
```

The `_persist_after(profile_node(_risk_impl, NODE_RISK), NODE_RISK)` wrapper
chain (from T-033 and T-036) is unchanged -- persistence and profiling still
apply.

---

### New file: `backend/tests/unit/test_risk_officer.py`

76 unit tests across 12 test classes:

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestCollectAllText` | 5 | String flattening, list fields, case normalisation |
| `TestExtractSentinelFlags` | 8 | Keyword detection; SEBI → regulatory; fraud → fraud; pledging → governance |
| `TestScoreRisk` | 10 | Clean/risky companies; D/E bands; FCF impact; red flag counts; bounds |
| `TestDetermineConcentrationFlags` | 6 | Macro headwinds, sector impact, SELL signal, high D/E |
| `TestDetermineRiskRecommendation` | 3 | Band mapping: 1-3 → proceed, 4-6 → monitor, 7-10 → avoid |
| `TestBuildRiskPrompt` | 8 | Company name, scores, red flags, headwinds, ASCII-only, N/A formatting |
| `TestRunRiskAnalysisCore` | 11 | Clean/risky company; SEBI flag; fraud → critical; frozen model; JSON-safe; empty research; LLM errors |
| `TestRunRiskAnalysisNode` | 9 | State in/out; required keys; missing ticker; None research; JSON-safe |
| `TestRiskAnalysisSchemaValidation` | 8 | Pydantic bounds (score 0 rejected, 11 rejected); defaults; frozen; round-trip |
| `TestSystemPrompt` | 5 | Content checks; ASCII-only; mentions key dimensions |
| `TestTracingIntegration` | 2 | `__wrapped__` present; callable |
| (standalone tests) | 1 | `_determine_risk_recommendation` edge cases |

---

## Design Decisions

**Why keyword scanning before the LLM?**
Deterministic detection guarantees that SEBI notices and fraud keywords
always surface in `critical_flags` regardless of LLM behaviour or quota
errors.  The LLM cannot "miss" a SEBI investigation if the keyword scanner
already found it.

**Why merge LLM output with sentinel flags?**
The LLM may expand on, confirm, or refute sentinel flags.  Merging (union,
deduplicated by 60-char prefix) ensures we get the richest possible flag
list without duplicates.

**Why four separate sub-scores?**
The Portfolio Manager and Contrarian Investor agents downstream can inspect
individual dimensions (e.g. "high governance risk but low financial risk")
rather than a single opaque number.  This mirrors how real investment
committees communicate risk.

**Why is `risk_recommendation` validated on the LLM's output?**
The LLM may hallucinate an invalid string.  If the returned recommendation
is not one of the three allowed values, the deterministic score-based
recommendation is used instead.

---

## AIRP Standards Compliance

| Standard | Status |
|----------|--------|
| No `from __future__ import annotations` | OK -- not present |
| Plain ASCII section comments (`# ---`) | OK -- no Unicode box-drawing |
| No bare `# type: ignore` | OK -- none in agent; `[misc]` only in frozen model tests |
| No `type: ignore` that becomes unnecessary when packages installed | OK -- removed; uses `hasattr` pattern |
| Tools never raise -- return error model on failure | OK |
| `@traced_agent` applied to LangGraph node | OK |
| `_run_risk_analysis_core` separated for testability | OK |
| All lines <= 88 bytes | OK |
| Two-stage pipeline: deterministic then LLM | OK |

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/debate-risk-officer
```

### 2. Place the files

Copy the following files into your local repository:

```
backend/agents/risk_officer.py          (new)
backend/tests/unit/test_risk_officer.py (new)
backend/graph/nodes.py                  (modified -- replace stub)
```

### 3. Set environment and run tests

**Windows CMD:**
```cmd
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_risk_officer.py -v --tb=short
```

**Git Bash / Mac / Linux:**
```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_risk_officer.py -v --tb=short
```

Expected: **76 passed**.

### 4. Run the full test suite to confirm no regressions

```bash
python -m pytest --tb=short -q
```

Expected: all existing tests continue to pass.

### 5. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/agents/risk_officer.py \
        backend/tests/unit/test_risk_officer.py \
        backend/graph/nodes.py
git commit -m "feat(agents): add Risk Officer agent with deterministic scoring and LLM synthesis"
```

Black / isort may auto-fix formatting.  If the commit is rejected by
pre-commit hooks:

```bash
git add .
git commit -m "feat(agents): add Risk Officer agent with deterministic scoring and LLM synthesis"
```

### 6. Push and open PR

```bash
git push -u origin feat/debate-risk-officer
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**
```
feat(agents): T-037 Risk Officer agent with deterministic risk scoring
```

**PR description:**

```markdown
## Summary

Implements the Risk Officer agent (T-037) -- the fifth of eight investment
committee agents.  The Risk Officer reads all four research agent outputs and
produces a structured `RiskAnalysis` with governance flags, regulatory risks,
fraud indicators, concentration risks, and a composite risk score.

## Changes

- `backend/agents/risk_officer.py` -- Full Risk Officer agent implementation
  with two-stage pipeline: deterministic keyword scanning + LLM narrative
  synthesis
- `backend/tests/unit/test_risk_officer.py` -- 76 unit tests covering all
  pure functions, the full agent core, the LangGraph node, error paths,
  and Pydantic schema validation
- `backend/graph/nodes.py` -- Replaced Phase 3 stub `_risk_impl` with real
  delegate to `run_risk_analysis`

## Testing

- 76 unit tests: `python -m pytest backend/tests/unit/test_risk_officer.py -v`
- Full suite regression: `python -m pytest --tb=short -q`
- All external calls (LLM, APIs) mocked -- no network required

## LangSmith Trace

Tracing is automatic via `@traced_agent("risk_officer")`.
Active when `LANGCHAIN_TRACING_V2=true` and `LANGSMITH_API_KEY` are set.

## Related Issues

Closes #37
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

Next task: **T-038** -- Build Contrarian Investor agent.

Branch: `feat/debate-contrarian-investor`

The Contrarian reads the full `InvestmentState` (all research outputs +
`RiskAnalysis`) and produces a `ContrarianReport` with `counter_arguments[]`,
`overlooked_risks[]`, `bear_conviction` score, and `strongest_argument`.