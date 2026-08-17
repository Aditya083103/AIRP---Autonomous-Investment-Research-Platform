# backend/evals/__init__.py
"""
AIRP -- LangSmith Evaluation Suites (Phase 11)

Home for every LangSmith-backed evaluator built against the design in
docs/EVAL_FRAMEWORK_DESIGN.md (T-067). Each agent's eval lives in its own
module (e.g. ``fundamental_evaluators.py`` for T-068) so PRs stay scoped to
one agent at a time, matching the Excel plan's one-branch-per-eval layout.

These modules are deliberately NOT imported by ``backend/main.py`` or any
LangGraph node -- they are evaluation tooling invoked manually via
``scripts/run_eval_<agent>.py``, never part of the production request path.
"""
