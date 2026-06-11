# T-027 — Write Unit Tests for All 4 Research Agents

**Phase:** 2 — Research Agents
**Week:** 05
**Branch:** `feat/agent-research-tests`
**Task status:** Ready to merge

---

## Overview

T-027 produces a single consolidated test file —
`backend/tests/unit/test_research_agents.py` — that fills the coverage gaps
left by the individual agent test files written in T-022 through T-025.

**Acceptance criteria:**
- >85% coverage across all 4 research agent modules
- All schema validations tested (Pydantic ValidationError paths)
- Error paths covered when tools return empty data
- All tool calls mocked — no network, no LLM quota

**What the individual files already cover (do NOT duplicate):**
- Pure function unit tests (`compute_rsi`, `_score_article`, etc.)
- Happy-path `_run_*_core` and `run_*` node tests
- LLM mock and fallback summary tests

**What T-027 adds (gap coverage):**

| Gap | Test classes |
|-----|-------------|
| Pydantic field constraints (ValidationError) | `TestFundamentalAnalystSchemaValidation`, `TestTechnicalAnalystSchemaValidation`, `TestSentimentAnalystSchemaValidation`, `TestMacroAnalystSchemaValidation` |
| Tools returning `{}` / sparse / minimal data | `TestFundamentalAnalystEmptyData`, `TestTechnicalAnalystEmptyData`, `TestSentimentAnalystEmptyData`, `TestMacroAnalystEmptyData` |
| `tool.invoke()` raises exception (not error dict) | `TestFundamentalAnalystErrorPaths`, `TestTechnicalAnalystErrorPaths`, `TestSentimentAnalystErrorPaths`, `TestMacroAnalystErrorPaths` |
| State dict key + JSON-safe contract (all agents) | `TestAllAgentsNodeContract` |
| `@traced_agent` structural check | `TestAllAgentsTracingIntegration` |

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
git checkout -b feat/agent-research-tests
```

---

## 3. File to Create

| File | Path |
|------|------|
| Tests | `backend/tests/unit/test_research_agents.py` |
| Docs | `docs/week-05/T-027-research-agent-unit-tests.md` |

Only one new Python file. The four existing individual test files are
**not modified** — T-027 adds to coverage, not replaces existing tests.

---

## 4. Section Comments Reminder

Plain ASCII `# ---` dividers only. No Unicode box-drawing characters.

---

## 5. Run Pre-commit Hooks

```bash
black backend/tests/unit/test_research_agents.py
isort backend/tests/unit/test_research_agents.py
flake8 backend/tests/unit/test_research_agents.py
```

All must produce zero output.

---

## 6. Run the Tests

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_research_agents.py -v
```

Expected: **117 tests**, all pass.

Key tests to verify (acceptance criteria):

```
TestFundamentalAnalystSchemaValidation::test_score_below_minimum_raises   PASSED
TestFundamentalAnalystSchemaValidation::test_score_above_maximum_raises   PASSED
TestFundamentalAnalystSchemaValidation::test_missing_score_raises         PASSED
TestFundamentalAnalystEmptyData::test_empty_financials_dict_no_crash      PASSED
TestFundamentalAnalystEmptyData::test_empty_financials_dict_score_at_minimum  PASSED
TestFundamentalAnalystEmptyData::test_both_tools_empty_dict_no_crash      PASSED
TestFundamentalAnalystErrorPaths::test_both_tools_raise_returns_valid_model  PASSED
TestTechnicalAnalystEmptyData::test_empty_ohlcv_list_returns_error_model  PASSED
TestTechnicalAnalystEmptyData::test_all_same_price_candles                PASSED
TestSentimentAnalystEmptyData::test_zero_articles_returns_neutral_score   PASSED
TestSentimentAnalystEmptyData::test_article_counts_sum_to_total           PASSED
TestMacroAnalystEmptyData::test_all_none_macro_data_no_crash              PASSED
TestMacroAnalystEmptyData::test_all_none_produces_valid_labels            PASSED
TestAllAgentsNodeContract::test_fa_output_json_safe                       PASSED
TestAllAgentsNodeContract::test_ta_output_json_safe                       PASSED
TestAllAgentsNodeContract::test_sa_output_json_safe                       PASSED
TestAllAgentsNodeContract::test_ma_output_json_safe                       PASSED
TestAllAgentsTracingIntegration::test_fundamental_analyst_node_is_traced  PASSED
TestAllAgentsTracingIntegration::test_all_node_names_preserved            PASSED
```

Run with coverage to verify the >85% threshold:

```bash
python -m pytest backend/tests/unit/ -v --tb=short \
  --cov=backend/agents \
  --cov-report=term-missing \
  --cov-fail-under=85
