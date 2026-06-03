# graph/

LangGraph StateGraph definition — the orchestration brain of AIRP.

## Files (added in Phase 3)
| File | Purpose |
|------|---------|
| `state.py` | `InvestmentState` TypedDict — the single shared state object passed through every node |
| `graph.py` | `StateGraph` definition — nodes, edges, parallel Send API calls, conditional routing |
| `nodes.py` | Thin wrapper functions that call agents and return updated state |
| `routing.py` | Conditional edge functions (error handling, escalation logic) |
