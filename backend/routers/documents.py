# backend/routers/documents.py
"""
AIRP -- Document Upload Router (T-051)

POST /api/v1/documents/upload

Accepts a PDF (annual report or earnings-call transcript), extracts its
text, embeds it into ChromaDB, and links it to a resolved Company row
so subsequent analyses for that ticker can retrieve it via RAG.

Acceptance criteria (from task spec):
  * PDF uploads
  * text extracted
  * embedded in ChromaDB
  * queryable by agents in subsequent analyses

HTTP-layer concerns only (multipart/form-data parsing via FastAPI's
UploadFile/Form, authentication via get_current_user, translating
service-layer exceptions into the correct status code) -- all PDF
extraction, company resolution, and ChromaDB ingestion live in
backend.services.documents, mirroring the router/service split
established by T-046 (auth) and T-047/T-048/T-050 (analysis).

Why multipart/form-data instead of a JSON body
------------------------------------------------
A PDF is binary file content, not something that round-trips through
JSON without a base64 encoding overhead FastAPI's UploadFile avoids
entirely -- UploadFile streams the upload from the ASGI server's
buffer rather than requiring the whole file to be loaded as a base64
string first. company_name/ticker/exchange are therefore plain
Form(...) fields alongside the File(...) upload, not a Pydantic
request schema (see backend.models.schemas.DocumentUploadResponse's
docstring for why no matching *Request schema exists for this route).

Why "queryable by agents in subsequent analyses" needs no new code
here
-----------------------------------------------------------------------
backend.agents.macro_economist and backend.agents.sentiment_analyst
already call backend.db.chroma_client.semantic_search against
COLLECTION_NEWS for their own RAG context (T-021-T-028). This
endpoint's only job is to make sure an uploaded document is embedded
into ChromaDB's airp_documents collection (COLLECTION_DOCUMENTS) with
the same {company, ticker, doc_type} metadata shape semantic_search's
company_filter already knows how to query -- a future agent task that
wants to read uploaded annual reports calls
semantic_search(..., collection_name=COLLECTION_DOCUMENTS,
company_filter=ticker) exactly the way the two existing agents already
call it against COLLECTION_NEWS. No agent currently does this (it is
not part of T-051's acceptance criteria, which only requires the
upload to BE queryable, not that any agent currently queries it), so
no agent module is touched by this task.

Why 413, not 422, for an oversized upload
---------------------------------------------
RFC 9110 defines 413 Content Too Large specifically for "the request
entity is larger than limits the server is willing to process" -- the
exact condition PDFTooLargeError represents. 422 is reserved below for
a different failure: a same-size, well-formed request whose CONTENT
the server cannot act on (a non-PDF content-type, or a PDF with no
extractable text), which is a semantic problem with the payload, not a
size problem.

Why 422, not 400, for an empty-text PDF
-------------------------------------------
The PDF itself parsed successfully -- it is a well-formed file, just
one with no embedded text layer (a scanned/image-only document, most
commonly). 400 Bad Request is reserved below for PDFExtractionError,
where the file itself could not be parsed at all (corrupt, truncated,
or not actually a PDF despite the extension/content-type claiming
otherwise) -- a request-malformation problem 422 does not describe as
precisely as 400 does.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.models.orm import User
from backend.models.schemas import DocumentUploadResponse
from backend.services.documents import (
    EmptyPDFError,
    PDFTooLargeError,
    ingest_uploaded_document,
)
from backend.tools.earnings_transcript import PDFExtractionError

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
logger = logging.getLogger(__name__)

#: Content-types accepted for the upload. application/pdf is the
#: standard PDF MIME type; application/octet-stream is included
#: because some browsers and HTTP clients report PDFs under the
#: generic binary type when the OS/browser does not have a specific
#: PDF association configured -- rejecting that case purely on
#: content-type would reject genuinely valid PDF uploads from those
#: clients. The actual file content is what backend.services.documents
#: validates (via PDF extraction itself failing on anything that is
#: not really a PDF), so this check is a fast, cheap first filter, not
#: the sole gate.
_ACCEPTED_CONTENT_TYPES = frozenset({"application/pdf", "application/octet-stream"})


# ---------------------------------------------------------------------------
# POST /api/v1/documents/upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF annual report or earnings transcript",
    description=(
        "Accepts a PDF, extracts its text, embeds it into ChromaDB's "
        "document collection, and links it to a resolved company so "
        "subsequent analyses for that ticker can retrieve it via RAG."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="The PDF file to upload"),
    company_name: str = Form(
        ...,
        description="Company name or ticker this document belongs to, e.g. 'TCS'",
    ),
    ticker: str | None = Form(
        default=None,
        description="Optional explicit Yahoo Finance ticker override (e.g. 'TCS.NS')",
    ),
    exchange: str | None = Form(
        default=None,
        description="Optional explicit exchange override: 'NSE' or 'BSE'",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings_dependency),
) -> DocumentUploadResponse:
    if not company_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="company_name must not be empty or whitespace-only",
        )

    if file.content_type not in _ACCEPTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported content type '{file.content_type}' -- only "
                "PDF uploads are accepted"
            ),
        )

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )

    source_filename = file.filename or "upload.pdf"

    try:
        result = await ingest_uploaded_document(
            session,
            settings,
            pdf_bytes=pdf_bytes,
            source_filename=source_filename,
            company_name=company_name,
            ticker_override=ticker,
            exchange_override=exchange,
        )
    except PDFTooLargeError as exc:
        # 413 Content Too Large (RFC 9110). Using the numeric value
        # directly rather than a status.HTTP_413_* constant -- Starlette
        # has renamed this constant across versions
        # (HTTP_413_REQUEST_ENTITY_TOO_LARGE vs HTTP_413_CONTENT_TOO_LARGE)
        # while the integer 413 itself is stable across all of them.
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except PDFExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse the uploaded PDF: {exc}",
        ) from exc
    except EmptyPDFError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "upload_document: user=%s filename=%s ticker=%s chunks=%d",
        current_user.id,
        source_filename,
        result.ticker,
        result.chunks_ingested,
    )

    return DocumentUploadResponse(
        company_name=result.company_name,
        ticker=result.ticker,
        exchange=result.exchange,
        source_filename=result.source_filename,
        doc_type=result.doc_type,
        chunks_ingested=result.chunks_ingested,
        characters_extracted=result.characters_extracted,
    )
