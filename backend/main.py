# backend/main.py
"""
AIRP -- FastAPI Application Entrypoint
(T-045 / T-046 / T-047 / T-048 / T-049 / T-050 / T-051)

Creates and configures the single FastAPI ``app`` instance used by both
local development (``uvicorn backend.main:app --reload``) and production
deployment (Render).

Responsibilities of this module ONLY
-------------------------------------
* Construct the ``FastAPI`` app with title/description/version metadata
  (drives the auto-generated Swagger UI at /docs and ReDoc at /redoc).
* Wire CORS so the React frontend (a different origin in dev and prod)
  can call the API and open the WebSocket endpoint added in T-049.
* Register routers (currently: health, auth, analysis, websocket,
  documents, accuracy). Each new router added from T-049 onward is
  included here and nowhere else. T-048 and T-050 both added new routes
  to the EXISTING analysis router (backend/routers/analysis.py) rather
  than a new router module, so no change was needed here for either
  task. T-049 added a new router module (backend/routers/websocket.py,
  ``WS /api/v1/analysis/{job_id}/stream``), T-051 added another
  (backend/routers/documents.py, ``POST /api/v1/documents/upload``),
  and T-090 added ``backend/routers/accuracy.py``
  (``POST /api/v1/accuracy/run``) -- all three registered below
  alongside the other routers.
* Provide a typed lifespan context manager as the single place startup
  and shutdown behaviour is added (e.g. warming the LangGraph singleton
  in a later task) -- avoids scattering @app.on_event hooks.

Explicitly OUT of scope for T-045 through T-051 (later tasks)
-----------------------------------------------------------------
* API test suite (pytest + httpx coverage pass)  -> T-052

Usage
-----
Local dev:
    uvicorn backend.main:app --reload --port 8000

Production (Render):
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import Settings, settings
from backend.routers import (
    accuracy,
    analysis,
    auth,
    chat,
    chat_stream,
    companies,
    documents,
    health,
    websocket,
)
from backend.services.rate_limiter import RateLimitMiddleware

logger = logging.getLogger(__name__)


def configure_logging(log_level: str) -> None:
    """
    Apply LOG_LEVEL to the root logger so application log calls are
    actually emitted somewhere.

    Section C audit finding, found during a live full-system smoke
    test: backend.config.Settings.log_level (LOG_LEVEL) was read and
    documented everywhere, but nothing ever actually applied it -- no
    logging.basicConfig()/dictConfig() call existed anywhere in this
    codebase. With the root logger left completely unconfigured, every
    module's `logging.getLogger(__name__).info(...)`/`.debug(...)` call
    (hundreds of them across backend/routers, backend/agents,
    backend/graph, ...) was silently dropped in every environment,
    local dev included -- Python's logging module only falls back to a
    bare stderr handler (`logging.lastResort`) fixed at WARNING, so
    only .warning()/.error() calls were ever actually visible. This was
    caught concretely: POST /auth/password-reset/request's own
    degraded-path `logger.info("password_reset: no email service
    configured -- reset URL for %s: %s", ...)`
    (backend/routers/auth.py) -- the exact mechanism a local developer
    relies on to complete a password reset without a real SMTP server
    -- never once appeared in the server's own log output despite
    firing on every request, because it logs at INFO.

    Called at import time (module scope, below), so it applies
    identically for every way this module gets loaded -- `uvicorn
    backend.main:app`, Render's production process, and pytest
    importing backend.main indirectly through other modules.
    `logging.basicConfig()` is a documented no-op if the root logger
    already has a handler (e.g. pytest's own logging plugin got there
    first), so this cannot fight or duplicate test log capture.

    A separate function (not inlined at module scope) purely so this
    behaviour is directly unit-testable -- asserting on side effects of
    a bare module-import statement, executed exactly once per process
    and cached in sys.modules thereafter, is not practical from a test.
    """
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


configure_logging(settings.log_level)

# ---------------------------------------------------------------------------
# App metadata -- drives Swagger UI (/docs) and ReDoc (/redoc)
# ---------------------------------------------------------------------------

API_TITLE = "AIRP -- Autonomous Investment Research Platform API"
API_DESCRIPTION = (
    "Backend API for AIRP, a multi-agent investment committee that "
    "researches, debates, and produces BUY/HOLD/SELL Investment Memos "
    "for NSE/BSE equities. Built with FastAPI, LangGraph, and PostgreSQL."
)
API_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Lifespan -- single place for startup/shutdown hooks
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Run startup logic before the app accepts requests, and shutdown
    logic after it stops accepting them.

    T-045 only logs the active environment so deployed logs immediately
    show which configuration is live. Later tasks (e.g. warming
    the LangGraph singleton via ``get_compiled_graph()``, or opening a
    Redis connection pool eagerly) hook into this same function rather
    than adding separate ``@app.on_event`` decorators, which are
    deprecated in modern FastAPI in favour of lifespan context managers.
    """
    logger.info(
        "AIRP backend starting -- environment=%s llm_provider=%s",
        settings.environment,
        settings.llm_provider,
    )
    yield
    logger.info("AIRP backend shutting down")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """
    Build and configure the FastAPI application.

    A factory function (rather than module-level construction only) makes
    the app trivially re-creatable in tests with different settings, and
    keeps ``app`` at the bottom of this module as a thin call to this
    function -- the conventional FastAPI pattern.

    ``settings_override`` lets callers (namely tests) build the app against
    a fully self-contained ``Settings`` instance -- e.g. the ``test_settings``
    fixture in ``backend/tests/conftest.py`` -- instead of the process-wide
    ``backend.config.settings`` singleton, which is populated from real
    environment variables at import time. Without this, CORS-related tests
    silently depend on whatever CORS_ORIGINS happens to be set to in the
    environment pytest runs in, rather than the value the test itself
    asserts against.
    """
    active_settings = settings_override or settings

    application = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=API_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # -- CORS --------------------------------------------------------------
    # settings.cors_origins_list is parsed from the comma-separated
    # CORS_ORIGINS env var (config.py). Defaults to the Vite dev server
    # origin (http://localhost:3000, see frontend/vite.config.ts's
    # server.port) so the React frontend built in Phase 6 can call this
    # API without any extra local configuration.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Rate limiting (T-074 audit findings C9/F9) -------------------------
    # In-process, per-client-IP fixed-window limiter -- protects the Groq
    # and NewsAPI free-tier quotas from a single caller's runaway traffic
    # once this is a public URL. See backend.services.rate_limiter's own
    # module docstring for the full design rationale (why in-process, why
    # fixed-window, why /health is exempt).
    if active_settings.feature_rate_limiting:
        application.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=active_settings.rate_limit_requests_per_minute,
        )

    # -- Routers -------------------------------------------------------------
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(analysis.router)
    application.include_router(websocket.router)
    application.include_router(documents.router)
    application.include_router(accuracy.router)
    application.include_router(chat.router)
    application.include_router(chat_stream.router)
    application.include_router(companies.router)

    return application


app: FastAPI = create_app()
