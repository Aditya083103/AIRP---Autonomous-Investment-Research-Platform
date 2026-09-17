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
    # to fire, on every platform, not just POSIX (SIGALRM).
    #
    # max_retries=0 (NOT 1): both the groq and anthropic Python SDKs
    # implement their OWN internal retry-with-backoff for a 429/5xx
    # BEFORE ever raising back to LangChain -- and per each SDK's own
    # _calculate_retry_timeout, a 429 response's Retry-After header (up
    # to 60s) is honoured as the SLEEP DURATION before that one internal
    # retry, entirely independent of the timeout= above (timeout bounds
    # one HTTP request/response, not a pre-request sleep the SDK does on
    # its own). With max_retries=1, a single rate-limited ainvoke() could
    # therefore silently take up to ~60s (SDK sleep) + 25s (timeout) =
    # 85s to raise -- reproduced live against a real exhausted Groq quota
    # during the chat-fallback bug investigation, a Retry-After of 57s
    # measured directly in this deployment's own logs. max_retries=0
    # disables that internal retry entirely, so a rate-limited call
    # raises immediately and each agent's own try/except (or, for chat,
    # backend/services/chat_llm.py's own fast ~1s-backoff retry plus
    # backend/routers/chat_stream.py's cross-provider fallback) is what
    # actually decides whether and how to retry -- deliberately, since
    # those callers know the real latency budget (a live user-facing
    # wait for chat, node_profiler.NODE_TIMEOUT_S for an agent node) and
    # the SDK's own generic backoff does not.
    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            api_key=settings.groq_api_key,
            model_name=settings.groq_model,
            temperature=0,
            timeout=25.0,
            max_retries=0,
        )
    else:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            temperature=0,
            timeout=25.0,
            max_retries=0,
        )
