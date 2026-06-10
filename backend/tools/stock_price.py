# backend/tools/stock_price.py
"""
AIRP — fetch_stock_price LangChain Tool

Wraps yFinance to provide OHLCV daily price data and summary statistics
for Indian (NSE/BSE) and global equities. Returns a fully-typed Pydantic
model so agents always receive structured, validated data.

Tools exposed:
    fetch_stock_price  — OHLCV candles + summary for a given ticker and period
    fetch_ohlcv        — Raw OHLCV DataFrame serialised to records (for charting)

Data source: yFinance (unofficial Yahoo Finance API — no key required)
Cache:       Redis (TTL = settings.cache_ttl_stock, default 15 min)

Indian ticker convention:
    NSE stocks → append `.NS`  (e.g. TCS → TCS.NS)
    BSE stocks → append `.BO`  (e.g. TCS → 532540.BO)

Usage (inside an agent):
    from backend.tools.stock_price import fetch_stock_price
    result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})
"""
from datetime import date as Date, datetime
import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator
import yfinance as yf

from backend.tools.cache import STOCK_TTL, cached

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PERIODS: frozenset[str] = frozenset({"1y", "3y", "5y"})

# Map human-readable periods to yFinance period strings
PERIOD_MAP: dict[str, str] = {
    "1y": "1y",
    "3y": "3y",
    "5y": "5y",
}


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------


class OHLCVRecord(BaseModel):
    """Single daily OHLCV candle."""

    date: Date = Field(description="Trading date (YYYY-MM-DD)")
    open: float = Field(description="Opening price (INR / native currency)")
    high: float = Field(description="Intraday high price")
    low: float = Field(description="Intraday low price")
    close: float = Field(description="Closing price (adjusted)")
    volume: int = Field(description="Number of shares traded")

    model_config = {"frozen": True}


class PriceStats(BaseModel):
    """Derived statistics computed from the OHLCV series."""

    current_price: float = Field(description="Most recent closing price")
    price_52w_high: float = Field(description="52-week high closing price")
    price_52w_low: float = Field(description="52-week low closing price")
    avg_volume_30d: int = Field(
        description="Average daily volume over last 30 sessions"
    )
    pct_change_1m: float = Field(description="Price return over last 30 sessions (%)")
    pct_change_3m: float = Field(description="Price return over last 63 sessions (%)")
    pct_change_1y: float = Field(description="Price return over last 252 sessions (%)")
    ma_50d: float | None = Field(
        default=None,
        description="50-day simple moving average (None if < 50 data points)",
    )
    ma_200d: float | None = Field(
        default=None,
        description="200-day simple moving average (None if < 200 data points)",
    )
    above_ma_50d: bool | None = Field(
        default=None,
        description="True if current price is above the 50-day MA",
    )
    above_ma_200d: bool | None = Field(
        default=None,
        description="True if current price is above the 200-day MA",
    )


