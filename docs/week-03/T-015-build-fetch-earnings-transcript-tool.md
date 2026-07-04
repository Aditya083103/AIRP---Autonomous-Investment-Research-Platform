# T-015 — Build `fetch_earnings_transcript` Tool

**Phase:** 1 — Data Layer & APIs
**Week:** 3
**Branch:** `feat/data-transcript`
**Commit prefix:** `feat(data):`
**PR title:** `feat(data): implement earnings transcript fetcher (Screener scrape + PDF upload)`

---

## Overview

Implements T-015: a LangChain tool that retrieves the latest earnings-call
(concall) transcript for an Indian listed company and returns it as a
fully-typed `TranscriptResult` Pydantic model.

The tool supports two data paths:

| Path                   | Trigger                                                       | Cache?          |
| ---------------------- | ------------------------------------------------------------- | --------------- |
| **Screener.in scrape** | No `pdf_bytes` / `pdf_path` supplied                          | ✅ Redis 1h TTL |
| **PDF upload**         | `pdf_bytes` (raw bytes from upload) or `pdf_path` (disk path) | ❌ Never cached |

**Two tools delivered:**

| Tool                        | Data returned                                                                                                                    |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `fetch_earnings_transcript` | Full `TranscriptResult` — `transcript_text`, `transcript_chunk`, `source`, `quarter`, `year`, `char_count`, `cached`, `warnings` |
| `fetch_transcript_chunk`    | Lightweight: `transcript_chunk` + metadata only (saves LLM tokens in the debate viewer)                                          |

**Screener.in scrape strategy (three fallbacks in order):**

| Strategy                     | How                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------- |
| 1. `div.concall-content`     | Direct CSS selector for embedded transcript block                                     |
| 2. Keyword-based largest div | Finds the widest `<div>` containing earnings-call keywords (operator, CFO, CEO, etc.) |
| 3. Linked PDF on page        | Follows `<a href="*.pdf">` links on the concalls page and extracts text via pdfminer  |

**Key production features:**

- `_company_to_slug` resolves common aliases (Infosys → INFY, TCS → TCS,
  Reliance → RELIANCE) via an override table before falling back to the
  ticker symbol.
- `_http_get` raises a typed `TranscriptBlockedError` on bot-block signals
  (401/403/406/429/451/503) and `TranscriptScrapeError` on other non-200
  statuses.
- Tenacity retry on `TranscriptBlockedError`: 3 attempts, exp back-off 2s → 60s.
- `_extract_quarter_year` parses quarter/year from page title or transcript
  text using a single regex (`Q[1-4]\s*F?Y\s*\d{2,4}`).
- **Redis cache, 1h TTL** (`settings.cache_ttl_news`). Empty-text results
  (≤ 100 chars) are NOT cached. PDF-upload results are never cached.
  `force_refresh=True` bypasses the read side.
- Standard error-dict return — both `@tool`s always return a dict the agent
  can inspect, never an exception. Agents route on the `error` key.
- `transcript_chunk` is capped at `max_chunk_chars` (default 4000) with a
  hard ceiling at `MAX_CHUNK_HARD_LIMIT = 20_000`.
- PDF extraction uses pdfminer.six (pulled in by weasyprint) with PyPDF2
  as a fallback; raises `PDFExtractionError` if neither is available.

**Acceptance criteria (from task spec):**

- Returns transcript text for Infosys, TCS, Reliance (scrape path) ✅
- PDF upload path works (`pdf_bytes` / `pdf_path` both tested) ✅
- Fails gracefully if scrape is blocked — returns error dict, never raises ✅
- Cached in Redis for 1h (`cache_ttl_news = 3600`) ✅

---

## Files Created in This Task

| File                                             | Action     | Purpose                                                                                                                                                                     |
| ------------------------------------------------ | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/tools/earnings_transcript.py`           | **CREATE** | Two LangChain tools, `TranscriptResult` / `TranscriptChunk` models, Screener.in scraper with three-strategy fallback, pdfminer PDF extractor, slug resolver, quarter parser |
| `backend/tests/unit/test_earnings_transcript.py` | **CREATE** | 40 unit tests — all HTTP mocked, all PDF extraction mocked, covers scrape strategies, PDF paths, cache, error dicts, chunk cap, model validation                            |

> **Note on pdfminer.six availability.** pdfminer.six is a transitive
> dependency of weasyprint (already in `requirements.txt`), so it is
> available in all environments without a new explicit pin. The import is
> done lazily inside `_extract_text_from_pdf_bytes` so the module-level
> import never fails if weasyprint's dependency graph changes.

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Checkout feature branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feat/data-transcript
git branch
# → * feat/data-transcript
```

---

### Step 2 — Place the files

Place the two files at their exact paths in the repo root:

```
backend/tools/earnings_transcript.py
backend/tests/unit/test_earnings_transcript.py
```

No other files are modified in this task.

---

### Step 3 — Run the test suite (offline, mocked)

```bash
# Windows
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_earnings_transcript.py -v

# macOS / Linux / Git Bash
ENVIRONMENT=test python -m pytest backend/tests/unit/test_earnings_transcript.py -v
```

