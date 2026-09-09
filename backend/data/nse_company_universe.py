# backend/data/nse_company_universe.py
"""
AIRP -- NSE company universe for the company-search endpoint (B5)

Root cause this closes: frontend/src/components/analysis/CompanyAutocomplete.tsx
was backed entirely by frontend/src/data/nseTop50.ts, a hand-maintained
51-entry list -- so the browsable/searchable dropdown was hard-capped at
50 companies no matter how the person searched (bug #5). This module is
the backend half of the fix: a much larger (~280-company), curated
static universe spanning large- and mid-cap NSE-listed names across
every major sector (banking/NBFC/insurance, IT, energy, metals, auto,
pharma, FMCG, cement/infra, telecom, chemicals, textiles, new-age tech,
aviation/logistics, defense/PSU, real estate, and diversified
industrials), served through GET /api/v1/companies/search
(backend/routers/companies.py) -- a real, paginated, ranked search
endpoint rather than a client-side array filter, so CompanyAutocomplete
can page/virtualize through however many results actually match.

Why a curated static list, not a live "every NSE/BSE symbol" pull
------------------------------------------------------------------------
There is no free, key-less "list every NSE/BSE-listed symbol" API this
project's stack already integrates with (see nseTop50.ts's own
docstring for the identical constraint it already documents for its
smaller list), and NSE's own website is unreachable from this
project's build/dev environment. This dataset is the same kind of
pragmatic, zero-cost, hand-maintained snapshot nseTop50.ts already was
-- just roughly 5-6x larger -- compiled from general knowledge of
large- and mid-cap NSE-listed companies, NOT a live market-cap ranking
or an exhaustive symbol master file. A company can rename, delist, get
acquired, or IPO after this file was written; entries here are believed
correct as of authoring but are not guaranteed current. If a future
data source becomes available (e.g. an official NSE/BSE equity list
export), swap the ``NSE_COMPANY_UNIVERSE`` list below for one built
from it -- ``backend/services/company_search.py`` and everything
downstream of it consume only ``CompanyEntry`` triples and need no
other change.

``ticker`` always carries the Yahoo Finance ``.NS`` suffix, the exact
shape ``frontend/src/data/nseTop50.ts``'s own entries already use and
that ``AnalysisStartRequest.ticker`` / ``DocumentUploadRequest`` expect
when a caller supplies an exact symbol.

Public API
----------
    from backend.data.nse_company_universe import CompanyEntry, NSE_COMPANY_UNIVERSE
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CompanyEntry", "NSE_COMPANY_UNIVERSE"]


@dataclass(frozen=True)
class CompanyEntry:
    """One searchable (name, ticker, exchange) triple."""

    name: str
    ticker: str
    exchange: str


#: (display name, bare NSE symbol) pairs, grouped by sector purely for
#: this file's own readability/maintainability -- the grouping carries
#: no runtime meaning. Duplicates across groups (a company that could
#: reasonably sit in more than one sector) are removed when
#: NSE_COMPANY_UNIVERSE is built below, keyed by ticker.
_RAW_ENTRIES: list[tuple[str, str]] = [
    # --- Banking ---------------------------------------------------------
    ("HDFC Bank", "HDFCBANK"),
    ("ICICI Bank", "ICICIBANK"),
    ("State Bank of India", "SBIN"),
    ("Kotak Mahindra Bank", "KOTAKBANK"),
    ("Axis Bank", "AXISBANK"),
    ("IndusInd Bank", "INDUSINDBK"),
    ("Bank of Baroda", "BANKBARODA"),
    ("Punjab National Bank", "PNB"),
    ("Canara Bank", "CANBK"),
    ("Union Bank of India", "UNIONBANK"),
    ("IDFC First Bank", "IDFCFIRSTB"),
    ("Federal Bank", "FEDERALBNK"),
    ("Bandhan Bank", "BANDHANBNK"),
    ("AU Small Finance Bank", "AUBANK"),
    ("City Union Bank", "CUB"),
    ("RBL Bank", "RBLBANK"),
    ("Yes Bank", "YESBANK"),
    ("Bank of India", "BANKINDIA"),
    ("Indian Bank", "INDIANB"),
    ("Karur Vysya Bank", "KARURVYSYA"),
    ("South Indian Bank", "SOUTHBANK"),
    # --- NBFC / Insurance / Asset management ------------------------------
    ("Bajaj Finance", "BAJFINANCE"),
    ("Bajaj Finserv", "BAJAJFINSV"),
    ("Bajaj Holdings & Investment", "BAJAJHLDNG"),
    ("HDFC Life Insurance", "HDFCLIFE"),
    ("SBI Life Insurance", "SBILIFE"),
    ("ICICI Prudential Life Insurance", "ICICIPRULI"),
    ("ICICI Lombard General Insurance", "ICICIGI"),
    ("Life Insurance Corporation of India", "LICI"),
    ("Shriram Finance", "SHRIRAMFIN"),
    ("Cholamandalam Investment and Finance", "CHOLAFIN"),
    ("Muthoot Finance", "MUTHOOTFIN"),
    ("Manappuram Finance", "MANAPPURAM"),
    ("PNB Housing Finance", "PNBHOUSING"),
    ("LIC Housing Finance", "LICHSGFIN"),
    ("Power Finance Corporation", "PFC"),
    ("REC Limited", "RECLTD"),
    ("HDFC Asset Management Company", "HDFCAMC"),
    ("Nippon Life India Asset Management", "NAM-INDIA"),
    ("UTI Asset Management Company", "UTIAMC"),
    ("Aditya Birla Sun Life AMC", "ABSLAMC"),
    ("Poonawalla Fincorp", "POONAWALLA"),
    ("IIFL Finance", "IIFL"),
    ("Multi Commodity Exchange of India", "MCX"),
    ("Central Depository Services (India)", "CDSL"),
    ("BSE Limited", "BSE"),
    ("Angel One", "ANGELONE"),
    ("Computer Age Management Services", "CAMS"),
    ("General Insurance Corporation of India", "GICRE"),
    ("New India Assurance Company", "NIACL"),
    ("Star Health and Allied Insurance", "STARHEALTH"),
    ("360 One WAM", "360ONE"),
    # --- IT / Technology --------------------------------------------------
    ("Tata Consultancy Services", "TCS"),
    ("Infosys", "INFY"),
    ("HCL Technologies", "HCLTECH"),
    ("Wipro", "WIPRO"),
    ("Tech Mahindra", "TECHM"),
    ("LTIMindtree", "LTIM"),
    ("Persistent Systems", "PERSISTENT"),
    ("Coforge", "COFORGE"),
    ("Mphasis", "MPHASIS"),
    ("L&T Technology Services", "LTTS"),
    ("Oracle Financial Services Software", "OFSS"),
    ("Tata Elxsi", "TATAELXSI"),
    ("KPIT Technologies", "KPITTECH"),
    ("Zensar Technologies", "ZENSARTECH"),
    ("Cyient", "CYIENT"),
    ("Birlasoft", "BSOFT"),
    ("Happiest Minds Technologies", "HAPPSTMNDS"),
    ("Sonata Software", "SONATSOFTW"),
    ("Newgen Software Technologies", "NEWGEN"),
    ("Firstsource Solutions", "FSL"),
    ("Latent View Analytics", "LATENTVIEW"),
    # --- Energy / Oil & Gas / Power -----------------------------------
    ("Reliance Industries", "RELIANCE"),
    ("Oil and Natural Gas Corporation", "ONGC"),
    ("Indian Oil Corporation", "IOC"),
    ("Bharat Petroleum Corporation", "BPCL"),
    ("Hindustan Petroleum Corporation", "HINDPETRO"),
    ("GAIL (India)", "GAIL"),
    ("NTPC", "NTPC"),
    ("Power Grid Corporation of India", "POWERGRID"),
    ("Tata Power Company", "TATAPOWER"),
    ("Adani Power", "ADANIPOWER"),
    ("Adani Green Energy", "ADANIGREEN"),
    ("Adani Energy Solutions", "ADANIENSOL"),
    ("Adani Total Gas", "ATGL"),
    ("JSW Energy", "JSWENERGY"),
    ("NHPC", "NHPC"),
    ("SJVN", "SJVN"),
    ("Coal India", "COALINDIA"),
    ("Oil India", "OIL"),
    ("Petronet LNG", "PETRONET"),
    ("Indraprastha Gas", "IGL"),
    ("Mahanagar Gas", "MGL"),
    ("Gujarat Gas", "GUJGASLTD"),
    ("Torrent Power", "TORNTPOWER"),
    ("CESC", "CESC"),
    # --- Metals & Mining ----------------------------------------------
    ("Tata Steel", "TATASTEEL"),
    ("JSW Steel", "JSWSTEEL"),
    ("Hindalco Industries", "HINDALCO"),
    ("Vedanta", "VEDL"),
    ("Jindal Steel & Power", "JINDALSTEL"),
    ("Steel Authority of India", "SAIL"),
    ("NMDC", "NMDC"),
    ("Hindustan Zinc", "HINDZINC"),
    ("National Aluminium Company", "NATIONALUM"),
    ("APL Apollo Tubes", "APLAPOLLO"),
    ("Ratnamani Metals & Tubes", "RATNAMANI"),
    ("Welspun Corp", "WELCORP"),
    ("Jindal Stainless", "JSL"),
    # --- Auto & Auto Ancillaries ----------------------------------------
    ("Maruti Suzuki India", "MARUTI"),
    ("Tata Motors", "TATAMOTORS"),
    ("Mahindra & Mahindra", "M&M"),
    ("Bajaj Auto", "BAJAJ-AUTO"),
    ("Hero MotoCorp", "HEROMOTOCO"),
    ("Eicher Motors", "EICHERMOT"),
    ("TVS Motor Company", "TVSMOTOR"),
    ("Ashok Leyland", "ASHOKLEY"),
    ("Bharat Forge", "BHARATFORG"),
    ("Samvardhana Motherson International", "MOTHERSON"),
    ("Bosch", "BOSCHLTD"),
    ("MRF", "MRF"),
    ("Apollo Tyres", "APOLLOTYRE"),
    ("Balkrishna Industries", "BALKRISIND"),
    ("Exide Industries", "EXIDEIND"),
    ("Amara Raja Energy & Mobility", "ARE&M"),
    ("Sona BLW Precision Forgings", "SONACOMS"),
    ("Escorts Kubota", "ESCORTS"),
    ("Tube Investments of India", "TIINDIA"),
    # --- Pharma & Healthcare --------------------------------------------
    ("Sun Pharmaceutical Industries", "SUNPHARMA"),
    ("Dr. Reddy's Laboratories", "DRREDDY"),
    ("Cipla", "CIPLA"),
    ("Divi's Laboratories", "DIVISLAB"),
    ("Lupin", "LUPIN"),
    ("Aurobindo Pharma", "AUROPHARMA"),
    ("Torrent Pharmaceuticals", "TORNTPHARM"),
    ("Zydus Lifesciences", "ZYDUSLIFE"),
    ("Alkem Laboratories", "ALKEM"),
    ("Mankind Pharma", "MANKIND"),
    ("Biocon", "BIOCON"),
    ("Glenmark Pharmaceuticals", "GLENMARK"),
    ("Ipca Laboratories", "IPCALAB"),
    ("Laurus Labs", "LAURUSLABS"),
    ("Gland Pharma", "GLAND"),
    ("Abbott India", "ABBOTINDIA"),
    ("Pfizer", "PFIZER"),
    ("Apollo Hospitals Enterprise", "APOLLOHOSP"),
    ("Max Healthcare Institute", "MAXHEALTH"),
    ("Fortis Healthcare", "FORTIS"),
    ("Syngene International", "SYNGENE"),
    ("Metropolis Healthcare", "METROPOLIS"),
    ("Dr. Lal PathLabs", "LALPATHLAB"),
    ("Poly Medicure", "POLYMED"),
    # --- FMCG / Consumer -------------------------------------------------
    ("Hindustan Unilever", "HINDUNILVR"),
    ("ITC", "ITC"),
    ("Nestle India", "NESTLEIND"),
    ("Britannia Industries", "BRITANNIA"),
    ("Tata Consumer Products", "TATACONSUM"),
    ("Dabur India", "DABUR"),
    ("Godrej Consumer Products", "GODREJCP"),
    ("Marico", "MARICO"),
    ("Colgate-Palmolive (India)", "COLPAL"),
    ("Varun Beverages", "VBL"),
    ("United Spirits", "MCDOWELL-N"),
    ("United Breweries", "UBL"),
    ("Emami", "EMAMILTD"),
    ("Jyothy Labs", "JYOTHYLAB"),
    ("Patanjali Foods", "PATANJALI"),
    ("Radico Khaitan", "RADICO"),
    ("Bikaji Foods International", "BIKAJI"),
    ("Zomato", "ZOMATO"),
    ("Avenue Supermarts (DMart)", "DMART"),
    ("Trent", "TRENT"),
    # --- Cement / Construction / Infrastructure -----------------------
    ("UltraTech Cement", "ULTRACEMCO"),
    ("Shree Cement", "SHREECEM"),
    ("Ambuja Cements", "AMBUJACEM"),
    ("ACC", "ACC"),
    ("Grasim Industries", "GRASIM"),
    ("Dalmia Bharat", "DALBHARAT"),
    ("JK Cement", "JKCEMENT"),
    ("Larsen & Toubro", "LT"),
    ("Adani Ports and Special Economic Zone", "ADANIPORTS"),
    ("GMR Airports", "GMRINFRA"),
    ("IRB Infrastructure Developers", "IRB"),
    ("KEC International", "KEC"),
    ("Kalpataru Projects International", "KPIL"),
    ("NCC", "NCC"),
    ("Rail Vikas Nigam", "RVNL"),
    ("Indian Railway Catering and Tourism Corporation", "IRCTC"),
    ("Indian Railway Finance Corporation", "IRFC"),
    # --- Telecom / Media -------------------------------------------------
    ("Bharti Airtel", "BHARTIARTL"),
    ("Vodafone Idea", "IDEA"),
    ("Indus Towers", "INDUSTOWER"),
    ("Zee Entertainment Enterprises", "ZEEL"),
    ("Sun TV Network", "SUNTV"),
    ("PVR INOX", "PVRINOX"),
    ("Network18 Media & Investments", "NETWORK18"),
    ("Tata Communications", "TATACOMM"),
    # --- Diversified Industrials / Capital Goods -------------------------
    ("Adani Enterprises", "ADANIENT"),
    ("3M India", "3MINDIA"),
    ("Siemens", "SIEMENS"),
    ("ABB India", "ABB"),
    ("Havells India", "HAVELLS"),
    ("Polycab India", "POLYCAB"),
    ("Voltas", "VOLTAS"),
    ("Blue Star", "BLUESTARCO"),
    ("Crompton Greaves Consumer Electricals", "CROMPTON"),
    ("Dixon Technologies (India)", "DIXON"),
    ("Amber Enterprises India", "AMBER"),
    ("Cummins India", "CUMMINSIND"),
    ("Thermax", "THERMAX"),
    ("Honeywell Automation India", "HONAUT"),
    ("Schaeffler India", "SCHAEFFLER"),
    ("SKF India", "SKFINDIA"),
    ("Timken India", "TIMKEN"),
    ("Astral", "ASTRAL"),
    ("Supreme Industries", "SUPREMEIND"),
    ("Finolex Cables", "FINCABLES"),
    ("KEI Industries", "KEI"),
    # --- Chemicals ---------------------------------------------------
    ("UPL", "UPL"),
    ("SRF", "SRF"),
    ("Pidilite Industries", "PIDILITIND"),
    ("Aarti Industries", "AARTIIND"),
    ("Deepak Nitrite", "DEEPAKNTR"),
    ("Navin Fluorine International", "NAVINFLUOR"),
    ("Atul", "ATUL"),
    ("Tata Chemicals", "TATACHEM"),
    ("PI Industries", "PIIND"),
    ("Coromandel International", "COROMANDEL"),
    ("Chambal Fertilisers & Chemicals", "CHAMBLFERT"),
    ("Gujarat Narmada Valley Fertilizers", "GNFC"),
    ("Linde India", "LINDEINDIA"),
    # --- Textiles / Apparel / Jewellery ----------------------------------
    ("Page Industries", "PAGEIND"),
    ("Vardhman Textiles", "VTL"),
    ("Welspun Living", "WELSPUNLIV"),
    ("Raymond", "RAYMOND"),
    ("Titan Company", "TITAN"),
    ("Kalyan Jewellers India", "KALYANKJIL"),
    ("Aditya Birla Fashion and Retail", "ABFRL"),
    ("Asian Paints", "ASIANPAINT"),
    # --- New-age tech / Internet -----------------------------------------
    ("One97 Communications (Paytm)", "PAYTM"),
    ("FSN E-Commerce Ventures (Nykaa)", "NYKAA"),
    ("PB Fintech (Policybazaar)", "POLICYBZR"),
    ("Delhivery", "DELHIVERY"),
    ("Info Edge (India)", "NAUKRI"),
    ("Indiamart Intermesh", "INDIAMART"),
    ("Just Dial", "JUSTDIAL"),
    ("Route Mobile", "ROUTE"),
    # --- Aviation / Logistics ---------------------------------------------
    ("InterGlobe Aviation (IndiGo)", "INDIGO"),
    ("Container Corporation of India", "CONCOR"),
    ("Adani Wilmar", "AWL"),
    ("Blue Dart Express", "BLUEDART"),
    ("TCI Express", "TCIEXP"),
    ("VRL Logistics", "VRLLOG"),
    # --- Defense / PSU manufacturing ---------------------------------
    ("Hindustan Aeronautics", "HAL"),
    ("Bharat Electronics", "BEL"),
    ("Bharat Dynamics", "BDL"),
    ("Mazagon Dock Shipbuilders", "MAZDOCK"),
    ("Cochin Shipyard", "COCHINSHIP"),
    ("Garden Reach Shipbuilders & Engineers", "GRSE"),
    ("BEML", "BEML"),
    # --- Real Estate -------------------------------------------------
    ("DLF", "DLF"),
    ("Godrej Properties", "GODREJPROP"),
    ("Oberoi Realty", "OBEROIRLTY"),
    ("Prestige Estates Projects", "PRESTIGE"),
    ("Phoenix Mills", "PHOENIXLTD"),
    ("Sobha", "SOBHA"),
    ("Brigade Enterprises", "BRIGADE"),
    ("Macrotech Developers (Lodha)", "LODHA"),
]


def _deduplicate_by_ticker(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Keep the first occurrence of each bare ticker, preserving
    ``entries``'s own order -- a safety net against a future edit
    accidentally re-listing the same company under two sector
    headings above; ``_RAW_ENTRIES`` itself has no duplicates today
    (see test_nse_company_universe.py's own regression test).
    """
    seen: set[str] = set()
    deduplicated: list[tuple[str, str]] = []
    for name, bare_ticker in entries:
        if bare_ticker in seen:
            continue
        seen.add(bare_ticker)
        deduplicated.append((name, bare_ticker))
    return deduplicated


#: The public, de-duplicated-by-ticker universe -- see this module's
#: own docstring for why a curated static list, not a live pull.
NSE_COMPANY_UNIVERSE: list[CompanyEntry] = [
    CompanyEntry(name=name, ticker=f"{bare_ticker}.NS", exchange="NSE")
    for name, bare_ticker in _deduplicate_by_ticker(_RAW_ENTRIES)
]
