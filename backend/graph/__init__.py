# backend/graph/__init__.py
"""
AIRP graph package.

The LangGraph StateGraph wiring: state.py (InvestmentState), nodes.py (all
15 node functions), routing.py (conditional edges), graph.py (the compiled
graph itself), node_profiler.py (per-node timing), and
graph_visualisation.py (Mermaid/Markdown diagram export).

T-074 audit finding C12: this file was previously missing while sibling
packages (backend/db/, backend/models/, backend/routers/) all had one --
added for consistency with backend/py.typed's implicit-package assumption.
No re-exports here on purpose -- every consumer imports the specific
submodule it needs (``from backend.graph.graph import build_graph``).
"""
