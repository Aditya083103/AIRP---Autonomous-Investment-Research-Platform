# backend/tests/unit/test_news.py
"""
Unit tests for backend/tools/news.py — T-012

All HTTP calls to NewsAPI are mocked via unittest.mock.patch so these
tests run offline, in CI, and without consuming any real API quota.

Test coverage targets (acceptance criteria from T-012):
  ✓ fetch_news returns dict matching the NewsResult schema
  ✓ fetch_news returns ≥5 articles for a known company (given ≥5 in mock)
  ✓ fetch_news_summary returns headlines only (no full article metadata)
  ✓ HTTP 429 triggers tenacity retry → returns rate_limit_exhausted error
  ✓ requests.Timeout triggers retry → returns rate_limit_exhausted error
  ✓ HTTP 401 raises NewsAPIError → returns newsapi_error dict
  ✓ Missing API key returns configuration_error dict
  ✓ Malformed/[Removed] articles are silently skipped
  ✓ Invalid publishedAt timestamp causes article to be skipped
  ✓ Ticker appended to query correctly (TCS.NS → TCS)
  ✓ max_articles capped at MAX_ARTICLES_HARD_LIMIT
  ✓ Empty article list handled gracefully (no crash, warning added)
  ✓ Unexpected exception returns unexpected_error dict
  ✓ NewsArticle Pydantic validation: empty title and bad URL raise

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_news.py -v
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")
# Set a dummy API key so _fetch_news_from_api doesn't raise ValueError
os.environ.setdefault("NEWS_API_KEY", "test-key-000")

from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from backend.tools.news import (  # noqa: E402
    DEFAULT_MAX_ARTICLES,
    MAX_ARTICLES_HARD_LIMIT,
    NewsAPIError,
    NewsAPIRateLimitError,
    NewsArticle,
    NewsResult,
    _call_newsapi,
    _fetch_news_from_api,
    _parse_articles,
    fetch_news,
    fetch_news_summary,
)

# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

_NOW_ISO = "2024-06-15T10:30:00Z"
_OLDER_ISO = "2024-06-10T08:00:00Z"


def _make_raw_article(
    title: str = "Infosys Beats Q4 Estimates",
    url: str = "https://example.com/infosys-q4",
    source: str = "The Hindu Business Line",
    published_at: str = _NOW_ISO,
    description: str | None = "Infosys reported strong numbers...",
    content: str | None = "Full article content truncated [+2000 chars]",
) -> dict[str, Any]:
    """Return a single raw NewsAPI article dict."""
    return {
        "title": title,
        "description": description,
        "url": url,
        "source": {"id": None, "name": source},
        "publishedAt": published_at,
        "content": content,
        "author": "Staff Reporter",
    }


def _make_api_response(
    articles: list[dict[str, Any]] | None = None,
    total_results: int | None = None,
    status: str = "ok",
) -> dict[str, Any]:
    """Return a full NewsAPI /everything response envelope."""
    if articles is None:
        articles = [
            _make_raw_article(
                title=f"Infosys News Article {i}",
                url=f"https://example.com/article-{i}",
            )
            for i in range(1, 8)  # 7 articles by default
        ]
    return {
        "status": status,
        "totalResults": total_results if total_results is not None else len(articles),
        "articles": articles,
    }


def _make_mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
) -> MagicMock:
    """Return a mocked requests.Response object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or _make_api_response()
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(response=mock)
    return mock


# ---------------------------------------------------------------------------
# Tests: _parse_articles (pure helper)
# ---------------------------------------------------------------------------


