# backend/tests/unit/test_redis_client.py
"""
Unit tests for backend/db/redis_client.py — T-018

Tests verify:
  1. ENVIRONMENT=test → get_redis_client() always returns None (hermetic)
  2. TTL constants are correct values
  3. reset_redis_client() clears memoised state
  4. No REDIS_URL → returns None and latches _client_unavailable
  5. Unreachable server (PING fails) → returns None and latches flag
  6. Happy path: valid URL + passing PING → returns a client
  7. Token (Upstash password) is forwarded to the client constructor

Patching strategy
-----------------
redis_client.py exposes a module-level ``_FORCE_DISABLE`` flag (True by
default) and an ``enable_for_tests()`` helper.  Tests that need to exercise
the real connection path call ``enable_for_tests()`` before calling
``get_redis_client()``.  ``reset_redis_client()`` (called in teardown)
always resets ``_FORCE_DISABLE`` back to True.

redis.Redis.from_url is intercepted with:
    patch.object(redis_lib.Redis, "from_url", return_value=fake_client)

No env-var manipulation is needed at all.

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


@contextmanager
def _patch_connection(
    fake_client: MagicMock,
) -> Generator[MagicMock, None, None]:
    """
    Enable the connection path and intercept redis.Redis.from_url.

    Calls enable_for_tests() to clear _FORCE_DISABLE, then patches
    redis.Redis.from_url to return fake_client.  Yields the mock so
    callers can inspect call_args / call_count.

    teardown_function() resets _FORCE_DISABLE back to True after every test.
    """
    enable_for_tests()
    with patch.object(
        redis_lib.Redis,
        "from_url",
        return_value=fake_client,
    ) as mock_from_url:
        yield mock_from_url


def teardown_function() -> None:
    """Reset all memoised state between tests."""
    reset_redis_client()  # also resets _FORCE_DISABLE to True


# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------


class TestTTLConstants:
    def test_stock_ttl_is_15_minutes(self) -> None:
        assert STOCK_TTL == 900

    def test_news_ttl_is_1_hour(self) -> None:
        assert NEWS_TTL == 3_600

    def test_ratios_ttl_is_1_hour(self) -> None:
        assert RATIOS_TTL == 3_600

    def test_macro_ttl_is_24_hours(self) -> None:
        assert MACRO_TTL == 86_400


# ---------------------------------------------------------------------------
# Default state — always returns None (both guards active)
# ---------------------------------------------------------------------------


class TestDefaultNoOp:
    def test_get_client_returns_none_by_default(self) -> None:
        """_FORCE_DISABLE=True by default → always returns None."""
        assert get_redis_client() is None

    def test_get_client_none_even_with_url_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        assert get_redis_client() is None

    def test_unavailable_flag_not_latched_in_disabled_state(self) -> None:
        """_FORCE_DISABLE path must NOT latch _client_unavailable — that flag
        is reserved for genuine connection failures."""
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
            get_redis_client()  # first call — latches flag
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
        """Second call returns the same object without reconnecting."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        fake_client = MagicMock()
        fake_client.ping.return_value = True

        with _patch_connection(fake_client) as mock_from_url:
            first = get_redis_client()
            second = get_redis_client()

        assert first is second
        assert mock_from_url.call_count == 1

    def test_decode_responses_is_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """decode_responses=True must be set so GET returns str, not bytes."""
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
