# backend/tools/ratios.py
"""
AIRP — fetch_ratios LangChain Tools

Computes the six core valuation and quality ratios used by the Fundamental
Analyst and Valuation agents, combining two free data sources:

    1. yFinance  — quote metadata (.info) + annual statements (primary source)
    2. Alpha Vantage OVERVIEW — used to fill gaps and cross-check yFinance
                                (best-effort; free tier = 25 requests/day)

Ratios computed (all derived from raw primitives, never blindly copied):

    PE  (Price / Earnings)          = price / trailing EPS
    PB  (Price / Book)              = price / book value per share
    ROE (Return on Equity)          = net income / shareholders' equity   (%)
    ROCE (Return on Capital Empl.)  = EBIT / capital employed             (%)
                                      capital employed = total assets
                                                         - current liabilities
    D/E (Debt / Equity)             = total debt / shareholders' equity
    EV/EBITDA                       = enterprise value / EBITDA
                                      enterprise value = market cap
                                                         + total debt - cash

Tools exposed:
    fetch_ratios          — All six ratios + the raw inputs used (full model)
    fetch_ratios_summary  — Six ratios only (lightweight format for the debate
                            viewer; no input breakdown)

Design notes:
    * `_compute_ratios` is a pure function of `RatioInputs` so the maths can be
      unit-tested against hand calculations with zero network access.
    * `_fetch_ratios_from_sources` is separated from the @tool decorator so it
      can be invoked directly in tests (mocking yFinance + Alpha Vantage).
    * Every ratio records which source produced it (`computed`, `alpha_vantage`)
      so agents and reviewers can audit the figure's provenance.

Ratios are unitless (or percentages) so currency normalisation is unnecessary:
all inputs are taken in the company's native reporting currency and the units
cancel in the division.

Usage (inside an agent):
    from backend.tools.ratios import fetch_ratios
    result = fetch_ratios.invoke({"ticker": "TCS.NS"})
    pe = result["pe_ratio"]
"""
from __future__ import annotations

from datetime import datetime
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
import yfinance as yf

try:
    from backend.config import settings as _settings
except Exception:
    _settings = None  # type: ignore[assignment]

# Module-level alias — patch target in tests:
#   patch("backend.tools.ratios.settings") replaces this object
settings = _settings

from backend.tools.cache import RATIOS_TTL, cached  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_FUNCTION = "OVERVIEW"

# Cross-check tolerance: if a yFinance-computed ratio and the Alpha Vantage
# reported value diverge by more than this fraction, emit a data_warning.
CROSS_CHECK_TOLERANCE = 0.25  # 25%

# Retry policy mirrors news.py: 3 attempts, exponential back-off 2s → 60s.
_RETRY_ATTEMPTS = 3
_RETRY_WAIT_MIN = 2  # seconds
_RETRY_WAIT_MAX = 60  # seconds

