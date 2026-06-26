# backend/services/documents.py
"""
AIRP -- Document Upload Service (T-051)

Business logic backing POST /api/v1/documents/upload: accept a PDF
(annual report or earnings-call transcript), extract its text, embed it
into ChromaDB, and link it to a resolved Company row so subsequent
analyses for that ticker can retrieve it via RAG. Pure service-layer
code with no FastAPI imports (mirrors backend/services/auth.py and
backend/services/analysis.py) so it stays independently testable
without spinning up an ASGI app; the router
(backend/routers/documents.py) translates this module's plain return
values and exceptions into the correct HTTP response shape and status
code.

What this module does
----------------------
1. ``validate_upload_size`` -- rejects a PDF above
   ``settings.max_upload_size_mb`` before any extraction work runs, so
   an oversized upload fails fast and cheaply rather than after a
   potentially slow pdfminer pass on a huge file.
2. ``extract_pdf_text`` -- thin wrapper around the EXISTING
   ``backend.tools.earnings_transcript._extract_text_from_pdf_bytes``
   (T-015) rather than a second implementation of PDF text extraction.
   Reusing it keeps the pdfminer.six-primary/PyPDF2-fallback behaviour,
   and its exact PDFExtractionError, identical between the two PDF
   upload entry points the codebase now has (this endpoint, and the
   existing pdf_bytes path on fetch_earnings_transcript).
3. ``link_document_to_company`` -- resolves the caller-supplied
   company_name/ticker/exchange to a canonical Company row via the
   SAME ``resolve_company`` / ``get_or_create_company`` pair
   ``backend.services.analysis`` already uses for
   POST /api/v1/analysis/start (T-047) -- "link to company" in this
   task's acceptance criteria means exactly the same resolution and
   persistence step, not a second company registry.
4. ``ingest_uploaded_document`` -- the single entry point the router
   calls: validates size, extracts text, resolves+persists the
   Company row, and chunks+embeds the extracted text into ChromaDB's
   ``airp_documents`` collection via the T-051 addition to
   backend.db.chroma_client (``ingest_document``). Returns an
   ``UploadResult`` with everything the router needs to build
   DocumentUploadResponse.

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- established AIRP rule
  (breaks Pydantic v2 union resolution for modules that import this one).
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``type: ignore`` -- cast()/explicit annotations only.
* Every database operation is async (SQLAlchemy 2.x asyncpg), matching
  backend.services.auth and backend.services.analysis.
* Reuses resolve_company/get_or_create_company from
  backend.services.analysis rather than re-implementing ticker
  resolution a second time -- one resolver, two callers (analysis
  trigger and document upload), exactly the DRY rationale already
  documented in backend.services.analysis's own module docstring for
  why it does NOT import backend.agents.valuation_agent's separate
  copy (different layering boundary; this case has no such boundary
  to cross, so reuse is the right call here).
* Reuses backend.tools.earnings_transcript._extract_text_from_pdf_bytes
  rather than a second PDF-extraction implementation -- same
  pdfminer.six/PyPDF2 fallback chain, same PDFExtractionError type,
  for both PDF upload entry points the codebase has.
* ChromaDB ingestion happens AFTER the Company row is committed --
  if get_or_create_company fails (e.g. a transient DB issue),
  ingest_uploaded_document never embeds an orphaned document a
  later analysis could retrieve for a company that does not yet
  exist in PostgreSQL.

Public API
----------
    from backend.services.documents import (
        UploadResult,
        PDFTooLargeError,
        validate_upload_size,
        extract_pdf_text,
        link_document_to_company,
        ingest_uploaded_document,
    )
"""

from dataclasses import dataclass
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.chroma_client import (
    ChromaClient,
    DocumentType,
    build_chroma_client,
    ingest_document,
)
from backend.models.orm import Company
from backend.services.analysis import get_or_create_company, resolve_company
from backend.tools.earnings_transcript import _extract_text_from_pdf_bytes

logger = logging.getLogger(__name__)

