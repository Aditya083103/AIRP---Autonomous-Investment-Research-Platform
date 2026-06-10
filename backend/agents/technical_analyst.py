# backend/agents/technical_analyst.py
"""
AIRP -- Technical Analyst Agent (T-023)

Persona: seasoned technical chart analyst with 15 years of experience
reading price action on Indian equity markets (NSE/BSE).  Specialises in
trend identification, momentum analysis, and key-level extraction.

Mandate
-------
Analyse a company's price history using the ``fetch_stock_price`` tool
(1-year OHLCV data) and compute all technical indicators deterministically
before passing pre-processed context to the LLM for narrative synthesis.

Indicators computed (pure Python, no external TA library required):
  * SMA-50 and SMA-200  -- simple moving averages
  * RSI-14              -- 14-period Relative Strength Index (Wilder's method)
  * Golden / Death cross -- MA-50 vs MA-200 relationship
  * Momentum            -- 1m / 3m / 6m / 1y price return
  * Volume trend        -- 30-day vs prior-30-day average volume
  * 52-week positioning -- current price vs 52w high/low
  * Support / Resistance -- computed from recent swing highs/lows

Signal determination (deterministic, no LLM):
  Bullish signals:  price > MA50, price > MA200, RSI 40-70, golden cross,
                    positive 3m momentum
  Bearish signals:  price < MA50, price < MA200, RSI < 30 or > 75 (overbought
                    exhaustion), death cross, negative 3m momentum
  Signal = BUY if bullish_count >= 4 of 5 checks
  Signal = SELL if bearish_count >= 4 of 5 checks
  Signal = HOLD otherwise

Public interface
----------------
  run_technical_analysis(state)       -> dict   LangGraph node
  _run_technical_analysis_core(...)   -> TechnicalAnalysis   testable core
  compute_rsi(closes, period)         -> float | None   pure, unit-testable
  compute_sma(closes, window)         -> float | None   pure, unit-testable
  compute_momentum(closes, lookback)  -> float | None   pure, unit-testable
  _determine_signal(indicators)       -> tuple[str, int]  pure, unit-testable
  _extract_key_levels(ohlcv)          -> tuple[list, list]  pure, unit-testable
  _compute_volume_trend(ohlcv)        -> str   pure, unit-testable
  _build_technical_prompt(...)        -> str   pure, unit-testable

Design decisions
----------------
* NO ``from __future__ import annotations`` -- breaks Pydantic v2.
* RSI uses Wilder's smoothing (exponential moving average of gains/losses),
  which is the industry standard and matches TradingView / Bloomberg.
* All indicator computation is pure Python -- no pandas, no TA-lib.
  This keeps CI dependency-free and makes every formula unit-testable.
* Support/resistance levels are derived from swing highs/lows over the
  last 60 trading days (roughly 3 months), which is the most actionable
  timeframe for near-term positioning.
* The LLM is called ONLY for summary + narrative.  Signal, signal_strength,
  all numeric fields, and support/resistance are computed deterministically.
* Error convention: never raises.  On failure, TechnicalAnalysis.error is set.

Usage in LangGraph (Phase 3)
----------------------------
    from backend.agents.technical_analyst import run_technical_analysis
    builder.add_node("technical_analyst", run_technical_analysis)
    # Reads: state["job_id"], state["company_name"], state["ticker"]
    # Writes: state["technical"]  (dict from TechnicalAnalysis.model_dump())
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import TechnicalAnalysis
from backend.tools.stock_price import fetch_stock_price

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RSI_PERIOD: int = 14
SMA_SHORT: int = 50
SMA_LONG: int = 200

# Swing high/low lookback for support/resistance extraction
KEY_LEVEL_LOOKBACK: int = 60  # trading days ~= 3 months

# Volume comparison window
VOLUME_WINDOW: int = 30  # days per period

# Signal thresholds
BULLISH_THRESHOLD: int = 4  # of 5 checks must be bullish for BUY
BEARISH_THRESHOLD: int = 4  # of 5 checks must be bearish for SELL

RSI_OVERSOLD: float = 30.0
RSI_OVERBOUGHT: float = 70.0
RSI_OVERBOUGHT_EXHAUSTION: float = 75.0  # above this = bearish exhaustion

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a seasoned technical chart analyst with 15 years of \
experience reading price action on Indian equity markets (NSE and BSE). You \
specialise in trend identification, momentum analysis, and identifying key \
support and resistance levels.

Your job is to synthesise pre-computed technical indicators into a concise, \
investment-committee-ready assessment.

RULES:
1. Be specific -- reference the exact indicator values provided.
2. The summary must be 2-3 sentences maximum, written for a Portfolio Manager.
3. Do NOT use markdown, bullet symbols, or headers in your output.
4. Respond ONLY with valid JSON matching the exact schema below.
5. Do not invent numbers. Use only the values provided in the data.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "summary": "<2-3 sentence technical assessment citing specific levels>"
}

The summary should cover: trend direction, momentum, key support/resistance \
levels, and what the chart implies for near-term price direction."""

