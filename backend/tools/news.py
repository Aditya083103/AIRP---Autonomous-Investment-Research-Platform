# backend/tools/news.py
"""
AIRP — fetch_news LangChain Tool

Wraps the NewsAPI v2 /everything endpoint to retrieve the last 30 days of
news articles for a given company name. Returns a fully-typed Pydantic model
so the News Sentiment Agent always receives structured, validated data.

Tools exposed:
    fetch_news          — Last 30 days of articles for a company (≥5 for known
                          companies); returns list[NewsArticle] with metadata
    fetch_news_summary  — Same data, summarised as article count + headlines only
                          (lightweight format for the debate viewer)

Rate limiting & retry:
    NewsAPI free tier allows 100 requests/day. This tool uses tenacity to retry
    on HTTP 429 (rate limit) and transient 5xx errors with exponential back-off
    (initial wait 2s, max wait 60s, max 3 attempts). Retry state is logged so
    LangSmith traces show every attempt clearly.

Caching:
    Responses are keyed by (company_name, from_date) and cached in Redis for
    settings.cache_ttl_news seconds (default 3600 = 1 hour) to protect the
    daily quota. Cache is bypassed when ENVIRONMENT=test.

Data source: NewsAPI v2 (https://newsapi.org)
API key:     NEWS_API_KEY environment variable (settings.news_api_key)
Free limit:  100 requests/day (sufficient for dev + demo with caching)

Usage (inside an agent):
    from backend.tools.news import fetch_news
    result = fetch_news.invoke({
        "company_name": "Tata Consultancy Services",
        "ticker": "TCS.NS",           # optional — appended to query
        "max_articles": 20,           # optional, default 20, max 100
    })
    articles = result["articles"]     # list of dicts matching NewsArticle
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator
import requests
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    from backend.config import settings as _settings
except Exception:
    _settings = None  # type: ignore[assignment]

# Module-level alias — patch target in tests:
#   patch("backend.tools.news.settings") replaces this object
settings = _settings

from backend.tools.cache import NEWS_TTL, cached  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"
DEFAULT_MAX_ARTICLES = 20
MAX_ARTICLES_HARD_LIMIT = 100
LOOKBACK_DAYS = 30  # NewsAPI free tier: last 30 days only

# Retry policy: 3 attempts, exponential back-off 2s → 60s
# Retries on 429 (rate limit) and requests.Timeout / ConnectionError
_RETRY_ATTEMPTS = 3
_RETRY_WAIT_MIN = 2  # seconds
_RETRY_WAIT_MAX = 60  # seconds


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class NewsAPIError(Exception):
    """Raised for unrecoverable NewsAPI errors (invalid key, 4xx other than 429)."""


class NewsAPIRateLimitError(Exception):
    """Raised on HTTP 429 — triggers tenacity retry."""


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------


class NewsArticle(BaseModel):
    """A single news article returned by the NewsAPI."""

    title: str = Field(description="Article headline")
    description: str | None = Field(
        default=None,
        description=(
            "Short summary / lead paragraph" " (may be None for some sources)"
        ),
    )
    url: str = Field(description="Full URL to the article")
    source_name: str = Field(
        description="Publisher name (e.g. 'The Hindu Business Line')"
    )
    published_at: datetime = Field(
        description="Publication timestamp in UTC (ISO 8601)"
    )
    content_snippet: str | None = Field(
        default=None,
        description=(
            "First ~200 chars of article body as returned by NewsAPI "
            "(full text requires NewsAPI paid tier)"
        ),
    )

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Article title must not be empty")
        return v

    @field_validator("url")
    @classmethod
    def url_must_start_with_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"Article URL does not look valid: {v!r}")
        return v

    model_config = {"frozen": True}


class NewsResult(BaseModel):
    """
    Complete output model for the fetch_news tool.

    Always contains a valid list (possibly empty) and metadata fields so
    agents can make decisions even when few articles are returned.
    """

    company_name: str = Field(description="Company name used in the search query")
    ticker: str | None = Field(
        default=None,
        description="Optional ticker appended to the search query",
    )
    query_used: str = Field(description="Exact query string sent to NewsAPI")
    from_date: str = Field(description="Start date of the lookback window (YYYY-MM-DD)")
    to_date: str = Field(description="End date of the lookback window (YYYY-MM-DD)")
    total_results: int = Field(
        description=(
            "Total matching articles reported by NewsAPI" " (may exceed max_articles)"
        )
    )
    articles_returned: int = Field(
        description="Number of articles in the articles list"
    )
    articles: list[NewsArticle] = Field(
        description="News articles sorted by publishedAt descending (most recent first)"
    )
    fetched_at: datetime = Field(description="UTC timestamp of this API call")
    source: str = Field(default="newsapi", description="Data provider identifier")
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings (e.g. fewer articles than requested)",
    )

    @field_validator("company_name")
    @classmethod
    def company_name_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("company_name must not be empty")
        return v


# ---------------------------------------------------------------------------
# Internal: API call with tenacity retry
# ---------------------------------------------------------------------------


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Return True if the exception signals an HTTP 429 from NewsAPI."""
    return isinstance(exc, NewsAPIRateLimitError)


