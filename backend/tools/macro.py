# backend/tools/macro.py
"""
AIRP — fetch_macro_data LangChain Tool

Builds the Indian macro-economic picture the Macro Economist agent needs:
the RBI policy repo rate, CPI inflation, and real GDP growth. Returns a
fully-typed Pydantic ``MacroData`` model so the agent always receives
structured, validated data — even when a source is temporarily unavailable.

Tools exposed:
    fetch_macro_data    — Full MacroData (repo_rate, cpi_inflation, gdp_growth)
                          plus per-field provenance, reference periods, and
                          non-fatal warnings.
    fetch_macro_summary — Lightweight: the three headline numbers only
                          (small token footprint for the debate viewer).

Data sources (each fetched independently; one failure never blocks the rest):
    repo_rate      RBI website scrape           (settings.rbi_base_url)
    cpi_inflation  MOSPI website scrape         (MOSPI_CPI_URL)
    gdp_growth     World Bank Indicators API    (WORLDBANK_GDP_URL, JSON, no key)

GDP is taken from the World Bank API rather than scraped because the API is a
stable, free, key-less JSON endpoint — far less brittle than HTML scraping and
the canonical source for the real-GDP-growth indicator (NY.GDP.MKTP.KD.ZG).

Graceful degradation (acceptance: "fails gracefully if scrape blocked"):
    A blocked or failed source sets only *its* field to None, appends a clear
    warning, and lets the others populate. The tool returns a valid MacroData
    in every non-programming-error case — it never raises out to the agent.

Caching (acceptance: "cached in Redis for 24h"):
    The full result is cached in Redis under MACRO_CACHE_KEY for
    settings.cache_ttl_macro seconds (default 86400 = 24h). An all-None result
    (total outage) is deliberately NOT cached, so the next call retries the
    live sources rather than serving 24h of empty data. ``force_refresh=True``
    bypasses the read side of the cache. Caching is a no-op under
    ENVIRONMENT=test and whenever Redis is unreachable (see tools/cache.py).

Usage (inside an agent):
    from backend.tools.macro import fetch_macro_data
    result = fetch_macro_data.invoke({})
    repo = result["repo_rate"]          # float | None  (e.g. 6.5)
    cpi = result["cpi_inflation"]       # float | None  (e.g. 5.1)
    gdp = result["gdp_growth"]          # float | None  (e.g. 7.0)
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
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

from backend.tools.cache import MACRO_TTL, cache_get_json, cache_set_json

try:
    from backend.config import settings as _settings
except Exception:
    _settings = None  # type: ignore[assignment]

# Module-level alias — patch target in tests:
#   patch("backend.tools.macro.settings") replaces this object
settings = _settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# RBI publishes the current policy rates in a "Current Rates" widget on its
# home page. The base URL is configurable (settings.rbi_base_url); the exact
# page markup can change, so the parser below keys off the *label text* rather
# than a brittle CSS path.
_DEFAULT_RBI_BASE_URL = "https://www.rbi.org.in"

# MOSPI (Ministry of Statistics & Programme Implementation) publishes the CPI
# inflation release. The site structure varies between releases, so the parser
# is best-effort and label-driven. If MOSPI changes layout, only the parser
# regex needs updating — the tool still degrades gracefully meanwhile.
MOSPI_CPI_URL = "https://www.mospi.gov.in/"

# World Bank Indicators API — real GDP growth (annual %), India, most recent
# non-empty value (mrnev=1). Stable, free, no API key required.
WORLDBANK_GDP_URL = (
    "https://api.worldbank.org/v2/country/IND/indicator/"
    "NY.GDP.MKTP.KD.ZG?format=json&per_page=5&mrnev=1"
)

# Redis cache key + TTL fallback (settings.cache_ttl_macro is the source of truth)
MACRO_CACHE_KEY = "airp:macro:india"
_DEFAULT_CACHE_TTL_MACRO = 86400  # 24h

# Shared HTTP settings
#
# _HTTP_TIMEOUT and _RETRY_ATTEMPTS were 15s / 3 attempts with exponential
# backoff up to 30s between retries -- worst case for ONE source alone:
# 15 (attempt 1) + 2 (wait) + 15 (attempt 2) + 4 (wait) + 15 (attempt 3)
# = 51 seconds. This node calls up to 3 sources sequentially (RBI-ish,
# MOSPI, World Bank -- see the three _http_get call sites below), so a
# single slow/unresponsive source could alone exceed the entire 30s node
# timeout (backend.graph.node_profiler.NODE_TIMEOUT_S) before even
# reaching this agent's LLM synthesis call at the end -- exactly what was
# observed in production: World Bank alone pushed macro_economist to
# 53.1s. Retrying a government/international API that just timed out at
# a shortened budget rarely helps within one request cycle, and every
# field this node produces from these sources already degrades
# gracefully to None with a warning on failure (ScrapeBlockedError et
# al.) -- so a fast, single-attempt failure is strictly better here than
# a slow one that still ends in the same degraded result. New worst case
# for all 3 sources combined: 3 x 5s = 15s, leaving real headroom for the
# LLM call that follows.
_HTTP_TIMEOUT = 5  # seconds
_USER_AGENT = "AIRP/1.0 (Autonomous Investment Research Platform)"

# Retry policy: 1 attempt (no retry) on transient errors -- see the
# rationale in the _HTTP_TIMEOUT comment above for why a retry here does
# more harm (budget consumed) than good (a source that just timed out
# essentially never succeeds on an immediate second attempt).
_RETRY_ATTEMPTS = 1
_RETRY_WAIT_MIN = 1
_RETRY_WAIT_MAX = 2

# HTTP status codes that mean "the scraper was blocked / throttled" — these are
# surfaced as ScrapeBlockedError so the field degrades to None with a warning.
_BLOCKED_STATUS = frozenset({401, 403, 406, 429, 451, 503})

# Plausibility bounds — guard against a regex grabbing the wrong number
# (e.g. "650" instead of "6.50"). Out-of-range values are discarded + warned.
_REPO_RATE_BOUNDS = (0.0, 25.0)  # % — RBI repo rate realistically 0-25
_CPI_BOUNDS = (-5.0, 50.0)  # % YoY — allow mild deflation, cap hyperinflation
_GDP_BOUNDS = (-25.0, 25.0)  # % annual real growth


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class MacroDataError(Exception):
    """Raised for unrecoverable macro-fetch errors (unexpected, non-transient)."""


class ScrapeBlockedError(Exception):
    """Raised when a source blocks/throttles the scraper (HTTP 403/429/503...)."""


# ---------------------------------------------------------------------------
# Pydantic output model
# ---------------------------------------------------------------------------


class MacroData(BaseModel):
    """
    The Indian macro-economic snapshot consumed by the Macro Economist agent.

    Every numeric field is ``float | None``: None means "could not be sourced
    this run" (blocked scrape, parse miss, or implausible value), never zero.
    The ``sources`` map and ``*_as_of`` fields make each figure auditable.
    """

    country: str = Field(default="India", description="Country the data describes")

    repo_rate: float | None = Field(
        default=None,
        description="RBI policy repo rate, percent (e.g. 6.5). None if unavailable.",
    )
    cpi_inflation: float | None = Field(
        default=None,
        description=(
            "CPI inflation, percent YoY (the 'cpi' figure, e.g. 5.1). "
            "None if unavailable."
        ),
    )
    gdp_growth: float | None = Field(
        default=None,
        description="Real GDP growth, annual percent (e.g. 7.0). None if unavailable.",
    )

    repo_rate_as_of: str | None = Field(
        default=None, description="Reference period/date for repo_rate, if known"
    )
    cpi_as_of: str | None = Field(
        default=None, description="Reference period/date for cpi_inflation, if known"
    )
    gdp_as_of: str | None = Field(
        default=None, description="Reference year for gdp_growth, if known"
    )

    sources: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Provenance per field, e.g. "
            "{'repo_rate': 'rbi', 'cpi_inflation': 'mospi', "
            "'gdp_growth': 'worldbank'}"
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues (blocked source, parse miss, stale value)",
    )

    fetched_at: datetime = Field(description="UTC timestamp this snapshot was built")
    cached: bool = Field(
        default=False, description="True if served from the Redis cache"
    )
    source: str = Field(
        default="rbi+mospi+worldbank",
        description="Combined data-source identifier",
    )

    @field_validator("country")
    @classmethod
    def country_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("country must not be empty")
        return v

    @property
    def has_any_data(self) -> bool:
        """True if at least one of the three headline figures was sourced."""
        return any(
            x is not None for x in (self.repo_rate, self.cpi_inflation, self.gdp_growth)
        )


# ---------------------------------------------------------------------------
# Internal: shared HTTP layer with retry
# ---------------------------------------------------------------------------


@retry(
    retry=(
        retry_if_exception_type(requests.Timeout)
        | retry_if_exception_type(requests.ConnectionError)
    ),
    wait=wait_exponential(multiplier=1, min=_RETRY_WAIT_MIN, max=_RETRY_WAIT_MAX),
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _http_get(url: str) -> requests.Response:
    """
    GET ``url`` with a browser-like User-Agent and retry on transient errors.

    A real User-Agent matters here: RBI and MOSPI often reject the default
    python-requests UA outright, which is the most common cause of a "blocked"
    scrape.

    Raises:
        ScrapeBlockedError:       on a blocking status (403/429/503/...).
        MacroDataError:           on any other non-2xx status.
        requests.Timeout:         on timeout — tenacity retries.
        requests.ConnectionError: on DNS/TCP failure — tenacity retries.
    """
    response = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/json"},
        timeout=_HTTP_TIMEOUT,
    )

    if response.status_code in _BLOCKED_STATUS:
        raise ScrapeBlockedError(
            f"Source blocked the request (HTTP {response.status_code}): {url}"
        )
    if response.status_code >= 500:
        # Transient server error — raise ConnectionError so tenacity retries.
        raise requests.ConnectionError(f"Server error HTTP {response.status_code}")
    if response.status_code >= 400:
        raise MacroDataError(f"Unexpected HTTP {response.status_code} fetching {url}")

    return response


def _make_soup(html: str) -> BeautifulSoup:
    """Build a BeautifulSoup tree, preferring lxml but never crashing if absent."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # lxml not installed — fall back to the stdlib parser
        return BeautifulSoup(html, "html.parser")


