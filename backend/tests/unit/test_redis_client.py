# backend/tests/unit/test_redis_client.py
"""
Unit tests for backend/db/redis_client.py — T-018

Tests verify:
  1. Default state (_FORCE_DISABLE=True) → get_redis_client() returns None
  2. TTL constants are correct values
  3. enable_for_tests() / reset_redis_client() cycle works correctly
  4. No REDIS_URL → returns None and latches _client_unavailable
  5. Unreachable server (PING fails) → returns None and latches flag
  6. Happy path: valid URL + passing PING → returns a client
  7. Token (Upstash password) is forwarded to the client constructor

Patching strategy
-----------------
redis_client.py uses ``_FORCE_DISABLE = True`` as the single runtime guard.
Tests that need to exercise the connection path call ``enable_for_tests()``
which sets _FORCE_DISABLE = False.  ``reset_redis_client()`` (called via
the ``reset_redis_state`` autouse fixture) always restores _FORCE_DISABLE=True
after every test — whether the test is a bare function or a class method.

Why autouse fixture instead of teardown_function:
    ``teardown_function`` only runs after bare module-level test functions.
    It is NOT called after test methods inside classes (TestHappyPath, etc.).
    An autouse fixture with ``yield`` runs its teardown after every test
    regardless of whether it is a bare function or a class method.

redis.Redis.from_url is intercepted with:
    patch.object(redis_lib.Redis, "from_url", return_value=fake_client)

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_redis_client.py -v
"""
from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from contextlib import contextmanager  # noqa: E402
from typing import Generator  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
import redis as redis_lib  # noqa: E402

import backend.db.redis_client as rc_mod  # noqa: E402
from backend.db.redis_client import (  # noqa: E402
    MACRO_TTL,
    NEWS_TTL,
    RATIOS_TTL,
    STOCK_TTL,
    enable_for_tests,
    get_redis_client,
    reset_redis_client,
)

# ---------------------------------------------------------------------------
# Autouse fixture — resets module state before AND after every test,
# whether the test is a bare function or a method inside a class.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_redis_state() -> Generator[None, None, None]:
    """
    Reset redis_client module state before and after every test.

    Using autouse=True on a fixture (rather than teardown_function) ensures
    the reset runs for:
      * bare module-level test functions  (teardown_function also works)
      * methods inside test classes       (teardown_function does NOT work)

    The reset before yield guarantees a clean slate even if a previous
    test crashed before its own teardown ran.
    """
    reset_redis_client()  # clean slate before the test
    yield
    reset_redis_client()  # restore _FORCE_DISABLE=True after the test


# ---------------------------------------------------------------------------
# Context manager helper
# ---------------------------------------------------------------------------


@contextmanager
def _patch_connection(
    fake_client: MagicMock,
) -> Generator[MagicMock, None, None]:
    """
    Enable the connection path and intercept redis.Redis.from_url.

    Calls enable_for_tests() to set _FORCE_DISABLE=False, then patches
    redis.Redis.from_url to return fake_client.  Yields the mock so
    callers can inspect call_args / call_count.
    """
    enable_for_tests()
    with patch.object(
        redis_lib.Redis,
        "from_url",
        return_value=fake_client,
    ) as mock_from_url:
        yield mock_from_url


# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------


class TestTTLConstants:
    # Values raised from the original dev defaults (15 min / 1 h / 1 h / 24 h)
    # to protect free-tier API quotas under public demo traffic. See the TTL
    # block in backend/db/redis_client.py for the rationale.
    def test_stock_ttl_is_6_hours(self) -> None:
        assert STOCK_TTL == 21_600

    def test_news_ttl_is_12_hours(self) -> None:
        assert NEWS_TTL == 43_200

    def test_ratios_ttl_is_24_hours(self) -> None:
        assert RATIOS_TTL == 86_400

    def test_macro_ttl_is_7_days(self) -> None:
        assert MACRO_TTL == 604_800


# ---------------------------------------------------------------------------
# Default state — _FORCE_DISABLE=True → always returns None
# ---------------------------------------------------------------------------


class TestDefaultNoOp:
    def test_get_client_returns_none_by_default(self) -> None:
        assert get_redis_client() is None

    def test_get_client_none_even_with_url_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        assert get_redis_client() is None

    def test_unavailable_flag_not_latched_in_disabled_state(self) -> None:
        get_redis_client()
        assert rc_mod._client_unavailable is False

    def test_force_disable_true_by_default(self) -> None:
        assert rc_mod._FORCE_DISABLE is True