def _is_transient_error(exc: BaseException) -> bool:
    """Return True for network-level transient errors worth retrying."""
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


@retry(
    retry=(
        retry_if_exception_type(NewsAPIRateLimitError)
        | retry_if_exception_type(requests.Timeout)
        | retry_if_exception_type(requests.ConnectionError)
    ),
    wait=wait_exponential(
        multiplier=1,
        min=_RETRY_WAIT_MIN,
        max=_RETRY_WAIT_MAX,
    ),
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_newsapi(params: dict[str, Any], api_key: str) -> dict[str, Any]:
    """
    Make a single GET request to NewsAPI /everything with retry logic.

    Separated from business logic so tenacity can wrap just the HTTP call,
    not the entire tool function. This also makes it independently testable.

    Raises:
        NewsAPIRateLimitError: on HTTP 429 — tenacity will retry.
        NewsAPIError:          on unrecoverable 4xx (invalid key, bad request).
        requests.Timeout:      on network timeout — tenacity will retry.
        requests.ConnectionError: on DNS/TCP failure — tenacity will retry.
    """
    headers = {
        "X-Api-Key": api_key,
        "User-Agent": "AIRP/1.0 (Autonomous Investment Research Platform)",
    }

    safe_params = {k: v for k, v in params.items() if k != "apiKey"}
    logger.debug("Calling NewsAPI: params=%s", safe_params)

    response = requests.get(
        NEWSAPI_BASE_URL,
        params=params,
        headers=headers,
        timeout=15,
    )

    if response.status_code == 429:
        logger.warning("NewsAPI rate limit hit (HTTP 429) — will retry with back-off")
        raise NewsAPIRateLimitError("NewsAPI rate limit exceeded (HTTP 429)")

    if response.status_code == 401:
        raise NewsAPIError("NewsAPI authentication failed — check NEWS_API_KEY in .env")

    if response.status_code == 400:
        body = response.json()
        raise NewsAPIError(
            f"NewsAPI bad request: {body.get('message', 'unknown error')}"
        )

    if response.status_code >= 500:
        # 5xx are transient; raise ConnectionError so tenacity retries
        raise requests.ConnectionError(
            f"NewsAPI server error HTTP {response.status_code}"
        )

    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Internal: parse raw API response into typed models
# ---------------------------------------------------------------------------


def _parse_articles(raw_articles: list[dict[str, Any]]) -> list[NewsArticle]:
    """
    Convert raw NewsAPI article dicts to validated NewsArticle objects.

    Skips articles that fail Pydantic validation (e.g. missing URL or
    title) and logs a warning rather than crashing the entire tool call.
    """
    parsed: list[NewsArticle] = []

    for raw in raw_articles:
        title = (raw.get("title") or "").strip()
        url = (raw.get("url") or "").strip()

        # NewsAPI sometimes returns [Removed] placeholders
        if title in ("[Removed]", "") or not url:
            continue

        source_name = (raw.get("source") or {}).get("name") or "Unknown"
        description = raw.get("description") or None
        content = raw.get("content") or None

        # publishedAt is always ISO 8601 UTC from NewsAPI
        published_raw = raw.get("publishedAt") or ""
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(
                "Could not parse publishedAt=%r — skipping article",
                published_raw,
            )
            continue

        try:
            article = NewsArticle(
                title=title,
                description=description,
                url=url,
                source_name=source_name,
                published_at=published_at,
                content_snippet=content,
            )
            parsed.append(article)
        except Exception as exc:
            logger.warning("Skipping malformed article %r: %s", title[:50], exc)

    return parsed


# ---------------------------------------------------------------------------
# Core fetch logic (separated from @tool for testability)
# ---------------------------------------------------------------------------


def _fetch_news_from_api(
    company_name: str,
    ticker: str | None = None,
    max_articles: int = DEFAULT_MAX_ARTICLES,
) -> NewsResult:
    """
    Core NewsAPI fetch logic — separated from @tool decorator for testability.

    Builds the search query, calls NewsAPI with retry, parses the response,
    and returns a validated NewsResult. Never raises — all errors are surfaced
    through the tool's error-dict pattern.

    Args:
        company_name: Company display name for the search query.
        ticker:       Optional ticker symbol appended to refine results.
        max_articles: Number of articles to request (capped at 100).

    Raises:
        NewsAPIError:         On invalid API key or bad request.
        NewsAPIRateLimitError: If all retry attempts are exhausted on 429.
        ValueError:           If NEWS_API_KEY is not configured.
    """
    # Resolve API key — prefer env var so tests can override without settings
    api_key = os.environ.get("NEWS_API_KEY", "")
    if not api_key and settings is not None:
        api_key = settings.news_api_key or ""

    if not api_key:
        raise ValueError(
            "NEWS_API_KEY is not set. Add it to your .env file. "
            "Get a free key at https://newsapi.org/register"
        )

    # Build query: company name + optional ticker for precision
    query_parts = [f'"{company_name}"']
    if ticker:
        # Strip exchange suffix for the query (TCS.NS → TCS)
        base_ticker = ticker.split(".")[0].split(":")[0]
        query_parts.append(base_ticker)
    query = " OR ".join(query_parts)

    # Date range: today → 30 days ago (NewsAPI free tier limit)
    now_utc = datetime.now(tz=timezone.utc)
    from_dt = now_utc - timedelta(days=LOOKBACK_DAYS)
    from_date = from_dt.strftime("%Y-%m-%d")
    to_date = now_utc.strftime("%Y-%m-%d")

    capped_max = min(max(1, max_articles), MAX_ARTICLES_HARD_LIMIT)

    params: dict[str, Any] = {
        "q": query,
        "from": from_date,
        "to": to_date,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": capped_max,
        "page": 1,
    }

    logger.info(
        "Fetching news: company=%r query=%r max=%d",
        company_name,
        query,
        capped_max,
    )

    data = _call_newsapi(params=params, api_key=api_key)

    raw_articles = data.get("articles") or []
    total_results = data.get("totalResults") or 0

    articles = _parse_articles(raw_articles)

    warnings: list[str] = []
    if len(articles) < 5 and total_results > 0:
        warnings.append(
            f"Only {len(articles)} articles parsed (NewsAPI reported "
            f"{total_results} total). Some articles may have been filtered "
            "as malformed or removed."
        )
    if total_results == 0:
        warnings.append(
            f"NewsAPI returned 0 results for query {query!r}. "
            "Try a shorter or broader company name."
        )

    return NewsResult(
        company_name=company_name,
        ticker=ticker,
        query_used=query,
        from_date=from_date,
        to_date=to_date,
        total_results=total_results,
        articles_returned=len(articles),
        articles=articles,
        fetched_at=now_utc,
        source="newsapi",
        warnings=warnings,
    )


@cached(key="airp:news:{company_name}", ttl=NEWS_TTL)
def _fetch_news_cached(
    company_name: str,
    ticker: str | None = None,
    max_articles: int = DEFAULT_MAX_ARTICLES,
) -> dict[str, Any]:
    """
    Cached wrapper around ``_fetch_news_from_api``.

    The ``@cached`` decorator handles Redis read-through: hit returns the
    cached dict immediately; miss calls the API, caches the result for
    ``NEWS_TTL`` seconds, and returns it.
    """
    result = _fetch_news_from_api(
        company_name=company_name,
        ticker=ticker,
        max_articles=max_articles,
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def fetch_news(
    company_name: str,
    ticker: str = "",
    max_articles: int = DEFAULT_MAX_ARTICLES,
) -> dict[str, Any]:
    """
    Fetch the last 30 days of English news articles for a company from NewsAPI.

    Returns a list of articles with title, URL, description, source, and
    publication timestamp. Articles are sorted most-recent-first. Handles
    HTTP 429 rate limiting with automatic exponential back-off (up to 3 retries).

    Args:
        company_name: Company display name for the search query.
                      Use the full name for precision:
                      'Tata Consultancy Services' not 'TCS'.
        ticker:       Optional stock ticker (e.g. 'TCS.NS'). When provided,
                      the base ticker (e.g. 'TCS') is OR'd into the query
                      to catch articles that use the ticker instead of the
                      full name. Leave empty ('') if not needed.
        max_articles: Maximum articles to return (default 20, hard max 100).
                      NewsAPI free tier: 100 requests/day — use Redis cache.

    Returns:
        Dict representation of NewsResult containing:
        - company_name, ticker, query_used, from_date, to_date
        - total_results (int — total NewsAPI found, may exceed max_articles)
        - articles_returned (int — actual count in articles list)
        - articles: list of {title, description, url, source_name,
                             published_at, content_snippet}
        - fetched_at, source
        - warnings: list of non-fatal issues

    On error, returns a dict with an 'error' key instead of raising.

    Example:
        >>> result = fetch_news.invoke({
        ...     "company_name": "Infosys",
        ...     "ticker": "INFY.NS",
        ...     "max_articles": 10,
        ... })
        >>> result["articles_returned"]
        10
        >>> result["articles"][0]["title"]
        'Infosys beats Q4 estimates...'
    """
    try:
        result = _fetch_news_cached(
            company_name=company_name.strip(),
            ticker=ticker.strip() if ticker else None,
            max_articles=max_articles,
        )
        return result
    except ValueError as exc:
        # Missing API key — configuration error
        logger.error("NewsAPI configuration error: %s", exc)
        return {
            "error": "configuration_error",
            "company_name": company_name,
            "message": str(exc),
        }
    except NewsAPIError as exc:
        logger.error("NewsAPI error for %r: %s", company_name, exc)
        return {
            "error": "newsapi_error",
            "company_name": company_name,
            "message": str(exc),
        }
    except (NewsAPIRateLimitError, RetryError) as exc:
        logger.error(
            "NewsAPI rate limit exhausted after %d retries for %r: %s",
            _RETRY_ATTEMPTS,
            company_name,
            exc,
        )
        return {
            "error": "rate_limit_exhausted",
            "company_name": company_name,
            "message": (
                f"NewsAPI rate limit hit and all {_RETRY_ATTEMPTS} retry "
                "attempts exhausted. Wait before trying again or check your "
                "daily quota at https://newsapi.org/account"
            ),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_news: company=%r", company_name)
        return {
            "error": "unexpected_error",
            "company_name": company_name,
            "message": f"An unexpected error occurred: {exc}",
        }


@tool
def fetch_news_summary(
    company_name: str,
    ticker: str = "",
    max_articles: int = DEFAULT_MAX_ARTICLES,
) -> dict[str, Any]:
    """
    Fetch a lightweight news summary: article count + headlines only.

    Use this tool when the agent only needs to know how much coverage
    a company is getting and what the headlines are, without the full
    article metadata. Reduces token usage in LLM context windows.

    Args:
        company_name: Company display name (e.g. 'Reliance Industries').
        ticker:       Optional stock ticker (e.g. 'RELIANCE.NS').
        max_articles: Max articles to fetch (default 20).

    Returns:
        Dict with keys: company_name, total_results, articles_returned,
        headlines (list of title strings), from_date, to_date, warnings.
        Returns error dict on failure.
    """
    try:
        data = _fetch_news_from_api(
            company_name=company_name.strip(),
            ticker=ticker.strip() if ticker else None,
            max_articles=max_articles,
        )
        return {
            "company_name": data.company_name,
            "total_results": data.total_results,
            "articles_returned": data.articles_returned,
            "headlines": [a.title for a in data.articles],
            "from_date": data.from_date,
            "to_date": data.to_date,
            "warnings": data.warnings,
        }
    except ValueError as exc:
        return {
            "error": "configuration_error",
            "company_name": company_name,
            "message": str(exc),
        }
    except NewsAPIError as exc:
        return {
            "error": "newsapi_error",
            "company_name": company_name,
            "message": str(exc),
        }
    except (NewsAPIRateLimitError, RetryError) as exc:
        return {
            "error": "rate_limit_exhausted",
            "company_name": company_name,
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception(
            "Unexpected error in fetch_news_summary: company=%r",
            company_name,
        )
        return {
            "error": "unexpected_error",
            "company_name": company_name,
            "message": str(exc),
        }