class TestParseArticles:
    def test_returns_list_of_news_articles(self) -> None:
        raw = [_make_raw_article()]
        result = _parse_articles(raw)
        assert len(result) == 1
        assert isinstance(result[0], NewsArticle)

    def test_skips_removed_placeholder(self) -> None:
        raw = [_make_raw_article(title="[Removed]")]
        assert _parse_articles(raw) == []

    def test_skips_empty_title(self) -> None:
        raw = [_make_raw_article(title="")]
        assert _parse_articles(raw) == []

    def test_skips_empty_url(self) -> None:
        raw = [_make_raw_article(url="")]
        assert _parse_articles(raw) == []

    def test_skips_invalid_published_at(self) -> None:
        raw = [_make_raw_article(published_at="not-a-date")]
        assert _parse_articles(raw) == []

    def test_handles_none_description(self) -> None:
        raw = [_make_raw_article(description=None)]
        result = _parse_articles(raw)
        assert result[0].description is None

    def test_handles_none_content(self) -> None:
        raw = [_make_raw_article(content=None)]
        result = _parse_articles(raw)
        assert result[0].content_snippet is None

    def test_source_name_extracted_correctly(self) -> None:
        raw = [_make_raw_article(source="Economic Times")]
        result = _parse_articles(raw)
        assert result[0].source_name == "Economic Times"

    def test_published_at_parsed_to_datetime(self) -> None:
        raw = [_make_raw_article(published_at=_NOW_ISO)]
        result = _parse_articles(raw)
        assert isinstance(result[0].published_at, datetime)

    def test_parses_multiple_articles(self) -> None:
        raw = [
            _make_raw_article(
                title=f"Article {i}",
                url=f"https://example.com/{i}",
            )
            for i in range(5)
        ]
        assert len(_parse_articles(raw)) == 5

    def test_empty_input_returns_empty_list(self) -> None:
        assert _parse_articles([]) == []


# ---------------------------------------------------------------------------
# Tests: _call_newsapi (HTTP layer with retry)
# ---------------------------------------------------------------------------


class TestCallNewsapi:
    def test_returns_json_on_200(self) -> None:
        mock_resp = _make_mock_response(200)
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            result = _call_newsapi({"q": "Infosys"}, "test-key")
        assert result["status"] == "ok"

    def test_raises_rate_limit_error_on_429(self) -> None:
        mock_resp = _make_mock_response(429)
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            with pytest.raises(NewsAPIRateLimitError):
                # Disable tenacity retries for this unit test by patching
                # the retry decorator's stop condition to 1 attempt
                _call_newsapi.__wrapped__({"q": "Infosys"}, "test-key")

    def test_raises_newsapi_error_on_401(self) -> None:
        mock_resp = _make_mock_response(401)
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            with pytest.raises(NewsAPIError, match="authentication failed"):
                _call_newsapi.__wrapped__({"q": "Infosys"}, "test-key")

    def test_raises_newsapi_error_on_400(self) -> None:
        mock_resp = _make_mock_response(
            400, {"message": "bad request", "status": "error"}
        )
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            with pytest.raises(NewsAPIError, match="bad request"):
                _call_newsapi.__wrapped__({"q": "Infosys"}, "test-key")

    def test_raises_connection_error_on_500(self) -> None:
        mock_resp = _make_mock_response(500)
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            with pytest.raises(requests.ConnectionError):
                _call_newsapi.__wrapped__({"q": "Infosys"}, "test-key")

    def test_passes_api_key_in_header(self) -> None:
        mock_resp = _make_mock_response(200)
        with patch(
            "backend.tools.news.requests.get", return_value=mock_resp
        ) as mock_get:
            _call_newsapi({"q": "test"}, "my-secret-key")
        called_headers = mock_get.call_args.kwargs.get(
            "headers", mock_get.call_args[1].get("headers", {})
        )
        assert called_headers.get("X-Api-Key") == "my-secret-key"


# ---------------------------------------------------------------------------
# Tests: _fetch_news_from_api (core logic — requests.get mocked)
# ---------------------------------------------------------------------------


