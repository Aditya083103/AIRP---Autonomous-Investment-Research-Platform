# backend/tests/unit/test_health_router.py
"""
Unit tests for T-045: backend/routers/health.py

Tests the health router's contents directly (the APIRouter object, the
HealthResponse schema, and the handler function) -- independent of the
app-level wiring already covered in test_main.py::TestHealthEndpoint.
This separation mirrors the AIRP pattern of testing a module's own
contract in its own file (see test_pdf_export.py / test_main.py split):
test_main.py proves the route is reachable end-to-end through the real
app; this file proves the router module itself is correctly shaped.
"""

from __future__ import annotations

import pytest

from backend.config import Settings
from backend.routers.health import HealthResponse, health_check, router


class TestHealthRouterObject:
    """The APIRouter instance itself."""

    def test_router_has_health_tag(self) -> None:
        assert router.tags == ["health"]

    def test_router_registers_health_path(self) -> None:
        paths = {route.path for route in router.routes}  # type: ignore[attr-defined]
        assert "/health" in paths

    def test_health_path_uses_get_method(self) -> None:
        all_routes = router.routes
        health_route = None
        for route in all_routes:
            if route.path == "/health":  # type: ignore[attr-defined]
                health_route = route
                break
        assert health_route is not None
        assert "GET" in health_route.methods  # type: ignore[attr-defined]


class TestHealthResponseModel:
    """The Pydantic schema backing the response."""

    def test_accepts_valid_payload(self) -> None:
        model = HealthResponse(status="ok", environment="test", version="0.1.0")
        assert model.status == "ok"
        assert model.environment == "test"
        assert model.version == "0.1.0"

    def test_status_field_rejects_non_ok_value(self) -> None:
        with pytest.raises(ValueError):
            HealthResponse(
                status="degraded",
                environment="test",
                version="0.1.0",
            )

    def test_serialises_to_dict_with_exact_three_keys(self) -> None:
        model = HealthResponse(status="ok", environment="test", version="0.1.0")
        dumped = model.model_dump()
        assert set(dumped.keys()) == {"status", "environment", "version"}


class TestHealthCheckHandler:
    """The async handler function, called directly (no HTTP layer)."""

    @pytest.mark.asyncio
    async def test_returns_health_response_instance(self) -> None:
        result = await health_check()
        assert isinstance(result, HealthResponse)

    @pytest.mark.asyncio
    async def test_status_is_always_ok(self) -> None:
        result = await health_check()
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_environment_reflects_active_settings(
        self, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """health_check() reads the module-level `settings` singleton from
        backend.config -- patch that exact import target so this test
        reflects a real environment value rather than whatever happens
        to be active in the process running the suite."""
        monkeypatch.setattr(
            "backend.routers.health.settings", test_settings, raising=True
        )
        result = await health_check()
        assert result.environment == test_settings.environment
