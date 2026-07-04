# T-038 -- Build Contrarian Investor Agent

**Phase:** 4 -- Debate Engine & Advanced Agents
**Week:** 10
**Branch:** `feat/debate-contrarian`
**Task status:** Complete

---

## Overview

T-038 builds the **Contrarian Investor agent** -- the sixth of eight investment
committee agents. The Contrarian's only job is to disagree: it reads all five
prior agent outputs (Fundamental, Technical, Sentiment, Macro, Risk) and
produces a `ContrarianReport` with named counter-arguments, overlooked risks,
and a bear conviction score that drives the debate loop routing.

**Acceptance criteria (all must pass):**

- Agent produces at least 3 distinct counter-arguments for any bullish stock
- Validated on TCS profile (fund score 9/10, BUY signal) and
  Infosys profile (fund score 8/10, overbought RSI)
- Outputs structured `ContrarianReport` with all required fields
- `bear_conviction` in `[1, 10]`
- Agent never raises -- always returns dict with `contrarian` key
- LangSmith trace visible (`@traced_agent` applied)

Also in this PR: **T-037 CI fix** -- removes `type: ignore[misc]` on
`__wrapped__` attribute access in `test_risk_officer.py`, which triggered
`warn_unused_ignores` under `mypy --strict` when `langsmith` is installed.

---

## Files Changed

| File                                             | Change                                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `backend/agents/contrarian_investor.py`          | **New** -- full Contrarian Investor agent                                            |
| `backend/tests/unit/test_contrarian_investor.py` | **New** -- 83 unit tests                                                             |
| `backend/graph/nodes.py`                         | **Modified** -- replaced stub `_contrarian_impl` with real delegate; added import    |
| `backend/tests/unit/test_risk_officer.py`        | **Modified** -- T-037 CI fix: removed `# type: ignore[misc]` on `__wrapped__` access |

---

## T-037 CI Fix: mypy `warn_unused_ignores`

### Root cause

`mypy --strict` implies `--warn-unused-ignores`. In the test file, line 1149
contained:

```python
assert callable(run_risk_analysis.__wrapped__)  # type: ignore[misc]
```

When `langsmith` is **not** installed (local dev), mypy cannot resolve
`__wrapped__` on the callable type, so `[misc]` is needed.

When `langsmith` **is** installed (CI), `functools.wraps` makes `__wrapped__`
visible enough that mypy no longer flags it -- so `[misc]` becomes unused,
and `warn_unused_ignores` fires as a new error.

### Fix

Replaced direct attribute access with `getattr` + `callable` check, matching
the pattern used in all other tracing integration tests:

```python
# Before (breaks CI under strict mypy + langsmith installed):
assert callable(run_risk_analysis.__wrapped__)  # type: ignore[misc]

# After (works regardless of what packages are installed):
assert hasattr(run_risk_analysis, "__wrapped__")
wrapped = getattr(run_risk_analysis, "__wrapped__", None)
assert wrapped is not None
assert callable(wrapped)
```

`getattr` with a default is **not** a `B009` flake8 violation because it
uses a default argument (three-argument form), unlike
`getattr(obj, "constant")` (two-argument form) which B009 flags.

The two `# type: ignore[misc]` comments on frozen-model mutation tests
(lines 706 and 1091) are **kept** -- they are always necessary because mypy
`--strict` always flags assignment to a frozen Pydantic model attribute as
`[misc]`, regardless of whether pydantic is installed. This matches the
existing pattern in `test_research_agents.py` line 314 which passes CI.

---

## What Was Built (T-038)

### New file: `backend/agents/contrarian_investor.py`

Two-stage pipeline:

**Stage 1 -- Deterministic (no LLM, always executes)**

| Function                        | Purpose                                                          |
| ------------------------------- | ---------------------------------------------------------------- |
| `_build_counter_arguments(...)` | Builds >= 3 specific counter-arguments from all research data    |
| `_score_bear_conviction(...)`   | Computes `bear_conviction` 1-10 from strength of bullish signals |

**Counter-argument logic (`_build_counter_arguments`):**

Each argument names the agent being challenged and cites specific data:

