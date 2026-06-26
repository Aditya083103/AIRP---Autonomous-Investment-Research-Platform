# backend/routers/__init__.py
"""
AIRP routers package.

Each FastAPI ``APIRouter`` lives in its own module here, one per
resource/concern (health, auth, analysis, websocket, documents, ...).
Every router is registered exactly once, in ``backend/main.py``, via
``app.include_router(...)``.

Current routers
----------------
    health.py     -- GET /health liveness probe (T-045)
    auth.py       -- POST /auth/register, /auth/login, GET /auth/me (T-046)
    analysis.py   -- POST /api/v1/analysis/start (T-047),
                     GET /api/v1/analysis/{job_id}/status (T-048),
                     GET /api/v1/analysis/{job_id}/result (T-050),
                     GET /api/v1/analysis/{job_id}/memo/pdf (T-050),
                     GET /api/v1/analysis/history (T-050)
    websocket.py  -- WS /api/v1/analysis/{job_id}/stream (T-049)
    documents.py  -- POST /api/v1/documents/upload (T-051)
"""
