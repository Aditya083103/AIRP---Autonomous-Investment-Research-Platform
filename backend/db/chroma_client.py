# backend/db/chroma_client.py
"""
AIRP — ChromaDB Client and Embedding Pipeline (T-017)

This module provides the vector store infrastructure for AIRP's RAG
(Retrieval-Augmented Generation) pipeline.  News articles, earnings
call transcripts, and uploaded annual reports are embedded using a
local sentence-transformer model and stored in ChromaDB for semantic
similarity search during agent analysis.

Architecture:
    ChromaClient          — manages collections and CRUD operations
    get_embedding_function — wraps SentenceTransformerEmbeddingFunction
    get_chroma_client      — returns env-appropriate raw client
    build_chroma_client    — factory combining client + embedding fn
    ingest_news_articles   — batch-ingest structured news dicts
    ingest_transcript      — split + ingest a single transcript
    ingest_document         — split + ingest a user-uploaded PDF (T-051)
    semantic_search        — similarity search across a collection

Environment routing (ENVIRONMENT variable):
    test        → EphemeralClient  (in-memory; no disk I/O in CI)
    development → PersistentClient (saves to .chroma_data/)
    production  → HttpClient       (Docker container at chroma_host:port)

Embedding model: all-MiniLM-L6-v2 (384-dim, ~90 MB, free/local)
    Downloaded on first call; cached in ~/.cache/torch thereafter.
    Override via settings.embedding_model or EMBEDDING_MODEL_DEFAULT.

Usage (from an agent):
    from backend.db.chroma_client import semantic_search, COLLECTION_NEWS

    results = semantic_search(
        "TCS revenue growth",
        collection_name=COLLECTION_NEWS,
        n_results=5,
        company_filter="TCS",
    )
    for r in results:
        print(r["title"], r["distance"])
"""
from __future__ import annotations

from enum import Enum
import hashlib
import logging
import os
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

try:
    from backend.config import settings as _settings
except Exception:  # pragma: no cover
    _settings = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

EMBEDDING_MODEL_DEFAULT = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384  # all-MiniLM-L6-v2 output dimension
CHROMA_PERSIST_DIR = ".chroma_data"  # local dev persistence path

# Standard collection names — one per document type
COLLECTION_NEWS = "airp_news"
COLLECTION_TRANSCRIPTS = "airp_transcripts"
COLLECTION_DOCUMENTS = "airp_documents"

ALL_COLLECTIONS: list[str] = [
    COLLECTION_NEWS,
    COLLECTION_TRANSCRIPTS,
    COLLECTION_DOCUMENTS,
]

# Safety cap — never return more than this many results per query
MAX_QUERY_RESULTS = 20

# Default chunking parameters for long transcripts
DEFAULT_CHUNK_SIZE = 500  # characters per chunk
DEFAULT_CHUNK_OVERLAP = 50  # overlap between consecutive chunks


# ── Enums ──────────────────────────────────────────────────────────────────────


class DocumentType(str, Enum):
    """
    Document categories stored in ChromaDB.

    Used as the ``doc_type`` metadata field so agents can filter
    results to a specific document category via ChromaDB where clauses.
    """

    NEWS = "news"
    TRANSCRIPT = "transcript"
    ANNUAL_REPORT = "annual_report"


# ── Exceptions ─────────────────────────────────────────────────────────────────


class ChromaClientError(RuntimeError):
    """Raised when ChromaDB client cannot be initialised or operated."""


# ── Embedding function ─────────────────────────────────────────────────────────


