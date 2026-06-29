# backend/tests/unit/test_api_integration_flow.py
"""
Unit tests for T-052: end-to-end API integration coverage across every
router added in Phase 5 (T-045-T-051).

Why this file exists alongside the per-router suites
------------------------------------------------------
T-046 through T-051 each shipped their own router test file
(test_auth_router.py, test_analysis_router.py,
test_analysis_result_history_router.py, test_websocket_router.py,
test_documents_router.py, test_health_router.py, test_main.py) as part
of building that endpoint -- those files are thorough and this suite
does not re-derive their assertions. What none of them do is exercise
**one continuous session across routers**: a real user registering,
authenticating, triggering an analysis, watching it over WebSocket,
reading back the result, downloading the PDF, paging through history,
and uploading a document -- all against the SAME fake database state,
the way a real frontend session actually would. That cross-router
continuity, plus the handful of error-path combinations that only show
up when two routers are exercised together (e.g. "a token minted by
/auth/login is honoured identically by /analysis/start, /documents/
upload, and the WebSocket stream"), is this file's job.

Acceptance criteria verified (from task spec):
  * All endpoints tested              -- TestFullSessionHappyPath
                                          exercises every route in
                                          backend/main.py's
                                          create_app() in one flow
  * Auth flow covered                 -- TestAuthFlowAcrossRouters
  * WebSocket test connects and
    receives events                   -- TestWebSocketAcrossSession
  * Error cases (invalid ticker,
    rate limits)                      -- TestErrorCases

What is faked vs. real
-----------------------
  * get_async_session -> _FakeFullSession, a single in-memory fake
    that merges the User-table operations test_auth_router.py's
    _FakeAsyncSession supports with the Company/Analysis ORM
    operations and the three raw text() queries (status, result,
    history) test_analysis_router.py / test_analysis_result_history_
    router.py already exercise separately -- ONE shared instance per
    test, so a user registered in step 1 is the same row
    get_current_user resolves in step 5.
  * get_current_user is NOT overridden in this file (unlike every
    per-router suite) -- the whole point is to prove the real
    dependency, the real JWT issued by /auth/login, and the real
    routers all agree with each other end-to-end.
  * run_analysis_pipeline patched to an AsyncMock (autouse) -- same
    rationale as test_analysis_router.py's patched_pipeline: the real
    background task would import all 8 agents and LangGraph itself.
  * backend.routers.websocket.AsyncSessionLocal patched to hand back
    the SAME _FakeFullSession instance the HTTP routes are using, so
    the WebSocket leg of the flow sees the identical Analysis row
    the HTTP leg created -- this is the one piece test_websocket_
    router.py's own suite does NOT do (it uses an isolated
    per-test fake), and is exactly the cross-router continuity this
    file adds.
  * backend.services.documents.build_chroma_client patched to an
    in-memory ChromaDB EphemeralClient -- identical pattern to
    test_documents_router.py.
  * backend.services.documents._extract_text_from_pdf_bytes patched to
    return a fixed sample string for any test that needs an upload to
    actually SUCCEED -- _TINY_PDF_BYTES below is not a structurally
    valid PDF (pdfminer.six genuinely fails to parse it), which is
    deliberately exploited by this file's negative-path tests but must
    be patched around for the happy-path/auth-flow tests that expect
    201, exactly the convention test_documents_router.py's own
    happy-path tests already established.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch
import uuid

import chromadb
from chromadb.config import Settings as _ChromaSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import TextClause

from backend.config import Settings
from backend.db.chroma_client import ChromaClient
from backend.db.session import get_async_session
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import Analysis, Company, User
from backend.tools.earnings_transcript import PDFExtractionError

# ---------------------------------------------------------------------------
# Fixed test data
# ---------------------------------------------------------------------------

_VALID_PASSWORD = "correct-horse-battery-staple"

_VALID_DECISION: dict[str, Any] = {
    "agent_name": "portfolio_manager",
    "analysis_id": "11111111-1111-1111-1111-111111111111",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "generated_at": "2026-06-20 10:30:00.123456",
    "error": None,
    "verdict": "BUY",
    "conviction_score": 8,
    "price_target": "Rs 4,200 (12-month)",
    "time_horizon": "12 months",
    "executive_summary": "TCS shows strong fundamentals.",
    "investment_thesis": "Consistent margin expansion and order book growth.",
    "bull_case": "Digital transformation deals accelerating.",
    "bear_case": "Currency headwinds and US recession risk.",
    "risk_summary": "Client concentration in BFSI vertical.",
    "valuation_summary": "Trading at a slight premium to 5-year average PE.",
    "key_risks": ["Client concentration", "Wage inflation"],
    "key_catalysts": ["Large deal wins", "Rupee depreciation"],
    "contrarian_response": "Diversification efforts are already underway.",
    "debate_rounds_used": 2,
    "agent_weights": {"fundamental_analyst": 0.3, "valuation_agent": 0.3},
    "summary": "TCS: BUY with conviction 8/10.",
}

#: A decision dict shaped exactly like _VALID_DECISION but reflecting a
#: News Sentiment Agent run that hit NewsAPI's daily quota -- see
#: backend.tools.news's rate_limit_exhausted degrade-to-dict contract
#: (agents never raise; the Risk Officer/Portfolio Manager still
#: produce a verdict from whatever data DID come back). This is what
#: "error cases ... rate limits" looks like at the API boundary: a
#: completed, 200-status analysis whose memo content records the
#: degradation, not an HTTP-level failure.
_RATE_LIMITED_DECISION: dict[str, Any] = {
    **_VALID_DECISION,
    "verdict": "HOLD",
    "conviction_score": 5,
    "risk_summary": (
        "News sentiment data unavailable -- NewsAPI rate limit exhausted "
        "after 3 retries. Verdict reflects fundamental and technical "
        "analysis only."
    ),
    "key_risks": [
        "News sentiment analysis incomplete (rate_limit_exhausted)",
        "Client concentration",
    ],
}


# ---------------------------------------------------------------------------
# Fake in-memory AsyncSession -- the union of every per-router fake this
# suite's predecessors built, sharing ONE instance across an entire
# session so register -> login -> analyse -> result -> history all see
# the same rows.
# ---------------------------------------------------------------------------


class _FakeScalarOrNoneResult:
    """Stand-in for SQLAlchemy's Result -- scalar_one_or_none() only."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeRowResult:
    """Stand-in for SQLAlchemy's Result -- fetchone() only."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _FakeRowsResult:
    """Stand-in for SQLAlchemy's Result -- fetchall() only."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows


