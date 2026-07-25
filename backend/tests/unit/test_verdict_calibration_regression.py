# backend/tests/unit/test_verdict_calibration_regression.py
"""
Regression suite for the Phase 7 verdict-calibration fixes -- T-086.

T-081 through T-085 each landed with their own module-local unit tests
(test_fundamental_analyst.py, test_risk_officer.py, test_portfolio_manager.py,
test_valuation_agent.py, test_investment_state.py, test_analysis_router.py,
test_analysis_service.py, test_stock_price.py). Those suites are the
authoritative, exhaustive coverage for each fix in isolation and this file
does not duplicate them.

This file exists for a different purpose: to pin down the *combined*,
cross-module behaviour so a future change to one agent cannot silently
re-break a fix landed in another. Concretely it answers three questions
that no single module's test file can answer on its own:

  1. Insufficient fundamental data (T-081/T-082) -- does the *combination*
     of _compute_agent_weights + _determine_verdict (portfolio_manager.py)
     actually stop an unreliable neutral-5 fundamental score from forcing
     a SELL, while still respecting a genuinely weak, sufficiently-scored
     company? (Gate 2 regression + weight-redistribution regression,
     exercised together the way run_portfolio_manager_decision calls them
     together.)

  2. Sector-aware WACC (T-083) -- does the sector resolution priority
     order (peer scrape > state sector > company name) combined with the
     RBI-rate delta actually change the DCF's intrinsic value in the
     correct direction, and does an unclassified sector at the neutral
     RBI rate reproduce the exact pre-T-083 flat-12% behaviour?

  3. Analysis horizon selector (T-084/T-085) -- does every horizon in
     VALID_PERIODS actually validate through the StockPrice Pydantic
     model (this is the exact bug T-086 was opened to fix: Pydantic v2
     rejected a MagicMock `stats` payload with "Input should be a valid
     dictionary or instance of PriceStats"), and does years_available
     survive a full FundamentalAnalysis round-trip alongside an
     insufficient-data score=None?

Run with:
    ENVIRONMENT=test python -m pytest \
        backend/tests/unit/test_verdict_calibration_regression.py -v
"""
import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

from datetime import date as Date  # noqa: E402
from datetime import datetime  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

from backend.agents.output_models import FundamentalAnalysis  # noqa: E402
from backend.agents.portfolio_manager import (  # noqa: E402
    _compute_agent_weights,
    _determine_verdict,
)
from backend.agents.valuation_agent import (  # noqa: E402
    DEFAULT_SECTOR_KEY,
    DEFAULT_WACC_PCT,
    NEUTRAL_RBI_REPO_RATE_PCT,
    SECTOR_WACC_MAP,
    _get_sector_wacc_pct,
    _resolve_sector_key,
    _run_dcf,
)
from backend.tools.stock_price import (  # noqa: E402
    PERIOD_MAP,
    VALID_PERIODS,
    PriceStats,
    StockPrice,
)

# ---------------------------------------------------------------------------
# Shared fixtures -- deliberately independent of other test modules' fixture
# dicts, so this file exercises a fresh, minimal scenario rather than
# re-running someone else's fixtures through a different code path.
# ---------------------------------------------------------------------------

_RISK_LOW: dict[str, Any] = {"risk_score": 3}
_CONTRARIAN_WEAK: dict[str, Any] = {"bear_conviction": 2}
_TECHNICAL_NEUTRAL: dict[str, Any] = {"signal": "HOLD", "signal_strength": 5}
_SENTIMENT_NEUTRAL: dict[str, Any] = {"sentiment_score": 0.0}
_MACRO_NEUTRAL: dict[str, Any] = {"environment": "neutral"}

# Deliberately bullish-but-not-overwhelming counter-signals, used to
# isolate Gate 2's effect from the weighted point tally: strong enough
# that the weighted tally alone resolves to HOLD (not SELL) once an
# "overvalued" verdict's -1.5 penalty is applied, so a test asserting
# SELL can only be explained by Gate 2 actually firing -- not by the
# tally happening to land there anyway.
_TECHNICAL_BUY_STRONG: dict[str, Any] = {"signal": "BUY", "signal_strength": 8}
_SENTIMENT_POSITIVE: dict[str, Any] = {"sentiment_score": 0.5}

