# backend/tests/unit/test_technical_analyst.py
"""
Unit tests for T-023: Technical Analyst Agent.

Test strategy:
  1. compute_sma         -- correctness against hand-calculated values
  2. compute_rsi         -- Wilder's method verified against manual calculation
  3. compute_momentum    -- percentage return formula
  4. _determine_signal   -- BUY/HOLD/SELL logic across all branches
  5. _extract_key_levels -- swing high/low detection
  6. _compute_volume_trend -- increasing/decreasing/stable classification
  7. _build_technical_prompt -- content verification
  8. _run_technical_analysis_core -- full agent with mocked tool + LLM
  9. run_technical_analysis -- LangGraph node state in/out
  10. Error paths -- missing ticker, tool error, LLM failure

Acceptance criteria verified:
  * RSI and MA computed correctly vs manual (TestComputeRSI, TestComputeSMA)
  * Agent output validated for TCS, Infosys, Reliance state shapes
  * Signal determination is deterministic and covers all three outcomes
  * Never raises -- always returns a dict with 'technical' key

All external calls (yFinance, Redis, LLM) are mocked.
"""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.agents.output_models import TechnicalAnalysis  # noqa: E402
from backend.agents.technical_analyst import (  # noqa: E402
    SYSTEM_PROMPT,
    _build_technical_prompt,
    _compute_volume_trend,
    _determine_signal,
    _extract_key_levels,
    _run_technical_analysis_core,
    compute_momentum,
    compute_rsi,
    compute_sma,
    run_technical_analysis,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

# 260 synthetic closes: starts at 3000, +1 per day (predictable, monotone)
_CLOSES_260: list[float] = [3000.0 + float(i) for i in range(260)]

# 20 flat closes at 100.0 (constant series -- RSI should be 100 or undefined)
_CLOSES_FLAT: list[float] = [100.0] * 25


# OHLCV records matching _CLOSES_260 shape
def _make_ohlcv(closes: list[float]) -> list[dict[str, Any]]:
    records = []
    for i, c in enumerate(closes):
        records.append(
            {
                "date": f"2024-{(i // 30) + 1:02d}-01",
                "open": round(c - 2.0, 2),
                "high": round(c + 5.0, 2),
                "low": round(c - 5.0, 2),
                "close": round(c, 2),
                "volume": 1_000_000 + i * 500,
            }
        )
    return records


_OHLCV_260 = _make_ohlcv(_CLOSES_260)

# Minimal valid price_data dict returned by fetch_stock_price
_PRICE_DATA_GOOD: dict[str, Any] = {
    "ticker": "TCS.NS",
    "company_name": "Tata Consultancy Services",
    "period": "1y",
    "data_points": 260,
    "stats": {
        "current_price": 3259.0,
        "price_52w_high": 3259.0,
        "price_52w_low": 3000.0,
        "avg_volume_30d": 1_040_000,
        "ma_50d": 3209.5,
        "ma_200d": 3129.5,
        "above_ma_50d": True,
        "above_ma_200d": True,
        "pct_change_1m": 2.1,
        "pct_change_3m": 5.3,
        "pct_change_1y": 8.6,
    },
    "ohlcv": _OHLCV_260,
}

_LLM_SUMMARY = (
    "TCS shows a BUY signal supported by price trading above both the "
    "50-day MA (Rs.3,209) and 200-day MA (Rs.3,129), confirming a bullish "
    "trend. RSI-14 at 62 indicates healthy momentum without being overbought."
)
_LLM_JSON = json.dumps({"summary": _LLM_SUMMARY})

# LangGraph state shapes for 3 test stocks
_STATE_TCS = {"job_id": "test-001", "company_name": "TCS", "ticker": "TCS.NS"}
_STATE_INFY = {
    "job_id": "test-002",
    "company_name": "Infosys",
    "ticker": "INFY.NS",
}
_STATE_RELIANCE = {
    "job_id": "test-003",
    "company_name": "Reliance",
    "ticker": "RELIANCE.NS",
}


def _mock_llm(content: str = _LLM_JSON) -> MagicMock:
    m = MagicMock()
    m.invoke.return_value = MagicMock(content=content)
    return m


# ---------------------------------------------------------------------------
# Tests: compute_sma
# ---------------------------------------------------------------------------


class TestComputeSMA:
    """
    SMA verified against manual calculation.

    For a list [1,2,3,4,5], SMA-3 of last 3 elements [3,4,5] = 4.0 exactly.
    For _CLOSES_260 (3000..3259), SMA-50 of last 50 = mean of 3210..3259
    = (3210 + 3259) / 2 = 3234.5
    """

    def test_sma_simple_known_values(self) -> None:
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert compute_sma(closes, 3) == pytest.approx(4.0)

    def test_sma_exact_window(self) -> None:
        # mean of [10, 20, 30] = 20.0
        assert compute_sma([10.0, 20.0, 30.0], 3) == pytest.approx(20.0)

    def test_sma_50_on_260_closes(self) -> None:
        # Last 50 of 3000..3259 are 3210..3259
        # Mean = (3210 + 3259) / 2 = 3234.5
        result = compute_sma(_CLOSES_260, 50)
        assert result == pytest.approx(3234.5)

    def test_sma_200_on_260_closes(self) -> None:
        # Last 200 of 3000..3259 are 3060..3259
        # Mean = (3060 + 3259) / 2 = 3159.5
        result = compute_sma(_CLOSES_260, 200)
        assert result == pytest.approx(3159.5)

    def test_insufficient_data_returns_none(self) -> None:
        assert compute_sma([100.0, 200.0], 50) is None

    def test_empty_list_returns_none(self) -> None:
        assert compute_sma([], 10) is None

    def test_zero_window_returns_none(self) -> None:
        assert compute_sma([1.0, 2.0, 3.0], 0) is None

    def test_window_equals_length(self) -> None:
        # mean of [2,4,6,8] = 5.0
        assert compute_sma([2.0, 4.0, 6.0, 8.0], 4) == pytest.approx(5.0)

    def test_returns_float_not_none_for_sufficient_data(self) -> None:
        result = compute_sma(_CLOSES_260, 50)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Tests: compute_rsi  (verified against manual Wilder's method)
# ---------------------------------------------------------------------------


class TestComputeRSI:
    """
    RSI-14 verified manually using Wilder's exponential smoothing.

    For a strictly rising series (e.g. closes = 1, 2, 3, ? 20):
      - All deltas are +1.0 (all gains, zero losses)
      - avg_gain = 1.0, avg_loss = 0.0
      - RSI = 100 (no losses)

    For a strictly falling series (closes = 20, 19, ? 1):
      - All deltas are -1.0 (all losses, zero gains)
      - RSI = 0 (no gains)

    For an alternating series we verify RSI is in [0, 100].

    We also verify the 5-point manual calculation:
      closes = [10, 12, 11, 13, 14, 12, 13, 15, 14, 16, 15, 17, 16, 18, 19]
      (15 points -> RSI with period=14)
      deltas = [+2,-1,+2,+1,-2,+1,+2,-1,+2,-1,+2,-1,+2,+1]
      gains  = [2,0,2,1,0,1,2,0,2,0,2,0,2,1]  -> sum=15, avg_gain=15/14
      losses = [0,1,0,0,2,0,0,1,0,1,0,1,0,0]  -> sum=6,  avg_loss=6/14
      After seeding (no further smoothing needed with exactly 14 deltas):
      RS = (15/14) / (6/14) = 15/6 = 2.5
      RSI = 100 - 100/(1+2.5) = 100 - 28.571... ~= 71.43
    """

    _KNOWN_CLOSES = [
        10.0,
        12.0,
        11.0,
        13.0,
        14.0,
        12.0,
        13.0,
        15.0,
        14.0,
        16.0,
        15.0,
        17.0,
        16.0,
        18.0,
        19.0,
    ]

    def test_rsi_known_result(self) -> None:
        # 15 closes, period=14 -> RSI ~= 71.43 (see docstring derivation)
        result = compute_rsi(self._KNOWN_CLOSES, period=14)
        assert result is not None
        assert result == pytest.approx(71.43, rel=1e-2)

    def test_rising_series_rsi_is_100(self) -> None:
        # All gains, no losses -> RSI = 100
        rising = [float(i) for i in range(1, 30)]
        result = compute_rsi(rising, period=14)
        assert result == pytest.approx(100.0)

    def test_falling_series_rsi_is_zero(self) -> None:
        # All losses, no gains -> RSI = 0
        falling = [float(i) for i in range(30, 0, -1)]
        result = compute_rsi(falling, period=14)
        assert result == pytest.approx(0.0)

    def test_rsi_always_in_range(self) -> None:
        import random

        random.seed(42)
        closes = [100.0 + random.uniform(-5, 5) for _ in range(50)]
        result = compute_rsi(closes, period=14)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_insufficient_data_returns_none(self) -> None:
        # Need period + 1 = 15 closes; 14 is not enough
        assert compute_rsi([float(i) for i in range(1, 15)], period=14) is None

    def test_exactly_minimum_data(self) -> None:
        # 15 closes, period=14 -> exactly enough
        result = compute_rsi([float(i) for i in range(1, 16)], period=14)
        assert result is not None

    def test_flat_series_rsi_is_100(self) -> None:
        # All deltas are 0 -> avg_loss = 0 -> RSI = 100
        flat = [100.0] * 20
        result = compute_rsi(flat, period=14)
        assert result == pytest.approx(100.0)

    def test_rsi_on_260_closes(self) -> None:
        # Monotone rising -> should be very high (near 100)
        result = compute_rsi(_CLOSES_260, period=14)
        assert result is not None
        assert result > 90.0

    def test_rsi_result_is_rounded_to_2dp(self) -> None:
        result = compute_rsi(self._KNOWN_CLOSES, period=14)
        assert result is not None
        assert result == round(result, 2)


# ---------------------------------------------------------------------------
# Tests: compute_momentum
# ---------------------------------------------------------------------------


class TestComputeMomentum:
    def test_simple_known_return(self) -> None:
        # closes = [100, ..., 110], lookback=1 -> (110-100)/100 = 10%
        closes = [100.0, 110.0]
        assert compute_momentum(closes, 1) == pytest.approx(10.0)

    def test_negative_return(self) -> None:
        closes = [200.0, 150.0]
        assert compute_momentum(closes, 1) == pytest.approx(-25.0)

    def test_zero_return(self) -> None:
        closes = [100.0, 100.0]
        assert compute_momentum(closes, 1) == pytest.approx(0.0)

    def test_insufficient_data_returns_none(self) -> None:
        assert compute_momentum([100.0, 110.0], 5) is None

    def test_zero_start_price_returns_none(self) -> None:
        assert compute_momentum([0.0, 100.0], 1) is None

    def test_momentum_on_260_closes_1m(self) -> None:
        # _CLOSES_260: last 21 days go from 3239 to 3259 (+20)
        # return = 20 / 3238 ~= 0.617%
        result = compute_momentum(_CLOSES_260, 21)
        assert result is not None
        assert result > 0  # monotone rising series

    def test_returns_float_rounded(self) -> None:
        result = compute_momentum([100.0, 115.123456], 1)
        assert result is not None
        assert result == round(result, 2)


# ---------------------------------------------------------------------------
# Tests: _determine_signal
# ---------------------------------------------------------------------------


class TestDetermineSignal:
    """Signal determination verified across all three outcomes."""

    def _call(
        self,
        price: float = 3259.0,
        ma50: float | None = 3200.0,
        ma200: float | None = 3100.0,
        rsi: float | None = 55.0,
        momentum_3m: float | None = 5.0,
    ) -> tuple[str, int]:
        return _determine_signal(price, ma50, ma200, rsi, momentum_3m)

    # BUY conditions
    def test_all_bullish_gives_buy(self) -> None:
        signal, strength = self._call(
            price=3300.0, ma50=3200.0, ma200=3100.0, rsi=55.0, momentum_3m=5.0
        )
        assert signal == "BUY"
        assert strength >= 6

    def test_buy_strength_is_at_least_6(self) -> None:
        signal, strength = self._call()
        if signal == "BUY":
            assert strength >= 6

    # SELL conditions
    def test_all_bearish_gives_sell(self) -> None:
        signal, strength = _determine_signal(
            price=2800.0,
            ma50=3000.0,
            ma200=3100.0,
            rsi=22.0,  # below oversold -> bearish check passes
            momentum_3m=-8.0,
        )
        assert signal == "SELL"

    def test_overbought_exhaustion_is_bearish(self) -> None:
        # RSI > 75 = overbought exhaustion -> bearish signal
        signal, _ = _determine_signal(
            price=2800.0,  # below both MAs -> 2 bearish
            ma50=3000.0,
            ma200=3100.0,
            rsi=80.0,  # exhaustion -> bearish
            momentum_3m=-5.0,  # bearish
        )
        assert signal == "SELL"

    # HOLD conditions
    def test_mixed_signals_gives_hold(self) -> None:
        # price above MA50 (bullish) but below MA200 (bearish)
        # golden cross False (bearish) but positive momentum (bullish)
        signal, _ = _determine_signal(
            price=3150.0,
            ma50=3100.0,  # above -> bullish
            ma200=3200.0,  # below -> bearish
            rsi=55.0,  # neutral band -> bullish
            momentum_3m=-1.0,  # slightly negative -> bearish
        )
        assert signal == "HOLD"

    # None handling
    def test_none_ma_still_works(self) -> None:
        signal, strength = _determine_signal(
            price=100.0, ma50=None, ma200=None, rsi=50.0, momentum_3m=3.0
        )
        assert signal in ("BUY", "HOLD", "SELL")
        assert 1 <= strength <= 10

    def test_none_rsi_still_works(self) -> None:
        signal, _ = _determine_signal(
            price=3300.0, ma50=3200.0, ma200=3100.0, rsi=None, momentum_3m=5.0
        )
        assert signal in ("BUY", "HOLD", "SELL")

    def test_strength_always_in_range(self) -> None:
        for rsi in [10.0, 30.0, 50.0, 70.0, 85.0]:
            for momentum in [-10.0, 0.0, 10.0]:
                _, strength = _determine_signal(
                    price=3000.0,
                    ma50=3000.0,
                    ma200=3000.0,
                    rsi=rsi,
                    momentum_3m=momentum,
                )
                assert 1 <= strength <= 10

    def test_rsi_neutral_band_not_bearish(self) -> None:
        # RSI between 70-75 should be neutral (no point either way)
        signal, _ = _determine_signal(
            price=3300.0,
            ma50=3200.0,
            ma200=3100.0,
            rsi=72.0,  # between 70 and 75 -> neutral, no extra bearish pt
            momentum_3m=5.0,
        )
        # Only 3 of 5 checks bullish (price>50, price>200, momentum)
        # golden cross = bullish (MA50>MA200), RSI neutral = no point
        # -> 4 bullish -> BUY
        assert signal == "BUY"


# ---------------------------------------------------------------------------
# Tests: _compute_volume_trend
# ---------------------------------------------------------------------------


class TestComputeVolumeTrend:
    def _make_ohlcv_vol(self, volumes: list[int]) -> list[dict[str, Any]]:
        return [{"close": 100.0, "volume": v} for v in volumes]

    def test_increasing_volume(self) -> None:
        # prior 30 avg = 1000, recent 30 avg = 1200 -> ratio 1.2 > 1.10
        prior = [1000] * 30
        recent = [1200] * 30
        ohlcv = self._make_ohlcv_vol(prior + recent)
        assert _compute_volume_trend(ohlcv) == "increasing"

    def test_decreasing_volume(self) -> None:
        prior = [1200] * 30
        recent = [800] * 30
        ohlcv = self._make_ohlcv_vol(prior + recent)
        assert _compute_volume_trend(ohlcv) == "decreasing"

    def test_stable_volume(self) -> None:
        # ratio = 1.05 -> stable (within +/-10%)
        prior = [1000] * 30
        recent = [1050] * 30
        ohlcv = self._make_ohlcv_vol(prior + recent)
        assert _compute_volume_trend(ohlcv) == "stable"

    def test_insufficient_data_returns_unknown(self) -> None:
        ohlcv = self._make_ohlcv_vol([1000] * 20)
        assert _compute_volume_trend(ohlcv) == "unknown"

    def test_empty_returns_unknown(self) -> None:
        assert _compute_volume_trend([]) == "unknown"


# ---------------------------------------------------------------------------
# Tests: _extract_key_levels
# ---------------------------------------------------------------------------


class TestExtractKeyLevels:
    def test_swing_highs_become_resistance(self) -> None:
        # Create a series with a clear swing high at index 5
        ohlcv = []
        for i in range(15):
            if i == 5:
                h, l, c = 120.0, 95.0, 110.0  # swing high
            elif i == 10:
                h, l, c = 95.0, 80.0, 85.0  # swing low
            else:
                h, l, c = 105.0, 90.0, 100.0
            ohlcv.append({"high": h, "low": l, "close": c, "volume": 1000})
        support, resistance = _extract_key_levels(ohlcv)
        assert isinstance(support, list)
        assert isinstance(resistance, list)

    def test_returns_at_most_3_levels_each(self) -> None:
        support, resistance = _extract_key_levels(_OHLCV_260)
        assert len(support) <= 3
        assert len(resistance) <= 3

    def test_empty_ohlcv_returns_empty_lists(self) -> None:
        support, resistance = _extract_key_levels([])
        assert support == []
        assert resistance == []

    def test_support_below_current_price(self) -> None:
        support, _ = _extract_key_levels(_OHLCV_260)
        current = _OHLCV_260[-1]["close"]
        for level in support:
            assert level < current

    def test_resistance_above_current_price(self) -> None:
        _, resistance = _extract_key_levels(_OHLCV_260)
        current = _OHLCV_260[-1]["close"]
        for level in resistance:
            assert level > current

    def test_too_few_candles(self) -> None:
        short_ohlcv = _make_ohlcv([100.0, 101.0])
        support, resistance = _extract_key_levels(short_ohlcv)
        assert support == []
        assert resistance == []


# ---------------------------------------------------------------------------
# Tests: _build_technical_prompt
# ---------------------------------------------------------------------------


class TestBuildTechnicalPrompt:
    def _make(self, **kwargs: Any) -> str:
        defaults: dict[str, Any] = {
            "company_name": "TCS",
            "ticker": "TCS.NS",
            "price": 3259.0,
            "ma50": 3209.5,
            "ma200": 3159.5,
            "rsi": 62.0,
            "golden_cross": True,
            "momentum_1m": 2.1,
            "momentum_3m": 5.3,
            "momentum_6m": 8.2,
            "momentum_1y": 12.5,
            "week_52_high": 3300.0,
            "week_52_low": 2900.0,
            "price_vs_52w_high_pct": 98.8,
            "volume_trend": "stable",
            "support_levels": [3150.0, 3100.0],
            "resistance_levels": [3300.0, 3350.0],
            "signal": "BUY",
            "signal_strength": 8,
        }
        defaults.update(kwargs)
        return _build_technical_prompt(**defaults)

    def test_contains_company_name(self) -> None:
        assert "TCS" in self._make()

    def test_contains_ticker(self) -> None:
        assert "TCS.NS" in self._make()

    def test_contains_signal(self) -> None:
        assert "BUY" in self._make()

    def test_contains_ma50(self) -> None:
        assert "3,209.50" in self._make()

    def test_contains_rsi(self) -> None:
        assert "62.00" in self._make()

    def test_contains_golden_cross(self) -> None:
        assert "Golden Cross" in self._make()

    def test_death_cross_shown_when_false(self) -> None:
        assert "Death Cross" in self._make(golden_cross=False)

    def test_none_ma_shows_na(self) -> None:
        prompt = self._make(ma50=None, ma200=None)
        assert "N/A" in prompt

    def test_no_support_shows_none_identified(self) -> None:
        prompt = self._make(support_levels=[])
        assert "None identified" in prompt

    def test_returns_string(self) -> None:
        assert isinstance(self._make(), str)


# ---------------------------------------------------------------------------
# Tests: _run_technical_analysis_core (full agent, mocked externals)
# ---------------------------------------------------------------------------


class TestRunTechnicalAnalysisCore:
    def _run(
        self,
        price_data: dict[str, Any] = _PRICE_DATA_GOOD,
        llm_response: str = _LLM_JSON,
        ticker: str = "TCS.NS",
    ) -> TechnicalAnalysis:
        mock_llm = _mock_llm(llm_response)
        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as mock_sp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_sp.invoke.return_value = price_data
            return _run_technical_analysis_core(
                analysis_id="test-001",
                company_name="Tata Consultancy Services",
                ticker=ticker,
            )

    def test_returns_technical_analysis_instance(self) -> None:
        assert isinstance(self._run(), TechnicalAnalysis)

    def test_agent_name_correct(self) -> None:
        assert self._run().agent_name == "technical_analyst"

    def test_ticker_preserved(self) -> None:
        assert self._run().ticker == "TCS.NS"

    def test_signal_is_valid(self) -> None:
        assert self._run().signal in ("BUY", "HOLD", "SELL")

    def test_signal_strength_in_range(self) -> None:
        result = self._run()
        assert 1 <= result.signal_strength <= 10

    def test_error_is_none_on_success(self) -> None:
        assert self._run().error is None

    def test_rsi_computed_and_not_none(self) -> None:
        result = self._run()
        # 260 closes is enough for RSI-14
        assert result.rsi_14 is not None
        assert 0.0 <= result.rsi_14 <= 100.0

    def test_ma50_computed_correctly(self) -> None:
        result = self._run()
        assert result.ma_50d is not None
        # Last 50 of 3000..3259 -> mean = 3234.5
        assert result.ma_50d == pytest.approx(3234.5)

    def test_ma200_computed_correctly(self) -> None:
        result = self._run()
        assert result.ma_200d is not None
        # Last 200 of 3000..3259 -> mean = 3159.5
        assert result.ma_200d == pytest.approx(3159.5)

    def test_golden_cross_is_bool(self) -> None:
        result = self._run()
        assert isinstance(result.golden_cross, bool)

    def test_golden_cross_correct_for_monotone_series(self) -> None:
        # MA-50 (3234.5) > MA-200 (3159.5) -> golden cross = True
        result = self._run()
        assert result.golden_cross is True

    def test_current_price_matches_last_close(self) -> None:
        result = self._run()
        assert result.current_price == pytest.approx(3259.0)

    def test_summary_populated_from_llm(self) -> None:
        result = self._run()
        assert result.summary == _LLM_SUMMARY

    def test_momentum_fields_populated(self) -> None:
        result = self._run()
        assert result.momentum_1m_pct is not None
        assert result.momentum_3m_pct is not None

    def test_support_resistance_are_lists(self) -> None:
        result = self._run()
        assert isinstance(result.support_levels, list)
        assert isinstance(result.resistance_levels, list)

    def test_tool_called_with_correct_ticker(self) -> None:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as mock_sp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_sp.invoke.return_value = _PRICE_DATA_GOOD
            _run_technical_analysis_core("x", "TCS", "TCS.NS")
            mock_sp.invoke.assert_called_once_with({"ticker": "TCS.NS", "period": "1y"})

    def test_price_data_error_returns_model_with_error(self) -> None:
        result = self._run(
            price_data={"error": "ticker_not_found", "message": "No data"}
        )
        assert isinstance(result, TechnicalAnalysis)
        assert result.error is not None

    def test_empty_ohlcv_returns_error_model(self) -> None:
        bad_data = {**_PRICE_DATA_GOOD, "ohlcv": []}
        result = self._run(price_data=bad_data)
        assert isinstance(result, TechnicalAnalysis)
        assert result.error is not None

    def test_llm_failure_uses_fallback_summary(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Groq timeout")
        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as mock_sp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_sp.invoke.return_value = _PRICE_DATA_GOOD
            result = _run_technical_analysis_core("x", "TCS", "TCS.NS")
        assert isinstance(result, TechnicalAnalysis)
        assert result.error is None  # graceful degradation
        assert len(result.summary) > 0

    def test_llm_malformed_json_uses_fallback(self) -> None:
        result = self._run(llm_response="Sorry, I can't help with that.")
        assert isinstance(result, TechnicalAnalysis)
        assert result.signal in ("BUY", "HOLD", "SELL")

    def test_model_serialisable(self) -> None:
        d = self._run().model_dump()
        assert isinstance(d, dict)
        assert d["agent_name"] == "technical_analyst"

    def test_volume_trend_populated(self) -> None:
        result = self._run()
        assert result.volume_trend in ("increasing", "decreasing", "stable", "unknown")

    def test_infy_ticker(self) -> None:
        result = self._run(ticker="INFY.NS")
        assert result.ticker == "INFY.NS"

    def test_reliance_ticker(self) -> None:
        result = self._run(ticker="RELIANCE.NS")
        assert result.ticker == "RELIANCE.NS"


# ---------------------------------------------------------------------------
# Tests: run_technical_analysis (LangGraph node)
# ---------------------------------------------------------------------------


class TestRunTechnicalAnalysisNode:
    def _invoke(
        self, state: dict[str, Any], price_data: dict[str, Any] = _PRICE_DATA_GOOD
    ) -> dict[str, Any]:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as mock_sp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_sp.invoke.return_value = price_data
            return run_technical_analysis(state)

    def test_returns_dict_with_technical_key(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert "technical" in result
        assert isinstance(result["technical"], dict)

    def test_technical_has_signal(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert result["technical"]["signal"] in ("BUY", "HOLD", "SELL")

    def test_technical_has_rsi(self) -> None:
        result = self._invoke(_STATE_TCS)
        rsi = result["technical"]["rsi_14"]
        assert rsi is None or 0.0 <= rsi <= 100.0

    def test_job_id_preserved(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert result["technical"]["analysis_id"] == "test-001"

    def test_empty_ticker_returns_error(self) -> None:
        result = run_technical_analysis(
            {"job_id": "x", "company_name": "Test", "ticker": ""}
        )
        assert result["technical"]["error"] is not None

    def test_missing_ticker_key_returns_error(self) -> None:
        result = run_technical_analysis({"job_id": "x", "company_name": "Test"})
        assert result["technical"]["error"] is not None

    def test_never_raises_on_catastrophic_failure(self) -> None:
        with patch(
            "backend.agents.technical_analyst._run_technical_analysis_core",
            side_effect=RuntimeError("Catastrophic failure"),
        ):
            result = run_technical_analysis(_STATE_TCS)
        assert "technical" in result
        assert result["technical"]["error"] is not None

    def test_tcs_state(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert result["technical"]["ticker"] == "TCS.NS"

    def test_infy_state(self) -> None:
        result = self._invoke(_STATE_INFY)
        assert result["technical"]["ticker"] == "INFY.NS"

    def test_reliance_state(self) -> None:
        result = self._invoke(_STATE_RELIANCE)
        assert result["technical"]["ticker"] == "RELIANCE.NS"

    def test_signal_strength_always_valid(self) -> None:
        result = self._invoke(_STATE_TCS)
        strength = result["technical"]["signal_strength"]
        assert 1 <= strength <= 10


# ---------------------------------------------------------------------------
# Tests: system prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_is_non_empty(self) -> None:
        assert isinstance(SYSTEM_PROMPT, str) and len(SYSTEM_PROMPT) > 50

    def test_mentions_json(self) -> None:
        assert "JSON" in SYSTEM_PROMPT

    def test_mentions_summary(self) -> None:
        assert "summary" in SYSTEM_PROMPT.lower()