def _in_bounds(value: float, bounds: tuple[float, float]) -> bool:
    """Return True if ``value`` is within the inclusive plausibility bounds."""
    low, high = bounds
    return low <= value <= high


# ---------------------------------------------------------------------------
# Internal: pure parsers (no I/O — unit-testable against fixture strings)
# ---------------------------------------------------------------------------


def _parse_rbi_repo_rate(html: str) -> float | None:
    """
    Extract the policy repo rate (percent) from RBI page HTML.

    Strategy: read the page's visible text and find the number that follows
    the "Policy Repo Rate" label. Label-driven matching survives markup
    changes far better than a fixed CSS selector. Returns None if no
    plausible value (0-25%) is found.
    """
    text = _make_soup(html).get_text(" ", strip=True)

    # "Policy Repo Rate ... 6.50%" / "Policy Repo Rate : 6.5 %"
    match = re.search(
        r"policy\s*repo\s*rate[^0-9%]{0,20}(\d{1,2}(?:\.\d{1,2})?)\s*%?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        # Fallback: a bare "Repo Rate" label (some layouts drop "Policy")
        match = re.search(
            r"\brepo\s*rate[^0-9%]{0,20}(\d{1,2}(?:\.\d{1,2})?)\s*%?",
            text,
            flags=re.IGNORECASE,
        )
    if not match:
        return None

    value = float(match.group(1))
    if not _in_bounds(value, _REPO_RATE_BOUNDS):
        logger.warning("Parsed RBI repo rate %.2f outside plausible range", value)
        return None
    return value


def _parse_mospi_cpi(html: str) -> float | None:
    """
    Extract CPI inflation (percent YoY) from MOSPI page HTML.

    Best-effort, label-driven parse. MOSPI's release layout varies, so this
    looks for an inflation percentage near a CPI / inflation label. Returns
    None when no plausible value (-5% to 50%) is found — the agent then treats
    CPI as unavailable rather than acting on a wrong number.
    """
    text = _make_soup(html).get_text(" ", strip=True)

    patterns = (
        # "CPI inflation ... 5.1%" / "Consumer Price Index ... 5.10 %"
        # Gap is lazy ({0,40}?) so a leading minus (e.g. "-1.20%") is left
        # for the capture's -? rather than being swallowed by the gap class.
        r"(?:cpi|consumer\s*price\s*index)[^0-9%]{0,40}?"
        r"(-?\d{1,2}(?:\.\d{1,2})?)\s*%",
        # "inflation rate ... 5.1%" near a CPI context
        r"inflation[^0-9%]{0,40}?(-?\d{1,2}(?:\.\d{1,2})?)\s*%",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1))
            if _in_bounds(value, _CPI_BOUNDS):
                return value
            logger.warning("Parsed MOSPI CPI %.2f outside plausible range", value)
    return None


