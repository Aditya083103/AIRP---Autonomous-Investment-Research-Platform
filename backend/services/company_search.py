# backend/services/company_search.py
"""
AIRP -- Company search service (B5)

Backs ``GET /api/v1/companies/search`` (backend/routers/companies.py):
a ranked, paginated search over ``backend.data.nse_company_universe
.NSE_COMPANY_UNIVERSE`` -- the backend half of fixing bug #5
("ticker dropdown only shows ~50 companies"). Pure in-memory logic, no
database access -- the universe is a small (~270-entry), static,
process-wide constant, so there is nothing to query and nothing that
benefits from a DB round trip the way a per-user table would.

Why this is a real search (ranked, paginated), not a substring filter
returning everything that matches
------------------------------------------------------------------------
``frontend/src/components/analysis/CompanyAutocomplete.tsx``'s OLD
behaviour -- filtering ``NSE_TOP_50`` client-side and hard-slicing to 8
visible rows -- is exactly the bug this endpoint replaces: a query like
"bank" matching 20+ companies needs those 20+ ranked by relevance (an
exact ticker match or a name/ticker PREFIX match belongs above a match
buried in the middle of a longer name), and the CLIENT should decide
how many it can usefully render (via limit/offset), not this function
silently truncating its own result set.

Ranking (best match first)
------------------------------------------------------------------------
For a non-empty, normalised (trimmed, lower-cased) query, each entry is
scored by the BEST (lowest-numbered) tier it qualifies for:
  0. bare ticker equals the query exactly (e.g. "tcs" -> TCS.NS)
  1. ticker starts with the query
  2. name starts with the query
  3. ticker contains the query
  4. name contains the query
An entry that matches no tier is excluded entirely. Within a tier,
entries are sorted alphabetically by name for a stable, predictable
order run to run. An empty/whitespace-only query matches everything,
returned in ``NSE_COMPANY_UNIVERSE``'s own (curated, sector-grouped)
order -- there is no relevance signal to rank by when nothing was
typed yet, matching CompanyAutocomplete's pre-B5 behaviour of showing
its full options list on focus before any input.

Public API
----------
    from backend.services.company_search import (
        CompanySearchResult,
        CompanySearchPage,
        DEFAULT_SEARCH_PAGE_SIZE,
        MAX_SEARCH_PAGE_SIZE,
        search_companies,
    )
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.data.nse_company_universe import NSE_COMPANY_UNIVERSE, CompanyEntry

__all__ = [
    "CompanySearchResult",
    "CompanySearchPage",
    "DEFAULT_SEARCH_PAGE_SIZE",
    "MAX_SEARCH_PAGE_SIZE",
    "search_companies",
]

#: Default / maximum page size for GET /api/v1/companies/search.
#: Deliberately larger than the old client-side MAX_VISIBLE_OPTIONS (8)
#: -- B5's whole point is that the dropdown is no longer hard-capped;
#: MAX_SEARCH_PAGE_SIZE is a request-size sanity bound, not a product
#: limit, matching every other paginated endpoint's limit/offset
#: convention in this codebase (see chat_session_service.py's
#: DEFAULT/MAX_SESSIONS_PAGE_SIZE for the identical pattern).
DEFAULT_SEARCH_PAGE_SIZE = 20
MAX_SEARCH_PAGE_SIZE = 100


@dataclass(frozen=True)
class CompanySearchResult:
    """
    One ranked row of a company search -- identical shape to
    CompanyEntry, kept as its own type so this module's public
    contract does not leak the data-layer's internal dataclass.
    """

    name: str
    ticker: str
    exchange: str


@dataclass(frozen=True)
class CompanySearchPage:
    """
    A single page of ``CompanySearchResult`` rows plus pagination
    metadata -- same shape as chat_session_service.ChatSessionPage.
    """

    items: list[CompanySearchResult]
    total_count: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        """True when at least one further row exists beyond this page."""
        return self.offset + len(self.items) < self.total_count


def _match_tier(entry: CompanyEntry, normalized_query: str) -> int | None:
    """
    Return the best-matching rank tier (0 = best) for ``entry`` against
    ``normalized_query``, or None if it does not match at all. See this
    module's own docstring for what each tier means.
    """
    bare_ticker = entry.ticker.split(".", 1)[0].lower()
    name = entry.name.lower()

    if bare_ticker == normalized_query:
        return 0
    if bare_ticker.startswith(normalized_query):
        return 1
    if name.startswith(normalized_query):
        return 2
    if normalized_query in bare_ticker:
        return 3
    if normalized_query in name:
        return 4
    return None


def search_companies(
    query: str,
    limit: int = DEFAULT_SEARCH_PAGE_SIZE,
    offset: int = 0,
) -> CompanySearchPage:
    """
    Rank and paginate ``NSE_COMPANY_UNIVERSE`` against ``query``.

    Args:
        query:  Free-text search input, matched case-insensitively
                against both company name and bare ticker symbol (the
                ``.NS`` suffix is never part of what the caller types).
                Trimmed before matching; empty/whitespace-only matches
                the full universe.
        limit:  Page size, already clamped to
                [1, MAX_SEARCH_PAGE_SIZE] by the router's
                ``Query(ge=1, le=MAX_SEARCH_PAGE_SIZE)`` validation.
        offset: Rows to skip, already clamped to >= 0 by the same
                validation.

    Returns:
        A ``CompanySearchPage`` -- ``total_count`` reflects every
        matching entry (not just this page), so a caller can page
        through the full ranked result set.
    """
    normalized_query = query.strip().lower()

    if not normalized_query:
        ranked = list(NSE_COMPANY_UNIVERSE)
    else:
        scored = (
            (tier, entry)
            for entry in NSE_COMPANY_UNIVERSE
            if (tier := _match_tier(entry, normalized_query)) is not None
        )
        ranked = [
            entry
            for _tier, entry in sorted(scored, key=lambda pair: (pair[0], pair[1].name))
        ]

    page_items = ranked[offset : offset + limit]

    return CompanySearchPage(
        items=[
            CompanySearchResult(
                name=entry.name, ticker=entry.ticker, exchange=entry.exchange
            )
            for entry in page_items
        ],
        total_count=len(ranked),
        limit=limit,
        offset=offset,
    )