```

Run the full unit suite to confirm no regressions:

```bash
python -m pytest backend/tests/unit/ -v --tb=short
```

---

## 7. Commit

```bash
git add backend/tests/unit/test_research_agents.py
git add docs/week-05/T-027-research-agent-unit-tests.md
```

```bash
git commit -m "test(agents): add consolidated research agent tests -- schema, empty data, error paths"
```

---

## 8. Push

```bash
git push origin feat/agent-research-tests
```

---

## 9. Pull Request

- **Base branch:** `main`
- **Compare branch:** `feat/agent-research-tests`
- **Title:** `test(agents): T-027 — Consolidated research agent unit tests`

**PR Description:**

```
## Summary

Adds `test_research_agents.py` — a consolidated test suite covering three
coverage gap areas across all four Phase 2 research agents that the individual
agent test files (T-022 through T-025) do not fully address: Pydantic schema
validation (ValidationError on out-of-range fields and missing required
fields), empty/sparse data paths (tools returning `{}` or `[]` instead of
populated dicts), and exception-raising tool paths (tool.invoke() throws
instead of returning an error dict). Also adds cross-agent state dict contract
tests and structural verification that @traced_agent was applied to all nodes.

## Changes

- `backend/tests/unit/test_research_agents.py` — 117 new tests across
  14 test classes covering all 4 research agents:
  - 4 × SchemaValidation classes — Pydantic ValidationError paths
  - 4 × EmptyData classes — tools return {}, [], None values
  - 4 × ErrorPaths classes — tool.invoke() raises exception
  - TestAllAgentsNodeContract — state key + JSON-safe checks for all 4
  - TestAllAgentsTracingIntegration — @traced_agent structural check

## Testing

```
python -m pytest backend/tests/unit/test_research_agents.py -v
# 117 passed
```

All schema validations tested:
- FundamentalAnalysis: score constraints (ge=1, le=10), missing required
- TechnicalAnalysis: signal_strength constraints (ge=1, le=10)
- SentimentAnalysis: sentiment_score constraints (ge=-1.0, le=1.0),
  articles_analysed (ge=0)
- MacroAnalysis: missing required fields raise ValidationError

All error paths covered:
- Both tools raise exception -> valid model returned, error=None or
  error set appropriately per agent convention
- Tools return {} (no error key, no data) -> graceful degradation
- ChromaDB raises -> non-fatal for sentiment and macro agents
- LLM returns invalid JSON -> fallback summary used, error=None

## Related Issues

Closes #27
```

---

## 10. CI Gate

**Backend CI:** mypy, flake8, pytest — all must pass.
**Frontend CI:** `continue-on-error: true` — does not block merge.

---

## 11. Merge

1. Squash and merge
2. Squash commit: `test(agents): T-027 — Consolidated research agent unit tests (#27)`
3. Delete branch

```bash
git checkout main
git pull origin main
git branch -d feat/agent-research-tests
```

---

## 12. Acceptance Criteria Mapping

| Criterion | How verified | Test count |
|-----------|-------------|-----------|
| >85% coverage | `--cov-fail-under=85` on `backend/agents` | Full suite |
| All schema validations tested | 4 × SchemaValidation classes | 42 tests |
| Error paths covered (empty data) | 4 × EmptyData classes | 40 tests |
| Error paths covered (tool raises) | 4 × ErrorPaths classes | 20 tests |
| All tool calls mocked | `patch()` on every tool import | All 117 |
| JSON-safe output | `model_dump(mode="json")` + `json.dumps()` | 4 tests |
| Tracing applied | `__wrapped__` attribute check | 5 tests |

---

*T-027 complete. Phase 2 research agents fully tested.*
*Next: T-028 (data layer documentation) or T-029 (LangGraph Planner node).*