def _parse_worldbank_gdp(payload: Any) -> tuple[float | None, str | None]:
    """
    Extract (gdp_growth_pct, year) from a World Bank Indicators API response.

    The API returns ``[metadata, [observation, ...]]`` where each observation
    has ``value`` (float | None) and ``date`` (year string). Returns the most
    recent non-null observation, or (None, None) on any structural surprise.
    """
    if not isinstance(payload, list) or len(payload) < 2:
        return None, None
    observations = payload[1]
    if not isinstance(observations, list):
        return None, None

    for obs in observations:
        if not isinstance(obs, dict):
            continue
        value = obs.get("value")
        if value is None:
            continue
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue
        if not _in_bounds(value_f, _GDP_BOUNDS):
            logger.warning("World Bank GDP %.2f outside plausible range", value_f)
            continue
        year = obs.get("date")
        return value_f, (str(year) if year is not None else None)

    return None, None


# ---------------------------------------------------------------------------
# Internal: per-source fetchers (HTTP + parse, each fails independently)
# ---------------------------------------------------------------------------


def _rbi_base_url() -> str:
    """Resolve the RBI base URL from settings, with a sane default."""
    if settings is not None:
        url = getattr(settings, "rbi_base_url", None)
        if url:
            return str(url).rstrip("/")
    return _DEFAULT_RBI_BASE_URL


