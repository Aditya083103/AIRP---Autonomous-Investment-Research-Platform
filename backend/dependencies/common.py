# backend/dependencies/common.py
"""
AIRP -- Shared FastAPI Dependencies (T-045)

Small, reusable ``Depends()`` callables that don't belong to a single
router. Currently holds only the settings dependency; grows as later
tasks (T-046 auth, T-047 analysis) need shared request-scoped helpers.
"""

from backend.config import Settings, get_settings

__all__ = ["get_settings_dependency"]


def get_settings_dependency() -> Settings:
    """
    FastAPI dependency that resolves to the cached ``Settings`` singleton.

    Thin wrapper around ``backend.config.get_settings`` so routers depend
    on something importable from ``backend.dependencies`` -- the package
    routers are expected to pull shared dependencies from -- rather than
    reaching into ``backend.config`` directly in every route signature.
    Tests override this exact callable via:

        app.dependency_overrides[get_settings_dependency] = lambda: test_settings

    Usage:
        from fastapi import Depends
        from backend.dependencies.common import get_settings_dependency
        from backend.config import Settings

        @router.get("/example")
        async def example(
            settings: Settings = Depends(get_settings_dependency),
        ) -> dict[str, str]:
            return {"environment": settings.environment}
    """
    return get_settings()
