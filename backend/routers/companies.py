# backend/routers/companies.py
"""
AIRP -- Company Search Endpoint (B5)

GET /api/v1/companies/search (list companies by name/ticker, ranked)

Fixes bug #5: frontend/src/components/analysis/CompanyAutocomplete.tsx
was backed by a static 51-entry list (frontend/src/data/nseTop50.ts),
so the browsable/searchable dropdown was hard-capped at 50 companies no
matter what the person typed. This endpoint serves
backend.services.company_search's much larger (~270-entry) curated NSE
universe as a real, ranked, paginated search -- CompanyAutocomplete
(frontend, this task) is rewired to query it (debounced) instead of
filtering an in-memory array, with a virtualized dropdown so the whole
result set is browsable rather than silently sliced to a handful of
rows.

Why JWT auth (get_current_user), matching every other feature endpoint
------------------------------------------------------------------------
This search only ever has a caller from within AnalysisPage.tsx /
CompareInputForm.tsx, both already behind ProtectedRoute (see
frontend/src/routes/AppRoutes.tsx) -- there is no unauthenticated use
case for it, and requiring auth here keeps this endpoint consistent
with every other feature router in this codebase (analysis.py,
chat.py, documents.py) rather than being the one unauthenticated
exception.

Why HTTP-layer only, no service-layer changes needed for pagination
validation
------------------------------------------------------------------------
backend.services.company_search.search_companies is pure, synchronous,
in-memory logic with no database access -- this router's only job is
translating query params into that function's arguments and its
CompanySearchPage result into CompanySearchResponse, the same
thin-router convention every other paginated list endpoint in this
codebase already follows (chat.py's list_chat_sessions_endpoint,
accuracy.py's history endpoint).

Design decisions
------------------------------------------------------------------------
* No ``from __future__ import annotations`` -- matches every other
  router in this codebase.
* Plain ASCII section comments (# ---).
* No bare ``type: ignore``.
"""

from fastapi import APIRouter, Depends, Query, status

from backend.dependencies.auth import get_current_user
from backend.models.orm import User
from backend.models.schemas import CompanySearchResponse, CompanySearchResultResponse
from backend.services.company_search import (
    DEFAULT_SEARCH_PAGE_SIZE,
    MAX_SEARCH_PAGE_SIZE,
    search_companies,
)

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])

#: Hard cap on the raw query string length -- generous enough for any
#: realistic company name search, small enough that a pathological
#: client payload cannot inflate request handling for no benefit (the
#: same "small, defensive bound on free-text input" convention
#: backend/routers/chat_stream.py's _MAX_USER_MESSAGE_LENGTH already
#: establishes for a different free-text field).
_MAX_QUERY_LENGTH = 100


@router.get(
    "/search",
    response_model=CompanySearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search the NSE company universe by name or ticker, ranked by relevance",
    description=(
        "Returns one page of companies whose name or ticker matches "
        "`q`, best match first (exact ticker, then ticker/name prefix, "
        "then substring) -- see "
        "backend.services.company_search.search_companies's own "
        "docstring for the full ranking rules. An empty or omitted `q` "
        "returns the full curated universe. Defaults to the first "
        "20 (DEFAULT_SEARCH_PAGE_SIZE) results; pass limit/offset to "
        "page further."
    ),
)
async def search_companies_endpoint(
    q: str = Query(
        default="",
        max_length=_MAX_QUERY_LENGTH,
        description="Free-text search against company name or ticker",
    ),
    limit: int = Query(
        default=DEFAULT_SEARCH_PAGE_SIZE,
        ge=1,
        le=MAX_SEARCH_PAGE_SIZE,
        description="Maximum number of results to return on this page",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of top-ranked results to skip",
    ),
    current_user: User = Depends(get_current_user),
) -> CompanySearchResponse:
    page = search_companies(q, limit=limit, offset=offset)

    return CompanySearchResponse(
        items=[
            CompanySearchResultResponse(
                name=entry.name, ticker=entry.ticker, exchange=entry.exchange
            )
            for entry in page.items
        ],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )
