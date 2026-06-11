# backend/agents/macro_economist.py
"""
AIRP -- Macro Economist Agent (T-025)

Persona: macro economist with 20 years of experience covering Indian markets.
Cuts through noise to identify the macro forces that actually move stock prices
-- RBI rate cycles, inflation trajectories, GDP momentum, and currency trends.

Mandate
-------
Assess the Indian macroeconomic environment using two data sources:
  * fetch_macro_data     -- RBI repo rate, CPI inflation, GDP growth
  * semantic_search      -- ChromaDB search on sector-relevant macro news
                            (COLLECTION_NEWS collection, non-fatal on failure)

Determine:
  1. Rate stance and direction (accommodative / tightening / cutting / hiking)
  2. Inflation trend (rising / stable / falling)
  3. Macro environment classification (favourable / neutral / unfavourable)
  4. Sector-specific impact (tailwind / neutral / headwind)
  5. Key tailwinds and headwinds for the company's sector

**Acceptance criteria:** Correctly identifies a rate hike environment
as a headwind for banking stocks (higher cost of funds, NIM compression
risk) and as a headwind for rate-sensitive sectors (NBFCs, real estate,
auto financing).

Output: MacroAnalysis (defined in output_models.py)

Public interface
----------------
  run_macro_analysis(state)            -> dict   LangGraph node
  _run_macro_analysis_core(...)        -> MacroAnalysis  testable core
  _classify_rate_stance(repo_rate)     -> str    pure, unit-testable
  _classify_rate_direction(repo_rate)  -> str    pure, unit-testable
  _classify_inflation_trend(cpi)       -> str    pure, unit-testable
  _classify_macro_environment(...)     -> str    pure, unit-testable
  _detect_sector(company_name)         -> str    pure, unit-testable
  _classify_sector_impact(...)         -> str    pure, unit-testable
  _build_tailwinds_headwinds(...)      -> tuple  pure, unit-testable
  _build_macro_prompt(...)             -> str    prompt builder, pure

Design decisions
----------------
* NO ``from __future__ import annotations`` -- breaks Pydantic v2.
* ALL classification logic is deterministic (pure Python) -- the LLM
  synthesises tailwinds/headwinds/summary but never overrides the
  numeric fields or environment/sector_impact labels.
* Sector detection is keyword-based, mapping company name to one of
  eight canonical Indian market sectors.  This is sufficient for the
  acceptance criteria and avoids a ticker-lookup round-trip.
* Rate stance thresholds follow RBI historical norms:
    < 5.0%  -> accommodative (e.g. COVID-era 4.0%)
    5.0-5.9% -> neutral
    6.0-6.9% -> calibrated_tightening
    >= 7.0% -> tightening
* Rate direction (cutting / holding / hiking) is inferred from the
  repo rate level vs the neutral midpoint (6.0%) -- not from scraping
  MPC minutes, which would require a separate brittle parser.
* Error convention: never raises.  On any failure MacroAnalysis.error
  is set and macro_environment defaults to 'neutral'.

Usage in LangGraph (Phase 3)
----------------------------
    from backend.agents.macro_economist import run_macro_analysis
    builder.add_node("macro_economist", run_macro_analysis)
    # Reads:  state["job_id"], state["company_name"], state["ticker"]
    # Writes: state["macro"]  (dict from MacroAnalysis.model_dump())
"""

import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import MacroAnalysis
from backend.db.chroma_client import COLLECTION_NEWS, semantic_search
from backend.tools.macro import fetch_macro_data

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants -- RBI rate thresholds
# ---------------------------------------------------------------------------

# Repo rate bands -> stance (RBI historical norms for Indian markets)
RATE_ACCOMMODATIVE_MAX: float = 5.0  # below this -> accommodative
RATE_NEUTRAL_MAX: float = 6.0  # 5.0-5.99 -> neutral
RATE_CALIB_TIGHTENING_MAX: float = 7.0  # 6.0-6.99 -> calibrated_tightening
# >= 7.0 -> tightening

# Midpoint used for direction inference
RATE_NEUTRAL_MIDPOINT: float = 6.0

# CPI inflation bands -> trend label (RBI's comfort zone is 2-6%)
CPI_LOW_THRESHOLD: float = 4.0  # below -> falling / benign
CPI_ELEVATED_THRESHOLD: float = 6.0  # 4-6 -> stable; above -> rising

# Macro environment thresholds
# A favourable environment needs: GDP > this AND CPI < CPI_ELEVATED_THRESHOLD
GDP_GROWTH_STRONG: float = 6.5  # India-specific: strong growth benchmark
GDP_GROWTH_WEAK: float = 5.0  # below this -> weak growth signal

# ChromaDB semantic search result count
CHROMA_N_RESULTS: int = 5

# ---------------------------------------------------------------------------
# Sector detection -- keyword map
# ---------------------------------------------------------------------------