class StockPrice(BaseModel):
    """
    Complete output model for the fetch_stock_price tool.

    Returned to agents as a validated, typed object. All fields are
    populated from yFinance data; the model raises ValidationError if
    yFinance returns structurally invalid data.
    """

    ticker: str = Field(description="Ticker symbol exactly as passed (e.g. TCS.NS)")
    company_name: str = Field(description="Company display name from Yahoo Finance")
    exchange: str = Field(description="Exchange code (e.g. NSE, BSE, NASDAQ)")
    currency: str = Field(description="Trading currency (e.g. INR, USD)")
    period: str = Field(description="Requested data period (1y / 3y / 5y)")
    data_points: int = Field(description="Number of daily candles returned")
    first_date: Date = Field(description="Date of the oldest candle in this response")
    last_date: Date = Field(description="Date of the most recent candle")
    stats: PriceStats = Field(description="Derived price statistics")
    ohlcv: list[OHLCVRecord] = Field(
        description="Full daily OHLCV series for the requested period"
    )
    fetched_at: datetime = Field(description="UTC timestamp of this data fetch")
    source: str = Field(default="yfinance", description="Data provider identifier")

    @field_validator("ticker")
    @classmethod
    def ticker_must_be_non_empty(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("ticker must not be empty")
        return v

    @field_validator("period")
    @classmethod
    def period_must_be_valid(cls, v: str) -> str:
        if v not in VALID_PERIODS:
            raise ValueError(
                f"period must be one of {sorted(VALID_PERIODS)}, got '{v}'"
            )
        return v


class TickerNotFoundError(Exception):
    """Raised when yFinance cannot find data for the requested ticker."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_pct_change(series: list[float], lookback: int) -> float:
    """
    Compute percentage price change over the last `lookback` data points.

    Returns 0.0 if the series is shorter than 2 points or shorter than
    `lookback`, to avoid crashes on thinly-traded or newly-listed stocks.
    """
    if len(series) < 2:
        return 0.0
    start_idx = max(0, len(series) - lookback - 1)
    start_price = series[start_idx]
    end_price = series[-1]
    if start_price == 0:
        return 0.0
    return round(((end_price - start_price) / start_price) * 100, 2)


def _compute_sma(closes: list[float], window: int) -> float | None:
    """Return the simple moving average over the last `window` closes, or None."""
    if len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 2)


def _build_stats(ohlcv_records: list[OHLCVRecord]) -> PriceStats:
    """Derive PriceStats from a list of OHLCVRecord objects."""
    closes = [r.close for r in ohlcv_records]
    volumes = [r.volume for r in ohlcv_records]

    current_price = closes[-1]

    # 52-week window = last 252 trading days
    window_252 = ohlcv_records[-252:]
    price_52w_high = max(r.high for r in window_252)
    price_52w_low = min(r.low for r in window_252)

    avg_volume_30d = int(sum(volumes[-30:]) / min(30, len(volumes)))

    pct_1m = _compute_pct_change(closes, lookback=30)
    pct_3m = _compute_pct_change(closes, lookback=63)
    pct_1y = _compute_pct_change(closes, lookback=252)

    ma_50 = _compute_sma(closes, 50)
    ma_200 = _compute_sma(closes, 200)

    return PriceStats(
        current_price=round(current_price, 2),
        price_52w_high=round(price_52w_high, 2),
        price_52w_low=round(price_52w_low, 2),
        avg_volume_30d=avg_volume_30d,
        pct_change_1m=pct_1m,
        pct_change_3m=pct_3m,
        pct_change_1y=pct_1y,
        ma_50d=ma_50,
        ma_200d=ma_200,
        above_ma_50d=(current_price > ma_50) if ma_50 is not None else None,
        above_ma_200d=(current_price > ma_200) if ma_200 is not None else None,
    )


def _fetch_stock_data(ticker: str, period: str) -> dict[str, Any]:
    """
    Core yFinance fetch — separated from the LangChain @tool decorator so it
    can be called directly in tests without invoking the full tool machinery.

    Wrapped by ``_fetch_stock_cached`` below for Redis caching.
    """
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Invalid period '{period}'. Must be one of {sorted(VALID_PERIODS)}"
        )

    logger.info("Fetching yFinance data: ticker=%s period=%s", ticker, period)

    yf_ticker = yf.Ticker(ticker)

    # Download historical OHLCV
    hist = yf_ticker.history(period=PERIOD_MAP[period], auto_adjust=True)

    if hist.empty:
        raise TickerNotFoundError(
            f"No price data found for ticker '{ticker}'. "
            "Check the ticker symbol — Indian NSE stocks use the '.NS' suffix "
            "(e.g. 'TCS.NS'), BSE stocks use '.BO' (e.g. '532540.BO')."
        )

    # Parse ticker metadata
    info: dict[str, Any] = {}
    try:
        info = yf_ticker.info or {}
    except Exception:
        logger.warning("Could not fetch ticker info for %s — using defaults", ticker)

    company_name: str = info.get("longName") or info.get("shortName") or ticker
    exchange: str = info.get("exchange") or "UNKNOWN"
    currency: str = info.get("currency") or "INR"

    # Build OHLCVRecord list
    records: list[OHLCVRecord] = []
    for idx_date, row in hist.iterrows():
        if hasattr(idx_date, "date"):
            trading_date = idx_date.date()
        else:
            trading_date = idx_date

        records.append(
            OHLCVRecord(
                date=trading_date,
                open=round(float(row["Open"]), 2),
                high=round(float(row["High"]), 2),
                low=round(float(row["Low"]), 2),
                close=round(float(row["Close"]), 2),
                volume=int(row["Volume"]),
            )
        )

    if not records:
        raise TickerNotFoundError(
            f"yFinance returned an empty history DataFrame for '{ticker}'."
        )

    stats = _build_stats(records)

    return StockPrice(
        ticker=ticker.upper(),
        company_name=company_name,
        exchange=exchange,
        currency=currency,
        period=period,
        data_points=len(records),
        first_date=records[0].date,
        last_date=records[-1].date,
        stats=stats,
        ohlcv=records,
        fetched_at=datetime.utcnow(),
        source="yfinance",
    ).model_dump(mode="json")


@cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
def _fetch_stock_cached(ticker: str, period: str) -> dict[str, Any]:
    """
    Cached wrapper around ``_fetch_stock_data``.

    The ``@cached`` decorator intercepts the call: on a hit it returns the
    cached dict immediately; on a miss it calls ``_fetch_stock_data``,
    caches the result for ``STOCK_TTL`` seconds, then returns it.
    """
    return _fetch_stock_data(ticker=ticker, period=period)


# Preserve the original name used by tests that patch _fetch_from_yfinance.
# This alias lets existing tests continue working without change.
def _fetch_from_yfinance(ticker: str, period: str) -> StockPrice:
    """
    Legacy entry-point for direct unit tests.

    Returns a StockPrice object (not a dict) for backward compatibility with
    tests written before the @cached decorator was introduced.
    """
    result = _fetch_stock_data(ticker=ticker, period=period)
    return StockPrice(**result)


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def fetch_stock_price(ticker: str, period: str = "1y") -> dict[str, Any]:
    """
    Fetch daily OHLCV price data for a stock using yFinance.

    Returns price statistics (52-week high/low, moving averages, momentum)
    and the full OHLCV candle series for the requested period.

    Args:
        ticker: Stock ticker symbol. Indian NSE stocks must use the '.NS'
                suffix (e.g. 'TCS.NS', 'INFY.NS', 'RELIANCE.NS').
                BSE stocks use '.BO'. US stocks use plain symbols ('AAPL').
        period: Data period to fetch. One of: '1y' (1 year, default),
                '3y' (3 years), '5y' (5 years).

    Returns:
        Dict representation of StockPrice model containing:
        - ticker, company_name, exchange, currency
        - period, data_points, first_date, last_date
        - stats: PriceStats (current price, 52w high/low, MAs, returns)
        - ohlcv: list of daily candles [{date, open, high, low, close, volume}]
        - fetched_at, source

    Example:
        >>> result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})
        >>> result["stats"]["current_price"]
        3845.20
    """
    try:
        return _fetch_stock_cached(ticker=ticker, period=period)
    except TickerNotFoundError as exc:
        logger.error("Ticker not found: %s — %s", ticker, exc)
        return {
            "error": "ticker_not_found",
            "ticker": ticker,
            "message": str(exc),
        }
    except ValueError as exc:
        logger.error("Invalid parameter for fetch_stock_price: %s", exc)
        return {
            "error": "invalid_parameter",
            "ticker": ticker,
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_stock_price: ticker=%s", ticker)
        return {
            "error": "unexpected_error",
            "ticker": ticker,
            "message": f"An unexpected error occurred: {exc}",
        }


@tool
def fetch_ohlcv(ticker: str, period: str = "1y") -> dict[str, Any]:
    """
    Fetch raw OHLCV daily candle data for a stock (charting-optimised format).

    Lightweight wrapper that returns only the candle series without
    the full statistics block. Intended for the frontend charting pipeline.

    Args:
        ticker: Stock ticker symbol with exchange suffix (e.g. 'INFY.NS').
        period: One of '1y', '3y', '5y'.

    Returns:
        Dict with keys:
        - ticker (str)
        - period (str)
        - currency (str)
        - data_points (int)
        - ohlcv (list of {date, open, high, low, close, volume} dicts)
        - error (str, present only on failure)
    """
    try:
        full = _fetch_stock_cached(ticker=ticker, period=period)
        if "error" in full:
            return full
        return {
            "ticker": full["ticker"],
            "period": full["period"],
            "currency": full["currency"],
            "data_points": full["data_points"],
            "ohlcv": full["ohlcv"],
        }
    except TickerNotFoundError as exc:
        return {
            "error": "ticker_not_found",
            "ticker": ticker,
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_ohlcv: ticker=%s", ticker)
        return {
            "error": "unexpected_error",
            "ticker": ticker,
            "message": str(exc),
        }
