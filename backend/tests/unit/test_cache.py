# backend/tests/unit/test_cache.py
"""
Unit tests for backend/tools/cache.py — T-018

Tests cover:
  1. Low-level helpers (backward-compatible with T-014):
       cache_get_json / cache_set_json under test env → no-op
       cache_get_json / cache_set_json with injected fake client → happy path
       Corrupt / non-dict cached values → treated as miss
       Client errors on GET / SET → degrade gracefully (never raise)

  2. @cached decorator:
       Cache hit → returns cached dict, does NOT call wrapped function
       Cache miss → calls wrapped function, caches result, returns it
       Error result (has "error" key) → NOT cached
       Unresolvable key template → bypasses cache, calls function directly
       Test env → wrapped function is called normally (cache is a no-op)
       TTL is forwarded to cache_set_json correctly
       Decorator preserves __name__ and __doc__ (functools.wraps)

  3. TTL re-exports are correct values

  4. reset_client delegates to reset_redis_client

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_cache.py -v
"""
from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from datetime import datetime, timezone  # noqa: E402
import json  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from backend.tools.cache import (  # noqa: E402
    MACRO_TTL,
    NEWS_TTL,
    RATIOS_TTL,
    STOCK_TTL,
    cache_get_json,
    cache_set_json,
    cached,
    get_client,
    reset_client,
)


def teardown_function() -> None:
    """Reset memoised client state between tests."""
    reset_client()


# ---------------------------------------------------------------------------
# TTL re-exports
# ---------------------------------------------------------------------------


class TestTTLReExports:
    def test_stock_ttl(self) -> None:
        assert STOCK_TTL == 900

    def test_news_ttl(self) -> None:
        assert NEWS_TTL == 3_600

    def test_ratios_ttl(self) -> None:
        assert RATIOS_TTL == 3_600

    def test_macro_ttl(self) -> None:
        assert MACRO_TTL == 86_400


# ---------------------------------------------------------------------------
# Low-level helpers — test env no-op
# ---------------------------------------------------------------------------


class TestTestEnvironmentNoOp:
    def test_get_client_is_none_under_test_env(self) -> None:
        assert get_client() is None

    def test_cache_get_returns_none_under_test_env(self) -> None:
        assert cache_get_json("any:key") is None

    def test_cache_set_returns_false_under_test_env(self) -> None:
        assert cache_set_json("any:key", {"a": 1}, 60) is False


# ---------------------------------------------------------------------------
# Low-level helpers — with injected fake client
# ---------------------------------------------------------------------------


class TestWithFakeClient:
    """Bypass test-env guard by patching get_client with a fake Redis."""

    def test_get_round_trips_json(self) -> None:
        fake = MagicMock()
        fake.get.return_value = json.dumps({"repo_rate": 6.5})
        with patch("backend.tools.cache.get_client", return_value=fake):
            assert cache_get_json("k") == {"repo_rate": 6.5}

    def test_get_returns_none_on_miss(self) -> None:
        fake = MagicMock()
        fake.get.return_value = None
        with patch("backend.tools.cache.get_client", return_value=fake):
            assert cache_get_json("k") is None

    def test_get_returns_none_on_corrupt_value(self) -> None:
        fake = MagicMock()
        fake.get.return_value = "{not valid json"
        with patch("backend.tools.cache.get_client", return_value=fake):
            assert cache_get_json("k") is None

    def test_get_returns_none_on_non_dict_json(self) -> None:
        fake = MagicMock()
        fake.get.return_value = json.dumps([1, 2, 3])
        with patch("backend.tools.cache.get_client", return_value=fake):
            assert cache_get_json("k") is None

    def test_get_returns_none_on_client_error(self) -> None:
        fake = MagicMock()
        fake.get.side_effect = RuntimeError("connection dropped")
        with patch("backend.tools.cache.get_client", return_value=fake):
            assert cache_get_json("k") is None

    def test_set_returns_true_and_calls_set_with_ttl(self) -> None:
        fake = MagicMock()
        with patch("backend.tools.cache.get_client", return_value=fake):
            ok = cache_set_json("k", {"a": 1}, 86400)
        assert ok is True
        kwargs = fake.set.call_args.kwargs
        assert kwargs.get("ex") == 86400

    def test_set_returns_false_on_client_error(self) -> None:
        fake = MagicMock()
        fake.set.side_effect = RuntimeError("write failed")
        with patch("backend.tools.cache.get_client", return_value=fake):
            assert cache_set_json("k", {"a": 1}, 60) is False

    def test_set_serialises_non_native_types(self) -> None:
        fake = MagicMock()
        payload: dict[str, Any] = {"fetched_at": datetime.now(tz=timezone.utc)}
        with patch("backend.tools.cache.get_client", return_value=fake):
            ok = cache_set_json("k", payload, 60)
        assert ok is True

    def test_set_enforces_minimum_ttl_of_1(self) -> None:
        fake = MagicMock()
        with patch("backend.tools.cache.get_client", return_value=fake):
            cache_set_json("k", {"a": 1}, 0)
        kwargs = fake.set.call_args.kwargs
        assert kwargs.get("ex") >= 1