# Map company name keywords -> canonical sector label
# Checked in order; first match wins.
SECTOR_KEYWORDS: list[tuple[list[str], str]] = [
    (
        [
            "bank",
            "hdfc",
            "icici",
            "axis",
            "kotak",
            "sbi",
            "pnb",
            "canara",
            "indusind",
            "yes bank",
            "federal bank",
            "bandhan",
        ],
        "banking",
    ),
    (
        [
            "nbfc",
            "bajaj finance",
            "shriram",
            "muthoot",
            "chola",
            "mahindra fin",
            "piramal",
            "lic housing",
            "hdfc ltd",
        ],
        "nbfc",
    ),
    (
        [
            "tcs",
            "infosys",
            "wipro",
            "hcl",
            "tech mahindra",
            "ltimindtree",
            "mphasis",
            "hexaware",
            "persistent",
            "coforge",
            "software",
            "technology",
            "it services",
        ],
        "it_services",
    ),
    (
        [
            "reliance",
            "oil",
            "ongc",
            "bpcl",
            "ioc",
            "hpcl",
            "petronet",
            "energy",
            "petroleum",
            "refiner",
        ],
        "energy",
    ),
    (
        [
            "pharma",
            "sun pharma",
            "cipla",
            "dr reddy",
            "lupin",
            "aurobindo",
            "biocon",
            "divi",
            "healthcare",
            "hospital",
            "apollo",
            "max health",
        ],
        "pharma_healthcare",
    ),
    (
        [
            "auto",
            "tata motors",
            "maruti",
            "mahindra",
            "bajaj auto",
            "hero",
            "tvs",
            "eicher",
            "ashok leyland",
            "vehicle",
            "automobile",
        ],
        "auto",
    ),
    (
        [
            "fmcg",
            "hindustan unilever",
            "hul",
            "itc",
            "nestle",
            "dabur",
            "marico",
            "godrej",
            "britannia",
            "consumer",
        ],
        "fmcg",
    ),
    (
        [
            "infra",
            "cement",
            "l&t",
            "ultratech",
            "ambuja",
            "acc",
            "shree",
            "construction",
            "power",
            "ntpc",
            "adani",
            "steel",
            "jsw",
            "tata steel",
        ],
        "infra_industrials",
    ),
]

DEFAULT_SECTOR: str = "diversified"

# ---------------------------------------------------------------------------
# Sector-specific macro impact rules
# ---------------------------------------------------------------------------
# Maps (sector, rate_stance) -> impact label and (tailwinds, headwinds)
# Rate-hike environment impact for banking is the key acceptance criterion.

