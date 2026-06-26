# backend/tests/unit/test_documents_router.py
"""
Unit tests for T-051: backend/routers/documents.py

End-to-end HTTP tests against the real FastAPI app (httpx.ASGITransport,
same pattern as test_analysis_router.py / test_auth_router.py), with:
  * get_async_session overridden to a small in-memory fake session that
    genuinely tracks inserted Company rows -- the SAME
    _FakeAnalysisSession-style fake test_analysis_router.py already
    uses for backend.services.analysis's identical
    resolve_company/get_or_create_company pair, since
    backend.services.documents.link_document_to_company calls into
    that exact same function.
  * get_current_user overridden to a fixed User -- this file is not
    re-testing JWT verification (T-046's job, covered elsewhere); it
    only needs *an* authenticated caller.
  * backend.services.documents.build_chroma_client patched (module-
    level monkeypatch, autouse for this file) to return a ChromaClient
    backed by an in-memory EphemeralClient (test_chroma_client.py's own
    _MockEF pattern) instead of a real embedding model + ChromaDB
    instance -- this is the SAME function the router's only call
    target (ingest_uploaded_document) falls back to when no chroma
    argument is supplied, and the router never supplies one, so
    patching it here is what keeps these HTTP tests offline and fast.
  * backend.tools.earnings_transcript._extract_text_from_pdf_bytes
    patched per-test (not autouse -- some tests need different
    return_value/side_effect) so no real pdfminer/PyPDF2 call happens;
    patched at backend.services.documents._extract_text_from_pdf_bytes,
    the name bound into the SERVICE module's namespace that actually
    calls it, per unittest.mock's "patch where it's looked up" rule.

Acceptance criteria verified (from task spec):
  * PDF uploads                        -- TestUploadDocumentSuccess
  * text extracted                     -- TestUploadDocumentSuccess
  * embedded in ChromaDB               -- TestUploadDocumentSuccess
  * queryable by agents in subsequent
    analyses                           -- TestUploadDocumentSuccess::
                                           test_uploaded_document_is_
                                           queryable_via_semantic_search
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import MagicMock, patch
import uuid

import chromadb
from chromadb.config import Settings as _ChromaSettings
from fastapi import FastAPI
import httpx
import pytest

from backend.config import Settings
from backend.db.chroma_client import COLLECTION_DOCUMENTS, ChromaClient, semantic_search
from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import Company, User
from backend.tools.earnings_transcript import PDFExtractionError

_SAMPLE_TEXT = (
    "Tata Consultancy Services Limited Annual Report FY2024. "
    "Revenue grew 12% year on year to Rs 240,893 crore. "
    "The board recommends a final dividend of Rs 28 per equity share. "
) * 5

_TINY_PDF_BYTES = b"%PDF-1.4 fake pdf content for testing\n%%EOF"


# ---------------------------------------------------------------------------
# Fake in-memory AsyncSession -- supports exactly the Company
# select/insert backend.services.documents.link_document_to_company
# performs (via backend.services.analysis.get_or_create_company under
# the hood). Mirrors test_analysis_router.py's _FakeAnalysisSession.
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for SQLAlchemy's Result object."""

    def __init__(self, value: Company | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Company | None:
        return self._value


class _FakeDocumentsSession:
    """
    Tiny in-memory fake of AsyncSession supporting exactly
    execute(select(Company).where(...)), add(), commit(), refresh() --
    the only operations backend.services.analysis.get_or_create_company
    performs. Not a SQL engine -- inspects the compiled statement's
    bound parameter VALUES to find a matching Company row, identical
    approach to test_analysis_router.py's _FakeAnalysisSession (see
    that file's docstring for why values, not bind-parameter names,
    are matched against).
    """

    def __init__(self) -> None:
        self.companies: dict[uuid.UUID, Company] = {}
        self._pending: list[Any] = []

    async def execute(self, statement: Any, params: Any = None) -> Any:
        compiled = statement.compile(compile_kwargs={"literal_binds": False})
        bound_values = set(compiled.params.values())

        if not bound_values:
            return _FakeResult(None)

        for company in self.companies.values():
            if company.ticker in bound_values and company.exchange in bound_values:
                return _FakeResult(company)
        return _FakeResult(None)

    def add(self, instance: Any) -> None:
        self._pending.append(instance)

    async def commit(self) -> None:
        for instance in self._pending:
            if isinstance(instance, Company):
                if instance.id is None:
                    instance.id = uuid.uuid4()
                self.companies[instance.id] = instance
        self._pending.clear()

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, instance: Any) -> None:
        return None


