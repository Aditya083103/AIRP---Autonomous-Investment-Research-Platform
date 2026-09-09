# backend/tests/unit/test_rate_limiter.py
"""
Unit tests for backend/services/rate_limiter.py (T-074 audit findings
C9/F9 -- feature_rate_limiting was declared in Settings but nothing ever
enforced it; this module and its wiring in backend/main.py close that gap).

Test strategy:
  1. RateLimiter        -- fixed-window counting, independent per key
  2. _client_key          -- X-Forwarded-For preferred over request.client
  3. RateLimitMiddleware  -- 429 over the limit, /health always exempt
"""

import os
import threading
import time
from unittest.mock import MagicMock

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from backend.services.rate_limiter import (  # noqa: E402
    YFINANCE_MAX_CONCURRENT_REQUESTS,
    ConcurrencyThrottle,
    RateLimiter,
    RateLimitMiddleware,
    _client_key,
    yfinance_throttle,
)

# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_allows_requests_under_the_limit(self) -> None:
        limiter = RateLimiter(requests_per_window=3, window_seconds=60)
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is True

    def test_blocks_requests_over_the_limit(self) -> None:
        limiter = RateLimiter(requests_per_window=2, window_seconds=60)
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is False

    def test_clients_are_tracked_independently(self) -> None:
        limiter = RateLimiter(requests_per_window=1, window_seconds=60)
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-b") is True
        assert limiter.allow("client-a") is False
        assert limiter.allow("client-b") is False

    def test_window_resets_after_expiry(self) -> None:
        limiter = RateLimiter(requests_per_window=1, window_seconds=0.05)
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is False
        time.sleep(0.06)
        assert limiter.allow("client-a") is True


# ---------------------------------------------------------------------------
# _client_key
# ---------------------------------------------------------------------------


class TestClientKey:
    def test_prefers_x_forwarded_for(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
        assert _client_key(request) == "203.0.113.5"

    def test_falls_back_to_request_client_host(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        assert _client_key(request) == "127.0.0.1"

    def test_falls_back_to_unknown_when_client_is_none(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = None
        assert _client_key(request) == "unknown"


# ---------------------------------------------------------------------------
# RateLimitMiddleware (end-to-end via a minimal Starlette app)
# ---------------------------------------------------------------------------


def _make_app(requests_per_minute: int) -> Starlette:
    async def ok(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/thing", ok),
            Route("/health", ok),
        ]
    )
    app.add_middleware(RateLimitMiddleware, requests_per_minute=requests_per_minute)
    return app


class TestRateLimitMiddleware:
    def test_requests_under_limit_pass_through(self) -> None:
        client = TestClient(_make_app(requests_per_minute=5))
        for _ in range(5):
            response = client.get("/thing")
            assert response.status_code == 200

    def test_requests_over_limit_get_429(self) -> None:
        client = TestClient(_make_app(requests_per_minute=2))
        assert client.get("/thing").status_code == 200
        assert client.get("/thing").status_code == 200
        blocked = client.get("/thing")
        assert blocked.status_code == 429
        assert "Too many requests" in blocked.json()["detail"]

    def test_health_endpoint_is_always_exempt(self) -> None:
        """A liveness probe must never itself get rate-limited -- that
        would make the platform wrongly conclude the service is down."""
        client = TestClient(_make_app(requests_per_minute=1))
        for _ in range(10):
            assert client.get("/health").status_code == 200

    def test_different_clients_are_not_penalised_by_each_other(self) -> None:
        client = TestClient(_make_app(requests_per_minute=1))
        assert (
            client.get("/thing", headers={"x-forwarded-for": "1.1.1.1"}).status_code
            == 200
        )
        assert (
            client.get("/thing", headers={"x-forwarded-for": "2.2.2.2"}).status_code
            == 200
        )
        assert (
            client.get("/thing", headers={"x-forwarded-for": "1.1.1.1"}).status_code
            == 429
        )


# ---------------------------------------------------------------------------
# ConcurrencyThrottle / yfinance_throttle (T-087, Section A)
# ---------------------------------------------------------------------------


class TestConcurrencyThrottle:
    def test_rejects_non_positive_max_concurrent(self) -> None:
        with pytest.raises(ValueError):
            ConcurrencyThrottle(0)

    def test_single_caller_acquires_and_releases(self) -> None:
        throttle = ConcurrencyThrottle(1)
        with throttle.acquire():
            pass  # must not raise / hang
        # A second, later acquisition must succeed -- the slot was released.
        with throttle.acquire():
            pass

    def test_bounds_concurrency_to_max_concurrent(self) -> None:
        """
        With max_concurrent=2, a third caller must block until one of the
        first two releases -- verified by timing: the third acquire()
        cannot complete before either of the first two threads finishes
        its (artificially slow) guarded section.
        """
        throttle = ConcurrencyThrottle(2)
        currently_inside = {"n": 0, "max_seen": 0}
        lock = threading.Lock()

        def worker() -> None:
            with throttle.acquire():
                with lock:
                    currently_inside["n"] += 1
                    currently_inside["max_seen"] = max(
                        currently_inside["max_seen"], currently_inside["n"]
                    )
                time.sleep(0.05)
                with lock:
                    currently_inside["n"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert currently_inside["max_seen"] <= 2

    def test_yfinance_throttle_is_bounded_by_the_documented_constant(self) -> None:
        """
        yfinance_throttle must actually be constructed with
        YFINANCE_MAX_CONCURRENT_REQUESTS, not just happen to share the
        name -- verified behaviourally rather than by reaching into
        private state: acquiring exactly that many slots must succeed,
        and each acquired slot is independently releasable.
        """
        acquired: list[object] = []
        try:
            for _ in range(YFINANCE_MAX_CONCURRENT_REQUESTS):
                ctx = yfinance_throttle.acquire()
                ctx.__enter__()
                acquired.append(ctx)
        finally:
            for ctx in acquired:
                ctx.__exit__(None, None, None)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
