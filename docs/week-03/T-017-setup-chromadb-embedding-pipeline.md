# T-017 — Setup ChromaDB and Embedding Pipeline

**Phase:** 1 — Data Layer & APIs
**Week:** 3
**Branch:** `feat/data-chromadb`
**Commit prefix:** `feat(rag):`
**PR title:** `feat(rag): setup ChromaDB and sentence-transformer embedding pipeline`

---

## Overview

Implements T-017: the vector store infrastructure that powers AIRP's
Retrieval-Augmented Generation (RAG) pipeline. News articles, earnings
transcripts, and uploaded annual reports are embedded locally using the
`all-MiniLM-L6-v2` sentence-transformer model and persisted in ChromaDB
for semantic similarity search during agent analysis.

**Three collections provisioned:**

| Collection         | Document type                   | Used by                          |
| ------------------ | ------------------------------- | -------------------------------- |
| `airp_news`        | News articles from `fetch_news` | News Sentiment Agent (T-024)     |
| `airp_transcripts` | Earnings call transcripts       | Fundamental Analyst (T-022)      |
| `airp_documents`   | Uploaded annual reports / PDFs  | Document upload endpoint (T-051) |

**Key production features:**

- Environment-routing: `EphemeralClient` (test) → `PersistentClient` (dev)
  → `HttpClient` (Docker/prod) — zero config change needed across envs
- Deterministic document IDs via SHA-256 of URL/key so repeated ingestion
  runs never create duplicates
- Long transcripts split into overlapping 500-char chunks so each chunk
  fits within MiniLM's 256-token context window; overlap preserves
  cross-sentence semantic context
- Embedding function injected at construction → unit tests provide a
  mock without ever downloading the 90 MB model
- `semantic_search()` convenience function used directly by agents:
  `from backend.db.chroma_client import semantic_search`

**Acceptance criteria met:**

- ChromaDB collection created via `get_or_create_collection`
- 10 test documents embedded and retrieved correctly
  (see `TestAcceptanceCriteria` in test file)

---

## Files Created in This Task

| File                                       | Action     | Purpose                                                |
| ------------------------------------------ | ---------- | ------------------------------------------------------ |
| `backend/db/__init__.py`                   | **CREATE** | Package init for db layer                              |
| `backend/db/chroma_client.py`              | **CREATE** | ChromaDB client, embedding pipeline, ingestion helpers |
| `backend/tests/unit/test_chroma_client.py` | **CREATE** | 50+ unit tests, all mocked, offline-safe               |

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Checkout feature branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feat/data-chromadb
git branch
# → * feat/data-chromadb
```

---

### Step 2 — Place the files

```
backend/db/__init__.py
backend/db/chroma_client.py
backend/tests/unit/test_chroma_client.py
```

---

### Step 3 — Install dependencies

`chromadb==0.5.0` and `sentence-transformers==3.0.1` are already in
`backend/requirements.txt` (added during T-009 environment setup).
Activate your venv and ensure they are installed:

```bash
pip install -r backend/requirements.txt
```

The `all-MiniLM-L6-v2` model downloads automatically on first call to
`get_embedding_function()` (development only — tests mock this call).

---

### Step 4 — Run the tests

```bash
# From repo root, venv active
set ENVIRONMENT=test          # Windows
# export ENVIRONMENT=test     # Git Bash / Mac / Linux

python -m pytest backend/tests/unit/test_chroma_client.py -v
```

**Expected output:**

```
backend/tests/unit/test_chroma_client.py::TestDocumentType::test_news_value PASSED
backend/tests/unit/test_chroma_client.py::TestChunkText::test_empty_text_returns_empty_list PASSED
...
backend/tests/unit/test_chroma_client.py::TestAcceptanceCriteria::test_ten_documents_embedded_and_retrieved PASSED
backend/tests/unit/test_chroma_client.py::TestAcceptanceCriteria::test_collection_created_with_expected_name PASSED
====== 50+ passed in X.XXs ======
```

Full suite — verify no regressions:

```bash
python -m pytest --tb=short
# → all passed
```

Coverage report:

```bash
python -m pytest backend/tests/unit/test_chroma_client.py -v \
  --cov=backend.db.chroma_client \
  --cov-report=term-missing
```

---

### Step 5 — Commit

```bash
git add backend/db/__init__.py
git add backend/db/chroma_client.py
git add backend/tests/unit/test_chroma_client.py

git commit -m "feat(rag): setup ChromaDB and sentence-transformer embedding pipeline