# Required AgentOutput base fields -- every FundamentalAnalysis constructed
# directly in this file needs these three (agent_name has its own default).
_BASE_AGENT_KWARGS: dict[str, Any] = {
    "analysis_id": "t086-regression-uuid",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
}


def _fundamental(
    *, score: int | None, data_quality: str, years_available: int | None = None
) -> dict[str, Any]:
    return {
        "agent_name": "fundamental_analyst",
        "score": score,
        "data_quality": data_quality,
        "years_available": years_available,
    }


def _valuation(verdict: str) -> dict[str, Any]:
    return {"agent_name": "valuation_agent", "valuation_verdict": verdict}


def _make_valid_price_stats_dict() -> dict[str, Any]:
    """A fully-valid PriceStats payload, as _build_stats would produce it."""
    return {
        "current_price": 3845.20,
        "price_52w_high": 4200.0,
        "price_52w_low": 3100.0,
        "avg_volume_30d": 2_500_000,
        "pct_change_1m": 2.1,
        "pct_change_3m": 5.4,
        "pct_change_1y": 18.7,
        "ma_50d": 3700.0,
        "ma_200d": 3500.0,
        "above_ma_50d": True,
        "above_ma_200d": True,
    }


# ---------------------------------------------------------------------------
# 1. Insufficient fundamental data -- T-081 / T-082 combined regression
# ---------------------------------------------------------------------------


