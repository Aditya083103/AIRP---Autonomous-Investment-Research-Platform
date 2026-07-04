# T-042 -- Build Investment Memo Generator

**Phase:** 4 -- Debate Engine & Advanced Agents
**Week:** 11
**Branch:** `feat/debate-memo-generator`
**Task status:** Complete

---

## Overview

T-042 takes the `InvestmentDecision` produced by the Portfolio Manager
(T-041) plus the full `InvestmentState` and renders a structured,
readable Investment Memo: Executive Summary, Investment Thesis, Bull
Case, Bear Case, Risk Analysis, Valuation, and Recommendation.

Every prose sentence in the memo already exists by the time T-042 runs
-- the Portfolio Manager's Stage 2 LLM synthesis (T-041) already wrote
`executive_summary`, `investment_thesis`, `bull_case`, `bear_case`,
`risk_summary`, `valuation_summary`, and `contrarian_response`. T-042
makes **zero additional LLM calls**. Its job is purely structural:
assemble those existing sections plus the structured numeric data
(verdict, conviction, price target, time horizon, `key_risks[]`,
`key_catalysts[]`, `agent_weights`) into one coherently formatted,
non-technical-reader-friendly Markdown document, and do it
deterministically so the memo never fails to render -- even if the
decision itself is incomplete or carries an error.

**Acceptance criteria (all must pass):**

- Memo generated for TCS
- All sections populated
- Readable by a non-technical person

---

## Files Changed

| File                                        | Change                                                                                                                                                                                                                                        |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/services/memo_generator.py`        | **New** -- the full memo assembly module: 7 section builders, the top-level `_build_memo_markdown` assembler, a no-decision fallback, and the `generate_investment_memo` LangGraph node entry point                                           |
| `backend/graph/nodes.py`                    | **Modified** -- added `NODE_REPORT_GENERATOR`, `_report_generator_impl`, and `report_generator_node` (same `_persist_after(profile_node(...))` composition as every other sequential node); added the `memo_generator` import                 |
| `backend/graph/graph.py`                    | **Modified** -- registered `report_generator` node; rewired the tail edge from `portfolio_manager -> END` to `portfolio_manager -> report_generator -> END` (14 nodes total, was 13); updated all node-count docstrings/comments/log messages |
| `backend/graph/graph_visualisation.py`      | **Modified** -- docstring updated to describe the new final node                                                                                                                                                                              |
| `backend/tests/unit/test_memo_generator.py` | **New** -- unit tests covering every section builder, full assembly, the no-decision fallback, and the LangGraph node contract                                                                                                                |
| `backend/tests/unit/test_graph_skeleton.py` | **Modified** -- node count assertion updated from 13 to 14; new registration, mermaid, edge, literal-value, and direct node-behaviour tests added for `report_generator`                                                                      |

---

## What Was Built

### New: `backend/services/memo_generator.py`

A pure-Python, zero-LLM, zero-third-party-dependency formatting module
(only `logging`, `datetime`, and `typing` from the standard library).
Structure:

| Function                                | Purpose                                                                                                                                                                                                                                                                                      |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_non_empty(...)`                       | Returns text if non-empty, else a readable fallback string -- the building block every section uses so a partially-populated decision never renders a blank or "None" section                                                                                                                |
| `_format_conviction_label(...)`         | Translates the raw 1-10 conviction score into a plain-English label (`"8/10 (high conviction)"`, `"5/10 (moderate conviction)"`, `"2/10 (low conviction -- treat with caution)"`)                                                                                                            |
| `_format_agent_weights_table(...)`      | Renders `agent_weights` as a small Markdown table with human-readable committee-member names instead of raw `agent_name` strings; falls back to explanatory text if weighting was unavailable                                                                                                |
| `_build_header_section(...)`            | Title, recommendation/conviction/price-target/time-horizon summary table                                                                                                                                                                                                                     |
| `_build_executive_summary_section(...)` | Section 1                                                                                                                                                                                                                                                                                    |
| `_build_thesis_section(...)`            | Section 2 -- prepends a plain-English one-line framing of what BUY/HOLD/SELL means before the Portfolio Manager's own debate-grounded thesis text                                                                                                                                            |
| `_build_bull_case_section(...)`         | Section 3 -- bull case prose plus `key_catalysts[]` as bullets                                                                                                                                                                                                                               |
| `_build_bear_case_section(...)`         | Section 4 -- bear case prose plus the Portfolio Manager's `contrarian_response` under a "How the committee addressed this" subheading                                                                                                                                                        |
| `_build_risk_section(...)`              | Section 5 -- risk summary prose plus `key_risks[]` as a numbered list                                                                                                                                                                                                                        |
| `_build_valuation_section(...)`         | Section 6 -- valuation summary prose plus the formatted price target                                                                                                                                                                                                                         |
| `_build_recommendation_section(...)`    | Section 7 -- final verdict restated, the dashboard `summary` line, time horizon, debate round count, and the agent-weights table                                                                                                                                                             |
| `_build_disclaimer_section(...)`        | Standard "not financial advice, for portfolio demonstration purposes" footer on every memo                                                                                                                                                                                                   |
| `_build_memo_markdown(...)`             | Top-level assembler: calls all of the above in order and joins them. Never raises -- every field access goes through `_non_empty` or an explicit `.get(...)` with a default                                                                                                                  |
| `_build_no_decision_memo(...)`          | Fallback used when `state["decision"]` is entirely absent (e.g. an earlier pipeline node failed). Still a complete, readable document explaining the analysis could not be completed -- never an empty string                                                                                |
| `generate_investment_memo(state)`       | The LangGraph node entry point. Reads `state["decision"]`, `state["company_name"]`, `state["ticker"]`; returns `{"memo_markdown": "..."}`. Wrapped in a try/except so any unexpected failure (e.g. a malformed decision dict) still degrades to the no-decision fallback rather than raising |

