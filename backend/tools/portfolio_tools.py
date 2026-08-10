# backend/tools/portfolio_tools.py
"""
AIRP -- Portfolio-Wide AIRP Assistant Tools (T-101)

Three LangChain tools for portfolio-wide chat sessions (T-099's
``chat_sessions.session_type = 'portfolio_wide'``) -- the counterpart to
T-100's memo-scoped context builder. Where T-100 answers questions
grounded in ONE already-open analysis, these tools let the chat agent
answer questions that span the user's whole history:

    get_user_analyses         -- "which of my BUY calls are up this
                                  month?", "show me my last 5 analyses"
    get_memo_by_ticker         -- "what did AIRP say about TCS?",
                                  "pull up my Infosys memo"
    search_uploaded_documents  -- "find the debt covenant clause in the
                                  annual report I uploaded"

Why a factory, not three plain module-level ``@tool`` functions
-------------------------------------------------------------------
``get_user_analyses`` and ``get_memo_by_ticker`` both read from the
``analyses``/``companies`` tables scoped to exactly one user -- and
that user MUST be the authenticated chat requester, never a value the
tool's own arguments accept. A LangChain ``@tool``'s parameters become
part of the JSON schema an LLM fills in at call time; if ``user_id``
were one of those parameters, a manipulated or simply confused model
turn could pass a different user's UUID and read their portfolio. So
``user_id`` (and the ``AsyncSession`` needed to query it) are never
tool arguments -- they are captured in a closure by
``build_portfolio_tools(session, user_id, chroma=None)``, which returns
three tool instances already bound to one request's identity. The chat
router/service (a later task) calls this factory once per turn with the
authenticated session's ``user_id`` and hands the returned tools to the
LLM; the LLM only ever sees and fills in the natural-language-relevant
parameters (``verdict``, ``ticker``, ``query``, ``limit``...).

``search_uploaded_documents`` does not need ``user_id`` at all --
``backend.db.chroma_client.ingest_document`` (T-051) never wrote a
``user_id`` into a chunk's ChromaDB metadata (only ``company``,
``ticker``, ``source_filename``, ``doc_type``, ``chunk_index``), so
there is no per-user filter to apply even in principle: any uploaded
document is searchable by any authenticated user today. That is a
pre-existing property of the T-051 ingestion pipeline, not something
introduced or worked around here -- extending ChromaDB metadata with
per-user scoping is a larger, separate change or a fix to make, out of
scope for a task whose acceptance criteria are "wrap the existing
semantic_search". It is still included in the same factory (with an
optional injectable ``chroma`` client, mirroring ``semantic_search``'s
own ``chroma: ChromaClient | None = None`` pattern) purely so one call
to ``build_portfolio_tools`` hands the chat loop all three tools
together.

Why async tools for get_user_analyses / get_memo_by_ticker
-------------------------------------------------------------
Every existing ``@tool`` in ``backend/tools/`` (``fetch_stock_price``,
``fetch_news``, ``fetch_ratios``...) is synchronous -- they wrap
external HTTP/scrape calls invoked from LangGraph's worker-thread node
execution model. These two tools instead read the SAME async
SQLAlchemy ``AsyncSession`` every FastAPI route handler in this codebase
already uses; wrapping an async database call in a sync tool would mean
either blocking the event loop or spinning up a second event loop
per call (the exact ``asyncio.run()``-inside-a-running-loop problem
``backend/services/state_persistence.py`` documents at length for a
different code path). ``langchain_core.tools.tool`` supports decorating
an ``async def`` directly -- the resulting tool exposes ``.ainvoke()``
for an async caller (the chat loop, itself running inside an async
FastAPI request) to await normally. ``search_uploaded_documents``
touches no async resource (ChromaDB's Python client is synchronous), so
it stays a plain sync tool, matching every other ChromaDB-backed call
site in this codebase (e.g. ``backend/agents/sentiment_analyst.py``'s
own direct, synchronous ``semantic_search`` call).

Design decisions
-----------------
* Every tool returns ``dict[str, Any]`` -- matches the universal
  convention across every ``@tool`` in this codebase
  (``fetch_stock_price``, ``fetch_news``, ``fetch_ratios``, ...).
* Every tool degrades gracefully and never raises -- an empty result
  set is a normal, well-formed dict (``{"count": 0, ...}``), and an
  unresolvable ticker or malformed input produces a clearly-labelled
  ``{"error": ..., "message": ...}`` dict, exactly as
  ``fetch_stock_price`` does for ``TickerNotFoundError``.
* Each tool's core logic lives in a private, plain ``async``/sync
  function (``_get_user_analyses_core``, ``_get_memo_by_ticker_core``,
  ``_search_uploaded_documents_core``) that the ``@tool``-decorated
  closure inside the factory simply calls -- the exact separation
  ``backend/tools/stock_price.py`` already established ("Core...
  separated from the LangChain @tool decorator so it can be called
  directly in tests without invoking the full tool machinery"). Every
  core function is unit tested directly, satisfying "each tool
  independently unit tested" without needing a LangChain agent
  executor or LLM call in the test suite at all.
* ``get_user_analyses`` and ``get_memo_by_ticker`` read
  ``analyses.state_snapshot`` via raw SQL (``sqlalchemy.text``), the
  same pattern ``backend/services/analysis.py`` and
  ``backend/services/chat_service.py`` both use for the identical
  reason: ``state_snapshot`` is a T-033-migration-only column, never
  added to the ``Analysis`` ORM model.
* ``search_uploaded_documents`` is a thin, literal wrapper around
  ``backend.db.chroma_client.semantic_search`` with
  ``collection_name=COLLECTION_DOCUMENTS`` fixed -- exactly what the
  acceptance criteria specify, no additional logic.
* NO ``from __future__ import annotations``... actually used here
  (unlike ``backend/services/*.py``): this module defines no Pydantic
  ``BaseModel`` subclasses, only plain ``dict[str, Any]`` returns, so
  the future import carries none of the union-resolution risk that
  rule exists to avoid, matching the majority convention already in
  ``backend/tools/`` (``news.py``, ``macro.py``, ``ratios.py`` all use
  it; only ``stock_price.py``, which predates the others, does not).
* Plain ASCII section comments (# ---) -- established AIRP convention.
* No bare ``type: ignore`` -- cast()/explicit annotations only.

Public API
----------
    from backend.tools.portfolio_tools import build_portfolio_tools

    tools = build_portfolio_tools(session, user_id)
    # tools == [get_user_analyses, get_memo_by_ticker, search_uploaded_documents]
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
import uuid

from langchain_core.tools import BaseTool, tool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.chroma_client import COLLECTION_DOCUMENTS, ChromaClient, semantic_search

logger = logging.getLogger(__name__)

__all__ = [
    "build_portfolio_tools",
    "DEFAULT_ANALYSES_LIMIT",
    "MAX_ANALYSES_LIMIT",
    "DEFAULT_SEARCH_RESULTS",
    "MAX_SEARCH_RESULTS",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default / maximum rows get_user_analyses returns in one call. Kept
#: much smaller than backend.services.analysis's
#: DEFAULT_HISTORY_PAGE_SIZE/MAX_HISTORY_PAGE_SIZE (20/100) -- this
#: result gets read by an LLM as prompt context, not paginated by a
#: human scrolling a dashboard, so a lean default keeps the tool
#: result token-cheap and the hard cap keeps a single call bounded.
DEFAULT_ANALYSES_LIMIT = 10
MAX_ANALYSES_LIMIT = 25

#: Default / maximum documents search_uploaded_documents returns.
#: Mirrors semantic_search's own default (n_results=5) and
#: backend.db.chroma_client.MAX_QUERY_RESULTS as the hard ceiling.
DEFAULT_SEARCH_RESULTS = 5
MAX_SEARCH_RESULTS = 20

_VALID_VERDICTS: frozenset[str] = frozenset({"BUY", "HOLD", "SELL"})


# ---------------------------------------------------------------------------
# get_user_analyses -- core
# ---------------------------------------------------------------------------

#: Optional-filter query: verdict and ticker are applied only when the
#: corresponding bind parameter is non-NULL (":verdict IS NULL OR ..."
#: is a standard Postgres pattern for "this filter is optional" inside
#: one static, parameterised query -- avoids building SQL strings by
#: hand for each filter combination). Verdict/conviction come out of
#: the JSONB state_snapshot via the same ->> extraction
#: backend.services.analysis._SQL_LOAD_HISTORY_PAGE already uses.
_SQL_GET_USER_ANALYSES = text(
    """
    SELECT a.id,
           c.name,
           c.ticker_yf,
           c.exchange,
           a.status,
           a.completed_at,
           a.state_snapshot -> 'decision' ->> 'verdict'          AS verdict,
           a.state_snapshot -> 'decision' ->> 'conviction_score' AS conviction_score,
           a.state_snapshot -> 'decision' ->> 'price_target'     AS price_target
      FROM analyses a
      JOIN companies c ON c.id = a.company_id
     WHERE a.user_id = CAST(:user_id AS uuid)
       AND a.status = 'completed'
       AND (:verdict IS NULL OR a.state_snapshot -> 'decision' ->> 'verdict' = :verdict)
       AND (
            :ticker IS NULL
            OR c.ticker_yf ILIKE :ticker
            OR c.ticker ILIKE :ticker
       )
     ORDER BY a.completed_at DESC
     LIMIT :limit
    """
)


async def _get_user_analyses_core(
    session: AsyncSession,
    user_id: uuid.UUID,
    verdict: Optional[str] = None,
    ticker: Optional[str] = None,
    limit: int = DEFAULT_ANALYSES_LIMIT,
) -> dict[str, Any]:
    """
    List the caller's own past completed analyses, newest first.

    Args:
        session: Active AsyncSession for this request.
        user_id: UUID of the authenticated chat requester -- bound by
                 the factory closure, never an LLM-fillable argument.
        verdict: Optional filter -- one of "BUY"/"HOLD"/"SELL"
                 (case-insensitive). Invalid values are reported back
                 as an error rather than silently ignored.
        ticker:  Optional filter -- matches either the Yahoo Finance
                 ticker (e.g. "TCS.NS") or the bare ticker (e.g.
                 "TCS"), case-insensitively.
        limit:   Maximum rows to return. Clamped to
                 [1, MAX_ANALYSES_LIMIT].

    Returns:
        ``{"count": int, "analyses": [...]}`` on success, or
        ``{"error": "invalid_verdict", "message": ...}`` when
        ``verdict`` is set but not one of BUY/HOLD/SELL.
    """
    normalised_verdict: Optional[str] = None
    if verdict is not None:
        normalised_verdict = verdict.strip().upper()
        if normalised_verdict not in _VALID_VERDICTS:
            return {
                "error": "invalid_verdict",
                "message": (
                    f"verdict must be one of {sorted(_VALID_VERDICTS)}, "
                    f"got {verdict!r}"
                ),
            }

    clamped_limit = max(1, min(limit, MAX_ANALYSES_LIMIT))

    result = await session.execute(
        _SQL_GET_USER_ANALYSES,
        {
            "user_id": str(user_id),
            "verdict": normalised_verdict,
            "ticker": ticker,
            "limit": clamped_limit,
        },
    )
    rows = result.fetchall()

    analyses = [
        {
            "analysis_id": str(row[0]),
            "company_name": row[1],
            "ticker": row[2],
            "exchange": row[3],
            "status": row[4],
            "completed_at": row[5].isoformat() if row[5] is not None else None,
            "verdict": row[6],
            "conviction_score": int(row[7]) if row[7] is not None else None,
            "price_target": row[8],
        }
        for row in rows
    ]

    logger.info(
        "get_user_analyses: user_id=%s verdict=%s ticker=%s -> %d rows",
        user_id,
        normalised_verdict,
        ticker,
        len(analyses),
    )

    return {"count": len(analyses), "analyses": analyses}


# ---------------------------------------------------------------------------
# get_memo_by_ticker -- core
# ---------------------------------------------------------------------------

#: Most recent completed analysis for one ticker, scoped to the caller.
#: Matches either ticker_yf or the bare ticker, case-insensitively, so
#: an LLM-supplied "TCS" and "TCS.NS" both resolve to the same company.
_SQL_GET_MEMO_BY_TICKER = text(
    """
    SELECT a.id,
           c.name,
           c.ticker_yf,
           c.exchange,
           a.completed_at,
           a.state_snapshot
      FROM analyses a
      JOIN companies c ON c.id = a.company_id
     WHERE a.user_id = CAST(:user_id AS uuid)
       AND a.status = 'completed'
       AND (c.ticker_yf ILIKE :ticker OR c.ticker ILIKE :ticker)
     ORDER BY a.completed_at DESC
     LIMIT 1
    """
)


async def _get_memo_by_ticker_core(
    session: AsyncSession,
    user_id: uuid.UUID,
    ticker: str,
) -> dict[str, Any]:
    """
    Fetch the caller's most recent completed memo for one ticker.

    Args:
        session: Active AsyncSession for this request.
        user_id: UUID of the authenticated chat requester -- bound by
                 the factory closure, never an LLM-fillable argument.
        ticker:  Ticker or bare symbol to look up (e.g. "TCS.NS" or
                 "TCS"), case-insensitive.

    Returns:
        A dict with the memo's key fields on success, or
        ``{"error": "not_found", "ticker": ticker, "message": ...}``
        when the caller has no completed analysis for that ticker.
    """
    if not ticker or not ticker.strip():
        return {
            "error": "invalid_ticker",
            "message": "ticker must be a non-empty string",
        }

    result = await session.execute(
        _SQL_GET_MEMO_BY_TICKER,
        {"user_id": str(user_id), "ticker": ticker.strip()},
    )
    row = result.fetchone()

    if row is None:
        logger.info(
            "get_memo_by_ticker: user_id=%s ticker=%s -> no completed analysis",
            user_id,
            ticker,
        )
        return {
            "error": "not_found",
            "ticker": ticker,
            "message": (
                f"No completed analysis found for ticker {ticker!r} " "in your history."
            ),
        }

    snapshot_val: Any = row[5]
    decision = _parse_decision(snapshot_val)
    if decision is None:
        logger.warning(
            "get_memo_by_ticker: user_id=%s ticker=%s -- analysis found but "
            "state_snapshot has no usable decision",
            user_id,
            ticker,
        )
        return {
            "error": "no_decision",
            "ticker": ticker,
            "message": (
                "A completed analysis exists for this ticker, but its "
                "decision data is missing or malformed."
            ),
        }

    logger.info(
        "get_memo_by_ticker: user_id=%s ticker=%s -> analysis_id=%s",
        user_id,
        ticker,
        row[0],
    )

    return {
        "analysis_id": str(row[0]),
        "company_name": row[1],
        "ticker": row[2],
        "exchange": row[3],
        "completed_at": row[4].isoformat() if row[4] is not None else None,
        "verdict": decision.get("verdict"),
        "conviction_score": decision.get("conviction_score"),
        "price_target": decision.get("price_target"),
        "time_horizon": decision.get("time_horizon"),
        "executive_summary": decision.get("executive_summary"),
        "investment_thesis": decision.get("investment_thesis"),
    }


def _parse_decision(snapshot_val: Any) -> Optional[dict[str, Any]]:
    """
    Normalise ``analyses.state_snapshot`` (JSONB) and return its
    ``decision`` key, or None if missing/malformed.

    A small, local duplicate of the same normalise-then-extract step
    ``backend.services.analysis`` and ``backend.services.chat_service``
    each keep their own copy of, for the same reason both of those
    modules give: this caller only ever needs one key back out of the
    parsed dict, so a shared private cross-module helper would be more
    machinery than the handful of lines it replaces.
    """
    if snapshot_val is None:
        return None

    if isinstance(snapshot_val, dict):
        snapshot: Any = snapshot_val
    else:
        try:
            snapshot = json.loads(str(snapshot_val))
        except json.JSONDecodeError:
            return None

    if not isinstance(snapshot, dict):
        return None

    decision = snapshot.get("decision")
    if not isinstance(decision, dict) or not decision:
        return None
    return decision


# ---------------------------------------------------------------------------
# search_uploaded_documents -- core
# ---------------------------------------------------------------------------


def _search_uploaded_documents_core(
    query: str,
    ticker: Optional[str] = None,
    n_results: int = DEFAULT_SEARCH_RESULTS,
    chroma: Optional[ChromaClient] = None,
) -> dict[str, Any]:
    """
    Semantic search over the ``airp_documents`` ChromaDB collection.

    A thin wrapper around ``backend.db.chroma_client.semantic_search``
    with ``collection_name=COLLECTION_DOCUMENTS`` fixed -- the exact
    "wrapping the existing semantic_search" the acceptance criteria
    describe, no additional logic.

    Args:
        query:     Natural-language search string.
        ticker:    Optional ticker to restrict results to one company's
                   uploaded documents (passed through to
                   semantic_search's own ``company_filter``).
        n_results: Maximum chunks to return. Clamped to
                   [1, MAX_SEARCH_RESULTS].
        chroma:    ChromaClient to search. Defaults to a fresh client
                   via semantic_search's own default when None; tests
                   inject a fake/ephemeral client instead.

    Returns:
        ``{"query": query, "count": int, "results": [...]}``. An empty
        ``results`` list (count=0) is a normal, well-formed response --
        it means no uploaded document matched, not an error.
    """
    if not query or not query.strip():
        return {
            "error": "invalid_query",
            "message": "query must be a non-empty string",
        }

    clamped_n_results = max(1, min(n_results, MAX_SEARCH_RESULTS))

    results = semantic_search(
        query,
        collection_name=COLLECTION_DOCUMENTS,
        n_results=clamped_n_results,
        company_filter=ticker,
        chroma=chroma,
    )

    logger.info(
        "search_uploaded_documents: query=%r ticker=%s -> %d results",
        query,
        ticker,
        len(results),
    )

    return {"query": query, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Factory -- builds all 3 tools bound to one request's identity
# ---------------------------------------------------------------------------


def build_portfolio_tools(
    session: AsyncSession,
    user_id: uuid.UUID,
    chroma: Optional[ChromaClient] = None,
) -> list[BaseTool]:
    """
    Build the 3 portfolio-wide AIRP Assistant tools for one chat turn.

    ``session``/``user_id``/``chroma`` are captured in a closure, NOT
    exposed as tool arguments -- see this module's docstring for why
    that is a security requirement, not a style choice, for the two
    tools that read a user's own analysis history.

    Args:
        session: Active AsyncSession for this request. The caller owns
                 its lifecycle (open/close) exactly as any other route
                 handler does -- this factory does not open or close
                 it.
        user_id: UUID of the authenticated chat requester. Every
                 result get_user_analyses/get_memo_by_ticker return is
                 scoped to this user and no other.
        chroma:  Optional ChromaClient for search_uploaded_documents.
                 Defaults to semantic_search's own default (a fresh
                 client via build_chroma_client()) when None.

    Returns:
        ``[get_user_analyses, get_memo_by_ticker, search_uploaded_documents]``
        -- three LangChain ``BaseTool`` instances ready to hand to an
        agent executor.
    """

    @tool
    async def get_user_analyses(
        verdict: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = DEFAULT_ANALYSES_LIMIT,
    ) -> dict[str, Any]:
        """
        List the user's own past completed analyses, newest first.

        Use this to answer questions like "show me my last 5
        analyses", "which of my BUY calls do I have?", or "have I
        analysed Infosys before?".

        Args:
            verdict: Optional filter -- one of "BUY", "HOLD", "SELL".
            ticker:  Optional filter -- a ticker symbol (e.g. "TCS" or
                     "TCS.NS") to restrict results to one company.
            limit:   Maximum number of analyses to return (default 10,
                     max 25).

        Returns:
            Dict with "count" and "analyses" -- a list of
            {analysis_id, company_name, ticker, exchange, status,
            completed_at, verdict, conviction_score, price_target}.
        """
        return await _get_user_analyses_core(
            session, user_id, verdict=verdict, ticker=ticker, limit=limit
        )

    @tool
    async def get_memo_by_ticker(ticker: str) -> dict[str, Any]:
        """
        Fetch the user's most recent completed investment memo for one
        ticker.

        Use this to answer questions like "what did AIRP say about
        TCS?" or "pull up my Infosys memo".

        Args:
            ticker: Ticker symbol or bare name (e.g. "TCS.NS" or "TCS").

        Returns:
            Dict with the memo's verdict, conviction score, price
            target, time horizon, executive summary, and investment
            thesis on success; an "error" dict (e.g. "not_found") if
            the user has no completed analysis for that ticker.
        """
        return await _get_memo_by_ticker_core(session, user_id, ticker=ticker)

    @tool
    def search_uploaded_documents(
        query: str,
        ticker: Optional[str] = None,
        n_results: int = DEFAULT_SEARCH_RESULTS,
    ) -> dict[str, Any]:
        """
        Semantic search over the user's uploaded documents (annual
        reports, earnings-call transcripts) in the airp_documents
        ChromaDB collection.

        Use this to answer questions like "find the debt covenant
        clause in the annual report I uploaded" or "what did the
        earnings call transcript say about margin guidance?".

        Args:
            query:     Natural-language search string.
            ticker:    Optional ticker to restrict results to one
                       company's uploaded documents.
            n_results: Maximum matching chunks to return (default 5,
                       max 20).

        Returns:
            Dict with "query", "count", and "results" -- a list of
            matching chunks, each with "id", "document" (the chunk
            text), "distance", and stored metadata (company, ticker,
            source_filename, doc_type, chunk_index).
        """
        return _search_uploaded_documents_core(
            query=query, ticker=ticker, n_results=n_results, chroma=chroma
        )

    return [get_user_analyses, get_memo_by_ticker, search_uploaded_documents]
