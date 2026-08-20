# backend/tools/__init__.py
"""
AIRP tools package.

LangChain ``@tool``-decorated functions the agents call for external data:
stock_price.py / financials.py / ratios.py (yFinance), news.py (NewsAPI),
macro.py (RBI scraper), earnings_transcript.py / market_data.py /
portfolio_tools.py.

T-074 audit finding C12: this file was previously missing while sibling
packages (backend/db/, backend/models/, backend/routers/) all had one --
added for consistency with backend/py.typed's implicit-package assumption.
No re-exports here on purpose -- every agent imports the specific tool it
needs (``from backend.tools.stock_price import fetch_ohlcv``).
"""