# ---------------------------------------------------------------------------
# Pure indicator computation functions (no I/O, fully unit-testable)
# ---------------------------------------------------------------------------


def compute_sma(closes: list[float], window: int) -> float | None:
    """
    Compute the Simple Moving Average of the last ``window`` closing prices.

    Returns None when fewer than ``window`` data points are available,
    so callers can distinguish "insufficient data" from a legitimate value.

    Args:
        closes: Chronological list of closing prices (oldest first).
        window: Number of periods for the moving average.

    Returns:
        Rounded SMA value, or None if len(closes) < window.
    """
    if not closes or window <= 0 or len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 2)


def compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """
    Compute the 14-period RSI using Wilder's exponential smoothing method.

    This matches the implementation used by TradingView and Bloomberg,
    making it the most appropriate benchmark for acceptance testing.

    Algorithm:
      1. Compute daily changes: delta[i] = close[i] - close[i-1]
      2. Separate gains (positive deltas) from losses (absolute negative deltas)
      3. Seed the first average gain/loss as the simple mean of the first
         ``period`` gains/losses
      4. Apply Wilder's smoothing for subsequent values:
         avg_gain[i] = (avg_gain[i-1] * (period-1) + gain[i]) / period
      5. RSI = 100 - (100 / (1 + avg_gain / avg_loss))

    Returns None when insufficient data (< period + 1 closes).

    Args:
        closes: Chronological list of closing prices (oldest first).
        period: RSI lookback period (default: 14).

    Returns:
        RSI value in range [0, 100], rounded to 2 decimal places, or None.
    """
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    # Seed: simple mean of first `period` values
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's smoothing over remaining values
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0  # all gains, no losses

    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def compute_momentum(closes: list[float], lookback: int) -> float | None:
    """
    Compute percentage price return over the last ``lookback`` trading days.

    Returns None when insufficient data is available.

    Args:
        closes: Chronological list of closing prices (oldest first).
        lookback: Number of trading days to look back.

    Returns:
        Percentage return (positive = price rose), rounded to 2 dp, or None.
    """
    if len(closes) < lookback + 1:
        return None
    start = closes[-(lookback + 1)]
    end = closes[-1]
    if start <= 0:
        return None
    return round(((end - start) / start) * 100, 2)


