# backend/agents/tracing.py
"""
AIRP -- LangSmith Tracing Utility (T-026)

Connects all four Phase 2 research agents to LangSmith so that every agent
run is visible in the LangSmith dashboard with:
  * Agent name tag      (e.g. 'fundamental_analyst')
  * Company name tag    (e.g. 'TCS')
  * Latency per agent   (automatic -- LangSmith measures wall-clock time)
  * Token usage         (automatic -- LangChain reports tokens per LLM call)
  * Run tree hierarchy  (agent run wraps all tool calls and LLM calls)

Architecture
------------
LangChain's auto-tracing activates when two OS environment variables are
present at the time any LangChain object is first constructed:

    LANGCHAIN_TRACING_V2=true
    LANGSMITH_API_KEY=<key>

These variables already exist in ``settings`` (loaded from .env).  The gap
is that ``settings`` values are Pydantic model attributes -- they live in
Python memory but are NOT automatically mirrored to ``os.environ``, which
is what LangChain's internals inspect.

``configure_tracing()`` bridges that gap: it reads from ``settings`` and
writes to ``os.environ``.  Call it once at application startup (e.g. from
``backend/main.py`` or from the LangGraph entrypoint).  In tests, tracing
is disabled because ``test_settings`` sets ``langsmith_api_key=\"\"``.

``traced_agent`` decorator
--------------------------
Wraps a LangGraph node function with ``@traceable`` from the langsmith SDK.
The decorator:
  1. Creates a named LangSmith run (``run_type="chain"`` for agents)
  2. Attaches ``tags=[agent_name, company_name]`` to the run
  3. Attaches ``metadata={agent_name, analysis_id, company_name}``
  4. Propagates any exception so the run is marked FAILED in LangSmith

Usage in agents
---------------
    from backend.agents.tracing import traced_agent

    @traced_agent("fundamental_analyst")
    def run_fundamental_analysis(state: dict) -> dict:
        ...

LangGraph node functions receive ``state: dict`` and return ``dict``.
The decorator reads ``company_name`` and ``job_id`` from the state dict
and attaches them as LangSmith run metadata automatically.

Acceptance criteria mapping
----------------------------
  * All 4 agent runs visible in LangSmith   ->  @traced_agent on all nodes
  * Correct tags on each run                ->  tags=[agent_name, company_name]
  * Latency per agent visible               ->  automatic (LangSmith wall-clock)
  * Tracing disabled in tests               ->  LANGSMITH_API_KEY="" in conftest

Public interface
----------------
  configure_tracing()      -> None   call at startup; no-op when key absent
  traced_agent(agent_name) -> Callable  decorator factory for node functions
  tracing_is_active()      -> bool   True when env vars are set and key present
"""

from collections.abc import Callable
import functools
import logging
import os
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# LangChain reads these exact environment variable names.
# Do not rename -- they are part of the LangChain public contract.
_ENV_TRACING_V2 = "LANGCHAIN_TRACING_V2"
_ENV_API_KEY = "LANGSMITH_API_KEY"
_ENV_PROJECT = "LANGCHAIN_PROJECT"
_ENV_ENDPOINT = "LANGCHAIN_ENDPOINT"


# ---------------------------------------------------------------------------
# configure_tracing
# ---------------------------------------------------------------------------


def configure_tracing() -> None:
    """
    Mirror LangSmith settings from ``settings`` into ``os.environ``.

    LangChain reads ``LANGCHAIN_TRACING_V2``, ``LANGSMITH_API_KEY``,
    ``LANGCHAIN_PROJECT``, and ``LANGCHAIN_ENDPOINT`` from OS environment
    variables -- not from Python objects.  This function ensures that the
    values already present in ``settings`` (loaded from .env) are written
    to ``os.environ`` so LangChain can find them.

    Idempotent -- safe to call multiple times.  If ``langsmith_api_key``
    is empty (e.g. in tests or when not yet configured), tracing is
    explicitly disabled by setting ``LANGCHAIN_TRACING_V2=false``.

    Call once at application startup before any LangChain object is
    constructed.  In production this is called from ``backend/main.py``.
    In the LangGraph entrypoint it is called before the graph is compiled.

    Returns:
        None.  Side-effect: mutates ``os.environ``.
    """
    if settings.tracing_enabled:
        os.environ[_ENV_TRACING_V2] = "true"
        os.environ[_ENV_API_KEY] = settings.langsmith_api_key
        os.environ[_ENV_PROJECT] = settings.langchain_project
        os.environ[_ENV_ENDPOINT] = settings.langchain_endpoint
        logger.info(
            "LangSmith tracing enabled: project=%s endpoint=%s",
            settings.langchain_project,
            settings.langchain_endpoint,
        )
    else:
        # Explicitly disable so any lingering env var from a previous run
        # or parent shell does not accidentally enable tracing.
        os.environ[_ENV_TRACING_V2] = "false"
        logger.debug(
            "LangSmith tracing disabled "
            "(LANGSMITH_API_KEY absent or LANGCHAIN_TRACING_V2!=true)"
        )


