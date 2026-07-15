# backend/agents/valuation_agent.py
"""
AIRP -- Valuation Agent (T-039)

Persona: rigorous quantitative analyst who values businesses using two
complementary methods: intrinsic value (DCF) and relative value (peer
multiples from Screener.in).  Numbers-first, narrative-second.

Mandate
-------
Produce a ValuationOutput containing:
  * intrinsic_value_per_share   -- DCF-derived value in Rs.
  * current_price               -- live market price in Rs.
  * upside_downside_pct         -- (intrinsic - price) / price * 100
  * valuation_verdict           -- 'undervalued' | 'fairly_valued' | 'overvalued'
  * pe_ratio / sector_avg_pe    -- trailing PE vs sector
  * pb_ratio / sector_avg_pb    -- P/B vs sector
  * ev_ebitda / sector_avg_ev_ebitda
  * peer_tickers                -- tickers used for peer comparison
  * premium_discount_to_peers_pct
  * margin_of_safety            -- 'high' | 'moderate' | 'low' | 'none'
  * dcf_sector_used             -- canonical WACC sector band (T-083)
  * summary                     -- 2-3 sentence PM-ready narrative

Acceptance criteria (T-039):
  * DCF output within 15% of manual calculation for Infosys
  * Peer comparison pulls from Screener.in correctly
  * valuation_verdict is one of 'undervalued', 'fairly_valued', 'overvalued'

Acceptance criteria (T-083 -- sector-aware WACC):
  * _run_dcf accepts a sector-specific WACC (unchanged signature -- the
    caller now resolves a sector-specific value instead of always passing
    the flat DEFAULT_WACC_PCT)
  * Unit tests cover at least 3 sector bands (it_services, fmcg,
    capital_intensive_cyclical) plus the diversified default
  * Existing DCF-dependent tests updated with new expected values

Two-stage pipeline:
  Stage 1 -- Deterministic: DCF + peer multiples from tool data
  Stage 2 -- LLM narrative synthesis of the valuation story

Data sources:
  * fetch_financials  -- FCF series for DCF (yFinance)
  * fetch_ratios      -- PE, PB, EV/EBITDA, market cap (yFinance + AlphaVantage)
  * fetch_stock_price -- current price (yFinance)
  * Screener.in scrape -- sector peer multiples (requests + BeautifulSoup)

Public interface
----------------
  run_valuation_analysis(state)        -> dict   LangGraph node
  _run_valuation_analysis_core(...)    -> ValuationOutput
  _run_dcf(...)                        -> tuple  pure DCF engine
  _fetch_peer_multiples(...)           -> dict   Screener.in peer scrape
  _classify_sector_for_wacc(...)       -> str    pure, unit-testable (T-083)
  _resolve_sector_key(...)             -> str    pure, unit-testable (T-083)
  _get_sector_wacc_pct(...)            -> float  pure, unit-testable (T-083)
  _determine_verdict(...)              -> str    pure verdict logic
  _determine_margin_of_safety(...)     -> str    pure MoS logic
  _build_valuation_prompt(...)         -> str    prompt builder

Design decisions
----------------
* NO ``from __future__ import annotations`` -- breaks Pydantic v2.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``# type: ignore`` -- use cast(), explicit annotations, assert.
* DCF uses only FREE CASH FLOW (not earnings) as the base for projections.
  FCF is taken from fetch_financials (yFinance).
* WACC (T-083) is sector-aware: a canonical sector key is resolved from
  (in priority order) the Screener.in peer scrape's sector label, the
  InvestmentState.sector field, and finally the company name, then looked
  up in SECTOR_WACC_MAP.  The live RBI repo rate then nudges that sector
  base up/down from a neutral policy-rate anchor (6.5%) -- replacing the
  old flat-default + flat-RBI-formula with a sector-specific base plus the
  same macro-cycle adjustment.  Companies that cannot be classified fall
  back to the 'diversified' band, which is pinned to DEFAULT_WACC_PCT so
  pre-T-083 behaviour is preserved exactly when no sector signal exists.
* Peer multiples are scraped from Screener.in company page, not the concalls
  page.  The /company/<slug>/ page has a ratio table that is parsed with
  BeautifulSoup.  If the scrape fails, sector averages fall back to None.
  The sector/industry label (T-083) is extracted best-effort from the same
  page and is likewise non-fatal on failure -- callers fall back to
  InvestmentState.sector or company-name classification.
* Error convention: never raises.  On any failure ValuationOutput.error is
  set and valuation_verdict defaults to 'fairly_valued'.
* In ENVIRONMENT=test (or when network is unavailable), all tool calls are
  mocked by the test suite.  The agent must handle empty-dict responses from
  tools without crashing.
* LangSmith tracing via @traced_agent is automatic.

Usage in LangGraph (Phase 4)
----------------------------
    from backend.agents.valuation_agent import run_valuation_analysis
    builder.add_node("valuation_agent", run_valuation_analysis)
    # Reads:  state["ticker"], state["company_name"], state["job_id"],
    #         state["fundamental"], state["macro"], state["sector"]
    # Writes: state["valuation"]  (ValuationOutput.model_dump())
"""

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import ValuationOutput
from backend.agents.tracing import traced_agent
from backend.tools.financials import fetch_financials
from backend.tools.ratios import fetch_ratios
from backend.tools.stock_price import fetch_stock_price

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DCF model constants
# ---------------------------------------------------------------------------

