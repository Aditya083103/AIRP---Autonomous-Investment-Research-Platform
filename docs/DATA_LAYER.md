# AIRP — Data Layer Reference

**Phase 1 (T-009 – T-019) · Last updated: T-020**

Complete reference for all LangChain data tools in `backend/tools/`.
Every tool follows the same contract:

- Returns a `dict[str, Any]` — **never raises** out to the caller.
- On success: no `"error"` key; all fields match the Pydantic schema below.
- On failure: `{"error": "<code>", "message": "<detail>", ...}` — the agent routes on `result["error"]`.
- All tools are separated into `_fetch_*()` inner function + `@tool` decorator so the inner function can be tested without LangChain machinery.

---

## Table of Contents

1. [Cache Layer](#1-cache-layer)
2. [fetch_stock_price / fetch_ohlcv](#2-fetch_stock_price--fetch_ohlcv)
3. [fetch_financials (and variants)](#3-fetch_financials-and-variants)
4. [fetch_ratios / fetch_ratios_summary](#4-fetch_ratios--fetch_ratios_summary)
5. [fetch_news / fetch_news_summary](#5-fetch_news--fetch_news_summary)
6. [fetch_macro_data / fetch_macro_summary](#6-fetch_macro_data--fetch_macro_summary)
7. [fetch_earnings_transcript / fetch_transcript_chunk](#7-fetch_earnings_transcript--fetch_transcript_chunk)
8. [Redis Cache Keys & TTLs](#8-redis-cache-keys--ttls)
9. [API Rate Limits & Free Tier Summary](#9-api-rate-limits--free-tier-summary)
10. [Error Code Reference](#10-error-code-reference)
11. [Ticker Convention](#11-ticker-convention)
12. [Testing Patterns](#12-testing-patterns)

---

## 1. Cache Layer

**Module:** `backend/tools/cache.py`  
**Redis client:** `backend/db/redis_client.py`

### How caching works

Every data tool wraps its core `_fetch_*()` function with the `@cached` decorator. On a cache **hit** the dict is returned from Redis immediately — no network call. On a **miss** the live fetch runs, the result is stored in Redis with a TTL, then returned.

```python
from backend.tools.cache import cached, STOCK_TTL

@cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
def _fetch_stock_cached(ticker: str, period: str) -> dict[str, Any]:
    return _fetch_stock_data(ticker=ticker, period=period)
```

### Cache behaviour by environment

| Environment | Redis connection | Cache reads | Cache writes |
|---|---|---|---|
| `ENVIRONMENT=test` | Disabled (`_FORCE_DISABLE=True`) | No-op | No-op |
| `ENVIRONMENT=development` | Lazy connect on first call | Active | Active |
| `ENVIRONMENT=production` | HttpClient to Upstash | Active | Active |

**Error results are never cached.** A dict containing `"error"` is returned to the caller but not written to Redis — transient failures resolve on the next call.

### Low-level helpers

```python
from backend.tools.cache import cache_get_json, cache_set_json

# Read
data = cache_get_json("airp:macro:india")   # → dict | None

# Write
cache_set_json("airp:macro:india", data, ttl_seconds=86400)  # → bool
```

Both functions degrade silently — they return `None` / `False` if Redis is unreachable; they never raise.

---

## 2. fetch_stock_price / fetch_ohlcv

**Module:** `backend/tools/stock_price.py`  
**Data source:** yFinance (unofficial Yahoo Finance — no API key required)  
**Cache TTL:** 900 s (15 min) · Key: `airp:stock:{ticker}:{period}`

### Tool signatures

```python
fetch_stock_price(ticker: str, period: str = "1y") -> dict[str, Any]
fetch_ohlcv(ticker: str, period: str = "1y") -> dict[str, Any]
```

| Parameter | Type | Required | Values | Description |
|---|---|---|---|---|
| `ticker` | `str` | Yes | e.g. `"TCS.NS"` | Exchange ticker with suffix |
| `period` | `str` | No | `"1y"` `"3y"` `"5y"` | Data lookback period (default `"1y"`) |

### Example invocation

```python
from backend.tools.stock_price import fetch_stock_price, fetch_ohlcv

result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})
ohlcv  = fetch_ohlcv.invoke({"ticker": "INFY.NS", "period": "3y"})
```

### Success output — fetch_stock_price

```json
{
  "ticker": "TCS.NS",
  "company_name": "Tata Consultancy Services Limited",
  "exchange": "NSE",
  "currency": "INR",
  "period": "1y",
  "data_points": 252,
  "first_date": "2023-06-10",
  "last_date":  "2024-06-10",
  "stats": {
    "current_price": 3845.20,
    "price_52w_high": 4255.00,
    "price_52w_low":  3056.70,
    "avg_volume_30d": 2847300,
    "pct_change_1m":  2.4,
    "pct_change_3m":  8.1,
    "pct_change_1y":  18.3,
    "ma_50d":         3712.40,
    "ma_200d":        3541.80,
    "above_ma_50d":   true,
    "above_ma_200d":  true
  },
  "ohlcv": [
    {
      "date":   "2023-06-12",
      "open":   3056.70,
      "high":   3089.00,
      "low":    3041.50,
      "close":  3072.30,
      "volume": 1823400
    }
  ],
  "fetched_at": "2024-06-10T05:30:00Z",
  "source": "yfinance"
}
```

### Success output — fetch_ohlcv

`fetch_ohlcv` is a lightweight variant — it returns only the candle series (no `stats` block), intended for the frontend charting pipeline.

```json
{
  "ticker": "TCS.NS",
  "period": "1y",
  "currency": "INR",
  "data_points": 252,
  "ohlcv": [ { "date": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ... } ]
}
```

### Error outputs

| `error` code | Trigger | Additional fields |
|---|---|---|
| `ticker_not_found` | yFinance returns no data for the ticker | `ticker`, `message` |
| `invalid_parameter` | `period` not in `{"1y", "3y", "5y"}` | `ticker`, `message` |
| `unexpected_error` | Unhandled exception | `ticker`, `message` |

```json
{ "error": "ticker_not_found", "ticker": "XYZINVALID.NS",
  "message": "No price data found for ticker 'XYZINVALID.NS'..." }
```

### Notes

- `ma_50d` and `ma_200d` are `null` when fewer than 50 / 200 data points are available.
- `pct_change_*` returns `0.0` when the series is too short.
- All prices are in the stock's native currency (INR for NSE, USD for US stocks).

---

## 3. fetch_financials (and variants)

**Module:** `backend/tools/financials.py`  
**Data source:** yFinance  
**Cache TTL:** No dedicated cache — called infrequently; add via `@cached` in Phase 2 if needed.  
**Currency normalisation:** All monetary output is in **INR Crores** regardless of the company's native reporting currency (`USD_TO_INR = 83.5`, `UNITS_TO_CRORES = 1e7`).

### Tool signatures

```python
fetch_financials(ticker: str)       -> dict[str, Any]  # all three statements
fetch_income_statement(ticker: str) -> dict[str, Any]  # income only
fetch_balance_sheet(ticker: str)    -> dict[str, Any]  # balance sheet only
fetch_cash_flow(ticker: str)        -> dict[str, Any]  # cash flow only
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `ticker` | `str` | Yes | Exchange ticker, e.g. `"TCS.NS"`, `"RELIANCE.NS"` |

### Example invocation

```python
from backend.tools.financials import fetch_financials

result = fetch_financials.invoke({"ticker": "TCS.NS"})
revenue = result["income_statement"][0]["revenue_crores"]   # most recent year
```

### Success output — fetch_financials

```json
{
  "ticker": "TCS.NS",
  "company_name": "Tata Consultancy Services Limited",
  "currency_reported": "INR",
  "currency_output": "INR",
  "years_available": 4,
  "income_statement": [
    {
      "fiscal_year": "FY 2024",
      "revenue_crores": 240890.0,
      "gross_profit_crores": 72400.0,
      "operating_income_crores": 59040.0,
      "ebitda_crores": 65230.0,
      "net_income_crores": 46110.0,
      "basic_eps": 125.70,
      "gross_margin_pct": 30.1,
      "operating_margin_pct": 24.5,
      "net_margin_pct": 19.1
    }
  ],
  "balance_sheet": [
    {
      "fiscal_year": "FY 2024",
      "total_assets_crores": 178560.0,
      "total_liabilities_crores": 65430.0,
      "total_equity_crores": 113130.0,
      "total_debt_crores": 4200.0,
      "cash_crores": 12800.0,
      "net_debt_crores": -8600.0,
      "debt_to_equity": 0.04,
      "current_ratio": 3.1
    }
  ],
  "cash_flow": [
    {
      "fiscal_year": "FY 2024",
      "operating_cash_flow_crores": 52100.0,
      "investing_cash_flow_crores": -9800.0,
      "financing_cash_flow_crores": -35000.0,
      "free_cash_flow_crores": 45200.0,
      "capital_expenditure_crores": 6900.0,
      "fcf_margin_pct": 18.8
    }
  ],
  "data_warnings": [],
  "fetched_at": "2024-06-10T05:30:00Z",
  "source": "yfinance"
}
```

All `*_crores` fields are `float | null` — `null` means yFinance did not report that figure for that year. Agents must handle null values.

### Error outputs

| `error` code | Trigger |
|---|---|
| `financials_not_found` | yFinance returns no statements for the ticker |
| `unexpected_error` | Unhandled exception |

---

## 4. fetch_ratios / fetch_ratios_summary

**Module:** `backend/tools/ratios.py`  
**Data sources:** yFinance (primary) + Alpha Vantage OVERVIEW (gap-fill, best-effort)  
**Cache TTL:** 3 600 s (1 h) · Key: `airp:ratios:{ticker}`  
**API key required:** `ALPHA_VANTAGE_KEY` (optional — ratios degrade gracefully without it)

### Ratios computed

| Ratio | Formula | Unit |
|---|---|---|
| PE | Price ÷ Trailing EPS | × |
| PB | Price ÷ Book Value per Share | × |
| ROE | Net Income ÷ Shareholders' Equity | % |
| ROCE | EBIT ÷ (Total Assets − Current Liabilities) | % |
| D/E | Total Debt ÷ Shareholders' Equity | × |
| EV/EBITDA | Enterprise Value ÷ EBITDA | × |

Enterprise Value = Market Cap + Total Debt − Cash

### Tool signatures

```python
fetch_ratios(ticker: str)         -> dict[str, Any]  # full model with inputs audit trail
fetch_ratios_summary(ticker: str) -> dict[str, Any]  # six ratios only — no inputs block
```

### Example invocation

```python
from backend.tools.ratios import fetch_ratios, fetch_ratios_summary

full    = fetch_ratios.invoke({"ticker": "TCS.NS"})
summary = fetch_ratios_summary.invoke({"ticker": "INFY.NS"})
pe      = full["pe_ratio"]
```

### Success output — fetch_ratios

```json
{
  "ticker": "TCS.NS",
  "company_name": "Tata Consultancy Services Limited",
  "currency": "INR",
  "pe_ratio": 29.4,
  "pb_ratio": 13.1,
  "roe_pct": 47.2,
  "roce_pct": 62.8,
  "debt_to_equity": 0.04,
  "ev_to_ebitda": 22.6,
  "enterprise_value": 1432000000000.0,
  "inputs": {
    "price": 3845.20,
    "eps": 130.80,
    "book_value_per_share": 293.50,
    "shares_outstanding": 3673000000.0,
    "net_income": 46110000000.0,
    "total_equity": 113130000000.0,
    "operating_income": 59040000000.0,
    "total_assets": 178560000000.0,
    "current_liabilities": 32400000000.0,
    "total_debt": 4200000000.0,
    "cash": 12800000000.0,
    "market_cap": 1412000000000.0,
    "ebitda": 63400000000.0
  },
  "sources": {
    "pe_ratio": "computed",
    "pb_ratio": "computed",
    "roe_pct": "computed",
    "roce_pct": "computed",
    "debt_to_equity": "computed",
    "ev_to_ebitda": "computed"
  },
  "data_warnings": [],
  "fetched_at": "2024-06-10T05:30:00Z",
  "source": "yfinance+alphavantage"
}
```

`sources` values are either `"computed"` (derived from yFinance raw primitives) or `"alpha_vantage"` (filled from Alpha Vantage OVERVIEW). All ratio fields are `float | null`.

### Success output — fetch_ratios_summary

```json
{
  "ticker": "TCS.NS",
  "company_name": "Tata Consultancy Services Limited",
  "currency": "INR",
  "pe_ratio": 29.4,
  "pb_ratio": 13.1,
  "roe_pct": 47.2,
  "roce_pct": 62.8,
  "debt_to_equity": 0.04,
  "ev_to_ebitda": 22.6,
  "data_warnings": []
}
```

### Error outputs

| `error` code | Trigger |
|---|---|
| `ratios_not_found` | yFinance returns no data for the ticker |
| `unexpected_error` | Unhandled exception |

---

## 5. fetch_news / fetch_news_summary

**Module:** `backend/tools/news.py`  
**Data source:** NewsAPI v2 `/everything` endpoint  
**Cache TTL:** 3 600 s (1 h) · Key: `airp:news:{company_name}`  
**API key required:** `NEWS_API_KEY` (free tier: 100 requests/day)  
**Lookback window:** Last 30 days (NewsAPI free tier limit)  
**Retry policy:** 3 attempts, exponential back-off 2 s → 60 s, on HTTP 429 and network errors

### Tool signatures

```python
fetch_news(
    company_name: str,
    ticker: str = "",
    max_articles: int = 20,
) -> dict[str, Any]

fetch_news_summary(
    company_name: str,
    ticker: str = "",
    max_articles: int = 20,
) -> dict[str, Any]
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `company_name` | `str` | **Yes** | — | Full company name for the search query, e.g. `"Tata Consultancy Services"` |
| `ticker` | `str` | No | `""` | Ticker appended to query for precision (base only: `TCS.NS` → `TCS`) |
| `max_articles` | `int` | No | `20` | Max articles to return (hard cap: 100) |

### Example invocation

```python
from backend.tools.news import fetch_news, fetch_news_summary

result = fetch_news.invoke({
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "max_articles": 10,
})
articles = result["articles"]

summary = fetch_news_summary.invoke({"company_name": "Infosys"})
headlines = summary["headlines"]
```

### Success output — fetch_news

```json
{
  "company_name": "Tata Consultancy Services",
  "ticker": "TCS.NS",
  "query_used": "\"Tata Consultancy Services\" OR TCS",
  "from_date": "2024-05-11",
  "to_date":   "2024-06-10",
  "total_results": 47,
  "articles_returned": 10,
  "articles": [
    {
      "title": "TCS Q4 profit rises 9% to ₹12,434 crore",
      "description": "India's largest IT company beats analyst estimates...",
      "url": "https://economictimes.indiatimes.com/...",
      "source_name": "The Economic Times",
      "published_at": "2024-04-19T10:30:00+00:00",
      "content_snippet": "Tata Consultancy Services on Friday reported..."
    }
  ],
  "fetched_at": "2024-06-10T05:30:00Z",
  "source": "newsapi",
  "warnings": []
}
```

### Success output — fetch_news_summary

```json
{
  "company_name": "Tata Consultancy Services",
  "total_results": 47,
  "articles_returned": 10,
  "headlines": [
    "TCS Q4 profit rises 9% to ₹12,434 crore",
    "TCS wins $2bn deal from a European bank"
  ],
  "from_date": "2024-05-11",
  "to_date":   "2024-06-10",
  "warnings": []
}
```

### Error outputs

| `error` code | Trigger |
|---|---|
| `configuration_error` | `NEWS_API_KEY` not set in environment |
| `newsapi_error` | HTTP 401 (invalid key) or HTTP 400 (bad request) |
| `rate_limit_exhausted` | HTTP 429 persists after all 3 retry attempts |
| `unexpected_error` | Unhandled exception |

### Rate limit protection

With Redis caching (TTL 1 h), a busy 8-agent analysis run needs at most 8 NewsAPI calls per unique company per hour. At 100 calls/day free tier, this supports ~12 unique company analyses per day without exhausting the quota. For heavier use, add a Redis URL to your `.env`.

---

## 6. fetch_macro_data / fetch_macro_summary

**Module:** `backend/tools/macro.py`  
**Data sources:**

| Field | Source | Method |
|---|---|---|
| `repo_rate` | RBI website (`settings.rbi_base_url`) | HTML scrape |
| `cpi_inflation` | MOSPI website | HTML scrape |
| `gdp_growth` | World Bank Indicators API | JSON GET (no key) |

**Cache TTL:** 86 400 s (24 h) · Key: `airp:macro:india` (fixed — India only)  
**API key required:** None  
**Graceful degradation:** Each source is fetched independently. A blocked scrape sets only its field to `null` and appends a warning — the other fields still populate.

### Tool signatures

```python
fetch_macro_data(force_refresh: bool = False) -> dict[str, Any]
fetch_macro_summary() -> dict[str, Any]
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `force_refresh` | `bool` | No | When `True`, bypass the 24h Redis cache and fetch live data |

### Example invocation

```python
from backend.tools.macro import fetch_macro_data, fetch_macro_summary

result  = fetch_macro_data.invoke({})
summary = fetch_macro_summary.invoke({})

repo_rate = result["repo_rate"]       # float | None  (e.g. 6.5)
cpi       = result["cpi_inflation"]   # float | None  (e.g. 5.1)
gdp       = result["gdp_growth"]      # float | None  (e.g. 7.0)

# Force a fresh fetch (bypass 24h cache):
fresh = fetch_macro_data.invoke({"force_refresh": True})
```

### Success output — fetch_macro_data

```json
{
  "country": "India",
  "repo_rate": 6.5,
  "cpi_inflation": 4.83,
  "gdp_growth": 8.2,
  "repo_rate_as_of": "June 2024",
  "cpi_as_of": "April 2024",
  "gdp_as_of": "2023",
  "sources": {
    "repo_rate":    "rbi",
    "cpi_inflation":"mospi",
    "gdp_growth":   "worldbank"
  },
  "warnings": [],
  "fetched_at": "2024-06-10T05:30:00Z",
  "cached": false,
  "source": "rbi+mospi+worldbank"
}
```

When a source fails, its field is `null` and a warning is added:

```json
{
  "repo_rate": null,
  "warnings": ["RBI repo rate not found in page — RBI layout may have changed"],
  "cached": false
}
```

### Success output — fetch_macro_summary

```json
{
  "country": "India",
  "repo_rate": 6.5,
  "cpi_inflation": 4.83,
  "gdp_growth": 8.2,
  "warnings": [],
  "fetched_at": "2024-06-10T05:30:00Z",
  "cached": false
}
```

### Error outputs

| `error` code | Trigger |
|---|---|
| `unexpected_error` | Unhandled exception (scrape failures are NOT errors — they produce `null` fields) |

> **Important:** A result where all three fields are `null` is NOT cached. The next call will retry the live sources. This prevents 24 hours of empty data being served after a temporary outage.

---

## 7. fetch_earnings_transcript / fetch_transcript_chunk

**Module:** `backend/tools/earnings_transcript.py`  
**Data sources:** Screener.in (scrape) or PDF upload  
**Cache TTL:** 3 600 s (1 h) · Key: `airp:transcript:<company_slug>`  
**API key required:** None  
**PDF-upload results are never cached** (caller owns the bytes)

### Tool signatures

```python
fetch_earnings_transcript(
    company_name: str,
    ticker: str = "",
    pdf_bytes: bytes | None = None,
    pdf_path: str | None = None,
    max_chunk_chars: int = 4000,
    force_refresh: bool = False,
) -> dict[str, Any]

fetch_transcript_chunk(
    company_name: str,
    ticker: str = "",
    max_chunk_chars: int = 4000,
    force_refresh: bool = False,
) -> dict[str, Any]
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `company_name` | `str` | **Yes** | Human-readable company name, e.g. `"Infosys"` |
| `ticker` | `str` | No | Used to derive the Screener.in URL slug (e.g. `"INFY.NS"` → slug `"INFY"`) |
| `pdf_bytes` | `bytes\|None` | No | Raw bytes of an uploaded PDF; bypasses web scraping |
| `pdf_path` | `str\|None` | No | Absolute path to a PDF on disk; bypasses web scraping |
| `max_chunk_chars` | `int` | No | Characters in `transcript_chunk` (default 4 000) |
| `force_refresh` | `bool` | No | Bypass Redis cache and re-fetch from Screener |

> `company_name` is **required**. Passing only `ticker` raises a Pydantic `ValidationError` before the tool body runs.

### Example invocation

```python
from backend.tools.earnings_transcript import (
    fetch_earnings_transcript,
    fetch_transcript_chunk,
)

# Scrape path
result = fetch_earnings_transcript.invoke({
    "company_name": "Infosys",
    "ticker": "INFY.NS",
})
text  = result["transcript_text"]    # full text
chunk = result["transcript_chunk"]   # first 4 000 chars

# PDF upload path
with open("concall_q4.pdf", "rb") as f:
    result = fetch_earnings_transcript.invoke({
        "company_name": "TCS",
        "ticker": "TCS.NS",
        "pdf_bytes": f.read(),
    })

# Lightweight chunk only (saves LLM tokens)
chunk_result = fetch_transcript_chunk.invoke({
    "company_name": "Reliance Industries",
    "ticker": "RELIANCE.NS",
})
```

### Success output — fetch_earnings_transcript

```json
{
  "company_name": "Infosys",
  "ticker": "INFY.NS",
  "exchange": "NSE",
  "transcript_text": "Ladies and gentlemen, welcome to the Infosys Q4 FY2024...",
  "transcript_chunk": "Ladies and gentlemen, welcome to the Infosys Q4 FY2024 earnings call...",
  "source": "screener",
  "quarter": "Q4",
  "year": "2024",
  "char_count": 42817,
  "fetched_at": "2024-06-10T05:30:00Z",
  "cached": false,
  "warnings": []
}
```

`source` is one of `"screener"` | `"pdf_upload"` | `"pdf_path"`.

### Success output — fetch_transcript_chunk

```json
{
  "company_name": "Infosys",
  "ticker": "INFY.NS",
  "transcript_chunk": "Ladies and gentlemen, welcome to the Infosys Q4 FY2024...",
  "quarter": "Q4",
  "year": "2024",
  "source": "screener",
  "char_count": 42817,
  "fetched_at": "2024-06-10T05:30:00Z",
  "cached": false,
  "warnings": []
}
```

### Error outputs

| `error` code | Trigger |
|---|---|
| `scrape_blocked` | Screener.in returned HTTP 403/429 or bot-detection |
| `scrape_error` | Screener.in returned unexpected HTTP status |
| `pdf_not_found` | `pdf_path` does not exist on disk |
| `pdf_extraction_error` | pdfminer.six raised an exception |
| `pdf_empty` | PDF parsed successfully but text is empty |
| `unexpected_error` | Unhandled exception |

---

## 8. Redis Cache Keys & TTLs

| Tool | Redis key | TTL | Notes |
|---|---|---|---|
| `fetch_stock_price` | `airp:stock:{ticker}:{period}` | 900 s (15 min) | Per ticker+period pair |
| `fetch_ohlcv` | `airp:stock:{ticker}:{period}` | 900 s (15 min) | Shares key with fetch_stock_price |
| `fetch_ratios` | `airp:ratios:{ticker}` | 3 600 s (1 h) | Both full and summary variants |
| `fetch_news` | `airp:news:{company_name}` | 3 600 s (1 h) | Keyed on company name |
| `fetch_earnings_transcript` | `airp:transcript:{slug}` | 3 600 s (1 h) | slug = NSE ticker without suffix |
| `fetch_macro_data` | `airp:macro:india` | 86 400 s (24 h) | Fixed key — India-wide snapshot |

TTL constants are defined in `backend/db/redis_client.py` and re-exported from `backend/tools/cache.py`:

```python
from backend.tools.cache import STOCK_TTL, NEWS_TTL, RATIOS_TTL, MACRO_TTL
# STOCK_TTL  = 900
# NEWS_TTL   = 3_600
# RATIOS_TTL = 3_600
# MACRO_TTL  = 86_400
```

---

## 9. API Rate Limits & Free Tier Summary

| Service | Free limit | Env variable | Caching mitigates? |
|---|---|---|---|
| yFinance | Unofficial; ~100–200 req/min before 429 | None required | Partially (STOCK_TTL=15 min) |
| Alpha Vantage | 25 requests/day | `ALPHA_VANTAGE_KEY` | Yes (RATIOS_TTL=1 h) |
| NewsAPI | 100 requests/day | `NEWS_API_KEY` | Yes (NEWS_TTL=1 h) |
| World Bank API | Unlimited (public) | None required | Yes (MACRO_TTL=24 h) |
| RBI scrape | Unlimited (public) | `RBI_BASE_URL` | Yes (MACRO_TTL=24 h) |
| MOSPI scrape | Unlimited (public) | None | Yes (MACRO_TTL=24 h) |
| Screener.in | Unlimited (public, bot-detection risk) | `SCREENER_BASE_URL` | Yes (1 h per company) |
| Upstash Redis | 10 000 commands/day (free) | `REDIS_URL`, `REDIS_TOKEN` | N/A — is the cache |

### `.env` configuration

```env
NEWS_API_KEY=your-key-from-newsapi-org
ALPHA_VANTAGE_KEY=your-key-from-alphavantage-co
REDIS_URL=redis://localhost:6379
REDIS_TOKEN=                       # leave empty for local; set for Upstash
SCREENER_BASE_URL=https://www.screener.in
RBI_BASE_URL=https://www.rbi.org.in
```

---

## 10. Error Code Reference

All tools return `{"error": "<code>", "message": "<detail>", ...}` on failure. Agents route on `result["error"]`.

| Error code | Tool(s) | Meaning | Agent action |
|---|---|---|---|
| `ticker_not_found` | stock_price, financials, ratios | Ticker not in Yahoo Finance | Try alternate ticker format (`.BO` vs `.NS`) |
| `invalid_parameter` | stock_price | `period` not in `{"1y","3y","5y"}` | Fix the period string |
| `financials_not_found` | financials | No financial statements in yFinance | Note as data gap in analysis |
| `ratios_not_found` | ratios | No ratio primitives available | Note as data gap |
| `configuration_error` | news | `NEWS_API_KEY` not set | Skip news analysis; flag in memo |
| `newsapi_error` | news | Invalid key or bad API request | Log and skip news section |
| `rate_limit_exhausted` | news | 429 persists after 3 retries | Wait and retry; use cached data |
| `scrape_blocked` | earnings_transcript | Screener.in returned 403/429 | Try `pdf_bytes` / `pdf_path` upload |
| `scrape_error` | earnings_transcript | Unexpected HTTP from Screener | Degrade gracefully; note in memo |
| `pdf_not_found` | earnings_transcript | `pdf_path` doesn't exist | Check path; prompt user to re-upload |
| `pdf_extraction_error` | earnings_transcript | pdfminer failed to parse | Try different PDF or scrape path |
| `pdf_empty` | earnings_transcript | PDF parsed but no text found | Likely a scanned PDF; needs OCR |
| `unexpected_error` | all | Unhandled exception | Log trace; skip this tool in analysis |

---

## 11. Ticker Convention

All data tools that accept a `ticker` parameter follow Yahoo Finance's exchange suffix convention:

| Exchange | Suffix | Example |
|---|---|---|
| NSE (National Stock Exchange of India) | `.NS` | `TCS.NS`, `INFY.NS`, `RELIANCE.NS` |
| BSE (Bombay Stock Exchange) | `.BO` | `532540.BO`, `500325.BO` |
| NASDAQ / NYSE (US) | *(none)* | `AAPL`, `MSFT` |
| London Stock Exchange | `.L` | `SHEL.L` |

**Recommendation:** Always use `.NS` for Indian stocks — NSE data is more complete in yFinance than BSE.

---

## 12. Testing Patterns

### Unit tests (all offline — no real API calls)

```python
# Always set ENVIRONMENT=test before importing backend modules
import os
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock, patch
from backend.tools.stock_price import fetch_stock_price

def test_fetch_stock_price_returns_error_on_empty_df():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()   # empty
    mock_ticker.info = {}

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = fetch_stock_price.invoke({"ticker": "BAD.NS"})

    assert result["error"] == "ticker_not_found"
```

### Integration tests (real APIs — `@pytest.mark.integration`)

```bash
# Run integration tests locally (never in CI):
ENVIRONMENT=test python -m pytest -m integration -v
```

Integration tests live in `backend/tests/integration/test_data_layer.py` and use a resilient ticker rotation (`RELIANCE.NS` → `HDFCBANK.NS` → `INFY.NS` → `TCS.NS`) to handle transient Yahoo Finance rate-limiting.

### Testing the cache layer

```python
# Inject a fake Redis client to test cache hit/miss without a real server:
from unittest.mock import MagicMock, patch
import json

fake_client = MagicMock()
fake_client.get.return_value = json.dumps({"repo_rate": 6.5})

with patch("backend.tools.cache.get_client", return_value=fake_client):
    result = cache_get_json("airp:macro:india")

assert result == {"repo_rate": 6.5}
```

### Coverage target

Unit test coverage for `backend/tools/` and `backend/db/` must remain above **75%** (enforced by `pyproject.toml` `fail_under = 75`). Run with:

```bash
ENVIRONMENT=test python -m pytest --cov=backend --cov-report=term-missing -q
```