# backend/services/chat_cache.py
"""
AIRP -- AIRP Assistant reply cache (B9)

Caches a repeated, identical question's FULL assistant reply so re-asking
the same thing within a short TTL window is served from Redis instead of
re-invoking the LLM (and, for a portfolio-wide or tool-eligible question,
re-running the tool-calling round -- a DB query and/or a live yFinance
call -- that produced it the first time).

Root cause this closes: nothing in backend/routers/chat_stream.py's
per-turn loop ever consulted a cache at all -- two identical questions,
seconds apart, each triggered a full LLM call (and, once B9's tool
binding lands, a full tool round too) from scratch.

Key: (user_id, session-scope, normalized question)
------------------------------------------------------------------------
Scoped per user (never shared across users -- two different users asking
"what is my portfolio's average conviction score" must never see each
other's answer) and per session-scope:

  * memo_scoped session -- scope is the analysis_id. Re-asking the exact
    same question about a DIFFERENT memo, even with identical text, is a
    cache miss -- the grounded context differs entirely.
  * portfolio_wide session -- scope is a fixed placeholder
    (_PORTFOLIO_SCOPE) shared across every portfolio-wide session for
    that user, since the tools it calls (get_user_analyses,
    get_memo_by_ticker, search_uploaded_documents) are not scoped to one
    session_id and the underlying data they read does not depend on
    which conversation asked about it.

The question text is normalised (trimmed, lower-cased, internal
whitespace collapsed) before hashing so "What's my PE ratio?" and
"what's my pe ratio?  " hit the same cache entry -- matching this
project's existing normalise-then-cache convention (see
backend.services.preference_extractor's own text-normalisation step for
a sibling example of the same idea applied to a different chat feature).

Why a short TTL (10 minutes), not stock_price.py's 6-hour STOCK_TTL
------------------------------------------------------------------------
A cached chat reply can reference BOTH live market data (a fetch_ratios/
fetch_stock_price result, itself already cached for hours by
backend.tools.cache -- see backend/tools/stock_price.py) AND the user's
own analysis history, which can change the moment a new analysis
completes. A long TTL here would risk serving a stale "you have 2 BUY
calls" answer well after a 3rd just finished. 10 minutes is long enough
to absorb the realistic "the user re-asks the same thing a few seconds
or minutes later" case this feature exists for, short enough that a
newly completed analysis or a materially different live price is
reflected again soon.

Design decisions
------------------------------------------------------------------------
* Reuses backend.tools.cache's existing Redis-backed cache_get_json/
  cache_set_json (never-raises, test-env no-op) rather than introducing
  a second caching mechanism -- this module is a thin, chat-specific key
  scheme layered on top of infrastructure that already exists.
* Caches the reply TEXT only, not the tool-calling decision or any
  intermediate messages -- the cheapest possible cache to reason about,
  and correct: a cache hit skips the LLM/tool round entirely rather than
  replaying a stale tool result through a fresh LLM call.
* Never raises. A cache miss, a corrupt cache entry, or a Redis outage
  all degrade to "generate a fresh reply", exactly the same fire-and-
  forget contract backend.tools.cache.cached already documents for
  every other cache in this codebase.

Public API
----------
    from backend.services.chat_cache import (
        CHAT_REPLY_CACHE_TTL_SECONDS,
        normalize_question,
        build_cache_key,
        get_cached_reply,
        set_cached_reply,
    )
"""

import hashlib
import logging
from typing import Optional
import uuid

from backend.tools.cache import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

__all__ = [
    "CHAT_REPLY_CACHE_TTL_SECONDS",
    "PORTFOLIO_SCOPE",
    "normalize_question",
    "build_cache_key",
    "get_cached_reply",
    "set_cached_reply",
]

#: How long a cached reply stays valid. See the module docstring's "Why
#: a short TTL" section for the reasoning behind this specific value.
CHAT_REPLY_CACHE_TTL_SECONDS = 600  # 10 minutes

#: Fixed session-scope placeholder for every portfolio-wide session --
#: see the module docstring's "Key" section for why this is shared
#: across sessions rather than keyed per session_id.
PORTFOLIO_SCOPE = "portfolio"


def normalize_question(text: str) -> str:
    """
    Normalise a question's text for cache-key purposes: trim, lower-case,
    and collapse any run of internal whitespace to a single space.

    Deliberately simple (no punctuation stripping, no stemming) -- the
    goal is to absorb the most common "same question, different
    formatting" cases (leading/trailing spaces, a stray double space,
    inconsistent casing), not to build a fuzzy-matching question
    canonicaliser. Two questions that are genuinely different beyond
    whitespace/case are two different cache entries, which is the
    correct, conservative default.
    """
    return " ".join(text.strip().lower().split())


def build_cache_key(user_id: uuid.UUID, session_scope: str, question: str) -> str:
    """
    Build the Redis key for one (user, session-scope, question) cache
    entry.

    The question text itself is hashed (SHA-256) rather than embedded
    verbatim in the key -- an arbitrarily long user question must not
    produce an arbitrarily long Redis key, and hashing the ALREADY-
    normalised text (see ``normalize_question``) is what makes two
    differently-formatted-but-equivalent questions collide on the same
    key in the first place.

    Args:
        user_id:       UUID of the authenticated chat requester.
        session_scope: The analysis_id (as a string) for a memo-scoped
                       session, or ``"portfolio"`` for a portfolio-wide
                       one -- see the module docstring's "Key" section.
        question:      The raw question text as the user typed it (NOT
                       pre-normalised -- this function normalises it).

    Returns:
        A Redis key string, e.g.
        ``"airp:chat_reply:<user_id>:<scope>:<sha256-hex>"``.
    """
    normalized = normalize_question(question)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"airp:chat_reply:{user_id}:{session_scope}:{digest}"


def get_cached_reply(cache_key: str) -> Optional[str]:
    """
    Return the cached reply for ``cache_key``, or None on a miss.

    Never raises -- see this module's docstring. A cached entry whose
    shape does not match what ``set_cached_reply`` writes (a corrupt or
    pre-B9 value under the same key, in principle) is treated as a miss
    rather than crashing the turn.
    """
    cached = cache_get_json(cache_key)
    if cached is None:
        return None
    reply = cached.get("reply")
    if not isinstance(reply, str):
        logger.warning(
            "chat_cache: cached value for %r has no usable 'reply' string "
            "-- treating as a miss",
            cache_key,
        )
        return None
    return reply


def set_cached_reply(cache_key: str, reply: str) -> None:
    """
    Cache ``reply`` under ``cache_key`` for ``CHAT_REPLY_CACHE_TTL_SECONDS``.

    Never raises (delegates to ``backend.tools.cache.cache_set_json``,
    which already never raises) -- a failed cache write must never fail
    the chat turn that already succeeded and is about to be persisted
    and returned to the user regardless.
    """
    cache_set_json(cache_key, {"reply": reply}, CHAT_REPLY_CACHE_TTL_SECONDS)