def _compute_volume_trend(ohlcv: list[dict[str, Any]]) -> str:
    """
    Classify volume trend by comparing the last 30-day average against the
    prior 30-day average.

    Returns:
        'increasing' -- recent volume > prior volume by > 10%
        'decreasing' -- recent volume < prior volume by > 10%
        'stable'     -- within +/-10%
        'unknown'    -- fewer than 31 candles available
    """
    if len(ohlcv) < VOLUME_WINDOW + 1:
        return "unknown"

    recent = ohlcv[-VOLUME_WINDOW:]
    prior = ohlcv[-(2 * VOLUME_WINDOW) : -VOLUME_WINDOW]  # noqa: E203

    if not prior:
        return "unknown"

    recent_avg = sum(c.get("volume", 0) for c in recent) / len(recent)
    prior_avg = sum(c.get("volume", 0) for c in prior) / len(prior)

    if prior_avg == 0:
        return "unknown"

    ratio = recent_avg / prior_avg
    if ratio > 1.10:
        return "increasing"
    if ratio < 0.90:
        return "decreasing"
    return "stable"


def _extract_key_levels(
    ohlcv: list[dict[str, Any]],
) -> tuple[list[float], list[float]]:
    """
    Extract support and resistance levels from swing highs and lows.

    Uses a simple swing-point algorithm over the last KEY_LEVEL_LOOKBACK
    candles: a swing high is a candle whose high is higher than both its
    neighbours; a swing low is a candle whose low is lower than both its
    neighbours.

    Returns at most 3 support and 3 resistance levels, sorted ascending
    and descending respectively, rounded to the nearest integer (clean levels).

    Args:
        ohlcv: List of OHLCV dicts (must have 'high', 'low', 'close' keys).

    Returns:
        Tuple of (support_levels, resistance_levels), each a list of floats.
    """
    window = ohlcv[-KEY_LEVEL_LOOKBACK:] if len(ohlcv) > KEY_LEVEL_LOOKBACK else ohlcv

    if len(window) < 3:
        return [], []

    swing_highs: list[float] = []
    swing_lows: list[float] = []

    for i in range(1, len(window) - 1):
        prev_h = window[i - 1].get("high", 0.0)
        curr_h = window[i].get("high", 0.0)
        next_h = window[i + 1].get("high", 0.0)

        prev_l = window[i - 1].get("low", float("inf"))
        curr_l = window[i].get("low", float("inf"))
        next_l = window[i + 1].get("low", float("inf"))

        if curr_h > prev_h and curr_h > next_h:
            swing_highs.append(round(curr_h))

        if curr_l < prev_l and curr_l < next_l:
            swing_lows.append(round(curr_l))

    current_price = ohlcv[-1].get("close", 0.0) if ohlcv else 0.0

    # Resistance = swing highs above current price (nearest 3)
    resistance = sorted({h for h in swing_highs if h > current_price})[:3]

    # Support = swing lows below current price (highest 3, i.e. nearest)
    support = sorted(
        {lo for lo in swing_lows if lo < current_price},
        reverse=True,
    )[:3]

    return support, resistance


