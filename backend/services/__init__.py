# backend/services/__init__.py
"""
AIRP services package.

Business logic that sits between the routers and the graph/agents/db
layers -- analysis.py, state_persistence.py, ws_broadcaster.py,
memo_generator.py, pdf_export.py, accuracy_tracker.py, chat_service.py,
chat_llm.py, chat_session_service.py, preference_service.py,
preference_extractor.py, documents.py, auth.py, rate_limiter.py.

T-074 audit finding C12: this file was previously missing while sibling
packages (backend/db/, backend/models/, backend/routers/) all had one --
added for consistency with backend/py.typed's implicit-package assumption.
No re-exports here on purpose -- every router imports the specific service
function it needs (``from backend.services.analysis import
run_analysis_pipeline``).
"""
