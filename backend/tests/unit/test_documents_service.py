# backend/tests/unit/test_documents_service.py
"""
Unit tests for T-051: backend/services/documents.py

Test strategy
-------------
1. validate_upload_size()
     under the limit         -- no exception
     exactly at the limit    -- no exception (boundary is inclusive)
     over the limit          -- raises PDFTooLargeError with the byte
                                 counts populated on the exception

2. extract_pdf_text()
     non-empty text returned by the underlying extractor -- returned
       as-is (stripped)
     underlying extractor returns "" / whitespace-only   -- raises
       EmptyPDFError
     underlying extractor raises PDFExtractionError       -- propagates
       unchanged (this module adds no extra wrapping)

   All cases patch
   backend.services.documents._extract_text_from_pdf_bytes (the name
   bound into THIS module's namespace by its own import statement --
   not backend.tools.earnings_transcript._extract_text_from_pdf_bytes,
   per unittest.mock's "patch where it's looked up" rule) so no real
   pdfminer/PyPDF2 call ever happens in this test file, matching
   test_earnings_transcript.py's own established pattern for the
   exact same underlying function.

3. link_document_to_company()
     existing Company row found -- returned as-is, no INSERT (reuses
       the exact _make_session_returning_company helper pattern from
       test_analysis_service.py, since this is the same
       get_or_create_company function under the hood)
     no existing row             -- inserts, commits, refreshes
     ticker_override/exchange_override are forwarded to resolve_company

4. ingest_uploaded_document() -- the full pipeline, exercising the
   actual T-051 acceptance criteria end-to-end at the service layer:
     happy path -- PDF uploads, text extracted, embedded in ChromaDB
                   (via a REAL ChromaClient backed by an in-memory
                   EphemeralClient + the test suite's existing _MockEF
                   pattern from test_chroma_client.py, so this is not
                   a mocked ingestion call -- it genuinely writes
                   chunks and they are genuinely retrievable after),
                   linked to the correct Company row, returns an
                   UploadResult with the right chunk/character counts
     queryable afterward -- semantic_search against COLLECTION_DOCUMENTS
                   for the same ticker returns the just-ingested chunk
                   (directly exercises "queryable by agents in
                   subsequent analyses")
     oversized PDF      -- raises PDFTooLargeError before any
                            extraction or DB work happens
     PDF with no text   -- raises EmptyPDFError; no Company row is
                            created as a side effect (ordering:
                            extraction happens before company linking)
     malformed PDF       -- PDFExtractionError propagates; no Company
                            row is created
     re-upload of the
     identical file       -- second call upserts the same chunk IDs
                            rather than duplicating (ChromaDB's
                            documented upsert-on-existing-id behaviour,
                            inherited unchanged from ingest_document's
                            deterministic ID derivation)
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import chromadb
from chromadb.config import Settings as _ChromaSettings
import pytest

from backend.config import Settings
from backend.db.chroma_client import (
    COLLECTION_DOCUMENTS,
    ChromaClient,
    DocumentType,
    semantic_search,
)
from backend.models.orm import Company
from backend.services.documents import (
    EmptyPDFError,
    PDFTooLargeError,
    extract_pdf_text,
    ingest_uploaded_document,
    link_document_to_company,
    validate_upload_size,
)
from backend.tools.earnings_transcript import PDFExtractionError

_SAMPLE_TEXT = (
    "Tata Consultancy Services Limited Annual Report FY2024. "
    "Revenue grew 12% year on year to Rs 240,893 crore. "
    "The board recommends a final dividend of Rs 28 per equity share. "
) * 5  # long enough to produce more than one 500-char chunk


# ---------------------------------------------------------------------------
# Shared ChromaDB test infrastructure -- mirrors test_chroma_client.py's
# _MockEF / shared EphemeralClient pattern so document ingestion is
# tested against a REAL (in-memory) ChromaDB instance, not a mock.
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

# Shared across this module's tests -- see test_chroma_client.py's own
# docstring for why EphemeralClient must be created once, at import
# time, before any test calls get_chroma_client() with default settings.
_SHARED_RAW_CLIENT: Any = chromadb.EphemeralClient(settings=_TEST_CHROMA_SETTINGS)


def _make_chroma_client() -> ChromaClient:
    """Return a ChromaClient over the shared EphemeralClient, reset to
    an empty state so each test starts with a clean collection slate."""
    _SHARED_RAW_CLIENT.reset()
    return ChromaClient(_SHARED_RAW_CLIENT, _MockEF())


# ---------------------------------------------------------------------------
# Shared AsyncSession fake -- mirrors test_analysis_service.py's
# _make_session_returning_company helper, since link_document_to_company
# is a thin wrapper over the exact same get_or_create_company function.
# ---------------------------------------------------------------------------


def _make_session_returning_company(company: Optional[Company]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=company)
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def settings_factory() -> Any:
    """Build a Settings instance with a configurable max_upload_size_mb,
    bypassing .env loading via model_construct (matches conftest.py's
    test_settings fixture pattern)."""

    def _build(max_upload_size_mb: int = 20) -> Settings:
        return Settings.model_construct(
            environment="test",
            log_level="DEBUG",
            llm_provider="groq",
            groq_api_key="gsk_test",
            groq_model="llama-3.3-70b-versatile",
            anthropic_api_key="sk-ant-test",
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
            max_upload_size_mb=max_upload_size_mb,
        )

    return _build


# ---------------------------------------------------------------------------
# validate_upload_size()
# ---------------------------------------------------------------------------


class TestValidateUploadSize:
    def test_under_limit_does_not_raise(self, settings_factory: Any) -> None:
        settings = settings_factory(max_upload_size_mb=20)
        validate_upload_size(1024 * 1024, settings)  # 1 MB, well under 20

    def test_exactly_at_limit_does_not_raise(self, settings_factory: Any) -> None:
        settings = settings_factory(max_upload_size_mb=20)
        exact = 20 * 1024 * 1024
        validate_upload_size(exact, settings)

    def test_over_limit_raises(self, settings_factory: Any) -> None:
        settings = settings_factory(max_upload_size_mb=20)
        over = 20 * 1024 * 1024 + 1
        with pytest.raises(PDFTooLargeError) as exc_info:
            validate_upload_size(over, settings)
        assert exc_info.value.size_bytes == over
        assert exc_info.value.max_size_bytes == 20 * 1024 * 1024

    def test_respects_configured_limit(self, settings_factory: Any) -> None:
        settings = settings_factory(max_upload_size_mb=1)
        with pytest.raises(PDFTooLargeError):
            validate_upload_size(2 * 1024 * 1024, settings)


# ---------------------------------------------------------------------------
# extract_pdf_text()
# ---------------------------------------------------------------------------


class TestExtractPdfText:
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    def test_returns_extracted_text(self, mock_extract: MagicMock) -> None:
        result = extract_pdf_text(b"%PDF fake")
        assert result == _SAMPLE_TEXT
        mock_extract.assert_called_once_with(b"%PDF fake")

    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value="",
    )
    def test_empty_text_raises_empty_pdf_error(self, mock_extract: MagicMock) -> None:
        with pytest.raises(EmptyPDFError):
            extract_pdf_text(b"%PDF fake")

    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value="   \n  ",
    )
    def test_whitespace_only_text_raises_empty_pdf_error(
        self, mock_extract: MagicMock
    ) -> None:
        with pytest.raises(EmptyPDFError):
            extract_pdf_text(b"%PDF fake")

    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        side_effect=PDFExtractionError("pdfminer broken"),
    )
    def test_extraction_error_propagates(self, mock_extract: MagicMock) -> None:
        with pytest.raises(PDFExtractionError):
            extract_pdf_text(b"%PDF fake")


# ---------------------------------------------------------------------------
# link_document_to_company()
# ---------------------------------------------------------------------------


class TestLinkDocumentToCompany:
    @pytest.mark.asyncio
    async def test_returns_existing_company_without_inserting(self) -> None:
        existing = Company(
            id=uuid.uuid4(),
            name="Tata Consultancy Services",
            ticker="TCS",
            ticker_yf="TCS.NS",
            exchange="NSE",
        )
        session = _make_session_returning_company(existing)

        result = await link_document_to_company(session, "Tata Consultancy Services")

        assert result is existing
        session.add.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_company_when_none_exists(self) -> None:
        session = _make_session_returning_company(None)

        result = await link_document_to_company(session, "Wipro")

        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()
        assert result.ticker == "WIPRO"
        assert result.ticker_yf == "WIPRO.NS"
        assert result.exchange == "NSE"

    @pytest.mark.asyncio
    async def test_ticker_override_is_forwarded(self) -> None:
        session = _make_session_returning_company(None)

        result = await link_document_to_company(
            session, "Some Co", ticker_override="SOMECO", exchange_override="BSE"
        )

        assert result.ticker == "SOMECO"
        assert result.ticker_yf == "SOMECO.BO"
        assert result.exchange == "BSE"


# ---------------------------------------------------------------------------
# ingest_uploaded_document() -- full pipeline
# ---------------------------------------------------------------------------


class TestIngestUploadedDocumentSuccess:
    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_pdf_uploads_text_extracted_and_embedded(
        self, mock_extract: MagicMock, settings_factory: Any
    ) -> None:
        """
        Directly exercises three of T-051's four acceptance criteria
        in one assertion path: "PDF uploads" (the call completes),
        "text extracted" (characters_extracted matches _SAMPLE_TEXT),
        "embedded in ChromaDB" (chunks_ingested > 0, verified against
        a REAL EphemeralClient, not a mock).
        """
        session = _make_session_returning_company(None)
        settings = settings_factory()
        chroma = _make_chroma_client()

        result = await ingest_uploaded_document(
            session,
            settings,
            pdf_bytes=b"%PDF fake",
            source_filename="TCS_Annual_Report_FY24.pdf",
            company_name="Tata Consultancy Services",
            chroma=chroma,
        )

        assert result.company_name == "Tata Consultancy Services"
        assert result.ticker == "TCS.NS"
        assert result.exchange == "NSE"
        assert result.source_filename == "TCS_Annual_Report_FY24.pdf"
        assert result.doc_type == DocumentType.ANNUAL_REPORT.value
        assert result.chunks_ingested > 0
        assert result.characters_extracted == len(_SAMPLE_TEXT)

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_document_is_queryable_after_ingestion(
        self, mock_extract: MagicMock, settings_factory: Any
    ) -> None:
        """
        Directly exercises the fourth acceptance criterion: "queryable
        by agents in subsequent analyses". Calls the exact
        backend.db.chroma_client.semantic_search function an agent
        would call, against the exact collection/company_filter shape
        backend.agents.macro_economist and backend.agents.
        sentiment_analyst already use for COLLECTION_NEWS, and asserts
        the just-ingested chunk is returned.
        """
        session = _make_session_returning_company(None)
        settings = settings_factory()
        chroma = _make_chroma_client()

        await ingest_uploaded_document(
            session,
            settings,
            pdf_bytes=b"%PDF fake",
            source_filename="TCS_Annual_Report_FY24.pdf",
            company_name="Tata Consultancy Services",
            chroma=chroma,
        )

        results = semantic_search(
            "revenue dividend",
            collection_name=COLLECTION_DOCUMENTS,
            company_filter="Tata Consultancy Services",
            chroma=chroma,
        )

        assert len(results) > 0
        assert any("Revenue grew" in r["document"] for r in results)
        assert all(r["doc_type"] == DocumentType.ANNUAL_REPORT.value for r in results)

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_links_to_existing_company_when_one_already_exists(
        self, mock_extract: MagicMock, settings_factory: Any
    ) -> None:
        existing = Company(
            id=uuid.uuid4(),
            name="Infosys Limited",
            ticker="INFY",
            ticker_yf="INFY.NS",
            exchange="NSE",
        )
        session = _make_session_returning_company(existing)
        settings = settings_factory()
        chroma = _make_chroma_client()

        result = await ingest_uploaded_document(
            session,
            settings,
            pdf_bytes=b"%PDF fake",
            source_filename="infy_transcript.pdf",
            company_name="Infosys",
            chroma=chroma,
        )

        session.add.assert_not_called()
        assert result.company_name == "Infosys Limited"
        assert result.ticker == "INFY.NS"

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_transcript_doc_type_is_honoured(
        self, mock_extract: MagicMock, settings_factory: Any
    ) -> None:
        session = _make_session_returning_company(None)
        settings = settings_factory()
        chroma = _make_chroma_client()

        result = await ingest_uploaded_document(
            session,
            settings,
            pdf_bytes=b"%PDF fake",
            source_filename="concall_q1.pdf",
            company_name="Reliance Industries",
            doc_type=DocumentType.TRANSCRIPT,
            chroma=chroma,
        )

        assert result.doc_type == DocumentType.TRANSCRIPT.value

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_TEXT,
    )
    async def test_reuploading_identical_file_upserts_not_duplicates(
        self, mock_extract: MagicMock, settings_factory: Any
    ) -> None:
        session = _make_session_returning_company(None)
        settings = settings_factory()
        chroma = _make_chroma_client()

        first = await ingest_uploaded_document(
            session,
            settings,
            pdf_bytes=b"%PDF fake",
            source_filename="TCS_Annual_Report_FY24.pdf",
            company_name="TCS",
            chroma=chroma,
        )
        before_count = chroma.collection_count(COLLECTION_DOCUMENTS)

        second = await ingest_uploaded_document(
            session,
            settings,
            pdf_bytes=b"%PDF fake",
            source_filename="TCS_Annual_Report_FY24.pdf",
            company_name="TCS",
            chroma=chroma,
        )
        after_count = chroma.collection_count(COLLECTION_DOCUMENTS)

        assert first.chunks_ingested == second.chunks_ingested
        assert before_count == after_count


class TestIngestUploadedDocumentFailureModes:
    @pytest.mark.asyncio
    async def test_oversized_pdf_raises_before_any_db_work(
        self, settings_factory: Any
    ) -> None:
        session = _make_session_returning_company(None)
        settings = settings_factory(max_upload_size_mb=1)
        oversized = b"x" * (2 * 1024 * 1024)

        with pytest.raises(PDFTooLargeError):
            await ingest_uploaded_document(
                session,
                settings,
                pdf_bytes=oversized,
                source_filename="huge.pdf",
                company_name="TCS",
                chroma=_make_chroma_client(),
            )

        session.add.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        return_value="",
    )
    async def test_empty_text_pdf_raises_and_creates_no_company(
        self, mock_extract: MagicMock, settings_factory: Any
    ) -> None:
        session = _make_session_returning_company(None)
        settings = settings_factory()

        with pytest.raises(EmptyPDFError):
            await ingest_uploaded_document(
                session,
                settings,
                pdf_bytes=b"%PDF fake",
                source_filename="scanned.pdf",
                company_name="TCS",
                chroma=_make_chroma_client(),
            )

        session.add.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    @patch(
        "backend.services.documents._extract_text_from_pdf_bytes",
        side_effect=PDFExtractionError("pdfminer broken"),
    )
    async def test_malformed_pdf_raises_and_creates_no_company(
        self, mock_extract: MagicMock, settings_factory: Any
    ) -> None:
        session = _make_session_returning_company(None)
        settings = settings_factory()

        with pytest.raises(PDFExtractionError):
            await ingest_uploaded_document(
                session,
                settings,
                pdf_bytes=b"not a real pdf",
                source_filename="corrupt.pdf",
                company_name="TCS",
                chroma=_make_chroma_client(),
            )

        session.add.assert_not_called()
        session.commit.assert_not_called()