# ---------------------------------------------------------------------------
# enable_for_tests / reset cycle
# ---------------------------------------------------------------------------


class TestEnableDisableCycle:
    def test_enable_clears_force_disable(self) -> None:
        enable_for_tests()
        assert rc_mod._FORCE_DISABLE is False

    def test_reset_restores_force_disable(self) -> None:
        enable_for_tests()
        reset_redis_client()
        assert rc_mod._FORCE_DISABLE is True

    def test_reset_clears_client(self) -> None:
        rc_mod._client = MagicMock()
        reset_redis_client()
        assert rc_mod._client is None

    def test_reset_clears_unavailable_flag(self) -> None:
        rc_mod._client_unavailable = True
        reset_redis_client()
        assert rc_mod._client_unavailable is False


# ---------------------------------------------------------------------------
# No REDIS_URL configured
# ---------------------------------------------------------------------------


class TestNoRedisUrl:
    def test_returns_none_when_no_url_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        enable_for_tests()
        with patch.object(rc_mod, "settings", None):
            result = get_redis_client()
        assert result is None

    def test_latches_unavailable_when_no_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        enable_for_tests()
        with patch.object(rc_mod, "settings", None):
            get_redis_client()
        assert rc_mod._client_unavailable is True


# ---------------------------------------------------------------------------
# Unreachable server (PING fails)
# ---------------------------------------------------------------------------


