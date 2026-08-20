# backend/services/rate_limiter.py
"""
AIRP -- In-process per-client rate limiting middleware (T-074 audit
findings C9/F9).

Before this module existed, backend.config.Settings declared
feature_rate_limiting: bool = True and nothing anywhere read it -- no
rate limiting existed at all. On a public URL, that means a single caller
(malicious or just enthusiastic) could burn the Groq and NewsAPI free-tier
quotas within hours.

Design
------
A fixed-window counter per client key (IP address, or X-Forwarded-For's
first hop when behind a reverse proxy -- see _client_key), reset every
RateLimiter.window_seconds. This is intentionally the simplest correct
rate limiter, not a sliding-window/token-bucket one: the goal is "stop
runaway abuse of a free-tier API budget on a single process," not
precise fairness, and a fixed window is trivial to reason about and test.

In-process only, exactly like backend.services.ws_broadcaster's own
documented pattern -- a single Render web service instance is the actual
deploy target this guards, so a Redis-backed distributed limiter would be
over-engineering for what this needs to do. If AIRP ever scales to
multiple instances, this should move to a Redis INCR + EXPIRE pattern
instead (backend.db.redis_client already exists and could back it).

Never blocks health checks: GET /health is exempt so the platform's own
liveness probe can never itself get rate-limited into reporting the
service as down.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

#: Paths never subject to rate limiting -- platform health checks must
#: always succeed regardless of traffic volume, or the deploy host would
#: wrongly conclude the service itself is down.
_EXEMPT_PATHS = frozenset({"/health"})


def _client_key(request: Request) -> str:
    """
    Derive a per-client identifier for the rate-limit bucket.

    Prefers the first hop of X-Forwarded-For (set by Render's / any
    reverse proxy's edge) over request.client.host, which behind a proxy
    is always the proxy's own address -- using it directly would bucket
    every real client together under one shared limit.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


class RateLimiter:
    """
    Fixed-window request counter.

    Not thread-safe across multiple OS threads -- fine here because
    Starlette middleware runs on the single asyncio event loop, the same
    concurrency model backend.services.ws_broadcaster already relies on
    for its own in-process state.
    """

    def __init__(self, requests_per_window: int, window_seconds: float = 60) -> None:
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._counts: dict[str, int] = {}
        self._window_started_at: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        """Return True if this request should proceed, False if rate-limited."""
        now = time.monotonic()
        window_start = self._window_started_at.get(key)
        if window_start is None or now - window_start >= self.window_seconds:
            self._window_started_at[key] = now
            self._counts[key] = 1
            return True
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key] <= self.requests_per_window


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware enforcing RateLimiter per client, returning 429 for
    requests over the limit. Registered in backend.main.create_app only
    when settings.feature_rate_limiting is True.
    """

    def __init__(self, app: ASGIApp, requests_per_minute: int) -> None:
        super().__init__(app)
        self._limiter = RateLimiter(
            requests_per_window=requests_per_minute, window_seconds=60
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        key = _client_key(request)
        if not self._limiter.allow(key):
            logger.warning(
                "Rate limit exceeded for client=%s path=%s", key, request.url.path
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down and try again."
                },
            )
        return await call_next(request)
