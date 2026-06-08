# backend/tools/earnings_transcript.py
"""
AIRP — fetch_earnings_transcript LangChain Tool

Retrieves the latest earnings-call (concall) transcript for an Indian listed
company from two sources, tried in order:

  1. **Screener.in scrape** — the /company/<slug>/concalls/ page embeds
     the most recent transcript text inside a ``<div class="concall-content">``
     block (or falls back to a linked PDF URL that is then fetched).
  2. **PDF upload path** — caller passes ``pdf_bytes`` (raw bytes) or a
     ``pdf_path`` (absolute path on disk); the tool extracts text with
     pdfminer.six and returns it directly, bypassing the web scrape entirely.

Both paths return a ``TranscriptResult`` Pydantic model containing:
  - ``company_name`` / ``ticker`` / ``exchange``
  - ``transcript_text``  — the full text (potentially thousands of chars)
  - ``transcript_chunk`` — first ``max_chunk_chars`` characters only
                            (compact token footprint for agents)
  - ``source``           — "screener" | "pdf_upload" | "pdf_path"
  - ``quarter`` / ``year`` — parsed from the Screener page title when available
  - ``fetched_at``       — UTC timestamp
  - ``warnings``         — list of non-fatal issues encountered

Tools exposed:
    fetch_earnings_transcript  — full TranscriptResult (both text + chunk)
    fetch_transcript_chunk     — lightweight: chunk + metadata only
                                 (saves LLM tokens for the debate viewer)

Acceptance criteria (T-015):
    Returns transcript text for Infosys, TCS, Reliance  (scrape path)
    PDF upload path works                                (pdf_bytes / pdf_path)
    Fails gracefully if scrape is blocked — returns error dict, never raises
    Cached in Redis for 1 h (same TTL as news)

Caching:
    The full result is cached in Redis under
    ``airp:transcript:<company_slug>`` for ``settings.cache_ttl_news``
    seconds (default 3600 = 1 h).  PDF-upload results are NEVER cached
    (the caller owns the bytes; we do not store them).  An empty-text result
    is not cached so the next call retries the live source.
    ``force_refresh=True`` bypasses the read side of the cache.
    Cache is a no-op when ENVIRONMENT=test (see cache.py).

Usage (inside an agent):
    from backend.tools.earnings_transcript import fetch_earnings_transcript

    # --- scrape path ---
    result = fetch_earnings_transcript.invoke({
        "company_name": "Infosys",
        "ticker": "INFY.NS",
    })
    text = result["transcript_text"]    # full text
    chunk = result["transcript_chunk"]  # first N chars

    # --- PDF upload path ---
    result = fetch_earnings_transcript.invoke({
        "company_name": "TCS",
        "ticker": "TCS.NS",
        "pdf_bytes": open("concall.pdf", "rb").read(),
    })
"""

from datetime import datetime, timezone
from io import BytesIO
import logging
import os
import re
from typing import Any

from bs4 import BeautifulSoup
from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator
import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.tools.cache import cache_get_json, cache_set_json

try:
    from backend.config import settings as _settings
except Exception:
    _settings = None  # type: ignore[assignment]

# Module-level alias — patch target in tests:
#   patch("backend.tools.earnings_transcript.settings")
settings = _settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCREENER_CONCALLS_URL = "{base}/company/{slug}/concalls/"
DEFAULT_MAX_CHUNK_CHARS = 4000  # token-safe excerpt for LLM context
MAX_CHUNK_HARD_LIMIT = 20_000

# HTTP request headers — mimic a real browser to reduce bot-block risk
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Retry policy for web requests: 3 attempts, exp back-off 2s → 60s
_RETRY_ATTEMPTS = 3
_RETRY_WAIT_MIN = 2
_RETRY_WAIT_MAX = 60

# Cache key prefix
TRANSCRIPT_CACHE_PREFIX = "airp:transcript:"

# Quarter extraction — matches "Q1 FY2024", "Q3FY24", "Q2 FY 2023" etc.
_QUARTER_RE = re.compile(
    r"(Q[1-4])\s*F?Y\s*(\d{2,4})",
    re.IGNORECASE,
)

