# backend/tests/unit/test_auth_router.py
"""
Unit tests for T-046: backend/routers/auth.py

End-to-end HTTP tests against the real FastAPI app (httpx.ASGITransport,
same pattern as test_main.py) with get_async_session overridden to a
small in-memory fake session -- not a real PostgreSQL connection, but a
stateful fake that genuinely inserts/queries rows, so the full
register -> login -> GET /me flow exercises real router + service +
ORM-construction logic rather than a fully mocked stub.

Acceptance criteria verified (from task spec):
  * Register -> login -> access protected route works end-to-end
  * Invalid token returns 401

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_auth_router.py -v
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, cast
import uuid

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import User

# ---------------------------------------------------------------------------
# Fake in-memory AsyncSession
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for SQLAlchemy's Result object."""

    def __init__(self, value: User | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> User | None:
        return self._value


class _FakeAsyncSession:
    """
    A tiny in-memory fake of AsyncSession that supports exactly the
    operations backend/routers/auth.py and backend/dependencies/auth.py
    use: execute(select(User).where(User.email == ...)),
    execute(select(User).where(User.id == ...)), add(), commit(),
    rollback(), refresh().

    Not a SQL engine -- inspects the compiled WHERE clause's bound
    parameter value directly. This is deliberately narrow (it would not
    support a real router doing anything more complex), which is
    appropriate: it exists only to make auth's three endpoints
    testable without a running PostgreSQL instance.
    """

    def __init__(self) -> None:
        self._users_by_id: dict[uuid.UUID, User] = {}
        self._pending: list[User] = []

    async def execute(self, statement: Any) -> _FakeResult:
        # Inspect the compiled statement's WHERE clause to find which
        # column is being filtered on and by what value, without
        # needing a real database engine to execute against.
        compiled = statement.compile(compile_kwargs={"literal_binds": False})
        params = compiled.params

        if "email_1" in params:
            target_email = params["email_1"]
            for user in self._users_by_id.values():
                if user.email == target_email:
                    return _FakeResult(user)
            return _FakeResult(None)

        if "id_1" in params:
            target_id = params["id_1"]
            return _FakeResult(self._users_by_id.get(target_id))

        return _FakeResult(None)

    def add(self, instance: User) -> None:
        self._pending.append(instance)

    async def commit(self) -> None:
        for user in self._pending:
            if user.id is None:
                user.id = uuid.uuid4()
            if any(
                existing.email == user.email
                for existing in self._users_by_id.values()
                if existing.id != user.id
            ):
                self._pending.clear()
                raise IntegrityError(
                    statement="INSERT", params={}, orig=Exception("duplicate email")
                )
            if user.is_active is None:
                user.is_active = True
            # User.created_at / updated_at are server_default=func.now()
            # columns -- a real PostgreSQL INSERT fills these in at the
            # database, and the ORM only sees the value after
            # session.refresh(user) re-reads the row. This fake session
            # has no real database underneath it, so nothing else would
            # ever populate these, leaving them None and failing
            # UserResponse's non-optional `created_at: datetime` field.
            # Simulate the server default explicitly here, the same
            # place id/is_active are simulated above.
            now = datetime.now(timezone.utc)
            if user.created_at is None:
                user.created_at = now
            if user.updated_at is None:
                user.updated_at = now
            self._users_by_id[user.id] = user
        self._pending.clear()

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, instance: User) -> None:
        return None


