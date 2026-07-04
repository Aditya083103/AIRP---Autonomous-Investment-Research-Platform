# scripts/

One-off utility scripts for local development. Not imported by the application.

## Scripts (added as needed)

| File              | Purpose                                                                   |
| ----------------- | ------------------------------------------------------------------------- |
| `seed_db.py`      | Seed PostgreSQL with sample analysis data for UI development              |
| `test_agent.py`   | Run a single agent in isolation for quick debugging                       |
| `clear_cache.py`  | Flush Redis cache (useful when switching between companies during dev)    |
| `export_graph.py` | Export LangGraph state diagram as Mermaid — updates docs/GRAPH_DIAGRAM.md |