# The six ratio keys, in canonical display order.
RATIO_KEYS: tuple[str, ...] = (
    "pe_ratio",
    "pb_ratio",
    "roe_pct",
    "roce_pct",
    "debt_to_equity",
    "ev_to_ebitda",
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class RatiosNotFoundError(Exception):
    """Raised when no usable data is available for the requested ticker."""


class AlphaVantageError(Exception):
    """Raised for unrecoverable Alpha Vantage errors (invalid key / symbol)."""


class AlphaVantageRateLimitError(Exception):
    """Raised when Alpha Vantage signals throttling — triggers tenacity retry."""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RatioInputs(BaseModel):
    """
    The raw primitives used to compute the ratios, in the company's native
    reporting currency. Exposed in the output so agents (and reviewers) can
    audit exactly how each ratio was derived.
    """

    price: float | None = Field(default=None, description="Current share price")
    eps: float | None = Field(default=None, description="Trailing EPS (per share)")
    book_value_per_share: float | None = Field(
        default=None, description="Book value per share"
    )
    shares_outstanding: float | None = Field(
        default=None, description="Shares outstanding"
    )
    net_income: float | None = Field(
        default=None, description="Net income (PAT), most recent fiscal year"
    )
    total_equity: float | None = Field(
        default=None, description="Shareholders' equity, most recent fiscal year"
    )
    operating_income: float | None = Field(
        default=None, description="Operating income (EBIT), most recent fiscal year"
    )
    total_assets: float | None = Field(
        default=None, description="Total assets, most recent fiscal year"
    )
    current_liabilities: float | None = Field(
        default=None, description="Current liabilities, most recent fiscal year"
    )
    total_debt: float | None = Field(default=None, description="Total debt")
    cash: float | None = Field(default=None, description="Cash and cash equivalents")
    market_cap: float | None = Field(default=None, description="Market capitalisation")
    ebitda: float | None = Field(default=None, description="EBITDA")

    model_config = {"frozen": True}


class RatiosModel(BaseModel):
    """
    Output model for the fetch_ratios tool — the six core ratios plus the
    inputs and provenance metadata needed to trust the figures.
    """

    ticker: str = Field(description="Ticker symbol as passed (e.g. 'TCS.NS')")
    company_name: str = Field(description="Company display name from Yahoo Finance")
    currency: str = Field(
        default="INR",
        description="Native reporting currency (ratios are unitless)",
    )

    pe_ratio: float | None = Field(
        default=None, description="Price-to-Earnings ratio (trailing)"
    )
    pb_ratio: float | None = Field(default=None, description="Price-to-Book ratio")
    roe_pct: float | None = Field(
        default=None, description="Return on Equity as a percentage (0-100 typical)"
    )
    roce_pct: float | None = Field(
        default=None,
        description="Return on Capital Employed as a percentage (0-100 typical)",
    )
    debt_to_equity: float | None = Field(
        default=None, description="Total Debt / Shareholders' Equity (unitless)"
    )
    ev_to_ebitda: float | None = Field(
        default=None, description="Enterprise Value / EBITDA (unitless)"
    )

    enterprise_value: float | None = Field(
        default=None,
        description="Derived enterprise value (market cap + debt - cash)",
    )
    inputs: RatioInputs = Field(
        description="Raw primitives used to compute each ratio (audit trail)"
    )
    sources: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-ratio provenance: 'computed' (from yFinance primitives) or "
            "'alpha_vantage' (filled from the Alpha Vantage OVERVIEW endpoint)"
        ),
    )
    fetched_at: datetime = Field(description="UTC timestamp of this data fetch")
    source: str = Field(
        default="yfinance+alphavantage", description="Data provider identifier"
    )
    data_warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings about missing or divergent data",
    )

    @field_validator("ticker")
    @classmethod
    def ticker_must_be_non_empty(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("ticker must not be empty")
        return v


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — fully unit-testable)
# ---------------------------------------------------------------------------


def _safe_info_get(info: dict[str, Any], key: str) -> float | None:
    """
    Read a numeric field from a yFinance .info dict, returning None when the
    value is missing, non-numeric, or NaN.

    Distinguishing None from 0.0 matters: a missing field must not be silently
    treated as zero (which would corrupt a ratio).
    """
    if key not in info:
        return None
    val = info.get(key)
    if val is None:
        return None
    try:
        fval = float(val)
    except (TypeError, ValueError):
        return None
    return None if fval != fval else fval  # NaN check without importing math


def _statement_get(df: Any, row_key: str, col_index: int = 0) -> float | None:
    """
    Safely extract a single float from a yFinance statements DataFrame
    (rows = line items, columns = fiscal dates, most recent first).

    Returns None when the DataFrame is empty, the row is absent, the column
    index is out of range, or the value is non-numeric / NaN.
    """
    if df is None or getattr(df, "empty", True):
        return None
    if row_key not in df.index:
        return None
    cols = list(df.columns)
    if col_index >= len(cols):
        return None
    val = df.loc[row_key, cols[col_index]]
    if val is None:
        return None
    try:
        fval = float(val)
    except (TypeError, ValueError):
        return None
    return None if fval != fval else fval


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """
    Divide two optionals, returning None when either is missing or the
    denominator is not strictly positive.

    A non-positive denominator (zero or negative equity / EBITDA / earnings)
    makes the ratio economically meaningless, so None is returned rather than
    a misleading negative or infinite value.
    """
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    return round(numerator / denominator, 2)


