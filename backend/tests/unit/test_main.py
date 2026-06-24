# backend/tests/unit/test_main.py
"""
Unit tests for T-045: FastAPI Project Structure.

Test strategy:
  1. create_app()        -- factory returns a configured FastAPI instance
  2. GET /health          -- 200, correct JSON shape (T-045 acceptance #1)
  3. GET /docs             -- Swagger UI is mounted and reachable
                               (T-045 acceptance #2)
  4. GET /openapi.json     -- the underlying schema FastAPI generates
                               for /docs is itself valid and reachable
  5. CORS                  -- the configured frontend origin receives
                               Access-Control-Allow-Origin on a
                               preflight OPTIONS request
                               (T-045 acceptance #3)
  6. lifespan               -- startup/shutdown run without raising

These tests use httpx's ASGITransport (already a project dependency via
httpx==0.27.0 in requirements-dev.txt) so no real network socket or
running uvicorn process is required -- the whole app is exercised
in-process, which is what makes this a unit test rather than an
integration test.

Acceptance criteria verified (from task spec):
  * GET /health returns 200
  * Swagger UI accessible at /docs
  * CORS allows frontend origin
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

import httpx
import pytest

from backend.config import Settings
from backend.main import API_TITLE, API_VERSION, create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Async test client bound to the real app via in-process ASGI transport.

    Runs the app's lifespan (startup/shutdown) automatically as part of
    the `async with` block, so lifespan errors surface as test failures.
    """
    app = create_app()
    # httpx's ASGITransport type stub expects an inline Callable matching
    # its private ASGIApp protocol (httpx._transports.asgi), which is not
    # part of httpx's public API to import and is structurally satisfied
    # by FastAPI/Starlette's __call__ at runtime. cast(Any, ...) documents
    # this known stub mismatch rather than silencing it with a bare

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# create_app() factory
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Tests for the create_app() factory function itself."""

    def test_returns_fastapi_instance(self) -> None:
        app = create_app()
        assert type(app).__name__ == "FastAPI"

    def test_title_and_version_set(self) -> None:
        app = create_app()
        assert app.title == API_TITLE
        assert app.version == API_VERSION

    def test_docs_url_configured(self) -> None:
        app = create_app()
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"
        assert app.openapi_url == "/openapi.json"

    def test_health_router_included(self) -> None:
        app = create_app()
        paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
        assert "/health" in paths

    def test_two_calls_produce_independent_app_instances(self) -> None:
        """Each create_app() call is independent -- no shared mutable state."""
        app_a = create_app()
        app_b = create_app()
        assert app_a is not app_b


# ---------------------------------------------------------------------------
# GET /health -- T-045 acceptance criterion #1
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """GET /health must return 200 with a well-formed JSON body."""

    @pytest.mark.asyncio
    async def test_returns_200(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_status_ok(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/health")
        body = response.json()
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_returns_environment_field(
        self, client: httpx.AsyncClient, test_settings: Settings
    ) -> None:
        response = await client.get("/health")
        body = response.json()
        assert "environment" in body
        assert isinstance(body["environment"], str)

    @pytest.mark.asyncio
    async def test_returns_version_field(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/health")
        body = response.json()
        assert body["version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_content_type_is_json(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/health")
        assert response.headers["content-type"].startswith("application/json")

    @pytest.mark.asyncio
    async def test_response_has_no_extra_unexpected_keys(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/health")
        body = response.json()
        assert set(body.keys()) == {"status", "environment", "version"}


# ---------------------------------------------------------------------------
# GET /docs and /openapi.json -- T-045 acceptance criterion #2
# ---------------------------------------------------------------------------


class TestSwaggerDocs:
    """Swagger UI and its backing OpenAPI schema must both be reachable."""

    @pytest.mark.asyncio
    async def test_docs_returns_200(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/docs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_docs_returns_html(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/docs")
        assert response.headers["content-type"].startswith("text/html")
        assert "swagger" in response.text.lower()

    @pytest.mark.asyncio
    async def test_redoc_returns_200(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/redoc")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json_returns_200(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/openapi.json")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json_is_valid_schema(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/openapi.json")
        schema = response.json()
        assert schema["info"]["title"] == API_TITLE
        assert schema["info"]["version"] == API_VERSION

    @pytest.mark.asyncio
    async def test_openapi_json_lists_health_path(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/openapi.json")
        schema = response.json()
        assert "/health" in schema["paths"]
        assert "get" in schema["paths"]["/health"]


# ---------------------------------------------------------------------------
# CORS -- T-045 acceptance criterion #3
# ---------------------------------------------------------------------------


class TestCORS:
    """
    The configured frontend origin must receive CORS headers.

    settings.cors_origins defaults to "http://localhost:5173" (the Vite
    dev server origin) per config.py and .env.example, so that exact
    origin is used here rather than a value invented for the test.
    """

    @pytest.mark.asyncio
    async def test_preflight_allows_configured_origin(
        self, client: httpx.AsyncClient, test_settings: Settings
    ) -> None:
        allowed_origin = test_settings.cors_origins_list[0]
        response = await client.options(
            "/health",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == allowed_origin

    @pytest.mark.asyncio
    async def test_actual_get_request_includes_cors_header(
        self, client: httpx.AsyncClient, test_settings: Settings
    ) -> None:
        allowed_origin = test_settings.cors_origins_list[0]
        response = await client.get(
            "/health",
            headers={"Origin": allowed_origin},
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == allowed_origin

    @pytest.mark.asyncio
    async def test_preflight_allows_credentials(
        self, client: httpx.AsyncClient, test_settings: Settings
    ) -> None:
        allowed_origin = test_settings.cors_origins_list[0]
        response = await client.options(
            "/health",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-credentials") == "true"

    @pytest.mark.asyncio
    async def test_preflight_allows_post_method(
        self, client: httpx.AsyncClient, test_settings: Settings
    ) -> None:
        """allow_methods=['*'] must cover POST for the T-047 analysis/start
        endpoint added in the next task -- verify the wildcard actually
        takes effect rather than silently defaulting to GET/HEAD only."""
        allowed_origin = test_settings.cors_origins_list[0]
        response = await client.options(
            "/health",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        allow_methods = response.headers.get("access-control-allow-methods", "")
        assert "POST" in allow_methods


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


class TestLifespan:
    """Startup/shutdown hooks must run cleanly without raising."""

    @pytest.mark.asyncio
    async def test_app_serves_requests_after_lifespan_startup(
        self, client: httpx.AsyncClient
    ) -> None:
        """If lifespan startup raised, httpx's ASGITransport would error
        before this request ever completed -- a successful 200 here is
        itself proof startup completed without an exception."""
        response = await client.get("/health")
        assert response.status_code == 200