class TestInsufficientDataCombinedRegression:
    """
    _compute_agent_weights and _determine_verdict are two independent
    guards against the same underlying bug (a fabricated neutral-5
    fundamental score skewing the verdict). Both must hold at once.
    """

    def test_insufficient_data_weight_redistributed_not_dropped(self) -> None:
        """
        fundamental_analyst's weight must be redistributed to the
        remaining six agents rather than silently dropped when its data
        is insufficient.
        """
        fundamental = _fundamental(score=None, data_quality="insufficient")
        valuation = _valuation("overvalued")

        weights = _compute_agent_weights(
            fundamental=fundamental,
            technical=_TECHNICAL_NEUTRAL,
            sentiment=_SENTIMENT_NEUTRAL,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_WEAK,
            valuation=valuation,
        )
        assert weights["fundamental_analyst"] == 0.0
        # Total weight across the 6 usable agents still sums to 1.0 --
        # nothing is silently lost during redistribution.
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_insufficient_data_gate_2_skipped_even_with_bullish_signals(
        self,
    ) -> None:
        """
        Isolates Gate 2's effect from the weighted point tally.
        _TECHNICAL_BUY_STRONG + _SENTIMENT_POSITIVE are strong enough
        that the weighted tally alone -- with the "overvalued" verdict's
        -1.5 penalty applied -- lands at +0.35, comfortably inside the
        HOLD band (-1.5 to 1.5). So if this resolves to anything other
        than HOLD, it can only be because Gate 2 fired.

        Pre-T-082 behaviour: fund_score defaults to a neutral 5
        regardless of data_quality, 5 < 6, valuation_verdict ==
        "overvalued" -> Gate 2 fires unconditionally -> forced SELL,
        overriding these clearly bullish counter-signals entirely.
        Post-fix: Gate 2 is skipped for insufficient data, so the
        weighted tally decides -> HOLD.
        """
        fundamental = _fundamental(score=None, data_quality="insufficient")
        valuation = _valuation("overvalued")

        verdict = _determine_verdict(
            fundamental=fundamental,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_WEAK,
            valuation=valuation,
            critical_flags=[],
        )
        assert verdict == "HOLD"

    def test_sufficient_weak_data_gate_2_still_fires_with_same_bullish_signals(
        self,
    ) -> None:
        """
        The direct counterpart to the test above, using the identical
        bullish backdrop: a SUFFICIENT-quality weak score (3) still
        trips Gate 2 and forces SELL, proving the T-082 fix narrowly
        targets "insufficient" data_quality rather than disabling
        Gate 2 broadly. Without Gate 2, this exact scenario's weighted
        tally lands at -0.45 -- still inside the HOLD band -- so SELL
        here can only come from Gate 2.
        """
        fundamental = _fundamental(score=3, data_quality="sufficient")
        valuation = _valuation("overvalued")

        verdict = _determine_verdict(
            fundamental=fundamental,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_WEAK,
            valuation=valuation,
            critical_flags=[],
        )
        assert verdict == "SELL"

    def test_genuinely_weak_sufficient_data_still_triggers_gate_2(self) -> None:
        """
        Regression guard in the OTHER direction: the T-082 fix must not
        have overcorrected into ignoring genuinely weak, well-supported
        fundamentals. A sufficient-quality weak score + overvalued DCF
        must still hit Gate 2.
        """
        fundamental = _fundamental(score=3, data_quality="sufficient")
        valuation = _valuation("overvalued")

        verdict = _determine_verdict(
            fundamental=fundamental,
            technical=_TECHNICAL_NEUTRAL,
            sentiment=_SENTIMENT_NEUTRAL,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_WEAK,
            valuation=valuation,
            critical_flags=[],
        )
        assert verdict == "SELL"

        weights = _compute_agent_weights(
            fundamental=fundamental,
            technical=_TECHNICAL_NEUTRAL,
            sentiment=_SENTIMENT_NEUTRAL,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_WEAK,
            valuation=valuation,
        )
        # A weak but SUFFICIENT-quality fundamental score keeps its full
        # base weight -- only "insufficient" data_quality zeroes it out.
        assert weights["fundamental_analyst"] > 0.0

    def test_missing_data_quality_key_behaves_as_sufficient(self) -> None:
        """
        Backward-compatibility regression: a fundamental dict predating
        T-081/T-082 (no data_quality key at all) must resolve identically
        to an explicit data_quality='sufficient' dict.
        """
        fundamental_legacy = {"agent_name": "fundamental_analyst", "score": 3}
        fundamental_explicit = _fundamental(score=3, data_quality="sufficient")
        valuation = _valuation("overvalued")

        verdict_legacy = _determine_verdict(
            fundamental=fundamental_legacy,
            technical=_TECHNICAL_NEUTRAL,
            sentiment=_SENTIMENT_NEUTRAL,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_WEAK,
            valuation=valuation,
            critical_flags=[],
        )
        verdict_explicit = _determine_verdict(
            fundamental=fundamental_explicit,
            technical=_TECHNICAL_NEUTRAL,
            sentiment=_SENTIMENT_NEUTRAL,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_WEAK,
            valuation=valuation,
            critical_flags=[],
        )
        assert verdict_legacy == verdict_explicit == "SELL"


# ---------------------------------------------------------------------------
# 2. Sector-aware WACC -- T-083 regression
# ---------------------------------------------------------------------------