# Default WACC when macro data / RBI rate is unavailable
# 12% is a reasonable WACC for a mid-cap Indian equity (RBI rate ~6.5% + risk premium)
DEFAULT_WACC_PCT: float = 12.0

# Terminal growth rate: Indian GDP long-run nominal growth
DEFAULT_TERMINAL_GROWTH_PCT: float = 5.0

# Number of years to project FCF
DCF_PROJECTION_YEARS: int = 5

# Upside/downside thresholds for verdict
UNDERVALUED_THRESHOLD_PCT: float = 15.0  # > 15% upside -> undervalued
OVERVALUED_THRESHOLD_PCT: float = -10.0  # > 10% downside -> overvalued

# Peer multiple tolerance: stock is expensive vs peers if premium > this
PEER_PREMIUM_THRESHOLD_PCT: float = 20.0

# ---------------------------------------------------------------------------
# Sector-aware WACC calibration (T-083)
# ---------------------------------------------------------------------------
# A flat 12% WACC systematically undervalues asset-light, low-capex sectors
# (IT services, FMCG) and can equally overstate cash-flow quality for
# capital-intensive, cyclical sectors (auto, energy, infrastructure/metals).
# SECTOR_WACC_MAP replaces the flat default with a per-sector base rate.
# The sector key used to look this up is resolved by _resolve_sector_key()
# -- see that function for the priority order (Screener.in peer scrape >
# InvestmentState.sector > company name).  Companies that cannot be
# classified into a known band fall back to 'diversified', which is pinned
# to DEFAULT_WACC_PCT so pre-T-083 behaviour is preserved exactly when no
# sector signal is available at all.
SECTOR_WACC_MAP: dict[str, float] = {
    "it_services": 10.0,  # asset-light, stable FCF, low leverage
    "fmcg": 10.5,  # stable demand, defensive, low capex intensity
    "capital_intensive_cyclical": 13.0,  # auto/energy/infra/metals/cement
    "diversified": DEFAULT_WACC_PCT,  # unclassified -- preserves pre-T-083 default
}

# Neutral RBI repo rate used as the macro-cycle anchor.  The live repo rate
# nudges the resolved sector base WACC up or down by the same delta -- e.g.
# at the historical neutral rate (6.5%) the sector base applies unchanged;
# a tightening cycle above 6.5% raises WACC for every sector equally, and
# an accommodative cycle below 6.5% lowers it.  This keeps the RBI-driven
# cost-of-capital cycle (the *only* signal before T-083) as a secondary
# adjustment layered on top of the new sector-specific base rate.
NEUTRAL_RBI_REPO_RATE_PCT: float = 6.5

# Screener.in URL pattern for the company page (financial ratios table)
_SCREENER_COMPANY_URL = "{base}/company/{slug}/"

# Browser-like headers to avoid bot blocking
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ---------------------------------------------------------------------------
# Agent persona -- system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Valuation Agent of an investment committee -- a rigorous \
quantitative analyst who values businesses using two complementary lenses: \
intrinsic value (DCF) and relative value (peer multiples).

Your job is to synthesise the deterministic DCF output and peer comparison \
data into a clear, concise narrative that the Portfolio Manager can use when \
writing the final Investment Memo.

