# T-041 -- Build Portfolio Manager Agent

**Phase:** 4 -- Debate Engine & Advanced Agents
**Week:** 11
**Branch:** `feat/debate-portfolio-mgr`
**Task status:** Complete

---

## Overview

T-041 replaces the T-032-era `portfolio_manager_node` stub with the real
Portfolio Manager agent -- the final, accountable decision-maker of the
8-agent investment committee. Every prior task in Phase 4 (T-037 Risk
Officer, T-038 Contrarian Investor, T-039 Valuation Agent, T-040 debate
loop) produced its own structured output and wrote it into
`InvestmentState`, but nothing read all seven of those outputs together
and turned them into a single verdict. T-041 closes that gap.

The agent's persona is the CIO of a hedge fund. It reads the complete
`InvestmentState` -- `fundamental`, `technical`, `sentiment`, `macro`,
`risk`, `contrarian`, `valuation`, and the full `debate_rounds[]`
transcript built by T-040 -- and produces an `InvestmentDecision`
containing the final `BUY` / `HOLD` / `SELL` verdict, a `conviction_score`
(1-10), `bull_case`, `bear_case`, `price_target`, `time_horizon`,
`key_risks[]`, and `key_catalysts[]`.

**Acceptance criteria (all must pass):**

- Portfolio Manager's decision references specific points from the debate
- Conviction score correlates with quality of analysis

---

## Files Changed

| File                                           | Change                                                                                                                                            |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/agents/output_models.py`              | **Modified** -- added `time_horizon`, `key_risks`, `key_catalysts` fields to `InvestmentDecision`                                                 |
| `backend/agents/portfolio_manager.py`          | **New** -- the full Portfolio Manager agent: deterministic verdict/conviction/weights/horizon/risks/catalysts engine plus LLM narrative synthesis |
| `backend/graph/nodes.py`                       | **Modified** -- `_portfolio_manager_impl` now delegates to `run_portfolio_manager_decision` instead of the T-032 stub; import added               |
| `backend/graph/graph.py`                       | **Modified** -- docstring/comment updates only; topology and wiring were already correct from T-031/T-032 (no edge changes needed)                |
| `backend/tests/unit/test_portfolio_manager.py` | **New** -- unit test suite covering every deterministic helper, the full core agent, the LangGraph node, schema validation, and tracing           |

---

## What Was Built

### New: `backend/agents/portfolio_manager.py`

A two-stage pipeline, following the same pattern established by
`risk_officer.py`, `contrarian_investor.py`, and `valuation_agent.py`:

**Stage 1 -- Deterministic decision (no LLM, fully testable in isolation):**

| Function                          | Purpose                                                                                                                                                                                                                                                                                                                       |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_compute_agent_weights(...)`     | Assigns a 0.0-1.0 weight to each of the 7 prior agents (fundamental and valuation weighted highest, sentiment lowest), zeroing and redistributing weight away from any agent that errored or produced no output, so weights always sum to 1.0                                                                                 |
| `_determine_verdict(...)`         | Two hard gates (risk_score >= 8 forces SELL; overvalued + weak fundamentals forces SELL) followed by a weighted bullish/bearish point tally across all six other agents, with a soft downgrade rule that pulls a marginal BUY down to HOLD when heavy critical flags are present                                              |
| `_score_conviction(...)`          | **The core acceptance-criterion function.** Starts at a neutral baseline and adjusts based on signal _agreement_ across agents, the Contrarian's credibility (`bear_conviction`), missing/errored data, critical flag count, and how many debate rounds were needed -- NOT on how strongly bullish or bearish the signals are |
| `_determine_time_horizon(...)`    | Chooses a holding-period phrase based on what is actually driving the verdict: technically-led calls get 3-6 months, high-margin-of-safety DCF-led BUYs get 3-5 years, everything else gets the standard 12-month review cycle                                                                                                |
| `_build_price_target(...)`        | Formats the Valuation Agent's `intrinsic_value_per_share` into a price-target string paired with the time horizon; returns `None` when no intrinsic value is available                                                                                                                                                        |
| `_build_key_risks(...)`           | Builds the structured `key_risks[]` list: Risk Officer's `critical_flags` first, then the Contrarian's `strongest_argument` and `overlooked_risks`, then any remaining state-level critical flags, de-duplicated and capped at 6                                                                                              |
| `_build_key_catalysts(...)`       | Builds `key_catalysts[]` from macro tailwinds, a DCF-upside re-rating catalyst (when margin of safety is high/moderate), macro headwinds framed as "monitor" items, and fundamental strengths, capped at 5                                                                                                                    |
| `_extract_debate_highlights(...)` | Converts `state["debate_rounds"]` into one human-readable `"Round N: <contrarian challenge>"` line per round, used to ground the LLM prompt in real debate content instead of letting it invent plausible-sounding detail                                                                                                     |

