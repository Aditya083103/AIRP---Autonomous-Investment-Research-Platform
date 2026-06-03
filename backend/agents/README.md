# agents/

One file per agent. Each agent is a self-contained module with:
- A system prompt defining the agent's persona and mandate
- LangChain tool bindings specific to that agent
- A Pydantic output model (e.g. `FundamentalAnalysis`, `TechnicalAnalysis`)
- A `run(state: InvestmentState) -> InvestmentState` function

## Files (added in Phase 2 & 4)
| File | Agent |
|------|-------|
| `fundamental_analyst.py` | ① Fundamental Analyst |
| `technical_analyst.py` | ② Technical Analyst |
| `news_sentiment.py` | ③ News Sentiment Agent |
| `macro_economist.py` | ④ Macro Economist |
| `risk_officer.py` | ⑤ Risk Officer |
| `contrarian_investor.py` | ⑥ Contrarian Investor |
| `valuation_agent.py` | ⑦ Valuation Agent |
| `portfolio_manager.py` | ⑧ Portfolio Manager |
| `base_agent.py` | Shared base class — prompt helpers, retry logic |