class TestUnreachableServer:
    def test_returns_none_when_ping_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://unreachable:6379")
        fake_client = MagicMock()
        fake_client.ping.side_effect = ConnectionError("ECONNREFUSED")

        with _patch_connection(fake_client):
            result = get_redis_client()

        assert result is None

    def test_latches_unavailable_when_ping_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://unreachable:6379")
        fake_client = MagicMock()
        fake_client.ping.side_effect = ConnectionError("ECONNREFUSED")

        with _patch_connection(fake_client):
            get_redis_client()

        assert rc_mod._client_unavailable is True

    def test_does_not_retry_after_latch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Once _client_unavailable is True, get_redis_client() is a no-op."""
        monkeypatch.setenv("REDIS_URL", "redis://unreachable:6379")
        fake_client = MagicMock()
        fake_client.ping.side_effect = ConnectionError("ECONNREFUSED")

        with _patch_connection(fake_client) as mock_from_url:
            get_redis_client()  # first call — latches _client_unavailable
            get_redis_client()  # second call — fast no-op
            get_redis_client()  # third call — fast no-op

        assert mock_from_url.call_count == 1


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_client_when_ping_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with _patch_connection(fake_client):
            result = get_redis_client()

        assert result is fake_client

    def test_client_is_memoised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with _patch_connection(fake_client) as mock_from_url:
            first = get_redis_client()
            second = get_redis_client()

        assert first is second
        assert mock_from_url.call_count == 1

    def test_decode_responses_is_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with _patch_connection(fake_client) as mock_from_url:
            get_redis_client()

        _, kwargs = mock_from_url.call_args
        assert kwargs.get("decode_responses") is True


# ---------------------------------------------------------------------------
# Upstash token forwarded as password
# ---------------------------------------------------------------------------


class TestUpstashToken:
    def test_token_forwarded_as_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "rediss://my-upstash.io:6380")
        monkeypatch.setenv("REDIS_TOKEN", "AXXXxxtoken")
        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with _patch_connection(fake_client) as mock_from_url:
            get_redis_client()

        _, kwargs = mock_from_url.call_args
        assert kwargs.get("password") == "AXXXxxtoken"

    def test_no_password_kwarg_when_no_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        monkeypatch.delenv("REDIS_TOKEN", raising=False)
        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with patch.object(rc_mod, "settings", None):
            with _patch_connection(fake_client) as mock_from_url:
                get_redis_client()

        _, kwargs = mock_from_url.call_args
        assert "password" not in kwargs


# ---------------------------------------------------------------------------
# reset_redis_client
# ---------------------------------------------------------------------------


class TestResetRedisClient:
    def test_reset_clears_client(self) -> None:
        rc_mod._client = MagicMock()
        reset_redis_client()
        assert rc_mod._client is None

    def test_reset_clears_unavailable_flag(self) -> None:
        rc_mod._client_unavailable = True
        reset_redis_client()
        assert rc_mod._client_unavailable is False


# ---------------------------------------------------------------------------
# Cross-file pollution recovery (Section C audit finding, unit 9)
# ---------------------------------------------------------------------------
#
# _FORCE_DISABLE (module docstring above) is computed exactly once, at
# backend.db.redis_client's raw Python import time, from
# _is_test_environment(). Whichever backend test file happens to be the
# FIRST in the whole pytest process to transitively import this module
# (it is pulled in by nearly everything, via backend.config/backend.main/
# most agents and tools) freezes that value for the rest of the process.
# If that import happens before ENVIRONMENT=test is actually set in the
# raw OS environment (every test file sets it via its own
# `os.environ.setdefault(...)`, but pytest's collection order does not
# guarantee any particular file's setdefault call has already run before
# some OTHER file's import chain first reaches this module), _FORCE_DISABLE
# freezes as False -- the real-process default -- and get_redis_client()
# then attempts, and in an environment with a real REDIS_URL configured
# actually succeeds at, a genuine connection. That live client gets
# memoised at module level and leaks into every subsequent test in the
# process that touches caching (directly, or via the @cached decorator
# inside backend.tools.* fetch functions), silently replacing the
# "always None under test env" contract with a real network call --
# exactly what broke test_cache.py's TestTestEnvironmentNoOp /
# TestCachedDecoratorTestEnv and several test_financials.py/test_news.py
# error-path assertions the first time `pytest backend/tests/unit/` ever
# completed collection (previously blocked entirely by the unrelated
# ChromaDB singleton bug fixed alongside this one).
#
# test_redis_client.py's own reset_redis_state autouse fixture (above)
# only protects tests within THIS file; it collects alphabetically after
# test_cache.py/test_financials.py/test_news.py, so it could never have
# caught this. The real fix is backend/tests/conftest.py's new
# _reset_redis_client_state autouse fixture, which calls
# reset_redis_client() before and after EVERY test in the entire suite --
# by which point every file's own os.environ.setdefault has unconditionally
# already run during collection, so _is_test_environment() is always
# correct regardless of import order. This test proves the recovery
# mechanism itself: reset_redis_client() restores hermetic test defaults
# no matter how badly the module's state was polluted beforehand.
# ---------------------------------------------------------------------------


class TestResetRecoversFromCrossFilePollution:
    def test_reset_recovers_even_from_a_live_looking_memoised_client(self) -> None:
        # Simulate the worst-case state an import-order race could freeze
        # at process start: _FORCE_DISABLE latched False (as if this module
        # was first imported before any test file's own
        # os.environ.setdefault("ENVIRONMENT", "test") had run) with a
        # real-looking client already memoised -- exactly what a live
        # Upstash connection succeeding under this bug would leave behind.
        rc_mod._FORCE_DISABLE = False
        rc_mod._client = MagicMock(name="leaked-live-redis-client")
        rc_mod._client_unavailable = False

        reset_redis_client()

        assert rc_mod._FORCE_DISABLE is True
        assert rc_mod._client is None
        assert get_redis_client() is None


# ---------------------------------------------------------------------------
# _is_test_environment() -- the function _FORCE_DISABLE's default is now
# bound to (see redis_client.py's docstring on _FORCE_DISABLE for the bug
# this fixes: it used to be a hardcoded `True`, so real uvicorn runs -- which
# never call enable_for_tests() -- had caching permanently disabled, not
# just the test suite). This class only exercises the pure helper directly;
# deliberately not reloading the module mid-suite to prove the module-level
# default, since that would leave every other test's directly-imported
# names (get_redis_client, enable_for_tests, ...) pointing at stale
# pre-reload function objects.
# ---------------------------------------------------------------------------


class TestIsTestEnvironment:
    def test_true_when_environment_is_test(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "test")
        assert rc_mod._is_test_environment() is True

    def test_true_regardless_of_case(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "TEST")
        assert rc_mod._is_test_environment() is True

    def test_false_when_environment_is_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert rc_mod._is_test_environment() is False

    def test_false_when_environment_is_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert rc_mod._is_test_environment() is False