def _make_session_override(shared: _FakeDocumentsSession) -> Any:
    """Build a zero-argument async generator function -- see
    test_auth_router.py's docstring for why a bare lambda does not work
    as a dependency_overrides value for an async-generator dependency."""

    async def _override() -> AsyncGenerator[_FakeDocumentsSession, None]:
        yield shared

    return _override


# ---------------------------------------------------------------------------
# Shared ChromaDB test infrastructure -- mirrors test_chroma_client.py's
# _MockEF / shared EphemeralClient pattern.
# ---------------------------------------------------------------------------


class _MockEF:
    """Fake embedding function satisfying ChromaDB's __call__ signature
    check, without loading any real sentence-transformer model."""

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [[0.1] * 384 for _ in input]


_TEST_CHROMA_SETTINGS = _ChromaSettings(
    is_persistent=False,
    allow_reset=True,
    anonymized_telemetry=False,
)

_SHARED_RAW_CLIENT: Any = chromadb.EphemeralClient(settings=_TEST_CHROMA_SETTINGS)


def _make_chroma_client() -> ChromaClient:
    _SHARED_RAW_CLIENT.reset()
    return ChromaClient(_SHARED_RAW_CLIENT, _MockEF())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session() -> _FakeDocumentsSession:
    return _FakeDocumentsSession()


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="analyst@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@pytest.fixture(autouse=True)
def patched_chroma(monkeypatch: pytest.MonkeyPatch) -> ChromaClient:
    """
    Replace backend.services.documents.build_chroma_client with one
    returning an in-memory EphemeralClient-backed ChromaClient, for
    every test in this module. Without this, the real
    sentence-transformer embedding model would be loaded (and a real
    ChromaDB instance touched) on every upload request -- far too
    heavy and slow for a unit test, exactly the same rationale
    test_analysis_router.py's patched_pipeline fixture documents for
    run_analysis_pipeline.
    """
    import backend.services.documents as documents_service_module

    client = _make_chroma_client()
    monkeypatch.setattr(documents_service_module, "build_chroma_client", lambda: client)
    return client


