# backend/dependencies/__init__.py
"""
AIRP dependencies package.

Holds FastAPI ``Depends()``-compatible callables shared across routers --
the things route handlers ask for in their function signature rather than
importing and constructing directly. Centralising them here (instead of
inline in each router) is what makes ``app.dependency_overrides[...]``
overrides in tests work cleanly.

Current dependencies
----------------------
    common.py   -- get_settings_dependency (Settings injection) (T-045)
    auth.py     -- get_current_user (JWT verification) (T-046)

Planned (later tasks -- not yet present)
-----------------------------------------
    db.py       -- thin re-export of backend.db.session.get_async_session
                   for routers that prefer importing from this package
"""
