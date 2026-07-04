# T-025 — Build Macro Economist Agent

**Phase:** 2 — Research Agents
**Week:** 05
**Branch:** `feat/agent-macro`
**Task status:** Ready to merge

---

## Overview

T-025 builds the Macro Economist Agent — the fourth and final parallel research
agent in the AIRP investment committee. This agent assesses India's
macroeconomic environment and translates it into sector-specific tailwinds and
headwinds for the company under analysis.

**Agent persona:** Macro economist with 20 years covering Indian equity markets.
Cuts through noise to identify the macro forces that actually move stock prices.

**Tools used:**

- `fetch_macro_data` (RBI repo rate, CPI inflation, India GDP growth)
- `semantic_search` (ChromaDB `airp_news` collection — sector macro news, non-fatal)

**Output:** `MacroAnalysis` (macro_environment, sector_impact, rate_stance,
rate_direction, inflation_trend, tailwinds, headwinds, global_factors,
india_specific, summary)

**Key acceptance criterion:** Agent correctly identifies a rate hike environment
(RBI repo rate >= 7.0%) as a **headwind** for banking stocks (NIM compression,
higher cost of funds, rising credit risk).

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
git checkout -b feat/agent-macro
git branch
# * feat/agent-macro
#   main
```

---

## 3. Files to Create

| File  | Path                                                |
| ----- | --------------------------------------------------- |
| Agent | `backend/agents/macro_economist.py`                 |
| Tests | `backend/tests/unit/test_macro_economist.py`        |
| Docs  | `docs/week-05/T-025-build-macro-economist-agent.md` |

The `docs/week-05/` folder already exists from T-024. No need to create it.

---

## 4. Implementation Notes

### 4.1 Section Comments — Plain ASCII Only

All section dividers use `# ---` (plain ASCII). No Unicode box-drawing
characters. This rule applies from T-024 onwards across all new agent files.

Correct:

```python
# ---------------------------------------------------------------------------
# Constants -- RBI rate thresholds
# ---------------------------------------------------------------------------
```

### 4.2 No `from __future__ import annotations`

Absent in the agent file by design (Pydantic v2 rule). Present in the test
file — safe there.

### 4.3 Architecture: Deterministic First, LLM Second

The scoring architecture has three layers:

```
Layer 1 — Deterministic (pure Python, no LLM):
  _classify_rate_stance()        RBI rate -> accommodative/neutral/
                                 calibrated_tightening/tightening
  _classify_rate_direction()     rate level vs midpoint -> cutting/holding/hiking
  _classify_inflation_trend()    CPI -> falling/stable/rising
  _classify_macro_environment()  composite -> favourable/neutral/unfavourable
  _detect_sector()               company name keyword -> 9 sector buckets
  _classify_sector_impact()      sector + stance -> tailwind/neutral/headwind
  _build_tailwinds_headwinds()   lookup table + GDP/CPI supplements

Layer 2 — LLM synthesis (narrative only):
  Expands tailwinds/headwinds with sector-specific language
  Identifies global factors (Fed, oil, USD)
  Identifies India-specific factors
  Writes 2-3 sentence summary

Layer 3 — Merge:
  macro_environment and sector_impact always from Layer 1
  rate_stance, rate_direction, inflation_trend always from Layer 1
  tailwinds/headwinds: LLM output when available, deterministic as fallback
```

### 4.4 Sector Detection

Eight canonical sectors, keyword-matched against the company name:
`banking`, `nbfc`, `it_services`, `energy`, `pharma_healthcare`,
`auto`, `fmcg`, `infra_industrials`, plus `diversified` as default.

This is sufficient for the acceptance criteria and avoids a ticker API
round-trip. The ticker resolver gap is addressed in T-029 (Planner node).

### 4.5 Rate Thresholds (RBI Historical Norms)

| Repo rate   | Stance                  |
| ----------- | ----------------------- |
| < 5.0%      | `accommodative`         |
| 5.0 – 5.99% | `neutral`               |
| 6.0 – 6.99% | `calibrated_tightening` |
| ≥ 7.0%      | `tightening`            |

These mirror the actual RBI rate cycle: 4.0% (COVID 2020), 6.5% (post-hike
2023), 7.25% (historical peak 2012).

### 4.6 Banking Headwind Logic (Acceptance Criteria)

When `rate_stance = "tightening"` AND `sector = "banking"`:

- `sector_impact = "headwind"` (from `_SECTOR_MACRO_RULES` lookup)
- Headwinds include: NIM compression, higher cost of funds, rising credit risk
- This covers the full path: `fetch_macro_data` returns `repo_rate=7.5` →
  `_classify_rate_stance(7.5) = "tightening"` →
  `_detect_sector("HDFC Bank") = "banking"` →
  `_classify_sector_impact("banking", "tightening") = "headwind"`

---

## 5. Run Pre-commit Hooks Locally

```bash
black backend/agents/macro_economist.py
isort backend/agents/macro_economist.py
flake8 backend/agents/macro_economist.py

black backend/tests/unit/test_macro_economist.py
isort backend/tests/unit/test_macro_economist.py
flake8 backend/tests/unit/test_macro_economist.py
```

All must produce zero output.

---

## 6. Run the Tests

```bash
set ENVIRONMENT=test
```

