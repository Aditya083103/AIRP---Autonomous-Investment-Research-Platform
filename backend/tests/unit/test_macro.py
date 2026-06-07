# backend/tests/unit/test_macro.py
"""
Unit tests for backend/tools/macro.py — T-014

Every HTTP call (RBI, MOSPI, World Bank) and every Redis cache call is mocked,
so these tests run fully offline, in CI, with no network and no real Redis.

Test coverage targets (acceptance criteria from T-014):
  ✓ fetch_macro_data returns a dict matching the MacroData schema
  ✓ Returns valid MacroData with all three figures on the happy path
  ✓ A blocked scrape (HTTP 403) → that field is None + a warning, others fill
  ✓ A blocked scrape never raises and never aborts the other sources
  ✓ Result is written to Redis (cache_set_json) for 24h on success
  ✓ A cache hit short-circuits the live fetch and sets cached=True
  ✓ An all-None result (total outage) is NOT cached
  ✓ force_refresh=True bypasses the cache read
  ✓ Pure parsers extract correct values and reject implausible numbers
  ✓ _http_get raises ScrapeBlockedError on 403/429/503, MacroDataError on 404
  ✓ Unexpected programming error → error dict (never raises out of the tool)
  ✓ fetch_macro_summary returns the three numbers only (no provenance)
  ✓ MacroData model validation: empty country rejected

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_macro.py -v
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from backend.tools.macro import (  # noqa: E402
    MACRO_CACHE_KEY,
    MacroData,
    MacroDataError,
    ScrapeBlockedError,
    _fetch_cpi,
    _fetch_gdp,
    _fetch_macro_data,
    _fetch_repo_rate,
    _http_get,
    _parse_mospi_cpi,
    _parse_rbi_repo_rate,
    _parse_worldbank_gdp,
    fetch_macro_data,
    fetch_macro_summary,
)

# Bypass tenacity retries by calling the unwrapped HTTP function directly.
_http_get_raw = _http_get.__wrapped__  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

_RBI_HTML = (
    "<html><body><table><tr><td>Policy Repo Rate</td>"
    "<td>: 6.50%</td></tr></table></body></html>"
)
_MOSPI_HTML = (
    "<html><body><p>The all-India CPI inflation for the month "
    "stood at 5.10% (provisional).</p></body></html>"
)
_WORLDBANK_JSON: list[Any] = [
    {"page": 1, "pages": 1, "per_page": 5, "total": 1},
    [
        {"indicator": {"id": "NY.GDP.MKTP.KD.ZG"}, "date": "2023", "value": 7.0},
        {"indicator": {"id": "NY.GDP.MKTP.KD.ZG"}, "date": "2022", "value": None},
    ],
]


def _make_mock_response(
    status_code: int = 200,
    text: str = "",
    json_data: Any = None,
) -> MagicMock:
    """Return a mocked requests.Response object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    if json_data is not None:
        mock.json.return_value = json_data
    else:
        mock.json.side_effect = ValueError("no json")
    return mock


# ---------------------------------------------------------------------------
# Tests: pure parsers (no I/O)
# ---------------------------------------------------------------------------


class TestParseRbiRepoRate:
    def test_parses_policy_repo_rate(self) -> None:
        assert _parse_rbi_repo_rate(_RBI_HTML) == 6.5

    def test_parses_without_policy_prefix(self) -> None:
        html = "<div>Repo Rate 6.25 %</div>"
        assert _parse_rbi_repo_rate(html) == 6.25

    def test_returns_none_when_absent(self) -> None:
        assert _parse_rbi_repo_rate("<div>nothing here</div>") is None

    def test_rejects_implausible_value(self) -> None:
        # 650 (markup glitch) is outside 0-25% → rejected as None
        html = "<div>Policy Repo Rate 650</div>"
        assert _parse_rbi_repo_rate(html) is None

    def test_handles_integer_rate(self) -> None:
        html = "<div>Policy Repo Rate : 7%</div>"
        assert _parse_rbi_repo_rate(html) == 7.0


class TestParseMospiCpi:
    def test_parses_cpi_inflation(self) -> None:
        assert _parse_mospi_cpi(_MOSPI_HTML) == 5.1

    def test_parses_inflation_label(self) -> None:
        html = "<p>Retail inflation eased to 4.85% in the latest reading.</p>"
        assert _parse_mospi_cpi(html) == 4.85

    def test_returns_none_when_absent(self) -> None:
        assert _parse_mospi_cpi("<p>no numbers about prices</p>") is None

    def test_rejects_implausible_value(self) -> None:
        html = "<p>CPI 999%</p>"
        assert _parse_mospi_cpi(html) is None

    def test_allows_mild_deflation(self) -> None:
        html = "<p>CPI inflation came in at -1.20%</p>"
        assert _parse_mospi_cpi(html) == -1.2