def _fetch_repo_rate() -> tuple[float | None, str | None, list[str]]:
    """Fetch the RBI repo rate. Returns (rate, as_of, warnings); never raises."""
    url = f"{_rbi_base_url()}/"
    try:
        response = _http_get(url)
        rate = _parse_rbi_repo_rate(response.text)
        if rate is None:
            return (
                None,
                None,
                [
                    "RBI repo rate not found in page — RBI layout may have changed; "
                    "repo_rate unavailable this run."
                ],
            )
        logger.info("RBI repo rate parsed: %.2f%%", rate)
        # RBI does not expose a machine-readable effective date in the widget;
        # we record the fetch date as the as-of reference.
        as_of = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return rate, as_of, []
    except ScrapeBlockedError as exc:
        logger.warning("RBI scrape blocked: %s", exc)
        return None, None, [f"RBI scrape blocked: {exc}. repo_rate unavailable."]
    except Exception as exc:
        logger.warning("RBI repo rate fetch failed: %s", exc)
        return (
            None,
            None,
            [f"RBI repo rate fetch failed: {exc}. repo_rate unavailable."],
        )


def _fetch_cpi() -> tuple[float | None, str | None, list[str]]:
    """Fetch CPI inflation from MOSPI. Returns (cpi, as_of, warnings); never raises."""
    try:
        response = _http_get(MOSPI_CPI_URL)
        cpi = _parse_mospi_cpi(response.text)
        if cpi is None:
            return (
                None,
                None,
                [
                    "CPI inflation not found on MOSPI page — layout may have changed; "
                    "cpi_inflation unavailable this run."
                ],
            )
        logger.info("MOSPI CPI inflation parsed: %.2f%%", cpi)
        as_of = datetime.now(tz=timezone.utc).strftime("%Y-%m")
        return cpi, as_of, []
    except ScrapeBlockedError as exc:
        logger.warning("MOSPI scrape blocked: %s", exc)
        return None, None, [f"MOSPI scrape blocked: {exc}. cpi_inflation unavailable."]
    except Exception as exc:
        logger.warning("MOSPI CPI fetch failed: %s", exc)
        return (
            None,
            None,
            [f"MOSPI CPI fetch failed: {exc}. cpi_inflation unavailable."],
        )