```bash
python -m pytest backend/tests/unit/test_macro_economist.py -v
```

Key tests to verify (acceptance criteria):

```
TestClassifySectorImpact::test_banking_tightening_is_headwind     PASSED
TestClassifySectorImpact::test_banking_calibrated_tightening_is_headwind  PASSED
TestClassifySectorImpact::test_nbfc_tightening_is_headwind        PASSED
TestClassifySectorImpact::test_auto_tightening_is_headwind        PASSED
TestRunMacroAnalysisCore::test_tightening_rate_banking_headwind   PASSED
TestRunMacroAnalysisNode::test_tightening_banking_headwind_full_pipeline  PASSED
```

Run the full unit suite:

```bash
python -m pytest backend/tests/unit/ -v --tb=short
```

---

## 7. Commit

```bash
git add backend/agents/macro_economist.py
git add backend/tests/unit/test_macro_economist.py
git add docs/week-05/T-025-build-macro-economist-agent.md
```

```bash
git commit -m "feat(agents): add Macro Economist agent with rate cycle and sector impact analysis"
```

---

## 8. Push

```bash
git push origin feat/agent-macro
```

---

## 9. Pull Request

- **Base branch:** `main`
- **Compare branch:** `feat/agent-macro`
- **Title:** `feat(agents): T-025 — Macro Economist Agent`

**PR Description:**

```
## Summary

Implements the Macro Economist Agent (T-025), the fourth and final parallel
research agent in the AIRP investment committee. Fetches live India macro data
(RBI repo rate, CPI, GDP) via `fetch_macro_data`, classifies the rate stance
and macro environment deterministically, maps the company to one of nine
canonical sectors via keyword matching, and derives sector-specific macro
impact (tailwind/neutral/headwind) from a lookup table. The LLM is used only
for narrative synthesis (tailwinds, headwinds, global/India factors, summary).

## Changes

- `backend/agents/macro_economist.py` — complete Macro Economist Agent
  - `_classify_rate_stance()` — RBI rate -> stance label (4 bands)
  - `_classify_rate_direction()` — direction inference vs neutral midpoint
  - `_classify_inflation_trend()` — CPI -> falling/stable/rising
  - `_classify_macro_environment()` — composite environment classification
  - `_detect_sector()` — company name keyword -> 9 sector buckets
  - `_classify_sector_impact()` — sector + stance -> tailwind/neutral/headwind
  - `_build_tailwinds_headwinds()` — lookup table + GDP/CPI supplements
  - `_build_macro_prompt()` — LLM prompt builder
  - `_run_macro_analysis_core()` — testable core logic
  - `run_macro_analysis()` — LangGraph node entry point
- `backend/tests/unit/test_macro_economist.py` — full unit test suite
- `docs/week-05/T-025-build-macro-economist-agent.md` — this workflow document

## Testing

```

python -m pytest backend/tests/unit/test_macro_economist.py -v

```

Acceptance criteria verified:
- Rate hike environment (repo_rate=7.5%) correctly identified as HEADWIND
  for banking, NBFC, and auto sectors
- Accommodative stance (repo_rate=4.0%) correctly identified as TAILWIND
  for banking and auto sectors
- IT services correctly identified as NEUTRAL in tightening environment
- ChromaDB failure is non-fatal
- LLM failure produces fallback summary, error=None

## Related Issues

Closes #25
```

---

## 10. CI Gate

**Backend CI (`backend-ci`):** mypy, flake8, pytest unit tests — all must pass.
**Frontend CI (`frontend-ci`):** `continue-on-error: true` — does not block merge.

---

## 11. Merge

1. Squash and merge on GitHub
2. Squash commit message: `feat(agents): T-025 — Macro Economist Agent (#25)`
3. Delete branch on GitHub

```bash
git checkout main
git pull origin main
git branch -d feat/agent-macro
```

---

## 12. Acceptance Criteria Mapping

| Criterion                         | Test(s)                                                                                                                          | Status   |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | -------- |
| Rate hike → banking headwind      | `test_banking_tightening_is_headwind`, `test_tightening_rate_banking_headwind`, `test_tightening_banking_headwind_full_pipeline` | Verified |
| Rate hike → NBFC headwind         | `test_nbfc_tightening_is_headwind`, `test_nbfc_tightening_headwind`                                                              | Verified |
| Rate hike → auto headwind         | `test_auto_tightening_is_headwind`, `test_auto_tightening_headwind`                                                              | Verified |
| Accommodative → banking tailwind  | `test_banking_accommodative_is_tailwind`, `test_accommodative_rate_banking_tailwind`                                             | Verified |
| IT services neutral in tightening | `test_it_tightening_is_neutral`                                                                                                  | Verified |
| Agent never raises                | `test_never_raises_on_catastrophic_failure`                                                                                      | Verified |
| ChromaDB failure non-fatal        | `test_chroma_failure_is_non_fatal`                                                                                               | Verified |
| LLM failure → fallback            | `test_llm_failure_uses_fallback_summary`                                                                                         | Verified |
| All-None macro data handled       | `test_none_macro_data_fields_handled`                                                                                            | Verified |

---

_T-025 complete. All four parallel research agents are now built._
_Next: T-026 or T-029 (LangGraph Planner node / ticker resolver)._