def _determine_signal(
    price: float,
    ma50: float | None,
    ma200: float | None,
    rsi: float | None,
    momentum_3m: float | None,
) -> tuple[str, int]:
    """
    Determine BUY / HOLD / SELL signal and conviction strength (1-10).

    Uses 5 binary checks -- each contributes one bullish or bearish point:
      1. Price vs MA50   (bullish if price > MA50)
      2. Price vs MA200  (bullish if price > MA200)
      3. Golden cross    (bullish if MA50 > MA200)
      4. RSI             (bullish if 40 <= RSI <= 70; bearish if RSI < 30
                          or RSI > RSI_OVERBOUGHT_EXHAUSTION)
      5. 3m momentum     (bullish if > 0; bearish if < 0)

    Signal:
      BUY  if bullish_count >= BULLISH_THRESHOLD (4)
      SELL if bearish_count >= BEARISH_THRESHOLD (4)
      HOLD otherwise

    Strength (1-10):
      BUY/SELL: 5 + bullish/bearish_count * 1 (range 6-10)
      HOLD:     3 + abs(bullish - bearish)     (range 3-7)

    Returns:
        Tuple of (signal: str, signal_strength: int)
    """
    bullish = 0
    bearish = 0

    # Check 1: price vs MA50
    if ma50 is not None:
        if price > ma50:
            bullish += 1
        else:
            bearish += 1

    # Check 2: price vs MA200
    if ma200 is not None:
        if price > ma200:
            bullish += 1
        else:
            bearish += 1

    # Check 3: golden / death cross
    if ma50 is not None and ma200 is not None:
        if ma50 > ma200:
            bullish += 1
        else:
            bearish += 1

    # Check 4: RSI
    if rsi is not None:
        if RSI_OVERSOLD <= rsi <= RSI_OVERBOUGHT:
            bullish += 1
        elif rsi < RSI_OVERSOLD or rsi > RSI_OVERBOUGHT_EXHAUSTION:
            bearish += 1
        # rsi between 70-75 = neutral (neither point awarded)

    # Check 5: 3m momentum
    if momentum_3m is not None:
        if momentum_3m > 0:
            bullish += 1
        else:
            bearish += 1

    if bullish >= BULLISH_THRESHOLD:
        signal = "BUY"
        strength = min(10, 5 + bullish)
    elif bearish >= BEARISH_THRESHOLD:
        signal = "SELL"
        strength = min(10, 5 + bearish)
    else:
        signal = "HOLD"
        strength = max(1, min(7, 3 + abs(bullish - bearish)))

    return signal, strength


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_technical_prompt(
    company_name: str,
    ticker: str,
    price: float,
    ma50: float | None,
    ma200: float | None,
    rsi: float | None,
    golden_cross: bool | None,
    momentum_1m: float | None,
    momentum_3m: float | None,
    momentum_6m: float | None,
    momentum_1y: float | None,
    week_52_high: float | None,
    week_52_low: float | None,
    price_vs_52w_high_pct: float | None,
    volume_trend: str,
    support_levels: list[float],
    resistance_levels: list[float],
    signal: str,
    signal_strength: int,
) -> str:
    """
    Build the user-turn prompt for the LLM synthesis call.

    The LLM receives all pre-computed indicators in a readable format.
    It does NOT compute anything -- only synthesises the narrative summary.
    """

    def _fmt(val: Any, suffix: str = "") -> str:
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:,.2f}{suffix}"
        return f"{val}{suffix}"

    def _bool_label(val: bool | None, true_str: str, false_str: str) -> str:
        if val is None:
            return "N/A"
        return true_str if val else false_str

    cross_label = _bool_label(
        golden_cross, "Golden Cross (BULLISH)", "Death Cross (BEARISH)"
    )
    above_50 = "above" if ma50 is not None and price > ma50 else "below"
    if rsi is not None:
        if rsi < 30:
            rsi_label = "oversold"
        elif rsi > 70:
            rsi_label = "overbought"
        else:
            rsi_label = "neutral"
    else:
        rsi_label = "N/A"
    above_200 = "above" if ma200 is not None and price > ma200 else "below"

    support_str = (
        ", ".join(f"Rs.{int(s):,}" for s in support_levels)
        if support_levels
        else "None identified"
    )
    resistance_str = (
        ", ".join(f"Rs.{int(r):,}" for r in resistance_levels)
        if resistance_levels
        else "None identified"
    )

    return f"""Analyse the following technical indicators for {company_name} ({ticker}).

PRE-COMPUTED SIGNAL: {signal} (strength {signal_strength}/10)

PRICE LEVELS:
  Current price     : Rs.{_fmt(price)}
  52-week high      : Rs.{_fmt(week_52_high)}
  52-week low       : Rs.{_fmt(week_52_low)}
  vs 52w high       : {_fmt(price_vs_52w_high_pct, '%')}

MOVING AVERAGES:
  MA-50             : Rs.{_fmt(ma50)} -- price is {above_50} MA-50
  MA-200            : Rs.{_fmt(ma200)} -- price is {above_200} MA-200
  Cross status      : {cross_label}

MOMENTUM:
  RSI-14            : {_fmt(rsi)} ({rsi_label})
  1-month return    : {_fmt(momentum_1m, '%')}
  3-month return    : {_fmt(momentum_3m, '%')}
  6-month return    : {_fmt(momentum_6m, '%')}
  1-year return     : {_fmt(momentum_1y, '%')}

VOLUME:
  Volume trend      : {volume_trend}

KEY LEVELS:
  Support           : {support_str}
  Resistance        : {resistance_str}

Using only the data above, provide the JSON summary as specified in the \
system prompt. Reference specific price levels and indicator values."""