- Add backend/db/ package with ChromaClient class and embedding helpers
- Implement DocumentType enum: news | transcript | annual_report
- Add get_chroma_client(): env-routing — Ephemeral (test) / Persistent
  (dev) / HttpClient (prod Docker) via ENVIRONMENT variable
- Add get_embedding_function(): wraps SentenceTransformerEmbeddingFunction
  (all-MiniLM-L6-v2, 384-dim, free/local, ~90 MB cached on first run)
- Implement ChromaClient with:
    get_or_create_collection() — in-process cache avoids DB round-trips
    add_documents()            — embed and store with metadata
    query_documents()          — similarity search with n_results cap
    delete_documents()         — remove by ID
    collection_count()         — document count
    reset_collection()         — wipe and recreate (dev/test only)
    list_collections()         — enumerate all collections
- Add ingest_news_articles(): deterministic SHA-256 IDs from URLs;
  stores company, ticker, doc_type, title, source_name in metadata
- Add ingest_transcript(): chunks long text at 500 chars with 50-char
  overlap; stores chunk_index and total_chunks in metadata
- Add semantic_search(): agent-facing function with company_filter
- Add _flatten_query_results(): converts ChromaDB nested output to
  flat list of result dicts
- Add 50+ unit tests: EphemeralClient + mock EF (no model download);
  covers all CRUD paths, acceptance criteria (10 docs), filters,
  metadata validation, edge cases

Acceptance criteria: ChromaDB collection created; 10 test documents
embedded and retrieved correctly (TestAcceptanceCriteria passes).

Closes #17"

git push -u origin feat/data-chromadb
```

---

### Step 6 — Open the Pull Request on GitHub

- **Base branch:** `main`
- **Compare branch:** `feat/data-chromadb`

---

## Pull Request Template

**PR Title:**
`feat(rag): setup ChromaDB and sentence-transformer embedding pipeline`

---

### Summary

Implements T-017: vector store infrastructure for AIRP's RAG pipeline.
`ChromaClient` manages three ChromaDB collections (news, transcripts,
documents) using `all-MiniLM-L6-v2` embeddings generated locally via
sentence-transformers. Provides `ingest_news_articles()`,
`ingest_transcript()`, and `semantic_search()` as the primary interfaces
agents will call from Phase 2 onwards. All tests use `EphemeralClient`

- a mock embedding function — no model download in CI.

### Changes

**`backend/db/__init__.py`**

- Package init for the db layer

**`backend/db/chroma_client.py`**

- `DocumentType` enum: `news | transcript | annual_report`
- `ChromaClientError` — raised on setup/config failures
- `get_embedding_function(model_name)` — wraps
  `SentenceTransformerEmbeddingFunction`; injectable for tests
- `get_chroma_client(persist_dir)` — env-aware factory:
  `EphemeralClient` (test), `PersistentClient` (dev), `HttpClient` (prod)
- `ChromaClient` class — all CRUD + collection management with
  in-process collection cache
- `build_chroma_client(raw_client?, ef?)` — factory with optional
  injection points for test doubles
- `ingest_news_articles()` — URL-based SHA-256 IDs for idempotent
  ingestion; rich text from title + description
- `ingest_transcript()` — fixed-size overlapping chunking; chunk
  metadata (index, total) stored for reconstruction
- `semantic_search()` — thin agent-facing wrapper with company filter
- `_flatten_query_results()` — converts ChromaDB nested output to flat list
- `_chunk_text()` — deterministic chunking with overlap guard

**`backend/tests/unit/test_chroma_client.py`**

- 50+ unit tests, all offline (EphemeralClient + mock EF)
- `TestDocumentType` — enum values
- `TestChunkText` — empty, short, long, overlap, guard
- `TestUrlToId` / `TestTextToId` — determinism, prefix, length
- `TestFlattenQueryResults` — single, multiple, null metadata
- `TestGetChromaClient` — env routing for all 3 environments
- `TestGetEmbeddingFunction` — patched; correct model passed
- `TestBuildChromaClient` — injection, defaults
- `TestChromaClientGetOrCreateCollection` — create, cache, distinct
- `TestChromaClientListCollections` — empty, populated
- `TestChromaClientAddDocuments` — count, empty no-op, mismatch error,
  metadata stored
- `TestChromaClientQueryDocuments` — empty collection, n_results cap,
  where filter, result keys
- `TestChromaClientDeleteDocuments` — reduces count, empty no-op
- `TestChromaClientResetCollection` — wipes docs, non-existent OK
- `TestIngestNewsArticles` — 10 docs, IDs, metadata, determinism, empty
- `TestIngestTranscript` — chunks, metadata, blank text
- `TestSemanticSearch` — results, company filter, empty
- `TestAcceptanceCriteria` — **10 docs embedded + retrieved** ✓

### Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_chroma_client.py -v
# → 50+ passed

python -m pytest --tb=short
# → all passed, 0 regressions
```

