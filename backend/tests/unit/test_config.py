# backend/tests/unit/test_config.py
"""
Unit tests for backend/config.py.

Tests validate that:
- Settings loads correctly from environment variables
- Computed properties return correct values
- active_database_url switches based on ENVIRONMENT
- cors_origins_list parses comma-separated string correctly
- tracing_enabled reflects key presence and flag state
"""
from __future__ import annotations

import os
from typing import Any

from pydantic import ValidationError
import pytest

from backend.config import Settings


def make_settings(**overrides: Any) -> Settings:
    """
    Helper — build a Settings instance with test defaults.

    Bypasses .env file by passing values directly. Any field can be
    overridden via keyword arguments.

    The **overrides type is Any (not str) because Settings fields have
    mixed types: str, int, bool, Literal[...]. Passing str-only dict
    causes mypy arg-type errors with model_construct in strict mode.
    """
    defaults: dict[str, Any] = {
        "environment": "test",
        "anthropic_api_key": "sk-ant-test-key",
        "database_url": "postgresql+asyncpg://airp:airp@localhost:5432/airp",
        "database_test_url": "postgresql+asyncpg://airp:airp@localhost:5432/airp_test",
    }
    defaults.update(overrides)
    result = Settings.model_construct(**defaults)
    assert isinstance(result, Settings)
    return result


def test_settings_loads_required_fields() -> None:
    """Settings initialises without error when required fields are provided."""
    s = make_settings()
    assert s.anthropic_api_key == "sk-ant-test-key"
    assert s.environment == "test"


def test_active_database_url_returns_test_url_in_test_env() -> None:
    """active_database_url returns the test DB URL when environment is test."""
    s = make_settings(environment="test")
    assert s.active_database_url == s.database_test_url
    assert "airp_test" in s.active_database_url


def test_active_database_url_returns_primary_url_in_dev() -> None:
    """active_database_url returns the primary DB URL in non-test environments."""
    s = make_settings(environment="development")
    assert s.active_database_url == s.database_url


def test_cors_origins_list_parses_single_origin() -> None:
    """Single CORS origin is returned as a one-item list."""
    s = make_settings(cors_origins="http://localhost:5173")
    assert s.cors_origins_list == ["http://localhost:5173"]


def test_cors_origins_list_parses_multiple_origins() -> None:
    """Multiple comma-separated CORS origins are split and stripped correctly."""
    s = make_settings(cors_origins="http://localhost:5173,https://airp.vercel.app")
    assert s.cors_origins_list == [
        "http://localhost:5173",
        "https://airp.vercel.app",
    ]


def test_is_production_false_in_development() -> None:
    """is_production is False for development environment."""
    s = make_settings(environment="development")
    assert s.is_production is False


def test_is_production_true_in_production() -> None:
    """is_production is True only for production environment."""
    s = make_settings(environment="production")
    assert s.is_production is True


def test_tracing_enabled_false_when_no_key() -> None:
    """tracing_enabled is False when langsmith_api_key is empty."""
    s = make_settings(langsmith_api_key="")
    assert s.tracing_enabled is False


def test_tracing_enabled_false_when_flag_off() -> None:
    """tracing_enabled is False when tracing flag is disabled, even with key."""
    s = make_settings(langsmith_api_key="ls__somekey", langchain_tracing_v2="false")
    assert s.tracing_enabled is False


def test_tracing_enabled_true_when_key_and_flag() -> None:
    """tracing_enabled is True when both key and flag are set."""
    s = make_settings(langsmith_api_key="ls__somekey", langchain_tracing_v2="true")
    assert s.tracing_enabled is True


def test_debate_rounds_default() -> None:
    """Default debate rounds is 2."""
    s = make_settings()
    assert s.debate_rounds == 2


def test_feature_flags_default_true() -> None:
    """Feature flags default to enabled."""
    s = make_settings()
    assert s.feature_debate_enabled is True
    assert s.feature_pdf_enabled is True
    assert s.feature_rate_limiting is True


def test_rate_limit_requests_per_minute_default() -> None:
    """T-074 audit findings C9/F9: rate_limit_requests_per_minute has a
    sane default now that feature_rate_limiting is actually enforced."""
    s = make_settings()
    assert s.rate_limit_requests_per_minute == 60


def test_max_concurrent_analyses_default() -> None:
    s = make_settings()
    assert s.max_concurrent_analyses == 3


