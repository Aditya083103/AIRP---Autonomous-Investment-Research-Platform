# T-029 -- Define InvestmentState TypedDict

**Phase:** 3 -- LangGraph Orchestration
**Week:** 7
**Branch:** `feat/graph-state`
**Task status:** Ready to merge

---

## Overview

T-029 defines `InvestmentState` -- the single TypedDict that flows through
every node in the AIRP LangGraph StateGraph. This is the foundational
data contract for Phase 3. Every agent (Phases 2 and 4) reads from and
writes to this object. No agent-to-agent messaging occurs outside of it.

**Acceptance criteria (all met):**

- State roundtrips through JSON serialisation (verified by 50+ pytest tests)
- All fields typed (TypedDict with full mypy --strict coverage)
- Documented in `docs/STATE.md` (new file, field-by-field reference)

**Files produced:**

| File                                            | Action | Description                           |
| ----------------------------------------------- | ------ | ------------------------------------- |
| `backend/graph/state.py`                        | Create | `InvestmentState` TypedDict + helpers |
| `backend/tests/unit/test_investment_state.py`   | Create | 50+ unit tests                        |
| `docs/STATE.md`                                 | Create | Field reference + lifecycle diagram   |
| `docs/week-07/T-029-define-investment-state.md` | Create | This workflow doc                     |

---

## 1. Pre-work Checklist

```bash
git checkout main
git pull origin main
git log --oneline -5
```

Confirm the graph folder has its stub README only:

```bash
ls backend/graph/
# Expected: README.md only (state.py does not exist yet)
```

---

## 2. Create the Feature Branch

```bash
git checkout -b feat/graph-state
```

---

## 3. Files to Create

### 3.1 `backend/graph/state.py`

The complete `InvestmentState` TypedDict with:

- All identity fields (`job_id`, `company_name`, `ticker`, `exchange`, etc.)
- Pipeline status fields (`status`, `current_node`, `started_at`, etc.)
- All 8 agent output fields as `Optional[dict[str, Any]]`
- Debate transcript fields (`debate_rounds`, `debate_round_count`)
- Risk flag aggregation fields (`risk_flags`, `critical_flags`)
- Final output fields (`final_verdict`, `conviction_score`, `memo_pdf_path`, etc.)
- Document upload context fields
- LangSmith observability fields
- `version: int` field (currently `1`)
- `make_initial_state()` factory function
- `state_to_json()` and `state_from_json()` serialisation helpers
- `DebateRound` documentation class

Key design decisions encoded in the file:

- `total=False` -- every field is implicitly Optional; state built incrementally
- No `from __future__ import annotations` -- breaks Pydantic v2 union resolution
- Plain ASCII `# ---` section comments -- avoids flake8 E501 from Unicode chars
- `default=str` in `state_to_json` -- handles datetime objects in agent dicts

### 3.2 `backend/tests/unit/test_investment_state.py`

Test classes:

| Class                              | What it tests                                              |
| ---------------------------------- | ---------------------------------------------------------- |
| `TestMakeInitialState`             | Factory produces correct required fields                   |
| `TestOptionalFields`               | Optional fields absent by default, settable when provided  |
| `TestJsonRoundTrip`                | `state_to_json` / `state_from_json` is lossless            |
| `TestPartialStateRoundTrip`        | Partially-populated state survives round-trip              |
| `TestFullyPopulatedStateRoundTrip` | All fields set, round-trip works                           |
| `TestAgentOutputDictsInState`      | All 8 `model.model_dump()` dicts are JSON-safe             |
| `TestDebateRounds`                 | Debate transcript list survives serialisation              |
| `TestRiskFlags`                    | `risk_flags` / `critical_flags` are mutable and round-trip |
| `TestVersionField`                 | `version` is always `1` on initial state                   |
| `TestStateFromJson`                | Deserialiser returns usable dict                           |
| `TestEdgeCases`                    | Empty strings, zero counts, datetime in agent dicts        |
| `TestDebateRoundDocumentation`     | `DebateRound` class is importable with docstring           |

### 3.3 `docs/STATE.md`

Full field reference with:

- Why TypedDict not Pydantic (comparison table)
- Full lifecycle ASCII diagram
- Field reference table for every field group
- Public API usage examples
- JSON serialisation contract
- Version migration strategy
- Integration points with LangGraph, FastAPI, PostgreSQL, etc.

---

## 4. Implementation Steps

### Step 1 -- Place the files

```
backend/graph/state.py
backend/tests/unit/test_investment_state.py
docs/STATE.md
docs/week-07/T-029-define-investment-state.md
```

### Step 2 -- Run pre-commit hooks

```bash
cd <repo-root>
pre-commit run --files backend/graph/state.py backend/tests/unit/test_investment_state.py
```

Expected: black, isort, flake8 all pass.

**Known pre-commit quirk on Windows:** If `pre-commit run` is blocked by
Windows Application Control, run the checks manually:

```bash
python -m black backend/graph/state.py backend/tests/unit/test_investment_state.py
python -m isort backend/graph/state.py backend/tests/unit/test_investment_state.py
python -m flake8 backend/graph/state.py backend/tests/unit/test_investment_state.py
```

