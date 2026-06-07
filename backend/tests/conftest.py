# backend/tests/conftest.py
"""
Global pytest fixtures and configuration for the AIRP test suite.

Fixtures defined here are available to every test module automatically —
no import required. Add fixtures here only when they are genuinely shared
across multiple test files; module-specific fixtures belong in that module.

Fixture scopes used in AIRP:
  - function (default) : recreated for every test — safest, no state leak
  - session            : created once per pytest run — used for heavy setup
                         (DB engine, HTTP client) that is read-only in tests

Environment contract:
  All tests MUST run with ENVIRONMENT=test. This is enforced by the
  require_test_environment fixture (autouse=True) which blocks any test
  that forgets to set the variable.
"""
from __future__ import annotations

from collections.abc import Generator
import os
from typing import Any

import pytest

from backend.config import Settings

# ── Environment Guard ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def require_test_environment() -> Generator[None, None, None]:
    """
    Block test execution if ENVIRONMENT is not set to 'test'.

    The CI workflow sets ENVIRONMENT=test automatically.
    Local runs must set it in the shell or a .env.test file:

        export ENVIRONMENT=test
        python -m pytest

    This guard prevents tests from ever touching the development or
    production database when DATABASE_URL is accidentally not overridden.
    """
    # Normalize before comparing: a trailing space or stray casing — the
    # classic Windows `set ENVIRONMENT=test ` artefact — must not trip the
    # guard. strip().lower() keeps the "you must opt into test mode" contract
    # while tolerating shell whitespace.
    raw = os.getenv("ENVIRONMENT", "")
    if raw.strip().lower() != "test":
        pytest.fail(
            f"Tests must run with ENVIRONMENT=test (got '{raw}'). "
            "Set it in your shell before running pytest:\n"
            "  export ENVIRONMENT=test       (mac/linux)\n"
            '  set "ENVIRONMENT=test"        (windows cmd)'
        )
    yield


# ── Settings Fixture ──────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """
    Return a Settings instance pre-configured for the test environment.

    Uses model_construct() to bypass .env file loading — tests must be
    fully self-contained and must not depend on a local .env file existing.

    Scope is 'session' because Settings is read-only; sharing one instance
    across all tests is safe and avoids redundant construction overhead.

    Usage:
        def test_something(test_settings: Settings) -> None:
            assert test_settings.environment == "test"
    """
    result = Settings.model_construct(
        environment="test",
        log_level="DEBUG",
        # LLM — Groq by default in dev; tests mock the actual calls
        llm_provider="groq",
        groq_api_key="gsk_test-groq-key-for-unit-tests",
        groq_model="llama3-70b-8192",
        anthropic_api_key="sk-ant-test-key-for-unit-tests",
        anthropic_model="claude-haiku-4-5-20251001",
        anthropic_max_tokens=4096,
        # LangSmith — tracing disabled in tests (no real traces emitted)
        langsmith_api_key="",
        langchain_tracing_v2="false",
        langchain_project="airp-test",
        langchain_endpoint="https://api.smith.langchain.com",
        # Database — always point to the test database in tests
        database_url="postgresql+asyncpg://airp:airp@localhost:5432/airp",
        database_test_url="postgresql+asyncpg://airp:airp@localhost:5432/airp_test",
        db_pool_size=2,
        db_max_overflow=2,
        # Cache — tests use a local Redis; external calls are mocked
        redis_url="redis://localhost:6379",
        redis_token="",
        cache_ttl_stock=900,
        cache_ttl_news=3600,
        cache_ttl_macro=86400,
        cache_ttl_fundamentals=3600,
        # Vector store
        chroma_host="localhost",
        chroma_port=8001,
        chroma_collection="airp_test_documents",
        embedding_model="all-MiniLM-L6-v2",
        # Auth — not validated in unit tests
        clerk_secret_key="sk_test_placeholder",
        clerk_publishable_key="pk_test_placeholder",
        clerk_jwt_issuer="https://test.clerk.accounts.dev",
        secret_key="a" * 32,  # minimum 32 chars required by Field validator
        access_token_expire_minutes=60,
        # External data APIs — mocked in unit tests
        news_api_key="test-news-api-key",
        alpha_vantage_key="test-alpha-vantage-key",
        screener_base_url="https://www.screener.in",
        rbi_base_url="https://www.rbi.org.in",
        # CORS
        cors_origins="http://localhost:5173",
        # Feature flags
        feature_debate_enabled=True,
        debate_rounds=2,
        feature_pdf_enabled=True,
        feature_rate_limiting=False,  # disabled in tests — no throttling
        max_concurrent_analyses=3,
    )
    assert isinstance(result, Settings)
    return result


# ── Environment Variable Helpers ──────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """
    Ensure a clean environment for tests that inspect os.environ directly.

    Strips variables that could leak from the developer's shell into tests,
    then restores the original environment after the test completes.
    Monkeypatch handles rollback automatically.

    Usage:
        def test_reads_env_var(clean_env: None, monkeypatch: ...) -> None:
            monkeypatch.setenv("MY_VAR", "value")
            assert os.getenv("MY_VAR") == "value"
    """
    sensitive_vars: list[str] = [
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "LANGSMITH_API_KEY",
        "NEWS_API_KEY",
        "ALPHA_VANTAGE_KEY",
        "DATABASE_URL",
        "REDIS_URL",
    ]
    for var in sensitive_vars:
        monkeypatch.delenv(var, raising=False)
    yield


# ── Shared Test Data Builders ─────────────────────────────────────────────────
# These factories are used by multiple test modules.
# Domain-specific builders (e.g., mock agent outputs) live in the module
# that tests that agent, not here.


@pytest.fixture
def sample_ticker() -> str:
    """Return a canonical test ticker used across data layer tests."""
    return "TCS.NS"


@pytest.fixture
def sample_company_name() -> str:
    """Return a canonical test company name used across data layer tests."""
    return "Tata Consultancy Services"


@pytest.fixture
def sample_analysis_metadata() -> dict[str, Any]:
    """
    Return a minimal analysis metadata dict that matches the shape
    expected by the LangGraph InvestmentState initialiser (Phase 3).
    """
    return {
        "company_name": "Tata Consultancy Services",
        "ticker": "TCS.NS",
        "exchange": "NSE",
        "job_id": "test-job-uuid-001",
        "requested_at": "2024-01-15T10:00:00Z",
    }