# ---------------------------------------------------------------------------
# Core agent logic (separated from LangGraph node for testability)
# ---------------------------------------------------------------------------


def _run_technical_analysis_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
) -> TechnicalAnalysis:
    """
    Core agent logic -- fetch OHLCV data, compute all indicators, call LLM.

    Never raises -- on any failure returns TechnicalAnalysis with error set.
    """
    # --- Step 1: Fetch 1-year OHLCV data
    logger.info(
        "Technical analyst: fetching price data ticker=%s analysis=%s",
        ticker,
        analysis_id,
    )
    try:
        price_data = fetch_stock_price.invoke({"ticker": ticker, "period": "1y"})
    except Exception as exc:
        logger.exception("fetch_stock_price failed for %s", ticker)
        return TechnicalAnalysis(
            agent_name="technical_analyst",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            signal="HOLD",
            signal_strength=1,
            error=f"fetch_stock_price failed: {exc}",
        )

    if "error" in price_data:
        return TechnicalAnalysis(
            agent_name="technical_analyst",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            signal="HOLD",
            signal_strength=1,
            error=price_data.get("message", "price data unavailable"),
        )

    # --- Step 2: Extract closes and OHLCV from tool output
    ohlcv: list[dict[str, Any]] = price_data.get("ohlcv", [])
    closes: list[float] = [float(c["close"]) for c in ohlcv if c.get("close")]
    stats: dict[str, Any] = price_data.get("stats", {})

    if not closes:
        return TechnicalAnalysis(
            agent_name="technical_analyst",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            signal="HOLD",
            signal_strength=1,
            error="No closing prices available in price data",
        )

    # --- Step 3: Compute all indicators (pure Python, deterministic)
    price = closes[-1]

    ma50 = compute_sma(closes, SMA_SHORT)
    ma200 = compute_sma(closes, SMA_LONG)
    rsi = compute_rsi(closes, RSI_PERIOD)

    momentum_1m = compute_momentum(closes, 21)  # ~1 month
    momentum_3m = compute_momentum(closes, 63)  # ~3 months
    momentum_6m = compute_momentum(closes, 126)  # ~6 months
    momentum_1y = compute_momentum(closes, 252)  # ~1 year

    golden_cross: bool | None = None
    if ma50 is not None and ma200 is not None:
        golden_cross = ma50 > ma200

    price_above_ma50: bool | None = (price > ma50) if ma50 is not None else None
    price_above_ma200: bool | None = (price > ma200) if ma200 is not None else None

    # Use tool-provided 52w stats (more accurate -- computed over 252 candles)
    week_52_high: float | None = stats.get("price_52w_high")
    week_52_low: float | None = stats.get("price_52w_low")

    price_vs_52w_high_pct: float | None = None
    if week_52_high and week_52_high > 0:
        price_vs_52w_high_pct = round((price / week_52_high) * 100, 2)

    avg_volume_30d: float | None = (
        float(stats["avg_volume_30d"]) if stats.get("avg_volume_30d") else None
    )
    volume_trend = _compute_volume_trend(ohlcv)

    support_levels, resistance_levels = _extract_key_levels(ohlcv)

    signal, signal_strength = _determine_signal(
        price=price,
        ma50=ma50,
        ma200=ma200,
        rsi=rsi,
        momentum_3m=momentum_3m,
    )

    # --- Step 4: LLM call for narrative summary
    logger.info("Technical analyst: invoking LLM ticker=%s", ticker)
    summary = ""

    try:
        import json
        import re

        llm = get_llm()
        prompt = _build_technical_prompt(
            company_name=company_name,
            ticker=ticker,
            price=price,
            ma50=ma50,
            ma200=ma200,
            rsi=rsi,
            golden_cross=golden_cross,
            momentum_1m=momentum_1m,
            momentum_3m=momentum_3m,
            momentum_6m=momentum_6m,
            momentum_1y=momentum_1y,
            week_52_high=week_52_high,
            week_52_low=week_52_low,
            price_vs_52w_high_pct=price_vs_52w_high_pct,
            volume_trend=volume_trend,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            signal=signal,
            signal_strength=signal_strength,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
        cleaned = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed = json.loads(cleaned)
        summary = parsed.get("summary", "")

    except Exception as exc:
        logger.warning("LLM call failed in technical analyst for %s: %s", ticker, exc)
        rsi_label = ""
        if rsi is not None:
            if rsi < RSI_OVERSOLD:
                rsi_label = "oversold"
            elif rsi > RSI_OVERBOUGHT:
                rsi_label = "overbought"
            else:
                rsi_label = "neutral"
        summary = (
            (
                f"{company_name} shows a {signal} signal "
                f"(strength {signal_strength}/10). "
                f"MA-50: Rs.{ma50:,.0f}, MA-200: Rs.{ma200:,.0f}. "
                f"RSI-14: {rsi} ({rsi_label}). "
                f"LLM synthesis unavailable -- review indicators directly."
            )
            if ma50 and ma200 and rsi
            else (
                f"{company_name} shows a {signal} signal "
                f"(strength {signal_strength}/10). "
                f"LLM synthesis unavailable -- review indicators directly."
            )
        )

    # --- Step 5: Build and return TechnicalAnalysis
    return TechnicalAnalysis(
        agent_name="technical_analyst",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        signal=signal,
        signal_strength=signal_strength,
        current_price=round(price, 2),
        week_52_high=week_52_high,
        week_52_low=week_52_low,
        price_vs_52w_high_pct=price_vs_52w_high_pct,
        ma_50d=ma50,
        ma_200d=ma200,
        price_above_ma50=price_above_ma50,
        price_above_ma200=price_above_ma200,
        golden_cross=golden_cross,
        rsi_14=rsi,
        momentum_1m_pct=momentum_1m,
        momentum_3m_pct=momentum_3m,
        momentum_6m_pct=momentum_6m,
        momentum_1y_pct=momentum_1y,
        avg_volume_30d=avg_volume_30d,
        volume_trend=volume_trend,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


def run_technical_analysis(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the Technical Analyst agent.

    Reads from InvestmentState:
      - job_id       -> analysis_id for the output model
      - company_name -> human-readable company name
      - ticker       -> Yahoo Finance ticker (e.g. 'TCS.NS')

    Writes to InvestmentState:
      - technical    -> dict representation of TechnicalAnalysis

    Never raises.  On failure ``technical["error"]`` is non-null.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_technical_analysis called with empty ticker")
        result = TechnicalAnalysis(
            agent_name="technical_analyst",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            signal="HOLD",
            signal_strength=1,
            error="ticker field is missing from InvestmentState",
        )
        return {"technical": result.model_dump()}

    try:
        result = _run_technical_analysis_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
        )
    except Exception as exc:
        logger.exception("Unhandled error in technical analyst node: ticker=%s", ticker)
        result = TechnicalAnalysis(
            agent_name="technical_analyst",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            signal="HOLD",
            signal_strength=1,
            error=f"Unhandled agent error: {exc}",
        )

    return {"technical": result.model_dump()}
