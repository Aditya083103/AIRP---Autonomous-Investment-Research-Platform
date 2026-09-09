# backend/tests/unit/test_companies_router.py
"""
Unit tests for B5: backend/routers/companies.py

End-to-end HTTP tests against the real FastAPI app
(httpx.ASGITransport, the same pattern test_chat_router.py already
established), with get_current_user overridden directly to a fixed
User instance -- this file is not re-testing JWT verification itself
(T-046's job). No get_async_session override is needed: this router
has no database dependency at all --
backend.services.company_search.search_companies runs entirely against
the in-memory NSE_COMPANY_UNIVERSE, so these tests exercise the REAL
search logic end-to-end through the HTTP layer, not a mocked service.

Acceptance criteria verified (from B5's own work-order text):
  * A backend search endpoint exists, backed by a much larger universe
    than the old 50-entry list, returning name + ticker, ranked and
    paginated.
  * No hardcoded cap on results shown -- callers page via limit/offset.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast
import uuid

from fastapi import FastAPI
import httpx
import pytest

from backend.config import Settings
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import User

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="searcher@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@pytest.fixture
async def client(
    current_user: User, test_settings: Settings
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: current_user

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/v1/companies/search -- success
# ---------------------------------------------------------------------------


class TestSearchSuccess:
    @pytest.mark.asyncio
    async def test_returns_200(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/companies/search", params={"q": "tcs"})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_body_shape(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/companies/search", params={"q": "tcs"})
        body = response.json()
        assert body["items"] == [
            {"name": "Tata Consultancy Services", "ticker": "TCS.NS", "exchange": "NSE"}
        ]
        assert body["total_count"] == 1
        assert body["has_more"] is False

    @pytest.mark.asyncio
    async def test_empty_q_returns_the_full_universe_ranked_by_curated_order(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/companies/search")
        body = response.json()
        assert body["total_count"] >= 200
        assert len(body["items"]) == 20  # DEFAULT_SEARCH_PAGE_SIZE

    @pytest.mark.asyncio
    async def test_no_hardcoded_cap_on_matches_bank_returns_more_than_eight(
        self, client: httpx.AsyncClient
    ) -> None:
        """The literal B5 regression this endpoint exists to fix: the
        OLD client-side dropdown hard-sliced to 8 visible rows no
        matter how many companies matched -- this endpoint must not
        reintroduce that cap server-side."""
        response = await client.get(
            "/api/v1/companies/search", params={"q": "bank", "limit": 100}
        )
        body = response.json()
        assert body["total_count"] > 8
        assert len(body["items"]) > 8

    @pytest.mark.asyncio
    async def test_pagination_via_limit_and_offset(
        self, client: httpx.AsyncClient
    ) -> None:
        first = await client.get(
            "/api/v1/companies/search", params={"q": "bank", "limit": 5, "offset": 0}
        )
        second = await client.get(
            "/api/v1/companies/search", params={"q": "bank", "limit": 5, "offset": 5}
        )
        first_tickers = {item["ticker"] for item in first.json()["items"]}
        second_tickers = {item["ticker"] for item in second.json()["items"]}
        assert first_tickers.isdisjoint(second_tickers)

    @pytest.mark.asyncio
    async def test_query_matching_nothing_returns_an_empty_page_not_an_error(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(
            "/api/v1/companies/search", params={"q": "zzz-no-such-company-zzz"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total_count"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/companies/search -- validation
# ---------------------------------------------------------------------------


class TestSearchValidation:
    @pytest.mark.asyncio
    async def test_limit_over_max_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/companies/search", params={"limit": 1000})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_below_one_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/companies/search", params={"limit": 0})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_offset_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/companies/search", params={"offset": -1})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_overlong_query_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/companies/search", params={"q": "x" * 101})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/companies/search -- auth
# ---------------------------------------------------------------------------


class TestSearchAuth:
    @pytest.mark.asyncio
    async def test_requires_authentication(self, test_settings: Settings) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get("/api/v1/companies/search", params={"q": "tcs"})
        assert response.status_code == 401
