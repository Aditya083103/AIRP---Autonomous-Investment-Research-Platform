# backend/tests/unit/test_auth_cookies.py
"""
Unit tests for T-056: the httpOnly cookie behaviour added to
backend/routers/auth.py (register, login, logout).

Deliberately a separate file from test_auth_router.py (T-046) rather
than an edit to it: this keeps the already-passing T-046 test file
untouched while covering the new, additive cookie behaviour on its
own. Uses its own small fake AsyncSession (same shape as
test_auth_router.py's, kept independent on purpose so this file has
no import-time dependency on another test module).

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_auth_cookies.py -v
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, cast
import uuid

from fastapi import FastAPI
import httpx
import pytest

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import User
from backend.routers.auth import ACCESS_TOKEN_COOKIE_NAME

# ---------------------------------------------------------------------------
# Minimal fake in-memory AsyncSession (register + login only)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value: User | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> User | None:
        return self._value


class _FakeAsyncSession:
    def __init__(self) -> None:
        self._users_by_email: dict[str, User] = {}
        self._pending: list[User] = []

    async def execute(self, statement: Any) -> _FakeResult:
        compiled = statement.compile(compile_kwargs={"literal_binds": False})
        params = compiled.params
        if "email_1" in params:
            return _FakeResult(self._users_by_email.get(params["email_1"]))
        return _FakeResult(None)

    def add(self, instance: User) -> None:
        self._pending.append(instance)

    async def commit(self) -> None:
        now = datetime.now(timezone.utc)
        for user in self._pending:
            user.id = user.id if user.id is not None else uuid.uuid4()
            user.is_active = True if user.is_active is None else user.is_active
            user.created_at = user.created_at or now
            user.updated_at = user.updated_at or now
            self._users_by_email[user.email] = user
        self._pending.clear()

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, instance: User) -> None:
        return None


def _make_session_override(shared: _FakeAsyncSession) -> Any:
    async def _override() -> AsyncGenerator[_FakeAsyncSession, None]:
        yield shared

    return _override


@pytest.fixture
def fake_session() -> _FakeAsyncSession:
    return _FakeAsyncSession()


@pytest.fixture
async def client(
    fake_session: _FakeAsyncSession, test_settings: Settings
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _make_session_override(fake_session)
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


_VALID_PASSWORD = "correct-horse-battery-staple"


# ---------------------------------------------------------------------------
# POST /auth/register sets the cookie
# ---------------------------------------------------------------------------


class TestRegisterSetsCookie:
    @pytest.mark.asyncio
    async def test_sets_httponly_cookie(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "cookie-register@example.com", "password": _VALID_PASSWORD},
        )
        set_cookie = response.headers.get("set-cookie", "")
        assert ACCESS_TOKEN_COOKIE_NAME in set_cookie
        assert "httponly" in set_cookie.lower()

    @pytest.mark.asyncio
    async def test_cookie_value_matches_body_token(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "cookie-match@example.com", "password": _VALID_PASSWORD},
        )
        body_token = response.json()["access_token"]
        assert response.cookies.get(ACCESS_TOKEN_COOKIE_NAME) == body_token


# ---------------------------------------------------------------------------
# POST /auth/login sets the cookie
# ---------------------------------------------------------------------------


class TestLoginSetsCookie:
    @pytest.mark.asyncio
    async def test_sets_httponly_cookie(self, client: httpx.AsyncClient) -> None:
        await client.post(
            "/auth/register",
            json={"email": "cookie-login@example.com", "password": _VALID_PASSWORD},
        )
        response = await client.post(
            "/auth/login",
            json={"email": "cookie-login@example.com", "password": _VALID_PASSWORD},
        )
        set_cookie = response.headers.get("set-cookie", "")
        assert ACCESS_TOKEN_COOKIE_NAME in set_cookie
        assert "httponly" in set_cookie.lower()

    @pytest.mark.asyncio
    async def test_failed_login_sets_no_cookie(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": _VALID_PASSWORD},
        )
        assert response.status_code == 401
        assert "set-cookie" not in response.headers


# ---------------------------------------------------------------------------
# POST /auth/logout clears the cookie
# ---------------------------------------------------------------------------


class TestLogout:
    @pytest.mark.asyncio
    async def test_returns_204(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/auth/logout")
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_clears_the_cookie(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/auth/logout")
        set_cookie = response.headers.get("set-cookie", "")
        assert ACCESS_TOKEN_COOKIE_NAME in set_cookie
        # Starlette's Response.delete_cookie expires the cookie immediately
        # (Max-Age=0) rather than sending back a real token value -- this
        # is the version-stable signal to check for, rather than asserting
        # on the exact empty-value serialization (quoted vs. unquoted).
        assert "max-age=0" in set_cookie.lower()

    @pytest.mark.asyncio
    async def test_does_not_require_authentication(
        self, client: httpx.AsyncClient
    ) -> None:
        """Logout must work even with no Authorization header -- AIRP's
        JWTs are stateless, so there is nothing on the server to check."""
        response = await client.post("/auth/logout")
        assert response.status_code != 401