# Tailwind/headwind templates per sector and macro regime
_SECTOR_MACRO_RULES: dict[str, dict[str, Any]] = {
    "banking": {
        "tightening": {
            "impact": "headwind",
            "headwinds": [
                "Rate hike cycle compresses net interest margins as deposit"
                " repricing outpaces lending rate increases",
                "Higher cost of funds squeezes NIMs for retail and MSME lenders",
                "Rising rates increase credit risk -- borrower stress rises"
                " as EMIs increase",
            ],
            "tailwinds": [
                "Higher rates initially boost treasury income on floating"
                " rate assets",
                "Strong GDP growth supports credit demand despite higher rates",
            ],
        },
        "calibrated_tightening": {
            "impact": "headwind",
            "headwinds": [
                "Gradual tightening puts mild pressure on NIMs for banks"
                " with high fixed-rate loan books",
                "Elevated rates slow retail credit growth in home and auto loans",
            ],
            "tailwinds": [
                "Calibrated approach limits systemic stress; asset quality"
                " remains manageable",
                "Rising yields benefit banks' investment portfolios on"
                " new deployments",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable rate environment supports consistent NIM expansion"
                " as banks pass on rates",
                "Neutral policy reduces uncertainty and supports credit offtake",
            ],
            "headwinds": [
                "Flat rate environment offers limited scope for NIM expansion"
                " beyond current levels",
            ],
        },
        "accommodative": {
            "impact": "tailwind",
            "tailwinds": [
                "Low rates boost loan demand across retail, MSME, and"
                " corporate segments",
                "Accommodative policy supports asset quality as borrower"
                " repayment capacity improves",
                "Rate cuts compress bond yields, producing mark-to-market"
                " gains on bank investment books",
            ],
            "headwinds": [
                "Very low rates compress spreads and reduce NIM on"
                " floating-rate loans",
            ],
        },
    },
    "nbfc": {
        "tightening": {
            "impact": "headwind",
            "headwinds": [
                "Rate hikes increase NBFC borrowing costs faster than"
                " lending rates can be repriced, compressing spreads",
                "Tighter liquidity conditions restrict NBFC access to"
                " commercial paper and NCD markets",
                "Higher EMIs reduce affordability and slow disbursement"
                " growth in retail and housing segments",
            ],
            "tailwinds": [
                "Strong underlying credit demand in rural and semi-urban"
                " segments is less rate-sensitive",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable funding costs support spread maintenance",
                "Broad-based credit demand across vehicle, home, and"
                " personal loan segments",
            ],
            "headwinds": [
                "Competition from banks intensifies as rate differential" " narrows",
            ],
        },
        "accommodative": {
            "impact": "tailwind",
            "tailwinds": [
                "Low rates significantly reduce NBFC borrowing costs,"
                " expanding spreads",
                "Rate cuts stimulate demand for auto, home, and"
                " consumer durable financing",
            ],
            "headwinds": [],
        },
        "calibrated_tightening": {
            "impact": "headwind",
            "headwinds": [
                "Gradual rate increases compress NBFC spreads as liabilities"
                " reprice faster than assets",
            ],
            "tailwinds": ["Measured pace of tightening avoids liquidity crunch"],
        },
    },
    "it_services": {
        "tightening": {
            "impact": "neutral",
            "tailwinds": [
                "INR depreciation (common in tightening cycles driven by"
                " global risk-off) boosts USD revenue realisations",
                "IT exporters are largely insulated from domestic rate"
                " cycles -- revenue is USD-denominated",
            ],
            "headwinds": [
                "Rate hikes in the US (often concurrent with India"
                " tightening) can slow client tech budgets",
                "Tighter global financial conditions reduce discretionary"
                " IT spending by BFSI clients",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable macro backdrop supports IT budgets at client firms",
                "Resilient domestic consumption supports BFSI and retail"
                " sector IT spending",
            ],
            "headwinds": [
                "Rupee appreciation risk if global conditions ease"
                " -- erodes USD earnings in INR terms",
            ],
        },
        "accommodative": {
            "impact": "neutral",
            "tailwinds": [
                "Low domestic rates reduce NBFC/bank client financial stress,"
                " supporting IT budget cycles",
            ],
            "headwinds": [
                "INR appreciation in low-rate environments reduces USD"
                " earnings realisation",
            ],
        },
        "calibrated_tightening": {
            "impact": "neutral",
            "tailwinds": ["Modest INR depreciation supports export competitiveness"],
            "headwinds": [
                "Global tightening backdrop may pressure BFSI client budgets"
            ],
        },
    },
    "energy": {
        "tightening": {
            "impact": "headwind",
            "headwinds": [
                "Higher interest rates increase the cost of capex-heavy"
                " energy projects",
                "Tighter liquidity can delay refinery and pipeline capacity"
                " expansion plans",
            ],
            "tailwinds": [
                "Strong GDP growth supports domestic fuel demand despite"
                " higher rates",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable macro environment supports domestic fuel consumption"
                " and refining margins",
            ],
            "headwinds": [
                "Global oil price volatility driven by geopolitical factors"
                " rather than domestic macro",
            ],
        },
        "accommodative": {
            "impact": "tailwind",
            "tailwinds": [
                "Low rates reduce financing costs for capital-intensive"
                " exploration and refining capex",
                "Accommodative policy supports industrial activity and" " fuel demand",
            ],
            "headwinds": [],
        },
        "calibrated_tightening": {
            "impact": "neutral",
            "tailwinds": ["Moderate growth sustains energy demand"],
            "headwinds": ["Rising capex costs in tightening cycle"],
        },
    },
    "pharma_healthcare": {
        "tightening": {
            "impact": "neutral",
            "tailwinds": [
                "Pharma sector is largely defensive -- demand is"
                " inelastic to rate cycles",
                "Export-oriented pharma benefits from INR depreciation"
                " common in tightening environments",
            ],
            "headwinds": [
                "Higher rates increase working capital costs for"
                " API and formulation manufacturers",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable macro underpins healthcare utilisation and"
                " pharma consumption",
            ],
            "headwinds": [],
        },
        "accommodative": {
            "impact": "neutral",
            "tailwinds": [
                "Low rates reduce debt burden for hospital chains and"
                " biotech firms with high capex",
            ],
            "headwinds": [
                "INR appreciation in accommodative cycles may reduce"
                " export pharma margins",
            ],
        },
        "calibrated_tightening": {
            "impact": "neutral",
            "tailwinds": ["Defensive sector with limited macro sensitivity"],
            "headwinds": ["Marginal working capital cost increase"],
        },
    },
    "auto": {
        "tightening": {
            "impact": "headwind",
            "headwinds": [
                "Rate hikes raise auto loan EMIs, dampening two-wheeler"
                " and passenger vehicle demand",
                "Higher borrowing costs pressure dealer inventory financing,"
                " potentially reducing channel fill",
                "Tighter monetary policy can dampen discretionary consumer"
                " spending on big-ticket purchases",
            ],
            "tailwinds": [
                "Strong employment and income growth can partially offset"
                " rate sensitivity in premium segments",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable EMI levels support broad-based retail demand"
                " across vehicle segments",
                "Strong rural income supports two-wheeler and tractor demand",
            ],
            "headwinds": [
                "Commodity cost pressures (steel, aluminium) remain" " a margin risk",
            ],
        },
        "accommodative": {
            "impact": "tailwind",
            "tailwinds": [
                "Low interest rates significantly improve auto loan"
                " affordability, driving volume growth",
                "Accommodative policy supports consumer confidence and"
                " discretionary spending",
            ],
            "headwinds": [],
        },
        "calibrated_tightening": {
            "impact": "headwind",
            "headwinds": [
                "Gradual rate increases put modest pressure on EMI"
                " affordability for entry-level vehicles",
            ],
            "tailwinds": ["Gradual approach limits shock to consumer confidence"],
        },
    },
    "fmcg": {
        "tightening": {
            "impact": "neutral",
            "tailwinds": [
                "FMCG demand is largely inelastic to rate cycles --"
                " consumers do not defer toothpaste",
                "Premium products benefit if GDP growth remains strong"
                " despite tightening",
            ],
            "headwinds": [
                "Higher rates slow rural credit availability, which"
                " can dampen rural FMCG consumption",
                "Working capital costs rise for distribution-heavy" " FMCG models",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable macro supports consistent volume growth across"
                " urban and rural markets",
            ],
            "headwinds": [
                "Input cost inflation (agri commodities, packaging)"
                " remains a sector-specific risk",
            ],
        },
        "accommodative": {
            "impact": "tailwind",
            "tailwinds": [
                "Low rates support rural credit and consumption,"
                " driving FMCG volume in Bharat markets",
                "Consumer confidence is higher in accommodative"
                " environments, supporting premiumisation",
            ],
            "headwinds": [],
        },
        "calibrated_tightening": {
            "impact": "neutral",
            "tailwinds": ["Defensive demand profile limits rate sensitivity"],
            "headwinds": [
                "Marginal rural credit tightening may slow lower-income" " tier volumes"
            ],
        },
    },
    "infra_industrials": {
        "tightening": {
            "impact": "headwind",
            "headwinds": [
                "Higher interest rates directly increase project financing"
                " costs for infrastructure and capital goods",
                "Tighter credit conditions can slow government capex"
                " execution and delay project awards",
                "Rising discount rates compress DCF-based valuations"
                " of long-duration infra assets",
            ],
            "tailwinds": [
                "Strong government infrastructure push provides a"
                " counter-cyclical support to sector order books",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": [
                "Stable rates support project viability for greenfield"
                " and brownfield infrastructure",
                "Government capex pipeline supports industrials order"
                " inflow visibility",
            ],
            "headwinds": [
                "Global commodity price volatility impacts input costs"
                " for cement, steel, and construction",
            ],
        },
        "accommodative": {
            "impact": "tailwind",
            "tailwinds": [
                "Low borrowing costs make infrastructure projects highly"
                " viable, boosting order pipelines",
                "Easy monetary conditions support government and private"
                " capex simultaneously",
                "Strong fiscal multiplier effect on construction and"
                " capital goods demand",
            ],
            "headwinds": [],
        },
        "calibrated_tightening": {
            "impact": "headwind",
            "headwinds": [
                "Gradual rate increases raise project IRR hurdles,"
                " selectively delaying private capex",
            ],
            "tailwinds": ["Public capex remains shielded from rate sensitivity"],
        },
    },
    "diversified": {
        "tightening": {
            "impact": "neutral",
            "tailwinds": ["Strong GDP growth underpins broad corporate earnings"],
            "headwinds": [
                "Higher cost of capital reduces valuation multiples" " across sectors",
                "Tighter liquidity impacts working capital financing",
            ],
        },
        "neutral": {
            "impact": "neutral",
            "tailwinds": ["Stable macro environment supports earnings visibility"],
            "headwinds": ["No specific macro tailwind or headwind identified"],
        },
        "accommodative": {
            "impact": "tailwind",
            "tailwinds": ["Low rates support broad-based growth and valuations"],
            "headwinds": [],
        },
        "calibrated_tightening": {
            "impact": "neutral",
            "tailwinds": ["Gradual normalisation limits disruption"],
            "headwinds": ["Gradual multiple compression risk"],
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a macro economist with 20 years of experience covering Indian equity \
markets. You cut through noise to identify the macro forces that actually \
move stock prices -- RBI rate cycles, inflation trajectories, GDP momentum, \
currency trends, and global spillovers.

Your job is to synthesise pre-computed macro metrics into a concise, \
sector-specific assessment for the investment committee.

RULES:
1. Be specific -- reference the actual RBI repo rate, CPI, and GDP figures.
2. Tailwinds and headwinds must be concrete and sector-relevant.
3. Global factors must reference real macro events (Fed policy, oil prices, \
dollar index, China slowdown risk).
4. India-specific factors must be grounded in the Indian macro data provided.
5. The summary must be 2-3 sentences maximum, written for a Portfolio Manager.
6. Do NOT use markdown, bullet symbols, or headers in your output.
7. Respond ONLY with valid JSON matching the exact schema below.
8. Do not invent numbers. Use only the data provided.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "tailwinds": ["<sector-specific macro tailwind>", ...],
  "headwinds": ["<sector-specific macro headwind>", ...],
  "global_factors": ["<global macro factor>", ...],
  "india_specific": ["<India-specific macro factor>", ...],
  "summary": "<2-3 sentence macro assessment>"
}

Provide 2-4 tailwinds, 2-4 headwinds, 2-3 global_factors, and \
2-3 india_specific factors. Be concrete -- cite RBI rate, CPI, GDP figures \
in your factors where relevant.\
"""

# ---------------------------------------------------------------------------
# Pure classification functions (no I/O, fully unit-testable)
# ---------------------------------------------------------------------------


def _classify_rate_stance(repo_rate: Optional[float]) -> str:
    """
    Map an RBI repo rate to a policy stance label.

    Thresholds based on RBI historical rate cycles:
      < 5.0%            -> 'accommodative'  (e.g. COVID-era 4.0%)
      5.0% to 5.99%     -> 'neutral'
      6.0% to 6.99%     -> 'calibrated_tightening'
      >= 7.0%           -> 'tightening'
      None              -> 'neutral'  (no data available)

    Args:
        repo_rate: RBI repo rate in percent (e.g. 6.5).

    Returns:
        One of: 'accommodative', 'neutral', 'calibrated_tightening',
        'tightening'.
    """
    if repo_rate is None:
        return "neutral"
    if repo_rate < RATE_ACCOMMODATIVE_MAX:
        return "accommodative"
    if repo_rate < RATE_NEUTRAL_MAX:
        return "neutral"
    if repo_rate < RATE_CALIB_TIGHTENING_MAX:
        return "calibrated_tightening"
    return "tightening"


def _classify_rate_direction(repo_rate: Optional[float]) -> str:
    """
    Infer the rate direction from the repo rate level vs neutral midpoint.

    This is a proxy inference, not MPC-minutes parsing. Direction is:
      < neutral midpoint (6.0%) -> 'cutting'
      = neutral midpoint        -> 'holding'
      > neutral midpoint        -> 'hiking'

    Args:
        repo_rate: RBI repo rate in percent.

    Returns:
        One of: 'cutting', 'holding', 'hiking'.
    """
    if repo_rate is None:
        return "holding"
    if repo_rate < RATE_NEUTRAL_MIDPOINT:
        return "cutting"
    if repo_rate == RATE_NEUTRAL_MIDPOINT:
        return "holding"
    return "hiking"


def _classify_inflation_trend(cpi: Optional[float]) -> str:
    """
    Classify CPI inflation as rising, stable, or falling based on level.

    Uses RBI's 2-6% comfort band as reference:
      < CPI_LOW_THRESHOLD (4.0%)  -> 'falling'
      4.0% to 5.99%               -> 'stable'
      >= CPI_ELEVATED_THRESHOLD (6.0%) -> 'rising'
      None                        -> 'stable'  (no data)

    Args:
        cpi: CPI inflation in percent (e.g. 5.1).

    Returns:
        One of: 'falling', 'stable', 'rising'.
    """
    if cpi is None:
        return "stable"
    if cpi < CPI_LOW_THRESHOLD:
        return "falling"
    if cpi < CPI_ELEVATED_THRESHOLD:
        return "stable"
    return "rising"


def _classify_macro_environment(
    repo_rate: Optional[float],
    cpi: Optional[float],
    gdp: Optional[float],
) -> str:
    """
    Classify the overall macro environment for equity investing.

    Logic:
      favourable  -- GDP strong (>= 6.5%) AND CPI benign (< 6%) AND
                     rates not tightening (< 7%)
      unfavourable -- any of: GDP weak (< 5%) OR CPI high (>= 6%) AND
                      rates tightening (>= 7%)
      neutral     -- all other cases (mixed signals)

    Args:
        repo_rate: RBI repo rate (%).
        cpi:       CPI inflation (%).
        gdp:       Real GDP growth (%).

    Returns:
        One of: 'favourable', 'neutral', 'unfavourable'.
    """
    rate = repo_rate if repo_rate is not None else RATE_NEUTRAL_MIDPOINT
    inflation = cpi if cpi is not None else 5.0
    growth = gdp if gdp is not None else GDP_GROWTH_STRONG

    gdp_strong = growth >= GDP_GROWTH_STRONG
    inflation_benign = inflation < CPI_ELEVATED_THRESHOLD
    rates_not_tightening = rate < RATE_CALIB_TIGHTENING_MAX

    gdp_weak = growth < GDP_GROWTH_WEAK
    inflation_high = inflation >= CPI_ELEVATED_THRESHOLD
    rates_tightening = rate >= RATE_CALIB_TIGHTENING_MAX

    if gdp_strong and inflation_benign and rates_not_tightening:
        return "favourable"
    if gdp_weak or (inflation_high and rates_tightening):
        return "unfavourable"
    return "neutral"


def _detect_sector(company_name: str) -> str:
    """
    Infer the company's sector from its name using keyword matching.

    Checks the company name (case-insensitive) against SECTOR_KEYWORDS.
    Returns the first matching sector or DEFAULT_SECTOR if no match found.

    Args:
        company_name: Human-readable company name (e.g. 'HDFC Bank').

    Returns:
        Canonical sector string (e.g. 'banking', 'it_services').
    """
    name_lower = company_name.lower()
    for keywords, sector in SECTOR_KEYWORDS:
        for kw in keywords:
            if kw in name_lower:
                return sector
    return DEFAULT_SECTOR


def _classify_sector_impact(sector: str, rate_stance: str) -> str:
    """
    Look up the macro impact on a sector given the RBI rate stance.

    Uses the _SECTOR_MACRO_RULES lookup table.  Falls back to 'neutral'
    if the sector or stance is not in the table.

    Args:
        sector:      Canonical sector string (from _detect_sector).
        rate_stance: Rate stance string (from _classify_rate_stance).

    Returns:
        One of: 'tailwind', 'neutral', 'headwind'.
    """
    sector_rules = _SECTOR_MACRO_RULES.get(sector, {})
    stance_rules = sector_rules.get(rate_stance, {})
    return stance_rules.get("impact", "neutral")


def _build_tailwinds_headwinds(
    sector: str,
    rate_stance: str,
    cpi: Optional[float],
    gdp: Optional[float],
) -> tuple[list[str], list[str]]:
    """
    Build deterministic tailwinds and headwinds lists from the lookup table.

    Supplements the lookup-table entries with GDP and CPI context lines
    when data is available.

    Args:
        sector:      Canonical sector string.
        rate_stance: Rate stance string.
        cpi:         CPI inflation (%) or None.
        gdp:         Real GDP growth (%) or None.

    Returns:
        Tuple of (tailwinds, headwinds), each a list of strings.
    """
    sector_rules = _SECTOR_MACRO_RULES.get(sector, _SECTOR_MACRO_RULES["diversified"])
    stance_rules = sector_rules.get(rate_stance, sector_rules.get("neutral", {}))

    tailwinds: list[str] = list(stance_rules.get("tailwinds", []))
    headwinds: list[str] = list(stance_rules.get("headwinds", []))

    # Supplement with GDP context
    if gdp is not None:
        if gdp >= GDP_GROWTH_STRONG:
            tailwinds.append(
                f"Strong India GDP growth of {gdp:.1f}% supports broad"
                " corporate earnings and domestic demand"
            )
        elif gdp < GDP_GROWTH_WEAK:
            headwinds.append(
                f"Weak GDP growth of {gdp:.1f}% signals softening"
                " domestic demand and earnings pressure"
            )

    # Supplement with CPI context
    if cpi is not None:
        if cpi >= CPI_ELEVATED_THRESHOLD:
            headwinds.append(
                f"Elevated CPI inflation of {cpi:.1f}% (above RBI's"
                " 6% upper tolerance) constrains MPC room to cut rates"
            )
        elif cpi < CPI_LOW_THRESHOLD:
            tailwinds.append(
                f"Benign CPI inflation of {cpi:.1f}% creates room for"
                " RBI rate cuts, supporting growth and valuations"
            )

    return tailwinds, headwinds


def _build_macro_prompt(
    company_name: str,
    ticker: str,
    sector: str,
    repo_rate: Optional[float],
    cpi: Optional[float],
    gdp: Optional[float],
    rate_stance: str,
    rate_direction: str,
    inflation_trend: str,
    macro_environment: str,
    sector_impact: str,
    tailwinds: list[str],
    headwinds: list[str],
    chroma_snippets: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    """
    Build the user-turn prompt for the LLM synthesis call.

    The LLM receives all pre-computed classifications and metrics.
    It does NOT recompute any labels -- it only synthesises tailwinds,
    headwinds, global factors, India-specific factors, and summary.

    Args:
        company_name:   Human-readable company name.
        ticker:         Yahoo Finance ticker.
        sector:         Detected sector.
        repo_rate:      RBI repo rate (%) or None.
        cpi:            CPI inflation (%) or None.
        gdp:            Real GDP growth (%) or None.
        rate_stance:    Pre-computed rate stance label.
        rate_direction: Pre-computed rate direction label.
        inflation_trend: Pre-computed inflation trend label.
        macro_environment: Pre-computed macro environment label.
        sector_impact:  Pre-computed sector impact label.
        tailwinds:      Pre-computed tailwinds list.
        headwinds:      Pre-computed headwinds list.
        chroma_snippets: ChromaDB semantic search results (may be empty).
        warnings:       Macro tool warnings (e.g. data unavailable).

    Returns:
        Formatted prompt string for the LLM.
    """

    def _fmt(val: Optional[float], suffix: str = "%") -> str:
        return f"{val:.2f}{suffix}" if val is not None else "N/A"

    tw_text = "\n".join(f"  - {t}" for t in tailwinds) or "  None identified"
    hw_text = "\n".join(f"  - {h}" for h in headwinds) or "  None identified"

    lines: list[str] = [
        f"Assess the macro environment for {company_name} ({ticker}).",
        f"Detected sector: {sector}",
        "",
        "PRE-COMPUTED MACRO CLASSIFICATIONS:",
        f"  Rate stance         : {rate_stance}",
        f"  Rate direction      : {rate_direction}",
        f"  Inflation trend     : {inflation_trend}",
        f"  Macro environment   : {macro_environment}",
        f"  Sector impact       : {sector_impact}",
        "",
        "LIVE MACRO DATA (India):",
        f"  RBI repo rate       : {_fmt(repo_rate)}",
        f"  CPI inflation       : {_fmt(cpi)}",
        f"  Real GDP growth     : {_fmt(gdp)}",
        "",
        "PRE-COMPUTED SECTOR TAILWINDS:",
        tw_text,
        "",
        "PRE-COMPUTED SECTOR HEADWINDS:",
        hw_text,
    ]

    if chroma_snippets:
        lines.extend(["", "SECTOR NEWS CONTEXT (ChromaDB):"])
        for snippet in chroma_snippets[:CHROMA_N_RESULTS]:
            doc = snippet.get("document") or ""
            lines.append(f"  {doc[:200]}")

    if warnings:
        lines.extend(["", "DATA WARNINGS:"])
        for w in warnings:
            lines.append(f"  {w}")

    lines.extend(
        [
            "",
            "Using the data above, provide the JSON output per the system"
            " prompt schema. Reference specific RBI, CPI, and GDP figures."
            " Tailwinds and headwinds should supplement the pre-computed"
            " ones above -- you may restate or expand them.",
        ]
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core agent logic (separated from LangGraph node for testability)
# ---------------------------------------------------------------------------


def _run_macro_analysis_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
) -> MacroAnalysis:
    """
    Core agent logic -- fetch macro data, classify, call LLM for synthesis.

    Never raises -- on any failure returns MacroAnalysis with error set.

    Args:
        analysis_id:  UUID of the parent Analysis job.
        company_name: Human-readable company name.
        ticker:       Yahoo Finance ticker (e.g. 'TCS.NS').

    Returns:
        MacroAnalysis Pydantic model (frozen, serialisable).
    """
    # --- Step 1: Fetch macro data
    logger.info(
        "Macro agent: fetching macro data analysis=%s company=%s",
        analysis_id,
        company_name,
    )
    try:
        macro_result = fetch_macro_data.invoke({})
    except Exception as exc:
        logger.exception("fetch_macro_data failed for analysis=%s", analysis_id)
        return MacroAnalysis(
            agent_name="macro_economist",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            macro_environment="neutral",
            sector_impact="neutral",
            error=f"fetch_macro_data failed: {exc}",
        )

    if "error" in macro_result:
        return MacroAnalysis(
            agent_name="macro_economist",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            macro_environment="neutral",
            sector_impact="neutral",
            error=macro_result.get("message", "macro data unavailable"),
        )

    # --- Step 2: Extract headline figures
    repo_rate: Optional[float] = macro_result.get("repo_rate")
    cpi: Optional[float] = macro_result.get("cpi_inflation")
    gdp: Optional[float] = macro_result.get("gdp_growth")
    tool_warnings: list[str] = macro_result.get("warnings", [])

    # --- Step 3: Deterministic classifications
    rate_stance = _classify_rate_stance(repo_rate)
    rate_direction = _classify_rate_direction(repo_rate)
    inflation_trend = _classify_inflation_trend(cpi)
    macro_environment = _classify_macro_environment(repo_rate, cpi, gdp)
    sector = _detect_sector(company_name)
    sector_impact = _classify_sector_impact(sector, rate_stance)
    tailwinds, headwinds = _build_tailwinds_headwinds(sector, rate_stance, cpi, gdp)

    logger.info(
        "Macro agent: sector=%s stance=%s direction=%s env=%s impact=%s",
        sector,
        rate_stance,
        rate_direction,
        macro_environment,
        sector_impact,
    )

    # --- Step 4: ChromaDB sector news search (non-fatal on failure)
    chroma_snippets: list[dict[str, Any]] = []
    try:
        chroma_snippets = semantic_search(
            query=f"{company_name} macro sector outlook interest rate",
            collection_name=COLLECTION_NEWS,
            n_results=CHROMA_N_RESULTS,
            company_filter=company_name,
        )
    except Exception as exc:
        logger.warning("ChromaDB search failed in macro agent (non-fatal): %s", exc)

    # --- Step 5: LLM synthesis
    logger.info(
        "Macro agent: invoking LLM company=%s sector=%s",
        company_name,
        sector,
    )

    llm_tailwinds: list[str] = []
    llm_headwinds: list[str] = []
    summary = ""

    try:
        import json
        import re

        llm = get_llm()
        prompt = _build_macro_prompt(
            company_name=company_name,
            ticker=ticker,
            sector=sector,
            repo_rate=repo_rate,
            cpi=cpi,
            gdp=gdp,
            rate_stance=rate_stance,
            rate_direction=rate_direction,
            inflation_trend=inflation_trend,
            macro_environment=macro_environment,
            sector_impact=sector_impact,
            tailwinds=tailwinds,
            headwinds=headwinds,
            chroma_snippets=chroma_snippets,
            warnings=tool_warnings,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
        cleaned = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed = json.loads(cleaned)

        llm_tailwinds = parsed.get("tailwinds", [])
        llm_headwinds = parsed.get("headwinds", [])
        # global_factors and india_specific captured for debug tracing;
        # MacroAnalysis does not yet expose these fields (Phase 4 enrichment).
        logger.debug(
            "Macro agent LLM global_factors=%s india_specific=%s",
            parsed.get("global_factors", []),
            parsed.get("india_specific", []),
        )
        summary = parsed.get("summary", "")

    except Exception as exc:
        logger.warning("LLM call failed in macro agent for %s: %s", company_name, exc)
        # Fallback: build summary from deterministic data
        rate_str = f"{repo_rate:.2f}%" if repo_rate is not None else "N/A"
        cpi_str = f"{cpi:.1f}%" if cpi is not None else "N/A"
        gdp_str = f"{gdp:.1f}%" if gdp is not None else "N/A"
        summary = (
            f"India macro: {rate_stance} rate environment (repo rate {rate_str}), "
            f"CPI {cpi_str} ({inflation_trend}), GDP growth {gdp_str}. "
            f"Overall environment is {macro_environment}; "
            f"sector ({sector}) macro impact: {sector_impact}. "
            "LLM synthesis unavailable."
        )
        llm_tailwinds = tailwinds
        llm_headwinds = headwinds
        # global_factors / india_specific not used in fallback path either;
        # MacroAnalysis fields reserved for Phase 4 enrichment.

    # Merge deterministic and LLM tailwinds/headwinds (LLM output takes
    # priority; deterministic used as fallback when LLM fails)
    final_tailwinds = llm_tailwinds if llm_tailwinds else tailwinds
    final_headwinds = llm_headwinds if llm_headwinds else headwinds

    # --- Step 6: Build and return MacroAnalysis
    return MacroAnalysis(
        agent_name="macro_economist",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        macro_environment=macro_environment,
        sector_impact=sector_impact,
        rbi_repo_rate_pct=repo_rate,
        rate_stance=rate_stance,
        rate_direction=rate_direction,
        cpi_inflation_pct=cpi,
        inflation_trend=inflation_trend,
        gdp_growth_pct=gdp,
        tailwinds=final_tailwinds,
        headwinds=final_headwinds,
        usd_inr_rate=None,  # not provided by fetch_macro_data; Phase 3 enrich
        inr_trend=None,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


def run_macro_analysis(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the Macro Economist agent.

    Reads from InvestmentState:
      - job_id       -> analysis_id for the output model
      - company_name -> used for sector detection and ChromaDB query
      - ticker       -> Yahoo Finance ticker (e.g. 'TCS.NS')

    Writes to InvestmentState:
      - macro        -> dict representation of MacroAnalysis

    Never raises.  On failure ``macro["error"]`` is non-null.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_macro_analysis called with empty ticker")
        result = MacroAnalysis(
            agent_name="macro_economist",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            macro_environment="neutral",
            sector_impact="neutral",
            error="ticker field is missing from InvestmentState",
        )
        return {"macro": result.model_dump()}

    try:
        result = _run_macro_analysis_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
        )
    except Exception as exc:
        logger.exception(
            "Unhandled error in macro agent node: company=%s", company_name
        )
        result = MacroAnalysis(
            agent_name="macro_economist",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            macro_environment="neutral",
            sector_impact="neutral",
            error=f"Unhandled agent error: {exc}",
        )

    return {"macro": result.model_dump()}