def _percentage(numerator: float | None, denominator: float | None) -> float | None:
    """
    Return ``numerator / denominator`` as a percentage, rounded once at the end.

    Computing the percentage in a single step (rather than rounding the ratio
    first and then multiplying by 100) preserves precision — e.g. 46000/90000
    yields 51.11%, not 51.0%.
    """
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _compute_ratios(inputs: RatioInputs) -> dict[str, float | None]:
    """
    Compute the six ratios from raw primitives. Pure function — no network,
    no side effects — so it can be verified directly against hand calculations.

    Returns a dict with the six RATIO_KEYS plus 'enterprise_value'. Any ratio
    whose inputs are missing or whose denominator is non-positive is None.
    """
    # Enterprise value = market cap + total debt - cash
    enterprise_value: float | None = None
    if inputs.market_cap is not None:
        debt = inputs.total_debt or 0.0
        cash = inputs.cash or 0.0
        enterprise_value = round(inputs.market_cap + debt - cash, 2)

    # Capital employed = total assets - current liabilities
    capital_employed: float | None = None
    if inputs.total_assets is not None and inputs.current_liabilities is not None:
        capital_employed = inputs.total_assets - inputs.current_liabilities

    return {
        "pe_ratio": _ratio(inputs.price, inputs.eps),
        "pb_ratio": _ratio(inputs.price, inputs.book_value_per_share),
        # ROE / ROCE are percentages — computed in one step to keep precision
        "roe_pct": _percentage(inputs.net_income, inputs.total_equity),
        "roce_pct": _percentage(inputs.operating_income, capital_employed),
        "debt_to_equity": _ratio(inputs.total_debt, inputs.total_equity),
        "ev_to_ebitda": _ratio(enterprise_value, inputs.ebitda),
        "enterprise_value": enterprise_value,
    }


def _parse_av_float(raw: Any) -> float | None:
    """
    Parse a numeric field from an Alpha Vantage OVERVIEW response.

    Alpha Vantage returns every field as a string; missing values appear as
    'None', '-', or ''. Returns None for any of those, or for unparseable text.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text in ("", "None", "-", "NaN"):
        return None
    try:
        fval = float(text)
    except ValueError:
        return None
    return None if fval != fval else fval


def _parse_av_overview(payload: dict[str, Any]) -> dict[str, float | None]:
    """
    Map an Alpha Vantage OVERVIEW payload onto the six ratio keys.

    ReturnOnEquityTTM is reported as a fraction (e.g. '0.45'), so it is scaled
    to a percentage to match AIRP's convention. PE / PB / EV-EBITDA are already
    in the correct units.
    """
    roe_fraction = _parse_av_float(payload.get("ReturnOnEquityTTM"))
    return {
        "pe_ratio": _parse_av_float(payload.get("PERatio")),
        "pb_ratio": _parse_av_float(payload.get("PriceToBookRatio")),
        "roe_pct": (round(roe_fraction * 100, 2) if roe_fraction is not None else None),
        # Alpha Vantage OVERVIEW does not expose ROCE
        "roce_pct": None,
        "debt_to_equity": None,  # not in OVERVIEW; computed from statements only
        "ev_to_ebitda": _parse_av_float(payload.get("EVToEBITDA")),
    }


# ---------------------------------------------------------------------------
# Alpha Vantage HTTP layer (with tenacity retry)
# ---------------------------------------------------------------------------


def _handle_av_response(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Inspect an Alpha Vantage JSON body and raise the appropriate exception.

    Alpha Vantage returns HTTP 200 even when throttled: a 'Note' or
    'Information' key signals the rate limit, and an 'Error Message' key
    signals an invalid symbol or request. An empty body means no coverage.

    Separated from the HTTP call so the raising logic is unit-testable without
    triggering tenacity's retry/back-off sleeps.
    """
    if "Note" in payload or "Information" in payload:
        raise AlphaVantageRateLimitError(
            "Alpha Vantage rate limit reached (free tier: 25 requests/day)"
        )
    if "Error Message" in payload:
        raise AlphaVantageError(f"Alpha Vantage error: {payload.get('Error Message')}")
    return payload


