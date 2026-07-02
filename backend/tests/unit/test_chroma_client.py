# backend/tests/unit/test_chroma_client.py
"""
Unit tests for backend/db/chroma_client.py — T-017

All sentence-transformer model loading is mocked so these tests run
offline in CI without downloading the ~90 MB all-MiniLM-L6-v2 model.
ChromaDB EphemeralClient is used directly — it requires no server and
stores data in-process memory.

Design decisions for test isolation
-------------------------------------
_MockEF
    ChromaDB 0.5.0 validates EF.__call__ parameter names at collection-
    creation time. It expects (self, input) — a MagicMock has
    (*args, **kwargs) and is rejected. A concrete class with the exact
    parameter name 'input' passes the check.

_SHARED_RAW_CLIENT (module-level singleton)
    EphemeralClient uses SharedSystemClient, a class-level dict keyed on
    the persistence path ("ephemeral" for in-memory). Once the first call
    creates the system with settings A, any subsequent call with different
    settings B raises:
        ValueError: An instance of Chroma already exists for ephemeral
                    with different settings
    Creating the shared client at MODULE IMPORT TIME with allow_reset=True
    ensures our settings win the slot before any test can call
    get_chroma_client() with the library defaults.
    _make_client() calls raw.reset() on this singleton so each test
    starts with a clean collection slate.

TestGetChromaClient::test_test_env_returns_ephemeral_client
    Must patch chromadb.EphemeralClient inside chroma_client.py so the
    function under test does not create a second "ephemeral" system with
    different (default) settings.

Test coverage targets (acceptance criteria from T-017):
  ✓ ChromaDB collection created via get_or_create_collection
  ✓ 10 test documents embedded and retrieved correctly (main AC)
  ✓ Document count reflects additions and deletions
  ✓ News articles ingested with correct metadata and deterministic IDs
  ✓ Duplicate URLs produce identical IDs (idempotent ingestion)
  ✓ Transcripts split into chunks; each chunk has correct metadata
  ✓ Empty article list / blank transcript text → no-op, no crash
  ✓ Length mismatch in add_documents raises ChromaClientError
  ✓ query_documents on empty collection returns []
  ✓ query_documents caps n_results at actual document count
  ✓ delete_documents removes docs; count decreases correctly
  ✓ reset_collection wipes all documents; count returns to 0
  ✓ list_collections returns known collection names
  ✓ semantic_search filters by company via metadata where clause
  ✓ get_chroma_client routing verified for all 3 environments
  ✓ _chunk_text handles empty text, short text, and long text
  ✓ _flatten_query_results converts raw ChromaDB output correctly
  ✓ DocumentType enum values match expected strings

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_chroma_client.py -v
"""
from __future__ import annotations

import os

# Must be set before any backend imports
os.environ.setdefault("ENVIRONMENT", "test")

from typing import Any  # noqa: E402
from unittest.mock import ANY, MagicMock, patch  # noqa: E402

import chromadb  # noqa: E402
from chromadb.config import Settings as _ChromaSettings  # noqa: E402
import pytest  # noqa: E402

from backend.db.chroma_client import (  # noqa: E402
    ALL_COLLECTIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_NEWS,
    COLLECTION_TRANSCRIPTS,
    EMBEDDING_MODEL_DEFAULT,
    ChromaClient,
    ChromaClientError,
    DocumentType,
    _chunk_text,
    _flatten_query_results,
    _text_to_id,
    _url_to_id,
    build_chroma_client,
    get_chroma_client,
    get_embedding_function,
    ingest_news_articles,
    ingest_transcript,
    semantic_search,
)

# ---------------------------------------------------------------------------
# _MockEF — concrete EmbeddingFunction for tests
# ---------------------------------------------------------------------------
# ChromaDB 0.5.0 validates __call__ parameter names:
#   odict_keys(['self', 'input']) is required.
# A plain class with the exact signature passes; MagicMock does not.
# ---------------------------------------------------------------------------


class _MockEF:
    """
    Fake embedding function satisfying ChromaDB's interface validation.

    Returns fixed 384-dim vectors (all-MiniLM-L6-v2 output dimension)
    without loading any model or making any network call.
    """

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [[0.1] * 384 for _ in input]


