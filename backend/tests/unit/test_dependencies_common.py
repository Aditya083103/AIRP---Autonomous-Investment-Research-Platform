# backend/tests/unit/test_dependencies_common.py
"""
Unit tests for T-045: backend/dependencies/common.py

Verifies get_settings_dependency() resolves to the same cached Settings
instance backend.config.get_settings() returns, and that it can be
overridden through FastAPI's app.dependency_overrides mechanism exactly
as the docstring in common.py describes -- proving the override pattern
documented there actually works, not just that it reads nicely.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import Depends, FastAPI
import httpx
import pytest

from backend.config import Settings, get_settings
from backend.dependencies.common import get_settings_dependency


class TestGetSettingsDependency:
    """Direct, non-HTTP behaviour of the dependency callable."""

    def test_returns_settings_instance(self) -> None:
        result = get_settings_dependency()
        assert isinstance(result, Settings)

    def test_matches_cached_get_settings_singleton(self) -> None:
        """get_settings() is lru_cache'd -- the dependency must resolve to
        that exact same object, not a fresh, separately-constructed one."""
        assert get_settings_dependency() is get_settings()

    def test_repeated_calls_return_same_object(self) -> None:
        first = get_settings_dependency()
        second = get_settings_dependency()
        assert first is second


class TestDependencyOverridePattern:
    """The override pattern documented in common.py's own docstring."""

    @pytest.mark.asyncio
    async def test_override_replaces_resolved_settings_in_a_route(
        self, test_settings: Settings
    ) -> None:
        probe_app = FastAPI()

        @probe_app.get("/probe")
        async def probe(
            settings: Settings = Depends(get_settings_dependency),
        ) -> dict[str, str]:
            return {"environment": settings.environment}

        probe_app.dependency_overrides[get_settings_dependency] = lambda: test_settings

        # See test_main.py's client fixture docstring for why this cast is
        # needed: httpx's ASGITransport stub expects its own private
        # ASGIApp protocol, which FastAPI/Starlette's __call__ satisfies
        # structurally at runtime but not nominally under mypy --strict.
        transport = httpx.ASGITransport(app=cast(Any, probe_app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get("/probe")

        assert response.status_code == 200
        assert response.json()["environment"] == test_settings.environment