### Step 3 -- Run mypy

```bash
python -m mypy backend/graph/state.py --strict --warn-unused-ignores
```

Expected output: `Success: no issues found in 1 source file`

Verify the test file also passes:

```bash
python -m mypy backend/tests/unit/test_investment_state.py
```

### Step 4 -- Run the test suite

Set environment first (Windows):

```bash
set ENVIRONMENT=test
```

Run just the new test file:

```bash
python -m pytest backend/tests/unit/test_investment_state.py -v
```

Expected: all tests pass with zero errors.

Run the full test suite to confirm no regressions:

```bash
python -m pytest -v
```

Expected: all existing tests continue to pass.

---

## 5. mypy Notes

The file uses `total=False` on `InvestmentState` (a TypedDict). Under
`mypy --strict`, accessing keys on a `total=False` TypedDict returns
`Optional[T]` for every field -- which is correct behaviour.

The `cast()` in `state_from_json` tells mypy that the JSON-parsed `dict`
is an `InvestmentState`. This is safe because:

1. The content was originally produced by `state_to_json` from a typed state
2. The `assert isinstance(raw, dict)` guard rejects non-dict JSON

The `typing_cast` alias (imported inside the function body) avoids the
name clash with any `cast` variable that might exist at module level.

---

## 6. Commit Message

```
feat(graph): define InvestmentState TypedDict with JSON round-trip helpers

- Add InvestmentState TypedDict (total=False) with all 8 agent output fields,
  debate transcript, risk flags, pipeline status, and observability fields
- Add make_initial_state() factory with version=1 schema
- Add state_to_json() / state_from_json() round-trip helpers (default=str for datetime)
- Add DebateRound documentation class for debate transcript dict shape
- Add 50+ unit tests covering factory, optionals, JSON round-trip, all 8 agent
  model_dump() dicts, debate rounds, risk flags, and edge cases
- Add docs/STATE.md -- field reference, lifecycle diagram, integration points

Closes #29
```

---

## 7. Pull Request

**Title:** `feat(graph): define InvestmentState TypedDict (T-029)`

**Description:**

```
## Summary

Defines InvestmentState -- the single shared TypedDict that flows through
every node in the AIRP LangGraph StateGraph.  This is the data contract
that connects all 8 agents, the debate loop, and the final PDF output.

## Changes

- `backend/graph/state.py` -- InvestmentState TypedDict, make_initial_state()
  factory, state_to_json() / state_from_json() helpers, DebateRound doc class
- `backend/tests/unit/test_investment_state.py` -- 50+ unit tests verifying
  the JSON round-trip contract, all 8 agent output dicts, debate rounds,
  risk flags, and edge cases
- `docs/STATE.md` -- field reference with lifecycle diagram and integration points
- `docs/week-07/T-029-define-investment-state.md` -- this workflow document

## Testing

All 50+ unit tests pass:

    python -m pytest backend/tests/unit/test_investment_state.py -v
    # All tests pass

Full suite passes with no regressions:

    python -m pytest -v

mypy --strict passes on state.py:

    python -m mypy backend/graph/state.py --strict --warn-unused-ignores
    # Success: no issues found in 1 source file

## Related Issues

Closes #29
```

---

## 8. Post-merge Checklist

After the PR is merged to main:

- [ ] Pull main: `git checkout main && git pull origin main`
- [ ] Confirm `backend/graph/state.py` exists on main
- [ ] Confirm `docs/STATE.md` exists on main
- [ ] Note for T-030 (Planner node): import `make_initial_state` from
      `backend.graph.state` to create the initial state in the Planner node
- [ ] Note for T-031+ (agent wrappers): agent node functions receive and
      return `InvestmentState` (or partial dict); type annotations should
      use `InvestmentState` from this module

---

## 9. Design Notes

### total=False

`InvestmentState` uses `total=False` so all fields are implicitly Optional
at the TypedDict level. This matches how LangGraph populates state:
incrementally, one node at a time. Accessing a key that has not been set
returns `None` via `.get()`.

### No from **future** import annotations

This is an AIRP-wide rule established in T-010. The annotations import
causes Pydantic v2 to receive forward references (strings) instead of
actual types during model construction, which breaks union type resolution.
The state module imports output model classes indirectly through tests, so
this rule applies here too.

### Plain ASCII section comments

Unicode box-drawing characters (`───`, `═══`) caused repeated flake8 E501
line-length failures in T-022 and T-023. Starting T-024, all new files use
`# ---` plain ASCII section dividers. `state.py` follows this convention.

### cast() over type: ignore

Under `mypy --strict --warn-unused-ignores`, every `# type: ignore` that
becomes unnecessary when packages are installed triggers a new mypy error.
`state_from_json` uses `typing_cast()` instead to convert the raw `dict` to
`InvestmentState` without a type ignore comment.

### version field

The `version: int` field starts at `1` and must be incremented whenever the
state schema changes (fields added or removed). Future Planner nodes can
read `state.get("version", 0)` to detect old snapshots from PostgreSQL and
backfill any newly added fields before passing state to agents.