### Why Markdown, not HTML or PDF directly?

T-043 (separate task, already scoped in the project plan) owns PDF
export via WeasyPrint. Markdown is the natural intermediate format: it
is human-readable on its own -- satisfying "readable by a non-technical
person" without any rendering step at all -- and is what
`InvestmentState.memo_markdown` was already typed to hold (see
`backend/graph/state.py`, which reserves both `memo_markdown` and
`memo_pdf_path` as `Optional[str]` fields, left unset by
`make_initial_state` until the relevant node populates them). Keeping
T-042 Markdown-only at the presentation layer means T-043 can convert
Markdown -> HTML -> PDF without `memo_generator.py` needing any
awareness of PDF libraries at all.

### Why no LLM call in `report_generator_node`?

The Portfolio Manager's Stage 2 synthesis (T-041) already produced
every prose sentence this memo needs, explicitly grounded in the debate
transcript and the Contrarian's strongest argument. Re-summarising via
a second LLM call would risk introducing details that were never part
of the original committee debate -- exactly the failure mode
`key_risks` / `key_catalysts` / debate-grounding were designed in T-041
to avoid -- and would double the LLM cost and latency per analysis for
no benefit. T-042 is purely a formatting and assembly layer, which is
also why it completes in well under a second with zero network calls.

### Why does the memo render even when the decision has an error?

A degraded analysis (missing ticker, all agents failed) still produces
a valid -- if minimal -- `InvestmentDecision` per T-041's "agents never
raise" contract. `memo_generator.py` honours that same contract: it
never raises, and always returns a complete, readable document, even
if that document's content is "analysis could not be completed" rather
than a full investment case. A blank or missing memo would be a worse
user experience than a clearly-labelled incomplete one.

### Modified: `backend/graph/nodes.py`