# ---------------------------------------------------------------------------
# Module-level ChromaDB singleton
# ---------------------------------------------------------------------------
# EphemeralClient uses SharedSystemClient — a process-wide singleton keyed
# on the identifier "ephemeral".  The FIRST creation wins; any subsequent
# creation with different settings raises ValueError.
#
# Creating _SHARED_RAW_CLIENT here (at module import time, before any test
# class is defined) ensures allow_reset=True settings win the "ephemeral"
# slot before get_chroma_client() is called by TestGetChromaClient with the
# library's default settings.
# ---------------------------------------------------------------------------

_TEST_CHROMA_SETTINGS = _ChromaSettings(
    is_persistent=False,
    allow_reset=True,
    anonymized_telemetry=False,
)

# One real EphemeralClient shared across all tests in this module.
_SHARED_RAW_CLIENT: Any = chromadb.EphemeralClient(settings=_TEST_CHROMA_SETTINGS)


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _make_mock_ef() -> _MockEF:
    """Return a fresh _MockEF instance."""
    return _MockEF()


def _make_client() -> ChromaClient:
    """
    Return a ChromaClient pointing at the shared EphemeralClient.

    Calls reset() to wipe all collections left by previous tests.
    Using the singleton avoids repeated EphemeralClient() calls with
    conflicting settings.
    """
    _SHARED_RAW_CLIENT.reset()
    return ChromaClient(_SHARED_RAW_CLIENT, _MockEF())