@retry(
    retry=(
        retry_if_exception_type(AlphaVantageRateLimitError)
        | retry_if_exception_type(requests.Timeout)
        | retry_if_exception_type(requests.ConnectionError)
    ),
    wait=wait_exponential(multiplier=1, min=_RETRY_WAIT_MIN, max=_RETRY_WAIT_MAX),
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _request_alpha_vantage(symbol: str, api_key: str) -> dict[str, Any]:
    """
    Fetch the Alpha Vantage OVERVIEW for a symbol, with retry on throttling
    and transient network errors.

    Raises:
        AlphaVantageRateLimitError: on throttling — tenacity will retry.
        AlphaVantageError:          on invalid symbol / request.
        requests.Timeout / ConnectionError: transient — tenacity will retry.
    """
    params = {
        "function": ALPHA_VANTAGE_FUNCTION,
        "symbol": symbol,
        "apikey": api_key,
    }
    response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=15)

    if response.status_code == 429:
        raise AlphaVantageRateLimitError("Alpha Vantage HTTP 429 (rate limit)")
    if response.status_code >= 500:
        raise requests.ConnectionError(
            f"Alpha Vantage server error HTTP {response.status_code}"
        )
    response.raise_for_status()

    payload: dict[str, Any] = response.json()
    return _handle_av_response(payload)