def test_clerk_fields_removed() -> None:
    """T-074 audit findings C9/F9: clerk_secret_key / clerk_publishable_key
    / clerk_jwt_issuer were dead since the self-hosted auth migration and
    have been deleted outright, not just left unused."""
    s = make_settings()
    assert not hasattr(s, "clerk_secret_key")
    assert not hasattr(s, "clerk_publishable_key")
    assert not hasattr(s, "clerk_jwt_issuer")


def test_environment_accepts_valid_values() -> None:
    """All valid ENVIRONMENT values are accepted without error."""
    for env_value in ["development", "test", "staging", "production"]:
        s = make_settings(environment=env_value)
        assert s.environment == env_value


# ---------------------------------------------------------------------------
# feature_rag_enabled (T-074 audit findings C4/C5)
# ---------------------------------------------------------------------------
#
# make_settings() uses Settings.model_construct(), which -- unlike
# Settings(**overrides) -- skips validation entirely, so the
# _default_rag_off_in_production model_validator never runs. These tests
# go through the real Settings(**overrides) constructor instead so the
# validator (and model_fields_set tracking) actually fires, matching how
# the app is constructed for real via get_settings().


def _construct_settings(**overrides: Any) -> Settings:
    # _env_file=None isolates this from whatever real .env happens to
    # exist in the developer's working directory (e.g. a local SECRET_KEY
    # placeholder) -- without it, tests asserting a field's actual Python
    # default would silently assert against .env's value instead.
    #
    # That alone is NOT enough: pydantic-settings reads real OS
    # environment variables regardless of _env_file, at a priority
    # between the Python default and an explicit constructor kwarg. Any
    # field NOT present in `overrides` below (e.g. secret_key in
    # test_insecure_secret_key_allowed_outside_production, which is
    # deliberately testing the untouched default) silently picks up
    # whatever real SECRET_KEY happens to be exported in the calling
    # process's environment instead -- true on a Windows dev host with
    # no such var set, but false the moment these tests run inside the
    # backend Docker container or CI, both of which export a real
    # SECRET_KEY for the app's own runtime use. Popping every
    # Settings field's env var that isn't part of this call's overrides
    # (restored after, so no cross-test leakage in the other direction)
    # makes the constructed instance's un-overridden fields reflect the
    # actual Python defaults everywhere this helper runs, not just on
    # machines that happen to have a clean environment.
    defaults: dict[str, Any] = {
        "anthropic_api_key": "sk-ant-test-key",
        "database_url": "postgresql+asyncpg://airp:airp@localhost:5432/airp",
        "database_test_url": "postgresql+asyncpg://airp:airp@localhost:5432/airp_test",
    }
    defaults.update(overrides)

    env_keys_to_isolate = {
        field_name.upper()
        for field_name in Settings.model_fields
        if field_name not in defaults
    }
    saved_env = {
        key: os.environ.pop(key, None)
        for key in env_keys_to_isolate
        if key in os.environ
    }
    try:
        return Settings(_env_file=None, **defaults)
    finally:
        for key, value in saved_env.items():
            os.environ[key] = value


def test_feature_rag_enabled_defaults_true_outside_production() -> None:
    for env_value in ("development", "test", "staging"):
        s = _construct_settings(environment=env_value)
        assert s.feature_rag_enabled is True, env_value


def test_feature_rag_enabled_defaults_false_in_production() -> None:
    s = _construct_settings(environment="production", secret_key="x" * 32)
    assert s.feature_rag_enabled is False


def test_feature_rag_enabled_explicit_true_respected_in_production() -> None:
    """An operator explicitly setting FEATURE_RAG_ENABLED=true in production
    is respected, not silently overridden by the production default-off."""
    s = _construct_settings(
        environment="production", feature_rag_enabled=True, secret_key="x" * 32
    )
    assert s.feature_rag_enabled is True


def test_feature_rag_enabled_explicit_false_respected_outside_production() -> None:
    s = _construct_settings(environment="development", feature_rag_enabled=False)
    assert s.feature_rag_enabled is False


# ---------------------------------------------------------------------------
# secret_key production guard (T-074 audit finding C11)
# ---------------------------------------------------------------------------


def test_insecure_secret_key_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _construct_settings(environment="production")


def test_insecure_secret_key_allowed_outside_production() -> None:
    for env_value in ("development", "test", "staging"):
        s = _construct_settings(environment=env_value)
        assert s.secret_key == "insecure-default-change-in-production"


def test_real_secret_key_accepted_in_production() -> None:
    s = _construct_settings(environment="production", secret_key="x" * 32)
    assert s.secret_key == "x" * 32
