# backend/agents/__init__.py
"""
AIRP agents package.

The 8-agent investment committee: Fundamental Analyst, Technical Analyst,
News Sentiment, Macro Economist, Risk Officer, Contrarian Investor,
Valuation Agent, Portfolio Manager -- each in its own module, plus the
shared output_models.py (Pydantic schemas), llm_factory.py (provider
switch), and tracing.py (LangSmith instrumentation) they all depend on.

T-074 audit finding C12: this file was previously missing while sibling
packages (backend/db/, backend/models/, backend/routers/) all had one --
added for consistency with backend/py.typed's implicit-package assumption.
No re-exports here on purpose: every agent module is imported directly
(``from backend.agents.fundamental_analyst import run_fundamental_analysis``),
so adding imports here would only risk introducing a circular-import
surface with no consumer that needs it.
"""
