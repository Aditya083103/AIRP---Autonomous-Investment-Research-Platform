# backend/tests/unit/test_analysis_result_history_router.py
"""
Unit tests for T-050: backend/routers/analysis.py's three new endpoints
  GET /api/v1/analysis/{job_id}/result
  GET /api/v1/analysis/{job_id}/memo/pdf
  GET /api/v1/analysis/history

A separate file from test_analysis_router.py (T-047/T-048) -- T-050 is
its own task with its own acceptance criteria and its own fake-session
surface (a new raw text() query for /result, two more for /history,
plus real on-disk PDF files for /memo/pdf), mirroring the precedent
test_websocket_router.py already set for T-049 rather than further
growing the T-047/T-048 file.

Acceptance criteria verified (from task spec):
  * PDF downloads correctly             -- TestDownloadPdfSuccess
  * result JSON matches InvestmentDecision
    schema                              -- TestGetResultSuccess
  * history paginates                   -- TestHistoryPagination

End-to-end HTTP tests against the real FastAPI app (httpx.ASGITransport,
same pattern as test_analysis_router.py / test_websocket_router.py)
with:
  * get_async_session overridden to a small in-memory fake session
    (_FakeResultHistorySession) that serves three distinct raw text()
    queries by inspecting each TextClause's own SQL text -- there are
    now three different text() queries this router can issue
    (_SQL_LOAD_RESULT, _SQL_COUNT_HISTORY, _SQL_LOAD_HISTORY_PAGE) in
    addition to T-048's _SQL_LOAD_STATUS, so unlike
    test_analysis_router.py's single status_overrides dict, this fake
    branches on a short, distinguishing substring of statement.text
    for each one.
  * get_current_user overridden to a fixed User instance, identical to
    test_analysis_router.py's approach -- this file is not re-testing
    JWT verification.
  * GET /memo/pdf is tested against REAL files written to a pytest
    tmp_path and backend.routers.analysis.resolve_memo_pdf_path
    monkeypatched to resolve into that tmp_path -- FileResponse reads
    an actual file from disk, so a fake/mocked filesystem would not
    exercise the real code path FileResponse takes.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
import uuid

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy.sql.elements import TextClause

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import User

# ---------------------------------------------------------------------------
# Fixed test data
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fake in-memory AsyncSession -- supports the three new raw text()
# queries T-050 introduces, distinguished by a substring of each
# TextClause's own SQL text.
# ---------------------------------------------------------------------------


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


class _FakeResultHistorySession:
    """
    In-memory fake of AsyncSession supporting exactly the three new
    raw text() queries backend.services.analysis introduces in T-050:
    _SQL_LOAD_RESULT (GET /result), _SQL_COUNT_HISTORY and
    _SQL_LOAD_HISTORY_PAGE (GET /history). get_analysis_status's
    existing _SQL_LOAD_STATUS (T-048, reused as-is by GET /memo/pdf's
    ownership check) is also supported, identical in shape to
    test_analysis_router.py's status_overrides.

    Branches on a short, distinguishing substring of each TextClause's
    own compiled SQL text (``statement.text``) rather than parameter
    shape, since three of these four queries take only {"job_id": ...}
    or {"user_id": ...} -- a single shared dict shape could not tell
    them apart on its own.
    """

    def __init__(self) -> None:
        self.status_overrides: dict[uuid.UUID, tuple[Any, ...]] = {}
        self.result_overrides: dict[uuid.UUID, tuple[Any, ...]] = {}
        self.history_rows: dict[uuid.UUID, list[tuple[Any, ...]]] = {}

    async def execute(self, statement: Any, params: Any = None) -> Any:
        assert isinstance(statement, TextClause), (
            "T-050's router issues only raw text() queries against "
            "the analyses/companies tables -- no ORM Select."
        )
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

        # Falls through to T-048's status query (_SQL_LOAD_STATUS),
        # reused as-is by GET /memo/pdf's ownership/existence check.
        job_id = uuid.UUID(str(params["job_id"]))
        row = self.status_overrides.get(job_id)
        return _FakeRowResult(row)


def _make_session_override(shared: _FakeResultHistorySession) -> Any:
    """Zero-argument async generator function -- see
    test_auth_router.py's docstring for why a bare lambda does not work
    as a dependency_overrides value for an async-generator dependency."""

    async def _override() -> AsyncGenerator[_FakeResultHistorySession, None]:
        yield shared

    return _override


def _seed_status_row(
    fake_session: _FakeResultHistorySession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "completed",
    last_completed_node: Any = "pdf_export",
    error_message: Any = None,
    requested_at: Any = None,
    started_at: Any = None,
    completed_at: Any = None,
) -> None:
    """Populate status_overrides with the exact 7-tuple shape
    get_analysis_status reads via row[0]..row[6]."""
    fake_session.status_overrides[job_id] = (
        user_id,
        status,
        last_completed_node,
        error_message,
        requested_at,
        started_at,
        completed_at,
    )


def _seed_result_row(
    fake_session: _FakeResultHistorySession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "completed",
    decision: dict[str, Any] | None = None,
) -> None:
    """Populate result_overrides with the exact 3-tuple shape
    get_analysis_result reads via row[0]..row[2]. ``decision=None`` with
    status='completed' simulates a state_snapshot with no decision key
    (the defensive/should-never-happen branch); pass an explicit dict
    (or _VALID_DECISION) to simulate a real, populated snapshot."""
    snapshot = {"decision": decision} if decision is not None else None
    fake_session.result_overrides[job_id] = (user_id, status, snapshot)


def _seed_history_row(
    fake_session: _FakeResultHistorySession,
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
    get_analysis_history reads via row[0]..row[8]. Rows are returned in
    insertion order by the fake -- tests that care about ordering seed
    rows newest-first themselves, since the fake does not re-sort (the
    real SQL's ORDER BY requested_at DESC is not re-implemented here;
    tests assert on CONTENTS and PAGINATION, not on the fake re-deriving
    order the production query already guarantees)."""
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session() -> _FakeResultHistorySession:
    return _FakeResultHistorySession()


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="analyst@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@pytest.fixture
async def client(
    fake_session: _FakeResultHistorySession,
    current_user: User,
    test_settings: Settings,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _make_session_override(fake_session)
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: current_user

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/result
# ---------------------------------------------------------------------------


class TestGetResultNotFound:
    @pytest.mark.asyncio
    async def test_unknown_job_id_returns_404(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/v1/analysis/{uuid.uuid4()}/result")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_malformed_job_id_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/analysis/not-a-uuid/result")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_job_belonging_to_a_different_user_returns_404(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session,
            job_id,
            user_id=uuid.uuid4(),
            decision=_VALID_DECISION,
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        fake_session: _FakeResultHistorySession,
        test_settings: Settings,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/{uuid.uuid4()}/result")
        assert response.status_code == 401


class TestGetResultNotReady:
    @pytest.mark.asyncio
    async def test_pending_job_returns_409(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, status="pending"
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_running_job_returns_409(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, status="running"
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_failed_job_returns_409(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(fake_session, job_id, user_id=current_user.id, status="failed")

        response = await client.get(f"/api/v1/analysis/{job_id}/result")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_409_detail_names_the_actual_status(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, status="running"
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")

        assert "running" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_completed_but_no_decision_in_snapshot_returns_409(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        """status='completed' but the snapshot has no decision key at
        all -- get_analysis_result's defensive fallback (should never
        happen given portfolio_manager_node's contract, which always
        writes status='completed' and state["decision"] in the same
        return dict) treats this identically to "not ready yet" and
        raises AnalysisNotReadyError, which the router maps to 409 --
        not the malformed-decision 500 path, which requires a snapshot
        that HAS a 'decision' key with required fields missing (see
        test_missing_required_field_returns_500 below)."""
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, status="completed"
        )
        # decision=None above means result_overrides stores a None
        # snapshot entirely -- get_analysis_result treats a
        # completed-but-snapshot-less row as AnalysisNotReadyError.
        response = await client.get(f"/api/v1/analysis/{job_id}/result")
        assert response.status_code == 409


class TestGetResultSuccess:
    @pytest.mark.asyncio
    async def test_returns_200_for_owning_user(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, decision=_VALID_DECISION
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_matches_investment_decision_schema_fields(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        """Acceptance criterion: 'result JSON matches InvestmentDecision
        schema' -- every field InvestmentDecision/InvestmentDecisionResponse
        declares must round-trip through the HTTP response untouched."""
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, decision=_VALID_DECISION
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")
        body = response.json()

        expected_fields = {
            "agent_name",
            "analysis_id",
            "company_name",
            "ticker",
            "generated_at",
            "error",
            "verdict",
            "conviction_score",
            "price_target",
            "time_horizon",
            "executive_summary",
            "investment_thesis",
            "bull_case",
            "bear_case",
            "risk_summary",
            "valuation_summary",
            "key_risks",
            "key_catalysts",
            "contrarian_response",
            "debate_rounds_used",
            "agent_weights",
            "summary",
        }
        assert expected_fields.issubset(body.keys())

    @pytest.mark.asyncio
    async def test_verdict_matches_seeded_decision(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, decision=_VALID_DECISION
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")
        body = response.json()

        assert body["verdict"] == "BUY"
        assert body["conviction_score"] == 8

    @pytest.mark.asyncio
    async def test_key_risks_list_preserved(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, decision=_VALID_DECISION
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")
        body = response.json()

        assert body["key_risks"] == ["Client concentration", "Wage inflation"]

    @pytest.mark.asyncio
    async def test_agent_weights_dict_preserved(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, decision=_VALID_DECISION
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")
        body = response.json()

        assert body["agent_weights"]["fundamental_analyst"] == 0.3

    @pytest.mark.asyncio
    async def test_missing_optional_fields_default_sensibly(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        """A decision dict missing every optional field (only the three
        truly-required ones present) must still produce a 200 with
        sensible defaults -- mirrors InvestmentDecision's own Pydantic
        defaults for these fields."""
        job_id = uuid.uuid4()
        minimal_decision = {
            "generated_at": "2026-06-20 10:30:00",
            "verdict": "HOLD",
            "conviction_score": 5,
        }
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, decision=minimal_decision
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")
        body = response.json()

        assert response.status_code == 200
        assert body["verdict"] == "HOLD"
        assert body["key_risks"] == []
        assert body["agent_weights"] == {}
        assert body["price_target"] is None

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_500(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        """A status='completed' snapshot whose decision dict is missing
        a truly-required field (verdict) -- the router's defensive
        KeyError handler, not InvestmentDecisionResponse's own
        validation (which would otherwise produce an unhandled 500 with
        an unhelpful traceback)."""
        job_id = uuid.uuid4()
        malformed_decision = {
            "generated_at": "2026-06-20 10:30:00",
            "conviction_score": 5,
            # 'verdict' missing entirely.
        }
        _seed_result_row(
            fake_session, job_id, user_id=current_user.id, decision=malformed_decision
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/result")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/memo/pdf
# ---------------------------------------------------------------------------


class TestDownloadPdfNotFound:
    @pytest.mark.asyncio
    async def test_unknown_job_id_returns_404(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/v1/analysis/{uuid.uuid4()}/memo/pdf")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_job_belonging_to_a_different_user_returns_404(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_status_row(fake_session, job_id, user_id=uuid.uuid4())

        response = await client.get(f"/api/v1/analysis/{job_id}/memo/pdf")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        fake_session: _FakeResultHistorySession,
        test_settings: Settings,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/{uuid.uuid4()}/memo/pdf")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_owned_job_with_no_pdf_on_disk_returns_404(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The analyses row exists and is owned by the caller (even
        status='completed'), but no PDF file exists at the resolved
        path -- T-043's pdf_export_node can legitimately degrade to
        memo_pdf_path=None (WeasyPrint unavailable, feature flag off,
        rendering failure) without failing the pipeline."""
        import backend.routers.analysis as analysis_router_module

        job_id = uuid.uuid4()
        _seed_status_row(fake_session, job_id, user_id=current_user.id)

        monkeypatch.setattr(
            analysis_router_module,
            "resolve_memo_pdf_path",
            lambda jid: tmp_path / f"{jid}.pdf",
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/memo/pdf")

        assert response.status_code == 404


class TestDownloadPdfSuccess:
    @pytest.mark.asyncio
    async def test_downloads_correctly(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Acceptance criterion: 'PDF downloads correctly' -- a real
        PDF-shaped file written to disk is served back byte-for-byte
        with the correct content type."""
        import backend.routers.analysis as analysis_router_module

        job_id = uuid.uuid4()
        _seed_status_row(fake_session, job_id, user_id=current_user.id)

        pdf_bytes = b"%PDF-1.4 fake-but-byte-identical-content\n%%EOF"
        pdf_path = tmp_path / f"{job_id}.pdf"
        pdf_path.write_bytes(pdf_bytes)

        monkeypatch.setattr(
            analysis_router_module,
            "resolve_memo_pdf_path",
            lambda jid: tmp_path / f"{jid}.pdf",
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/memo/pdf")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == pdf_bytes

    @pytest.mark.asyncio
    async def test_content_disposition_suggests_a_filename(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import backend.routers.analysis as analysis_router_module

        job_id = uuid.uuid4()
        _seed_status_row(fake_session, job_id, user_id=current_user.id)

        pdf_path = tmp_path / f"{job_id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")

        monkeypatch.setattr(
            analysis_router_module,
            "resolve_memo_pdf_path",
            lambda jid: tmp_path / f"{jid}.pdf",
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/memo/pdf")

        content_disposition = response.headers["content-disposition"]
        assert "attachment" in content_disposition
        assert str(job_id) in content_disposition

    @pytest.mark.asyncio
    async def test_pending_job_with_no_pdf_yet_returns_404_not_500(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A still-running analysis has no PDF yet -- this must be a
        plain 404 (covered by TestDownloadPdfNotFound's identical
        no-file-on-disk case), not a 409 like GET /result uses for the
        same lifecycle state. GET /memo/pdf has only one failure mode
        for 'not ready', deliberately simpler than GET /result's
        ready/not-ready distinction, since the PDF either exists on
        disk right now or it does not."""
        import backend.routers.analysis as analysis_router_module

        job_id = uuid.uuid4()
        _seed_status_row(
            fake_session, job_id, user_id=current_user.id, status="running"
        )

        monkeypatch.setattr(
            analysis_router_module,
            "resolve_memo_pdf_path",
            lambda jid: tmp_path / f"{jid}.pdf",
        )

        response = await client.get(f"/api/v1/analysis/{job_id}/memo/pdf")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/history
# ---------------------------------------------------------------------------


class TestHistoryEmpty:
    @pytest.mark.asyncio
    async def test_no_analyses_returns_empty_page(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/analysis/history")
        body = response.json()

        assert response.status_code == 200
        assert body["items"] == []
        assert body["total_count"] == 0
        assert body["has_more"] is False

    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        fake_session: _FakeResultHistorySession,
        test_settings: Settings,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get("/api/v1/analysis/history")
        assert response.status_code == 401


class TestHistoryDefaults:
    @pytest.mark.asyncio
    async def test_default_limit_is_twenty(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        """Acceptance criterion's own wording: 'user's past 20
        analyses' -- the default page size with no limit/offset
        supplied must be exactly 20."""
        for _ in range(25):
            _seed_history_row(
                fake_session, user_id=current_user.id, job_id=uuid.uuid4()
            )

        response = await client.get("/api/v1/analysis/history")
        body = response.json()

        assert body["limit"] == 20
        assert len(body["items"]) == 20
        assert body["total_count"] == 25
        assert body["has_more"] is True

    @pytest.mark.asyncio
    async def test_default_offset_is_zero(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        _seed_history_row(fake_session, user_id=current_user.id, job_id=uuid.uuid4())

        response = await client.get("/api/v1/analysis/history")

        assert response.json()["offset"] == 0


class TestHistoryPagination:
    @pytest.mark.asyncio
    async def test_second_page_returns_remaining_rows(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        """Acceptance criterion: 'history paginates' -- two consecutive
        pages cover the full set with no overlap and no gap."""
        job_ids = [uuid.uuid4() for _ in range(5)]
        for jid in job_ids:
            _seed_history_row(fake_session, user_id=current_user.id, job_id=jid)

        first_page = await client.get(
            "/api/v1/analysis/history", params={"limit": 3, "offset": 0}
        )
        second_page = await client.get(
            "/api/v1/analysis/history", params={"limit": 3, "offset": 3}
        )

        assert len(first_page.json()["items"]) == 3
        assert len(second_page.json()["items"]) == 2
        assert second_page.json()["has_more"] is False

    @pytest.mark.asyncio
    async def test_offset_beyond_total_count_returns_empty_items(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        _seed_history_row(fake_session, user_id=current_user.id, job_id=uuid.uuid4())

        response = await client.get("/api/v1/analysis/history", params={"offset": 100})
        body = response.json()

        assert body["items"] == []
        assert body["total_count"] == 1
        assert body["has_more"] is False

    @pytest.mark.asyncio
    async def test_limit_above_maximum_is_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/analysis/history", params={"limit": 9999})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_below_one_is_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/analysis/history", params={"limit": 0})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_offset_is_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/analysis/history", params={"offset": -1})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_never_returns_another_users_analyses(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        someone_elses_user_id = uuid.uuid4()
        _seed_history_row(
            fake_session, user_id=someone_elses_user_id, job_id=uuid.uuid4()
        )

        response = await client.get("/api/v1/analysis/history")
        body = response.json()

        assert body["items"] == []
        assert body["total_count"] == 0


class TestHistoryEntryShape:
    @pytest.mark.asyncio
    async def test_entry_includes_company_and_verdict(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_history_row(
            fake_session,
            user_id=current_user.id,
            job_id=job_id,
            company_name="Infosys Limited",
            ticker_yf="INFY.NS",
            exchange="NSE",
            verdict="HOLD",
            conviction_score="6",
        )

        response = await client.get("/api/v1/analysis/history")
        entry = response.json()["items"][0]

        assert entry["job_id"] == str(job_id)
        assert entry["company_name"] == "Infosys Limited"
        assert entry["ticker"] == "INFY.NS"
        assert entry["verdict"] == "HOLD"
        assert entry["conviction_score"] == 6

    @pytest.mark.asyncio
    async def test_pending_entry_has_null_verdict_and_conviction(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeResultHistorySession,
        current_user: User,
    ) -> None:
        """A pending/running analysis row -- the JSONB ->> extraction
        in the real SQL yields NULL for both columns; the fake mirrors
        that by passing through whatever the test seeds, here None."""
        job_id = uuid.uuid4()
        _seed_history_row(
            fake_session,
            user_id=current_user.id,
            job_id=job_id,
            status="pending",
            verdict=None,
            conviction_score=None,
        )

        response = await client.get("/api/v1/analysis/history")
        entry = response.json()["items"][0]

        assert entry["status"] == "pending"
        assert entry["verdict"] is None
        assert entry["conviction_score"] is None
