# STATE.md -- InvestmentState Reference

**Module:** `backend/graph/state.py`
**Phase:** 3 -- LangGraph Orchestration
**Task:** T-029

---

## Overview

`InvestmentState` is the single shared state object that flows through every
node in the AIRP LangGraph StateGraph. It is defined as a `TypedDict` so it
is statically type-checked by mypy while remaining a plain Python `dict` at
runtime -- which is what LangGraph requires.

No agent communicates with another agent directly. All information exchange
happens through this state object: an agent reads prior outputs from the
state and writes its own output back into the same dict.

---

## Why TypedDict, Not Pydantic

| Concern                 | TypedDict                         | Pydantic                          |
| ----------------------- | --------------------------------- | --------------------------------- |
| LangGraph compatibility | Native -- LangGraph expects dicts | Requires `.model_dump()` wrapping |
| Runtime validation      | None (by design)                  | Full validation on construction   |
| Mutability              | Mutable dict                      | Frozen (agent outputs)            |
| JSON serialisation      | Manual (helpers provided)         | `.model_dump_json()`              |
| mypy coverage           | Full (all fields typed)           | Full                              |

**Agent outputs** (which DO need validation) are stored as pre-serialised
`dict` values obtained by calling `model.model_dump()`. The Pydantic models
in `backend/agents/output_models.py` enforce all field constraints at agent
output time.

---

## State Lifecycle

```
make_initial_state()          <-- Planner node creates state with identity fields
        |
        v
[4 research agents run in parallel, each writing one field]
  state["fundamental"] = FundamentalAnalysis(...).model_dump()
  state["technical"]  = TechnicalAnalysis(...).model_dump()
  state["sentiment"]  = SentimentAnalysis(...).model_dump()
  state["macro"]      = MacroAnalysis(...).model_dump()
        |
        v
[Debate loop, 1-2 rounds]
  state["debate_rounds"] grows with each round
  state["debate_round_count"] incremented
  state["contrarian"] = ContrarianReport(...).model_dump()
        |
        v
[Risk Officer and Valuation Agent run sequentially]
  state["risk"]      = RiskAnalysis(...).model_dump()
  state["valuation"] = ValuationOutput(...).model_dump()
        |
        v
[Portfolio Manager produces final decision]
  state["decision"]        = InvestmentDecision(...).model_dump()
  state["final_verdict"]   = "BUY" / "HOLD" / "SELL"
  state["conviction_score"] = 1-10
        |
        v
[Report Generator creates PDF]
  state["memo_markdown"] = "# TCS Investment Memo\n..."
  state["memo_pdf_path"] = "/outputs/<job_id>.pdf"
        |
        v
[Pipeline complete]
  state["status"]       = "completed"
  state["completed_at"] = "<ISO timestamp>"
```

---

## Field Reference

### Identity Fields

Set by the Planner node before any agent runs.

| Field          | Type            | Description                                                      |
| -------------- | --------------- | ---------------------------------------------------------------- |
| `job_id`       | `str`           | UUID of the analysis job (FK to `analyses.id` in PostgreSQL)     |
| `company_name` | `str`           | Human-readable company name (e.g. `"Tata Consultancy Services"`) |
| `ticker`       | `str`           | Yahoo Finance ticker with exchange suffix (e.g. `"TCS.NS"`)      |
| `exchange`     | `str`           | `"NSE"` or `"BSE"`                                               |
| `isin`         | `Optional[str]` | ISIN code when available (e.g. `"INE467B01029"`)                 |
| `sector`       | `Optional[str]` | Sector string (e.g. `"Information Technology"`)                  |
| `industry`     | `Optional[str]` | Industry string (e.g. `"IT Services & Consulting"`)              |
| `raw_query`    | `str`           | Raw user input before ticker resolution                          |
| `requested_at` | `str`           | UTC ISO timestamp when the analysis was triggered                |
| `requested_by` | `str`           | Clerk user_id of the requester, or `"anonymous"`                 |
| `version`      | `int`           | State schema version (currently `1`)                             |

### Pipeline Status Fields

| Field            | Type            | Description                                            |
| ---------------- | --------------- | ------------------------------------------------------ |
| `status`         | `str`           | `"pending"` / `"running"` / `"completed"` / `"failed"` |
| `current_node`   | `Optional[str]` | Node currently executing (for WebSocket events)        |
| `started_at`     | `Optional[str]` | UTC ISO timestamp when pipeline started                |
| `completed_at`   | `Optional[str]` | UTC ISO timestamp when pipeline finished               |
| `pipeline_error` | `Optional[str]` | Top-level error message on catastrophic failure        |

### Research Agent Output Fields

Each stores the result of `model.model_dump()` -- a JSON-serialisable dict.
The field is **absent** (not `None`) until the agent has run.

| Field         | Type             | Agent                | Output Model          |
| ------------- | ---------------- | -------------------- | --------------------- |
| `fundamental` | `Optional[dict]` | Fundamental Analyst  | `FundamentalAnalysis` |
| `technical`   | `Optional[dict]` | Technical Analyst    | `TechnicalAnalysis`   |
| `sentiment`   | `Optional[dict]` | News Sentiment Agent | `SentimentAnalysis`   |
| `macro`       | `Optional[dict]` | Macro Economist      | `MacroAnalysis`       |

### Debate Fields

