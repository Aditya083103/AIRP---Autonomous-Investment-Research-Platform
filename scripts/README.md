# scripts/

One-off utility scripts for local development. Not imported by the application.

## Scripts (added as needed)

| File              | Purpose                                                                   |
| ----------------- | ------------------------------------------------------------------------- |
| `seed_db.py`      | Seed PostgreSQL with sample analysis data for UI development              |
| `test_agent.py`   | Run a single agent in isolation for quick debugging                       |
| `clear_cache.py`  | Flush Redis cache (useful when switching between companies during dev)    |
| `export_graph.py` | Export LangGraph state diagram as Mermaid — updates docs/GRAPH_DIAGRAM.md |
| `manual_qa_chat_llm.py` | Run a fixed adversarial conversation against a real LLM to QA the AIRP Assistant's objectivity guardrail (T-102) — prints a PR-ready transcript |
| `manual_qa_chat_personalization.py` | Run a fixed conversation against a real LLM to QA the AIRP Assistant's personalization (T-106) — ask-once, real extractor recognition, side-by-side tone comparison, and a verdict-independence check — prints a PR-ready transcript |