**Stage 2 -- LLM narrative synthesis:**

`_build_portfolio_manager_prompt(...)` hands the LLM every Stage 1 number
explicitly and instructs it not to change them -- its only job is to
write `executive_summary`, `investment_thesis`, `bull_case`, `bear_case`,
`risk_summary`, `valuation_summary`, `contrarian_response`, and a
one-line `summary`. The system prompt requires `investment_thesis` to
name a specific debate-transcript point and `contrarian_response` to
name and directly address the Contrarian's `strongest_argument` --
this is what satisfies the "references specific points from debate"
acceptance criterion at the narrative level, on top of the deterministic
`key_risks` already doing so structurally.

`_run_portfolio_manager_core(...)` orchestrates both stages and never
raises: on any LLM failure (timeout, malformed JSON, provider error) it
falls back to a fully deterministic summary built directly from the
Stage 1 numbers, including a guaranteed `contrarian_response` that names
the strongest argument even without LLM assistance.

### Why conviction tracks _quality_, not _direction_

A literal reading of "conviction score correlates with quality of
analysis" ruled out the simplest implementation (conviction = strength
of the bullish/bearish signal). Instead `_score_conviction` rewards:

- **Agreement** -- when fundamental, technical, sentiment, and valuation
  signals point the same direction, conviction rises; when they
  contradict each other, conviction falls, even if the net verdict is
  unchanged.
- **A weak Contrarian case** (`bear_conviction <= 3`) raises conviction;
  a strong one (`>= 7`) lowers it, on the theory that a credible bear
  case the committee chose to overrule should temper confidence in the
  override.
- **Complete data** -- every missing or errored agent output is a unit
  of missing evidence and directly reduces conviction.
- **Fast consensus** -- reaching a decision in 1 debate round scores
  higher than needing 2, since extra rounds are a direct signal that the
  committee could not agree quickly.

This is verified directly by
`TestScoreConviction.test_agreeing_clean_profile_beats_conflicting_high_risk_profile`,
which constructs two profiles that resolve to the **same nominal BUY
direction** but differ only in internal agreement/risk/debate-length, and
asserts the clean profile scores strictly higher conviction.

### Why `key_risks` / `key_catalysts` are separate from `risk_summary` / prose

The original `InvestmentDecision` schema (T-021) already had a free-text
`risk_summary` field for the memo narrative. The T-041 task spec
explicitly calls for `key_risks[]` and `key_catalysts[]` as discrete
lists -- these feed the Report Generator (T-042) for bullet-point
rendering in the Investment Memo PDF without that task needing to parse
prose back into a list. `risk_summary` remains the narrative companion;
`key_risks` is the structured data.

### Modified: `backend/agents/output_models.py`

Three new fields added to `InvestmentDecision`, all additive and
backward-compatible (existing code that constructs `InvestmentDecision`
without them still works, since all three have defaults):

```python
time_horizon: str = Field(default="12 months", ...)
key_risks: list[str] = Field(default_factory=list, ...)
key_catalysts: list[str] = Field(default_factory=list, ...)
```

### Modified: `backend/graph/nodes.py`