def _fetch_gdp() -> tuple[float | None, str | None, list[str]]:
    """Fetch GDP growth from the World Bank API. Returns (gdp, year, warnings)."""
    try:
        response = _http_get(WORLDBANK_GDP_URL)
        payload = response.json()
        gdp, year = _parse_worldbank_gdp(payload)
        if gdp is None:
            return (
                None,
                None,
                [
                    "World Bank returned no usable GDP growth value; "
                    "gdp_growth unavailable this run."
                ],
            )
        logger.info("World Bank GDP growth parsed: %.2f%% (%s)", gdp, year)
        return gdp, year, []
    except ScrapeBlockedError as exc:
        logger.warning("World Bank API blocked: %s", exc)
        return None, None, [f"World Bank API blocked: {exc}. gdp_growth unavailable."]
    except ValueError as exc:
        # response.json() failed — non-JSON body
        logger.warning("World Bank API returned non-JSON body: %s", exc)
        return None, None, ["World Bank API returned an invalid body; gdp unavailable."]
    except Exception as exc:
        logger.warning("World Bank GDP fetch failed: %s", exc)
        return (
            None,
            None,
            [f"World Bank GDP fetch failed: {exc}. gdp_growth unavailable."],
        )


# ---------------------------------------------------------------------------
# Core fetch logic (separated from @tool for testability)
# ---------------------------------------------------------------------------


def _cache_ttl() -> int:
    """Resolve the macro cache TTL: settings override, else canonical MACRO_TTL."""
    if settings is not None and getattr(settings, "cache_ttl_macro", None):
        return int(settings.cache_ttl_macro)
    return MACRO_TTL