class _FakeScalarResult:
    """Stand-in for SQLAlchemy's Result -- scalar_one() only."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value


class _FakeFullSession:
    """
    One in-memory fake AsyncSession supporting every operation the
    Phase 5 routers issue:

      * select(User).where(User.email == ...)   -- auth.register/login
      * select(User).where(User.id == ...)      -- get_current_user
      * select(Company).where(ticker, exchange)  -- analysis.start,
                                                     documents.upload
      * raw text() _SQL_LOAD_STATUS              -- analysis.status,
                                                     websocket ownership
                                                     check, memo/pdf
      * raw text() _SQL_LOAD_RESULT              -- analysis.result
      * raw text() _SQL_COUNT_HISTORY /
        _SQL_LOAD_HISTORY_PAGE                   -- analysis.history

    ORM selects are distinguished by inspecting the compiled
    statement's bound parameter values (User.email/.id values are
    unambiguous Python types -- str email vs. uuid.UUID -- and
    Company's two-column filter is matched by value, exactly like
    test_analysis_router.py's _FakeAnalysisSession). Raw text() queries
    are distinguished by a short substring of statement.text, exactly
    like test_analysis_result_history_router.py's
    _FakeResultHistorySession.
    """

    def __init__(self) -> None:
        self.users_by_id: dict[uuid.UUID, User] = {}
        self.companies: dict[uuid.UUID, Company] = {}
        self.analyses: dict[uuid.UUID, Analysis] = {}
        self.status_overrides: dict[uuid.UUID, tuple[Any, ...]] = {}
        self.result_overrides: dict[uuid.UUID, tuple[Any, ...]] = {}
        self.history_rows: dict[uuid.UUID, list[tuple[Any, ...]]] = {}
        self._pending: list[Any] = []

    # -- SELECT dispatch -----------------------------------------------

    async def execute(self, statement: Any, params: Any = None) -> Any:
        if isinstance(statement, TextClause):
            return self._execute_text(statement, params)
        return self._execute_orm_select(statement)

    @staticmethod
    def _target_entity(statement: Any) -> Any:
        """
        Return the mapped class a plain ``select(Model).where(...)``
        statement targets (``User`` or ``Company`` in this codebase),
        read directly off ``Select.column_descriptions`` rather than
        guessed from bound-parameter NAMES or VALUES.

        Both backend.routers.auth (``select(User)...``) and
        backend.services.analysis (``select(Company)...``) issue
        exactly one single-entity select each -- column_descriptions[0]
        ['entity'] is SQLAlchemy 2.x's own documented, public way to
        ask "what ORM class does this Select return rows of", and is
        far more robust across SQLAlchemy point releases than relying
        on whatever a particular query happens to name its bind
        parameters (e.g. "id_1" is liable to collide between two
        different single-column .where(Model.id == ...) filters on two
        different tables, exactly the ambiguity a previous version of
        this fake tried, and failed, to fully disambiguate by value).
        """
        try:
            return statement.column_descriptions[0]["entity"]
        except (AttributeError, IndexError, KeyError, TypeError):
            return None

    def _execute_text(self, statement: TextClause, params: Any) -> Any:
        sql = statement.text

        if "state_snapshot" in sql and "FROM analyses" in sql and "JOIN" not in sql:
            job_id = uuid.UUID(str(params["job_id"]))
            row = self.result_overrides.get(job_id)
            return _FakeRowResult(row)

        if "COUNT(*)" in sql:
            user_id = uuid.UUID(str(params["user_id"]))
            rows = self.history_rows.get(user_id, [])
            return _FakeScalarResult(len(rows))

        if "JOIN companies" in sql:
            user_id = uuid.UUID(str(params["user_id"]))
            rows = self.history_rows.get(user_id, [])
            limit = int(params["limit"])
            offset = int(params["offset"])
            page = rows[offset : offset + limit]
            return _FakeRowsResult(page)

        # Falls through to _SQL_LOAD_STATUS -- shared by GET /status,
        # the WebSocket ownership check, and GET /memo/pdf.
        job_id = uuid.UUID(str(params["job_id"]))
        row = self.status_overrides.get(job_id)
        return _FakeRowResult(row)

    def _execute_orm_select(self, statement: Any) -> Any:
        entity = self._target_entity(statement)
        compiled = statement.compile(compile_kwargs={"literal_binds": False})
        params = compiled.params
        bound_values = set(params.values())

        if entity is User:
            if "email_1" in params:
                target_email = params["email_1"]
                for user in self.users_by_id.values():
                    if user.email == target_email:
                        return _FakeScalarOrNoneResult(user)
                return _FakeScalarOrNoneResult(None)
            if "id_1" in params:
                target_id = params["id_1"]
                return _FakeScalarOrNoneResult(self.users_by_id.get(target_id))
            return _FakeScalarOrNoneResult(None)

        if entity is Company:
            # select(Company).where(Company.ticker == bare, Company.exchange == exch)
            if not bound_values:
                return _FakeScalarOrNoneResult(None)
            for company in self.companies.values():
                if company.ticker in bound_values and company.exchange in bound_values:
                    return _FakeScalarOrNoneResult(company)
            return _FakeScalarOrNoneResult(None)

        raise AssertionError(
            f"_FakeFullSession.execute received an ORM select for an "
            f"unsupported entity: {entity!r}. This fake only supports "
            f"select(User)/select(Company), matching every ORM query "
            f"backend.routers.auth / backend.services.analysis issue."
        )

    # -- Mutations -------------------------------------------------------

    def add(self, instance: Any) -> None:
        self._pending.append(instance)

    async def commit(self) -> None:
        for instance in self._pending:
            if isinstance(instance, User):
                self._commit_user(instance)
            elif isinstance(instance, Company):
                if instance.id is None:
                    instance.id = uuid.uuid4()
                self.companies[instance.id] = instance
            elif isinstance(instance, Analysis):
                if instance.id is None:
                    instance.id = uuid.uuid4()
                if instance.status is None:
                    instance.status = "pending"
                self.analyses[instance.id] = instance
                # Mirror the row into status_overrides AND
                # result_overrides immediately so GET /status and GET
                # /result issued right after POST /start (before any
                # test explicitly seeds a richer row) see the row a
                # real INSERT would have produced: status='pending',
                # state_snapshot=NULL. Without this, get_analysis_result
                # would see a missing row (row is None) and return 404
                # instead of correctly raising AnalysisNotReadyError
                # (-> 409) for a job that exists but has no decision yet.
                self.status_overrides.setdefault(
                    instance.id,
                    (
                        instance.user_id,
                        instance.status,
                        None,
                        None,
                        datetime.now(timezone.utc),
                        None,
                        None,
                    ),
                )
                self.result_overrides.setdefault(
                    instance.id,
                    (instance.user_id, instance.status, None),
                )
        self._pending.clear()

    def _commit_user(self, user: User) -> None:
        if user.id is None:
            user.id = uuid.uuid4()
        if any(
            existing.email == user.email
            for existing in self.users_by_id.values()
            if existing.id != user.id
        ):
            self._pending.clear()
            raise IntegrityError(
                statement="INSERT", params={}, orig=Exception("duplicate email")
            )
        if user.is_active is None:
            user.is_active = True
        now = datetime.now(timezone.utc)
        if user.created_at is None:
            user.created_at = now
        if user.updated_at is None:
            user.updated_at = now
        self.users_by_id[user.id] = user

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, instance: Any) -> None:
        return None


def _make_session_override(shared: _FakeFullSession) -> Any:
    """Zero-argument async generator function -- see
    test_auth_router.py's docstring for why a bare lambda does not work
    as a dependency_overrides value for an async-generator dependency."""

    async def _override() -> AsyncGenerator[_FakeFullSession, None]:
        yield shared

    return _override


def _seed_status_row(
    fake_session: _FakeFullSession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "completed",
    last_completed_node: Any = "pdf_export",
    error_message: Any = None,
    requested_at: Any = None,
    started_at: Any = None,
    completed_at: Any = None,
) -> None:
    """Overwrite status_overrides with the exact 7-tuple shape
    get_analysis_status reads via row[0]..row[6] -- used to simulate
    the pipeline having advanced since the initial commit-time row."""
    fake_session.status_overrides[job_id] = (
        user_id,
        status,
        last_completed_node,
        error_message,
        requested_at or datetime.now(timezone.utc),
        started_at,
        completed_at,
    )


def _seed_result_row(
    fake_session: _FakeFullSession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "completed",
    decision: dict[str, Any] | None = None,
) -> None:
    """Populate result_overrides with the exact 3-tuple shape
    get_analysis_result reads via row[0]..row[2]."""
    snapshot = {"decision": decision} if decision is not None else None
    fake_session.result_overrides[job_id] = (user_id, status, snapshot)


def _seed_history_row(
    fake_session: _FakeFullSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    company_name: str = "Tata Consultancy Services",
    ticker_yf: str = "TCS.NS",
    exchange: str = "NSE",
    status: str = "completed",
    requested_at: Any = None,
    completed_at: Any = None,
    verdict: Any = "BUY",
    conviction_score: Any = "8",
) -> None:
    """Append one row to history_rows, in the exact 9-tuple shape
    get_analysis_history reads via row[0]..row[8]."""
    fake_session.history_rows.setdefault(user_id, []).append(
        (
            job_id,
            company_name,
            ticker_yf,
            exchange,
            status,
            requested_at or datetime(2026, 6, 20, tzinfo=timezone.utc),
            completed_at,
            verdict,
            conviction_score,
        )
    )


# ---------------------------------------------------------------------------
# Shared ChromaDB test infrastructure -- mirrors test_documents_router.py's
# _MockEF / EphemeralClient pattern, so document upload can be exercised
# as part of the full session without loading a real embedding model.
# ---------------------------------------------------------------------------


class _MockEmbeddingFunction:
    """Fake embedding function satisfying ChromaDB's __call__ signature
    check, without loading any real sentence-transformer model."""

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [[0.1] * 384 for _ in input]


_TEST_CHROMA_SETTINGS = _ChromaSettings(
    is_persistent=False,
    allow_reset=True,
    anonymized_telemetry=False,
)

_SHARED_RAW_CHROMA_CLIENT: Any = chromadb.EphemeralClient(
    settings=_TEST_CHROMA_SETTINGS
)


def _make_chroma_client() -> ChromaClient:
    _SHARED_RAW_CHROMA_CLIENT.reset()
    return ChromaClient(_SHARED_RAW_CHROMA_CLIENT, _MockEmbeddingFunction())


_TINY_PDF_BYTES = b"%PDF-1.4 fake pdf content for integration testing\n%%EOF"

#: _TINY_PDF_BYTES above is not a structurally valid PDF -- pdfminer.six
#: genuinely fails to parse it (raises PDFExtractionError), which is
#: exactly the right behaviour for THIS file's negative tests (garbage
#: token, blank company_name, corrupt-PDF) since those should fail
#: before/regardless of extraction. Any test that needs the upload to
#: actually SUCCEED must patch
#: backend.services.documents._extract_text_from_pdf_bytes to return
#: this sample text instead -- the exact convention
#: test_documents_router.py's own happy-path tests already established,
#: rather than constructing a byte-perfect real PDF inline.
_SAMPLE_TEXT = (
    "Tata Consultancy Services Limited Annual Report FY2024. "
    "Revenue grew 12% year on year to Rs 240,893 crore. "
    "The board recommends a final dividend of Rs 28 per equity share. "
) * 5


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session() -> _FakeFullSession:
    """One fake session shared across an entire test's HTTP requests --
    this is the load-bearing fixture of this file: every other fixture
    and every test wires THIS instance into both the HTTP app and (for
    WebSocket tests) backend.routers.websocket.AsyncSessionLocal, so a
    user/company/analysis row created via one route is visible to
    every subsequent route call within the same test."""
    return _FakeFullSession()


@pytest.fixture(autouse=True)
def patched_pipeline(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace backend.routers.analysis.run_analysis_pipeline with an
    AsyncMock for every test in this module -- identical rationale to
    test_analysis_router.py's own patched_pipeline fixture."""
    import backend.routers.analysis as analysis_router_module

    mock = AsyncMock()
    monkeypatch.setattr(analysis_router_module, "run_analysis_pipeline", mock)
    return mock