```python
# Before (T-032 stub):
def _portfolio_manager_impl(state: InvestmentState) -> dict[str, Any]:
    logger.info("portfolio_manager_node: STUB -- ...")
    return {"decision": {...hardcoded HOLD/5...}, ...}

# After (T-041):
def _portfolio_manager_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = run_portfolio_manager_decision(state)
    partial["status"] = "completed"
    partial["completed_at"] = datetime.utcnow().isoformat() + "Z"
    partial["current_node"] = NODE_PORTFOLIO_MANAGER
    return partial
```

This follows the identical thin-wrapper pattern already used by
`_risk_impl` and `_valuation_impl` -- delegate to the agent's own node
function, then merge in pipeline bookkeeping fields. No change to
`_persist_after` / `profile_node` composition was needed; T-033 and T-036
already wrap `portfolio_manager_node` correctly.

### `backend/graph/graph.py`

No wiring changes were required -- `NODE_PORTFOLIO_MANAGER` was already
registered and already had its `risk -> valuation -> portfolio_manager ->
END` edge from T-031/T-032. Only the docstring/comment lines that
described it as a "Phase 4 stub (T-042)" were corrected to reflect that
it is now fully implemented as of T-041.

---

## Tests

| Test class                               | What it covers                                                                                                                                                                                                                                                                                                                                                                                 |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TestComputeAgentWeights`                | Weights sum to 1.0, all 7 agents present, errored/empty agents zeroed and redistributed, all-agents-failed degenerate case, fundamental/valuation outweigh sentiment                                                                                                                                                                                                                           |
| `TestDetermineVerdict`                   | Strong bull -> BUY, prohibitive risk hard gate -> SELL, overvalued+weak-fundamentals hard gate -> SELL, weak bearish profile, mixed signals -> HOLD, strong Contrarian downgrades a marginal BUY, verdict always in the allowed set across multiple profiles including the empty-state edge case                                                                                               |
| `TestScoreConviction`                    | Bounds check, the core quality-vs-direction acceptance criterion (clean profile beats conflicting profile at the same nominal verdict), missing data reduces conviction, more debate rounds reduce conviction, high bear_conviction reduces conviction, critical flags reduce conviction                                                                                                       |
| `TestDetermineTimeHorizon`               | HOLD -> quarterly review, technically-driven BUY -> short horizon, high-margin-of-safety BUY -> long horizon, default case -> 12 months                                                                                                                                                                                                                                                        |
| `TestBuildPriceTarget`                   | Missing intrinsic value -> None, correct formatting, non-numeric input handled gracefully                                                                                                                                                                                                                                                                                                      |
| `TestBuildKeyRisks`                      | Critical flags prioritised first, strongest_argument included, capped at 6, fallback text when nothing found, de-duplication across overlapping sources                                                                                                                                                                                                                                        |
| `TestBuildKeyCatalysts`                  | Macro tailwinds included, DCF-upside catalyst generated, capped at 5, fallback text when nothing found                                                                                                                                                                                                                                                                                         |
| `TestExtractDebateHighlights`            | Empty rounds -> empty list, one/two rounds produce correctly-numbered highlights, highlight text contains the actual contrarian challenge                                                                                                                                                                                                                                                      |
| `TestBuildPortfolioManagerPrompt`        | Prompt contains company/ticker, the predetermined verdict/conviction (so the LLM is told, not asked), debate highlights, the Contrarian's strongest argument, key_risks/key_catalysts, and handles a fully-empty state without raising                                                                                                                                                         |
| `TestRunPortfolioManagerCore`            | Returns `InvestmentDecision`, verdict/conviction within bounds, investment_thesis references a named debate round, contrarian_response is always populated, LLM failure produces a valid non-raising fallback with `error is None`, malformed LLM JSON falls back gracefully, empty research dicts handled, key_risks/key_catalysts/time_horizon always populated                              |
| `TestRunPortfolioManagerDecisionNode`    | Full LangGraph node contract: `decision`/`final_verdict`/`conviction_score`/`price_target` keys present, all `InvestmentDecision` fields present in the dumped dict, missing-ticker error path, `None` research dicts handled, JSON-serialisable output, end-to-end strong-bull-state -> BUY with conviction >= 6, end-to-end high-risk-state -> SELL, end-to-end debate-round reference check |
| `TestInvestmentDecisionSchemaValidation` | `conviction_score` bounds (1-10) rejected outside range, new field defaults (`time_horizon="12 months"`, empty `key_risks`/`key_catalysts`), `debate_rounds_used >= 1` enforced, model is frozen, `model_dump()` round-trips the new fields correctly, `verdict` is a required field                                                                                                           |
| `TestSystemPrompt`                       | Non-empty, mentions RULES/OUTPUT SCHEMA/JSON, ASCII-only, mentions `contrarian_response` and `investment_thesis`, mentions "debate"                                                                                                                                                                                                                                                            |
| `TestTracingIntegration`                 | `@traced_agent` applied (`__wrapped__` present and callable)                                                                                                                                                                                                                                                                                                                                   |

All LLM calls are mocked via `@patch("backend.agents.portfolio_manager.get_llm")`,
following the identical pattern used in `test_contrarian_investor.py` and
`test_valuation_agent.py`. No network, no database, no LLM quota consumed.

---

## Design Decisions

**Why deterministic Stage 1, LLM Stage 2 -- same split as every other
Phase 4 agent?**
Consistency with `risk_officer.py`, `contrarian_investor.py`, and
`valuation_agent.py`, all of which compute their numeric/structural
outputs in pure Python first and use the LLM only for narrative. For the
Portfolio Manager this matters even more than for the other agents: the
verdict and conviction score are the single most consequential outputs
in the entire pipeline, and they must be reproducible and unit-testable
without depending on LLM determinism (Groq's `llama-3.3-70b-versatile`
is not guaranteed to return byte-identical JSON across calls).

**Why does the LLM get told the verdict instead of being asked to decide
it?**
Letting the LLM choose BUY/HOLD/SELL independently would create a second,
ungoverned decision path that could disagree with the deterministic
Stage 1 result -- which result would then be "the real one"? Telling the
LLM the verdict and conviction explicitly and instructing it not to
change them keeps exactly one source of truth for the decision itself,
while still using the LLM for what it is good at: writing a coherent,
specific narrative around a decision that has already been made.

**Why hard gates (`risk_score >= 8`, `overvalued + weak fundamentals`)
instead of letting everything flow through the weighted point tally?**
A sufficiently bullish fundamental/technical/sentiment combination could
otherwise mathematically outweigh a catastrophic risk score in the
tally. Real investment committees do not allow this -- a Risk Officer
flag at "avoid" severity overrides enthusiasm from other desks
regardless of point totals. The two hard gates encode that override
explicitly rather than relying on weight tuning to approximate it.

**Why is `key_risks` sourced from `critical_flags` first and the
Contrarian second, rather than merging and re-sorting by some computed
severity score?**
`RiskAnalysis.critical_flags` is itself already the Risk Officer's
considered judgement of which flags are critical (T-037's own logic
filters fraud/regulatory keywords into that list). Re-deriving severity
in the Portfolio Manager would duplicate that judgement and risk
disagreeing with it. Trusting the upstream agent's own critical
classification, then layering the Contrarian's fresh angles on top,
keeps each agent's expertise in its own lane.

**Why `agent_weights` redistribute proportionally instead of just
zeroing failed agents in place?**
A flat zero-and-leave-the-rest-alone approach would make the weights sum
to less than 1.0 whenever any agent fails, which breaks the documented
contract that `agent_weights` represents "how much weight... summing to
1.0" (the original T-021 field description). Proportional redistribution
preserves that contract under partial failure, which is the common case
in production (a single flaky API call should not corrupt the entire
weight distribution's interpretability).

---

## AIRP Standards Compliance

| Standard                                                      | Status                                                                                                                                                                                                               |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No `from __future__ import annotations` in production modules | OK -- not present in `portfolio_manager.py`                                                                                                                                                                          |
| Plain ASCII section comments (`# ---`)                        | OK -- no Unicode box-drawing, no rupee signs, no em-dashes, no arrows in the new file                                                                                                                                |
| No bare `# type: ignore`                                      | OK -- none added; the one `type: ignore[misc]` in the test file's frozen-model mutation test follows the documented exception for that pattern                                                                       |
| `mypy --strict` safe                                          | OK -- every new function fully annotated with explicit parameter and return types; `cast()`/explicit `Optional` used where needed, no untyped defs                                                                   |
| Tools/agents never raise -- graceful degradation on bad input | OK -- `_run_portfolio_manager_core` never raises; verified for missing ticker, `None` research dicts, empty research dicts, LLM exceptions, and malformed LLM JSON                                                   |
| `@traced_agent` / LangSmith                                   | OK -- `run_portfolio_manager_decision` is wrapped with `@traced_agent("portfolio_manager")`, verified by `TestTracingIntegration`                                                                                    |
| Persistence wrapper applied (T-033 pattern)                   | OK -- unchanged; `portfolio_manager_node` in `nodes.py` keeps its existing `_persist_after(profile_node(...))` composition                                                                                           |
| All lines <= 88 chars                                         | OK -- verified directly against the new files                                                                                                                                                                        |
| flake8 (bugbear, comprehensions) clean                        | OK -- no `getattr` with constant string, no bare `pytest.raises(Exception)`, exception types are specific in test fallback paths                                                                                     |
| `ENVIRONMENT=test` guard respected                            | OK -- new test file uses the same `os.environ.setdefault("ENVIRONMENT", "test")` pattern as every other agent test module, and the autouse `require_test_environment` fixture in `conftest.py` applies automatically |

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/debate-portfolio-mgr
```

### 2. Place the files

Copy the following files into your local repository (paths relative to
repo root):

```
backend/agents/output_models.py                  (modified)
backend/agents/portfolio_manager.py               (new)
backend/graph/nodes.py                             (modified)
backend/graph/graph.py                             (modified -- docstrings only)
backend/tests/unit/test_portfolio_manager.py       (new)
docs/week-11/T-041-portfolio-manager.md            (new)
```

### 3. Set environment and run the new test file

**Windows CMD:**

```cmd
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_portfolio_manager.py -v --tb=short
```

**Git Bash / Mac / Linux:**

```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_portfolio_manager.py -v --tb=short
```

> Note: on Windows, set `ENVIRONMENT=test` as its own command, not chained
> with `&&` -- a chained assignment can leave a trailing space that fails
> the `conftest.py` guard's strict comparison before its `.strip().lower()`
> normalisation was added. The guard now tolerates this, but the
> standalone form remains the documented convention.

Expected: all tests pass.

### 4. Run the previously-touched files to confirm no regressions

```bash
python -m pytest backend/tests/unit/test_output_models.py -v --tb=short
python -m pytest backend/tests/unit/test_graph_skeleton.py -v --tb=short
```

Expected: all passed. `test_output_models.py` continues to pass because
the three new `InvestmentDecision` fields are additive with defaults --
no existing construction call site breaks. `test_graph_skeleton.py`
continues to pass because no nodes were added, removed, or rewired; node
count remains 13.

### 5. Run the full unit suite to confirm no regressions anywhere

```bash
python -m pytest --tb=short -q
```

Expected: all existing tests continue to pass. `test_debate_loop.py`
(T-040) is unaffected since `debate_loop_node` and `route_after_contrarian`
were not touched. `test_valuation_agent.py` and `test_risk_officer.py`
are unaffected since their agents were not modified.

### 6. Run with coverage to confirm the 75% threshold still holds

```bash
pytest --cov=backend --cov-report=term-missing -q
```

### 7. (Optional) Run the integration suite

```bash
python -m pytest -m integration -v --tb=short
```

This calls the real Groq LLM for Portfolio Manager synthesis (in addition
to the pre-existing Risk Officer / Contrarian / Valuation integration
calls from T-037/T-038/T-039) -- requires `GROQ_API_KEY` to be set; skip
if you don't want to spend Groq quota in this session.

### 8. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/agents/output_models.py \
        backend/agents/portfolio_manager.py \
        backend/graph/nodes.py \
        backend/graph/graph.py \
        backend/tests/unit/test_portfolio_manager.py \
        docs/week-11/T-041-portfolio-manager.md
git commit -m "feat(agents): add Portfolio Manager agent"
```