def _make_articles(n: int = 10) -> list[dict[str, Any]]:
    """Generate ``n`` fake news article dicts for ingestion tests."""
    return [
        {
            "title": f"TCS Q{i} earnings beat analyst expectations",
            "url": f"https://example.com/tcs-q{i}-earnings",
            "description": (f"Tata Consultancy Services Q{i} revenue rose strongly."),
            "source_name": "Economic Times",
            "published_at": f"2024-0{(i % 9) + 1}-15T10:00:00Z",
        }
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# TestDocumentType
# ---------------------------------------------------------------------------


class TestDocumentType:
    def test_news_value(self) -> None:
        assert DocumentType.NEWS.value == "news"

    def test_transcript_value(self) -> None:
        assert DocumentType.TRANSCRIPT.value == "transcript"

    def test_annual_report_value(self) -> None:
        assert DocumentType.ANNUAL_REPORT.value == "annual_report"

    def test_is_string_enum(self) -> None:
        assert isinstance(DocumentType.NEWS, str)


# ---------------------------------------------------------------------------
# TestChunkText
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_empty_text_returns_empty_list(self) -> None:
        assert _chunk_text("") == []

    def test_blank_text_returns_empty_list(self) -> None:
        assert _chunk_text("   ") == []

    def test_short_text_is_single_chunk(self) -> None:
        text = "Short text that fits in one chunk."
        chunks = _chunk_text(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_split_into_multiple_chunks(self) -> None:
        text = "word " * 300  # ~1500 chars
        chunks = _chunk_text(text, chunk_size=500, overlap=0)
        assert len(chunks) > 1

    def test_each_chunk_within_size_limit(self) -> None:
        text = "a" * 2000
        chunks = _chunk_text(text, chunk_size=500, overlap=0)
        for chunk in chunks:
            assert len(chunk) <= 500

    def test_overlap_produces_more_chunks_than_no_overlap(self) -> None:
        text = "a" * 1000
        chunks_with = _chunk_text(text, chunk_size=300, overlap=50)
        chunks_without = _chunk_text(text, chunk_size=300, overlap=0)
        assert len(chunks_with) >= len(chunks_without)

    def test_no_empty_chunks(self) -> None:
        text = "hello " * 500
        for chunk in _chunk_text(text, chunk_size=100, overlap=10):
            assert chunk.strip() != ""

    def test_overlap_gte_chunk_size_forced_to_zero(self) -> None:
        # Misconfigured overlap >= chunk_size → clamped to 0, no infinite loop
        chunks = _chunk_text("a" * 1000, chunk_size=100, overlap=200)
        assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# TestUrlToId
# ---------------------------------------------------------------------------


class TestUrlToId:
    def test_returns_string_with_prefix(self) -> None:
        result = _url_to_id("https://example.com/article", prefix="news")
        assert result.startswith("news_")

    def test_deterministic_same_url_same_id(self) -> None:
        url = "https://economictimes.com/tcs-q2"
        assert _url_to_id(url) == _url_to_id(url)

    def test_different_urls_different_ids(self) -> None:
        id1 = _url_to_id("https://example.com/article-1")
        id2 = _url_to_id("https://example.com/article-2")
        assert id1 != id2

    def test_id_length(self) -> None:
        # "news_" (5) + 16 hex chars = 21
        assert len(_url_to_id("https://example.com/x", prefix="news")) == 21


# ---------------------------------------------------------------------------
# TestTextToId
# ---------------------------------------------------------------------------


class TestTextToId:
    def test_deterministic(self) -> None:
        text = "TCS:Q2FY24:screener.in"
        assert _text_to_id(text) == _text_to_id(text)

    def test_prefix_included(self) -> None:
        assert _text_to_id("hello", prefix="transcript").startswith("transcript_")


# ---------------------------------------------------------------------------
# TestFlattenQueryResults
# ---------------------------------------------------------------------------


class TestFlattenQueryResults:
    def test_empty_raw_returns_empty_list(self) -> None:
        raw: dict[str, Any] = {
            "ids": [],
            "documents": [],
            "distances": [],
            "metadatas": [],
        }
        assert _flatten_query_results(raw) == []

    def test_single_result_flattened(self) -> None:
        raw: dict[str, Any] = {
            "ids": [["id_001"]],
            "documents": [["Some financial news text."]],
            "distances": [[0.12]],
            "metadatas": [[{"company": "TCS", "doc_type": "news"}]],
        }
        results = _flatten_query_results(raw)
        assert len(results) == 1
        assert results[0]["id"] == "id_001"
        assert results[0]["distance"] == 0.12
        assert results[0]["company"] == "TCS"

    def test_metadata_merged_into_result(self) -> None:
        raw: dict[str, Any] = {
            "ids": [["abc"]],
            "documents": [["text"]],
            "distances": [[0.5]],
            "metadatas": [[{"ticker": "INFY.NS", "doc_type": "transcript"}]],
        }
        result = _flatten_query_results(raw)[0]
        assert result["ticker"] == "INFY.NS"
        assert result["doc_type"] == "transcript"

    def test_none_metadata_does_not_raise(self) -> None:
        raw: dict[str, Any] = {
            "ids": [["x"]],
            "documents": [["doc"]],
            "distances": [[0.0]],
            "metadatas": [[None]],
        }
        assert _flatten_query_results(raw)[0]["id"] == "x"


# ---------------------------------------------------------------------------
# TestGetChromaClient
# ---------------------------------------------------------------------------


class TestGetChromaClient:
    def test_test_env_returns_ephemeral_client(self) -> None:
        # Patch EphemeralClient inside chroma_client.py so it returns our
        # shared client instead of trying to create a second system with
        # different (default) settings — which would raise ValueError.
        with patch(
            "backend.db.chroma_client.chromadb.EphemeralClient",
            return_value=_SHARED_RAW_CLIENT,
        ):
            client = get_chroma_client()
        assert hasattr(client, "list_collections")

    def test_production_env_calls_http_client(self) -> None:
        mock_settings = MagicMock()
        mock_settings.environment = "production"
        mock_settings.chroma_host = "chromadb"
        mock_settings.chroma_port = 8001
        with patch("backend.db.chroma_client._settings", mock_settings):
            with patch("backend.db.chroma_client.chromadb.HttpClient") as mock_http:
                mock_http.return_value = MagicMock()
                get_chroma_client()
        # settings=ANY: get_chroma_client() always passes a Settings
        # object with anonymized_telemetry=False (see that function's
        # docstring for why) -- this test only pins the host/port
        # routing, not the exact Settings instance.
        mock_http.assert_called_once_with(host="chromadb", port=8001, settings=ANY)

    def test_development_env_calls_persistent_client(self) -> None:
        mock_settings = MagicMock()
        mock_settings.environment = "development"
        with patch("backend.db.chroma_client._settings", mock_settings):
            with patch(
                "backend.db.chroma_client.chromadb.PersistentClient"
            ) as mock_pers:
                mock_pers.return_value = MagicMock()
                get_chroma_client(persist_dir="/tmp/test_chroma")
        mock_pers.assert_called_once_with(path="/tmp/test_chroma", settings=ANY)


# ---------------------------------------------------------------------------
# TestGetEmbeddingFunction
# ---------------------------------------------------------------------------


class TestGetEmbeddingFunction:
    def test_calls_sentence_transformer_with_model_name(self) -> None:
        with patch(
            "backend.db.chroma_client.SentenceTransformerEmbeddingFunction"
        ) as mock_cls:
            mock_cls.return_value = _MockEF()
            get_embedding_function("all-MiniLM-L6-v2")
        mock_cls.assert_called_once_with(model_name="all-MiniLM-L6-v2")

    def test_uses_default_model_when_no_arg(self) -> None:
        with patch(
            "backend.db.chroma_client.SentenceTransformerEmbeddingFunction"
        ) as mock_cls:
            mock_cls.return_value = _MockEF()
            get_embedding_function()
        mock_cls.assert_called_once_with(model_name=EMBEDDING_MODEL_DEFAULT)


# ---------------------------------------------------------------------------
# TestBuildChromaClient
# ---------------------------------------------------------------------------


class TestBuildChromaClient:
    def test_returns_chroma_client_instance(self) -> None:
        # Re-using _SHARED_RAW_CLIENT: same _TEST_CHROMA_SETTINGS →
        # SharedSystemClient finds the existing system, no ValueError.
        client = build_chroma_client(
            raw_client=_SHARED_RAW_CLIENT,
            embedding_fn=_MockEF(),
        )
        assert isinstance(client, ChromaClient)

    def test_custom_client_and_ef_are_used(self) -> None:
        ef = _make_mock_ef()
        client = build_chroma_client(raw_client=_SHARED_RAW_CLIENT, embedding_fn=ef)
        assert client._client is _SHARED_RAW_CLIENT
        assert client._ef is ef

    def test_default_ef_calls_get_embedding_function(self) -> None:
        with patch("backend.db.chroma_client.get_embedding_function") as mock_gef:
            mock_gef.return_value = _MockEF()
            build_chroma_client(raw_client=_SHARED_RAW_CLIENT)
        mock_gef.assert_called_once()


# ---------------------------------------------------------------------------
# TestChromaClientGetOrCreateCollection
# ---------------------------------------------------------------------------


class TestChromaClientGetOrCreateCollection:
    def test_creates_new_collection(self) -> None:
        client = _make_client()
        col = client.get_or_create_collection(COLLECTION_NEWS)
        assert col is not None

    def test_same_object_returned_on_second_call(self) -> None:
        client = _make_client()
        col1 = client.get_or_create_collection(COLLECTION_NEWS)
        col2 = client.get_or_create_collection(COLLECTION_NEWS)
        assert col1 is col2  # in-process cache hit

    def test_different_collections_are_different_objects(self) -> None:
        client = _make_client()
        news = client.get_or_create_collection(COLLECTION_NEWS)
        transcripts = client.get_or_create_collection(COLLECTION_TRANSCRIPTS)
        assert news is not transcripts


# ---------------------------------------------------------------------------
# TestChromaClientListCollections
# ---------------------------------------------------------------------------


class TestChromaClientListCollections:
    def test_empty_instance_returns_empty_list(self) -> None:
        client = _make_client()  # reset() guarantees clean slate
        assert client.list_collections() == []

    def test_created_collections_appear_in_list(self) -> None:
        client = _make_client()
        client.get_or_create_collection(COLLECTION_NEWS)
        client.get_or_create_collection(COLLECTION_TRANSCRIPTS)
        names = client.list_collections()
        assert COLLECTION_NEWS in names
        assert COLLECTION_TRANSCRIPTS in names


# ---------------------------------------------------------------------------
# TestChromaClientAddDocuments
# ---------------------------------------------------------------------------


class TestChromaClientAddDocuments:
    def test_add_documents_increases_count(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["Article text."],
            [{"company": "TCS"}],
            ["doc_001"],
        )
        assert client.collection_count(COLLECTION_NEWS) == 1

    def test_add_multiple_documents(self) -> None:
        client = _make_client()
        n = 5
        client.add_documents(
            COLLECTION_NEWS,
            [f"Doc {i}" for i in range(n)],
            [{"company": "TCS"} for _ in range(n)],
            [f"id_{i:03d}" for i in range(n)],
        )
        assert client.collection_count(COLLECTION_NEWS) == n

    def test_empty_list_is_no_op(self) -> None:
        client = _make_client()
        client.add_documents(COLLECTION_NEWS, [], [], [])
        assert client.collection_count(COLLECTION_NEWS) == 0

    def test_length_mismatch_raises_chroma_client_error(self) -> None:
        client = _make_client()
        with pytest.raises(ChromaClientError, match="same length"):
            client.add_documents(
                COLLECTION_NEWS,
                ["doc1", "doc2"],  # 2 docs
                [{"company": "TCS"}],  # 1 metadata — mismatch
                ["id_001", "id_002"],
            )

    def test_metadata_stored_and_retrievable(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["Infosys Q3 revenue growth reported."],
            [{"company": "Infosys", "ticker": "INFY.NS"}],
            ["infy_001"],
        )
        results = client.query_documents(
            COLLECTION_NEWS, ["Infosys revenue"], n_results=1
        )
        assert results[0]["company"] == "Infosys"
        assert results[0]["ticker"] == "INFY.NS"


# ---------------------------------------------------------------------------
# TestChromaClientQueryDocuments
# ---------------------------------------------------------------------------


class TestChromaClientQueryDocuments:
    def test_empty_collection_returns_empty_list(self) -> None:
        client = _make_client()
        assert client.query_documents(COLLECTION_NEWS, ["query"]) == []

    def test_query_returns_at_most_n_results(self) -> None:
        client = _make_client()
        for i in range(6):
            client.add_documents(
                COLLECTION_NEWS,
                [f"Doc {i}"],
                [{"company": "TCS"}],
                [f"id_{i}"],
            )
        results = client.query_documents(COLLECTION_NEWS, ["TCS"], n_results=3)
        assert len(results) <= 3

    def test_n_results_capped_at_collection_size(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["Only doc"],
            [{"company": "TCS"}],
            ["only_id"],
        )
        # Request 10 but only 1 exists — should return 1, not raise
        results = client.query_documents(COLLECTION_NEWS, ["query"], n_results=10)
        assert len(results) == 1

    def test_result_has_required_keys(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["TCS quarterly earnings beat consensus."],
            [{"company": "TCS"}],
            ["tcs_001"],
        )
        result = client.query_documents(COLLECTION_NEWS, ["TCS earnings"], n_results=1)[
            0
        ]
        assert "id" in result
        assert "document" in result
        assert "distance" in result

    def test_where_filter_restricts_results(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["TCS strong quarter.", "Infosys weak quarter."],
            [{"company": "TCS"}, {"company": "Infosys"}],
            ["tcs_001", "infy_001"],
        )
        results = client.query_documents(
            COLLECTION_NEWS,
            ["quarterly results"],
            n_results=5,
            where_filter={"company": "TCS"},
        )
        for r in results:
            assert r["company"] == "TCS"


# ---------------------------------------------------------------------------
# TestChromaClientDeleteDocuments
# ---------------------------------------------------------------------------


class TestChromaClientDeleteDocuments:
    def test_delete_reduces_count(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["Doc A", "Doc B"],
            [{"company": "TCS"}, {"company": "TCS"}],
            ["id_a", "id_b"],
        )
        client.delete_documents(COLLECTION_NEWS, ["id_a"])
        assert client.collection_count(COLLECTION_NEWS) == 1

    def test_delete_empty_list_is_no_op(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["Doc"],
            [{"company": "TCS"}],
            ["id_x"],
        )
        client.delete_documents(COLLECTION_NEWS, [])
        assert client.collection_count(COLLECTION_NEWS) == 1

    def test_delete_all_documents(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["A", "B", "C"],
            [{"company": "TCS"} for _ in range(3)],
            ["i1", "i2", "i3"],
        )
        client.delete_documents(COLLECTION_NEWS, ["i1", "i2", "i3"])
        assert client.collection_count(COLLECTION_NEWS) == 0


# ---------------------------------------------------------------------------
# TestChromaClientResetCollection
# ---------------------------------------------------------------------------


class TestChromaClientResetCollection:
    def test_reset_wipes_all_documents(self) -> None:
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["A", "B"],
            [{"company": "TCS"}, {"company": "TCS"}],
            ["r1", "r2"],
        )
        client.reset_collection(COLLECTION_NEWS)
        assert client.collection_count(COLLECTION_NEWS) == 0

    def test_reset_non_existent_collection_does_not_raise(self) -> None:
        client = _make_client()
        client.reset_collection("non_existent_collection_xyz")


# ---------------------------------------------------------------------------
# TestIngestNewsArticles
# ---------------------------------------------------------------------------


class TestIngestNewsArticles:
    def test_ten_articles_increase_count_to_ten(self) -> None:
        client = _make_client()
        ingest_news_articles(_make_articles(10), "TCS", "TCS.NS", client)
        assert client.collection_count(COLLECTION_NEWS) == 10

    def test_returns_list_of_ids(self) -> None:
        client = _make_client()
        ids = ingest_news_articles(_make_articles(5), "TCS", "TCS.NS", client)
        assert len(ids) == 5
        assert all(isinstance(i, str) for i in ids)

    def test_ids_are_deterministic_for_same_url(self) -> None:
        client = _make_client()
        articles = _make_articles(3)
        ids1 = ingest_news_articles(articles, "TCS", "TCS.NS", client)
        client.reset_collection(COLLECTION_NEWS)
        ids2 = ingest_news_articles(articles, "TCS", "TCS.NS", client)
        assert ids1 == ids2

    def test_metadata_fields_stored_correctly(self) -> None:
        client = _make_client()
        article = [
            {
                "title": "TCS beats Q2 estimates",
                "url": "https://example.com/tcs-q2",
                "description": "Revenue up 8%.",
                "source_name": "Economic Times",
                "published_at": "2024-10-15T10:00:00Z",
            }
        ]
        ingest_news_articles(article, "TCS", "TCS.NS", client)
        r = client.query_documents(COLLECTION_NEWS, ["TCS Q2"], n_results=1)[0]
        assert r["company"] == "TCS"
        assert r["ticker"] == "TCS.NS"
        assert r["doc_type"] == DocumentType.NEWS.value
        assert r["source_name"] == "Economic Times"

    def test_empty_articles_list_returns_empty_ids(self) -> None:
        client = _make_client()
        ids = ingest_news_articles([], "TCS", "TCS.NS", client)
        assert ids == []
        assert client.collection_count(COLLECTION_NEWS) == 0


# ---------------------------------------------------------------------------
# TestIngestTranscript
# ---------------------------------------------------------------------------


class TestIngestTranscript:
    def test_short_transcript_creates_one_chunk(self) -> None:
        client = _make_client()
        ids = ingest_transcript(
            "Q2 earnings call transcript. Revenue grew by 8%.",
            "TCS",
            "TCS.NS",
            "screener.in",
            "Q2FY24",
            client,
        )
        assert len(ids) == 1

    def test_long_transcript_creates_multiple_chunks(self) -> None:
        client = _make_client()
        text = "Q2 earnings call. " * 200  # ~3600 chars
        ids = ingest_transcript(
            text,
            "Infosys",
            "INFY.NS",
            "screener.in",
            "Q2FY24",
            client,
            chunk_size=500,
        )
        assert len(ids) > 1
        assert client.collection_count(COLLECTION_TRANSCRIPTS) == len(ids)

    def test_chunk_metadata_includes_chunk_index(self) -> None:
        client = _make_client()
        ingest_transcript("a" * 1500, "TCS", "TCS.NS", "pdf_upload", "Q3FY24", client)
        results = client.query_documents(COLLECTION_TRANSCRIPTS, ["a"], n_results=20)
        assert 0 in [r["chunk_index"] for r in results]

    def test_blank_text_returns_empty_list(self) -> None:
        client = _make_client()
        ids = ingest_transcript("   ", "TCS", "TCS.NS", "screener.in", "Q1FY24", client)
        assert ids == []


# ---------------------------------------------------------------------------
# TestSemanticSearch
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    def test_search_returns_results_list(self) -> None:
        client = _make_client()
        ingest_news_articles(_make_articles(5), "TCS", "TCS.NS", client)
        results = semantic_search(
            "TCS quarterly earnings", COLLECTION_NEWS, chroma=client
        )
        assert isinstance(results, list) and len(results) > 0

    def test_company_filter_restricts_results(self) -> None:
        client = _make_client()
        ingest_news_articles(_make_articles(5), "TCS", "TCS.NS", client)
        client.add_documents(
            COLLECTION_NEWS,
            ["Infosys reports strong quarter."],
            [{"company": "Infosys", "ticker": "INFY.NS"}],
            ["infy_q1"],
        )
        results = semantic_search(
            "quarterly results",
            COLLECTION_NEWS,
            n_results=10,
            company_filter="TCS",
            chroma=client,
        )
        for r in results:
            assert r["company"] == "TCS"

    def test_search_on_empty_collection_returns_empty(self) -> None:
        client = _make_client()
        assert semantic_search("anything", COLLECTION_NEWS, chroma=client) == []


# ---------------------------------------------------------------------------
# TestAllCollections
# ---------------------------------------------------------------------------


class TestAllCollections:
    def test_all_collections_list_has_three_entries(self) -> None:
        assert len(ALL_COLLECTIONS) == 3

    def test_all_collections_contains_expected_names(self) -> None:
        assert COLLECTION_NEWS in ALL_COLLECTIONS
        assert COLLECTION_TRANSCRIPTS in ALL_COLLECTIONS
        assert COLLECTION_DOCUMENTS in ALL_COLLECTIONS


# ---------------------------------------------------------------------------
# TestAcceptanceCriteria — T-017 main acceptance test
# ---------------------------------------------------------------------------


class TestAcceptanceCriteria:
    """
    Formal acceptance criteria from T-017:
    'ChromaDB collection created; 10 test documents embedded and
    retrieved correctly.'
    """

    def test_ten_documents_embedded_and_retrieved(self) -> None:
        """Embed 10 docs into a collection and retrieve them via query."""
        client = _make_client()

        # Step 1: create 10 article dicts
        articles = _make_articles(10)

        # Step 2: embed and store
        ids = ingest_news_articles(articles, "TCS", "TCS.NS", client)
        assert len(ids) == 10, "Expected 10 document IDs returned"

        # Step 3: verify count
        count = client.collection_count(COLLECTION_NEWS)
        assert count == 10, f"Expected 10 documents in collection, got {count}"

        # Step 4: retrieve via semantic search
        results = client.query_documents(
            COLLECTION_NEWS, ["TCS quarterly earnings"], n_results=10
        )
        assert len(results) == 10, f"Expected 10 results from query, got {len(results)}"

        # Step 5: verify result structure and metadata
        for r in results:
            assert "id" in r
            assert "document" in r
            assert "distance" in r
            assert r["company"] == "TCS"
            assert r["ticker"] == "TCS.NS"
            assert r["doc_type"] == DocumentType.NEWS.value

    def test_collection_created_with_expected_name(self) -> None:
        """The airp_news collection is created and queryable."""
        client = _make_client()
        client.add_documents(
            COLLECTION_NEWS,
            ["Sample document."],
            [{"company": "INFY"}],
            ["sample_001"],
        )
        assert COLLECTION_NEWS in client.list_collections()
