# backend/agents/output_models.py
"""
AIRP — Agent Output Models (T-021)

Pydantic v2 models for every agent in the investment committee.
These are the canonical output schemas — agents return instances of these
models and LangGraph stores them in InvestmentState.  Every schema is:

  * Typed         — every field has a Python type annotation
  * Documented    — every field has a description (shown in JSON schema)
  * Serialisable  — model.model_dump() / model.model_dump_json() work correctly
  * Importable    — all models are re-exported from this module's __all__

Hierarchy
─────────
  AgentOutput          ← shared base: agent_name, analysis_id, error
    ├── FundamentalAnalysis
    ├── TechnicalAnalysis
    ├── SentimentAnalysis
    ├── MacroAnalysis
    ├── RiskAnalysis
    ├── ContrarianReport
    ├── ValuationOutput
    └── InvestmentDecision

Design decisions
────────────────
* NO ``from __future__ import annotations`` — it breaks Pydantic v2 union
  type resolution (forward references become strings, not types).
* All Literal types are used for constrained string fields (verdict, signal,
  macro environment) so invalid values are rejected at validation time.
* Optional fields use ``Optional[X]`` (not bare ``X | None``) for clarity.
* Field descriptions are machine-readable so JSON schema auto-generation
  (``model.model_json_schema()``) produces self-documenting API docs.
* ``model_config = ConfigDict(frozen=True)`` on the base makes all agent
  outputs immutable once constructed — agents cannot mutate each other's
  outputs via shared state references.

Usage in agents (Phase 2+)
──────────────────────────
    from agents.output_models import FundamentalAnalysis

    result = FundamentalAnalysis(
        agent_name="fundamental_analyst",
        analysis_id=state["job_id"],
        company_name="TCS",
        ticker="TCS.NS",
        score=8,
        revenue_growth_pct=12.5,
        ...
    )
    # Serialise to dict for LangGraph state
    state["fundamental"] = result.model_dump()
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class AgentOutput(BaseModel):
    """
    Shared base class for every investment committee agent output.

    Every agent must populate the four base fields.  The ``error`` field
    follows the AIRP convention: agents never raise — if an error occurs,
    they return a model with ``error`` set.  Downstream agents and the
    LangGraph router check ``result.error is not None`` to detect failures.
    """

    model_config = ConfigDict(frozen=True)

    agent_name: str = Field(
        description=(
            "Canonical agent identifier matching the AgentNameEnum in orm.py "
            "(e.g. 'fundamental_analyst', 'portfolio_manager')"
        )
    )
    analysis_id: str = Field(
        description="UUID of the parent Analysis job (FK → analyses.id)"
    )
    company_name: str = Field(
        description="Human-readable company name (e.g. 'Tata Consultancy Services')"
    )
    ticker: str = Field(
        description="Yahoo Finance ticker with exchange suffix (e.g. 'TCS.NS')"
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this output was produced",
    )
    error: Optional[str] = Field(
        default=None,
        description=(
            "Non-null when the agent failed.  Contains a human-readable error "
            "message.  Null on success.  Downstream agents check this field "
            "before consuming the output."
        ),
    )


# ---------------------------------------------------------------------------
# Fundamental Analyst (Agent 1)
# ---------------------------------------------------------------------------


class FundamentalAnalysis(AgentOutput):
    """
    Output from the Fundamental Analyst agent.

    Analyses revenue growth, profit margins, free cash flow, and balance
    sheet health over 4 years.  Produces a scalar score (1–10) that the
    Portfolio Manager uses as one input to the final verdict.

    Tools used: yFinance, Alpha Vantage
    """

    agent_name: str = Field(default="fundamental_analyst", frozen=True)

    # ── Scores ────────────────────────────────────────────────────────────
    score: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description=(
            "Overall fundamental quality score: 1 (very poor) – 10 (excellent). "
            "Weighted average of revenue growth, margin stability, FCF generation, "
            "and debt safety. None when data_quality='insufficient' — an "
            "unreliable score is worse than an honest 'unknown'."
        ),
    )
    data_quality: str = Field(
        default="sufficient",
        description=(
            "'sufficient' when >=2 of the 5 scoring metrics (revenue CAGR, net "
            "margin, ROE, debt-to-equity, FCF margin) were available; "
            "'insufficient' when fewer than 2 were available, in which case "
            "score is None rather than a misleadingly low floor value."
        ),
    )
    years_available: Optional[int] = Field(
        default=None,
        ge=0,
        le=4,
        description=(
            "Number of fiscal years (out of a maximum of 4) fetch_financials "
            "actually returned data for (T-084). Pass-through from "
            "FinancialStatements.years_available -- distinct from "
            "data_quality, which measures how many of the 5 SCORING metrics "
            "could be computed from whatever years were available. None when "
            "the financials fetch failed entirely (no year count to report)."
        ),
    )

    # ── Revenue ───────────────────────────────────────────────────────────
    revenue_growth_pct: Optional[float] = Field(
        default=None,
        description="YoY revenue growth rate (%) for the most recent fiscal year",
    )
    revenue_cagr_3y_pct: Optional[float] = Field(
        default=None,
        description="3-year compound annual revenue growth rate (%)",
    )

    # ── Margins ───────────────────────────────────────────────────────────
    gross_margin_pct: Optional[float] = Field(
        default=None,
        description="Gross profit margin (%) = gross profit / revenue × 100",
    )
    operating_margin_pct: Optional[float] = Field(
        default=None,
        description="Operating margin (%) = EBIT / revenue × 100",
    )
    net_margin_pct: Optional[float] = Field(
        default=None,
        description="Net profit margin (%) = net income / revenue × 100",
    )

    # ── Cash flow ─────────────────────────────────────────────────────────
    free_cash_flow_cr: Optional[float] = Field(
        default=None,
        description="Free cash flow in ₹ crore (TTM)",
    )
    fcf_yield_pct: Optional[float] = Field(
        default=None,
        description="FCF yield (%) = FCF / market cap × 100",
    )

    # ── Balance sheet ─────────────────────────────────────────────────────
    debt_to_equity: Optional[float] = Field(
        default=None,
        description="Total debt / total shareholders' equity ratio",
    )
    current_ratio: Optional[float] = Field(
        default=None,
        description="Current assets / current liabilities (liquidity indicator)",
    )
    interest_coverage: Optional[float] = Field(
        default=None,
        description="EBIT / interest expense (debt service safety margin)",
    )

    # ── Return metrics ────────────────────────────────────────────────────
    roe_pct: Optional[float] = Field(
        default=None,
        description="Return on equity (%) = net income / shareholders' equity × 100",
    )
    roce_pct: Optional[float] = Field(
        default=None,
        description="Return on capital employed (%)",
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    strengths: list[str] = Field(
        default_factory=list,
        description="Top 3–5 fundamental strengths identified by the agent",
    )
    weaknesses: list[str] = Field(
        default_factory=list,
        description="Top 3–5 fundamental weaknesses or risks identified",
    )
    summary: str = Field(
        default="",
        description=(
            "2–3 sentence plain-English summary of the fundamental analysis, "
            "written to be read by the Portfolio Manager and Contrarian agents"
        ),
    )


# ---------------------------------------------------------------------------
# Technical Analyst (Agent 2)
# ---------------------------------------------------------------------------


class TechnicalAnalysis(AgentOutput):
    """
    Output from the Technical Analyst agent.

    Evaluates price trends, moving averages, RSI, and momentum.
    Produces a directional signal (BUY / HOLD / SELL) based on technical
    indicators derived from OHLCV data.

    Tools used: yFinance OHLCV data
    """

    agent_name: str = Field(default="technical_analyst", frozen=True)

    # ── Signal ────────────────────────────────────────────────────────────
    signal: str = Field(
        description=(
            "Directional signal from technical analysis: "
            "'BUY' (bullish), 'HOLD' (neutral), or 'SELL' (bearish)"
        )
    )
    signal_strength: int = Field(
        ge=1,
        le=10,
        description=(
            "Conviction level of the technical signal: "
            "1 (very weak) – 10 (very strong)"
        ),
    )

    # ── Price levels ──────────────────────────────────────────────────────
    current_price: Optional[float] = Field(
        default=None,
        description="Most recent closing price in ₹",
    )
    week_52_high: Optional[float] = Field(
        default=None,
        description="52-week high closing price in ₹",
    )
    week_52_low: Optional[float] = Field(
        default=None,
        description="52-week low closing price in ₹",
    )
    price_vs_52w_high_pct: Optional[float] = Field(
        default=None,
        description="Current price as % of 52-week high (100 = at high, <100 = below)",
    )

    # ── Moving averages ───────────────────────────────────────────────────
    ma_50d: Optional[float] = Field(
        default=None,
        description="50-day simple moving average of closing price in ₹",
    )
    ma_200d: Optional[float] = Field(
        default=None,
        description="200-day simple moving average of closing price in ₹",
    )
    price_above_ma50: Optional[bool] = Field(
        default=None,
        description="True when current price is above the 50-day MA (bullish sign)",
    )
    price_above_ma200: Optional[bool] = Field(
        default=None,
        description="True when current price is above the 200-day MA (trend indicator)",
    )
    golden_cross: Optional[bool] = Field(
        default=None,
        description=(
            "True when the 50-day MA is above the 200-day MA "
            "(bullish 'golden cross' formation)"
        ),
    )

    # ── Momentum ──────────────────────────────────────────────────────────
    rsi_14: Optional[float] = Field(
        default=None,
        description=(
            "14-period Relative Strength Index: "
            "<30 = oversold, >70 = overbought, 30–70 = neutral"
        ),
    )
    momentum_1m_pct: Optional[float] = Field(
        default=None,
        description="1-month price return (%)",
    )
    momentum_3m_pct: Optional[float] = Field(
        default=None,
        description="3-month price return (%)",
    )
    momentum_6m_pct: Optional[float] = Field(
        default=None,
        description="6-month price return (%)",
    )
    momentum_1y_pct: Optional[float] = Field(
        default=None,
        description="1-year price return (%)",
    )

    # ── Volume ────────────────────────────────────────────────────────────
    avg_volume_30d: Optional[float] = Field(
        default=None,
        description="Average daily trading volume over the last 30 days",
    )
    volume_trend: Optional[str] = Field(
        default=None,
        description=(
            "Volume trend: 'increasing', 'decreasing', or 'stable' "
            "compared to prior 30-day period"
        ),
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    support_levels: list[float] = Field(
        default_factory=list,
        description="Key price support levels identified from the chart (in ₹)",
    )
    resistance_levels: list[float] = Field(
        default_factory=list,
        description="Key price resistance levels identified from the chart (in ₹)",
    )
    summary: str = Field(
        default="",
        description=(
            "2–3 sentence plain-English technical summary — "
            "what the chart says about the likely near-term price direction"
        ),
    )


# ---------------------------------------------------------------------------
# News Sentiment Agent (Agent 3)
# ---------------------------------------------------------------------------


class SentimentAnalysis(AgentOutput):
    """
    Output from the News Sentiment Agent.

    Scores the last 30 days of news, detects red flags in management
    conduct, regulatory issues, and public perception.

    Tools used: NewsAPI, ChromaDB semantic search
    """

    agent_name: str = Field(default="news_sentiment", frozen=True)

    # ── Scores ────────────────────────────────────────────────────────────
    sentiment_score: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Aggregate sentiment score over the last 30 days: "
            "-1.0 (very negative) … 0.0 (neutral) … +1.0 (very positive)"
        ),
    )
    sentiment_label: str = Field(
        description=(
            "Human-readable sentiment label: "
            "'very_positive', 'positive', 'neutral', 'negative', or 'very_negative'"
        )
    )

    # ── Article statistics ────────────────────────────────────────────────
    articles_analysed: int = Field(
        ge=0,
        description="Number of news articles analysed in this run",
    )
    positive_articles: int = Field(
        ge=0,
        description="Count of articles scored as positive (score > 0.1)",
    )
    negative_articles: int = Field(
        ge=0,
        description="Count of articles scored as negative (score < -0.1)",
    )
    neutral_articles: int = Field(
        ge=0,
        description="Count of articles scored as neutral (-0.1 ≤ score ≤ 0.1)",
    )

    # ── Red flags ─────────────────────────────────────────────────────────
    red_flags: list[str] = Field(
        default_factory=list,
        description=(
            "List of specific red flags detected (e.g. 'CEO under investigation', "
            "'SEBI regulatory notice', 'accounting restatement rumour'). "
            "Empty list means no red flags found."
        ),
    )
    red_flag_count: int = Field(
        default=0,
        ge=0,
        description="Total number of distinct red flags detected",
    )

    # ── Top stories ───────────────────────────────────────────────────────
    top_positive_headlines: list[str] = Field(
        default_factory=list,
        description="Up to 3 most positive headlines from the analysis period",
    )
    top_negative_headlines: list[str] = Field(
        default_factory=list,
        description="Up to 3 most negative headlines from the analysis period",
    )

    # ── Topics ────────────────────────────────────────────────────────────
    dominant_topics: list[str] = Field(
        default_factory=list,
        description=(
            "Top 3–5 news topics dominating coverage "
            "(e.g. 'AI investment', 'deal win', 'margin pressure')"
        ),
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    summary: str = Field(
        default="",
        description=(
            "2–3 sentence plain-English summary of the news sentiment landscape, "
            "highlighting the most impactful stories and any red flags found"
        ),
    )


# ---------------------------------------------------------------------------
# Macro Economist (Agent 4)
# ---------------------------------------------------------------------------


class MacroAnalysis(AgentOutput):
    """
    Output from the Macro Economist agent.

    Assesses the Indian macroeconomic environment: RBI rate stance,
    inflation, GDP, and sector-specific tailwinds/headwinds.

    Tools used: RBI scraper, World Bank API, macro data cache
    """

    agent_name: str = Field(default="macro_economist", frozen=True)

    # ── Macro environment classification ──────────────────────────────────
    macro_environment: str = Field(
        description=(
            "Overall macro environment: 'favourable', 'neutral', or 'unfavourable' "
            "for equity investing at the current time"
        )
    )
    sector_impact: str = Field(
        description=(
            "Macro impact on the company's specific sector: "
            "'tailwind', 'neutral', or 'headwind'"
        )
    )

    # ── RBI & interest rates ──────────────────────────────────────────────
    rbi_repo_rate_pct: Optional[float] = Field(
        default=None,
        description="Current RBI repo rate (%)",
    )
    rate_stance: Optional[str] = Field(
        default=None,
        description=(
            "RBI's current rate stance: "
            "'accommodative', 'neutral', 'calibrated_tightening', or 'tightening'"
        ),
    )
    rate_direction: Optional[str] = Field(
        default=None,
        description=("Expected near-term direction: 'cutting', 'holding', or 'hiking'"),
    )

    # ── Inflation ─────────────────────────────────────────────────────────
    cpi_inflation_pct: Optional[float] = Field(
        default=None,
        description="Latest CPI inflation reading (%)",
    )
    wpi_inflation_pct: Optional[float] = Field(
        default=None,
        description="Latest WPI inflation reading (%)",
    )
    inflation_trend: Optional[str] = Field(
        default=None,
        description=("Inflation trend direction: 'rising', 'stable', or 'falling'"),
    )

    # ── Growth ────────────────────────────────────────────────────────────
    gdp_growth_pct: Optional[float] = Field(
        default=None,
        description="India's latest GDP growth rate (%)",
    )
    gdp_forecast_pct: Optional[float] = Field(
        default=None,
        description="IMF / World Bank GDP growth forecast for current fiscal year (%)",
    )

    # ── Sector-specific factors ───────────────────────────────────────────
    tailwinds: list[str] = Field(
        default_factory=list,
        description=(
            "Specific macro tailwinds benefiting this sector "
            "(e.g. 'INR depreciation benefits IT exporters', 'capex cycle upturn')"
        ),
    )
    headwinds: list[str] = Field(
        default_factory=list,
        description=(
            "Specific macro headwinds facing this sector "
            "(e.g. 'higher cost of capital hurts NBFC margins', 'global slowdown risk')"
        ),
    )

    # ── Currency ──────────────────────────────────────────────────────────
    usd_inr_rate: Optional[float] = Field(
        default=None,
        description="Current USD/INR exchange rate",
    )
    inr_trend: Optional[str] = Field(
        default=None,
        description="INR trend vs USD: 'appreciating', 'stable', or 'depreciating'",
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    summary: str = Field(
        default="",
        description=(
            "2–3 sentence plain-English macro summary — "
            "how the current macro environment affects this company's investment case"
        ),
    )


# ---------------------------------------------------------------------------
# Risk Officer (Agent 5)
# ---------------------------------------------------------------------------


class RiskAnalysis(AgentOutput):
    """
    Output from the Risk Officer agent.

    Reads all prior research agent outputs and identifies governance
    failures, fraud indicators, regulatory risks, and concentration risks.
    Produces a risk score and a list of named flags.

    Tools used: All prior agent outputs (reads from InvestmentState)
    """

    agent_name: str = Field(default="risk_officer", frozen=True)

    # ── Risk scores ───────────────────────────────────────────────────────
    risk_score: int = Field(
        ge=1,
        le=10,
        description=(
            "Overall risk level: 1 (very low risk) – 10 (extremely high risk). "
            "Composite of governance, fraud, regulatory, and concentration risks."
        ),
    )
    governance_risk: int = Field(
        ge=1,
        le=10,
        description="Governance and management quality risk score (1=best, 10=worst)",
    )
    regulatory_risk: int = Field(
        ge=1,
        le=10,
        description=(
            "Regulatory and compliance risk score — "
            "considers active investigations, sector-level regulation, pending cases"
        ),
    )
    financial_risk: int = Field(
        ge=1,
        le=10,
        description=(
            "Financial health risk score — "
            "considers leverage, liquidity, FCF stability, and accounting quality"
        ),
    )
    concentration_risk: int = Field(
        ge=1,
        le=10,
        description=(
            "Business concentration risk — "
            "customer/geography/revenue-stream dependency"
        ),
    )

    # ── Risk flags ────────────────────────────────────────────────────────
    risk_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Specific named risk flags the Risk Officer has identified. "
            "Each entry is a 1-sentence description of a concrete risk "
            "(e.g. 'High promoter pledge: 45% of holding pledged as of Q3 FY24'). "
            "Empty list when no material flags are found."
        ),
    )
    critical_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Subset of risk_flags deemed critical — risks that could impair "
            "capital severely if materialised. Portfolio Manager must explicitly "
            "address every entry here in the investment thesis."
        ),
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    risk_recommendation: str = Field(
        default="",
        description=(
            "Risk Officer's recommendation to the committee: "
            "'proceed with caution', 'monitor closely', or 'avoid'. "
            "Not a final verdict — the Portfolio Manager decides."
        ),
    )
    summary: str = Field(
        default="",
        description=(
            "2–3 sentence plain-English risk summary — "
            "the most important risks and their potential impact on returns"
        ),
    )


# ---------------------------------------------------------------------------
# Contrarian Investor (Agent 6)
# ---------------------------------------------------------------------------


class ContrarianReport(AgentOutput):
    """
    Output from the Contrarian Investor agent.

    Its only job: disagree.  Finds flaws in every bullish thesis, surfaces
    overlooked risks, and challenges assumptions made by all other agents.
    The Portfolio Manager must explicitly address the most significant
    counter-arguments in the final memo.

    Tools used: Full InvestmentState (reads all prior outputs)
    """

    agent_name: str = Field(default="contrarian_investor", frozen=True)

    # ── Counter-arguments ─────────────────────────────────────────────────
    counter_arguments: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of counter-arguments against the prevailing bullish "
            "thesis.  Each entry is a 1–2 sentence specific challenge "
            "(e.g. 'The Fundamental Analyst's 8/10 score ignores that FCF "
            "conversion has declined for 3 consecutive years')."
        ),
    )
    challenged_agents: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the agents whose outputs the Contrarian most directly "
            "challenges (e.g. ['fundamental_analyst', 'valuation_agent'])"
        ),
    )

    # ── Overlooked risks ──────────────────────────────────────────────────
    overlooked_risks: list[str] = Field(
        default_factory=list,
        description=(
            "Risks that no other agent flagged but the Contrarian has identified. "
            "These are structural or hidden risks not captured by standard analysis."
        ),
    )

    # ── Contrarian conviction ─────────────────────────────────────────────
    bear_conviction: int = Field(
        ge=1,
        le=10,
        description=(
            "How strongly the Contrarian believes the consensus is wrong: "
            "1 (mild disagreement) – 10 (strongly contra-consensus). "
            "A score ≥7 should trigger a second debate round."
        ),
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    strongest_argument: str = Field(
        default="",
        description=(
            "The single most compelling counter-argument — "
            "the one the Portfolio Manager must address directly"
        ),
    )
    summary: str = Field(
        default="",
        description=(
            "2–3 sentence summary of the Contrarian's overall position — "
            "why the bullish case may be overstated"
        ),
    )


# ---------------------------------------------------------------------------
# Valuation Agent (Agent 7)
# ---------------------------------------------------------------------------


class ValuationOutput(AgentOutput):
    """
    Output from the Valuation Agent.

    Runs a DCF valuation model and compares PE / PB / EV-EBITDA against
    sector peers.  Calculates upside / downside to intrinsic value.

    Tools used: Screener.in (peer data), yFinance (market data)
    """

    agent_name: str = Field(default="valuation_agent", frozen=True)

    # ── Intrinsic value ───────────────────────────────────────────────────
    intrinsic_value_per_share: Optional[float] = Field(
        default=None,
        description="DCF-derived intrinsic value per share in ₹",
    )
    current_price: Optional[float] = Field(
        default=None,
        description="Current market price per share in ₹ (used as DCF denominator)",
    )
    upside_downside_pct: Optional[float] = Field(
        default=None,
        description=(
            "Upside (+) or downside (-) to intrinsic value as % of current price. "
            "Positive = undervalued, negative = overvalued."
        ),
    )
    valuation_verdict: str = Field(
        description=(
            "Valuation-based view: 'undervalued', 'fairly_valued', or 'overvalued'"
        )
    )

    # ── DCF assumptions ───────────────────────────────────────────────────
    dcf_wacc_pct: Optional[float] = Field(
        default=None,
        description="Weighted average cost of capital used in DCF model (%)",
    )
    dcf_terminal_growth_pct: Optional[float] = Field(
        default=None,
        description="Terminal growth rate assumed in DCF model (%)",
    )
    dcf_projection_years: Optional[int] = Field(
        default=None,
        description="Number of years projected in the DCF model (typically 5 or 10)",
    )
    dcf_sector_used: Optional[str] = Field(
        default=None,
        description=(
            "Canonical sector band used to select the DCF WACC (T-083), e.g. "
            "'it_services', 'fmcg', 'capital_intensive_cyclical', or "
            "'diversified' when no sector signal could be resolved"
        ),
    )

    # ── Relative valuation (multiples vs peers) ───────────────────────────
    pe_ratio: Optional[float] = Field(
        default=None,
        description="Current trailing P/E ratio",
    )
    sector_avg_pe: Optional[float] = Field(
        default=None,
        description="Sector average P/E ratio for peer comparison",
    )
    pb_ratio: Optional[float] = Field(
        default=None,
        description="Current price-to-book ratio",
    )
    sector_avg_pb: Optional[float] = Field(
        default=None,
        description="Sector average P/B ratio for peer comparison",
    )
    ev_ebitda: Optional[float] = Field(
        default=None,
        description="Current EV/EBITDA multiple",
    )
    sector_avg_ev_ebitda: Optional[float] = Field(
        default=None,
        description="Sector average EV/EBITDA for peer comparison",
    )

    # ── Peer comparison ───────────────────────────────────────────────────
    peer_tickers: list[str] = Field(
        default_factory=list,
        description="Yahoo Finance tickers of peer companies used in comparison",
    )
    premium_discount_to_peers_pct: Optional[float] = Field(
        default=None,
        description=(
            "How much the stock trades at a premium (+) or discount (-) "
            "to peers on a blended multiples basis (%)"
        ),
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    margin_of_safety: Optional[str] = Field(
        default=None,
        description=(
            "'high' (>30% upside), 'moderate' (15–30%), "
            "'low' (0–15%), or 'none' (overvalued)"
        ),
    )
    summary: str = Field(
        default="",
        description=(
            "2–3 sentence plain-English valuation summary — "
            "what the DCF and peer comparison say about the stock's current price"
        ),
    )


# ---------------------------------------------------------------------------
# Investment Decision — Portfolio Manager (Agent 8)
# ---------------------------------------------------------------------------


class InvestmentDecision(AgentOutput):
    """
    Final output from the Portfolio Manager agent.

    Reads the complete InvestmentState (all 7 prior agent outputs plus the
    debate transcript) and delivers the final BUY / HOLD / SELL verdict
    with a conviction score and written Investment Memo sections.

    This model is the direct source of data for the Investment Memo PDF.

    Tools used: Full InvestmentState (all prior agent outputs + debate log)
    """

    agent_name: str = Field(default="portfolio_manager", frozen=True)

    # ── Verdict ───────────────────────────────────────────────────────────
    verdict: str = Field(
        description="Final investment recommendation: 'BUY', 'HOLD', or 'SELL'"
    )
    conviction_score: int = Field(
        ge=1,
        le=10,
        description=(
            "Portfolio Manager confidence in the verdict: "
            "1 (very low conviction) – 10 (very high conviction). "
            "A score ≤3 suggests the committee should seek more data."
        ),
    )
    price_target: Optional[str] = Field(
        default=None,
        description=(
            "Implied price target (e.g. '₹4,200 (12-month)'); "
            "None when valuation is inconclusive"
        ),
    )
    time_horizon: str = Field(
        default="12 months",
        description=(
            "Suggested holding period for this verdict, e.g. "
            "'3-6 months', '12 months', '3-5 years', or "
            "'quarterly review (3 months)' for HOLD verdicts."
        ),
    )

    # ── Investment Memo sections ──────────────────────────────────────────
    executive_summary: str = Field(
        default="",
        description=(
            "2–3 paragraph executive summary of the investment case. "
            "Written for a non-specialist reader."
        ),
    )
    investment_thesis: str = Field(
        default="",
        description=(
            "Core investment thesis in 3–5 sentences — "
            "the primary reason for the BUY/HOLD/SELL verdict"
        ),
    )
    bull_case: str = Field(
        default="",
        description=(
            "Bull case argument — synthesised from fundamental, technical, "
            "sentiment, and macro agent outputs"
        ),
    )
    bear_case: str = Field(
        default="",
        description=(
            "Bear case — incorporates Contrarian Investor challenges and "
            "Risk Officer flags"
        ),
    )
    risk_summary: str = Field(
        default="",
        description=(
            "Top 3–5 risks the investor must monitor, "
            "ranked by potential impact on the thesis"
        ),
    )
    valuation_summary: str = Field(
        default="",
        description=(
            "Valuation perspective — DCF and peer comparison summary "
            "from the Valuation Agent"
        ),
    )

    # ── Structured memo inputs (T-041, consumed by T-042 memo generator) ──
    key_risks: list[str] = Field(
        default_factory=list,
        description=(
            "Structured list of the most important risks (critical Risk "
            "Officer flags first, then the Contrarian's strongest "
            "argument and overlooked risks), capped at 6 entries. "
            "Used directly by the Investment Memo's Risk Analysis section."
        ),
    )
    key_catalysts: list[str] = Field(
        default_factory=list,
        description=(
            "Structured list of factors that could move the thesis "
            "forward (macro tailwinds, valuation re-rating triggers, "
            "fundamental strengths), capped at 5 entries."
        ),
    )

    # ── Debate resolution ─────────────────────────────────────────────────
    contrarian_response: str = Field(
        default="",
        description=(
            "How the Portfolio Manager addresses the Contrarian's strongest argument. "
            "Every ContrarianReport.strongest_argument must be explicitly addressed."
        ),
    )
    debate_rounds_used: int = Field(
        default=1,
        ge=1,
        description="Number of debate rounds that occurred before this decision",
    )

    # ── Agent weight summary ──────────────────────────────────────────────
    agent_weights: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "How much weight (0.0–1.0) the Portfolio Manager assigned to each "
            "agent's output when forming the verdict. Keys are agent_name strings."
        ),
    )

    # ── Qualitative synthesis ─────────────────────────────────────────────
    summary: str = Field(
        default="",
        description=(
            "One-sentence summary suitable for dashboard display "
            "(e.g. 'TCS: BUY with conviction 8/10 — strong fundamentals, "
            "reasonable valuation, manageable risks')"
        ),
    )


# ---------------------------------------------------------------------------
# Public API — everything needed by agents and LangGraph
# ---------------------------------------------------------------------------

__all__ = [
    "AgentOutput",
    "FundamentalAnalysis",
    "TechnicalAnalysis",
    "SentimentAnalysis",
    "MacroAnalysis",
    "RiskAnalysis",
    "ContrarianReport",
    "ValuationOutput",
    "InvestmentDecision",
]