# ---------------------------------------------------------------------------
# @cached decorator — test environment behaviour
#
# Under ENVIRONMENT=test, get_client() returns None, so cache_get_json()
# and cache_set_json() are both no-ops. The @cached decorator still calls
# cache_get_json (it gets None back = miss) then calls the wrapped function.
# This is correct behaviour: the decorator is transparent in test env.
# ---------------------------------------------------------------------------


class TestCachedDecoratorTestEnv:
    def test_wrapped_function_is_called_normally(self) -> None:
        """Under test env the decorator is transparent — function runs normally."""
        call_count = 0

        @cached(key="airp:test:{ticker}", ttl=STOCK_TTL)
        def _fetch(ticker: str) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ticker": ticker, "price": 100.0}

        result = _fetch(ticker="TCS.NS")
        assert result == {"ticker": "TCS.NS", "price": 100.0}
        assert call_count == 1

    def test_result_is_not_cached_under_test_env(self) -> None:
        """In test env cache_set_json is a no-op — nothing is written."""

        @cached(key="airp:test:{ticker}", ttl=STOCK_TTL)
        def _fetch(ticker: str) -> dict[str, Any]:
            return {"ticker": ticker}

        with patch("backend.tools.cache.cache_set_json") as mock_set:
            _fetch(ticker="TCS.NS")

        # get_client() returns None in test env → cache_set_json is never
        # called with the real Redis, but the decorator still calls it.
        # The set call goes through but writes nothing (returns False).
        # We verify the decorator DID attempt the set (correct wiring),
        # and that the key was resolved correctly.
        mock_set.assert_called_once_with(
            "airp:test:TCS.NS", {"ticker": "TCS.NS"}, STOCK_TTL
        )


# ---------------------------------------------------------------------------
# @cached decorator — cache hit
# ---------------------------------------------------------------------------


class TestCachedDecoratorCacheHit:
    def test_returns_cached_value_without_calling_function(self) -> None:
        call_count = 0

        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch(ticker: str, period: str = "1y") -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ticker": ticker, "period": period, "price": 200.0}

        cached_data = {"ticker": "TCS.NS", "period": "1y", "price": 150.0}

        with patch("backend.tools.cache.cache_get_json", return_value=cached_data):
            result = _fetch(ticker="TCS.NS", period="1y")

        assert result == cached_data
        assert call_count == 0

    def test_cache_key_is_resolved_correctly(self) -> None:
        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch(ticker: str, period: str = "1y") -> dict[str, Any]:
            return {"ticker": ticker}

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None) as mock_get,
            patch("backend.tools.cache.cache_set_json"),
        ):
            _fetch(ticker="INFY.NS", period="3y")

        mock_get.assert_called_once_with("airp:stock:INFY.NS:3y")

    def test_key_resolved_from_positional_args(self) -> None:
        @cached(key="airp:ratios:{ticker}", ttl=RATIOS_TTL)
        def _fetch(ticker: str) -> dict[str, Any]:
            return {"ticker": ticker}

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None) as mock_get,
            patch("backend.tools.cache.cache_set_json"),
        ):
            _fetch("TCS.NS")  # positional — must still resolve

        mock_get.assert_called_once_with("airp:ratios:TCS.NS")


# ---------------------------------------------------------------------------
# @cached decorator — cache miss
# ---------------------------------------------------------------------------