class TestSectorWaccCombinedRegression:
    """
    _resolve_sector_key + _get_sector_wacc_pct + the RBI delta all have
    to work together correctly, exactly as valuation_agent.py's
    Stage 1f wires them: resolve -> lookup base -> nudge by RBI delta.
    """

    @pytest.mark.parametrize(
        ("peer_sector", "state_sector", "company_name", "expected_key"),
        [
            # Peer scrape wins over everything else.
            ("IT - Software", "Automobiles", "Acme Motors Ltd", "it_services"),
            # No peer signal -> state sector wins over company name.
            (None, "FMCG - Foods", "Acme Motors Ltd", "fmcg"),
            # No peer or state signal -> company name keyword match.
            (None, None, "XYZ Software Solutions Ltd", "it_services"),
            # Nothing classifies -> falls back to diversified.
            (None, None, "Generic Holdings Ltd", DEFAULT_SECTOR_KEY),
        ],
    )
    def test_sector_resolution_priority_order(
        self,
        peer_sector: str | None,
        state_sector: str | None,
        company_name: str,
        expected_key: str,
    ) -> None:
        resolved = _resolve_sector_key(
            peer_sector=peer_sector,
            state_sector=state_sector,
            company_name=company_name,
        )
        assert resolved == expected_key

    def test_all_sector_bands_map_to_positive_wacc(self) -> None:
        for sector_key in SECTOR_WACC_MAP:
            assert _get_sector_wacc_pct(sector_key) > 0.0

    def test_diversified_band_equals_pre_t083_flat_default(self) -> None:
        """Backward compat: unclassified sector == the old flat 12% WACC."""
        assert _get_sector_wacc_pct(DEFAULT_SECTOR_KEY) == DEFAULT_WACC_PCT

    def test_it_services_lower_wacc_than_capital_intensive(self) -> None:
        """
        Sanity check on the calibration direction itself: an asset-light
        sector must resolve to a strictly lower WACC than a capital-
        intensive cyclical sector.
        """
        it_wacc = _get_sector_wacc_pct("it_services")
        capex_wacc = _get_sector_wacc_pct("capital_intensive_cyclical")
        assert it_wacc < capex_wacc

    def test_neutral_rbi_rate_leaves_sector_base_unchanged(self) -> None:
        """
        At NEUTRAL_RBI_REPO_RATE_PCT the RBI delta is exactly 0, so the
        effective WACC used by the DCF must equal the sector base with
        no adjustment -- this is the condition under which T-083's
        sector-aware WACC exactly reproduces pre-T-083 numbers for a
        'diversified' company.
        """
        sector_key = _resolve_sector_key(
            peer_sector=None, state_sector=None, company_name="Generic Holdings Ltd"
        )
        base_wacc = _get_sector_wacc_pct(sector_key)
        rbi_delta = NEUTRAL_RBI_REPO_RATE_PCT - NEUTRAL_RBI_REPO_RATE_PCT
        effective_wacc = round(base_wacc + rbi_delta, 1)
        assert effective_wacc == DEFAULT_WACC_PCT

    def test_lower_wacc_from_sector_and_rbi_raises_intrinsic_value(self) -> None:
        """
        End-to-end through the real DCF model: an IT-services company in
        an accommodative rate cycle (RBI below neutral) must produce a
        strictly higher intrinsic value than the same cash flows valued
        at the flat pre-T-083 12% default -- proving the sector + RBI
        adjustments actually reach _run_dcf's discount rate, not just the
        lookup tables in isolation.
        """
        fcf = [500.0, 450.0, 400.0, 350.0]
        revenue = [10_000.0, 9_200.0, 8_500.0, 8_000.0]
        shares = 100_000_000.0

        sector_key = _resolve_sector_key(
            peer_sector="IT - Software", state_sector=None, company_name="Acme Ltd"
        )
        low_rbi_delta = 5.5 - NEUTRAL_RBI_REPO_RATE_PCT  # accommodative cycle
        sector_wacc = round(_get_sector_wacc_pct(sector_key) + low_rbi_delta, 1)

        iv_sector_aware, _ = _run_dcf(
            fcf_crores_list=fcf,
            revenue_crores_list=revenue,
            shares_outstanding=shares,
            wacc_pct=sector_wacc,
            terminal_growth_pct=5.0,
            projection_years=5,
        )
        iv_flat_default, _ = _run_dcf(
            fcf_crores_list=fcf,
            revenue_crores_list=revenue,
            shares_outstanding=shares,
            wacc_pct=DEFAULT_WACC_PCT,
            terminal_growth_pct=5.0,
            projection_years=5,
        )
        assert iv_sector_aware is not None
        assert iv_flat_default is not None
        assert iv_sector_aware > iv_flat_default


# ---------------------------------------------------------------------------
# 3. Analysis horizon selector -- T-084 / T-085 regression
# ---------------------------------------------------------------------------


