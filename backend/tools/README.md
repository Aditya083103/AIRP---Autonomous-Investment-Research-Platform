# tools/

LangChain `@tool` definitions. Each tool wraps one external API or data source.
Tools are imported and bound to agents in `agents/`.

## Files (added in Phase 1)

| File             | Tool(s)                                                            | Data source              |
| ---------------- | ------------------------------------------------------------------ | ------------------------ |
| `stock_price.py` | `fetch_stock_price`, `fetch_ohlcv`                                 | yFinance                 |
| `financials.py`  | `fetch_income_statement`, `fetch_balance_sheet`, `fetch_cash_flow` | yFinance / Alpha Vantage |
| `ratios.py`      | `fetch_ratios`, `fetch_peer_comparison`                            | Screener.in (scrape)     |
| `news.py`        | `fetch_news`, `fetch_sentiment_score`                              | NewsAPI                  |
| `macro.py`       | `fetch_rbi_rate`, `fetch_gdp`, `fetch_inflation`                   | RBI scraper / macro DB   |
| `rag.py`         | `search_transcripts`, `search_annual_report`                       | ChromaDB semantic search |

## Files (added in Phase 10)

| File                 | Tool(s)                                                                              | Data source                                  |
| -------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------- |
| `portfolio_tools.py` | `get_user_analyses`, `get_memo_by_ticker`, `search_uploaded_documents` (via `build_portfolio_tools`) | PostgreSQL (`analyses`/`companies`) / ChromaDB (`airp_documents`) |