def get_embedding_function(
    model_name: str = EMBEDDING_MODEL_DEFAULT,
) -> Any:
    """
    Return a ChromaDB-compatible SentenceTransformer embedding function.

    The underlying model (~90 MB) is downloaded on first call and cached
    in ``~/.cache/torch/sentence_transformers``.  Subsequent calls are
    instant because the model is loaded from disk.

    Args:
        model_name: HuggingFace model identifier.
                    Default: ``all-MiniLM-L6-v2`` (384-dim, fast, good
                    quality for short financial text snippets).

    Returns:
        A callable that accepts ``list[str]`` and returns
        ``list[list[float]]`` of dimension EMBEDDING_DIMENSION.
    """
    logger.debug("Loading sentence-transformer model: %s", model_name)
    return SentenceTransformerEmbeddingFunction(model_name=model_name)


# ── Raw client factory ─────────────────────────────────────────────────────────


def get_chroma_client(
    persist_dir: str = CHROMA_PERSIST_DIR,
) -> Any:
    """
    Return an environment-appropriate ChromaDB raw client.

    Routing logic:
        - ``test``        → ``EphemeralClient``   (in-memory, no disk)
        - ``production``  → ``HttpClient``        (Docker container)
        - ``development`` → ``PersistentClient``  (local disk)

    Args:
        persist_dir: Directory used by ``PersistentClient`` in development.
                     Ignored in test and production environments.

    Returns:
        A ``chromadb.ClientAPI`` instance.
    """
    env = (
        _settings.environment
        if _settings is not None
        else os.getenv("ENVIRONMENT", "development")
    )

    if env == "test":
        logger.debug("ChromaDB → EphemeralClient (test environment)")
        return chromadb.EphemeralClient()

    if env == "production":
        host = _settings.chroma_host if _settings is not None else "localhost"
        port = _settings.chroma_port if _settings is not None else 8001
        logger.info("ChromaDB → HttpClient (%s:%d)", host, port)
        return chromadb.HttpClient(host=host, port=port)

    # development (default)
    logger.info("ChromaDB → PersistentClient (%s)", persist_dir)
    return chromadb.PersistentClient(path=persist_dir)


# ── ChromaClient ───────────────────────────────────────────────────────────────