class TestParseWorldbankGdp:
    def test_returns_most_recent_non_null(self) -> None:
        gdp, year = _parse_worldbank_gdp(_WORLDBANK_JSON)
        assert gdp == 7.0
        assert year == "2023"

    def test_skips_null_values(self) -> None:
        payload = [
            {},
            [{"date": "2023", "value": None}, {"date": "2022", "value": 6.5}],
        ]
        gdp, year = _parse_worldbank_gdp(payload)
        assert gdp == 6.5
        assert year == "2022"

    def test_returns_none_on_empty_observations(self) -> None:
        assert _parse_worldbank_gdp([{}, []]) == (None, None)

    def test_returns_none_on_malformed_payload(self) -> None:
        assert _parse_worldbank_gdp({"unexpected": "shape"}) == (None, None)
        assert _parse_worldbank_gdp([{}]) == (None, None)

    def test_rejects_implausible_value(self) -> None:
        payload = [{}, [{"date": "2023", "value": 999.0}]]
        assert _parse_worldbank_gdp(payload) == (None, None)


# ---------------------------------------------------------------------------
# Tests: _http_get (HTTP layer — unwrapped, no retry waits)
# ---------------------------------------------------------------------------


class TestHttpGet:
    def test_returns_response_on_200(self) -> None:
        mock_resp = _make_mock_response(200, text="ok")
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            result = _http_get_raw("https://example.com")
        assert result.status_code == 200

    @pytest.mark.parametrize("status", [401, 403, 429, 451, 503])
    def test_raises_scrape_blocked_on_blocking_status(self, status: int) -> None:
        mock_resp = _make_mock_response(status)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            with pytest.raises(ScrapeBlockedError):
                _http_get_raw("https://example.com")

    def test_raises_connection_error_on_500(self) -> None:
        # 5xx is transient → ConnectionError (so the wrapped fn would retry)
        mock_resp = _make_mock_response(500)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            with pytest.raises(requests.ConnectionError):
                _http_get_raw("https://example.com")

    def test_raises_macro_data_error_on_404(self) -> None:
        mock_resp = _make_mock_response(404)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            with pytest.raises(MacroDataError):
                _http_get_raw("https://example.com")


# ---------------------------------------------------------------------------
# Tests: per-source fetchers (HTTP mocked; each fails independently)
# ---------------------------------------------------------------------------


class TestFetchRepoRate:
    def test_success(self) -> None:
        mock_resp = _make_mock_response(200, text=_RBI_HTML)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            rate, as_of, warnings = _fetch_repo_rate()
        assert rate == 6.5
        assert as_of is not None
        assert warnings == []

    def test_blocked_returns_none_with_warning(self) -> None:
        mock_resp = _make_mock_response(403)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            rate, as_of, warnings = _fetch_repo_rate()
        assert rate is None
        assert any("blocked" in w.lower() for w in warnings)

    def test_parse_miss_returns_none_with_warning(self) -> None:
        mock_resp = _make_mock_response(200, text="<div>no rate here</div>")
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            rate, _as_of, warnings = _fetch_repo_rate()
        assert rate is None
        assert warnings and "repo rate" in warnings[0].lower()

    def test_unexpected_error_returns_none_with_warning(self) -> None:
        with patch(
            "backend.tools.macro.requests.get",
            side_effect=RuntimeError("boom"),
        ):
            rate, _as_of, warnings = _fetch_repo_rate()
        assert rate is None
        assert warnings


class TestFetchCpi:
    def test_success(self) -> None:
        mock_resp = _make_mock_response(200, text=_MOSPI_HTML)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            cpi, as_of, warnings = _fetch_cpi()
        assert cpi == 5.1
        assert as_of is not None
        assert warnings == []

    def test_blocked_returns_none(self) -> None:
        mock_resp = _make_mock_response(429)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            cpi, _as_of, warnings = _fetch_cpi()
        assert cpi is None
        assert warnings


class TestFetchGdp:
    def test_success(self) -> None:
        mock_resp = _make_mock_response(200, json_data=_WORLDBANK_JSON)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            gdp, year, warnings = _fetch_gdp()
        assert gdp == 7.0
        assert year == "2023"
        assert warnings == []

    def test_non_json_body_returns_none(self) -> None:
        mock_resp = _make_mock_response(200, text="<html>not json</html>")
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            gdp, _year, warnings = _fetch_gdp()
        assert gdp is None
        assert warnings

    def test_blocked_returns_none(self) -> None:
        mock_resp = _make_mock_response(503)
        with patch("backend.tools.macro.requests.get", return_value=mock_resp):
            gdp, _year, warnings = _fetch_gdp()
        assert gdp is None
        assert warnings


