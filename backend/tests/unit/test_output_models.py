# backend/tests/unit/test_output_models.py
"""
Unit tests for T-021: Agent Output Pydantic Models.

Test strategy:
  1. Instantiation   — every model can be created with minimal required fields
  2. Defaults        — optional fields default correctly (None, [], 0, "")
  3. Validation      — out-of-range values raise ValidationError as expected
  4. Serialisation   — model_dump() and model_dump_json() round-trip correctly
  5. Schema          — model_json_schema() returns a non-empty dict (auto-docs)
  6. Immutability    — frozen=True prevents attribute mutation
  7. Base class      — AgentOutput fields propagate to all subclasses
  8. Error flag      — error field is None by default, settable to a string
  9. All agents      — every one of the 8 concrete models has dedicated tests
 10. agent_name      — default value is correct for each concrete model

All tests are pure unit tests: no I/O, no database, no LLM calls.
The only dependency is Pydantic v2.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from pydantic import BaseModel
import pytest

from backend.agents.output_models import (
    AgentOutput,
    ContrarianReport,
    FundamentalAnalysis,
    InvestmentDecision,
    MacroAnalysis,
    RiskAnalysis,
    SentimentAnalysis,
    TechnicalAnalysis,
    ValuationOutput,
)

# ── Shared helpers ────────────────────────────────────────────────────────────

BASE_KWARGS: dict[str, Any] = {
    "analysis_id": "test-analysis-uuid-001",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
}


def _make_fundamental(**extra: Any) -> FundamentalAnalysis:
    defaults: dict[str, Any] = {"score": 8}
    return FundamentalAnalysis(**BASE_KWARGS, **{**defaults, **extra})


def _make_technical(**extra: Any) -> TechnicalAnalysis:
    defaults: dict[str, Any] = {"signal": "BUY", "signal_strength": 7}
    return TechnicalAnalysis(**BASE_KWARGS, **{**defaults, **extra})


def _make_sentiment(**extra: Any) -> SentimentAnalysis:
    defaults: dict[str, Any] = {
        "sentiment_score": 0.45,
        "sentiment_label": "positive",
        "articles_analysed": 30,
        "positive_articles": 18,
        "negative_articles": 4,
        "neutral_articles": 8,
    }
    return SentimentAnalysis(**BASE_KWARGS, **{**defaults, **extra})


def _make_macro(**extra: Any) -> MacroAnalysis:
    defaults: dict[str, Any] = {
        "macro_environment": "favourable",
        "sector_impact": "tailwind",
    }
    return MacroAnalysis(**BASE_KWARGS, **{**defaults, **extra})


def _make_risk(**extra: Any) -> RiskAnalysis:
    defaults: dict[str, Any] = {
        "risk_score": 3,
        "governance_risk": 2,
        "regulatory_risk": 3,
        "financial_risk": 3,
        "concentration_risk": 4,
    }
    return RiskAnalysis(**BASE_KWARGS, **{**defaults, **extra})


def _make_contrarian(**extra: Any) -> ContrarianReport:
    defaults: dict[str, Any] = {"bear_conviction": 6}
    return ContrarianReport(**BASE_KWARGS, **{**defaults, **extra})


def _make_valuation(**extra: Any) -> ValuationOutput:
    defaults: dict[str, Any] = {"valuation_verdict": "undervalued"}
    return ValuationOutput(**BASE_KWARGS, **{**defaults, **extra})


def _make_decision(**extra: Any) -> InvestmentDecision:
    defaults: dict[str, Any] = {"verdict": "BUY", "conviction_score": 8}
    return InvestmentDecision(**BASE_KWARGS, **{**defaults, **extra})


# ── Test class: AgentOutput base ──────────────────────────────────────────────


class TestAgentOutput:
    """Tests for the shared AgentOutput base class."""

    def test_base_fields_present_on_subclass(self) -> None:
        """All base fields from AgentOutput are accessible on subclasses."""
        m = _make_fundamental()
        assert m.analysis_id == "test-analysis-uuid-001"
        assert m.company_name == "Tata Consultancy Services"
        assert m.ticker == "TCS.NS"
        assert m.error is None
        assert isinstance(m.generated_at, datetime)

    def test_error_field_defaults_to_none(self) -> None:
        m = _make_fundamental()
        assert m.error is None

    def test_error_field_accepts_string(self) -> None:
        m = _make_fundamental(error="yFinance timeout after 3 retries")
        assert m.error == "yFinance timeout after 3 retries"

    def test_generated_at_is_datetime(self) -> None:
        m = _make_fundamental()
        assert isinstance(m.generated_at, datetime)

    def test_custom_generated_at(self) -> None:
        ts = datetime(2024, 6, 15, 10, 30, 0)
        m = _make_fundamental(generated_at=ts)
        assert m.generated_at == ts

    def test_frozen_prevents_mutation(self) -> None:
        """frozen=True means all output models are immutable once created."""
        from pydantic import ValidationError

        m = _make_fundamental()
        with pytest.raises((ValidationError, TypeError)):
            m.score = 9  # type: ignore[misc]

    def test_all_models_importable(self) -> None:
        """Smoke test — all 8 + 1 models are importable from output_models."""
        from backend.agents.output_models import (
            AgentOutput,
            ContrarianReport,
            FundamentalAnalysis,
            InvestmentDecision,
            MacroAnalysis,
            RiskAnalysis,
            SentimentAnalysis,
            TechnicalAnalysis,
            ValuationOutput,
        )

        classes = [
            AgentOutput,
            FundamentalAnalysis,
            TechnicalAnalysis,
            SentimentAnalysis,
            MacroAnalysis,
            RiskAnalysis,
            ContrarianReport,
            ValuationOutput,
            InvestmentDecision,
        ]
        for cls in classes:
            assert issubclass(cls, AgentOutput)


# ── Test class: FundamentalAnalysis ───────────────────────────────────────────


class TestFundamentalAnalysis:
    def test_minimal_instantiation(self) -> None:
        m = _make_fundamental()
        assert m.score == 8
        assert m.agent_name == "fundamental_analyst"

    def test_default_agent_name(self) -> None:
        m = _make_fundamental()
        assert m.agent_name == "fundamental_analyst"

    def test_optional_fields_default_none(self) -> None:
        m = _make_fundamental()
        assert m.revenue_growth_pct is None
        assert m.gross_margin_pct is None
        assert m.free_cash_flow_cr is None
        assert m.debt_to_equity is None
        assert m.roe_pct is None

    def test_list_fields_default_empty(self) -> None:
        m = _make_fundamental()
        assert m.strengths == []
        assert m.weaknesses == []

    def test_full_instantiation(self) -> None:
        m = _make_fundamental(
            revenue_growth_pct=12.5,
            revenue_cagr_3y_pct=10.2,
            gross_margin_pct=45.0,
            operating_margin_pct=28.0,
            net_margin_pct=20.0,
            free_cash_flow_cr=15000.0,
            fcf_yield_pct=4.2,
            debt_to_equity=0.05,
            current_ratio=2.1,
            interest_coverage=45.0,
            roe_pct=46.0,
            roce_pct=51.0,
            strengths=["Market leader in IT services", "Strong FCF generation"],
            weaknesses=["Geographic concentration in US market"],
            summary="TCS demonstrates exceptional fundamental quality...",
        )
        assert m.revenue_growth_pct == 12.5
        assert m.roe_pct == 46.0
        assert len(m.strengths) == 2

    def test_score_lower_bound(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_fundamental(score=0)

    def test_score_upper_bound(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_fundamental(score=11)

    def test_score_boundary_values(self) -> None:
        assert _make_fundamental(score=1).score == 1
        assert _make_fundamental(score=10).score == 10

    def test_model_dump(self) -> None:
        m = _make_fundamental(revenue_growth_pct=12.5)
        d = m.model_dump()
        assert isinstance(d, dict)
        assert d["score"] == 8
        assert d["revenue_growth_pct"] == 12.5
        assert d["agent_name"] == "fundamental_analyst"

    def test_json_round_trip(self) -> None:
        m = _make_fundamental(strengths=["Leader"])
        json_str = m.model_dump_json()
        d = json.loads(json_str)
        assert d["score"] == 8
        assert d["strengths"] == ["Leader"]

    def test_json_schema_generated(self) -> None:
        schema = FundamentalAnalysis.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "score" in schema["properties"]


# ── Test class: TechnicalAnalysis ─────────────────────────────────────────────


class TestTechnicalAnalysis:
    def test_minimal_instantiation(self) -> None:
        m = _make_technical()
        assert m.signal == "BUY"
        assert m.signal_strength == 7
        assert m.agent_name == "technical_analyst"

    def test_optional_fields_default_none(self) -> None:
        m = _make_technical()
        assert m.current_price is None
        assert m.rsi_14 is None
        assert m.ma_50d is None
        assert m.golden_cross is None

    def test_boolean_fields(self) -> None:
        m = _make_technical(price_above_ma50=True, golden_cross=False)
        assert m.price_above_ma50 is True
        assert m.golden_cross is False

    def test_signal_strength_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_technical(signal_strength=0)
        with pytest.raises(ValidationError):
            _make_technical(signal_strength=11)

    def test_list_fields_default_empty(self) -> None:
        m = _make_technical()
        assert m.support_levels == []
        assert m.resistance_levels == []

    def test_full_instantiation(self) -> None:
        m = _make_technical(
            current_price=3850.0,
            week_52_high=4100.0,
            week_52_low=3100.0,
            price_vs_52w_high_pct=93.9,
            ma_50d=3700.0,
            ma_200d=3500.0,
            price_above_ma50=True,
            price_above_ma200=True,
            golden_cross=True,
            rsi_14=62.0,
            momentum_1m_pct=3.2,
            momentum_3m_pct=8.5,
            momentum_6m_pct=15.0,
            momentum_1y_pct=22.0,
            avg_volume_30d=3500000.0,
            volume_trend="increasing",
            support_levels=[3700.0, 3500.0],
            resistance_levels=[4000.0, 4100.0],
            summary="TCS shows strong bullish momentum...",
        )
        assert m.current_price == 3850.0
        assert m.golden_cross is True
        assert m.support_levels == [3700.0, 3500.0]

    def test_model_dump_round_trip(self) -> None:
        m = _make_technical(rsi_14=55.0)
        d = m.model_dump()
        assert d["signal"] == "BUY"
        assert d["rsi_14"] == 55.0

    def test_json_schema_generated(self) -> None:
        schema = TechnicalAnalysis.model_json_schema()
        assert "signal" in schema["properties"]


# ── Test class: SentimentAnalysis ─────────────────────────────────────────────


class TestSentimentAnalysis:
    def test_minimal_instantiation(self) -> None:
        m = _make_sentiment()
        assert m.sentiment_score == 0.45
        assert m.agent_name == "news_sentiment"

    def test_sentiment_score_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_sentiment(sentiment_score=-1.1)
        with pytest.raises(ValidationError):
            _make_sentiment(sentiment_score=1.1)

    def test_sentiment_score_boundary_values(self) -> None:
        assert _make_sentiment(sentiment_score=-1.0).sentiment_score == -1.0
        assert _make_sentiment(sentiment_score=1.0).sentiment_score == 1.0
        assert _make_sentiment(sentiment_score=0.0).sentiment_score == 0.0

    def test_article_counts_non_negative(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_sentiment(articles_analysed=-1)

    def test_red_flags_default_empty(self) -> None:
        m = _make_sentiment()
        assert m.red_flags == []
        assert m.red_flag_count == 0

    def test_top_headlines(self) -> None:
        m = _make_sentiment(
            top_positive_headlines=["TCS wins $500M deal from Citigroup"],
            top_negative_headlines=["Attrition rises to 18% in Q3"],
        )
        assert len(m.top_positive_headlines) == 1
        assert len(m.top_negative_headlines) == 1

    def test_model_dump(self) -> None:
        m = _make_sentiment(red_flags=["SEBI investigation initiated"])
        d = m.model_dump()
        assert d["sentiment_score"] == 0.45
        assert d["red_flags"] == ["SEBI investigation initiated"]

    def test_json_schema_generated(self) -> None:
        schema = SentimentAnalysis.model_json_schema()
        assert "sentiment_score" in schema["properties"]


# ── Test class: MacroAnalysis ─────────────────────────────────────────────────


class TestMacroAnalysis:
    def test_minimal_instantiation(self) -> None:
        m = _make_macro()
        assert m.macro_environment == "favourable"
        assert m.sector_impact == "tailwind"
        assert m.agent_name == "macro_economist"

    def test_optional_numeric_fields(self) -> None:
        m = _make_macro()
        assert m.rbi_repo_rate_pct is None
        assert m.cpi_inflation_pct is None
        assert m.gdp_growth_pct is None
        assert m.usd_inr_rate is None

    def test_tailwinds_headwinds_default_empty(self) -> None:
        m = _make_macro()
        assert m.tailwinds == []
        assert m.headwinds == []

    def test_full_instantiation(self) -> None:
        m = _make_macro(
            rbi_repo_rate_pct=6.5,
            rate_stance="neutral",
            rate_direction="holding",
            cpi_inflation_pct=4.8,
            wpi_inflation_pct=1.1,
            inflation_trend="falling",
            gdp_growth_pct=7.0,
            gdp_forecast_pct=6.8,
            tailwinds=["INR depreciation benefits IT exporters"],
            headwinds=["US tech sector slowdown"],
            usd_inr_rate=83.50,
            inr_trend="stable",
            summary="India's macro environment is broadly supportive...",
        )
        assert m.rbi_repo_rate_pct == 6.5
        assert m.tailwinds == ["INR depreciation benefits IT exporters"]
        assert m.usd_inr_rate == 83.50

    def test_json_round_trip(self) -> None:
        m = _make_macro(rbi_repo_rate_pct=6.5)
        data = json.loads(m.model_dump_json())
        assert data["macro_environment"] == "favourable"
        assert data["rbi_repo_rate_pct"] == 6.5

    def test_json_schema_generated(self) -> None:
        schema = MacroAnalysis.model_json_schema()
        assert "macro_environment" in schema["properties"]


# ── Test class: RiskAnalysis ──────────────────────────────────────────────────


class TestRiskAnalysis:
    def test_minimal_instantiation(self) -> None:
        m = _make_risk()
        assert m.risk_score == 3
        assert m.agent_name == "risk_officer"

    def test_score_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_risk(risk_score=0)
        with pytest.raises(ValidationError):
            _make_risk(governance_risk=11)

    def test_all_subscores_range(self) -> None:
        for score in [1, 5, 10]:
            m = _make_risk(
                risk_score=score,
                governance_risk=score,
                regulatory_risk=score,
                financial_risk=score,
                concentration_risk=score,
            )
            assert m.risk_score == score

    def test_risk_flags_default_empty(self) -> None:
        m = _make_risk()
        assert m.risk_flags == []
        assert m.critical_flags == []

    def test_risk_flags_populated(self) -> None:
        m = _make_risk(
            risk_flags=["High promoter pledge: 45%"],
            critical_flags=["High promoter pledge: 45%"],
        )
        assert len(m.risk_flags) == 1
        assert m.critical_flags[0].startswith("High promoter")

    def test_model_dump(self) -> None:
        m = _make_risk()
        d = m.model_dump()
        assert d["risk_score"] == 3
        assert d["agent_name"] == "risk_officer"

    def test_json_schema_generated(self) -> None:
        schema = RiskAnalysis.model_json_schema()
        assert "risk_score" in schema["properties"]


# ── Test class: ContrarianReport ──────────────────────────────────────────────


class TestContrarianReport:
    def test_minimal_instantiation(self) -> None:
        m = _make_contrarian()
        assert m.bear_conviction == 6
        assert m.agent_name == "contrarian_investor"

    def test_bear_conviction_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_contrarian(bear_conviction=0)
        with pytest.raises(ValidationError):
            _make_contrarian(bear_conviction=11)

    def test_lists_default_empty(self) -> None:
        m = _make_contrarian()
        assert m.counter_arguments == []
        assert m.overlooked_risks == []
        assert m.challenged_agents == []

    def test_full_instantiation(self) -> None:
        m = _make_contrarian(
            counter_arguments=[
                "FCF conversion has declined for 3 consecutive years",
                "US visa restrictions could hurt headcount growth",
            ],
            challenged_agents=["fundamental_analyst"],
            overlooked_risks=["Management succession risk not priced in"],
            bear_conviction=8,
            strongest_argument="FCF decline is structural, not cyclical",
            summary="The consensus understates execution risks...",
        )
        assert len(m.counter_arguments) == 2
        assert m.bear_conviction == 8
        assert m.challenged_agents == ["fundamental_analyst"]

    def test_json_round_trip(self) -> None:
        m = _make_contrarian(counter_arguments=["Valuation is stretched"])
        data = json.loads(m.model_dump_json())
        assert data["bear_conviction"] == 6
        assert data["counter_arguments"] == ["Valuation is stretched"]

    def test_json_schema_generated(self) -> None:
        schema = ContrarianReport.model_json_schema()
        assert "bear_conviction" in schema["properties"]


# ── Test class: ValuationOutput ───────────────────────────────────────────────


class TestValuationOutput:
    def test_minimal_instantiation(self) -> None:
        m = _make_valuation()
        assert m.valuation_verdict == "undervalued"
        assert m.agent_name == "valuation_agent"

    def test_optional_numeric_fields_default_none(self) -> None:
        m = _make_valuation()
        assert m.intrinsic_value_per_share is None
        assert m.current_price is None
        assert m.upside_downside_pct is None
        assert m.pe_ratio is None
        assert m.pb_ratio is None

    def test_full_instantiation(self) -> None:
        m = _make_valuation(
            intrinsic_value_per_share=4200.0,
            current_price=3850.0,
            upside_downside_pct=9.1,
            dcf_wacc_pct=10.5,
            dcf_terminal_growth_pct=4.5,
            dcf_projection_years=10,
            pe_ratio=28.5,
            sector_avg_pe=25.0,
            pb_ratio=9.5,
            sector_avg_pb=8.0,
            ev_ebitda=18.0,
            sector_avg_ev_ebitda=16.0,
            peer_tickers=["INFY.NS", "WIPRO.NS", "HCL.NS"],
            premium_discount_to_peers_pct=12.0,
            margin_of_safety="low",
            summary="TCS trades at a modest premium to peers...",
        )
        assert m.intrinsic_value_per_share == 4200.0
        assert m.peer_tickers == ["INFY.NS", "WIPRO.NS", "HCL.NS"]
        assert m.dcf_projection_years == 10

    def test_peer_tickers_default_empty(self) -> None:
        m = _make_valuation()
        assert m.peer_tickers == []

    def test_model_dump(self) -> None:
        m = _make_valuation(pe_ratio=28.5)
        d = m.model_dump()
        assert d["valuation_verdict"] == "undervalued"
        assert d["pe_ratio"] == 28.5

    def test_json_schema_generated(self) -> None:
        schema = ValuationOutput.model_json_schema()
        assert "valuation_verdict" in schema["properties"]


# ── Test class: InvestmentDecision ────────────────────────────────────────────


class TestInvestmentDecision:
    def test_minimal_instantiation(self) -> None:
        m = _make_decision()
        assert m.verdict == "BUY"
        assert m.conviction_score == 8
        assert m.agent_name == "portfolio_manager"

    def test_conviction_score_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_decision(conviction_score=0)
        with pytest.raises(ValidationError):
            _make_decision(conviction_score=11)

    def test_verdict_values(self) -> None:
        for v in ["BUY", "HOLD", "SELL"]:
            m = _make_decision(verdict=v)
            assert m.verdict == v

    def test_optional_price_target(self) -> None:
        m = _make_decision()
        assert m.price_target is None
        m2 = _make_decision(price_target="₹4,200 (12-month)")
        assert m2.price_target == "₹4,200 (12-month)"

    def test_memo_section_defaults(self) -> None:
        m = _make_decision()
        assert m.executive_summary == ""
        assert m.investment_thesis == ""
        assert m.bull_case == ""
        assert m.bear_case == ""

    def test_agent_weights_default_empty(self) -> None:
        m = _make_decision()
        assert m.agent_weights == {}

    def test_full_instantiation(self) -> None:
        m = _make_decision(
            verdict="BUY",
            conviction_score=8,
            price_target="₹4,200 (12-month)",
            executive_summary="TCS is a high-quality compounder...",
            investment_thesis="Market share gains + AI transformation...",
            bull_case="Strong fundamental quality score of 8/10...",
            bear_case="Contrarian flags FCF decline risk...",
            risk_summary="Key risks: US visa policy, attrition...",
            valuation_summary="DCF implies 9% upside at current price...",
            contrarian_response="FCF decline is cyclical not structural...",
            debate_rounds_used=2,
            agent_weights={
                "fundamental_analyst": 0.3,
                "technical_analyst": 0.1,
                "news_sentiment": 0.1,
                "macro_economist": 0.1,
                "risk_officer": 0.2,
                "contrarian_investor": 0.1,
                "valuation_agent": 0.1,
            },
            summary="TCS: BUY with conviction 8/10",
        )
        assert m.conviction_score == 8
        assert m.debate_rounds_used == 2
        assert m.agent_weights["fundamental_analyst"] == 0.3

    def test_model_dump(self) -> None:
        m = _make_decision()
        d = m.model_dump()
        assert d["verdict"] == "BUY"
        assert d["conviction_score"] == 8
        assert d["agent_name"] == "portfolio_manager"

    def test_json_round_trip(self) -> None:
        m = _make_decision(
            verdict="HOLD",
            conviction_score=5,
            investment_thesis="Awaiting macro clarity.",
        )
        data = json.loads(m.model_dump_json())
        assert data["verdict"] == "HOLD"
        assert data["conviction_score"] == 5
        assert data["investment_thesis"] == "Awaiting macro clarity."

    def test_json_schema_generated(self) -> None:
        schema = InvestmentDecision.model_json_schema()
        assert "verdict" in schema["properties"]
        assert "conviction_score" in schema["properties"]


# ── Cross-model tests ─────────────────────────────────────────────────────────


class TestCrossModel:
    """Tests that span multiple models — serialisation, schema, __all__."""

    ALL_FACTORIES = [
        _make_fundamental,
        _make_technical,
        _make_sentiment,
        _make_macro,
        _make_risk,
        _make_contrarian,
        _make_valuation,
        _make_decision,
    ]

    EXPECTED_AGENT_NAMES = [
        "fundamental_analyst",
        "technical_analyst",
        "news_sentiment",
        "macro_economist",
        "risk_officer",
        "contrarian_investor",
        "valuation_agent",
        "portfolio_manager",
    ]

    def test_all_models_have_correct_agent_name(self) -> None:
        for factory, expected_name in zip(
            self.ALL_FACTORIES, self.EXPECTED_AGENT_NAMES
        ):
            m = factory()
            assert m.agent_name == expected_name, (
                f"Expected agent_name={expected_name!r}, got {m.agent_name!r} "
                f"for {type(m).__name__}"
            )

    def test_all_models_serialise_to_dict(self) -> None:
        for factory in self.ALL_FACTORIES:
            m = factory()
            d = m.model_dump()
            assert isinstance(d, dict), f"{type(m).__name__}.model_dump() not a dict"
            assert "agent_name" in d
            assert "analysis_id" in d
            assert "ticker" in d

    def test_all_models_serialise_to_json(self) -> None:
        for factory in self.ALL_FACTORIES:
            m = factory()
            json_str = m.model_dump_json()
            assert isinstance(json_str, str)
            parsed = json.loads(json_str)
            assert parsed["agent_name"] == m.agent_name

    def test_all_schemas_auto_generated(self) -> None:
        models: list[type[BaseModel]] = [
            FundamentalAnalysis,
            TechnicalAnalysis,
            SentimentAnalysis,
            MacroAnalysis,
            RiskAnalysis,
            ContrarianReport,
            ValuationOutput,
            InvestmentDecision,
        ]
        for cls in models:
            schema = cls.model_json_schema()
            assert isinstance(schema, dict), f"Schema for {cls.__name__} is not a dict"
            assert (
                "properties" in schema
            ), f"Schema for {cls.__name__} missing 'properties'"

    def test_all_models_inherit_agent_output(self) -> None:
        for factory in self.ALL_FACTORIES:
            m = factory()
            assert isinstance(
                m, AgentOutput
            ), f"{type(m).__name__} does not inherit from AgentOutput"

    def test_error_field_on_all_models(self) -> None:
        for factory in self.ALL_FACTORIES:
            m = factory()
            assert (
                m.error is None
            ), f"{type(m).__name__} should have error=None by default"

    def test_all_exports_in_dunder_all(self) -> None:
        from backend.agents import output_models

        assert hasattr(output_models, "__all__")
        expected = {
            "AgentOutput",
            "FundamentalAnalysis",
            "TechnicalAnalysis",
            "SentimentAnalysis",
            "MacroAnalysis",
            "RiskAnalysis",
            "ContrarianReport",
            "ValuationOutput",
            "InvestmentDecision",
        }
        actual = set(output_models.__all__)
        missing = expected - actual
        extra = actual - expected
        assert (
            expected == actual
        ), f"__all__ mismatch.\n  Missing: {missing}\n  Extra: {extra}"

    def test_json_round_trip_preserves_none_optionals(self) -> None:
        """None optional fields survive JSON serialisation as null → None."""
        m = _make_fundamental()
        data = json.loads(m.model_dump_json())
        assert data["revenue_growth_pct"] is None
        assert data["debt_to_equity"] is None

    def test_json_round_trip_preserves_lists(self) -> None:
        m = _make_fundamental(
            strengths=["S1", "S2"],
            weaknesses=["W1"],
        )
        data = json.loads(m.model_dump_json())
        assert data["strengths"] == ["S1", "S2"]
        assert data["weaknesses"] == ["W1"]