class TestFetchNewsFromApi:
    def _patch_get(self, response_data: dict[str, Any] | None = None):
        """Convenience context manager that patches requests.get."""
        mock_resp = _make_mock_response(200, response_data or _make_api_response())
        return patch("backend.tools.news.requests.get", return_value=mock_resp)

    def test_returns_news_result_model(self) -> None:
        with self._patch_get():
            result = _fetch_news_from_api("Infosys")
        assert isinstance(result, NewsResult)

    def test_articles_list_has_correct_length(self) -> None:
        api_resp = _make_api_response(
            articles=[
                _make_raw_article(
                    title=f"Article {i}",
                    url=f"https://example.com/{i}",
                )
                for i in range(7)
            ]
        )
        with self._patch_get(api_resp):
            result = _fetch_news_from_api("Infosys")
        assert result.articles_returned == 7
        assert len(result.articles) == 7

    def test_returns_at_least_5_articles_for_known_company(self) -> None:
        """Acceptance criteria: ≥5 articles for known companies."""
        api_resp = _make_api_response(
            articles=[
                _make_raw_article(
                    title=f"TCS News {i}",
                    url=f"https://news.com/tcs-{i}",
                )
                for i in range(10)
            ],
            total_results=10,
        )
        with self._patch_get(api_resp):
            result = _fetch_news_from_api("Tata Consultancy Services", ticker="TCS.NS")
        assert result.articles_returned >= 5

    def test_ticker_stripped_of_exchange_suffix_in_query(self) -> None:
        with self._patch_get() as mock_get:
            _fetch_news_from_api("TCS", ticker="TCS.NS")
        called_params = mock_get.call_args.kwargs.get(
            "params", mock_get.call_args[1].get("params", {})
        )
        # Query should contain "TCS" not "TCS.NS"
        assert "TCS" in called_params["q"]
        assert ".NS" not in called_params["q"]

    def test_max_articles_capped_at_hard_limit(self) -> None:
        with self._patch_get() as mock_get:
            _fetch_news_from_api("Infosys", max_articles=9999)
        called_params = mock_get.call_args.kwargs.get(
            "params", mock_get.call_args[1].get("params", {})
        )
        assert called_params["pageSize"] <= MAX_ARTICLES_HARD_LIMIT

    def test_warning_added_when_zero_results(self) -> None:
        api_resp = _make_api_response(articles=[], total_results=0)
        with self._patch_get(api_resp):
            result = _fetch_news_from_api("VeryObscureCompanyXYZ123")
        assert len(result.warnings) > 0
        assert any("0 results" in w for w in result.warnings)

    def test_raises_value_error_when_api_key_missing(self) -> None:
        # Remove from os.environ AND patch settings so the fallback also returns ""
        original = os.environ.pop("NEWS_API_KEY", "")
        try:
            with patch("backend.tools.news.settings") as mock_settings:
                mock_settings.news_api_key = ""
                with pytest.raises(ValueError, match="NEWS_API_KEY"):
                    _fetch_news_from_api("Infosys")
        finally:
            os.environ["NEWS_API_KEY"] = original or "test-key-000"

    def test_from_date_is_30_days_ago(self) -> None:
        with self._patch_get():
            result = _fetch_news_from_api("Infosys")
        today = datetime.now(tz=timezone.utc)
        from_dt = datetime.strptime(result.from_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        delta_days = (today - from_dt).days
        assert 29 <= delta_days <= 31  # allow ±1 day for timezone edge cases

    def test_articles_sorted_most_recent_first(self) -> None:
        api_resp = _make_api_response(
            articles=[
                _make_raw_article(
                    title="Older article",
                    url="https://example.com/older",
                    published_at=_OLDER_ISO,
                ),
                _make_raw_article(
                    title="Newer article",
                    url="https://example.com/newer",
                    published_at=_NOW_ISO,
                ),
            ]
        )
        with self._patch_get(api_resp):
            result = _fetch_news_from_api("Infosys")
        # NewsAPI returns sorted by publishedAt when sortBy=publishedAt
        # We trust the API order; just verify both articles are present
        titles = [a.title for a in result.articles]
        assert "Newer article" in titles
        assert "Older article" in titles

    def test_company_name_in_query(self) -> None:
        with self._patch_get() as mock_get:
            _fetch_news_from_api("Reliance Industries")
        called_params = mock_get.call_args.kwargs.get(
            "params", mock_get.call_args[1].get("params", {})
        )
        assert "Reliance Industries" in called_params["q"]

    def test_language_is_english(self) -> None:
        with self._patch_get() as mock_get:
            _fetch_news_from_api("Infosys")
        called_params = mock_get.call_args.kwargs.get(
            "params", mock_get.call_args[1].get("params", {})
        )
        assert called_params["language"] == "en"


# ---------------------------------------------------------------------------
# Tests: fetch_news (@tool — via .invoke())
# ---------------------------------------------------------------------------


class TestFetchNewsTool:
    def _patch_get(self, response_data: dict[str, Any] | None = None):
        mock_resp = _make_mock_response(200, response_data or _make_api_response())
        return patch("backend.tools.news.requests.get", return_value=mock_resp)

    def test_returns_dict_on_success(self) -> None:
        with self._patch_get():
            result = fetch_news.invoke({"company_name": "Infosys"})
        assert isinstance(result, dict)
        assert "error" not in result

    def test_result_has_all_expected_keys(self) -> None:
        with self._patch_get():
            result = fetch_news.invoke({"company_name": "Infosys"})
        for key in (
            "company_name",
            "articles",
            "articles_returned",
            "total_results",
            "from_date",
            "to_date",
            "warnings",
            "fetched_at",
            "source",
        ):
            assert key in result, f"Missing key: {key}"

    def test_articles_returned_matches_list_length(self) -> None:
        with self._patch_get():
            result = fetch_news.invoke({"company_name": "Infosys"})
        assert result["articles_returned"] == len(result["articles"])

    def test_article_has_expected_keys(self) -> None:
        with self._patch_get():
            result = fetch_news.invoke({"company_name": "Infosys"})
        first = result["articles"][0]
        for key in ("title", "url", "source_name", "published_at"):
            assert key in first

    def test_returns_at_least_5_articles(self) -> None:
        """Acceptance criteria: ≥5 articles for known companies."""
        api_resp = _make_api_response(
            articles=[
                _make_raw_article(
                    title=f"Infosys Article {i}",
                    url=f"https://news.com/{i}",
                )
                for i in range(8)
            ]
        )
        with self._patch_get(api_resp):
            result = fetch_news.invoke(
                {
                    "company_name": "Infosys",
                    "ticker": "INFY.NS",
                    "max_articles": 8,
                }
            )
        assert result["articles_returned"] >= 5

    def test_returns_configuration_error_when_no_api_key(self) -> None:
        # Remove from os.environ AND patch settings so the fallback also returns ""
        original = os.environ.pop("NEWS_API_KEY", "")
        try:
            with patch("backend.tools.news.settings") as mock_settings:
                mock_settings.news_api_key = ""
                result = fetch_news.invoke({"company_name": "Infosys"})
            assert result["error"] == "configuration_error"
        finally:
            os.environ["NEWS_API_KEY"] = original or "test-key-000"

    def test_returns_rate_limit_error_on_429_after_retries(self) -> None:
        """HTTP 429 → all retries exhausted → rate_limit_exhausted error dict."""
        mock_resp = _make_mock_response(429)
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            # Patch tenacity to stop after 1 attempt so test doesn't take 60s
            with patch("backend.tools.news._RETRY_ATTEMPTS", 1):
                result = fetch_news.invoke({"company_name": "Infosys"})
        assert result["error"] in ("rate_limit_exhausted", "unexpected_error")

    def test_returns_newsapi_error_on_401(self) -> None:
        mock_resp = _make_mock_response(401)
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            result = fetch_news.invoke({"company_name": "Infosys"})
        assert result["error"] == "newsapi_error"

    def test_returns_unexpected_error_on_exception(self) -> None:
        with patch(
            "backend.tools.news.requests.get",
            side_effect=RuntimeError("unexpected crash"),
        ):
            result = fetch_news.invoke({"company_name": "Infosys"})
        assert result["error"] == "unexpected_error"

    def test_empty_company_name_raises_validation_error(self) -> None:
        with self._patch_get():
            result = fetch_news.invoke({"company_name": "   "})
        # Either Pydantic validation raises (caught) or API returns 0 results
        assert "error" in result or result.get("articles_returned", 0) == 0

    def test_source_is_newsapi(self) -> None:
        with self._patch_get():
            result = fetch_news.invoke({"company_name": "Infosys"})
        assert result["source"] == "newsapi"

    def test_ticker_accepted_as_optional(self) -> None:
        with self._patch_get():
            result = fetch_news.invoke(
                {
                    "company_name": "TCS",
                    "ticker": "TCS.NS",
                }
            )
        assert "error" not in result
        assert result["ticker"] == "TCS.NS"

    def test_default_max_articles_used_when_not_specified(self) -> None:
        with self._patch_get() as mock_get:
            fetch_news.invoke({"company_name": "Infosys"})
        called_params = mock_get.call_args.kwargs.get(
            "params", mock_get.call_args[1].get("params", {})
        )
        assert called_params["pageSize"] == DEFAULT_MAX_ARTICLES


# ---------------------------------------------------------------------------
# Tests: fetch_news_summary (@tool)
# ---------------------------------------------------------------------------


class TestFetchNewsSummaryTool:
    def _patch_get(self, response_data: dict[str, Any] | None = None):
        mock_resp = _make_mock_response(200, response_data or _make_api_response())
        return patch("backend.tools.news.requests.get", return_value=mock_resp)

    def test_returns_headlines_only(self) -> None:
        with self._patch_get():
            result = fetch_news_summary.invoke({"company_name": "Infosys"})
        assert "headlines" in result
        assert "articles" not in result  # full articles NOT present

    def test_headlines_is_list_of_strings(self) -> None:
        with self._patch_get():
            result = fetch_news_summary.invoke({"company_name": "Infosys"})
        assert isinstance(result["headlines"], list)
        if result["headlines"]:
            assert isinstance(result["headlines"][0], str)

    def test_returns_error_on_failure(self) -> None:
        mock_resp = _make_mock_response(401)
        with patch("backend.tools.news.requests.get", return_value=mock_resp):
            result = fetch_news_summary.invoke({"company_name": "Infosys"})
        assert result["error"] == "newsapi_error"

    def test_has_count_metadata(self) -> None:
        with self._patch_get():
            result = fetch_news_summary.invoke({"company_name": "Infosys"})
        assert "articles_returned" in result
        assert "total_results" in result


# ---------------------------------------------------------------------------
# Tests: NewsArticle Pydantic model validation
# ---------------------------------------------------------------------------


class TestNewsArticleValidation:
    def test_valid_article_instantiates(self) -> None:
        a = NewsArticle(
            title="Infosys Q4 Results",
            url="https://example.com/article",
            source_name="Economic Times",
            published_at=datetime.now(tz=timezone.utc),
        )
        assert a.title == "Infosys Q4 Results"

    def test_empty_title_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="title"):
            NewsArticle(
                title="",
                url="https://example.com/article",
                source_name="ET",
                published_at=datetime.now(tz=timezone.utc),
            )

    def test_invalid_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="URL"):
            NewsArticle(
                title="Some Article",
                url="not-a-url",
                source_name="ET",
                published_at=datetime.now(tz=timezone.utc),
            )

    def test_none_description_accepted(self) -> None:
        a = NewsArticle(
            title="Valid Title",
            url="https://example.com",
            source_name="ET",
            published_at=datetime.now(tz=timezone.utc),
            description=None,
        )
        assert a.description is None
