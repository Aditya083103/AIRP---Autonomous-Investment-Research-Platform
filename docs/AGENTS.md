# AIRP Agent System — Design Reference

**Document version:** 1.0  
**Phase:** 2 (Research Agents complete)  
**Last updated:** T-028

This document is the authoritative reference for the AIRP investment
committee agent system. It covers each agent's persona, tools, scoring
logic, output schema, example JSON output, known limitations, and
interaction with the LangGraph pipeline.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Agent Base Contract](#2-agent-base-contract)
3. [Agent 1 — Fundamental Analyst](#3-agent-1--fundamental-analyst)
4. [Agent 2 — Technical Analyst](#4-agent-2--technical-analyst)
5. [Agent 3 — News Sentiment Agent](#5-agent-3--news-sentiment-agent)
6. [Agent 4 — Macro Economist](#6-agent-4--macro-economist)
7. [Agents 5–8 — Phase 4 Stubs](#7-agents-58--phase-4-stubs)
8. [LangGraph Execution Order](#8-langgraph-execution-order)
9. [Error Handling Convention](#9-error-handling-convention)
10. [LangSmith Tracing Tags](#10-langsmith-tracing-tags)

---

## 1. System Overview

AIRP simulates an investment committee using 8 collaborating AI agents.
Each agent has a distinct persona, a set of LangChain tools for data
retrieval, and a Pydantic output model that enforces the schema downstream
agents and the Portfolio Manager consume.

**Phase 2 agents (built and tested):**

| #   | Agent                | `agent_name`          | State key     | LangGraph node             |
| --- | -------------------- | --------------------- | ------------- | -------------------------- |
| 1   | Fundamental Analyst  | `fundamental_analyst` | `fundamental` | `run_fundamental_analysis` |
| 2   | Technical Analyst    | `technical_analyst`   | `technical`   | `run_technical_analysis`   |
| 3   | News Sentiment Agent | `news_sentiment`      | `sentiment`   | `run_sentiment_analysis`   |
| 4   | Macro Economist      | `macro_economist`     | `macro`       | `run_macro_analysis`       |

**Phase 4 agents (stubs — built in T-037 to T-044):**

| #   | Agent               | `agent_name`          |
| --- | ------------------- | --------------------- |
| 5   | Risk Officer        | `risk_officer`        |
| 6   | Contrarian Investor | `contrarian_investor` |
| 7   | Valuation Agent     | `valuation_agent`     |
| 8   | Portfolio Manager   | `portfolio_manager`   |

Agents 1–4 run in **parallel** via LangGraph's `Send` API. Agents 5–8
run **sequentially** after the debate round.

---

## 2. Agent Base Contract

Every agent output model inherits from `AgentOutput` in
`backend/agents/output_models.py`.

### Base fields (all agents)

| Field          | Type          | Description                                  |
| -------------- | ------------- | -------------------------------------------- |
| `agent_name`   | `str`         | Canonical identifier (frozen, set by agent)  |
| `analysis_id`  | `str`         | UUID of the parent Analysis job              |
| `company_name` | `str`         | Human-readable company name                  |
| `ticker`       | `str`         | Yahoo Finance ticker (e.g. `TCS.NS`)         |
| `generated_at` | `datetime`    | UTC timestamp of output production           |
| `error`        | `str \| None` | Non-null when the agent encountered an error |

### Error convention

Agents **never raise**. On any failure they return a valid model with
`error` set. LangGraph routing and downstream agents check
`result["error"] is not None` to detect failures and route accordingly.

### Serialisation

Use `model.model_dump(mode="json")` (not `model_dump()`) to get a
JSON-safe dict. The `generated_at` field is a `datetime` object that
becomes an ISO-8601 string only when `mode="json"` is specified.

---

## 3. Agent 1 — Fundamental Analyst

### Persona

> _"You are a seasoned buy-side fundamental analyst with 20 years of
> experience covering Indian equities on NSE and BSE. You specialise in
> quality-of-earnings analysis, balance-sheet stress-testing, and free
> cash flow decomposition."_

### Mandate

Analyse revenue growth, profit margins, free cash flow, debt levels, and
balance sheet health over 4 fiscal years. Produce a scalar score (1–10)
that the Portfolio Manager uses as one input to the final verdict.

### Tools

| Tool               | Source        | Cache TTL | Purpose                                              |
| ------------------ | ------------- | --------- | ---------------------------------------------------- |
| `fetch_financials` | yFinance      | 15 min    | Income statement, balance sheet, cash flow (4 years) |
| `fetch_ratios`     | Alpha Vantage | 60 min    | PE, PB, ROE, ROCE, D/E, EV/EBITDA                    |

### Scoring logic

The overall `score` (1–10) is a weighted average across four dimensions.
All scoring is done in deterministic Python before the LLM call. The LLM
synthesises `strengths`, `weaknesses`, and `summary` only.

| Dimension       | Weight | Key metrics                                      |
| --------------- | ------ | ------------------------------------------------ |
| Revenue growth  | 25%    | 3Y CAGR, YoY growth                              |
| Margin quality  | 25%    | Gross, operating, net margins + trends           |
| Cash generation | 25%    | FCF, FCF margin, FCF yield                       |
| Balance sheet   | 25%    | D/E, current ratio, interest coverage, ROE, ROCE |

Each dimension sub-score is on a 1–10 scale. Missing data defaults to the
minimum contribution for that dimension.

### Output schema — `FundamentalAnalysis`

| Field                  | Type            | Constraints   | Description                       |
| ---------------------- | --------------- | ------------- | --------------------------------- |
| `score`                | `int`           | `ge=1, le=10` | Overall fundamental quality score |
| `revenue_growth_pct`   | `float \| None` | —             | YoY revenue growth (%)            |
| `revenue_cagr_3y_pct`  | `float \| None` | —             | 3-year revenue CAGR (%)           |
| `gross_margin_pct`     | `float \| None` | —             | Gross margin (%)                  |
| `operating_margin_pct` | `float \| None` | —             | Operating margin (%)              |
| `net_margin_pct`       | `float \| None` | —             | Net profit margin (%)             |
| `free_cash_flow_cr`    | `float \| None` | —             | FCF in ₹ crore (TTM)              |
| `fcf_yield_pct`        | `float \| None` | —             | FCF yield (%)                     |
| `debt_to_equity`       | `float \| None` | —             | D/E ratio                         |
| `current_ratio`        | `float \| None` | —             | Liquidity indicator               |
| `interest_coverage`    | `float \| None` | —             | EBIT / interest expense           |
| `roe_pct`              | `float \| None` | —             | Return on equity (%)              |
| `roce_pct`             | `float \| None` | —             | Return on capital employed (%)    |
| `strengths`            | `list[str]`     | default `[]`  | Top 3–5 fundamental strengths     |
| `weaknesses`           | `list[str]`     | default `[]`  | Top 3–5 weaknesses / risks        |
| `summary`              | `str`           | default `""`  | 2–3 sentence PM-ready summary     |

### Example JSON output

```json
{
  "agent_name": "fundamental_analyst",
  "analysis_id": "3f8a2c1d-0e4b-4c7a-9f2e-1b5d6e8f0a3c",
  "company_name": "Tata Consultancy Services",
  "ticker": "TCS.NS",
  "generated_at": "2024-01-15T09:32:14.221Z",
  "error": null,
  "score": 9,
  "revenue_growth_pct": 6.8,
  "revenue_cagr_3y_pct": 13.7,
  "gross_margin_pct": 35.7,
  "operating_margin_pct": 24.5,
  "net_margin_pct": 19.1,
  "free_cash_flow_cr": 44021.0,
  "fcf_yield_pct": 3.1,
  "debt_to_equity": 0.02,
  "current_ratio": 2.1,
  "interest_coverage": null,
  "roe_pct": 46.2,
  "roce_pct": 51.1,
  "strengths": [
    "3Y revenue CAGR of 13.7% demonstrates consistent double-digit growth",
    "ROE of 46.2% is elite — top decile among Nifty 50 constituents",
    "Near-zero debt (D/E 0.02) with ₹30,000 Cr net cash provides resilience",
    "FCF conversion of 92% of net income signals high earnings quality"
  ],
  "weaknesses": [
    "Growth decelerating — YoY revenue growth of 6.8% vs 17.6% in FY22",
    "Premium PE of 28.5x leaves limited margin of safety on valuation",
    "BFSI vertical (32% of revenue) exposed to US and European bank capex cuts"
  ],
  "summary": "TCS presents one of the strongest fundamental profiles in Indian IT — near-zero leverage, elite ROE of 46%, and ₹44,000 Cr of annual free cash flow. The primary concern is a cyclical growth deceleration in the core BFSI vertical, which bears monitoring over the next 2 quarters."
}
```

### Known limitations

- **yFinance rate limits:** Yahoo Finance imposes informal rate limits.
  Rapid repeated calls return 429 errors. Redis caching (15 min TTL)
  mitigates this in normal usage.
- **Alpha Vantage free tier:** 25 requests/day. Once exhausted, ratio
  fields (`roe_pct`, `roce_pct`, PE, PB) fall back to None. The agent
  degrades gracefully — score is computed from available data only.
- **Historical depth:** yFinance returns up to 4 years of annual
  statements for most Indian tickers. Some smaller-cap or recently-listed
  companies may have fewer years, which reduces CAGR accuracy.
- **Currency:** All financial values are in ₹ crore as reported. No
  currency conversion is performed.
- **Ticker resolution:** The agent assumes the `ticker` field in
  `InvestmentState` already carries the correct `.NS` or `.BO` suffix.
  The Planner node (T-029) is responsible for resolving company names
  to tickers.

---

## 4. Agent 2 — Technical Analyst

### Persona

> _"You are a seasoned technical chart analyst with 15 years of experience
> reading price action on Indian equity markets (NSE and BSE). You
> specialise in trend identification, momentum analysis, and identifying
> key support and resistance levels."_

### Mandate

Evaluate price trends, 50-day and 200-day moving averages, RSI momentum,
and 52-week positioning. Produce a directional signal (BUY / HOLD / SELL)
with a conviction score (1–10).

### Tools

| Tool                | Source         | Cache TTL | Purpose                                |
| ------------------- | -------------- | --------- | -------------------------------------- |
| `fetch_stock_price` | yFinance OHLCV | 15 min    | 1-year daily OHLCV data (~260 candles) |

### Indicator computation

All indicator computation is pure Python (no TA-Lib dependency):

| Indicator         | Formula                                  | Minimum candles |
| ----------------- | ---------------------------------------- | --------------- |
| MA-50             | Simple moving average of last 50 closes  | 50              |
| MA-200            | Simple moving average of last 200 closes | 200             |
| RSI-14            | Wilder's RSI on 14-period gains/losses   | 15              |
| Golden Cross      | MA-50 > MA-200                           | 200             |
| Momentum 1M/3M/6M | `(P_now / P_n_periods_ago - 1) × 100`    | 22 / 66 / 130   |
| Volume trend      | Average volume last 30d vs prior 30d     | 60              |
| 52-week high/low  | Max/min close over trailing 252 candles  | 1               |

When fewer than the minimum candles are available, the indicator is
returned as `None` (not an error). The LLM receives the available
indicators and generates a `summary` contextualised to what is known.

### Signal derivation

The `signal` field (BUY / HOLD / SELL) and `signal_strength` (1–10) are
synthesised by the LLM from the pre-computed indicators. The LLM is
instructed to follow standard technical interpretation conventions:

- RSI < 30 + price above MA-50 → strong BUY signal
- RSI > 70 + price below MA-50 → SELL consideration
- Golden cross present → bullish bias
- Price within 2% of 52-week high → momentum BUY
- Price > 20% below 52-week high → bearish signal

### Output schema — `TechnicalAnalysis`

| Field                   | Type            | Constraints   | Description                                |
| ----------------------- | --------------- | ------------- | ------------------------------------------ |
| `signal`                | `str`           | —             | `"BUY"`, `"HOLD"`, or `"SELL"`             |
| `signal_strength`       | `int`           | `ge=1, le=10` | Conviction level                           |
| `current_price`         | `float \| None` | —             | Latest close price (₹)                     |
| `week_52_high`          | `float \| None` | —             | 52-week high (₹)                           |
| `week_52_low`           | `float \| None` | —             | 52-week low (₹)                            |
| `price_vs_52w_high_pct` | `float \| None` | —             | Current price as % of 52w high             |
| `ma_50d`                | `float \| None` | —             | 50-day SMA (₹)                             |
| `ma_200d`               | `float \| None` | —             | 200-day SMA (₹)                            |
| `price_above_ma50`      | `bool \| None`  | —             | Price above MA-50                          |
| `price_above_ma200`     | `bool \| None`  | —             | Price above MA-200                         |
| `golden_cross`          | `bool \| None`  | —             | MA-50 > MA-200                             |
| `rsi_14`                | `float \| None` | —             | 14-period RSI                              |
| `momentum_1m_pct`       | `float \| None` | —             | 1-month return (%)                         |
| `momentum_3m_pct`       | `float \| None` | —             | 3-month return (%)                         |
| `momentum_6m_pct`       | `float \| None` | —             | 6-month return (%)                         |
| `volume_trend`          | `str \| None`   | —             | `"increasing"`, `"decreasing"`, `"stable"` |
| `support_levels`        | `list[float]`   | default `[]`  | Key support levels (₹)                     |
| `resistance_levels`     | `list[float]`   | default `[]`  | Key resistance levels (₹)                  |
| `summary`               | `str`           | default `""`  | 2–3 sentence PM-ready summary              |

### Example JSON output

```json
{
  "agent_name": "technical_analyst",
  "analysis_id": "3f8a2c1d-0e4b-4c7a-9f2e-1b5d6e8f0a3c",
  "company_name": "Tata Consultancy Services",
  "ticker": "TCS.NS",
  "generated_at": "2024-01-15T09:32:19.448Z",
  "error": null,
  "signal": "BUY",
  "signal_strength": 7,
  "current_price": 3859.5,
  "week_52_high": 4255.85,
  "week_52_low": 3056.05,
  "price_vs_52w_high_pct": 90.7,
  "ma_50d": 3782.3,
  "ma_200d": 3541.65,
  "price_above_ma50": true,
  "price_above_ma200": true,
  "golden_cross": true,
  "rsi_14": 62.4,
  "momentum_1m_pct": 3.2,
  "momentum_3m_pct": 8.7,
  "momentum_6m_pct": 14.1,
  "volume_trend": "increasing",
  "support_levels": [3782.3, 3650.0, 3541.65],
  "resistance_levels": [4000.0, 4255.85],
  "summary": "TCS is in a confirmed uptrend with both MA crossovers bullish (golden cross present) and RSI at 62 — strong momentum without being overbought. Price is within 10% of 52-week highs and volume is expanding, which supports the BUY signal with high conviction."
}
```

### Known limitations

- **OHLCV availability:** yFinance returns daily OHLCV for approximately
  1 year (252 trading days). Newly-listed stocks or illiquid instruments
  may have fewer candles, causing MA-200 and long-momentum metrics to be
  `None`.
- **Intraday signals:** The agent uses daily closes only. Intraday
  patterns (head and shoulders, flags, etc.) are not computed.
- **Support/resistance:** Levels are LLM-identified from round numbers
  and moving averages visible in the indicator set — not computed from
  fractal highs/lows. Treat them as approximate.
- **No fundamental context:** The technical agent is intentionally
  isolated from fundamentals. It reads only price and volume. The
  Portfolio Manager reconciles the technical signal with fundamental
  and macro inputs.
- **Flat price series:** If all closes are identical (e.g. illiquid
  stocks), RSI computes as 100. This is mathematically correct but
  should be interpreted cautiously.

---

## 5. Agent 3 — News Sentiment Agent

### Persona

> _"You are a sharp financial journalist who has covered Indian equities
> for 15 years. You read market news the way a seasoned reporter does —
> looking for the story behind the story, spotting management credibility
> gaps, regulatory smoke signals, and momentum shifts before they become
> consensus."_

### Mandate

Analyse the last 30 days of news for a given company. Score aggregate
sentiment from -1.0 (very negative) to +1.0 (very positive). Surface
specific red flags such as SEBI notices, fraud allegations, management
misconduct, and earnings restatements.

### Tools

| Tool              | Source                 | Cache TTL | Purpose                                                  |
| ----------------- | ---------------------- | --------- | -------------------------------------------------------- |
| `fetch_news`      | NewsAPI                | 60 min    | Last 30 days of headlines and snippets (max 20 articles) |
| `semantic_search` | ChromaDB (`airp_news`) | —         | Similarity search on previously ingested news embeddings |

ChromaDB search is non-fatal — if it fails, the agent continues with
NewsAPI data alone.

### Scoring architecture

Sentiment scoring uses a **three-layer** approach:

```
Layer 1 — Deterministic keyword scoring (pure Python, no LLM):
  _score_article(title, description)  →  float in [-1.0, 1.0]
  _aggregate_scores(scores)           →  arithmetic mean, clamped
  _label_from_score(score)            →  band label
  _detect_red_flags(texts)            →  keyword scanner

Layer 2 — LLM narrative synthesis:
  Top positive/negative headline selection
  Dominant topic identification
  Red flag narrative augmentation
  2-3 sentence summary

Layer 3 — Merge:
  sentiment_score and sentiment_label  →  always from Layer 1
  red_flags  →  union of Layer 1 + Layer 2 (deduplicated)
```

**Score bands:**

| Score range  | Label           |
| ------------ | --------------- |
| > 0.3        | `very_positive` |
| 0.1 to 0.3   | `positive`      |
| -0.1 to 0.1  | `neutral`       |
| -0.3 to -0.1 | `negative`      |
| < -0.3       | `very_negative` |

**Red flag triggers (deterministic):** `sebi`, `fraud`, `investigation`,
`probe`, `insider trading`, `accounting restatement`, `whistleblower`,
`arrested`, `default`, `manipulation`, `ed raid`, `cbi`, `promoter pledge`,
`pledging`, `resign`, `ceo quit` — and others. See `RED_FLAG_PHRASES` in
`backend/agents/sentiment_analyst.py`.

### Output schema — `SentimentAnalysis`

| Field                    | Type        | Constraints       | Description                    |
| ------------------------ | ----------- | ----------------- | ------------------------------ |
| `sentiment_score`        | `float`     | `ge=-1.0, le=1.0` | Aggregate score                |
| `sentiment_label`        | `str`       | —                 | Human-readable band label      |
| `articles_analysed`      | `int`       | `ge=0`            | Number of articles processed   |
| `positive_articles`      | `int`       | `ge=0`            | Articles with score > 0.1      |
| `negative_articles`      | `int`       | `ge=0`            | Articles with score < -0.1     |
| `neutral_articles`       | `int`       | `ge=0`            | Articles with \|score\| ≤ 0.1  |
| `red_flags`              | `list[str]` | default `[]`      | Specific red flag descriptions |
| `red_flag_count`         | `int`       | `ge=0`            | len(red_flags)                 |
| `top_positive_headlines` | `list[str]` | default `[]`      | Up to 3 top positive headlines |
| `top_negative_headlines` | `list[str]` | default `[]`      | Up to 3 top negative headlines |
| `dominant_topics`        | `list[str]` | default `[]`      | 3–5 dominant news themes       |
| `summary`                | `str`       | default `""`      | 2–3 sentence PM-ready summary  |

### Example JSON output

```json
{
  "agent_name": "news_sentiment",
  "analysis_id": "3f8a2c1d-0e4b-4c7a-9f2e-1b5d6e8f0a3c",
  "company_name": "Tata Consultancy Services",
  "ticker": "TCS.NS",
  "generated_at": "2024-01-15T09:32:22.817Z",
  "error": null,
  "sentiment_score": 0.34,
  "sentiment_label": "very_positive",
  "articles_analysed": 18,
  "positive_articles": 13,
  "negative_articles": 2,
  "neutral_articles": 3,
  "red_flags": [],
  "red_flag_count": 0,
  "top_positive_headlines": [
    "TCS bags $500 million multi-year digital transformation deal from US retailer",
    "TCS Q3 results beat Street — PAT up 8.2% YoY, dividend of ₹28 declared",
    "TCS AI platform GenAI Studio sees enterprise adoption surge"
  ],
  "top_negative_headlines": [
    "TCS attrition ticks up to 13.3% amid BFSI project delays"
  ],
  "dominant_topics": [
    "Large deal wins in North America",
    "AI and GenAI platform adoption",
    "Q3 earnings beat",
    "BFSI vertical softness",
    "Talent retention"
  ],
  "summary": "TCS news sentiment is strongly positive over the last 30 days, driven by a major deal win and a Q3 earnings beat. No governance or regulatory red flags detected. The only modest negative is a slight uptick in attrition that management attributed to normalisation post-pandemic."
}
```

### Known limitations

- **NewsAPI free tier:** 100 requests/day. Once exhausted, `fetch_news`
  returns an error dict and the agent returns a neutral score with
  `error` set.
- **Article quality:** NewsAPI returns headlines and short snippets — not
  full article text. Sentiment scoring is based on headlines and
  200-character descriptions. Deep investigative stories may be
  under-scored.
- **Language:** Only English-language news is processed. Vernacular
  Indian media (Hindi, Gujarati financial press) is not covered.
- **Keyword scorer limitations:** The keyword-weight approach can
  mis-score articles with sarcasm, negation ("did not miss"), or
  context-dependent language. The LLM narrative synthesis partially
  corrects for this but does not override the numeric score.
- **ChromaDB dependency:** Semantic search improves context when
  earnings transcripts and prior news have been ingested. Without
  prior ingestion, the ChromaDB search returns empty results
  (non-fatal).

---

## 6. Agent 4 — Macro Economist

### Persona

> _"You are a macro economist with 20 years of experience covering Indian
> equity markets. You cut through noise to identify the macro forces that
> actually move stock prices — RBI rate cycles, inflation trajectories,
> GDP momentum, and currency trends."_

### Mandate

Assess the Indian macroeconomic environment. Classify the RBI rate stance,
inflation trend, and macro environment. Derive the sector-specific macro
impact (tailwind / neutral / headwind) for the company under analysis.

### Tools

| Tool               | Source                         | Cache TTL | Purpose                               |
| ------------------ | ------------------------------ | --------- | ------------------------------------- |
| `fetch_macro_data` | RBI website, MOSPI, World Bank | 24 hrs    | Repo rate, CPI inflation, GDP growth  |
| `semantic_search`  | ChromaDB (`airp_news`)         | —         | Sector macro news context (non-fatal) |

### Classification logic

All classifications are deterministic before the LLM call:

**Rate stance** (from RBI repo rate):

| Repo rate   | Stance                  |
| ----------- | ----------------------- |
| < 5.0%      | `accommodative`         |
| 5.0 – 5.99% | `neutral`               |
| 6.0 – 6.99% | `calibrated_tightening` |
| ≥ 7.0%      | `tightening`            |

**Rate direction** (vs neutral midpoint 6.0%):

| Repo rate vs 6.0% | Direction |
| ----------------- | --------- |
| Below             | `cutting` |
| Equal             | `holding` |
| Above             | `hiking`  |

**Inflation trend** (from CPI):

| CPI         | Trend     |
| ----------- | --------- |
| < 4.0%      | `falling` |
| 4.0 – 5.99% | `stable`  |
| ≥ 6.0%      | `rising`  |

**Sector impact** is looked up from a 9-sector × 4-stance rule table.
Key rules relevant to the acceptance criteria:

| Sector              | Rate stance     | Impact                                                               |
| ------------------- | --------------- | -------------------------------------------------------------------- |
| `banking`           | `tightening`    | **headwind** (NIM compression, higher cost of funds)                 |
| `banking`           | `accommodative` | **tailwind** (loan demand surge, mark-to-market gains)               |
| `nbfc`              | `tightening`    | **headwind** (spread compression, liquidity tightening)              |
| `auto`              | `tightening`    | **headwind** (EMI affordability, dealer inventory costs)             |
| `it_services`       | `tightening`    | **neutral** (USD-denominated revenue, insulated from domestic rates) |
| `pharma_healthcare` | any             | **neutral** (inelastic demand)                                       |

**Sector detection** uses keyword matching on `company_name`. Sectors:
`banking`, `nbfc`, `it_services`, `energy`, `pharma_healthcare`, `auto`,
`fmcg`, `infra_industrials`, `diversified` (default).

### Output schema — `MacroAnalysis`

| Field               | Type            | Constraints  | Description                                                                  |
| ------------------- | --------------- | ------------ | ---------------------------------------------------------------------------- |
| `macro_environment` | `str`           | required     | `"favourable"`, `"neutral"`, or `"unfavourable"`                             |
| `sector_impact`     | `str`           | required     | `"tailwind"`, `"neutral"`, or `"headwind"`                                   |
| `rbi_repo_rate_pct` | `float \| None` | —            | RBI repo rate (%)                                                            |
| `rate_stance`       | `str \| None`   | —            | `"accommodative"` / `"neutral"` / `"calibrated_tightening"` / `"tightening"` |
| `rate_direction`    | `str \| None`   | —            | `"cutting"` / `"holding"` / `"hiking"`                                       |
| `cpi_inflation_pct` | `float \| None` | —            | CPI (%)                                                                      |
| `wpi_inflation_pct` | `float \| None` | —            | WPI (%)                                                                      |
| `inflation_trend`   | `str \| None`   | —            | `"rising"` / `"stable"` / `"falling"`                                        |
| `gdp_growth_pct`    | `float \| None` | —            | GDP growth (%)                                                               |
| `gdp_forecast_pct`  | `float \| None` | —            | IMF/World Bank GDP forecast (%)                                              |
| `tailwinds`         | `list[str]`     | default `[]` | Sector-specific macro tailwinds                                              |
| `headwinds`         | `list[str]`     | default `[]` | Sector-specific macro headwinds                                              |
| `usd_inr_rate`      | `float \| None` | —            | USD/INR rate (Phase 4 enrichment)                                            |
| `inr_trend`         | `str \| None`   | —            | `"appreciating"` / `"stable"` / `"depreciating"`                             |
| `summary`           | `str`           | default `""` | 2–3 sentence PM-ready summary                                                |

### Example JSON output

```json
{
  "agent_name": "macro_economist",
  "analysis_id": "3f8a2c1d-0e4b-4c7a-9f2e-1b5d6e8f0a3c",
  "company_name": "Tata Consultancy Services",
  "ticker": "TCS.NS",
  "generated_at": "2024-01-15T09:32:25.003Z",
  "error": null,
  "macro_environment": "favourable",
  "sector_impact": "neutral",
  "rbi_repo_rate_pct": 6.5,
  "rate_stance": "calibrated_tightening",
  "rate_direction": "hiking",
  "cpi_inflation_pct": 5.1,
  "wpi_inflation_pct": null,
  "inflation_trend": "stable",
  "gdp_growth_pct": 7.2,
  "gdp_forecast_pct": null,
  "tailwinds": [
    "INR depreciation trend benefits TCS's USD-denominated revenue realisations",
    "Strong India GDP growth of 7.2% supports domestic BFSI and telecom IT budgets",
    "Stable inflation within RBI's comfort band reduces near-term rate hike risk"
  ],
  "headwinds": [
    "Concurrent US and European rate hikes are slowing BFSI client tech spend decisions",
    "Global risk-off sentiment creating deal decision delays in discretionary IT segments"
  ],
  "usd_inr_rate": null,
  "inr_trend": null,
  "summary": "India's macro environment is broadly favourable — GDP growing at 7.2% with CPI contained within the RBI's tolerance band. For IT services, the domestic rate cycle is largely irrelevant; the key macro headwind is the US and European slowdown dampening client discretionary spend."
}
```

**Example — banking sector in rate-hike environment:**

```json
{
  "agent_name": "macro_economist",
  "analysis_id": "9a1c3e5f-2b4d-6f8a-0c2e-4d6f8a0c2e4d",
  "company_name": "HDFC Bank",
  "ticker": "HDFCBANK.NS",
  "generated_at": "2024-01-15T09:32:26.112Z",
  "error": null,
  "macro_environment": "unfavourable",
  "sector_impact": "headwind",
  "rbi_repo_rate_pct": 7.5,
  "rate_stance": "tightening",
  "rate_direction": "hiking",
  "cpi_inflation_pct": 7.2,
  "wpi_inflation_pct": null,
  "inflation_trend": "rising",
  "gdp_growth_pct": 5.8,
  "gdp_forecast_pct": null,
  "tailwinds": [
    "Higher rates initially boost treasury income on floating-rate assets"
  ],
  "headwinds": [
    "Rate hike cycle compresses net interest margins as deposit repricing outpaces lending rate increases",
    "Higher cost of funds squeezes NIMs for retail and MSME lenders",
    "Rising rates increase credit risk as EMIs increase for borrowers",
    "Elevated CPI of 7.2% above RBI's 6% upper tolerance constrains MPC room to cut rates"
  ],
  "usd_inr_rate": null,
  "inr_trend": null,
  "summary": "India's macro environment is unfavourable for banking — RBI repo rate at 7.5% (tightening stance) with CPI above the 6% upper tolerance band. HDFC Bank faces meaningful NIM compression headwinds as deposit costs reprice faster than lending rates, and rising EMI burdens increase retail credit risk."
}
```

### Known limitations

- **RBI data scraping:** The RBI website structure can change, causing
  `fetch_macro_data` to fail. The fallback is returning `None` for
  affected fields. The agent uses default classifications when data
  is `None`.
- **CPI vs WPI:** CPI is the primary inflation metric used for
  classification. WPI is fetched where available but not used in
  classification logic (Phase 4 enhancement).
- **Sector detection accuracy:** Keyword matching on `company_name`
  is sufficient for large-cap names but may mis-classify holding
  companies, conglomerates, or companies with ambiguous names.
  The Planner node (T-029) will enrich InvestmentState with a sector
  field in Phase 3.
- **USD/INR:** The `usd_inr_rate` and `inr_trend` fields are populated
  as `None` in Phase 2. Currency enrichment is a Phase 4 task
  (T-037 onwards).
- **Macro data lag:** GDP figures are published quarterly with a 45-day
  lag. CPI is published monthly. The agent uses the most recent
  available data and annotates with `as_of` timestamps.

---

## 7. Agents 5–8 — Phase 4 Stubs

These agents are designed but not yet implemented. They will be built
in T-037 through T-044.

### Agent 5 — Risk Officer

**Mandate:** Reads all four research agent outputs and identifies
governance failures, fraud indicators, regulatory risks, concentration
risks, and management credibility issues.

**Key input:** Full `InvestmentState` (all prior agent outputs).  
**Output model:** `RiskAnalysis` (risk_score 1–10, flags[], summary).

### Agent 6 — Contrarian Investor

**Mandate:** Its only job is to disagree. Finds flaws in every bullish
thesis, surfaces overlooked risks, and challenges assumptions made by
the four research agents and the Risk Officer.

**Key input:** Full debate state including all prior outputs.  
**Output model:** `ContrarianReport` (counter_arguments[], summary).

### Agent 7 — Valuation Agent

**Mandate:** Runs a DCF valuation and compares PE/PB/EV-EBITDA vs sector
peers using Indian market data. Calculates upside/downside to intrinsic
value.

**Tools:** `fetch_ratios`, Screener.in scraper.  
**Output model:** `ValuationOutput` (intrinsic_value, verdict, pe_vs_peers).

### Agent 8 — Portfolio Manager

**Mandate:** Reads the full debate transcript and all agent outputs.
Delivers the final investment decision with a written Investment Memo.

**Key input:** Complete `InvestmentState` after all debate rounds.  
**Output model:** `InvestmentDecision` (verdict: BUY/HOLD/SELL,
conviction_score 1–10, memo: str).

---

## 8. LangGraph Execution Order

```
Planner (T-029)
    │
    ├── Fundamental Analyst  ─┐
    ├── Technical Analyst     ├─ parallel (Send API)
    ├── News Sentiment Agent  │
    └── Macro Economist      ─┘
                              │
                     Debate Round 1
                     (agents read each other's outputs)
                              │
                     Contrarian Investor
                              │
                     Debate Round 2
                              │
                     Risk Officer
                              │
                     Valuation Agent
                              │
                     Portfolio Manager
                              │
                     Report Generator (PDF)
```

State key written by each agent:

| Agent                | State key written      |
| -------------------- | ---------------------- |
| Fundamental Analyst  | `state["fundamental"]` |
| Technical Analyst    | `state["technical"]`   |
| News Sentiment Agent | `state["sentiment"]`   |
| Macro Economist      | `state["macro"]`       |
| Risk Officer         | `state["risk"]`        |
| Contrarian Investor  | `state["contrarian"]`  |
| Valuation Agent      | `state["valuation"]`   |
| Portfolio Manager    | `state["decision"]`    |

---

## 9. Error Handling Convention

All agents follow the same error convention:

1. **Never raise** from the LangGraph node function.
2. On any failure, return a valid Pydantic model with `error` set to a
   descriptive string.
3. LangGraph routing in Phase 3 checks `state["agent_key"]["error"]`.
4. ChromaDB failures are always **non-fatal** — agent continues with
   primary tool data only.
5. LLM failures trigger **fallback summary** — deterministic summary
   built from pre-computed metrics, `error` remains `None`.
6. Tool `error` dicts (returned when the tool itself fails gracefully)
   are distinct from tool **exceptions** (when `tool.invoke()` raises).
   Both are handled — see `TestXxxErrorPaths` in `test_research_agents.py`.

---

## 10. LangSmith Tracing Tags

Every agent node is wrapped with `@traced_agent(agent_name)` from
`backend/agents/tracing.py` (T-026).

Each LangSmith run entry includes:

| Field      | Value                                            |
| ---------- | ------------------------------------------------ |
| Run name   | `agent_name` (e.g. `fundamental_analyst`)        |
| Run type   | `chain`                                          |
| Tags       | `[agent_name, company_name]`                     |
| Metadata   | `{agent_name, analysis_id, company_name}`        |
| Child runs | Tool calls + LLM call (auto-traced by LangChain) |

To enable tracing, set in `.env`:

```env
LANGCHAIN_TRACING_V2=true
LANGSMITH_API_KEY=ls__your_key_here
LANGCHAIN_PROJECT=airp-dev
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

Tracing is automatically disabled in the test environment
(`LANGSMITH_API_KEY` is empty in `test_settings`).
