# backend/agents/llm_factory.py
"""
AIRP -- LLM Factory (updated T-026)

Single place to get the configured LLM instance.
Switch between Groq (dev, free) and Anthropic (demo, paid)
by changing LLM_PROVIDER in .env -- zero code changes.

T-026 addition: ``get_llm()`` now calls ``configure_tracing()`` before
constructing the LLM object.  LangChain's auto-tracing activates when
``LANGCHAIN_TRACING_V2`` and ``LANGSMITH_API_KEY`` are present in
``os.environ`` at the time the LLM is first constructed.  This ensures
every LLM call made by any agent is automatically captured in LangSmith.

Usage:
    from agents.llm_factory import get_llm
    llm = get_llm()
"""

from __future__ import annotations

from typing import Any

from backend.agents.tracing import configure_tracing
from backend.config import settings


def get_llm() -> Any:
    """
    Return the configured LLM based on LLM_PROVIDER env var.

    Calls ``configure_tracing()`` first so LangChain's auto-tracing is
    active before the LLM object is constructed.  In tests, tracing is
    a no-op (``LANGSMITH_API_KEY`` is empty in ``test_settings``).

    Returns:
        ChatGroq instance when LLM_PROVIDER=groq (default, free tier).
        ChatAnthropic instance when LLM_PROVIDER=anthropic (demo only).
    """
    # Ensure LangSmith env vars are set before any LangChain object is built.
    # configure_tracing() is idempotent -- safe to call on every get_llm().
    configure_tracing()

    # timeout / max_retries are set explicitly on both clients below.
    # Without them, langchain_groq/langchain_anthropic fall back to the
    # underlying SDK's own defaults, which are NOT guaranteed to be
    # bounded -- observed in practice as a node hanging with zero log
    # output (no timeout warning, no traceback) well past
    # node_profiler.NODE_TIMEOUT_S (30s), because that soft-timeout can
    # only detect an overrun *after* the blocking call returns on its
    # own (see node_profiler.py's _ThreadTimeout docstring). Capping the
    # HTTP-level timeout here at 25s -- under NODE_TIMEOUT_S -- means the
    # call itself raises before the node-level timeout would even need
    # to fire, on every platform, not just POSIX (SIGALRM). max_retries=1
    # additionally prevents the SDK's own internal retry/backoff on 429s
    # from silently multiplying that 25s into 60-90+ seconds across
    # several attempts before the exception ever surfaces to AIRP's own
    # try/except graceful-degradation handling in each agent.
    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            api_key=settings.groq_api_key,
            model_name=settings.groq_model,
            temperature=0,
            timeout=25.0,
            max_retries=1,
        )
    else:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            temperature=0,
            timeout=25.0,
            max_retries=1,
        )