def _fetch_alpha_vantage_ratios(ticker: str) -> dict[str, float | None] | None:
    """
    Best-effort Alpha Vantage ratios for gap-filling. Returns None (never
    raises) when no key is configured, the symbol has no coverage, or the
    request fails — yFinance remains the primary source.

    Alpha Vantage uses bare US-style symbols, so the exchange suffix is
    stripped (TCS.NS → TCS). Indian listings frequently have no OVERVIEW
    coverage; that is expected and handled silently.
    """
    api_key = os.environ.get("ALPHA_VANTAGE_KEY", "")
    if not api_key and settings is not None:
        api_key = settings.alpha_vantage_key or ""
    if not api_key:
        return None

    symbol = ticker.split(".")[0].split(":")[0]
    try:
        payload = _request_alpha_vantage(symbol=symbol, api_key=api_key)
    except (AlphaVantageError, AlphaVantageRateLimitError, RetryError) as exc:
        logger.warning("Alpha Vantage unavailable for %s: %s", symbol, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — best-effort, never fatal
        logger.warning("Alpha Vantage request failed for %s: %s", symbol, exc)
        return None

    if not payload or payload.get("Symbol") is None:
        return None
    return _parse_av_overview(payload)


# ---------------------------------------------------------------------------
# Core fetch logic (separated from @tool for testability)
# ---------------------------------------------------------------------------


def _build_inputs(info: dict[str, Any], balance_df: Any, income_df: Any) -> RatioInputs:
    """Assemble RatioInputs from yFinance .info and the annual statements."""
    return RatioInputs(
        price=_safe_info_get(info, "currentPrice")
        or _safe_info_get(info, "regularMarketPrice"),
        eps=_safe_info_get(info, "trailingEps"),
        book_value_per_share=_safe_info_get(info, "bookValue"),
        shares_outstanding=_safe_info_get(info, "sharesOutstanding"),
        net_income=_statement_get(income_df, "Net Income")
        or _safe_info_get(info, "netIncomeToCommon"),
        total_equity=_statement_get(balance_df, "Stockholders Equity"),
        operating_income=_statement_get(income_df, "Operating Income")
        or _statement_get(income_df, "EBIT"),
        total_assets=_statement_get(balance_df, "Total Assets"),
        current_liabilities=_statement_get(balance_df, "Current Liabilities"),
        total_debt=_statement_get(balance_df, "Total Debt")
        or _safe_info_get(info, "totalDebt"),
        cash=_statement_get(balance_df, "Cash And Cash Equivalents")
        or _safe_info_get(info, "totalCash"),
        market_cap=_safe_info_get(info, "marketCap"),
        ebitda=_safe_info_get(info, "ebitda") or _statement_get(income_df, "EBITDA"),
    )


def _merge_with_alpha_vantage(
    computed: dict[str, float | None],
    av_ratios: dict[str, float | None] | None,
) -> tuple[dict[str, float | None], dict[str, str], list[str]]:
    """
    Fill any missing computed ratios from Alpha Vantage and cross-check the
    ones present in both sources.

    Returns:
        (final_ratios, sources, warnings)
        - final_ratios: the six ratios after gap-filling
        - sources:      per-ratio provenance ('computed' / 'alpha_vantage')
        - warnings:     divergence notes where the two sources disagree
    """
    final: dict[str, float | None] = {k: computed.get(k) for k in RATIO_KEYS}
    sources: dict[str, str] = {}
    warnings: list[str] = []

    for key in RATIO_KEYS:
        computed_val = computed.get(key)
        av_val = av_ratios.get(key) if av_ratios else None

        if computed_val is not None:
            sources[key] = "computed"
            # Cross-check against Alpha Vantage where both exist
            if av_val is not None and av_val != 0:
                divergence = abs(computed_val - av_val) / abs(av_val)
                if divergence > CROSS_CHECK_TOLERANCE:
                    warnings.append(
                        f"{key}: computed {computed_val} diverges >"
                        f"{int(CROSS_CHECK_TOLERANCE * 100)}% from Alpha Vantage "
                        f"{av_val} — verify before relying on this figure"
                    )
        elif av_val is not None:
            final[key] = av_val
            sources[key] = "alpha_vantage"
        else:
            sources[key] = "unavailable"

    return final, sources, warnings


def _fetch_ratios_from_sources(ticker: str) -> RatiosModel:
    """
    Core fetch logic — gathers primitives from yFinance, computes the six
    ratios, fills gaps from Alpha Vantage, and returns a validated RatiosModel.

    Raises:
        RatiosNotFoundError: when neither yFinance nor Alpha Vantage yields any
                             usable data for the ticker.
    """
    ticker = ticker.strip().upper()
    logger.info("Fetching ratios: ticker=%s", ticker)

    yf_ticker = yf.Ticker(ticker)

    info: dict[str, Any] = {}
    try:
        info = yf_ticker.info or {}
    except Exception:
        logger.warning("Could not fetch ticker info for %s", ticker)

    balance_df = yf_ticker.balance_sheet
    income_df = yf_ticker.financials

    inputs = _build_inputs(info, balance_df, income_df)
    computed = _compute_ratios(inputs)

    av_ratios = _fetch_alpha_vantage_ratios(ticker)
    final, sources, warnings = _merge_with_alpha_vantage(computed, av_ratios)

    # Guard: if every ratio is unavailable, the ticker is effectively invalid.
    if all(final[k] is None for k in RATIO_KEYS):
        raise RatiosNotFoundError(
            f"No ratio data found for ticker '{ticker}'. Verify the symbol — "
            "Indian NSE stocks use the '.NS' suffix (e.g. 'TCS.NS'), BSE stocks "
            "use '.BO'."
        )

    company_name: str = info.get("longName") or info.get("shortName") or ticker
    currency: str = info.get("financialCurrency") or info.get("currency") or "INR"

    if av_ratios is None:
        warnings.append(
            "Alpha Vantage gap-fill skipped (no key configured or no coverage "
            "for this symbol); ratios computed from yFinance only"
        )

    return RatiosModel(
        ticker=ticker,
        company_name=company_name,
        currency=currency,
        pe_ratio=final["pe_ratio"],
        pb_ratio=final["pb_ratio"],
        roe_pct=final["roe_pct"],
        roce_pct=final["roce_pct"],
        debt_to_equity=final["debt_to_equity"],
        ev_to_ebitda=final["ev_to_ebitda"],
        enterprise_value=computed["enterprise_value"],
        inputs=inputs,
        sources=sources,
        fetched_at=datetime.utcnow(),
        source="yfinance+alphavantage",
        data_warnings=warnings,
    )


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@cached(key="airp:ratios:{ticker}", ttl=RATIOS_TTL)
def _fetch_ratios_cached(ticker: str) -> dict[str, Any]:
    """
    Cached wrapper around ``_fetch_ratios_from_sources``.

    Serves from Redis for ``RATIOS_TTL`` seconds on a cache hit; calls
    the live data sources and caches the result on a miss.
    """
    result = _fetch_ratios_from_sources(ticker=ticker)
    return result.model_dump(mode="json")


@tool
def fetch_ratios(ticker: str) -> dict[str, Any]:
    """
    Compute the six core valuation and quality ratios for a stock.

    Ratios returned: PE (price/earnings), PB (price/book), ROE (return on
    equity, %), ROCE (return on capital employed, %), Debt/Equity, and
    EV/EBITDA. Values are derived from yFinance primitives and gap-filled from
    Alpha Vantage where yFinance is missing data. Each ratio's provenance is
    reported in the 'sources' field.

    Args:
        ticker: Stock ticker with exchange suffix. Indian NSE stocks require
                the '.NS' suffix (e.g. 'TCS.NS', 'INFY.NS', 'RELIANCE.NS').
                BSE stocks use '.BO'. US stocks use plain symbols ('AAPL').

    Returns:
        Dict representation of RatiosModel containing:
        - ticker, company_name, currency
        - pe_ratio, pb_ratio, roe_pct, roce_pct, debt_to_equity, ev_to_ebitda
        - enterprise_value (derived)
        - inputs: the raw primitives used (audit trail)
        - sources: per-ratio provenance ('computed' / 'alpha_vantage')
        - data_warnings, fetched_at, source

    On error, returns a dict with an 'error' key instead of raising.

    Example:
        >>> result = fetch_ratios.invoke({"ticker": "TCS.NS"})
        >>> result["pe_ratio"]
        29.4
    """
    try:
        return _fetch_ratios_cached(ticker=ticker)
    except RatiosNotFoundError as exc:
        logger.error("Ratios not found: %s — %s", ticker, exc)
        return {
            "error": "ratios_not_found",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_ratios: ticker=%s", ticker)
        return {
            "error": "unexpected_error",
            "ticker": ticker.strip().upper(),
            "message": f"An unexpected error occurred: {exc}",
        }


@tool
def fetch_ratios_summary(ticker: str) -> dict[str, Any]:
    """
    Fetch the six core ratios only — a lightweight format for the debate viewer.

    Use this when an agent needs the headline ratios without the full input
    breakdown or provenance metadata, to keep LLM context windows small.

    Args:
        ticker: Stock ticker with exchange suffix (e.g. 'INFY.NS').

    Returns:
        Dict with keys: ticker, company_name, currency, pe_ratio, pb_ratio,
        roe_pct, roce_pct, debt_to_equity, ev_to_ebitda, data_warnings.
        Returns an error dict on failure.
    """
    try:
        data = _fetch_ratios_cached(ticker=ticker)
        if "error" in data:
            return data
        return {
            "ticker": data["ticker"],
            "company_name": data["company_name"],
            "currency": data["currency"],
            "pe_ratio": data["pe_ratio"],
            "pb_ratio": data["pb_ratio"],
            "roe_pct": data["roe_pct"],
            "roce_pct": data["roce_pct"],
            "debt_to_equity": data["debt_to_equity"],
            "ev_to_ebitda": data["ev_to_ebitda"],
            "data_warnings": data["data_warnings"],
        }
    except RatiosNotFoundError as exc:
        return {
            "error": "ratios_not_found",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_ratios_summary: ticker=%s", ticker)
        return {
            "error": "unexpected_error",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
