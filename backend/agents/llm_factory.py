"""
AIRP — LLM Factory

Single place to get the configured LLM instance.
Switch between Groq (dev, free) and Anthropic (demo, paid)
by changing LLM_PROVIDER in .env — zero code changes.

Usage:
    from agents.llm_factory import get_llm
    llm = get_llm()
"""

from backend.config import settings


def get_llm():
    """Return the configured LLM based on LLM_PROVIDER env var."""
    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            api_key=settings.groq_api_key,
            model_name=settings.groq_model,
            temperature=0,  # deterministic outputs for financial analysis
        )
    else:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            temperature=0,
        )