RULES:
1. Lead with the intrinsic value and upside/downside percentage.
2. Compare PE, PB, and EV/EBITDA to sector peers explicitly.
3. State the margin of safety clearly.
4. Be specific -- quote the actual numbers from the data provided.
5. 2-3 sentences maximum for the summary.
6. Do NOT use markdown, bullet symbols, or headers in your output.
7. Respond ONLY with valid JSON matching the schema below.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "summary": "<2-3 sentence valuation summary for the Portfolio Manager>"
}"""

# ---------------------------------------------------------------------------
# Helper: company ticker -> Screener.in slug
# ---------------------------------------------------------------------------

# Known overrides (same logic as earnings_transcript.py)
_SLUG_OVERRIDES: dict[str, str] = {
    "tata consultancy services": "TCS",
    "infosys": "INFY",
    "infosys limited": "INFY",
    "reliance industries": "RELIANCE",
    "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK",
    "state bank of india": "SBIN",
    "wipro": "WIPRO",
    "hcl technologies": "HCLTECH",
    "tech mahindra": "TECHM",
    "larsen & toubro": "LT",
    "bajaj finance": "BAJFINANCE",
    "asian paints": "ASIANPAINT",
    "itc": "ITC",
    "kotak mahindra bank": "KOTAKBANK",
}


def _ticker_to_slug(company_name: str, ticker: str) -> str:
    """
    Derive the Screener.in company slug from company name or ticker.

    Strategy (in order):
      1. Hard-coded override table
      2. Strip the exchange suffix from ticker  (TCS.NS -> TCS)
    """
    name_lower = company_name.strip().lower()
    for key, slug in _SLUG_OVERRIDES.items():
        if key in name_lower:
            return slug
    # Fall back: strip exchange suffix
    bare = ticker.split(".")[0].strip().upper()
    return bare if bare else "UNKNOWN"


# ---------------------------------------------------------------------------
# Pure helper: DCF engine
# ---------------------------------------------------------------------------


def _run_dcf(
    fcf_crores_list: list[float],
    revenue_crores_list: list[float],
    shares_outstanding: Optional[float],
    wacc_pct: float,
    terminal_growth_pct: float,
    projection_years: int,
) -> tuple[Optional[float], Optional[float]]:
    """
    Simple 5-year DCF model returning (intrinsic_value_per_share, implied_fcf_crores).

    Algorithm:
      1. Compute average FCF margin from the last 3 years of data.
      2. Use the most recent revenue as the base.
      3. Grow FCF at ``avg_fcf_growth_rate`` (capped at 25%) for N years.
      4. Compute terminal value using the Gordon Growth Model.
      5. Discount all cash flows at WACC.
      6. Divide enterprise value by shares outstanding to get value per share.

    Returns (None, None) when insufficient data is available.

    Args:
        fcf_crores_list:     FCF in crores, most recent first (up to 4 years).
        revenue_crores_list: Revenue in crores, most recent first.
        shares_outstanding:  Number of shares outstanding (not in crores).
        wacc_pct:            WACC as a percentage (e.g. 12.0 for 12%).
        terminal_growth_pct: Terminal growth rate as a percentage.
        projection_years:    Number of years to project (default 5).

    Returns:
        (intrinsic_value_per_share_rs, total_enterprise_value_crores)
        Both None when inputs are insufficient.
    """
    if not fcf_crores_list or not revenue_crores_list:
        return None, None
    if shares_outstanding is None or shares_outstanding <= 0:
        return None, None

    wacc = wacc_pct / 100.0
    tgr = terminal_growth_pct / 100.0

    if wacc <= tgr:
        # WACC must exceed terminal growth for the Gordon model to be valid
        wacc = tgr + 0.05  # enforce minimum spread of 5%

    # --- Base FCF: most recent year ---
    base_fcf = fcf_crores_list[0]
    if base_fcf <= 0:
        # Negative FCF -> use the average of positive FCFs if available
        positive_fcfs = [f for f in fcf_crores_list if f > 0]
        if not positive_fcfs:
            return None, None
        base_fcf = sum(positive_fcfs) / len(positive_fcfs)

    # --- FCF growth rate: average YoY growth, capped at 25% ---
    growth_rate = 0.10  # default 10% if insufficient history
    if len(fcf_crores_list) >= 2:
        valid_pairs = [
            (fcf_crores_list[i], fcf_crores_list[i + 1])
            for i in range(len(fcf_crores_list) - 1)
            if fcf_crores_list[i + 1] > 0 and fcf_crores_list[i] > 0
        ]
        if valid_pairs:
            # YoY rates (current / prior - 1), list is most-recent-first
            yoy_rates = [cur / prior - 1.0 for cur, prior in valid_pairs]
            avg_rate = sum(yoy_rates) / len(yoy_rates)
            growth_rate = max(-0.10, min(0.25, avg_rate))  # cap [-10%, 25%]

    # --- Project FCF and discount ---
    projected_fcf_crores = base_fcf
    total_pv_crores = 0.0
    for year in range(1, projection_years + 1):
        projected_fcf_crores = projected_fcf_crores * (1 + growth_rate)
        discount_factor = (1 + wacc) ** year
        total_pv_crores += projected_fcf_crores / discount_factor

    # --- Terminal value (Gordon Growth Model) ---
    terminal_fcf = projected_fcf_crores * (1 + tgr)
    terminal_value_crores = terminal_fcf / (wacc - tgr)
    pv_terminal_crores = terminal_value_crores / ((1 + wacc) ** projection_years)

    # --- Enterprise value in crores ---
    enterprise_value_crores = total_pv_crores + pv_terminal_crores

    # --- Value per share ---
    # shares_outstanding is in raw units (e.g. 3.6e9)
    # enterprise_value_crores is in crores (1 crore = 1e7)
    enterprise_value_rs = enterprise_value_crores * 1e7  # convert crores to Rs
    intrinsic_value_per_share = enterprise_value_rs / shares_outstanding

    return round(intrinsic_value_per_share, 2), round(enterprise_value_crores, 2)


# ---------------------------------------------------------------------------
# Pure helpers: sector classification for WACC (T-083)
# ---------------------------------------------------------------------------

# Keyword -> canonical WACC sector key.  Checked in order; first match wins.
# Matching is whole-word (regex \b...\b) so short keywords like 'auto'
# cannot match inside unrelated words -- e.g. 'automobile' is listed
# explicitly because a bare word boundary would not match inside it
# ('auto' and 'mobile' are not separated by a non-word character).
_SECTOR_WACC_KEYWORDS: list[tuple[list[str], str]] = [
    (
        [
            "information technology",
            "it services",
            "it - software",
            "software",
            "computers",
        ],
        "it_services",
    ),
    (
        [
            "fmcg",
            "fast moving consumer goods",
            "consumer goods",
        ],
        "fmcg",
    ),
    (
        [
            "auto",
            "automobile",
            "automotive",
            "energy",
            "oil & gas",
            "oil and gas",
            "petroleum",
            "power",
            "infrastructure",
            "infra",
            "cement",
            "steel",
            "metal",
            "metals",
            "construction",
            "industrial",
            "capital goods",
            "engineering",
        ],
        "capital_intensive_cyclical",
    ),
]

DEFAULT_SECTOR_KEY: str = "diversified"


def _classify_sector_for_wacc(text: Optional[str]) -> str:
    """
    Map a free-text sector/industry/company-name string to a canonical
    WACC sector key using whole-word keyword matching.

    Args:
        text: Any human-readable text that might describe a company's
              sector -- e.g. 'Information Technology', 'IT - Software',
              a Screener.in industry label, or a company name.

    Returns:
        One of the keys in SECTOR_WACC_MAP, or DEFAULT_SECTOR_KEY
        ('diversified') when no keyword matches or text is empty/None.
    """
    if not text:
        return DEFAULT_SECTOR_KEY
    text_lower = text.strip().lower()
    if not text_lower:
        return DEFAULT_SECTOR_KEY
    for keywords, sector_key in _SECTOR_WACC_KEYWORDS:
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                return sector_key
    return DEFAULT_SECTOR_KEY


def _resolve_sector_key(
    peer_sector: Optional[str],
    state_sector: Optional[str],
    company_name: str,
) -> str:
    """
    Resolve the canonical WACC sector key from the best available signal.

    Priority (most to least specific):
      1. peer_sector   -- sector/industry label scraped from the
                           Screener.in peer comparison page
                           (peer_data['sector']).
      2. state_sector  -- InvestmentState.sector, set upstream by the
                           Planner / ticker resolver.
      3. company_name  -- keyword-matched as a last resort (catches
                           names like 'XYZ Software Ltd' even with no
                           other signal available).

    Args:
        peer_sector:  Sector label from the Screener.in scrape, if any.
        state_sector: Sector string from InvestmentState, if any.
        company_name: Human-readable company name (always available).

    Returns:
        A key from SECTOR_WACC_MAP.  Returns 'diversified' when none of
        the three signals classify into a known band -- this exactly
        preserves pre-T-083 behaviour (flat DEFAULT_WACC_PCT) for every
        company AIRP could not previously distinguish.
    """
    for candidate in (peer_sector, state_sector, company_name):
        sector_key = _classify_sector_for_wacc(candidate)
        if sector_key != DEFAULT_SECTOR_KEY:
            return sector_key
    return DEFAULT_SECTOR_KEY


def _get_sector_wacc_pct(sector_key: str) -> float:
    """
    Look up the base WACC (%) for a canonical sector key.

    Falls back to DEFAULT_WACC_PCT for any key not present in
    SECTOR_WACC_MAP.  Defensive only -- _resolve_sector_key always
    returns a valid map key, but this keeps the lookup itself safe
    against future callers that pass an arbitrary string.

    Args:
        sector_key: A canonical sector key, typically the return value
                    of _resolve_sector_key().

    Returns:
        WACC as a percentage (e.g. 10.0 for 10%).
    """
    return SECTOR_WACC_MAP.get(sector_key, DEFAULT_WACC_PCT)


# ---------------------------------------------------------------------------
# Pure helpers: verdict and margin of safety
# ---------------------------------------------------------------------------


def _determine_verdict(
    upside_pct: Optional[float],
    pe_premium_pct: Optional[float],
) -> str:
    """
    Determine valuation verdict from DCF upside and PE premium to peers.

    Primary signal: DCF upside/downside.
    Secondary signal: PE premium to sector peers (used as tiebreaker).

    Returns one of: 'undervalued', 'fairly_valued', 'overvalued'.
    """
    if upside_pct is None:
        # No DCF data -- fall back to peer comparison
        if pe_premium_pct is not None:
            if pe_premium_pct > PEER_PREMIUM_THRESHOLD_PCT:
                return "overvalued"
            if pe_premium_pct < -PEER_PREMIUM_THRESHOLD_PCT:
                return "undervalued"
        return "fairly_valued"

    if upside_pct >= UNDERVALUED_THRESHOLD_PCT:
        return "undervalued"
    if upside_pct <= OVERVALUED_THRESHOLD_PCT:
        return "overvalued"
    return "fairly_valued"


def _determine_margin_of_safety(upside_pct: Optional[float]) -> Optional[str]:
    """
    Classify margin of safety from the upside percentage.

    Bands:
      > 30%       -> 'high'
      15% to 30%  -> 'moderate'
      0% to 15%   -> 'low'
      <= 0%       -> 'none'
      None        -> None (insufficient data)
    """
    if upside_pct is None:
        return None
    if upside_pct > 30:
        return "high"
    if upside_pct > 15:
        return "moderate"
    if upside_pct > 0:
        return "low"
    return "none"


# ---------------------------------------------------------------------------
# Screener.in peer multiples scraper
# ---------------------------------------------------------------------------


def _fetch_peer_multiples(
    company_name: str,
    ticker: str,
    base_url: str,
) -> dict[str, Any]:
    """
    Scrape the Screener.in company page to extract sector peer multiples.

    The Screener.in company page (/company/<slug>/) contains a ratio table
    with the company's own ratios.  We also parse the peer comparison table
    when present.

    Returns a dict with keys (all Optional[float] or list):
      pe_ratio, pb_ratio, ev_ebitda       -- company's own ratios from page
      peer_tickers                        -- list of peer ticker symbols
      sector_avg_pe, sector_avg_pb, sector_avg_ev_ebitda

    On any error, returns an empty dict (caller handles gracefully).
    """
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415
        import requests  # noqa: PLC0415 -- lazy import, not in all envs
    except ImportError:
        logger.warning("requests or bs4 not available -- skipping Screener scrape")
        return {}

    slug = _ticker_to_slug(company_name, ticker)
    url = _SCREENER_COMPANY_URL.format(base=base_url.rstrip("/"), slug=slug)
    logger.info("Valuation: scraping Screener.in slug=%s url=%s", slug, url)

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Screener.in fetch failed for %s: %s", slug, exc)
        return {}

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        return _parse_screener_page(soup, slug)
    except Exception as exc:
        logger.warning("Screener.in parse failed for %s: %s", slug, exc)
        return {}


def _parse_float(text: str) -> Optional[float]:
    """Extract a float from a Screener.in table cell string."""
    cleaned = re.sub(r"[^\d.\-]", "", text.strip())
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_sector_from_page(soup: Any) -> Optional[str]:
    """
    Best-effort extraction of the company's sector/industry label from the
    Screener.in company page (T-083).

    Screener.in does not expose a single stable selector for this across
    page layouts, so a few plausible locations are tried in order:
      1. The '#peers' section heading, which often reads something like
         "Peer comparison ... Sector: <label>".
      2. A breadcrumb-style link in the '.sub' element near the company
         name, containing a non-exchange label (i.e. not 'NSE:' / 'BSE:').
      3. A <meta name="industry"> tag, when present.

    This is intentionally hedged: unlike the ratio tables (which have a
    stable, well-known id), sector/industry placement varies by page
    template.  Returns None if no label can be found -- callers must
    treat this as a soft signal only and fall back to
    InvestmentState.sector or company-name classification (see
    _resolve_sector_key).

    Args:
        soup: Parsed BeautifulSoup document for the company page.

    Returns:
        A free-text sector/industry label, or None if not found.
    """
    # 1. Peers section heading -- "Peer comparison ... Sector: <label>"
    peers_section = soup.find(id="peers")
    if peers_section:
        heading = peers_section.find(["h2", "h3"])
        if heading:
            heading_text: str = str(heading.get_text(" ", strip=True))
            match = re.search(r"sector\s*[:\-]\s*(.+)$", heading_text, re.IGNORECASE)
            if match:
                label: str = match.group(1).strip()
                if label:
                    return label

    # 2. Breadcrumb-style sub-header near the company name
    sub = soup.find(class_="sub")
    if sub:
        for link in sub.find_all("a"):
            link_text: str = str(link.get_text(strip=True))
            if link_text and not link_text.upper().startswith(("NSE", "BSE")):
                return link_text

    # 3. <meta name="industry"> tag, when present
    meta = soup.find("meta", attrs={"name": "industry"})
    if meta is not None:
        content = meta.get("content")
        if content:
            content_str = str(content).strip()
            if content_str:
                return content_str

    return None


def _parse_screener_page(soup: Any, slug: str) -> dict[str, Any]:
    """
    Parse the Screener.in company page HTML to extract ratio data.

    Screener.in renders a #top-ratios section with individual li elements
    like: <li><span class="name">Stock P/E</span><span class="value">28.5</span></li>

    Peer comparison tables (section id="peers") are also parsed when present.
    The company's sector/industry label is extracted best-effort (T-083)
    and returned under the 'sector' key -- see _extract_sector_from_page.
    """
    result: dict[str, Any] = {}

    sector_label = _extract_sector_from_page(soup)
    if sector_label:
        result["sector"] = sector_label

    # --- Parse company's own ratios from the top-ratios section ---
    ratio_map: dict[str, str] = {
        "stock p/e": "pe_ratio",
        "price to book": "pb_ratio",
        "ev / ebitda": "ev_ebitda",
    }

    top_ratios = soup.find(id="top-ratios")
    if top_ratios:
        for li in top_ratios.find_all("li"):
            name_span = li.find(class_="name")
            val_span = li.find(class_="value")
            if not name_span or not val_span:
                continue
            name_lower = name_span.get_text(strip=True).lower()
            for key, field in ratio_map.items():
                if key in name_lower:
                    val = _parse_float(val_span.get_text(strip=True))
                    if val is not None:
                        result[field] = val

    # --- Parse peers table for sector averages ---
    peers_section = soup.find(id="peers")
    peer_pes: list[float] = []
    peer_pbs: list[float] = []
    peer_tickers: list[str] = []

    if peers_section:
        rows = peers_section.find_all("tr")
        # First row is header; subsequent rows are peers
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            # First cell: company name link -- extract ticker from href
            link = cells[0].find("a")
            if link and link.get("href"):
                href = str(link.get("href", ""))
                # href pattern: /company/TCS/ -> extract TCS
                parts = [p for p in href.strip("/").split("/") if p]
                if parts:
                    peer_slug = parts[-1].upper()
                    if peer_slug != slug.upper():
                        peer_tickers.append(peer_slug + ".NS")

            # Try to parse PE from a later column (column index varies by page)
            for cell in cells[2:6]:
                val = _parse_float(cell.get_text(strip=True))
                if val is not None and 1 < val < 300:
                    peer_pes.append(val)
                    break

    if peer_pes:
        result["sector_avg_pe"] = round(sum(peer_pes) / len(peer_pes), 2)
    if peer_pbs:
        result["sector_avg_pb"] = round(sum(peer_pbs) / len(peer_pbs), 2)
    if peer_tickers:
        result["peer_tickers"] = peer_tickers[:6]  # cap at 6

    return result


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_valuation_prompt(
    company_name: str,
    ticker: str,
    current_price: Optional[float],
    intrinsic_value: Optional[float],
    upside_pct: Optional[float],
    verdict: str,
    margin_of_safety: Optional[str],
    pe_ratio: Optional[float],
    sector_avg_pe: Optional[float],
    pb_ratio: Optional[float],
    sector_avg_pb: Optional[float],
    ev_ebitda: Optional[float],
    sector_avg_ev_ebitda: Optional[float],
    wacc_pct: float,
    terminal_growth_pct: float,
    peer_tickers: list[str],
    premium_discount_pct: Optional[float],
) -> str:
    """
    Build the user-turn prompt sent to the LLM for narrative synthesis.
    """

    def _fmt(val: Optional[float], suffix: str = "") -> str:
        if val is None:
            return "N/A"
        return f"{val:,.2f}{suffix}"

    peer_str = ", ".join(peer_tickers[:5]) if peer_tickers else "N/A"
    upside_str = _fmt(upside_pct, "%")
    if upside_pct is not None and upside_pct > 0:
        upside_str = f"+{upside_str}"

    return f"""Write a valuation summary for {company_name} ({ticker}).