### LangSmith Trace

_Not applicable — infrastructure module with no LLM calls. Traces
appear when the News Sentiment Agent calls `semantic_search()` in
T-024 (Phase 2)._

### Screenshots

Terminal showing `50+ passed` with `TestAcceptanceCriteria` tests visible.

### Related Issues

Closes #17

---

## Architecture Notes

### Environment routing decision

| Environment   | Client             | Rationale                                        |
| ------------- | ------------------ | ------------------------------------------------ |
| `test`        | `EphemeralClient`  | In-process memory; no Docker/disk needed in CI   |
| `development` | `PersistentClient` | Survives process restarts during dev iteration   |
| `production`  | `HttpClient`       | Separate Docker container; survives API restarts |

This means no code change is needed when promoting from dev to prod —
just change the `ENVIRONMENT` variable.

### Why inject the embedding function?

`SentenceTransformerEmbeddingFunction` downloads the `all-MiniLM-L6-v2`
model (~90 MB) on first call and keeps it in memory. If the EF were
created inside `ChromaClient.__init__`, every test that constructs a
client would trigger a model download in CI. By injecting it:

```python
# production
client = ChromaClient(get_chroma_client(), get_embedding_function())

# tests — no download, no network
ef = MagicMock()
ef.side_effect = lambda texts: [[0.1] * 384 for _ in texts]
client = ChromaClient(chromadb.EphemeralClient(), ef)
```

### Chunking strategy for transcripts

```
Q2 earnings call transcript text (2000 chars):
  Chunk 0: text[0:500]     (chars 0–499)
  Chunk 1: text[450:950]   (chars 450–949, overlaps 50 chars with chunk 0)
  Chunk 2: text[900:1400]  (chars 900–1399, overlaps 50 chars with chunk 1)
  Chunk 3: text[1350:1850] (...)
  Chunk 4: text[1800:2000] (final, shorter)
```

Each chunk stores `chunk_index` and `total_chunks` in metadata so agents
can reconstruct the full context if needed by retrieving all chunks.

### Deterministic document IDs

```python
# Same article URL → same ID every ingestion run
_url_to_id("https://economictimes.com/tcs-q2") → "news_3a9f2b1c4e5d6a7f"

# Same transcript key → same base ID → same chunk IDs
_text_to_id("TCS.NS:Q2FY24:screener.in") → "transcript_8b1c2d3e4f5a6b7c"
# Chunk IDs: transcript_8b1c2d3e4f5a6b7c_chunk0000, _chunk0001, ...
```

### How agents use ChromaDB (Phase 2 preview)

```python
# Inside NewsSentimentAgent (T-024)
from backend.db.chroma_client import semantic_search, COLLECTION_NEWS

relevant_news = semantic_search(
    query="TCS revenue guidance cut",
    collection_name=COLLECTION_NEWS,
    n_results=10,
    company_filter="TCS",
)
# relevant_news is a list of dicts with id, document, distance, metadata
headlines = [r["title"] for r in relevant_news]
```

### Output model structure

```
ChromaClient.query_documents() returns list[dict]:
  {
    "id":          str,          # document ID (e.g. "news_3a9f2b1c...")
    "document":    str,          # raw embedded text
    "distance":    float,        # cosine distance (0 = identical)
    "company":     str,          # metadata: company name
    "ticker":      str,          # metadata: stock ticker
    "doc_type":    str,          # metadata: news | transcript | annual_report
    "title":       str,          # news only
    "url":         str,          # news only
    "source_name": str,          # news only
    "published_at": str,         # news only
    "source":      str,          # transcript only
    "date":        str,          # transcript only
    "chunk_index": int,          # transcript only
    "total_chunks": int,         # transcript only
  }
```

---

## EOD Update Template

```
EOD Update [DATE]:
Completed: T-017
Merged to main: feat/data-chromadb
Current week: 3 | Current phase: 1
Blocker: None
Next session: T-018 — Setup Redis caching layer
  (cache decorator for all data tools; TTL: stock=15min, news=1h,
   macro=24h, ratios=1h; Upstash Redis via REDIS_URL)
```