class ChromaClient:
    """
    High-level ChromaDB client for AIRP's RAG pipeline.

    Wraps a raw ``chromadb.ClientAPI`` with:
    - Collection management (get-or-create with in-process caching)
    - Typed add / query / delete operations
    - Consistent metadata schema across all document types

    The embedding function is injected at construction so unit tests can
    provide a mock without loading the real sentence-transformer model.

    Example::

        client = build_chroma_client()
        client.add_documents(
            COLLECTION_NEWS, texts, metadatas, ids
        )
        results = client.query_documents(
            COLLECTION_NEWS, ["TCS quarterly earnings"], n_results=5
        )
    """

    def __init__(self, client: Any, embedding_fn: Any) -> None:
        """
        Initialise the client.

        Args:
            client:       Raw ``chromadb.ClientAPI`` instance.
            embedding_fn: Callable — ``list[str]`` → ``list[list[float]]``.
        """
        self._client = client
        self._ef = embedding_fn
        self._cache: dict[str, Any] = {}

    # ── Collection management ────────────────────────────────────────────────

    def get_or_create_collection(self, name: str) -> Any:
        """
        Return a collection by name, creating it if it does not exist.

        Collections are cached in-process to avoid repeated DB round-trips
        on every agent tool call.

        Args:
            name: Collection name.  Use the module-level constants
                  (``COLLECTION_NEWS``, ``COLLECTION_TRANSCRIPTS``, …).

        Returns:
            ``chromadb.Collection`` instance.
        """
        if name not in self._cache:
            col = self._client.get_or_create_collection(
                name=name,
                embedding_function=self._ef,
                metadata={"hnsw:space": "cosine"},
            )
            self._cache[name] = col
        return self._cache[name]

    def list_collections(self) -> list[str]:
        """Return names of all collections in this ChromaDB instance."""
        return [c.name for c in self._client.list_collections()]

    def reset_collection(self, name: str) -> None:
        """
        Delete and recreate a collection, wiping all its documents.

        Intended for development fixtures and test teardown.
        Do not call in production without explicit user intent.

        Args:
            name: Collection name to reset.
        """
        try:
            self._client.delete_collection(name=name)
        except Exception:  # collection may not exist yet
            pass
        self._cache.pop(name, None)
        self.get_or_create_collection(name)
        logger.debug("Reset collection '%s'.", name)

    # ── CRUD ────────────────────────────────────────────────────────────────

    def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
    ) -> None:
        """
        Embed and store documents in a collection.

        IDs must be unique within the collection.  If an ID already exists,
        ChromaDB silently upserts (re-embeds) the document — so repeated
        ingestion runs with the same URLs are safe.

        Args:
            collection_name: Target collection.
            documents:       Text strings to embed and store.
            metadatas:       One metadata dict per document.
                             Values must be ``str | int | float | bool``.
            ids:             Unique string identifier per document.

        Raises:
            ChromaClientError: If ``documents``, ``metadatas``, and ``ids``
                               have different lengths.
        """
        n_docs = len(documents)
        n_meta = len(metadatas)
        n_ids = len(ids)
        if not (n_docs == n_meta == n_ids):
            raise ChromaClientError(
                f"documents ({n_docs}), metadatas ({n_meta}), and "
                f"ids ({n_ids}) must all have the same length."
            )
        if not documents:
            logger.warning(
                "add_documents called with empty list for '%s' — no-op.",
                collection_name,
            )
            return
        col = self.get_or_create_collection(collection_name)
        col.add(documents=documents, metadatas=metadatas, ids=ids)
        logger.debug(
            "Added %d document(s) to collection '%s'.",
            n_docs,
            collection_name,
        )

    def query_documents(
        self,
        collection_name: str,
        query_texts: list[str],
        n_results: int = 5,
        where_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic similarity search across a collection.

        Args:
            collection_name: Collection to search.
            query_texts:     One or more natural-language query strings.
            n_results:       Maximum documents returned per query text.
                             Automatically capped at the collection size and
                             ``MAX_QUERY_RESULTS`` to prevent ChromaDB errors.
            where_filter:    ChromaDB metadata filter dict.
                             Example: ``{"company": "TCS"}``

        Returns:
            Flat list of result dicts sorted by similarity (closest first).
            Each dict has keys: ``id``, ``document``, ``distance``, plus
            all metadata keys from the stored document.
            Returns ``[]`` if the collection is empty.
        """
        col = self.get_or_create_collection(collection_name)
        count = int(col.count())
        if count == 0:
            logger.warning(
                "query_documents: collection '%s' is empty.",
                collection_name,
            )
            return []
        capped = min(n_results, count, MAX_QUERY_RESULTS)
        kwargs: dict[str, Any] = {
            "query_texts": query_texts,
            "n_results": capped,
            "include": ["documents", "metadatas", "distances"],
        }
        if where_filter:
            kwargs["where"] = where_filter
        raw: dict[str, Any] = col.query(**kwargs)
        return _flatten_query_results(raw)

    def delete_documents(
        self,
        collection_name: str,
        ids: list[str],
    ) -> None:
        """
        Remove documents from a collection by their IDs.

        Args:
            collection_name: Target collection.
            ids:             Document IDs to remove.
        """
        if not ids:
            return
        col = self.get_or_create_collection(collection_name)
        col.delete(ids=ids)
        logger.debug(
            "Deleted %d document(s) from '%s'.",
            len(ids),
            collection_name,
        )

    def collection_count(self, collection_name: str) -> int:
        """
        Return the number of documents in a collection.

        Creates the collection if it does not yet exist (count = 0).

        Args:
            collection_name: Target collection.

        Returns:
            Integer document count.
        """
        col = self.get_or_create_collection(collection_name)
        return int(col.count())


# ── Factory ────────────────────────────────────────────────────────────────────


def build_chroma_client(
    raw_client: Any | None = None,
    embedding_fn: Any | None = None,
) -> ChromaClient:
    """
    Build a fully configured ``ChromaClient`` instance.

    Both arguments default to environment-derived values.  Pass explicit
    values to inject test doubles without touching global state.

    Args:
        raw_client:   ``chromadb.ClientAPI`` instance.  Defaults to
                      ``get_chroma_client()``.
        embedding_fn: Embedding callable.  Defaults to
                      ``get_embedding_function()`` using the model name
                      from ``settings.embedding_model``.

    Returns:
        Ready-to-use ``ChromaClient``.
    """
    if raw_client is None:
        raw_client = get_chroma_client()
    if embedding_fn is None:
        model = (
            _settings.embedding_model
            if _settings is not None
            else EMBEDDING_MODEL_DEFAULT
        )
        embedding_fn = get_embedding_function(model)
    return ChromaClient(raw_client, embedding_fn)


# ── Ingestion helpers ──────────────────────────────────────────────────────────


def ingest_news_articles(
    articles: list[dict[str, Any]],
    company: str,
    ticker: str,
    chroma: ChromaClient,
) -> list[str]:
    """
    Embed and store news articles in the ``airp_news`` collection.

    Each article dict must contain at minimum:
        ``title`` (str), ``url`` (str), ``published_at`` (str ISO-8601).
    Optional: ``description``, ``source_name``.

    A deterministic ID is derived from the article URL via SHA-256 so
    the same article is never duplicated across overlapping news windows.

    Args:
        articles: List of article dicts (from ``fetch_news`` output).
        company:  Company display name — stored in metadata for filtering.
        ticker:   Stock ticker — stored in metadata for filtering.
        chroma:   ``ChromaClient`` instance to write into.

    Returns:
        List of document IDs added to the collection.
        Returns ``[]`` if ``articles`` is empty.
    """
    if not articles:
        logger.warning("ingest_news_articles: empty list for '%s' — skipped.", company)
        return []

    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []

    for article in articles:
        url = str(article.get("url", ""))
        title = str(article.get("title", ""))
        description = str(article.get("description", "") or "")
        source_name = str(article.get("source_name", ""))
        published_at = str(article.get("published_at", ""))

        # Build rich text — title + description for better embedding quality
        text = f"{title}. {description}".strip(". ") or title

        meta: dict[str, Any] = {
            "company": company,
            "ticker": ticker,
            "doc_type": DocumentType.NEWS.value,
            "title": title[:512],
            "url": url[:512],
            "source_name": source_name[:128],
            "published_at": published_at,
        }
        documents.append(text)
        metadatas.append(meta)
        ids.append(_url_to_id(url, prefix="news"))

    chroma.add_documents(COLLECTION_NEWS, documents, metadatas, ids)
    logger.info(
        "Ingested %d news articles for %s (%s).",
        len(ids),
        company,
        ticker,
    )
    return ids


def ingest_transcript(
    text: str,
    company: str,
    ticker: str,
    source: str,
    date: str,
    chroma: ChromaClient,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[str]:
    """
    Embed and store an earnings transcript in ``airp_transcripts``.

    Long transcripts are split into overlapping chunks so each piece fits
    within the embedding model's context window (~256 tokens for MiniLM)
    while preserving cross-sentence context via the overlap region.

    Args:
        text:       Full transcript text.
        company:    Company display name — stored in metadata.
        ticker:     Stock ticker — stored in metadata.
        source:     Source label (e.g. ``"screener.in"``, ``"pdf_upload"``).
        date:       Transcript date or quarter label (e.g. ``"Q2FY24"``).
        chroma:     ``ChromaClient`` instance to write into.
        chunk_size: Target characters per chunk (default 500).

    Returns:
        List of chunk document IDs added to the collection.
        Returns ``[]`` if ``text`` is blank.
    """
    if not text.strip():
        logger.warning("ingest_transcript: blank text for '%s' — skipped.", company)
        return []

    chunks = _chunk_text(text, chunk_size=chunk_size)
    base_id = _text_to_id(f"{ticker}:{date}:{source}", prefix="transcript")

    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        meta: dict[str, Any] = {
            "company": company,
            "ticker": ticker,
            "doc_type": DocumentType.TRANSCRIPT.value,
            "source": source,
            "date": date,
            "chunk_index": i,
            "total_chunks": total,
        }
        documents.append(chunk)
        metadatas.append(meta)
        ids.append(f"{base_id}_chunk{i:04d}")

    chroma.add_documents(COLLECTION_TRANSCRIPTS, documents, metadatas, ids)
    logger.info(
        "Ingested transcript for %s (%s): %d chunks from %s.",
        company,
        ticker,
        total,
        source,
    )
    return ids


def ingest_document(
    text: str,
    company: str,
    ticker: str,
    source_filename: str,
    chroma: ChromaClient,
    doc_type: DocumentType = DocumentType.ANNUAL_REPORT,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[str]:
    """
    Embed and store a user-uploaded document in ``airp_documents`` (T-051).

    Generalises ``ingest_transcript``'s chunk-and-store flow for the
    ``POST /api/v1/documents/upload`` endpoint: a caller-supplied PDF
    (annual report or earnings call transcript) is split into the same
    overlapping fixed-size chunks and written with ``doc_type`` set to
    whichever ``DocumentType`` the upload represents — kept in the
    dedicated ``COLLECTION_DOCUMENTS`` collection (distinct from
    ``COLLECTION_TRANSCRIPTS``, which only ever holds Screener.in-scraped
    earnings calls) so a future per-collection retention or quota policy
    can treat user uploads independently of scraped data.

    A deterministic base ID is derived from ``(ticker, source_filename)``
    via SHA-256 — re-uploading the exact same file for the exact same
    ticker upserts (re-embeds) rather than duplicating, the same
    idempotency guarantee ``ingest_transcript`` and ``ingest_news_articles``
    already provide for their own inputs.

    Args:
        text:             Full extracted document text (already run
                          through PDF text extraction by the caller —
                          this function only chunks and embeds).
        company:          Company display name — stored in metadata so
                          agents can filter results via
                          ``semantic_search(..., company_filter=...)``.
        ticker:           Stock ticker — stored in metadata.
        source_filename:  Original uploaded filename (e.g.
                          ``"TCS_Annual_Report_FY24.pdf"``) — stored in
                          metadata for display/audit, and folded into the
                          deterministic chunk ID so re-uploads upsert.
        chroma:           ``ChromaClient`` instance to write into.
        doc_type:         Which ``DocumentType`` this upload represents.
                          Defaults to ``ANNUAL_REPORT`` since that is the
                          acceptance criterion's primary use case; pass
                          ``DocumentType.TRANSCRIPT`` for an uploaded
                          earnings-call PDF instead of a scraped one.
        chunk_size:       Target characters per chunk (default 500,
                          matching ``ingest_transcript``).

    Returns:
        List of chunk document IDs added to the collection.
        Returns ``[]`` if ``text`` is blank.
    """
    if not text.strip():
        logger.warning(
            "ingest_document: blank text for '%s' (%s) — skipped.",
            company,
            source_filename,
        )
        return []

    chunks = _chunk_text(text, chunk_size=chunk_size)
    base_id = _text_to_id(f"{ticker}:{source_filename}", prefix="document")

    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        meta: dict[str, Any] = {
            "company": company,
            "ticker": ticker,
            "doc_type": doc_type.value,
            "source_filename": source_filename[:256],
            "chunk_index": i,
            "total_chunks": total,
        }
        documents.append(chunk)
        metadatas.append(meta)
        ids.append(f"{base_id}_chunk{i:04d}")

    chroma.add_documents(COLLECTION_DOCUMENTS, documents, metadatas, ids)
    logger.info(
        "Ingested document '%s' for %s (%s): %d chunks, doc_type=%s.",
        source_filename,
        company,
        ticker,
        total,
        doc_type.value,
    )
    return ids


def semantic_search(
    query: str,
    collection_name: str,
    n_results: int = 5,
    company_filter: str | None = None,
    chroma: ChromaClient | None = None,
) -> list[dict[str, Any]]:
    """
    Semantic similarity search — primary interface for agents.

    This is the function agents (News Sentiment Agent, Fundamental Analyst)
    call to retrieve relevant context before drafting their analysis.

    Args:
        query:           Natural-language search string.
        collection_name: Collection to search.  Use module-level constants.
        n_results:       Maximum results to return (default 5).
        company_filter:  If set, restricts results to documents where the
                         ``company`` metadata field matches this string.
        chroma:          ``ChromaClient`` to use.  Defaults to a new client
                         built via ``build_chroma_client()`` if ``None``.

    Returns:
        Flat list of result dicts, closest first.  Each dict contains:
        ``id``, ``document``, ``distance``, and all stored metadata keys.
    """
    if chroma is None:
        chroma = build_chroma_client()
    where: dict[str, Any] | None = None
    if company_filter:
        where = {"company": company_filter}
    return chroma.query_documents(
        collection_name,
        query_texts=[query],
        n_results=n_results,
        where_filter=where,
    )


# ── Private helpers ────────────────────────────────────────────────────────────


def _flatten_query_results(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert ChromaDB ``collection.query()`` output to a flat list.

    ChromaDB returns nested lists (one sub-list per query text).  AIRP
    always sends a single query text so this flattens the outer list.

    Args:
        raw: Raw dict from ``chromadb.Collection.query()``.

    Returns:
        Flat list of result dicts.  Each dict has ``id``, ``document``,
        ``distance``, plus all metadata key-value pairs.
    """
    results: list[dict[str, Any]] = []
    ids_nested: list[Any] = raw.get("ids") or []
    docs_nested: list[Any] = raw.get("documents") or []
    dists_nested: list[Any] = raw.get("distances") or []
    metas_nested: list[Any] = raw.get("metadatas") or []

    for ids_, docs_, dists_, metas_ in zip(
        ids_nested, docs_nested, dists_nested, metas_nested
    ):
        for doc_id, doc, dist, meta in zip(ids_, docs_, dists_, metas_):
            entry: dict[str, Any] = {
                "id": doc_id,
                "document": doc,
                "distance": dist,
            }
            if meta:
                entry.update(meta)
            results.append(entry)
    return results


def _url_to_id(url: str, prefix: str = "doc") -> str:
    """
    Derive a stable, collision-resistant document ID from a URL.

    Uses the first 16 hex characters of SHA-256 to produce a short,
    URL-safe identifier.  The same URL always maps to the same ID so
    repeated ingestion runs never create duplicate documents.

    Args:
        url:    Article URL string.
        prefix: Short category label prepended to the ID.

    Returns:
        String of the form ``"{prefix}_{16-char hex digest}"``.
    """
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _text_to_id(text: str, prefix: str = "doc") -> str:
    """
    Derive a stable document ID from arbitrary text using SHA-256.

    Args:
        text:   Any string to hash.
        prefix: Short label prepended to the digest.

    Returns:
        String of the form ``"{prefix}_{16-char hex digest}"``.
    """
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into overlapping fixed-size chunks for embedding.

    The overlap region ensures that sentences straddling a chunk boundary
    appear in both the preceding and following chunk, preserving semantic
    continuity for the embedding model.

    Args:
        text:       Full text to split.
        chunk_size: Target characters per chunk (default 500).
        overlap:    Character overlap between consecutive chunks (default 50).
                    Must be less than ``chunk_size``.

    Returns:
        List of non-empty text chunks.  Returns ``[]`` if ``text`` is blank.
    """
    if not text:
        return []
    if overlap >= chunk_size:
        overlap = 0  # guard against misconfigured parameters
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = end - overlap
    return chunks