- Fundamental high score (>= 7) -> valuation risk at PE, or sustainability challenge
- High ROE (>= 20%) -> mean reversion / competition inevitability
- Low D/E (< 0.1) -> growth exhaustion signal
- High D/E (> 0.8) -> leverage risk in rising rate environment
- BUY signal with strength >= 6 -> momentum chase argument
- HOLD signal -> capital trap argument
- RSI > 65 -> overbought argument
- Price >= 90% of 52w high -> near-top risk
- Positive sentiment (> 0.2) -> peak positioning contrarian signal
- Low risk score (<= 4) -> complacency argument
- Neutral/favourable macro with headwinds -> direction-of-travel argument

**Bear conviction scoring (`_score_bear_conviction`):**

```
base = 1  (mild scepticism)
+2  if fundamental score >= 8   (over-loved quality)
+1  if BUY signal strength >= 6  (momentum chase)
+1  if RSI > 65                  (overbought)
+1  if price >= 90% of 52w high  (near-top)
+1  if sentiment > 0.3           (peak positioning)
+1  if risk_score <= 3           (complacency)
+1  if >= 5 counter-arguments    (many attack angles)
+1  if D/E < 0.1                 (growth exhaustion)
+1  if D/E > 1.0                 (leverage risk)
clip to [1, 10]
```

**Stage 2 -- LLM synthesis**

The LLM receives all pre-computed arguments and is instructed to:

- Extend/deepen the arguments (not repeat them)
- Add 1-3 overlooked risks no other agent flagged
- Identify the single strongest argument
- Write the bear-case summary

LLM output is merged (deduplicated by 60-char prefix) with deterministic args.

**Error convention:** Never raises. On any failure, `ContrarianReport.error`
is set but `counter_arguments` still contains the deterministic pre-computed
arguments, so acceptance criteria (>= 3 args) is met even with LLM failures.

---

### Modified: `backend/graph/nodes.py`

Added import and replaced stub with real delegate:

```python
# Added import (alphabetical order maintained):
from backend.agents.contrarian_investor import run_contrarian_analysis

# Replaced:
def _contrarian_impl(state: InvestmentState) -> dict[str, Any]:
    logger.info("contrarian_node: STUB -- not yet implemented (T-040)")
    return {"contrarian": {"error": "not_implemented", ...}, ...}

# With:
def _contrarian_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = run_contrarian_analysis(state)
    partial["current_node"] = NODE_CONTRARIAN
    return partial
```

The `_persist_after(profile_node(...))` wrapper chain is unchanged.

**graph_skeleton tests still pass** because `contrarian_node(_make_state())`
with `ticker=""` triggers the early-return error path (no LLM call needed).

---

### New file: `backend/tests/unit/test_contrarian_investor.py`

83 unit tests across 9 test classes:

| Class                                  | Tests | What it covers                                                                               |
| -------------------------------------- | ----- | -------------------------------------------------------------------------------------------- |
| `TestConstants`                        | 1     | `MIN_COUNTER_ARGUMENTS == 3`                                                                 |
| `TestBuildCounterArguments`            | 15    | TCS/Infosys acceptance criteria; PE/ROE/D/E/RSI/sentiment/risk challenges; caps; empty dicts |
| `TestScoreBearConviction`              | 9     | Bullish/bearish profiles; each scoring dimension; bounds                                     |
| `TestBuildContrarianPrompt`            | 11    | Company/ticker/scores in prompt; ASCII-only; N/A formatting                                  |
| `TestRunContrarianAnalysisCore`        | 14    | TCS & Infosys acceptance criteria; LLM merge; failure paths; frozen model; JSON-safe         |
| `TestRunContrarianAnalysisNode`        | 11    | State in/out; round count increment; missing ticker; None research; acceptance criteria      |
| `TestContrarianReportSchemaValidation` | 9     | Pydantic bounds (0 rejected, 11 rejected); defaults; frozen; round-trip                      |
| `TestSystemPrompt`                     | 8     | Content checks; ASCII-only; required keys present                                            |
| `TestTracingIntegration`               | 2     | `__wrapped__` present; callable (safe pattern, no `type: ignore`)                            |

---

## AIRP Standards Compliance