def _fetch_macro_data(force_refresh: bool = False) -> MacroData:
    """
    Build the full MacroData snapshot, using Redis as a 24h read-through cache.

    Each of the three sources is fetched independently — a failure in one
    contributes a warning and a None field but never aborts the others. The
    assembled result is cached for ``settings.cache_ttl_macro`` seconds unless
    it is completely empty (so a total outage does not poison the cache).

    Args:
        force_refresh: Skip the cache read and always fetch live (a fresh
                       result is still written back to the cache).

    Returns:
        A MacroData instance. Never raises for blocked/failed sources.
    """
    # 1. Read-through cache (unless force_refresh)
    if not force_refresh:
        cached = cache_get_json(MACRO_CACHE_KEY)
        if cached is not None:
            try:
                model = MacroData(**cached)
                model.cached = True
                logger.info("Macro data served from cache")
                return model
            except Exception as exc:
                # Corrupt/old-schema cache entry — log and fall through to live.
                logger.warning("Ignoring unparseable cached macro data: %s", exc)

    # 2. Fetch each source independently
    repo_rate, repo_as_of, repo_warn = _fetch_repo_rate()
    cpi, cpi_as_of, cpi_warn = _fetch_cpi()
    gdp, gdp_as_of, gdp_warn = _fetch_gdp()

    sources: dict[str, str] = {}
    if repo_rate is not None:
        sources["repo_rate"] = "rbi"
    if cpi is not None:
        sources["cpi_inflation"] = "mospi"
    if gdp is not None:
        sources["gdp_growth"] = "worldbank"

    warnings = [*repo_warn, *cpi_warn, *gdp_warn]

    data = MacroData(
        country="India",
        repo_rate=repo_rate,
        cpi_inflation=cpi,
        gdp_growth=gdp,
        repo_rate_as_of=repo_as_of,
        cpi_as_of=cpi_as_of,
        gdp_as_of=gdp_as_of,
        sources=sources,
        warnings=warnings,
        fetched_at=datetime.now(tz=timezone.utc),
        cached=False,
        source="rbi+mospi+worldbank",
    )

    # 3. Cache only a non-empty result (avoid serving 24h of all-None data)
    if data.has_any_data:
        cache_set_json(MACRO_CACHE_KEY, data.model_dump(mode="json"), _cache_ttl())
    else:
        logger.warning("All macro sources failed — result not cached")

    return data


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def fetch_macro_data(force_refresh: bool = False) -> dict[str, Any]:
    """
    Fetch the current Indian macro snapshot: repo rate, CPI inflation, GDP growth.

    Gathers three figures from three independent free sources — the RBI policy
    repo rate (scraped), CPI inflation (scraped from MOSPI), and real GDP growth
    (World Bank API). Any single source being blocked or unavailable yields a
    None for that field plus a warning; the other two still populate. The result
    is cached in Redis for 24 hours.

    Args:
        force_refresh: When True, bypass the cached value and fetch live data.
                       The fresh result is written back to the cache. Default
                       False (serve a cached snapshot if one exists).

    Returns:
        Dict representation of MacroData containing:
        - country
        - repo_rate (float | None, percent)
        - cpi_inflation (float | None, percent YoY)
        - gdp_growth (float | None, annual percent)
        - repo_rate_as_of, cpi_as_of, gdp_as_of
        - sources (per-field provenance map)
        - warnings (list of non-fatal issues, e.g. a blocked scrape)
        - fetched_at, cached, source

        On an unexpected programming error, returns a dict with an 'error' key
        instead of raising. A blocked scrape is NOT an error — it returns a
        valid MacroData with the relevant field set to None and a warning.

    Example:
        >>> result = fetch_macro_data.invoke({})
        >>> result["repo_rate"]
        6.5
        >>> result["gdp_growth"]
        7.0
    """
    try:
        data = _fetch_macro_data(force_refresh=force_refresh)
        return data.model_dump(mode="json")
    except Exception as exc:
        logger.exception("Unexpected error in fetch_macro_data")
        return {
            "error": "unexpected_error",
            "country": "India",
            "message": f"An unexpected error occurred: {exc}",
        }


@tool
def fetch_macro_summary() -> dict[str, Any]:
    """
    Fetch a lightweight macro summary: the three headline numbers only.

    Use this when the agent only needs repo rate, CPI inflation, and GDP growth
    without the full provenance/warnings metadata — keeps the LLM context small.
    Reads through the same 24h Redis cache as fetch_macro_data.

    Returns:
        Dict with keys: country, repo_rate, cpi_inflation, gdp_growth, cached,
        fetched_at, warnings. Returns an error dict on an unexpected failure.
    """
    try:
        data = _fetch_macro_data(force_refresh=False)
        return {
            "country": data.country,
            "repo_rate": data.repo_rate,
            "cpi_inflation": data.cpi_inflation,
            "gdp_growth": data.gdp_growth,
            "cached": data.cached,
            "fetched_at": data.fetched_at.isoformat(),
            "warnings": data.warnings,
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_macro_summary")
        return {
            "error": "unexpected_error",
            "country": "India",
            "message": f"An unexpected error occurred: {exc}",
        }