```python
# New, mirrors the portfolio_manager_node composition exactly:
def _report_generator_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = generate_investment_memo(state)
    partial["status"] = "completed"
    partial["completed_at"] = datetime.utcnow().isoformat() + "Z"
    partial["current_node"] = NODE_REPORT_GENERATOR
    return partial


report_generator_node: _NodeFn = _persist_after(
    profile_node(_report_generator_impl, NODE_REPORT_GENERATOR),
    NODE_REPORT_GENERATOR,
)
```

Identical thin-wrapper pattern to every other sequential node --
delegate to the module's own entry point, then merge in pipeline
bookkeeping fields (`status`, `completed_at`, `current_node`). T-033's
`_persist_after` and T-036's `profile_node` wrap it exactly as they
wrap `portfolio_manager_node`, so the memo's generation latency is
automatically captured in the per-node latency profile and the memo
text is automatically persisted to PostgreSQL after the node completes.

### Modified: `backend/graph/graph.py`

Topology change, fully additive:

```
Before (T-041):
  valuation_agent -> portfolio_manager -> END

After (T-042):
  valuation_agent -> portfolio_manager -> report_generator -> END
```

`portfolio_manager_node` now has a single unconditional edge to
`report_generator`, which has a single unconditional edge to `END`.
Total node count: 14 (was 13). All docstring/comment node-count
references (`"13 nodes total"`, `"Register all 13 nodes"`, the
compile-time log message) were updated to 14 to keep the file's own
documentation accurate.

---

## Tests