@pytest.fixture(autouse=True)
def patched_chroma(monkeypatch: pytest.MonkeyPatch) -> ChromaClient:
    """Replace backend.services.documents.build_chroma_client with an
    in-memory EphemeralClient-backed ChromaClient for every test --
    identical rationale to test_documents_router.py's patched_chroma."""
    import backend.services.documents as documents_service_module

    client = _make_chroma_client()
    monkeypatch.setattr(documents_service_module, "build_chroma_client", lambda: client)
    return client


@pytest.fixture
async def client(
    fake_session: _FakeFullSession,
    test_settings: Settings,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    The real FastAPI app with ONLY get_async_session and
    get_settings_dependency overridden -- get_current_user is
    deliberately left wired to the real dependency (unlike every
    per-router suite) so this file proves real JWTs issued by
    POST /auth/login are honoured by every other router.
    """
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _make_session_override(fake_session)
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(
    client: httpx.AsyncClient,
    email: str = "analyst@example.com",
    password: str = _VALID_PASSWORD,
) -> tuple[str, uuid.UUID]:
    """Register a fresh user and return (access_token, user_id)."""
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": "Analyst"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


# ---------------------------------------------------------------------------
# 1. Full session happy path -- every endpoint, one continuous flow
# ---------------------------------------------------------------------------


class TestFullSessionHappyPath:
    """
    Walks the exact user journey AIRP_Project_Overview describes:
    register -> login -> trigger analysis -> poll status -> read
    result -> download PDF -> view history -> upload a supporting
    document -- all as the SAME authenticated user, against the SAME
    fake database state.
    """

    @pytest.mark.asyncio
    async def test_register_then_me_returns_the_same_user(
        self, client: httpx.AsyncClient
    ) -> None:
        token, user_id = await _register_and_login(client)

        me = await client.get("/auth/me", headers=_auth_headers(token))

        assert me.status_code == 200
        assert me.json()["id"] == str(user_id)
        assert me.json()["email"] == "analyst@example.com"

    @pytest.mark.asyncio
    async def test_login_after_register_issues_an_equally_valid_token(
        self, client: httpx.AsyncClient
    ) -> None:
        await _register_and_login(client, email="reuser@example.com")

        login_response = await client.post(
            "/auth/login",
            json={"email": "reuser@example.com", "password": _VALID_PASSWORD},
        )
        assert login_response.status_code == 200
        login_token = login_response.json()["access_token"]

        me = await client.get("/auth/me", headers=_auth_headers(login_token))
        assert me.status_code == 200
        assert me.json()["email"] == "reuser@example.com"

    @pytest.mark.asyncio
    async def test_full_journey_register_to_history_and_upload(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeFullSession,
        tmp_path: Path,
    ) -> None:
        # 1. Register -- immediately authenticated, no separate login.
        token, user_id = await _register_and_login(client)
        headers = _auth_headers(token)

        # 2. Trigger an analysis for a known company.
        start = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Tata Consultancy Services"},
            headers=headers,
        )
        assert start.status_code == 202
        job_id = uuid.UUID(start.json()["job_id"])
        assert start.json()["ticker"] == "TCS.NS"

        # 3. Poll status -- pending immediately after creation.
        status_response = await client.get(
            f"/api/v1/analysis/{job_id}/status", headers=headers
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "pending"

        # 4. Simulate the background pipeline reaching completion --
        #    the same two rows run_analysis_pipeline would itself write
        #    via state_persistence (T-033) once portfolio_manager_node
        #    finishes, seeded directly here since the pipeline itself
        #    is mocked out by the autouse patched_pipeline fixture.
        _seed_status_row(
            fake_session,
            job_id,
            user_id=user_id,
            status="completed",
            last_completed_node="pdf_export",
        )
        _seed_result_row(
            fake_session, job_id, user_id=user_id, decision=_VALID_DECISION
        )
        _seed_history_row(fake_session, user_id=user_id, job_id=job_id)

        # 5. Status now reflects completion.
        status_response = await client.get(
            f"/api/v1/analysis/{job_id}/status", headers=headers
        )
        assert status_response.json()["status"] == "completed"
        assert status_response.json()["progress_percent"] == 100

        # 6. Result returns the full Investment Memo.
        result = await client.get(f"/api/v1/analysis/{job_id}/result", headers=headers)
        assert result.status_code == 200
        result_body = result.json()
        assert result_body["verdict"] == "BUY"
        assert result_body["conviction_score"] == 8
        assert result_body["ticker"] == "TCS.NS"

        # 7. PDF download -- a real file on disk, resolved via the same
        #    "patch resolve_memo_pdf_path to a tmp_path file" approach
        #    test_analysis_result_history_router.py established
        #    (FileResponse reads an actual file, so a real on-disk path
        #    is needed rather than a fully mocked filesystem).
        pdf_path = tmp_path / f"{job_id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake memo pdf\n%%EOF")
        with patch(
            "backend.routers.analysis.resolve_memo_pdf_path",
            return_value=pdf_path,
        ):
            pdf_response = await client.get(
                f"/api/v1/analysis/{job_id}/memo/pdf", headers=headers
            )
        assert pdf_response.status_code == 200
        assert pdf_response.headers["content-type"] == "application/pdf"

        # 8. History lists the just-completed analysis.
        history = await client.get("/api/v1/analysis/history", headers=headers)
        assert history.status_code == 200
        history_body = history.json()
        assert history_body["total_count"] == 1
        assert history_body["items"][0]["job_id"] == str(job_id)
        assert history_body["items"][0]["verdict"] == "BUY"

        # 9. Upload a supporting annual report PDF for the SAME company
        #    -- proves backend.services.documents.link_document_to_company
        #    resolves to the identical Company row the analysis itself
        #    created (get_or_create_company's find path, not a second
        #    insert). PDF extraction itself is patched to a fixed
        #    sample text -- _TINY_PDF_BYTES is not a structurally valid
        #    PDF, and this step is about the Company-reuse contract,
        #    not about pdfminer's real parsing behaviour (that is
        #    test_documents_router.py's job, already covered there).
        with patch(
            "backend.services.documents._extract_text_from_pdf_bytes",
            return_value=_SAMPLE_TEXT,
        ):
            upload = await client.post(
                "/api/v1/documents/upload",
                headers=headers,
                files={
                    "file": (
                        "annual_report.pdf",
                        _TINY_PDF_BYTES,
                        "application/pdf",
                    )
                },
                data={"company_name": "Tata Consultancy Services"},
            )
        assert upload.status_code == 201
        assert upload.json()["ticker"] == "TCS.NS"
        assert len(fake_session.companies) == 1, (
            "the document upload must reuse the Company row "
            "POST /analysis/start already created, not insert a second one"
        )

    @pytest.mark.asyncio
    async def test_health_endpoint_needs_no_authentication(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. Auth flow across routers -- the same token/session honoured
#    identically everywhere it is presented
# ---------------------------------------------------------------------------


class TestAuthFlowAcrossRouters:
    @pytest.mark.asyncio
    async def test_token_from_register_authorises_analysis_start(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)

        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Infosys"},
            headers=_auth_headers(token),
        )
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_token_from_register_authorises_document_upload(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)

        with patch(
            "backend.services.documents._extract_text_from_pdf_bytes",
            return_value=_SAMPLE_TEXT,
        ):
            response = await client.post(
                "/api/v1/documents/upload",
                headers=_auth_headers(token),
                files={"file": ("report.pdf", _TINY_PDF_BYTES, "application/pdf")},
                data={"company_name": "Infosys"},
            )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_duplicate_registration_returns_409(
        self, client: httpx.AsyncClient
    ) -> None:
        await _register_and_login(client, email="dupe@example.com")

        second = await client.post(
            "/auth/register",
            json={"email": "dupe@example.com", "password": _VALID_PASSWORD},
        )
        assert second.status_code == 409

    @pytest.mark.asyncio
    async def test_login_with_wrong_password_returns_401(
        self, client: httpx.AsyncClient
    ) -> None:
        await _register_and_login(client, email="wrongpw@example.com")

        response = await client.post(
            "/auth/login",
            json={"email": "wrongpw@example.com", "password": "not-the-password"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_with_unknown_email_returns_401_not_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """
        Same response as a wrong password (see backend/routers/auth.py's
        module docstring) -- distinguishing "no such user" from "wrong
        password" would let a caller enumerate registered emails.
        """
        response = await client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": _VALID_PASSWORD},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_authorization_header_returns_401(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(
            "/auth/me", headers={"Authorization": "NotBearer abc123"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_garbage_token_rejected_by_every_protected_router(
        self, client: httpx.AsyncClient
    ) -> None:
        """
        One malformed token, asserted against THREE different routers
        in the same test -- the cross-router check no single per-router
        suite performs (each of them only owns one route).
        """
        headers = _auth_headers("this-is-not-a-real-jwt")

        me = await client.get("/auth/me", headers=headers)
        start = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "TCS"},
            headers=headers,
        )
        upload = await client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("x.pdf", _TINY_PDF_BYTES, "application/pdf")},
            data={"company_name": "TCS"},
        )

        assert me.status_code == 401
        assert start.status_code == 401
        assert upload.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_authorization_header_rejected_everywhere(
        self, client: httpx.AsyncClient
    ) -> None:
        me = await client.get("/auth/me")
        start = await client.post(
            "/api/v1/analysis/start", json={"company_name": "TCS"}
        )
        history = await client.get("/api/v1/analysis/history")

        assert me.status_code == 401
        assert start.status_code == 401
        assert history.status_code == 401

    @pytest.mark.asyncio
    async def test_one_users_token_cannot_read_another_users_job(
        self, client: httpx.AsyncClient, fake_session: _FakeFullSession
    ) -> None:
        """
        Two independent users in the SAME shared fake database -- user
        A's job is invisible to user B's token, across every job_id-
        scoped route (404, never a distinguishing 403 -- see analysis.py's
        module docstring on why both routes use the identical contract).
        """
        token_a, user_a_id = await _register_and_login(client, email="a@example.com")
        token_b, _user_b_id = await _register_and_login(client, email="b@example.com")

        start = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Wipro"},
            headers=_auth_headers(token_a),
        )
        job_id = uuid.UUID(start.json()["job_id"])
        _seed_result_row(
            fake_session, job_id, user_id=user_a_id, decision=_VALID_DECISION
        )

        status_as_b = await client.get(
            f"/api/v1/analysis/{job_id}/status", headers=_auth_headers(token_b)
        )
        result_as_b = await client.get(
            f"/api/v1/analysis/{job_id}/result", headers=_auth_headers(token_b)
        )

        assert status_as_b.status_code == 404
        assert result_as_b.status_code == 404


# ---------------------------------------------------------------------------
# 3. WebSocket across the same session -- proves the WS route honours
#    the identical token AND the identical Analysis row the HTTP routes
#    just created, not an isolated fixture of its own.
# ---------------------------------------------------------------------------


def _make_async_session_local_patch(fake_session: _FakeFullSession) -> Any:
    """Build a callable usable as backend.routers.websocket.
    AsyncSessionLocal, handing back the SAME _FakeFullSession the HTTP
    client in this test is also using -- see test_websocket_router.py's
    identical helper for why a plain async context manager wrapper is
    needed here."""

    class _FakeAsyncContextManager:
        async def __aenter__(self) -> _FakeFullSession:
            return fake_session

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    def _factory() -> _FakeAsyncContextManager:
        return _FakeAsyncContextManager()

    return _factory


@pytest.fixture
def ws_test_client(
    fake_session: _FakeFullSession, test_settings: Settings
) -> Generator[TestClient, None, None]:
    """
    A synchronous starlette TestClient wired to the SAME fake_session
    instance the async httpx fixture above uses, and with
    backend.routers.websocket.AsyncSessionLocal patched to return it --
    see test_websocket_router.py's module docstring for why WebSocket
    routes need TestClient rather than httpx.ASGITransport.
    """
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _make_session_override(fake_session)
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings

    with patch(
        "backend.routers.websocket.AsyncSessionLocal",
        new=_make_async_session_local_patch(fake_session),
    ):
        yield TestClient(app)


class TestWebSocketAcrossSession:
    def test_stream_reflects_the_same_job_just_created_over_http(
        self,
        ws_test_client: TestClient,
        fake_session: _FakeFullSession,
        test_settings: Settings,
    ) -> None:
        """
        Register + start an analysis via plain HTTP calls against the
        SAME TestClient (Starlette's TestClient supports both regular
        HTTP and WebSocket on one instance), then open the stream for
        that exact job_id and confirm the very first event names the
        real, just-created job as still pending -- proving the
        WebSocket route's ownership check
        (backend.services.analysis.get_analysis_status) is reading the
        identical row the HTTP route inserted, not a separately-mocked
        fixture.
        """
        register = ws_test_client.post(
            "/auth/register",
            json={"email": "wsflow@example.com", "password": _VALID_PASSWORD},
        )
        assert register.status_code == 201
        token = register.json()["access_token"]

        start = ws_test_client.post(
            "/api/v1/analysis/start",
            json={"company_name": "HDFC Bank"},
            headers=_auth_headers(token),
        )
        assert start.status_code == 202
        job_id = start.json()["job_id"]

        with ws_test_client.websocket_connect(
            f"/api/v1/analysis/{job_id}/stream?token={token}"
        ) as ws:
            first_event = ws.receive_json()

        assert first_event["job_id"] == job_id
        assert first_event["status"] == "pending"
        assert first_event["is_final"] is False

    def test_stream_closes_immediately_once_status_is_terminal(
        self,
        ws_test_client: TestClient,
        fake_session: _FakeFullSession,
    ) -> None:
        register = ws_test_client.post(
            "/auth/register",
            json={"email": "wsdone@example.com", "password": _VALID_PASSWORD},
        )
        token = register.json()["access_token"]
        user_id = uuid.UUID(register.json()["user"]["id"])

        start = ws_test_client.post(
            "/api/v1/analysis/start",
            json={"company_name": "ITC"},
            headers=_auth_headers(token),
        )
        job_id = uuid.UUID(start.json()["job_id"])

        _seed_status_row(
            fake_session,
            job_id,
            user_id=user_id,
            status="completed",
            last_completed_node="pdf_export",
        )

        with ws_test_client.websocket_connect(
            f"/api/v1/analysis/{job_id}/stream?token={token}"
        ) as ws:
            first_event = ws.receive_json()
            assert first_event["is_final"] is True
            # The server closes right after the terminal snapshot -- a
            # further receive must raise WebSocketDisconnect(1000), not
            # hang. Mirrors test_websocket_router.py's identical check.
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 1000

    def test_unauthenticated_stream_request_closes_with_4401(
        self, ws_test_client: TestClient
    ) -> None:
        job_id = uuid.uuid4()
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with ws_test_client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream"
            ) as ws:
                ws.receive_json()
        assert exc_info.value.code == 4401

    def test_someone_elses_job_id_closes_with_4404(
        self, ws_test_client: TestClient, fake_session: _FakeFullSession
    ) -> None:
        owner_register = ws_test_client.post(
            "/auth/register",
            json={"email": "owner@example.com", "password": _VALID_PASSWORD},
        )
        owner_id = uuid.UUID(owner_register.json()["user"]["id"])
        owner_token = owner_register.json()["access_token"]

        intruder_register = ws_test_client.post(
            "/auth/register",
            json={"email": "intruder@example.com", "password": _VALID_PASSWORD},
        )
        intruder_token = intruder_register.json()["access_token"]

        start = ws_test_client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Asian Paints"},
            headers=_auth_headers(owner_token),
        )
        job_id = start.json()["job_id"]
        # Sanity: the row really is owned by `owner_id`, not the intruder.
        assert fake_session.analyses[uuid.UUID(job_id)].user_id == owner_id

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with ws_test_client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token={intruder_token}"
            ) as ws:
                ws.receive_json()
        assert exc_info.value.code == 4404


# ---------------------------------------------------------------------------
# 4. Error cases -- invalid ticker/company input and rate-limit
#    degradation surfacing through the API, plus the remaining
#    cross-cutting HTTP error paths.
# ---------------------------------------------------------------------------


class TestErrorCases:
    """
    "Invalid ticker" in AIRP's actual design (see
    backend.services.analysis.resolve_company's docstring) is NOT a
    rejection -- resolve_company is a pure, total function with a
    final "treat it as a bare ticker symbol" fallback, so there is no
    string POST /analysis/start can be given that resolve_company
    itself refuses. The real "invalid ticker" boundary is therefore
    INPUT validation (AnalysisStartRequest's Pydantic constraints,
    enforced before resolve_company ever runs) -- a blank/whitespace
    company_name, or an out-of-range exchange override. This class
    tests that boundary precisely, rather than asserting a rejection
    resolve_company was never designed to perform.

    "Rate limits" maps to backend.tools.news's documented
    rate_limit_exhausted degrade-to-dict contract (agents never raise
    -- see the "Architecture patterns" project convention): a pipeline
    that hit NewsAPI's quota still completes and returns 200/202
    throughout, with the degradation recorded INSIDE the memo content,
    not as an HTTP failure. TestRateLimitDegradation proves the API
    surface honours that contract rather than inventing a 429 the
    real pipeline never raises.
    """

    @pytest.mark.asyncio
    async def test_blank_company_name_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "   "},
            headers=_auth_headers(token),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_company_name_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        response = await client.post(
            "/api/v1/analysis/start",
            json={},
            headers=_auth_headers(token),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_out_of_range_exchange_override_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "TCS", "exchange": "NYSE"},
            headers=_auth_headers(token),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unrecognised_free_text_still_resolves_rather_than_erroring(
        self, client: httpx.AsyncClient
    ) -> None:
        """
        A company name with no entry in AIRP's lookup table is not
        rejected -- resolve_company's final fallback treats it as a
        bare ticker symbol. POST /analysis/start returns 202 for ANY
        non-blank company_name; whether the resulting ticker is a real,
        tradeable NSE/BSE symbol is something only the (separately
        mocked-out) LangGraph pipeline's own yFinance call could ever
        determine, well after this endpoint has already responded.
        """
        token, _ = await _register_and_login(client)
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "ThisIsNotARealCompanyXYZ123"},
            headers=_auth_headers(token),
        )
        assert response.status_code == 202
        assert response.json()["ticker"] == "THISISNOTAREALCOMPANYXYZ123.NS"

    @pytest.mark.asyncio
    async def test_nonexistent_job_id_returns_404_for_status_result_and_pdf(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        headers = _auth_headers(token)
        unknown_job_id = uuid.uuid4()

        status_response = await client.get(
            f"/api/v1/analysis/{unknown_job_id}/status", headers=headers
        )
        result_response = await client.get(
            f"/api/v1/analysis/{unknown_job_id}/result", headers=headers
        )
        pdf_response = await client.get(
            f"/api/v1/analysis/{unknown_job_id}/memo/pdf", headers=headers
        )

        assert status_response.status_code == 404
        assert result_response.status_code == 404
        assert pdf_response.status_code == 404

    @pytest.mark.asyncio
    async def test_malformed_job_id_returns_422_not_500(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        response = await client.get(
            "/api/v1/analysis/not-a-valid-uuid/status",
            headers=_auth_headers(token),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_result_for_a_still_pending_job_returns_409(
        self, client: httpx.AsyncClient
    ) -> None:
        token, user_id = await _register_and_login(client)
        start = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Bajaj Finance"},
            headers=_auth_headers(token),
        )
        job_id = start.json()["job_id"]

        response = await client.get(
            f"/api/v1/analysis/{job_id}/result", headers=_auth_headers(token)
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_oversized_document_upload_returns_413(
        self, fake_session: _FakeFullSession, test_settings: Settings
    ) -> None:
        """
        Tightens max_upload_size_mb to 1 for this test only (mirroring
        test_documents_router.py's TestUploadDocumentOversizedFile) so
        a 2MB payload is enough to trip PDFTooLargeError -- avoids
        allocating a wastefully large (21MB+) byte string just to
        exceed test_settings' default 20MB limit.
        """
        tight_settings = test_settings.model_copy(update={"max_upload_size_mb": 1})

        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: tight_settings

        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            register = await ac.post(
                "/auth/register",
                json={"email": "oversized@example.com", "password": _VALID_PASSWORD},
            )
            token = register.json()["access_token"]

            oversized = b"x" * (2 * 1024 * 1024)
            response = await ac.post(
                "/api/v1/documents/upload",
                headers=_auth_headers(token),
                files={"file": ("huge.pdf", oversized, "application/pdf")},
                data={"company_name": "TCS"},
            )
        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_blank_company_name_on_upload_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        response = await client.post(
            "/api/v1/documents/upload",
            headers=_auth_headers(token),
            files={"file": ("report.pdf", _TINY_PDF_BYTES, "application/pdf")},
            data={"company_name": "   "},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unsupported_content_type_upload_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        response = await client.post(
            "/api/v1/documents/upload",
            headers=_auth_headers(token),
            files={"file": ("notes.txt", b"plain text content", "text/plain")},
            data={"company_name": "TCS"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_corrupt_pdf_upload_returns_400(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        with patch(
            "backend.services.documents._extract_text_from_pdf_bytes",
            side_effect=PDFExtractionError("could not parse PDF structure"),
        ):
            response = await client.post(
                "/api/v1/documents/upload",
                headers=_auth_headers(token),
                files={"file": ("corrupt.pdf", b"not really a pdf", "application/pdf")},
                data={"company_name": "TCS"},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_method_not_allowed_on_analysis_start_returns_405(
        self, client: httpx.AsyncClient
    ) -> None:
        token, _ = await _register_and_login(client)
        response = await client.get(
            "/api/v1/analysis/start", headers=_auth_headers(token)
        )
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_unknown_route_returns_404(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/this-route-does-not-exist")
        assert response.status_code == 404


class TestRateLimitDegradation:
    """
    Proves the API surface honours backend.tools.news's documented
    "agents never raise" contract: an analysis whose News Sentiment
    Agent hit NewsAPI's daily quota still reaches status='completed'
    and a 200 response from every read endpoint -- the rate-limit
    signal lives inside the memo content (risk_summary / key_risks),
    never as an HTTP error code the real pipeline has no mechanism to
    raise in the first place.
    """

    @pytest.mark.asyncio
    async def test_rate_limited_analysis_still_returns_200_with_degraded_content(
        self, client: httpx.AsyncClient, fake_session: _FakeFullSession
    ) -> None:
        token, user_id = await _register_and_login(client)
        start = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Reliance Industries"},
            headers=_auth_headers(token),
        )
        job_id = uuid.UUID(start.json()["job_id"])

        _seed_status_row(
            fake_session,
            job_id,
            user_id=user_id,
            status="completed",
            last_completed_node="pdf_export",
        )
        _seed_result_row(
            fake_session, job_id, user_id=user_id, decision=_RATE_LIMITED_DECISION
        )

        status_response = await client.get(
            f"/api/v1/analysis/{job_id}/status", headers=_auth_headers(token)
        )
        result_response = await client.get(
            f"/api/v1/analysis/{job_id}/result", headers=_auth_headers(token)
        )

        assert status_response.status_code == 200
        assert status_response.json()["status"] == "completed"
        assert result_response.status_code == 200
        result_body = result_response.json()
        assert result_body["verdict"] == "HOLD"
        assert "rate_limit_exhausted" in " ".join(result_body["key_risks"])
        assert "rate limit exhausted" in result_body["risk_summary"]