@pytest.fixture
async def client(
    fake_session: _FakeDocumentsSession,
    current_user: User,
    test_settings: Settings,
    patched_chroma: ChromaClient,
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


def _pdf_files(filename: str = "report.pdf") -> dict[str, Any]:
    """Build the httpx ``files=`` dict for a multipart PDF upload."""
    return {"file": (filename, _TINY_PDF_BYTES, "application/pdf")}


# ---------------------------------------------------------------------------
# POST /api/v1/documents/upload -- happy path
# ---------------------------------------------------------------------------


class TestUploadDocumentSuccess:
    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_returns_201(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
            data={"company_name": "Tata Consultancy Services"},
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_response_includes_resolved_ticker(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
            data={"company_name": "Tata Consultancy Services"},
        )
        body = response.json()
        assert body["ticker"] == "TCS.NS"
        assert body["exchange"] == "NSE"

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_response_reports_extracted_characters(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
            data={"company_name": "TCS"},
        )
        assert response.json()["characters_extracted"] == len(_SAMPLE_TEXT)

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_response_reports_chunks_ingested(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
            data={"company_name": "TCS"},
        )
        assert response.json()["chunks_ingested"] > 0

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_source_filename_is_preserved(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(filename="TCS_Annual_Report_FY24.pdf"),
            data={"company_name": "TCS"},
        )
        assert response.json()["source_filename"] == "TCS_Annual_Report_FY24.pdf"

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_explicit_ticker_and_exchange_overrides_are_respected(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
            data={
                "company_name": "Some Co",
                "ticker": "SOMECO",
                "exchange": "BSE",
            },
        )
        body = response.json()
        assert body["ticker"] == "SOMECO.BO"
        assert body["exchange"] == "BSE"

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_application_octet_stream_content_type_is_accepted(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _TINY_PDF_BYTES, "application/octet-stream")},
            data={"company_name": "TCS"},
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_uploaded_document_is_queryable_via_semantic_search(
        self,
        mock_extract: MagicMock,
        client: httpx.AsyncClient,
        patched_chroma: ChromaClient,
    ) -> None:
        """
        Acceptance criterion: "queryable by agents in subsequent
        analyses". After a successful upload via the real HTTP route,
        calls semantic_search directly against the SAME ChromaClient
        instance the route just wrote into (patched_chroma) and
        confirms the ingested content comes back.
        """
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
            data={"company_name": "Tata Consultancy Services"},
        )
        assert response.status_code == 201

        results = semantic_search(
            "dividend revenue",
            collection_name=COLLECTION_DOCUMENTS,
            company_filter="Tata Consultancy Services",
            chroma=patched_chroma,
        )
        assert len(results) > 0

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_requires_authentication(
        self,
        mock_extract: MagicMock,
        fake_session: _FakeDocumentsSession,
        test_settings: Settings,
        patched_chroma: ChromaClient,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        # Deliberately NOT overriding get_current_user here.
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.post(
                "/api/v1/documents/upload",
                files=_pdf_files(),
                data={"company_name": "TCS"},
            )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/documents/upload -- validation
# ---------------------------------------------------------------------------


class TestUploadDocumentValidation:
    @pytest.mark.asyncio
    async def test_missing_company_name_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_blank_company_name_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(),
            data={"company_name": "   "},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_file_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            data={"company_name": "TCS"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unsupported_content_type_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("notes.txt", b"plain text content", "text/plain")},
            data={"company_name": "TCS"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_file_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("empty.pdf", b"", "application/pdf")},
            data={"company_name": "TCS"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/documents/upload -- error translation from the service layer
# ---------------------------------------------------------------------------


class TestUploadDocumentErrorTranslation:
    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value="",
    )
    async def test_empty_text_pdf_returns_422(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(filename="scanned.pdf"),
            data={"company_name": "TCS"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        side_effect=PDFExtractionError("pdfminer broken"),
    )
    async def test_malformed_pdf_returns_400(
        self, mock_extract: MagicMock, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files=_pdf_files(filename="corrupt.pdf"),
            data={"company_name": "TCS"},
        )
        assert response.status_code == 400


class TestUploadDocumentOversizedFile:
    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_oversized_pdf_returns_413(
        self,
        mock_extract: MagicMock,
        fake_session: _FakeDocumentsSession,
        current_user: User,
        patched_chroma: ChromaClient,
    ) -> None:
        tight_settings = Settings.model_construct(
            environment="test",
            log_level="DEBUG",
            llm_provider="groq",
            groq_api_key="gsk_test-groq-key-for-unit-tests",
            groq_model="llama-3.3-70b-versatile",
            anthropic_api_key="sk-ant-test-key-for-unit-tests",
            anthropic_model="claude-haiku-4-5-20251001",
            anthropic_max_tokens=4096,
            langsmith_api_key="",
            langchain_tracing_v2="false",
            langchain_project="airp-test",
            langchain_endpoint="https://api.smith.langchain.com",
            database_url="postgresql+asyncpg://airp:airp@localhost:5432/airp",
            database_test_url=(
                "postgresql+asyncpg://airp:airp@localhost:5432/airp_test"
            ),
            db_pool_size=2,
            db_max_overflow=2,
            redis_url="redis://localhost:6379",
            redis_token="",
            cache_ttl_stock=900,
            cache_ttl_news=3600,
            cache_ttl_macro=86400,
            cache_ttl_fundamentals=3600,
            chroma_host="localhost",
            chroma_port=8001,
            chroma_collection="airp_test_documents",
            embedding_model="all-MiniLM-L6-v2",
            clerk_secret_key="sk_test_placeholder",
            clerk_publishable_key="pk_test_placeholder",
            clerk_jwt_issuer="https://test.clerk.accounts.dev",
            secret_key="a" * 32,
            access_token_expire_minutes=60,
            news_api_key="test-news-api-key",
            alpha_vantage_key="test-alpha-vantage-key",
            screener_base_url="https://www.screener.in",
            rbi_base_url="https://www.rbi.org.in",
            cors_origins="http://localhost:5173",
            feature_debate_enabled=True,
            debate_rounds=2,
            feature_pdf_enabled=True,
            feature_rate_limiting=False,
            max_concurrent_analyses=3,
            max_upload_size_mb=1,  # the one field this test deliberately tightens
        )
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: tight_settings
        app.dependency_overrides[get_current_user] = lambda: current_user
        transport = httpx.ASGITransport(app=cast(Any, app))

        oversized = b"x" * (2 * 1024 * 1024)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.post(
                "/api/v1/documents/upload",
                files={"file": ("huge.pdf", oversized, "application/pdf")},
                data={"company_name": "TCS"},
            )
        assert response.status_code == 413