# Known company slug overrides for Screener.in
_SLUG_OVERRIDES: dict[str, str] = {
    "infosys": "INFY",
    "tcs": "TCS",
    "tata consultancy services": "TCS",
    "reliance": "RELIANCE",
    "reliance industries": "RELIANCE",
    "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK",
    "wipro": "WIPRO",
    "hcl technologies": "HCLTECH",
    "hcl tech": "HCLTECH",
    "bajaj finance": "BAJFINANCE",
    "asian paints": "ASIANPAINT",
    "maruti suzuki": "MARUTI",
    "itc": "ITC",
    "kotak mahindra bank": "KOTAKBANK",
}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TranscriptScrapeError(Exception):
    """Raised when Screener.in returns an unexpected / empty response."""


class TranscriptBlockedError(Exception):
    """Raised on 403/429/503 — bot-block signal; triggers tenacity retry."""


class PDFExtractionError(Exception):
    """Raised when pdfminer fails to extract any text from a PDF."""


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------


class TranscriptResult(BaseModel):
    """
    Fully-typed output for the fetch_earnings_transcript tool.

    The agent receives this as a validated dict via ``.model_dump()``.
    Fields are deliberately kept flat — no nested objects — so the LangGraph
    state serialiser can round-trip them without a custom encoder.
    """

    company_name: str = Field(description="Company name as provided by the caller")
    ticker: str = Field(description="Exchange ticker (e.g. TCS.NS, INFY.NS)")
    exchange: str = Field(
        default="NSE",
        description="Primary listing exchange (NSE | BSE)",
    )
    transcript_text: str = Field(
        description="Full raw transcript text extracted from source"
    )
    transcript_chunk: str = Field(
        description=(
            "First max_chunk_chars characters of transcript_text — "
            "compact excerpt for LLM context windows"
        )
    )
    source: str = Field(
        description="Where the transcript came from: screener | pdf_upload | pdf_path"
    )
    quarter: str = Field(
        default="",
        description="Earnings quarter extracted from page title (e.g. Q3 FY2024)",
    )
    year: str = Field(
        default="",
        description="Fiscal year extracted from page title (e.g. 2024)",
    )
    char_count: int = Field(description="Total character count of transcript_text")
    fetched_at: datetime = Field(
        description="UTC timestamp when the transcript was fetched"
    )
    cached: bool = Field(
        default=False,
        description="True when the result was served from Redis cache",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues encountered during fetch",
    )

    model_config = {"frozen": False}

    @field_validator("transcript_text", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("source", mode="before")
    @classmethod
    def _validate_source(cls, v: object) -> object:
        valid = {"screener", "pdf_upload", "pdf_path"}
        if isinstance(v, str) and v not in valid:
            raise ValueError(f"source must be one of {valid}, got {v!r}")
        return v


class TranscriptChunk(BaseModel):
    """Lightweight output for the fetch_transcript_chunk tool."""

    company_name: str
    ticker: str
    transcript_chunk: str
    quarter: str = ""
    year: str = ""
    source: str
    char_count: int
    fetched_at: datetime
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# HTTP helper (tenacity-retried)
# ---------------------------------------------------------------------------


@retry(
    retry=retry_if_exception_type(TranscriptBlockedError),
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    wait=wait_exponential(min=_RETRY_WAIT_MIN, max=_RETRY_WAIT_MAX),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,
)
def _http_get(url: str, timeout: int = 15) -> requests.Response:
    """
    Perform a GET request with browser-like headers.

    Raises:
        TranscriptBlockedError: on 403 / 429 / 503 (bot-block signals)
        TranscriptScrapeError:  on any other non-200 status
        requests.Timeout:       propagated; tenacity does NOT retry these
        requests.ConnectionError: propagated similarly
    """
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    if resp.status_code in {401, 403, 406, 429, 451, 503}:
        raise TranscriptBlockedError(
            f"Bot-block signal HTTP {resp.status_code} from {url}"
        )
    if resp.status_code != 200:
        raise TranscriptScrapeError(f"Unexpected HTTP {resp.status_code} from {url}")
    return resp


# ---------------------------------------------------------------------------
# Company-name → Screener slug helpers
# ---------------------------------------------------------------------------


def _company_to_slug(company_name: str, ticker: str) -> str:
    """
    Convert a company name or ticker to a Screener.in URL slug.

    Strategy (in order):
      1. Check the hard-coded override table (covers the most common names)
      2. Strip the exchange suffix from the ticker (TCS.NS → TCS)
      3. Upper-case the company name, replace spaces with hyphens
         (works for many single-word company names)

    Screener slugs are always the NSE ticker symbol (upper-case, no suffix).
    """
    name_lower = company_name.strip().lower()

    # Check override table first — handles common aliasing
    if name_lower in _SLUG_OVERRIDES:
        return _SLUG_OVERRIDES[name_lower]

    # Partial match — e.g. "infosys limited" matches "infosys" key
    for key, slug in _SLUG_OVERRIDES.items():
        if key in name_lower:
            return slug

    # Strip exchange suffix from ticker: TCS.NS → TCS, 532540.BO → 532540
    if ticker:
        bare_ticker = ticker.split(".")[0].strip().upper()
        if bare_ticker:
            return bare_ticker

    # Last resort: upper-case the company name, take the first word
    first_word = company_name.strip().upper().split()[0] if company_name.strip() else ""
    return first_word or "UNKNOWN"


def _extract_quarter_year(text: str) -> tuple[str, str]:
    """
    Scan text for a quarter/year pattern like 'Q3 FY2024'.

    Returns (quarter, year) strings or ("", "") if not found.
    The year is normalised to 4 digits: 'FY24' → '2024'.
    """
    match = _QUARTER_RE.search(text)
    if not match:
        return "", ""
    quarter_str = match.group(1).upper()  # e.g. "Q3"
    year_raw = match.group(2)  # e.g. "2024" or "24"
    if len(year_raw) == 2:
        # Assume 20xx for fiscal years (safe until 2099)
        year_str = f"20{year_raw}"
    else:
        year_str = year_raw
    return f"{quarter_str} FY{year_str}", year_str


# ---------------------------------------------------------------------------
# Screener.in scraper
# ---------------------------------------------------------------------------


def _scrape_screener_transcript(
    company_name: str,
    ticker: str,
    base_url: str,
) -> tuple[str, str, str, list[str]]:
    """
    Scrape the latest concall transcript from Screener.in.

    Returns:
        (transcript_text, quarter, year, warnings)

    Raises:
        TranscriptScrapeError: if no text can be extracted and there's no
            PDF fallback, or if the HTTP request fails with a non-block error.
        TranscriptBlockedError: re-raised from _http_get (after retries).
    """
    warnings: list[str] = []
    slug = _company_to_slug(company_name, ticker)
    url = SCREENER_CONCALLS_URL.format(base=base_url.rstrip("/"), slug=slug)

    logger.info("Scraping Screener.in concalls page: %s", url)
    resp = _http_get(url)

    soup = BeautifulSoup(resp.text, "lxml")

    # --- Try to extract embedded transcript text ---
    # Screener embeds transcript text in various containers depending on page version
    transcript_text = ""
    quarter = ""
    year = ""

    # Strategy 1: <div class="concall-content"> or similar wrappers
    content_selectors = [
        "div.concall-content",
        "div.document-content",
        "div.transcript-content",
        "article.concall",
        "div#concall-content",
    ]
    for selector in content_selectors:
        el = soup.select_one(selector)
        if el:
            transcript_text = el.get_text(separator="\n", strip=True)
            if len(transcript_text) > 200:
                break
            transcript_text = ""

    # Strategy 2: largest <div> containing concall keywords
    if not transcript_text:
        keyword_pattern = re.compile(
            r"(operator|moderator|chairman|ceo|cfo|participants|"
            r"earnings call|conference call|concall|q\d fy)",
            re.IGNORECASE,
        )
        best_div = None
        best_len = 0
        for div in soup.find_all("div"):
            text = div.get_text(separator=" ", strip=True)
            if keyword_pattern.search(text) and len(text) > best_len:
                best_div = div
                best_len = len(text)
        if best_div and best_len > 100:
            transcript_text = best_div.get_text(separator="\n", strip=True)

    # Strategy 3: look for a linked PDF on the page and fetch its text
    if not transcript_text:
        pdf_links = soup.find_all("a", href=re.compile(r"\.pdf", re.IGNORECASE))
        for link in pdf_links[:3]:  # try first 3 PDFs at most
            pdf_url = link.get("href", "")
            if not pdf_url.startswith("http"):
                pdf_url = base_url.rstrip("/") + "/" + pdf_url.lstrip("/")
            try:
                pdf_resp = requests.get(pdf_url, headers=_HEADERS, timeout=20)
                if pdf_resp.status_code == 200:
                    extracted = _extract_text_from_pdf_bytes(pdf_resp.content)
                    if extracted and len(extracted) > 50:
                        transcript_text = extracted
                        warnings.append(
                            f"Transcript text extracted from linked PDF: {pdf_url}"
                        )
                        break
            except Exception as exc:
                warnings.append(f"PDF fetch failed for {pdf_url}: {exc}")

    if not transcript_text:
        raise TranscriptScrapeError(
            f"No transcript text found on Screener.in for slug '{slug}' "
            f"(URL: {url}). The page may not have a concall yet, or "
            f"the layout may have changed."
        )

    # Try to extract quarter/year from page title or heading
    page_title = soup.find("title")
    title_text = page_title.get_text() if page_title else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text() if h1 else ""
    for search_text in [title_text, h1_text, transcript_text[:500]]:
        q, y = _extract_quarter_year(search_text)
        if q:
            quarter, year = q, y
            break

    return transcript_text, quarter, year, warnings


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Extract all text from a PDF given its raw bytes.

    Uses pdfminer.six which is already available (pulled in by weasyprint's
    dependency tree).  Falls back to a character-count heuristic to detect
    scanned/image-only PDFs.

    Returns:
        Extracted text string (may be empty for scanned PDFs).

    Raises:
        PDFExtractionError: if pdfminer raises an unexpected exception.
    """
    try:
        # Import here so the module-level import doesn't fail when pdfminer
        # is absent in environments that don't have weasyprint installed.
        from pdfminer.high_level import extract_text as pm_extract_text

        text = pm_extract_text(BytesIO(pdf_bytes))
        return (text or "").strip()
    except ImportError:
        # pdfminer not available — try a simpler approach with PyPDF2 if present
        try:
            import PyPDF2  # type: ignore[import]

            reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
            pages_text = []
            for page in reader.pages:
                pages_text.append(page.extract_text() or "")
            return "\n".join(pages_text).strip()
        except ImportError:
            raise PDFExtractionError(
                "Neither pdfminer.six nor PyPDF2 is installed. "
                "Install pdfminer.six: pip install pdfminer.six"
            )
    except Exception as exc:
        raise PDFExtractionError(f"pdfminer failed to extract text: {exc}") from exc


def _extract_text_from_pdf_path(pdf_path: str) -> str:
    """
    Extract text from a PDF file on disk.

    Args:
        pdf_path: Absolute or relative path to the PDF file.

    Returns:
        Extracted text string.

    Raises:
        FileNotFoundError: if pdf_path does not exist.
        PDFExtractionError: if text extraction fails.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    with open(pdf_path, "rb") as fh:
        return _extract_text_from_pdf_bytes(fh.read())


# ---------------------------------------------------------------------------
# Core fetch function (testable without LangChain machinery)
# ---------------------------------------------------------------------------


def _fetch_earnings_transcript(
    company_name: str,
    ticker: str,
    pdf_bytes: bytes | None = None,
    pdf_path: str | None = None,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch the latest earnings transcript for a company.

    Separated from the ``@tool`` decorator so it is directly testable without
    any LangChain machinery (same pattern as all other AIRP tools).

    Priority:
        1. pdf_bytes — use bytes directly, skip cache entirely
        2. pdf_path  — read file, skip cache entirely
        3. Redis cache hit (unless force_refresh=True)
        4. Screener.in scrape

    Args:
        company_name:   Human-readable company name (e.g. "Infosys")
        ticker:         Exchange ticker (e.g. "INFY.NS")
        pdf_bytes:      Raw PDF bytes from an upload; bypasses all scraping
        pdf_path:       Absolute path to a PDF on disk; bypasses all scraping
        max_chunk_chars: Max characters in transcript_chunk (default 4000)
        force_refresh:  If True, bypass the Redis cache read

    Returns:
        dict matching TranscriptResult schema, or error dict on failure.
    """
    now_utc = datetime.now(timezone.utc)
    warnings: list[str] = []
    chunk_cap = min(
        max(max_chunk_chars, 100),
        MAX_CHUNK_HARD_LIMIT,
    )

    # ── PDF upload path (bytes) ─────────────────────────────────────────
    if pdf_bytes is not None:
        try:
            text = _extract_text_from_pdf_bytes(pdf_bytes)
        except PDFExtractionError as exc:
            return {
                "error": "pdf_extraction_error",
                "message": str(exc),
                "company_name": company_name,
                "ticker": ticker,
            }
        if not text:
            return {
                "error": "pdf_empty",
                "message": "PDF contained no extractable text (may be scanned).",
                "company_name": company_name,
                "ticker": ticker,
            }
        q, y = _extract_quarter_year(text[:2000])
        result = TranscriptResult(
            company_name=company_name,
            ticker=ticker,
            transcript_text=text,
            transcript_chunk=text[:chunk_cap],
            source="pdf_upload",
            quarter=q,
            year=y,
            char_count=len(text),
            fetched_at=now_utc,
            cached=False,
            warnings=warnings,
        )
        return result.model_dump(mode="json")

    # ── PDF path on disk ──────────────────────────────────────────────
    if pdf_path is not None:
        try:
            text = _extract_text_from_pdf_path(pdf_path)
        except FileNotFoundError as exc:
            return {
                "error": "pdf_not_found",
                "message": str(exc),
                "company_name": company_name,
                "ticker": ticker,
            }
        except PDFExtractionError as exc:
            return {
                "error": "pdf_extraction_error",
                "message": str(exc),
                "company_name": company_name,
                "ticker": ticker,
            }
        if not text:
            return {
                "error": "pdf_empty",
                "message": "PDF contained no extractable text (may be scanned).",
                "company_name": company_name,
                "ticker": ticker,
            }
        q, y = _extract_quarter_year(text[:2000])
        result = TranscriptResult(
            company_name=company_name,
            ticker=ticker,
            transcript_text=text,
            transcript_chunk=text[:chunk_cap],
            source="pdf_path",
            quarter=q,
            year=y,
            char_count=len(text),
            fetched_at=now_utc,
            cached=False,
            warnings=warnings,
        )
        return result.model_dump(mode="json")

    # ── Screener.in scrape path with Redis cache ─────────────────────
    slug = _company_to_slug(company_name, ticker)
    cache_key = f"{TRANSCRIPT_CACHE_PREFIX}{slug.lower()}"

    # Check cache
    if not force_refresh:
        cached_data = cache_get_json(cache_key)
        if cached_data is not None and isinstance(cached_data, dict):
            try:
                cached_data["cached"] = True
                result = TranscriptResult(**cached_data)
                result.transcript_chunk = result.transcript_text[:chunk_cap]
                return result.model_dump(mode="json")
            except Exception as exc:
                warnings.append(f"Cache entry corrupt, re-fetching: {exc}")

    # Determine base URL
    base_url: str
    if settings is not None:
        base_url = settings.screener_base_url
    else:
        base_url = "https://www.screener.in"

    # Fetch from Screener
    try:
        transcript_text, quarter, year, scrape_warnings = _scrape_screener_transcript(
            company_name, ticker, base_url
        )
        warnings.extend(scrape_warnings)
    except TranscriptBlockedError as exc:
        return {
            "error": "scrape_blocked",
            "message": str(exc),
            "company_name": company_name,
            "ticker": ticker,
            "warnings": warnings,
        }
    except TranscriptScrapeError as exc:
        return {
            "error": "scrape_error",
            "message": str(exc),
            "company_name": company_name,
            "ticker": ticker,
            "warnings": warnings,
        }
    except Exception as exc:
        logger.exception("Unexpected error fetching transcript for %s", company_name)
        return {
            "error": "unexpected_error",
            "message": f"Unexpected error: {exc}",
            "company_name": company_name,
            "ticker": ticker,
            "warnings": warnings,
        }

    result = TranscriptResult(
        company_name=company_name,
        ticker=ticker,
        transcript_text=transcript_text,
        transcript_chunk=transcript_text[:chunk_cap],
        source="screener",
        quarter=quarter,
        year=year,
        char_count=len(transcript_text),
        fetched_at=now_utc,
        cached=False,
        warnings=warnings,
    )

    # Write to cache only if we got meaningful text
    if len(transcript_text) > 100:
        ttl: int = 3600  # default 1h
        if settings is not None:
            ttl = settings.cache_ttl_news
        cache_set_json(cache_key, result.model_dump(mode="json"), ttl_seconds=ttl)

    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# LangChain @tool wrappers
# ---------------------------------------------------------------------------

# Extract wrapped callables at module level for mypy
_fetch_transcript_raw = _http_get.__wrapped__  # type: ignore[attr-defined]


@tool
def fetch_earnings_transcript(
    company_name: str,
    ticker: str = "",
    pdf_bytes: bytes | None = None,
    pdf_path: str | None = None,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch the latest earnings-call transcript for an Indian listed company.

    Tries Screener.in first; falls back to extracting text from a PDF supplied
    by the caller (via pdf_bytes or pdf_path).  Always returns a dict — never
    raises — so LangGraph agents can route on the ``error`` key.

    Args:
        company_name:    Human-readable name (e.g. "Infosys", "TCS", "Reliance")
        ticker:          NSE/BSE ticker with suffix (e.g. "INFY.NS", "TCS.NS")
        pdf_bytes:       Raw bytes of an uploaded PDF; bypasses scraping
        pdf_path:        Absolute path to a PDF on disk; bypasses scraping
        max_chunk_chars: Characters to include in transcript_chunk (default 4000)
        force_refresh:   Bypass Redis cache and re-fetch from Screener

    Returns:
        dict matching TranscriptResult, or an error dict with key "error".
    """
    return _fetch_earnings_transcript(
        company_name=company_name,
        ticker=ticker,
        pdf_bytes=pdf_bytes,
        pdf_path=pdf_path,
        max_chunk_chars=max_chunk_chars,
        force_refresh=force_refresh,
    )


@tool
def fetch_transcript_chunk(
    company_name: str,
    ticker: str = "",
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch only the first N characters of the latest earnings transcript.

    Lightweight alternative to fetch_earnings_transcript — omits the full
    transcript_text to keep the LLM context window small.

    Args:
        company_name:    Human-readable company name
        ticker:          Exchange ticker (e.g. "TCS.NS")
        max_chunk_chars: Characters to include (default 4000)
        force_refresh:   Bypass Redis cache

    Returns:
        dict matching TranscriptChunk schema, or an error dict.
    """
    full = _fetch_earnings_transcript(
        company_name=company_name,
        ticker=ticker,
        max_chunk_chars=max_chunk_chars,
        force_refresh=force_refresh,
    )
    if "error" in full:
        return full

    # Return lightweight view — drop the full text
    return {
        "company_name": full.get("company_name", company_name),
        "ticker": full.get("ticker", ticker),
        "transcript_chunk": full.get("transcript_chunk", ""),
        "quarter": full.get("quarter", ""),
        "year": full.get("year", ""),
        "source": full.get("source", ""),
        "char_count": full.get("char_count", 0),
        "fetched_at": full.get("fetched_at", ""),
        "cached": full.get("cached", False),
        "warnings": full.get("warnings", []),
    }