class TestCachedDecoratorCacheMiss:
    def test_calls_wrapped_function_on_miss(self) -> None:
        call_count = 0

        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch(ticker: str, period: str = "1y") -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ticker": ticker, "price": 300.0}

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None),
            patch("backend.tools.cache.cache_set_json"),
        ):
            _fetch(ticker="TCS.NS", period="1y")

        assert call_count == 1

    def test_caches_result_with_correct_ttl(self) -> None:
        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch(ticker: str, period: str = "1y") -> dict[str, Any]:
            return {"ticker": ticker, "price": 300.0}

        expected = {"ticker": "TCS.NS", "price": 300.0}

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None),
            patch("backend.tools.cache.cache_set_json") as mock_set,
        ):
            _fetch(ticker="TCS.NS", period="1y")

        mock_set.assert_called_once_with("airp:stock:TCS.NS:1y", expected, STOCK_TTL)

    def test_returns_live_result_on_miss(self) -> None:
        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch(ticker: str, period: str = "1y") -> dict[str, Any]:
            return {"ticker": ticker, "price": 420.0}

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None),
            patch("backend.tools.cache.cache_set_json"),
        ):
            result = _fetch(ticker="TCS.NS", period="1y")

        assert result == {"ticker": "TCS.NS", "price": 420.0}


# ---------------------------------------------------------------------------
# @cached decorator — error result NOT cached
# ---------------------------------------------------------------------------


class TestCachedDecoratorErrorNotCached:
    def test_error_result_is_not_written_to_cache(self) -> None:
        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch(ticker: str, period: str = "1y") -> dict[str, Any]:
            return {
                "error": "ticker_not_found",
                "ticker": ticker,
                "message": "No data",
            }

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None),
            patch("backend.tools.cache.cache_set_json") as mock_set,
        ):
            _fetch(ticker="INVALID.NS", period="1y")

        mock_set.assert_not_called()

    def test_error_result_is_returned_to_caller(self) -> None:
        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch(ticker: str, period: str = "1y") -> dict[str, Any]:
            return {"error": "ticker_not_found", "ticker": ticker}

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None),
            patch("backend.tools.cache.cache_set_json"),
        ):
            result = _fetch(ticker="BAD.NS", period="1y")

        assert result["error"] == "ticker_not_found"


# ---------------------------------------------------------------------------
# @cached decorator — unresolvable key template
# ---------------------------------------------------------------------------


class TestCachedDecoratorBadKeyTemplate:
    def test_unresolvable_key_bypasses_cache(self) -> None:
        """A key template with an unknown placeholder calls the function."""
        call_count = 0

        @cached(key="airp:stock:{nonexistent_arg}", ttl=STOCK_TTL)
        def _fetch(ticker: str) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ticker": ticker}

        with (
            patch("backend.tools.cache.cache_get_json") as mock_get,
            patch("backend.tools.cache.cache_set_json") as mock_set,
        ):
            result = _fetch(ticker="TCS.NS")

        assert result == {"ticker": "TCS.NS"}
        assert call_count == 1
        mock_get.assert_not_called()
        mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# @cached decorator — TTL forwarding
# ---------------------------------------------------------------------------


class TestCachedDecoratorTTL:
    @pytest.mark.parametrize(
        "ttl_constant,expected_ttl",
        [
            (STOCK_TTL, 900),
            (NEWS_TTL, 3_600),
            (RATIOS_TTL, 3_600),
            (MACRO_TTL, 86_400),
        ],
    )
    def test_ttl_forwarded_correctly(
        self, ttl_constant: int, expected_ttl: int
    ) -> None:
        @cached(key="airp:test:{key}", ttl=ttl_constant)
        def _fetch(key: str) -> dict[str, Any]:
            return {"key": key}

        with (
            patch("backend.tools.cache.cache_get_json", return_value=None),
            patch("backend.tools.cache.cache_set_json") as mock_set,
        ):
            _fetch(key="x")

        _, _, forwarded_ttl = mock_set.call_args.args
        assert forwarded_ttl == expected_ttl


# ---------------------------------------------------------------------------
# @cached decorator — functools.wraps
# ---------------------------------------------------------------------------


class TestCachedDecoratorPreservesMetadata:
    def test_preserves_function_name(self) -> None:
        @cached(key="airp:test:{k}", ttl=STOCK_TTL)
        def _my_fetch_function(k: str) -> dict[str, Any]:
            return {}

        assert _my_fetch_function.__name__ == "_my_fetch_function"

    def test_preserves_docstring(self) -> None:
        @cached(key="airp:test:{k}", ttl=STOCK_TTL)
        def _documented_fetch(k: str) -> dict[str, Any]:
            """This is the docstring."""
            return {}

        assert _documented_fetch.__doc__ == "This is the docstring."


# ---------------------------------------------------------------------------
# reset_client
# ---------------------------------------------------------------------------


class TestResetClient:
    def test_reset_delegates_to_reset_redis_client(self) -> None:
        with patch("backend.tools.cache.reset_redis_client") as mock_reset:
            reset_client()
        mock_reset.assert_called_once()
