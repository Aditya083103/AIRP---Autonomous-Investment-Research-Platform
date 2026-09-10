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
from backend.tools.market_data import reset_shared_ticker_cache

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


@pytest.fixture(autouse=True)
def _reset_shared_ticker_cache() -> Generator[None, None, None]:
    """
    Clear the shared yf.Ticker cache (backend.tools.market_data) before
    and after every test.

    Without this, a test that patches ``backend.tools.market_data.yf.Ticker``
    with one mock could receive a *different* test's cached instance for
    the same ticker symbol (e.g. "TCS.NS" is reused across dozens of
    stock_price/financials/ratios tests), silently exercising the wrong
    mock. Autouse + function scope keeps every test's yfinance mocking
    fully isolated regardless of which module it lives in.
    """
    reset_shared_ticker_cache()
    yield
    reset_shared_ticker_cache()


@pytest.fixture(autouse=True)
def _reset_in_flight_analyses_counter() -> Generator[None, None, None]:
    """
    Reset backend.services.analysis's module-level concurrency counter
    (T-074 audit findings C9/F9) before and after every test.

    Without this, any test that calls POST /api/v1/analysis/start (real or
    via TestClient) reserves a slot via reserve_analysis_slot() -- and if
    that test mocks out run_analysis_pipeline entirely (common in router
    tests asserting it was scheduled with the right args), the matching
    release_analysis_slot() call inside the real run_analysis_pipeline
    never fires. The counter would then silently accumulate across every
    test in the whole suite until settings.max_concurrent_analyses is
    permanently exceeded, turning every later /start call into a 503
    regardless of what that test is actually about.
    """
    import backend.services.analysis as analysis_module

    analysis_module._in_flight_analyses = 0
    yield
    analysis_module._in_flight_analyses = 0


@pytest.fixture(autouse=True)
def _reset_redis_client_state() -> Generator[None, None, None]:
    """
    Reset backend.db.redis_client's module-level connection state
    (Section C audit finding, unit 9) before and after every test.

    backend.db.redis_client._FORCE_DISABLE is computed exactly once, at
    the module's raw Python import time, as `_is_test_environment()` --
    which reads os.getenv("ENVIRONMENT"). Whichever backend test file
    happens to be the FIRST in the whole pytest process to transitively
    import backend.db.redis_client (a near-universal dependency, pulled
    in via backend.config/backend.main/most agents and tools) freezes
    that value for the rest of the process. Every test file in this repo
    sets ENVIRONMENT=test itself via `os.environ.setdefault(...)` at its
    own module top, but import order during collection means that
    setdefault call is not guaranteed to have already run in some OTHER,
    earlier-collected file by the time that file's own import chain first
    pulls in redis_client -- if it hasn't, _FORCE_DISABLE freezes as
    False (the real-process default), and get_redis_client() then
    attempts (and, in this environment, succeeds at) a REAL connection to
    whatever REDIS_URL happens to be configured, memoising that live
    client at module level for the rest of the process. Every later test
    that calls get_client()/cache_get_json()/cache_set_json() -- directly
    or via the @cached decorator inside backend.tools.* fetch functions --
    then silently talks to a real Redis server instead of the hermetic
    None the "under test env" contract promises, until something calls
    reset_redis_client() (test_redis_client.py's own local autouse
    fixture does, but only protects tests within that one file, which
    happens to collect alphabetically after test_cache.py/
    test_financials.py/test_news.py -- exactly the three files this bug
    was observed breaking).

    reset_redis_client() already recomputes _FORCE_DISABLE from
    _is_test_environment() fresh rather than reusing the frozen value --
    calling it here, in a global autouse fixture that runs after
    collection has fully finished (by which point every test file's own
    os.environ.setdefault("ENVIRONMENT", "test") has unconditionally
    already run), guarantees the correct value regardless of which file
    happened to import redis_client first during collection. Mirrors
    _reset_shared_ticker_cache's and
    _reset_in_flight_analyses_counter's identical rationale for their own
    module-level singletons above.
    """
    from backend.db.redis_client import reset_redis_client

    reset_redis_client()
    yield
    reset_redis_client()


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
        groq_model="llama-3.3-70b-versatile",
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
        secret_key="a" * 32,  # minimum 32 chars required by Field validator
        access_token_expire_minutes=60,
        accuracy_service_token="test-accuracy-service-token",
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
        max_upload_size_mb=20,
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