# ---------------------------------------------------------------------------
# tracing_is_active
# ---------------------------------------------------------------------------


def tracing_is_active() -> bool:
    """
    Return True when LangSmith tracing is currently active.

    Checks ``os.environ`` directly (not ``settings``) so it reflects the
    state after ``configure_tracing()`` has been called.  This is the
    function tests use to verify that ``configure_tracing()`` worked.

    Returns:
        bool -- True when both LANGCHAIN_TRACING_V2=true and
        LANGSMITH_API_KEY is non-empty in ``os.environ``.
    """
    return os.environ.get(_ENV_TRACING_V2, "").lower() == "true" and bool(
        os.environ.get(_ENV_API_KEY, "")
    )


# ---------------------------------------------------------------------------
# traced_agent decorator
# ---------------------------------------------------------------------------


def traced_agent(agent_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator factory that wraps a LangGraph node function with LangSmith
    tracing using ``@traceable`` from the langsmith SDK.

    The decorated function:
      1. Reads ``company_name`` and ``job_id`` from the LangGraph state dict
      2. Creates a named LangSmith run via ``@traceable``
      3. Attaches ``tags=[agent_name, company_name]`` (acceptance criteria)
      4. Attaches ``metadata`` with agent_name, analysis_id, company_name
      5. Propagates exceptions so the run is marked FAILED in LangSmith

    When ``LANGCHAIN_TRACING_V2`` is false or ``LANGSMITH_API_KEY`` is absent
    (e.g. in tests), ``@traceable`` is a near-zero-cost no-op -- no network
    calls, no latency overhead.

    Args:
        agent_name: Canonical agent identifier string matching the
                    ``agent_name`` field in the agent's output model
                    (e.g. 'fundamental_analyst', 'news_sentiment').

    Returns:
        A decorator that wraps the LangGraph node function.

    Example::

        @traced_agent("fundamental_analyst")
        def run_fundamental_analysis(state: dict[str, Any]) -> dict[str, Any]:
            ...

    LangSmith dashboard entry produced::

        Run name   : fundamental_analyst
        Run type   : chain
        Tags       : ["fundamental_analyst", "TCS"]
        Metadata   : {"agent_name": "fundamental_analyst",
                      "analysis_id": "uuid-...",
                      "company_name": "TCS"}
        Latency    : <measured automatically>
        Tokens     : <measured automatically from child LLM calls>
    """

    def decorator(
        func: Callable[..., Any],
    ) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            company_name: str = state.get("company_name", "unknown")
            analysis_id: str = state.get("job_id", "unknown")

            # Build per-run tags and metadata for LangSmith.
            # Tags are indexed and searchable in the LangSmith UI.
            run_tags: list[str] = [agent_name, company_name]
            run_metadata: dict[str, str] = {
                "agent_name": agent_name,
                "analysis_id": analysis_id,
                "company_name": company_name,
            }

            # Attempt to wrap with @traceable.  If langsmith is not installed
            # or the SDK raises during decorator construction (unlikely but
            # possible with network issues at import time), fall back to the
            # unwrapped function -- tracing failure must never break the agent.
            try:
                from langsmith import traceable

                traced_func = traceable(
                    run_type="chain",
                    name=agent_name,
                    tags=run_tags,
                    metadata=run_metadata,
                )(func)
                return traced_func(state, *args, **kwargs)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "LangSmith traceable setup failed for %s (non-fatal): %s",
                    agent_name,
                    exc,
                )
                return func(state, *args, **kwargs)

        return wrapper

    return decorator
