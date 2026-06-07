# backend/tests/unit/test_cache.py
"""
Unit tests for backend/tools/cache.py — T-014 (cache helper)

These tests verify the cache helper's two contracts:
  1. Under ENVIRONMENT=test it is a hard no-op — get_client() returns None and
     get/set never touch a real Redis server (tests stay hermetic).
  2. With a fake client injected, get/set round-trip JSON and degrade
     gracefully (never raise) on a miss, a corrupt value, or a client error.

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_cache.py -v
"""
from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

import json  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from backend.tools import cache as cache_mod  # noqa: E402
from backend.tools.cache import (  # noqa: E402
    cache_get_json,
    cache_set_json,
    get_client,
    reset_client,
)


def teardown_function() -> None:
    """Reset memoised client state between tests."""
    reset_client()


class TestTestEnvironmentNoOp:
    def test_get_client_is_none_under_test_env(self) -> None:
        assert get_client() is None

    def test_cache_get_returns_none_under_test_env(self) -> None:
        assert cache_get_json("any:key") is None

    def test_cache_set_returns_false_under_test_env(self) -> None:
        assert cache_set_json("any:key", {"a": 1}, 60) is False


class TestWithFakeClient:
    """Bypass the test-env guard by patching get_client with a fake Redis."""

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
        from datetime import datetime, timezone

        fake = MagicMock()
        payload: dict[str, Any] = {"fetched_at": datetime.now(tz=timezone.utc)}
        with patch("backend.tools.cache.get_client", return_value=fake):
            ok = cache_set_json("k", payload, 60)
        assert ok is True  # default=str lets datetime serialise without error


class TestResetClient:
    def test_reset_clears_memoised_state(self) -> None:
        cache_mod._client_unavailable = True
        reset_client()
        assert cache_mod._client is None
        assert cache_mod._client_unavailable is False