# ---------------------------------------------------------------------------
# Tests: _fetch_macro_data (core — cache + source assembly)
# ---------------------------------------------------------------------------


class TestFetchMacroDataCore:
    def _patch_sources(
        self,
        repo: tuple[Any, Any, list[str]] = (6.5, "2024-06-01", []),
        cpi: tuple[Any, Any, list[str]] = (5.1, "2024-06", []),
        gdp: tuple[Any, Any, list[str]] = (7.0, "2023", []),
    ) -> Any:
        """Patch all three source fetchers with controlled return tuples."""
        return (
            patch("backend.tools.macro._fetch_repo_rate", return_value=repo),
            patch("backend.tools.macro._fetch_cpi", return_value=cpi),
            patch("backend.tools.macro._fetch_gdp", return_value=gdp),
        )

    def test_happy_path_all_three_present(self) -> None:
        p_repo, p_cpi, p_gdp = self._patch_sources()
        with (
            p_repo,
            p_cpi,
            p_gdp,
            patch("backend.tools.macro.cache_get_json", return_value=None),
            patch("backend.tools.macro.cache_set_json", return_value=True),
        ):
            data = _fetch_macro_data()
        assert data.repo_rate == 6.5
        assert data.cpi_inflation == 5.1
        assert data.gdp_growth == 7.0
        assert data.cached is False
        assert data.sources == {
            "repo_rate": "rbi",
            "cpi_inflation": "mospi",
            "gdp_growth": "worldbank",
        }

    def test_success_writes_to_cache(self) -> None:
        p_repo, p_cpi, p_gdp = self._patch_sources()
        with (
            p_repo,
            p_cpi,
            p_gdp,
            patch("backend.tools.macro.cache_get_json", return_value=None),
            patch("backend.tools.macro.cache_set_json") as mock_set,
        ):
            _fetch_macro_data()
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[0] == MACRO_CACHE_KEY

    def test_blocked_source_degrades_others_fill(self) -> None:
        """Acceptance: blocked scrape → None field + warning; others still fill."""
        p_repo, p_cpi, p_gdp = self._patch_sources(
            repo=(None, None, ["RBI scrape blocked: HTTP 403. repo_rate unavailable."]),
        )
        with (
            p_repo,
            p_cpi,
            p_gdp,
            patch("backend.tools.macro.cache_get_json", return_value=None),
            patch("backend.tools.macro.cache_set_json", return_value=True),
        ):
            data = _fetch_macro_data()
        assert data.repo_rate is None
        assert data.cpi_inflation == 5.1  # other sources unaffected
        assert data.gdp_growth == 7.0
        assert any("blocked" in w.lower() for w in data.warnings)
        assert "repo_rate" not in data.sources

    def test_all_sources_fail_is_not_cached(self) -> None:
        p_repo, p_cpi, p_gdp = self._patch_sources(
            repo=(None, None, ["blocked"]),
            cpi=(None, None, ["blocked"]),
            gdp=(None, None, ["blocked"]),
        )
        with (
            p_repo,
            p_cpi,
            p_gdp,
            patch("backend.tools.macro.cache_get_json", return_value=None),
            patch("backend.tools.macro.cache_set_json") as mock_set,
        ):
            data = _fetch_macro_data()
        assert data.has_any_data is False
        mock_set.assert_not_called()  # empty result must not poison the cache

    def test_cache_hit_short_circuits_fetch(self) -> None:
        cached_payload = MacroData(
            country="India",
            repo_rate=6.0,
            cpi_inflation=4.5,
            gdp_growth=6.8,
            sources={"repo_rate": "rbi"},
            fetched_at=datetime.now(tz=timezone.utc),
        ).model_dump(mode="json")

        with (
            patch("backend.tools.macro.cache_get_json", return_value=cached_payload),
            patch("backend.tools.macro._fetch_repo_rate") as mock_repo,
        ):
            data = _fetch_macro_data()
        assert data.repo_rate == 6.0
        assert data.cached is True
        mock_repo.assert_not_called()  # live fetch skipped on cache hit

    def test_force_refresh_bypasses_cache_read(self) -> None:
        p_repo, p_cpi, p_gdp = self._patch_sources()
        with (
            p_repo,
            p_cpi,
            p_gdp,
            patch("backend.tools.macro.cache_get_json") as mock_get,
            patch("backend.tools.macro.cache_set_json", return_value=True),
        ):
            _fetch_macro_data(force_refresh=True)
        mock_get.assert_not_called()

    def test_corrupt_cache_falls_through_to_live(self) -> None:
        p_repo, p_cpi, p_gdp = self._patch_sources()
        with (
            p_repo,
            p_cpi,
            p_gdp,
            patch(
                "backend.tools.macro.cache_get_json",
                return_value={"unexpected": "schema"},
            ),
            patch("backend.tools.macro.cache_set_json", return_value=True),
        ):
            data = _fetch_macro_data()
        # MacroData(**{"unexpected": ...}) misses required fetched_at → fall through
        assert data.repo_rate == 6.5
        assert data.cached is False