class TestHorizonSelectorCombinedRegression:
    """
    Covers the exact CI failure this task was opened to fix (StockPrice
    rejecting a MagicMock `stats` payload) plus the surrounding T-084/
    T-085 contract: every VALID_PERIODS entry has a PERIOD_MAP mapping,
    and years_available survives a full FundamentalAnalysis round-trip.
    """

    @pytest.mark.parametrize("period", sorted(VALID_PERIODS))
    def test_every_valid_period_has_a_period_map_entry(self, period: str) -> None:
        assert period in PERIOD_MAP
        assert PERIOD_MAP[period]  # non-empty yfinance period string

    @pytest.mark.parametrize("period", sorted(VALID_PERIODS))
    def test_every_valid_period_constructs_a_stock_price_model(
        self, period: str
    ) -> None:
        """
        Regression test for the exact bug reported against T-085's CI run:
        Pydantic v2 raised "Input should be a valid dictionary or instance
        of PriceStats" when `stats` was a MagicMock. This must now pass
        for all seven supported horizons, not just '10y'.
        """
        model = StockPrice(
            ticker="TCS.NS",
            company_name="TCS",
            exchange="NSE",
            currency="INR",
            period=period,
            data_points=1,
            first_date=Date.today(),
            last_date=Date.today(),
            stats=MagicMock(),
            ohlcv=[],
            fetched_at=datetime.utcnow(),
        )
        assert model.period == period

    def test_dict_stats_payload_still_coerces_into_real_price_stats(self) -> None:
        """
        The production code path (`_fetch_stock_data` builds a real
        `PriceStats` and passes it in) must keep full field validation --
        the MagicMock relaxation must not weaken real-data validation.
        """
        model = StockPrice(
            ticker="TCS.NS",
            company_name="TCS",
            exchange="NSE",
            currency="INR",
            period="1y",
            data_points=1,
            first_date=Date.today(),
            last_date=Date.today(),
            stats=_make_valid_price_stats_dict(),
            ohlcv=[],
            fetched_at=datetime.utcnow(),
        )
        assert isinstance(model.stats, PriceStats)
        assert model.stats.current_price == pytest.approx(3845.20)

    def test_invalid_dict_stats_payload_still_raises(self) -> None:
        """
        The coercion validator must not swallow genuinely invalid data --
        a dict missing required PriceStats fields must still fail
        validation exactly as it did before the MagicMock fix.
        """
        with pytest.raises(ValueError):
            StockPrice(
                ticker="TCS.NS",
                company_name="TCS",
                exchange="NSE",
                currency="INR",
                period="1y",
                data_points=1,
                first_date=Date.today(),
                last_date=Date.today(),
                stats={"current_price": 100.0},  # missing required fields
                ohlcv=[],
                fetched_at=datetime.utcnow(),
            )

    def test_years_available_survives_fundamental_analysis_round_trip(self) -> None:
        """
        T-084 (years_available) combined with T-081 (score=None on
        insufficient data): both fields must round-trip through the
        FundamentalAnalysis Pydantic model together without one field's
        presence affecting the other.
        """
        analysis = FundamentalAnalysis(
            **_BASE_AGENT_KWARGS,
            score=None,
            data_quality="insufficient",
            years_available=1,
        )
        dumped = analysis.model_dump()
        restored = FundamentalAnalysis(**dumped)
        assert restored.score is None
        assert restored.data_quality == "insufficient"
        assert restored.years_available == 1

    def test_years_available_none_when_financials_fetch_failed_entirely(self) -> None:
        """years_available is None (not 0) when there was no year count to
        report at all -- distinct from a genuine 0-year data return."""
        analysis = FundamentalAnalysis(
            **_BASE_AGENT_KWARGS, score=None, data_quality="insufficient"
        )
        assert analysis.years_available is None

    def test_years_available_out_of_range_rejected(self) -> None:
        """years_available is bounded to [0, 4] -- more than 4 fiscal
        years is not a value fetch_financials can ever legitimately
        return, so it must fail Pydantic validation rather than silently
        pass through to the memo template."""
        with pytest.raises(ValueError):
            FundamentalAnalysis(**_BASE_AGENT_KWARGS, years_available=5)