Expected output:

```
backend/tests/unit/test_earnings_transcript.py::TestCompanyToSlug::test_exact_lowercase_override PASSED
backend/tests/unit/test_earnings_transcript.py::TestCompanyToSlug::test_exact_override_with_full_name PASSED
...
backend/tests/unit/test_earnings_transcript.py::TestFetchTranscriptChunkTool::test_chunk_tool_propagates_error PASSED

========= 40 passed in X.Xs =========
```

Then run the full suite to confirm no regressions:

```bash
python -m pytest --tb=short
# → all passed (T-010 through T-015 tests)
```

---

### Step 4 — Run pre-commit hooks

```bash
git add backend/tools/earnings_transcript.py \
        backend/tests/unit/test_earnings_transcript.py
git commit -m "feat(data): implement earnings transcript fetcher (Screener scrape + PDF upload)"
```

If pre-commit auto-fixes formatting (black / isort), the commit will abort.
Run again:

```bash
git add .
git commit -m "feat(data): implement earnings transcript fetcher (Screener scrape + PDF upload)"
```

---

### Step 5 — Push the branch

```bash
git push origin feat/data-transcript
```

CI will trigger automatically on push.

---

### Step 6 — Open Pull Request on GitHub

**PR Title:**

```
feat(data): implement earnings transcript fetcher (Screener scrape + PDF upload)
```

**PR Description (copy–paste):**

````markdown
## Summary

Implements T-015: `fetch_earnings_transcript` and `fetch_transcript_chunk`
LangChain tools that retrieve the latest concall transcript for an Indian
listed company from Screener.in or from a caller-supplied PDF. Returns a
fully-typed `TranscriptResult` Pydantic model. Follows all established
Phase 1 data-tool patterns (internal `_fetch_*` function, error-dict
return, Redis cache, tenacity retry).

## Changes

- `backend/tools/earnings_transcript.py` — new file
  - `fetch_earnings_transcript` tool: Screener.in scrape + PDF upload path
  - `fetch_transcript_chunk` tool: lightweight excerpt-only variant
  - `TranscriptResult` / `TranscriptChunk` Pydantic output models
  - `_company_to_slug` — alias table + ticker fallback (TCS, INFY, RELIANCE…)
  - `_scrape_screener_transcript` — three-strategy fallback scraper
  - `_extract_text_from_pdf_bytes` / `_extract_text_from_pdf_path` — pdfminer
  - `_http_get` — tenacity-retried with `TranscriptBlockedError` on 403/429/503
  - `_extract_quarter_year` — regex-based quarter/year parser
  - Redis cache: 1h TTL, empty results not cached, PDF paths never cached

- `backend/tests/unit/test_earnings_transcript.py` — new file
  - 40 unit tests; all HTTP and PDF calls mocked; runs fully offline

## Testing

```bash
set ENVIRONMENT=test   # or: export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_earnings_transcript.py -v
# → 40 passed
python -m pytest --tb=short
# → all passed, 0 regressions
```
````

## LangSmith Trace

Not applicable — data tool with no LLM calls. Traces appear when the
News Sentiment Agent calls this tool in Phase 2 (T-023).

## Screenshots

Terminal output showing `40 passed` with test class names visible.

## Related Issues

Closes #15

```

---

## Architecture Notes

### Data source decision: Screener.in over Bombay Stock Exchange

Screener.in aggregates concall transcripts from NSE/BSE disclosures and
displays them on a predictable URL (`/company/<TICKER>/concalls/`). The
page is publicly accessible and embeds the transcript text directly in the
HTML for many large-cap companies. This is more reliable than scraping NSE
or BSE directly, where the same disclosure is buried in ZIP archives.

For companies where Screener does not embed the text, it links to the
original exchange PDF. The tool follows those PDF links and extracts text,
so the three-strategy fallback covers the realistic range of page layouts.

### Three-strategy scraper design

```

_scrape_screener_transcript(company_name, ticker, base_url)
│
├── 1. _http_get(url) → BeautifulSoup parse
│ ├── Strategy 1: soup.select_one("div.concall-content") → text
│ ├── Strategy 2: find largest <div> with keyword match → text
│ └── Strategy 3: find <a href="*.pdf"> → fetch PDF → extract text
│
├── any TranscriptBlockedError (403/429/503) → re-raised → caller → error dict
├── no text found → TranscriptScrapeError → caller → error dict
└── success → (transcript_text, quarter, year, warnings)

```

Strategy 1 is zero-overhead when the selector matches. Strategy 2 is a
safety net for pages that embed transcripts in ad-hoc wrappers. Strategy 3
handles companies whose Screener page links out to BSE/NSE PDFs rather than
embedding text directly.

### Slug override table rationale

Screener.in uses the NSE ticker symbol as the URL slug. The override table
maps the most common human-readable company names that agents or users are
likely to send. Names not in the table fall through to ticker stripping
(`TCS.NS` → `TCS`), which works for any company whose name is passed as a
proper NSE ticker.

### Cache strategy

```