| Field                | Type         | Description                                                                                            |
| -------------------- | ------------ | ------------------------------------------------------------------------------------------------------ |
| `debate_round_count` | `int`        | Number of completed debate rounds (0 initially)                                                        |
| `debate_rounds`      | `list[dict]` | Full debate transcript; each dict has: `round_number`, `agent_responses`, `contrarian`, `completed_at` |

### Advanced Agent Output Fields

| Field        | Type             | Agent               | Output Model         |
| ------------ | ---------------- | ------------------- | -------------------- |
| `risk`       | `Optional[dict]` | Risk Officer        | `RiskAnalysis`       |
| `contrarian` | `Optional[dict]` | Contrarian Investor | `ContrarianReport`   |
| `valuation`  | `Optional[dict]` | Valuation Agent     | `ValuationOutput`    |
| `decision`   | `Optional[dict]` | Portfolio Manager   | `InvestmentDecision` |

### Risk Flag Fields

Flat lists aggregated across all agents for fast access by the UI.

| Field            | Type        | Description                            |
| ---------------- | ----------- | -------------------------------------- |
| `risk_flags`     | `list[str]` | All risk flags raised by any agent     |
| `critical_flags` | `list[str]` | Subset of `risk_flags` deemed critical |

### Final Output Fields

| Field              | Type            | Description                                        |
| ------------------ | --------------- | -------------------------------------------------- |
| `final_verdict`    | `Optional[str]` | `"BUY"`, `"HOLD"`, or `"SELL"`                     |
| `conviction_score` | `Optional[int]` | 1-10 Portfolio Manager confidence score            |
| `price_target`     | `Optional[str]` | Price target string (e.g. `"Rs 4,200 (12-month)"`) |
| `memo_markdown`    | `Optional[str]` | Full Investment Memo as Markdown                   |
| `memo_pdf_path`    | `Optional[str]` | Path or URL to the generated PDF memo              |

### Document Upload Fields

Set when the user uploads an annual report or earnings transcript PDF.

| Field                      | Type            | Description                                     |
| -------------------------- | --------------- | ----------------------------------------------- |
| `uploaded_doc_collection`  | `Optional[str]` | ChromaDB collection where document was ingested |
| `uploaded_doc_filename`    | `Optional[str]` | Original filename of the uploaded document      |
| `uploaded_doc_chunk_count` | `Optional[int]` | Number of chunks ingested                       |

### Observability Fields

| Field               | Type             | Description                             |
| ------------------- | ---------------- | --------------------------------------- |
| `langsmith_run_ids` | `dict[str, str]` | LangSmith run IDs keyed by `agent_name` |

---

## Public API

```python
from backend.graph.state import (
    InvestmentState,     # TypedDict -- the state schema
    DebateRound,         # Documentation class for debate round dict shape
    make_initial_state,  # Factory function
    state_to_json,       # Serialiser
    state_from_json,     # Deserialiser
)
```

### `make_initial_state()`

```python
state = make_initial_state(
    job_id="uuid-001",
    company_name="Tata Consultancy Services",
    ticker="TCS.NS",
    exchange="NSE",
    raw_query="TCS",
    requested_by="user_abc123",   # optional, default "anonymous"
    isin="INE467B01029",          # optional
    sector="Information Technology",  # optional
    industry="IT Services & Consulting",  # optional
)
```

### `state_to_json()` / `state_from_json()`

```python
# Serialise for PostgreSQL JSONB storage or WebSocket transmission
json_str: str = state_to_json(state)

# Deserialise from PostgreSQL or WebSocket
recovered: InvestmentState = state_from_json(json_str)
```

`state_to_json` uses `default=str` for the JSON encoder so datetime objects
in agent output dicts (before `model_dump(mode='json')`) are converted to
ISO strings rather than raising `TypeError`.

---

## JSON Serialisation Contract

All values stored in `InvestmentState` must be JSON-serialisable:

- Agent outputs: call `model.model_dump()` (uses Pydantic's serialiser)
- Timestamps: always stored as ISO strings, never as `datetime` objects
- Lists and dicts: only contain `str`, `int`, `float`, `bool`, `list`, `dict`, or `None`

This contract is verified by the `state_to_json` / `state_from_json` round-trip
tests in `backend/tests/unit/test_investment_state.py`.

---

## State Version Migration

The `version` field exists for future-proofing. If a field is added or
removed from `InvestmentState` in a future task, the version number must be
incremented. Migration logic in the Planner node can check
`state.get("version", 0)` to backfill missing fields in state snapshots
loaded from PostgreSQL.

Current version: **1**

---

## Integration Points

| System                | How it uses InvestmentState                                                              |
| --------------------- | ---------------------------------------------------------------------------------------- |
| **LangGraph**         | Passes the full state dict to every node function; merges the returned partial dict back |
| **FastAPI WebSocket** | Reads `current_node` and `status` to push progress events                                |
| **PostgreSQL**        | Stores `state_to_json(state)` in `analyses.raw_state` JSONB column after every node      |
| **ChromaDB**          | Reads `uploaded_doc_collection` to scope RAG queries                                     |
| **LangSmith**         | Reads `langsmith_run_ids` to link agent traces in the dashboard                          |
| **Report Generator**  | Reads `decision`, `fundamental`, `risk`, `valuation` to compose the PDF memo             |

---

_End of STATE.md | AIRP v1.0 | T-029_