# ---------------------------------------------------------------------------
# Tests: fetch_macro_data (@tool — via .invoke())
# ---------------------------------------------------------------------------


class TestFetchMacroDataTool:
    def _patch_all(self) -> Any:
        return (
            patch("backend.tools.macro._fetch_repo_rate", return_value=(6.5, "x", [])),
            patch("backend.tools.macro._fetch_cpi", return_value=(5.1, "x", [])),
            patch("backend.tools.macro._fetch_gdp", return_value=(7.0, "2023", [])),
            patch("backend.tools.macro.cache_get_json", return_value=None),
            patch("backend.tools.macro.cache_set_json", return_value=True),
        )

    def test_returns_dict(self) -> None:
        p1, p2, p3, p4, p5 = self._patch_all()
        with p1, p2, p3, p4, p5:
            result = fetch_macro_data.invoke({})
        assert isinstance(result, dict)
        assert "error" not in result

    def test_has_all_expected_keys(self) -> None:
        p1, p2, p3, p4, p5 = self._patch_all()
        with p1, p2, p3, p4, p5:
            result = fetch_macro_data.invoke({})
        for key in (
            "country",
            "repo_rate",
            "cpi_inflation",
            "gdp_growth",
            "sources",
            "warnings",
            "fetched_at",
            "cached",
            "source",
        ):
            assert key in result, f"Missing key: {key}"

    def test_values_match(self) -> None:
        p1, p2, p3, p4, p5 = self._patch_all()
        with p1, p2, p3, p4, p5:
            result = fetch_macro_data.invoke({})
        assert result["repo_rate"] == 6.5
        assert result["cpi_inflation"] == 5.1
        assert result["gdp_growth"] == 7.0

    def test_unexpected_error_returns_error_dict(self) -> None:
        with patch(
            "backend.tools.macro._fetch_macro_data",
            side_effect=RuntimeError("kaboom"),
        ):
            result = fetch_macro_data.invoke({})
        assert result["error"] == "unexpected_error"
        assert "message" in result


# ---------------------------------------------------------------------------
# Tests: fetch_macro_summary (@tool)
# ---------------------------------------------------------------------------


class TestFetchMacroSummaryTool:
    def _patch_all(self) -> Any:
        return (
            patch("backend.tools.macro._fetch_repo_rate", return_value=(6.5, "x", [])),
            patch("backend.tools.macro._fetch_cpi", return_value=(5.1, "x", [])),
            patch("backend.tools.macro._fetch_gdp", return_value=(7.0, "2023", [])),
            patch("backend.tools.macro.cache_get_json", return_value=None),
            patch("backend.tools.macro.cache_set_json", return_value=True),
        )

    def test_returns_headline_numbers_only(self) -> None:
        p1, p2, p3, p4, p5 = self._patch_all()
        with p1, p2, p3, p4, p5:
            result = fetch_macro_summary.invoke({})
        assert set(result) == {
            "country",
            "repo_rate",
            "cpi_inflation",
            "gdp_growth",
            "cached",
            "fetched_at",
            "warnings",
        }
        assert "sources" not in result  # provenance omitted in the summary

    def test_returns_error_dict_on_failure(self) -> None:
        with patch(
            "backend.tools.macro._fetch_macro_data",
            side_effect=RuntimeError("kaboom"),
        ):
            result = fetch_macro_summary.invoke({})
        assert result["error"] == "unexpected_error"


# ---------------------------------------------------------------------------
# Tests: MacroData model validation
# ---------------------------------------------------------------------------


class TestMacroDataModel:
    def test_valid_instantiates(self) -> None:
        data = MacroData(
            repo_rate=6.5,
            cpi_inflation=5.1,
            gdp_growth=7.0,
            fetched_at=datetime.now(tz=timezone.utc),
        )
        assert data.country == "India"
        assert data.has_any_data is True

    def test_all_none_has_no_data(self) -> None:
        data = MacroData(fetched_at=datetime.now(tz=timezone.utc))
        assert data.has_any_data is False

    def test_empty_country_raises(self) -> None:
        with pytest.raises(ValueError, match="country"):
            MacroData(country="   ", fetched_at=datetime.now(tz=timezone.utc))