__all__ = [
    "UploadResult",
    "PDFTooLargeError",
    "EmptyPDFError",
    "validate_upload_size",
    "extract_pdf_text",
    "link_document_to_company",
    "ingest_uploaded_document",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PDFTooLargeError(Exception):
    """
    Raised by validate_upload_size when the upload exceeds
    settings.max_upload_size_mb. The router translates this into a 413
    Payload Too Large response.
    """

    def __init__(self, size_bytes: int, max_size_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.max_size_bytes = max_size_bytes
        super().__init__(
            f"upload is {size_bytes} bytes, exceeds the " f"{max_size_bytes}-byte limit"
        )


class EmptyPDFError(Exception):
    """
    Raised by extract_pdf_text when pdfminer/PyPDF2 extracts zero
    characters of text -- the classic signature of a scanned,
    image-only PDF with no embedded text layer. Distinct from
    PDFExtractionError (a hard parsing failure on a malformed/corrupt
    file): an empty-text PDF is well-formed, it simply has nothing for
    this endpoint to embed. The router translates this into a 422
    Unprocessable Entity rather than the 400 it uses for
    PDFExtractionError, since the file itself was valid.
    """


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadResult:
    """
    Everything backend.routers.documents needs to build
    DocumentUploadResponse, returned by ingest_uploaded_document in one
    call rather than the router re-deriving any of these fields itself.
    """

    company_name: str
    ticker: str
    exchange: str
    source_filename: str
    doc_type: str
    chunks_ingested: int
    characters_extracted: int


# ---------------------------------------------------------------------------
# Size validation
# ---------------------------------------------------------------------------


def validate_upload_size(size_bytes: int, settings: Settings) -> None:
    """
    Raise PDFTooLargeError if size_bytes exceeds
    settings.max_upload_size_mb (converted to bytes).

    Called as the first step of ingest_uploaded_document, immediately
    after the router has read the upload body into memory -- FastAPI's
    UploadFile does not expose a reliable size before reading it for
    an arbitrary ASGI server/client combination, so this check runs on
    the in-memory byte count rather than a streamed, partial read.
    Still cheap relative to the rest of the pipeline: it is one
    multiplication and a comparison, run before the meaningfully more
    expensive PDF text extraction step.

    Args:
        size_bytes: Size of the uploaded file in bytes.
        settings:   Active Settings -- max_upload_size_mb is read from
                    here rather than hard-coded so the limit stays
                    centrally configurable via .env, matching every
                    other tunable in this codebase.

    Raises:
        PDFTooLargeError: if size_bytes exceeds the configured limit.
    """
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise PDFTooLargeError(size_bytes=size_bytes, max_size_bytes=max_bytes)


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """
    Extract text from raw PDF bytes, raising EmptyPDFError for a
    well-formed PDF with no extractable text.

    Deliberately delegates the actual extraction to
    backend.tools.earnings_transcript._extract_text_from_pdf_bytes
    (T-015) instead of re-implementing the pdfminer.six-primary /
    PyPDF2-fallback chain a second time -- see this module's docstring
    for the full rationale. That function already raises
    PDFExtractionError for a malformed/corrupt PDF or when neither
    library is installed; this wrapper adds the empty-text check that
    earnings_transcript.py's OWN callers handle differently (a blank
    transcript there just means "fall back to the next data source",
    which has no equivalent for a direct upload -- there is no second
    source to fall back to, so it is surfaced as a distinct error
    instead).

    Args:
        pdf_bytes: Raw PDF file bytes.

    Returns:
        Extracted text, stripped of leading/trailing whitespace.
        Guaranteed non-empty (raises rather than returning "").

    Raises:
        PDFExtractionError: if pdfminer/PyPDF2 fail to parse the file,
            or neither library is installed.
        EmptyPDFError: if extraction succeeds but yields no text (e.g.
            a scanned, image-only PDF with no embedded text layer).
    """
    text = _extract_text_from_pdf_bytes(pdf_bytes)
    if not text.strip():
        raise EmptyPDFError(
            "PDF parsed successfully but contains no extractable text "
            "(it may be a scanned, image-only document)"
        )
    return text


# ---------------------------------------------------------------------------
# Company linking
# ---------------------------------------------------------------------------


async def link_document_to_company(
    session: AsyncSession,
    company_name: str,
    ticker_override: Optional[str] = None,
    exchange_override: Optional[str] = None,
) -> Company:
    """
    Resolve and persist the Company row this upload is linked to.

    Thin wrapper around backend.services.analysis.resolve_company +
    get_or_create_company -- the SAME pair POST /api/v1/analysis/start
    (T-047) uses, so a document uploaded for "TCS" and an analysis
    later triggered for "Tata Consultancy Services" resolve to the
    identical Company row rather than two near-duplicate ones. See
    this module's docstring for why this is intentional reuse, not a
    parallel ticker-resolution implementation.

    Args:
        session:            Active AsyncSession for this request.
        company_name:        Free-text company name/ticker as submitted
                            on the upload form, e.g. 'TCS' or
                            'Tata Consultancy Services'.
        ticker_override:     Optional explicit Yahoo Finance ticker.
        exchange_override:   Optional explicit exchange ('NSE'/'BSE').

    Returns:
        The existing or newly-created Company ORM instance.
    """
    resolution = resolve_company(
        raw_query=company_name,
        ticker_override=ticker_override,
        exchange_override=exchange_override,
    )
    return await get_or_create_company(session, resolution)


# ---------------------------------------------------------------------------
# Full upload pipeline
# ---------------------------------------------------------------------------


async def ingest_uploaded_document(
    session: AsyncSession,
    settings: Settings,
    pdf_bytes: bytes,
    source_filename: str,
    company_name: str,
    ticker_override: Optional[str] = None,
    exchange_override: Optional[str] = None,
    doc_type: DocumentType = DocumentType.ANNUAL_REPORT,
    chroma: Optional[ChromaClient] = None,
) -> UploadResult:
    """
    Run the full T-051 pipeline: validate size, extract text, link to
    a Company row, and embed the result into ChromaDB.

    This is the single function backend.routers.documents.upload_document
    calls -- every other function in this module exists to be composed
    here (and to be independently unit-tested in isolation).

    Ordering rationale: the Company row is resolved and committed
    BEFORE ChromaDB ingestion runs, so a failure partway through never
    leaves an embedded document pointing at a company that does not
    exist in PostgreSQL. PDF size validation and text extraction both
    happen before touching the database at all, so a malformed or
    oversized upload never creates a Company row for a document that
    will not end up ingested anyway.

    Args:
        session:            Active AsyncSession for this request.
        settings:            Active Settings (max_upload_size_mb).
        pdf_bytes:           Raw uploaded PDF file bytes.
        source_filename:     Original uploaded filename, used for
                            metadata and the deterministic chunk ID
                            ingest_document derives.
        company_name:        Company name/ticker as submitted on the
                            upload form.
        ticker_override:     Optional explicit ticker override.
        exchange_override:   Optional explicit exchange override.
        doc_type:            Which DocumentType this upload represents
                            -- ANNUAL_REPORT (default) or TRANSCRIPT.
        chroma:              ChromaClient to ingest into. Defaults to a
                            fresh client via build_chroma_client() when
                            not supplied; tests inject a fake client
                            pointed at an EphemeralClient instead.

    Returns:
        UploadResult with the resolved company, the ingested chunk
        count, and the extracted character count.

    Raises:
        PDFTooLargeError: if pdf_bytes exceeds settings.max_upload_size_mb.
        PDFExtractionError: if the PDF cannot be parsed at all.
        EmptyPDFError: if the PDF parses but has no extractable text.
    """
    validate_upload_size(len(pdf_bytes), settings)
    text = extract_pdf_text(pdf_bytes)

    company = await link_document_to_company(
        session,
        company_name=company_name,
        ticker_override=ticker_override,
        exchange_override=exchange_override,
    )

    active_chroma = chroma if chroma is not None else build_chroma_client()
    chunk_ids = ingest_document(
        text=text,
        company=company.name,
        ticker=company.ticker_yf,
        source_filename=source_filename,
        chroma=active_chroma,
        doc_type=doc_type,
    )

    logger.info(
        "ingest_uploaded_document: filename=%s ticker=%s doc_type=%s "
        "chunks=%d chars=%d",
        source_filename,
        company.ticker_yf,
        doc_type.value,
        len(chunk_ids),
        len(text),
    )

    return UploadResult(
        company_name=company.name,
        ticker=company.ticker_yf,
        exchange=company.exchange,
        source_filename=source_filename,
        doc_type=doc_type.value,
        chunks_ingested=len(chunk_ids),
        characters_extracted=len(text),
    )