_fetch_earnings_transcript(company_name, ticker, ...)
│
├── pdf_bytes provided → extract → return (no cache)
├── pdf_path provided → extract → return (no cache)
│
├── cache_get_json("airp:transcript:tcs") → hit → return cached=True
│
└── _scrape_screener_transcript(...)
└── success → result
├── len(text) > 100 → cache_set_json(key, result, ttl=3600)
└── len(text) ≤ 100 → skip cache (don't pollute with empty)

```

PDF results are not cached because the PDF bytes came from the user's
session; storing them in Redis would waste memory on potentially large binary
conversions. The scrape path is cached at 1h to align with the news cache
TTL — both change on a similar timescale (per quarter for transcripts, per
hour for news headlines).

### Output model structure

```

TranscriptResult
├── company_name: str
├── ticker: str
├── exchange: str ("NSE")
├── transcript_text: str full raw transcript
├── transcript_chunk: str first max_chunk_chars characters
├── source: str "screener" | "pdf_upload" | "pdf_path"
├── quarter: str e.g. "Q3 FY2024" (empty if not found)
├── year: str e.g. "2024" (empty if not found)
├── char_count: int len(transcript_text)
├── fetched_at: datetime UTC
├── cached: bool
└── warnings: list[str]

TranscriptChunk (lightweight)
├── company_name, ticker, transcript_chunk
├── quarter, year, source, char_count
├── fetched_at, cached, warnings
└── (no transcript_text — omitted to save LLM tokens)

````

### How the News Sentiment Agent uses this tool (Phase 2 — T-023)

```python
# Inside NewsSentimentAgent
from backend.tools.earnings_transcript import fetch_earnings_transcript

result = fetch_earnings_transcript.invoke({
    "company_name": "Infosys",
    "ticker": "INFY.NS",
})

if "error" in result:
    warnings.append(result["message"])
    # Proceed without transcript context
else:
    transcript_chunk = result["transcript_chunk"]  # first 4000 chars
    quarter = result["quarter"]                    # e.g. "Q3 FY2024"
    # Embed chunk into agent prompt for RAG-style context injection
````

### ChromaDB integration (T-016)

T-016 will consume `transcript_text` from this tool and chunk-embed it into
ChromaDB using `sentence-transformers`. This tool is deliberately responsible
only for fetching and parsing — storage and embedding are out of scope for
T-015. The `char_count` field helps T-016 decide whether to chunk before
embedding.

### Tool-name reconciliation (`README.md`)

`backend/tools/README.md` currently lists `fetch_concall_transcript` as a
placeholder name. This task ships the tool as `fetch_earnings_transcript`
(matching the task spec). The README line is left for a docs-sync pass so
this PR stays focused on the tool (same approach as T-013, T-014).

---

## Test Coverage Summary

**`backend/tests/unit/test_earnings_transcript.py`** (40 tests)

- `TestCompanyToSlug` — exact override, partial override, ticker fallback,
  BSE suffix strip, last-resort first word (10 tests)
- `TestExtractQuarterYear` — Q3 FY2024, Q1FY24, Q2 FY 2023, no match,
  2-digit year normalisation, case-insensitive (6 tests)
- `TestHttpGet` — 200 OK, 401/403/406/429/451/503 → blocked, 404/500/502
  → scrape error, Timeout propagates (10 tests across `TestHttpGet`)
- `TestScrapeScreenerTranscript` — concall-div path, keyword-fallback path,
  PDF-link fallback, empty page → error, blocked → raises (5 tests)
- `TestPDFExtraction` — bytes delegation, import error, path not found,
  path success, path pdfminer error (5 tests)
- `TestFetchEarningsTranscriptPDFUpload` — source="pdf_upload", no cache
  written, empty → error, pdfminer error → error, quarter extracted (5 tests)
- `TestFetchEarningsTranscriptPDFPath` — source="pdf_path", missing file,
  bypasses cache (3 tests)
- `TestFetchEarningsTranscriptScrape` — happy path TCS/Infosys/Reliance,
  blocked, scrape error, unexpected error, cache hit → cached=True,
  short text not cached, force_refresh, cache key contains slug (10 tests)
- `TestTranscriptChunkCap` — chunk capped at max_chunk_chars, hard cap (2 tests)
- `TestTranscriptResultModel` — invalid source raises, text stripped,
  valid screener/pdf_upload, warnings default empty (5 tests)
- `TestFetchEarningsTranscriptTool` / `TestFetchTranscriptChunkTool` —
  tool delegates, error propagation, drops full text (5 tests)

### Testing Commands

```bash
# Run T-015 tests only
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_earnings_transcript.py -v

# Full suite — confirm no regressions
python -m pytest --tb=short

# With coverage
python -m pytest \
  --cov=backend \
  --cov-report=term-missing \
  backend/tests/unit/test_earnings_transcript.py -v
```

---

## EOD Update Template

```
EOD Update [DATE]:
Completed: T-015
Merged to main: feat/data-transcript
Current week: 3 | Current phase: 1
Blocker: None
Next session: T-016 — Setup ChromaDB vector store + embed earnings transcripts
  (chunk TranscriptResult.transcript_text → sentence-transformers embeddings
   → store in ChromaDB collection for RAG retrieval by News Sentiment Agent)
```
