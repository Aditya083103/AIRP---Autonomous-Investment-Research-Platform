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
| `run_eval_fundamental.py` | Run the Fundamental Analyst LangSmith eval (T-068) against the 5-company dataset in `backend/evals/fundamental_eval_dataset.py` — real agent calls, real LLM, prints a pass/fail table + accuracy vs. the >70% target, and (when `LANGSMITH_API_KEY` is set) uploads the dataset and runs a real LangSmith experiment |
| `run_eval_sentiment.py` | Run the Sentiment Agent LangSmith eval (T-069) against the 10 directional news sets + 3 scandal cases in `backend/evals/sentiment_eval_dataset.py` — fully deterministic, no network or LLM call needed for grading; prints a directional-accuracy + red-flag-detection report, and (when `LANGSMITH_API_KEY` is set) uploads both datasets and runs real LangSmith experiments |