Black / isort may auto-fix formatting on the first attempt. If the commit
is rejected by pre-commit hooks (the two-commit pattern from AIRP
standards):

```bash
git add .
git commit -m "feat(agents): add Portfolio Manager agent"
```

### 9. Push and open PR

```bash
git push -u origin feat/debate-portfolio-mgr
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**

```
feat(agents): implement Portfolio Manager as final decision synthesiser
```

**PR description:**

```markdown
## Summary

Implements the Portfolio Manager agent (T-041) -- the final, accountable
decision-maker of the AIRP investment committee. Replaces the T-032-era
stub in `nodes.py` with a real two-stage agent that reads all 7 prior
agent outputs plus the full debate transcript from T-040 and produces a
BUY/HOLD/SELL verdict with a conviction score, structured risk/catalyst
lists, and full Investment Memo narrative sections.

## Changes

- `backend/agents/output_models.py` -- added `time_horizon`, `key_risks`,
  `key_catalysts` fields to `InvestmentDecision` (additive, all have
  defaults, no existing call sites broken).
- `backend/agents/portfolio_manager.py` -- new file. Deterministic Stage 1
  (verdict, conviction, agent weights, time horizon, price target, key
  risks/catalysts) followed by LLM Stage 2 narrative synthesis grounded
  in the debate transcript. Never raises; LLM failures fall back to a
  fully deterministic summary.
