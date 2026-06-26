# backend/main.py
"""
AIRP -- FastAPI Application Entrypoint (T-045 / T-046 / T-047 / T-048 / T-049)

Creates and configures the single FastAPI ``app`` instance used by both
local development (``uvicorn backend.main:app --reload``) and production
deployment (Render).

Responsibilities of this module ONLY
-------------------------------------
* Construct the ``FastAPI`` app with title/description/version metadata
  (drives the auto-generated Swagger UI at /docs and ReDoc at /redoc).
* Wire CORS so the React frontend (a different origin in dev and prod)
  can call the API and open the WebSocket endpoint added in T-049.
* Register routers (currently: health, auth, analysis, websocket). Each
  new router added from T-049 onward is included here and nowhere
  else. T-048 added a new route to the EXISTING analysis router
  (backend/routers/analysis.py) rather than a new router module, so no
  change was needed here for that task. T-049 DOES add a new router
  module (backend/routers/websocket.py, ``WS /api/v1/analysis/{job_id}
  /stream``) and is registered below alongside the other three.
* Provide a typed lifespan context manager as the single place startup
  and shutdown behaviour is added (e.g. warming the LangGraph singleton
  in a later task) -- avoids scattering @app.on_event hooks.

Explicitly OUT of scope for T-045 through T-049 (later tasks)
-----------------------------------------------------------------
* Document upload endpoint                          -> T-051

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

from backend.config import settings
from backend.routers import analysis, auth, health, websocket

logger = logging.getLogger(__name__)

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


def create_app() -> FastAPI:
    """
    Build and configure the FastAPI application.

    A factory function (rather than module-level construction only) makes
    the app trivially re-creatable in tests with different settings, and
    keeps ``app`` at the bottom of this module as a thin call to this
    function -- the conventional FastAPI pattern.
    """
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
    # origin (http://localhost:5173) so the React frontend built in
    # Phase 6 can call this API without any extra local configuration.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Routers -------------------------------------------------------------
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(analysis.router)
    application.include_router(websocket.router)

    return application


app: FastAPI = create_app()