def _make_session_override(
    shared: _FakeAsyncSession,
) -> Any:
    """
    Build a zero-argument async generator function to use as a
    dependency_overrides value for get_async_session.

    FastAPI's dependency resolution machinery special-cases async
    generator FUNCTIONS passed to Depends() / dependency_overrides: it
    calls the function with no arguments, then drives the resulting
    generator itself (the equivalent of `async for value in gen():
    return value`) to obtain the yielded session.

    A bare `lambda: _fake_get_async_session(shared)` does NOT work for
    this -- calling an async generator function returns an async
    generator OBJECT immediately, without running any of its body.
    FastAPI then treats that object itself as the already-resolved
    dependency value (since a lambda is an ordinary callable, not an
    async generator function), so route handlers received the raw
    generator object instead of the session it would yield --
    `AttributeError: 'async_generator' object has no attribute
    'execute'`. Returning a real `async def` closure here (still zero
    arguments, closing over `shared` instead of taking it as a
    parameter) makes FastAPI correctly recognise and drive it as an
    async generator dependency, exactly like the real
    get_async_session().
    """

    async def _override() -> AsyncGenerator[_FakeAsyncSession, None]:
        yield shared

    return _override


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session() -> _FakeAsyncSession:
    """One fake session shared across a single test's requests, so a
    user registered in one request is visible to a later login/me
    request within the same test -- mirroring how a real connection
    pool would behave for one logical flow."""
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
# POST /auth/register
# ---------------------------------------------------------------------------


class TestRegister:
    @pytest.mark.asyncio
    async def test_returns_201(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": _VALID_PASSWORD},
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_returns_access_token(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": _VALID_PASSWORD},
        )
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_returns_user_without_password_hash(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": _VALID_PASSWORD},
        )
        user = response.json()["user"]
        assert user["email"] == "new@example.com"
        assert "password_hash" not in user
        assert "password" not in user

    @pytest.mark.asyncio
    async def test_duplicate_email_returns_409(self, client: httpx.AsyncClient) -> None:
        first = await client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": _VALID_PASSWORD},
        )
        assert first.status_code == 201

        second = await client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": _VALID_PASSWORD},
        )
        assert second.status_code == 409

    @pytest.mark.asyncio
    async def test_short_password_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": "short"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_email_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": _VALID_PASSWORD},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    @pytest.mark.asyncio
    async def test_correct_credentials_return_200_and_token(
        self, client: httpx.AsyncClient
    ) -> None:
        await client.post(
            "/auth/register",
            json={"email": "login@example.com", "password": _VALID_PASSWORD},
        )
        response = await client.post(
            "/auth/login",
            json={"email": "login@example.com", "password": _VALID_PASSWORD},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self, client: httpx.AsyncClient) -> None:
        await client.post(
            "/auth/register",
            json={"email": "login2@example.com", "password": _VALID_PASSWORD},
        )
        response = await client.post(
            "/auth/login",
            json={"email": "login2@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_email_returns_401(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": _VALID_PASSWORD},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_and_wrong_password_return_same_detail(
        self, client: httpx.AsyncClient
    ) -> None:
        """Both failure modes must be indistinguishable to the caller --
        verifies the deliberate non-enumeration design in the router."""
        await client.post(
            "/auth/register",
            json={"email": "exists@example.com", "password": _VALID_PASSWORD},
        )
        wrong_password_resp = await client.post(
            "/auth/login",
            json={"email": "exists@example.com", "password": "wrong-password"},
        )
        no_such_user_resp = await client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": _VALID_PASSWORD},
        )
        assert (
            wrong_password_resp.json()["detail"] == no_such_user_resp.json()["detail"]
        )


# ---------------------------------------------------------------------------
# GET /auth/me -- protected route
# ---------------------------------------------------------------------------


class TestMe:
    @pytest.mark.asyncio
    async def test_valid_token_returns_200_and_user(
        self, client: httpx.AsyncClient
    ) -> None:
        register_resp = await client.post(
            "/auth/register",
            json={"email": "me@example.com", "password": _VALID_PASSWORD},
        )
        token = register_resp.json()["access_token"]

        response = await client.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["email"] == "me@example.com"

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_token_returns_401(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_token_from_login_also_works(self, client: httpx.AsyncClient) -> None:
        """The full register -> login -> protected-route flow, using a
        SEPARATE login call's token rather than the register response's
        token -- the acceptance criterion's exact wording."""
        await client.post(
            "/auth/register",
            json={"email": "flow@example.com", "password": _VALID_PASSWORD},
        )
        login_resp = await client.post(
            "/auth/login",
            json={"email": "flow@example.com", "password": _VALID_PASSWORD},
        )
        token = login_resp.json()["access_token"]

        response = await client.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["email"] == "flow@example.com"