| Test class                         | What it covers                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TestNonEmpty`                     | Text passthrough, whitespace stripping, fallback on `None`/empty/whitespace-only input, custom fallback text                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `TestFormatConvictionLabel`        | High/moderate/low conviction label bands, numeric score always included                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `TestFormatAgentWeightsTable`      | Markdown table renders correctly, all 7 committee members present with human-readable names, empty/all-zero weights produce explanatory fallback text instead of an empty table                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `TestBuildHeaderSection`           | Company/ticker/verdict/price-target present, missing price target shows "Not available", timestamp present, correct Markdown H1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `TestBuildExecutiveSummarySection` | Content passthrough, empty-input fallback, section header present                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `TestBuildThesisSection`           | Plain-English framing differs correctly per verdict (BUY/HOLD/SELL), provided thesis text is preserved                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `TestBuildBullCaseSection`         | Bull case text present, catalysts rendered as bullets when present, no empty "Potential catalysts" subheading when the list is empty                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `TestBuildBearCaseSection`         | Bear case text present, contrarian response present, empty-response fallback text                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `TestBuildRiskSection`             | Risk summary present, key risks rendered as a numbered list, no empty subheading when the list is empty                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `TestBuildValuationSection`        | Valuation summary present, price target present when available, no dangling "Implied price target" line when `None`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `TestBuildRecommendationSection`   | Verdict and summary present, time horizon present, correct singular/plural "round(s) of committee debate" grammar, agent-weights table embedded                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `TestBuildMemoMarkdown`            | Full assembly returns a non-empty string; **all 7 required section headings present** (the "all sections populated" acceptance criterion, checked directly); disclaimer present; BUY/HOLD/SELL decisions all render correctly; a near-empty decision still renders without raising; **readability check** -- plain-English verdict framing present, no raw `{` JSON artifacts, no bare `None` leaking into text; key risks appear as a numbered list; key catalysts appear as bullets                                                                                                                               |
| `TestBuildNoDecisionMemo`          | Non-empty fallback document, company/ticker present, "could not be completed" notice present, disclaimer present                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `TestGenerateInvestmentMemoNode`   | Node returns `{"memo_markdown": str}`; **full TCS end-to-end test** asserting company name, ticker, and all 7 section headings are present (the primary acceptance criterion, exercised through the actual node entry point); missing/`None` decision triggers the fallback memo; missing `company_name` handled gracefully; a deliberately malformed decision dict (`agent_weights` as a string instead of a dict) does not raise, confirming the try/except fallback path; input state dict is never mutated; the node's return value contains exactly one key (`memo_markdown`) as a proper partial-state update |

All tests are pure-Python with zero mocking required -- `memo_generator.py`
has no LLM calls, no database calls, and no third-party imports, so
every test exercises the real production code path directly with no
network and no quota consumed.

Additions to `backend/tests/unit/test_graph_skeleton.py`:
`test_report_generator_registered`, `test_mermaid_contains_report_generator`,
`test_portfolio_manager_to_report_generator_edge`,
`test_node_report_generator_is_string`, plus `report_generator_node` added
to `test_all_stub_nodes_never_raise` (renamed from its stale "Phase 4
stub nodes" docstring) and three new direct node-behaviour tests
(`test_report_generator_returns_memo_markdown`,
`test_report_generator_sets_status_completed`,
`test_report_generator_sets_current_node`,
`test_report_generator_handles_missing_decision`).

---

## Design Decisions

**Why a separate `services/memo_generator.py` module instead of folding
this into `portfolio_manager.py`?**
Single responsibility, and a meaningful boundary for T-043. The
Portfolio Manager's job (T-041) is to _decide_ -- verdict, conviction,
narrative synthesis grounded in debate. The memo generator's job
(T-042) is to _format_ an already-finished decision for a human reader.
Keeping them separate means T-043 (PDF export) only needs to depend on
`memo_generator.py`'s Markdown output, not on the Portfolio Manager's
LLM-calling internals at all. It also means `memo_generator.py` can be
tested with zero mocking, since it never touches an LLM, while
`portfolio_manager.py` necessarily does.

**Why is this a `backend/services/` module rather than `backend/agents/`?**
It performs no analysis and makes no LLM call -- it is a pure
data-to-presentation transformation, the same category as
`backend/services/state_persistence.py`. Every module under
`backend/agents/` in this codebase produces a new Pydantic-validated
analytical judgement; `memo_generator.py` does not produce a judgement,
it presents one that already exists.

**Why does `_build_thesis_section` prepend a plain-English sentence
before the Portfolio Manager's own thesis text, instead of relying on
the LLM-written thesis alone to be accessible?**
The acceptance criterion is "readable by a non-technical person," and
the Portfolio Manager's `investment_thesis` field is written for
debate-grounding accuracy first (it must name a specific round per
T-041's system prompt), which can read as dense to someone unfamiliar
with how the verdict was produced. The one-sentence plain-English
preamble ("The committee recommends buying this stock...") gives every
reader an immediate, jargon-free anchor before the more detailed,
debate-specific thesis follows. This is verified directly by
`TestBuildMemoMarkdown.test_readable_by_non_technical_reader`.

**Why render `key_risks` as a numbered list but `key_catalysts` as
bullets?**
Risks in an investment memo are conventionally read in order of
materiality (T-041's `_build_key_risks` already orders critical flags
first), so numbering signals "these are ranked." Catalysts have no
inherent ranking from T-041 -- they are a flat set of independent
positive factors -- so bullets avoid implying an ordering that does not
exist.

**Why catch exceptions around the entire `_build_memo_markdown` call in
`generate_investment_memo` rather than trusting that pure formatting
code cannot fail?**
"Agents never raise" is a load-bearing convention throughout this
codebase, and `report_generator_node` is the very last node before
`END` -- if it raised, the entire pipeline run would fail at the finish
line after every other agent's work had already succeeded. The
`test_never_raises_on_malformed_decision` test exists specifically to
prove this defence works, not just that the happy path is correct.

---

## AIRP Standards Compliance

| Standard                                                      | Status                                                                                                                                                                                                                            |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No `from __future__ import annotations` in production modules | OK -- not present in `memo_generator.py`                                                                                                                                                                                          |
| Plain ASCII section comments (`# ---`)                        | OK -- no Unicode box-drawing, no rupee signs, no em-dashes, no arrows in the new file                                                                                                                                             |
| No bare `# type: ignore`                                      | OK -- none added anywhere in this task's files                                                                                                                                                                                    |
| `mypy --strict` safe                                          | OK -- every function fully annotated with explicit parameter and return types                                                                                                                                                     |
| Tools/agents never raise -- graceful degradation on bad input | OK -- `generate_investment_memo` never raises; verified for missing decision, `None` decision, missing company name, and a deliberately malformed `agent_weights` value                                                           |
| `@traced_agent` / LangSmith                                   | N/A -- `report_generator_node` makes no LLM calls, nothing to trace (consistent with `debate_loop_node`'s T-040 precedent for zero-LLM nodes)                                                                                     |
| Persistence wrapper applied (T-033 pattern)                   | OK -- `_persist_after(profile_node(...))` composition, identical to every other sequential node                                                                                                                                   |
| All lines <= 88 chars                                         | OK -- verified by direct character-length check (not byte-length, to correctly account for the project's pre-existing Unicode characters elsewhere in the codebase)                                                               |
| flake8 (bugbear, comprehensions) clean                        | OK -- no `getattr` with constant string, no bare `pytest.raises(Exception)`, no unnecessary dict/list comprehensions with constant values                                                                                         |
| `ENVIRONMENT=test` guard respected                            | OK -- new test file sets `ENVIRONMENT=test` via `os.environ.setdefault` before any backend import, consistent with every other test module; the autouse `require_test_environment` fixture in `conftest.py` applies automatically |

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/debate-memo-generator
```

### 2. Place the files

Copy the following files into your local repository (paths relative to
repo root):

```
backend/services/memo_generator.py            (new)
backend/graph/nodes.py                          (modified)
backend/graph/graph.py                          (modified)
backend/graph/graph_visualisation.py            (modified)
backend/tests/unit/test_memo_generator.py       (new)
backend/tests/unit/test_graph_skeleton.py       (modified)
docs/week-11/T-042-memo-generator.md            (new)
```

### 3. Set environment and run the new test file

**Windows CMD:**

```cmd
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_memo_generator.py -v --tb=short
```

**Git Bash / Mac / Linux:**

```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_memo_generator.py -v --tb=short
```

Expected: all tests pass. This file makes zero LLM calls, zero database
calls, and zero network calls, so it will also be one of the fastest
files in the suite to run.

### 4. Run the previously-touched file to confirm no regressions there

```bash
python -m pytest backend/tests/unit/test_graph_skeleton.py -v --tb=short
```

Expected: all passed, including the updated 14-node assertion and the
new `report_generator` registration/mermaid/edge/literal-value tests.

### 5. Run the full unit suite to confirm no regressions anywhere

```bash
python -m pytest --tb=short -q
```

Expected: all existing tests continue to pass. `test_portfolio_manager.py`
(T-041) is unaffected since `portfolio_manager.py` itself was not
modified in this task -- only `nodes.py` and `graph.py` changed, and
only to add the new node after it.

### 6. Run with coverage to confirm the threshold still holds

```bash
pytest --cov=backend --cov-report=term-missing -q
```

`memo_generator.py` should show very high coverage given every code
path (happy path, no-decision fallback, malformed-decision fallback)
has a dedicated test with zero mocking required.

### 7. (Optional) Run the integration suite

```bash
python -m pytest -m integration -v --tb=short
```

`report_generator_node` makes no external calls of its own, so this
task adds nothing new to integration test scope -- any pre-existing
integration tests covering the full pipeline through T-041 will now
also exercise `memo_markdown` being populated in the final state.

### 8. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/services/memo_generator.py \
        backend/graph/nodes.py \
        backend/graph/graph.py \
        backend/graph/graph_visualisation.py \
        backend/tests/unit/test_memo_generator.py \
        backend/tests/unit/test_graph_skeleton.py \
        docs/week-11/T-042-memo-generator.md
git commit -m "feat(report): add Investment Memo generator"
```

Black / isort may auto-fix formatting on the first attempt. If the
commit is rejected by pre-commit hooks (the two-commit pattern from
AIRP standards):

```bash
git add .
git commit -m "feat(report): add Investment Memo generator"
```

### 9. Push and open PR

```bash
git push -u origin feat/debate-memo-generator
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**

```
feat(report): implement structured Investment Memo generator with full analysis
```

**PR description:**

```markdown
## Summary

Implements the Investment Memo generator (T-042) -- a new
`report_generator` LangGraph node that runs immediately after the
Portfolio Manager and renders the full InvestmentDecision (T-041) into
a structured, readable Markdown memo: Executive Summary, Investment
Thesis, Bull Case, Bear Case, Risk Analysis, Valuation, and
Recommendation. Makes zero additional LLM calls -- every prose section
was already written by the Portfolio Manager's own synthesis step;
T-042 is purely formatting and assembly.

## Changes

- `backend/services/memo_generator.py` -- new file. Seven section
  builders, a top-level assembler, a no-decision fallback, and the
  `generate_investment_memo` LangGraph node entry point. Pure stdlib,
  no third-party dependencies, never raises.
- `backend/graph/nodes.py` -- added `NODE_REPORT_GENERATOR`,
  `report_generator_node` (same `_persist_after(profile_node(...))`
  composition as every other sequential node).
- `backend/graph/graph.py` -- registered the new node and rewired the
  tail edge: `portfolio_manager -> report_generator -> END`
  (14 nodes total, was 13).
- `backend/graph/graph_visualisation.py` -- docstring updated.
- `backend/tests/unit/test_memo_generator.py` -- new file, full
  coverage of every section builder and the node contract, zero
  mocking required.
- `backend/tests/unit/test_graph_skeleton.py` -- node count assertion
  updated 13 -> 14; new tests for the `report_generator` node.

## Testing

- New unit test suite: `pytest backend/tests/unit/test_memo_generator.py -v`
- Full suite regression: `pytest --tb=short -q`
- Explicit acceptance-criterion test
  (`test_tcs_end_to_end_memo_generation`) generates a memo for TCS
  through the actual node entry point and asserts company name,
  ticker, and all 7 required section headings are present
- Explicit readability test (`test_readable_by_non_technical_reader`)
  checks for plain-English verdict framing and the absence of raw
  JSON/`None` artifacts in the rendered text
- Robustness tests confirm the node never raises on a missing,
  `None`, or malformed decision
- No mocking required anywhere in this test file -- zero LLM calls,
  zero database calls, zero network calls

## LangSmith Trace

Not applicable -- `report_generator_node` makes no LLM calls, so there
is nothing new to trace. The Portfolio Manager's existing
`@traced_agent` trace already covers the LLM cost for the narrative
content this memo presents.

## Related Issues

Closes #42
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

Next task: **T-043** -- Add PDF export for the Investment Memo. This
task converts `state["memo_markdown"]` to a professional, branded PDF
via WeasyPrint (already pinned in `backend/requirements.txt`), adding
AIRP branding, a company-name header, a generation date, and page
numbers, then writes the result to `state["memo_pdf_path"]` -- the
second `Optional[str]` field already reserved in `InvestmentState`
alongside `memo_markdown`. T-042's Markdown output was deliberately
kept format-agnostic so T-043 can build a Markdown -> HTML -> PDF
conversion pipeline without `memo_generator.py` needing any awareness
of PDF libraries at all.

Branch: `feat/debate-pdf-export` (per the project plan).

With T-042 complete, the full LangGraph pipeline from `planner` through
`report_generator` now produces a complete, human-readable Investment
Memo for every analysis -- the only remaining Phase 4 task is PDF
export, after which Phase 5 (FastAPI Backend) can expose this pipeline
over REST and WebSocket endpoints.

---

_End of Document | T-042 Workflow | AIRP Week 11_