- `backend/graph/nodes.py` -- `_portfolio_manager_impl` now delegates to
  `run_portfolio_manager_decision` instead of returning a hardcoded
  HOLD/5 stub.
- `backend/graph/graph.py` -- docstring corrections only; no wiring
  changes (T-031/T-032 already had `portfolio_manager` correctly placed
  at the end of the pipeline).
- `backend/tests/unit/test_portfolio_manager.py` -- new file covering
  every deterministic helper, the full agent core, the LangGraph node
  contract, schema validation, and tracing.

## Testing

- New unit test suite: `pytest backend/tests/unit/test_portfolio_manager.py -v`
- Full suite regression: `pytest --tb=short -q`
- Explicit acceptance-criterion test
  (`test_agreeing_clean_profile_beats_conflicting_high_risk_profile`)
  constructs two profiles with the same nominal verdict and asserts
  conviction differs based on analysis quality, not signal strength
- Explicit acceptance-criterion tests confirm `investment_thesis` and
  `contrarian_response` reference named debate-round content
- All external calls (LLM) mocked -- no network, no database, no LLM
  quota consumed

## LangSmith Trace

`run_portfolio_manager_decision` is wrapped with
`@traced_agent("portfolio_manager")`, consistent with every other
committee agent. Trace link will be available once this runs against a
live Groq call in the dev environment.

## Related Issues

Closes #41
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

Next task: **T-042** -- Build Investment Memo generator. This task takes
the `InvestmentDecision` produced here (plus the full `InvestmentState`)
and renders it into a structured 2-page memo: Executive Summary, Thesis,
Bull Case, Bear Case, Risks, Valuation, Recommendation. The
`key_risks[]` / `key_catalysts[]` lists and `time_horizon` field added in
this task exist specifically so T-042 can render them as bullet points
without needing to parse prose.

Branch: `feat/debate-memo-generator` (per the project plan).

With T-041 complete, every node in the LangGraph pipeline from `planner`
through `portfolio_manager` is now fully implemented -- Phase 4
(Debate Engine & Advanced Agents) is functionally done pending the memo
generator and PDF export (T-042/T-043), after which Phase 5 (FastAPI
Backend) can be built on top of a complete agent pipeline.

---

_End of Document | T-041 Workflow | AIRP Week 11_