DCF VALUATION:
  Current price       : Rs. {_fmt(current_price)}
  Intrinsic value     : Rs. {_fmt(intrinsic_value)}
  Upside / downside   : {upside_str}
  WACC used           : {_fmt(wacc_pct, '%')}
  Terminal growth     : {_fmt(terminal_growth_pct, '%')}
  Verdict             : {verdict.upper().replace('_', ' ')}
  Margin of safety    : {margin_of_safety or 'N/A'}

RELATIVE VALUATION (vs peers):
  Trailing PE         : {_fmt(pe_ratio)}x  |  Sector avg: {_fmt(sector_avg_pe)}x
  Price/Book          : {_fmt(pb_ratio)}x  |  Sector avg: {_fmt(sector_avg_pb)}x
  EV/EBITDA           : {_fmt(ev_ebitda)}x  |  Sector avg: {_fmt(sector_avg_ev_ebitda)}x
  Premium to peers    : {_fmt(premium_discount_pct, '%')}
  Peers used          : {peer_str}

Write 2-3 sentences that synthesise both the DCF and peer comparison \
into a single verdict for the Portfolio Manager. \
Respond ONLY with the JSON schema: {{"summary": "<text>"}}"""


# ---------------------------------------------------------------------------
# Core agent logic
# ---------------------------------------------------------------------------


def _run_valuation_analysis_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
    sector: Optional[str],
    fundamental: dict[str, Any],
    macro: dict[str, Any],
    screener_base_url: str,
) -> ValuationOutput:
    """
    Core Valuation Agent logic.

    Stage 1: Deterministic -- fetch financials, ratios, price; run DCF;
             scrape Screener.in for peer multiples.
    Stage 2: LLM -- synthesise narrative summary.

    Never raises.  On any failure returns ValuationOutput with error set.

    Args:
        analysis_id:        UUID of the parent Analysis job.
        company_name:       Human-readable company name.
        ticker:             Yahoo Finance ticker (e.g. 'INFY.NS').
        sector:             Optional sector string from state.
        fundamental:        FundamentalAnalysis.model_dump() dict (may be {}).
        macro:              MacroAnalysis.model_dump() dict (may be {}).
        screener_base_url:  Screener.in base URL from config.

    Returns:
        ValuationOutput Pydantic model (frozen, serialisable).
    """
    logger.info(
        "Valuation: starting analysis ticker=%s analysis=%s",
        ticker,
        analysis_id,
    )

    # --- Stage 1a: Fetch financial statements (FCF series for DCF) -------
    logger.info("Valuation: fetching financials ticker=%s", ticker)
    financials: dict[str, Any] = {}
    try:
        raw_fin = fetch_financials.invoke({"ticker": ticker})
        if isinstance(raw_fin, dict) and "error" not in raw_fin:
            financials = raw_fin
        else:
            logger.warning(
                "fetch_financials returned error for %s: %s",
                ticker,
                raw_fin.get("message") if isinstance(raw_fin, dict) else raw_fin,
            )
    except Exception as exc:
        logger.warning("fetch_financials failed for %s: %s", ticker, exc)

    # --- Stage 1b: Fetch ratios (PE, PB, EV/EBITDA, shares outstanding) --
    logger.info("Valuation: fetching ratios ticker=%s", ticker)
    ratios: dict[str, Any] = {}
    try:
        raw_rat = fetch_ratios.invoke({"ticker": ticker})
        if isinstance(raw_rat, dict) and "error" not in raw_rat:
            ratios = raw_rat
        else:
            logger.warning(
                "fetch_ratios returned error for %s: %s",
                ticker,
                raw_rat.get("message") if isinstance(raw_rat, dict) else raw_rat,
            )
    except Exception as exc:
        logger.warning("fetch_ratios failed for %s: %s", ticker, exc)

    # --- Stage 1c: Fetch current price ------------------------------------
    logger.info("Valuation: fetching stock price ticker=%s", ticker)
    current_price: Optional[float] = None
    try:
        price_result = fetch_stock_price.invoke({"ticker": ticker, "period": "1y"})
        if isinstance(price_result, dict) and "error" not in price_result:
            current_price_raw: Any = price_result.get("current_price")
            if current_price_raw is not None:
                current_price = float(current_price_raw)
    except Exception as exc:
        logger.warning("fetch_stock_price failed for %s: %s", ticker, exc)

    # Fall back to ratios price field if stock price call failed
    if current_price is None:
        price_raw: Any = ratios.get("price")
        if price_raw is not None:
            try:
                current_price = float(price_raw)
            except (TypeError, ValueError):
                pass

    # --- Stage 1d: Extract FCF series and shares for DCF ------------------
    income_stmt: list[dict[str, Any]] = financials.get("income_statement", []) or []
    cash_flow: list[dict[str, Any]] = financials.get("cash_flow", []) or []

    fcf_list: list[float] = []
    for cf in cash_flow:
        val: Any = cf.get("free_cash_flow_crores")
        if val is not None:
            try:
                fcf_list.append(float(val))
            except (TypeError, ValueError):
                pass

    revenue_list: list[float] = []
    for inc in income_stmt:
        val2: Any = inc.get("revenue_crores")
        if val2 is not None:
            try:
                revenue_list.append(float(val2))
            except (TypeError, ValueError):
                pass

    shares_raw: Any = ratios.get("shares_outstanding")
    shares_outstanding: Optional[float] = None
    if shares_raw is not None:
        try:
            shares_outstanding = float(shares_raw)
        except (TypeError, ValueError):
            pass

    # --- Stage 1e: Scrape Screener.in for peer multiples -----------------
    # Moved ahead of the WACC/DCF stages (T-083) -- the sector/industry
    # label scraped here is now the primary signal for sector-aware WACC.
    logger.info("Valuation: scraping Screener.in for peer data")
    peer_data: dict[str, Any] = {}
    try:
        peer_data = _fetch_peer_multiples(company_name, ticker, screener_base_url)
    except Exception as exc:
        logger.warning("Screener.in peer scrape failed for %s: %s", ticker, exc)

    # --- Stage 1f: Resolve sector and determine WACC (T-083) --------------
    peer_sector_raw: Any = peer_data.get("sector")
    peer_sector: Optional[str] = (
        str(peer_sector_raw) if peer_sector_raw is not None else None
    )

    sector_key = _resolve_sector_key(
        peer_sector=peer_sector,
        state_sector=sector,
        company_name=company_name,
    )
    wacc_pct: float = _get_sector_wacc_pct(sector_key)

    rbi_rate_raw: Any = macro.get("rbi_repo_rate_pct")
    if rbi_rate_raw is not None:
        try:
            rbi_rate = float(rbi_rate_raw)
            # RBI rate cycle nudges the sector base WACC up/down from the
            # neutral policy-rate anchor -- a tightening cycle raises the
            # cost of capital for every sector, not just the one detected.
            rbi_delta_pct = rbi_rate - NEUTRAL_RBI_REPO_RATE_PCT
            wacc_pct = round(wacc_pct + rbi_delta_pct, 1)
        except (TypeError, ValueError):
            pass

    logger.info(
        "Valuation: sector=%s wacc_pct=%.1f ticker=%s",
        sector_key,
        wacc_pct,
        ticker,
    )

    terminal_growth_pct: float = DEFAULT_TERMINAL_GROWTH_PCT

    # --- Stage 1g: Run DCF -------------------------------------------------
    intrinsic_value, _ev_crores = _run_dcf(
        fcf_crores_list=fcf_list,
        revenue_crores_list=revenue_list,
        shares_outstanding=shares_outstanding,
        wacc_pct=wacc_pct,
        terminal_growth_pct=terminal_growth_pct,
        projection_years=DCF_PROJECTION_YEARS,
    )

    # --- Stage 1h: Compute upside/downside ---------------------------------
    upside_pct: Optional[float] = None
    if intrinsic_value is not None and current_price is not None and current_price > 0:
        upside_pct = round((intrinsic_value - current_price) / current_price * 100, 2)

    # --- Stage 1i: Extract company ratios -----------------------------------
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None

    pe_raw: Any = ratios.get("pe_ratio")
    if pe_raw is not None:
        try:
            pe_ratio = float(pe_raw)
        except (TypeError, ValueError):
            pass

    pb_raw: Any = ratios.get("pb_ratio")
    if pb_raw is not None:
        try:
            pb_ratio = float(pb_raw)
        except (TypeError, ValueError):
            pass

    ev_raw: Any = ratios.get("ev_to_ebitda")
    if ev_raw is not None:
        try:
            ev_ebitda = float(ev_raw)
        except (TypeError, ValueError):
            pass

    # --- Stage 1j: Incorporate peer data (sector averages + overrides) ----
    sector_avg_pe: Optional[float] = None
    sector_avg_pb: Optional[float] = None
    sector_avg_ev_ebitda: Optional[float] = None
    peer_tickers: list[str] = []

    pe_avg_raw: Any = peer_data.get("sector_avg_pe")
    if pe_avg_raw is not None:
        try:
            sector_avg_pe = float(pe_avg_raw)
        except (TypeError, ValueError):
            pass

    pb_avg_raw: Any = peer_data.get("sector_avg_pb")
    if pb_avg_raw is not None:
        try:
            sector_avg_pb = float(pb_avg_raw)
        except (TypeError, ValueError):
            pass

    ev_avg_raw: Any = peer_data.get("sector_avg_ev_ebitda")
    if ev_avg_raw is not None:
        try:
            sector_avg_ev_ebitda = float(ev_avg_raw)
        except (TypeError, ValueError):
            pass

    peer_tickers_raw: Any = peer_data.get("peer_tickers")
    if isinstance(peer_tickers_raw, list):
        peer_tickers = [str(t) for t in peer_tickers_raw]

    # Peer PE from the Screener page may override ratios PE
    screener_pe_raw: Any = peer_data.get("pe_ratio")
    if screener_pe_raw is not None and pe_ratio is None:
        try:
            pe_ratio = float(screener_pe_raw)
        except (TypeError, ValueError):
            pass

    screener_pb_raw: Any = peer_data.get("pb_ratio")
    if screener_pb_raw is not None and pb_ratio is None:
        try:
            pb_ratio = float(screener_pb_raw)
        except (TypeError, ValueError):
            pass

    screener_ev_raw: Any = peer_data.get("ev_ebitda")
    if screener_ev_raw is not None and ev_ebitda is None:
        try:
            ev_ebitda = float(screener_ev_raw)
        except (TypeError, ValueError):
            pass

    # --- Stage 1k: PE premium/discount to peers ----------------------------
    premium_discount_pct: Optional[float] = None
    if pe_ratio is not None and sector_avg_pe is not None and sector_avg_pe > 0:
        premium_discount_pct = round(
            (pe_ratio - sector_avg_pe) / sector_avg_pe * 100, 2
        )

    # --- Stage 1l: Verdict and margin of safety -----------------------------
    verdict = _determine_verdict(upside_pct, premium_discount_pct)
    margin_of_safety = _determine_margin_of_safety(upside_pct)

    # --- Stage 2: LLM narrative synthesis ---------------------------------
    logger.info("Valuation: invoking LLM for narrative ticker=%s", ticker)
    summary: str = ""

    try:
        llm = get_llm()
        prompt = _build_valuation_prompt(
            company_name=company_name,
            ticker=ticker,
            current_price=current_price,
            intrinsic_value=intrinsic_value,
            upside_pct=upside_pct,
            verdict=verdict,
            margin_of_safety=margin_of_safety,
            pe_ratio=pe_ratio,
            sector_avg_pe=sector_avg_pe,
            pb_ratio=pb_ratio,
            sector_avg_pb=sector_avg_pb,
            ev_ebitda=ev_ebitda,
            sector_avg_ev_ebitda=sector_avg_ev_ebitda,
            wacc_pct=wacc_pct,
            terminal_growth_pct=terminal_growth_pct,
            peer_tickers=peer_tickers,
            premium_discount_pct=premium_discount_pct,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text: str = (
            response.content if hasattr(response, "content") else str(response)
        )
        cleaned: str = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed: dict[str, Any] = json.loads(cleaned)
        summary = str(parsed.get("summary") or "").strip()

    except Exception as exc:
        logger.exception("LLM call failed in Valuation Agent for %s: %s", ticker, exc)
        # Build a fallback summary from the deterministic data
        if intrinsic_value is not None and current_price is not None:
            upside_sign = "+" if (upside_pct or 0) > 0 else ""
            summary = (
                f"{company_name} has a DCF intrinsic value of "
                f"Rs. {intrinsic_value:,.0f} vs current price of "
                f"Rs. {current_price:,.0f} "
                f"({upside_sign}{upside_pct or 0:.1f}% "
                f"{'upside' if (upside_pct or 0) > 0 else 'downside'}). "
                f"Valuation verdict: {verdict.replace('_', ' ')}. "
                f"LLM synthesis unavailable -- review DCF assumptions manually."
            )
        else:
            summary = (
                f"Insufficient financial data to complete DCF valuation for "
                f"{company_name}.  Valuation verdict defaulted to "
                f"{verdict.replace('_', ' ')} based on available peer data."
            )

    return ValuationOutput(
        agent_name="valuation_agent",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        intrinsic_value_per_share=intrinsic_value,
        current_price=current_price,
        upside_downside_pct=upside_pct,
        valuation_verdict=verdict,
        dcf_wacc_pct=wacc_pct,
        dcf_terminal_growth_pct=terminal_growth_pct,
        dcf_projection_years=DCF_PROJECTION_YEARS,
        dcf_sector_used=sector_key,
        pe_ratio=pe_ratio,
        sector_avg_pe=sector_avg_pe,
        pb_ratio=pb_ratio,
        sector_avg_pb=sector_avg_pb,
        ev_ebitda=ev_ebitda,
        sector_avg_ev_ebitda=sector_avg_ev_ebitda,
        peer_tickers=peer_tickers,
        premium_discount_to_peers_pct=premium_discount_pct,
        margin_of_safety=margin_of_safety,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


@traced_agent("valuation_agent")
def run_valuation_analysis(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the Valuation Agent.

    Reads from InvestmentState:
      - job_id        -> analysis_id
      - company_name  -> human-readable company name
      - ticker        -> Yahoo Finance ticker
      - sector        -> Optional sector string (used for peer classification)
      - fundamental   -> FundamentalAnalysis.model_dump() (may be None)
      - macro         -> MacroAnalysis.model_dump() (may be None)

    Writes to InvestmentState:
      - valuation     -> ValuationOutput.model_dump()

    Never raises -- on failure, ``valuation["error"]`` is set.

    Args:
        state: InvestmentState dict (LangGraph passes the full state).

    Returns:
        Dict with key 'valuation'.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_valuation_analysis called with empty ticker")
        result = ValuationOutput(
            agent_name="valuation_agent",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            valuation_verdict="fairly_valued",
            error="ticker field is missing from InvestmentState",
        )
        return {"valuation": result.model_dump()}

    sector_raw: Any = state.get("sector")
    sector: Optional[str] = str(sector_raw) if sector_raw is not None else None

    fundamental: dict[str, Any] = dict(state.get("fundamental") or {})
    macro: dict[str, Any] = dict(state.get("macro") or {})

    # Resolve Screener.in base URL from config (graceful fallback)
    screener_base_url: str = "https://www.screener.in"
    try:
        from backend.config import settings as _cfg  # noqa: PLC0415

        screener_base_url = _cfg.screener_base_url
    except Exception:
        pass

    try:
        result = _run_valuation_analysis_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            sector=sector,
            fundamental=fundamental,
            macro=macro,
            screener_base_url=screener_base_url,
        )
    except Exception as exc:
        logger.exception("Unhandled error in Valuation Agent node: ticker=%s", ticker)
        result = ValuationOutput(
            agent_name="valuation_agent",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            valuation_verdict="fairly_valued",
            error=f"Unhandled agent error: {exc}",
        )

    return {"valuation": result.model_dump()}