| Standard                                                      | Status                                           |
| ------------------------------------------------------------- | ------------------------------------------------ |
| No `from __future__ import annotations`                       | OK                                               |
| Plain ASCII section comments (`# ---`)                        | OK                                               |
| No bare `# type: ignore` in agent file                        | OK -- zero in `contrarian_investor.py`           |
| No `type: ignore` that becomes unused when packages installed | OK -- fixed in `test_risk_officer.py`            |
| `# type: ignore[misc]` on frozen model mutations in tests     | OK -- always necessary, matches existing pattern |
| Agent never raises                                            | OK                                               |
| `@traced_agent` applied                                       | OK                                               |
| `_run_contrarian_analysis_core` separated for testability     | OK                                               |
| All lines <= 88 bytes                                         | OK                                               |
| All ASCII                                                     | OK                                               |

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/debate-contrarian
```

### 2. Place the files

```
backend/agents/contrarian_investor.py           (new)
backend/tests/unit/test_contrarian_investor.py  (new)
backend/graph/nodes.py                          (modified)
backend/tests/unit/test_risk_officer.py         (modified -- T-037 CI fix)
```

### 3. Set environment and run tests

**Windows CMD:**

```cmd
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_contrarian_investor.py -v --tb=short
python -m pytest backend/tests/unit/test_risk_officer.py -v --tb=short
```

**Git Bash / Mac / Linux:**

```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_contrarian_investor.py -v --tb=short
python -m pytest backend/tests/unit/test_risk_officer.py -v --tb=short
```

Expected: **83 passed** (contrarian), **79 passed** (risk officer).

### 4. Run full suite

```bash
python -m pytest --tb=short -q
```

Expected: all tests pass.

### 5. Commit

```bash
git add backend/agents/contrarian_investor.py \
        backend/tests/unit/test_contrarian_investor.py \
        backend/graph/nodes.py \
        backend/tests/unit/test_risk_officer.py \
        docs/week-10/T-038-contrarian-investor.md
git commit -m "feat(agents): add Contrarian Investor agent with deterministic counter-arguments"
```

If pre-commit auto-fixes formatting:

```bash
git add .
git commit -m "feat(agents): add Contrarian Investor agent with deterministic counter-arguments"
```

### 6. Push and open PR

```bash
git push -u origin feat/debate-contrarian
```

---

## PR Details

**PR title:**

```
feat(agents): T-038 Contrarian Investor agent + T-037 mypy CI fix
```

**PR description:**

```markdown
## Summary

Implements the Contrarian Investor agent (T-038) and fixes the mypy
`warn_unused_ignores` CI failure from T-037.

The Contrarian reads all five prior agent outputs and produces a
`ContrarianReport` with >= 3 counter-arguments for any bullish stock,
validated on TCS and Infosys profiles. The `bear_conviction` score (1-10)
drives the LangGraph debate loop routing.

## Changes

- `backend/agents/contrarian_investor.py` -- Full Contrarian Investor agent
  with two-stage pipeline: deterministic counter-argument generation + LLM
  narrative synthesis
- `backend/tests/unit/test_contrarian_investor.py` -- 83 unit tests including
  TCS and Infosys acceptance-criteria validation
- `backend/graph/nodes.py` -- Replaced Phase 3 stub `_contrarian_impl` with
  real delegate; added `run_contrarian_analysis` import
- `backend/tests/unit/test_risk_officer.py` -- T-037 CI fix: removed
  `# type: ignore[misc]` on `__wrapped__` attribute access; replaced with
  safe `getattr(..., None)` pattern that works regardless of installed packages

## Testing

- 83 new contrarian tests: `python -m pytest backend/tests/unit/test_contrarian_investor.py`
- 79 risk officer tests (unchanged count): `python -m pytest backend/tests/unit/test_risk_officer.py`
- Full suite: `python -m pytest --tb=short -q`

## LangSmith Trace

Automatic via `@traced_agent("contrarian_investor")`.

## Related Issues

Closes #38
```

**Squash merge** to main.

---

## After Merge

Next task: **T-039** -- Build Valuation Agent.

Branch: `feat/debate-valuation-agent`

The Valuation Agent runs a DCF model and compares PE/PB/EV-EBITDA vs
sector peers, producing `ValuationOutput` with `intrinsic_value_per_share`,
`upside_downside_pct`, and `valuation_verdict`.
