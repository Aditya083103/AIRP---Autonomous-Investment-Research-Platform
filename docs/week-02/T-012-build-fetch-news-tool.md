# T-012 — Build `fetch_news` Tool

**Phase:** 1 — Data Layer & APIs
**Week:** 2
**Branch:** `feat/data-news`
**Commit prefix:** `feat(tools):`
**PR title:** `feat(tools): add fetch_news and fetch_news_summary tools with tenacity retry and Pydantic models`

---

## Overview

Implements T-012: two LangChain tools wrapping the NewsAPI v2 `/everything`
endpoint to retrieve the last 30 days of English news articles for a company.
Returns a fully-typed `NewsResult` Pydantic model so the News Sentiment Agent
always receives structured, validated data.

**Two tools delivered:**

| Tool                 | Data returned                                                        |
| -------------------- | -------------------------------------------------------------------- |
| `fetch_news`         | Full article list with title, URL, description, source, timestamp    |
| `fetch_news_summary` | Lightweight: headline list only (saves LLM tokens in context window) |

**Key production features:**

- HTTP 429 handled with tenacity exponential back-off (2s → 60s, 3 attempts)
- `requests.Timeout` and `requests.ConnectionError` also retried
- Malformed / `[Removed]` articles silently skipped (never crash the agent)
- `NEWS_API_KEY` resolved from `os.environ` first, then `settings` — safe in test
- `data_warnings` list surfaces non-fatal issues to the agent

**Acceptance criteria:**

- Returns ≥5 articles for known companies (given NewsAPI returns them)
- HTTP 429 triggers tenacity retry → surfaces `rate_limit_exhausted` error dict
- Unit tests use only mocked `requests.get` calls — zero real API calls

---

## Files Created in This Task

| File                              | Action     | Purpose                                                                     |
| --------------------------------- | ---------- | --------------------------------------------------------------------------- |
| `backend/tools/news.py`           | **CREATE** | Two LangChain tools, Pydantic models, retry logic, parse helpers            |
| `backend/tests/unit/test_news.py` | **CREATE** | 40+ unit tests — all HTTP mocked, covers retry, malformed data, error paths |

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Checkout feature branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feat/data-news
git branch
# → * feat/data-news
```

---

### Step 2 — Place the files

```
backend/tools/news.py
backend/tests/unit/test_news.py
```

---

### Step 3 — Run the tests

```bash
# From repo root, venv active
set ENVIRONMENT=test      # Windows
# export ENVIRONMENT=test  (Git Bash / Mac / Linux)

python -m pytest backend/tests/unit/test_news.py -v
```

**Expected output:**

```
backend/tests/unit/test_news.py::TestParseArticles::test_returns_list_of_news_articles PASSED
backend/tests/unit/test_news.py::TestParseArticles::test_skips_removed_placeholder PASSED
backend/tests/unit/test_news.py::TestCallNewsapi::test_returns_json_on_200 PASSED
backend/tests/unit/test_news.py::TestFetchNewsTool::test_returns_at_least_5_articles PASSED
...
====== 40+ passed in X.XXs ======
```

Full suite (no regressions from T-010 and T-011):

```bash
python -m pytest --tb=short
# → all passed
```

Coverage:

```bash
python -m pytest backend/tests/unit/test_news.py -v --cov=backend.tools.news --cov-report=term-missing
```

---

### Step 4 — Commit

```bash
git add backend/tools/news.py
git add backend/tests/unit/test_news.py

git commit -m "feat(tools): add fetch_news and fetch_news_summary tools with tenacity retry

- Implement NewsArticle, NewsResult Pydantic output models with validators
- Wrap NewsAPI /everything endpoint: last 30 days, English, sortBy publishedAt
- Add tenacity retry: HTTP 429, requests.Timeout, ConnectionError
  (exponential back-off 2s → 60s, max 3 attempts)
- Add _parse_articles(): skip [Removed] placeholders, bad URLs, invalid dates
- Separate _call_newsapi() and _fetch_news_from_api() for testability
- Implement fetch_news_summary: headline-only format to reduce LLM token usage
- Resolve NEWS_API_KEY from os.environ then settings (test-safe)
- Add 40+ unit tests with mocked requests.get (zero real API calls)
- Handle: 401 invalid key, 429 rate limit, 5xx transient, missing key

Closes #12"

git push -u origin feat/data-news
```

---

### Step 5 — Open the Pull Request on GitHub

- **Base branch:** `main`
- **Compare branch:** `feat/data-news`

---

## Pull Request Template

**PR Title:**
`feat(tools): add fetch_news and fetch_news_summary tools with tenacity retry and Pydantic models`

---

### Summary

Implements T-012: two LangChain tools wrapping NewsAPI to fetch the last 30
days of news for a company. Handles HTTP 429 rate limiting with tenacity
exponential back-off so the pipeline never crashes on quota exhaustion.
Malformed articles are silently skipped. All monetary/structural data validated
through Pydantic models.

### Changes

**`backend/tools/news.py`**

- `NewsArticle` — title, description, url, source_name, published_at, content_snippet
- `NewsResult` — full result envelope with warnings, metadata, article list
- `NewsAPIError` / `NewsAPIRateLimitError` — typed exceptions for routing
- `_call_newsapi()` — HTTP GET with `@retry` decorator (tenacity); handles 429,
  401, 400, 5xx, Timeout, ConnectionError distinctly
- `_parse_articles()` — filters `[Removed]` placeholders, empty URLs, bad timestamps
- `_fetch_news_from_api()` — core logic: builds query, resolves key, calls API
- `fetch_news` `@tool` — full article list with all metadata
- `fetch_news_summary` `@tool` — headline-only lightweight format

**`backend/tests/unit/test_news.py`**

- 40+ unit tests, all HTTP mocked via `patch("backend.tools.news.requests.get")`
- Uses `__wrapped__` to bypass tenacity on retry-specific tests
- `TestParseArticles` — removed, empty, bad date, None description
- `TestCallNewsapi` — 200, 429, 401, 400, 500; API key in headers
- `TestFetchNewsFromApi` — ≥5 articles, ticker suffix stripping, date range,
  max_articles cap, zero results warning, missing API key
- `TestFetchNewsTool` / `TestFetchNewsSummaryTool` — success, error dicts,
  expected keys, default max_articles
- `TestNewsArticleValidation` — empty title, bad URL, None description

### Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_news.py -v
# → 40+ passed

python -m pytest --tb=short
# → all passed, 0 regressions
```

### LangSmith Trace

_Not applicable for this PR — data tool with no LLM calls. Traces appear when
the News Sentiment Agent calls this tool in T-024 (Phase 2)._

### Related Issues

Closes #12

---

## Architecture Notes

### Key design decisions

| Decision                                                  | Rationale                                                                                                                             |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `_call_newsapi()` separated from `_fetch_news_from_api()` | tenacity `@retry` wraps only the HTTP layer; business logic (query building, parsing) is not retried                                  |
| `__wrapped__` in tests                                    | tenacity decorates the function; `__wrapped__` gives direct access to the undecorated version so retry tests don't sleep for 60s      |
| `os.environ` first for API key                            | Allows `os.environ["NEWS_API_KEY"] = "test-key"` in tests without importing settings (which needs a DB URL)                           |
| `[Removed]` filter in `_parse_articles`                   | NewsAPI returns this placeholder for articles that were deleted or deindexed after being cached                                       |
| `content_snippet` not `content`                           | NewsAPI free tier truncates content to ~200 chars + `[+XXXX chars]`. Renaming signals to agents that this is NOT the full text        |
| `fetch_news_summary`                                      | News Sentiment Agent's debate responses only need headline sentiment counts — sending 20 full articles wastes ~4000 tokens of context |

### How the retry works

```
fetch_news.invoke({"company_name": "Infosys"})
    └── _fetch_news_from_api()
            └── _call_newsapi()  ← @retry wraps THIS function only
                    ├── attempt 1: HTTP 429 → raise NewsAPIRateLimitError
                    │   └── tenacity waits 2s
                    ├── attempt 2: HTTP 429 → raise NewsAPIRateLimitError
                    │   └── tenacity waits 4s
                    ├── attempt 3: HTTP 429 → raise NewsAPIRateLimitError
                    │   └── tenacity reraises (stop_after_attempt=3)
                    └── RetryError bubbles up to fetch_news @tool
                            └── returns {"error": "rate_limit_exhausted", ...}
```

### NewsAPI query format

For a company with ticker:

```
"Tata Consultancy Services" OR TCS
```

For a company without ticker:

```
"Infosys"
```

The full company name is always quoted for phrase matching. The base ticker
(without `.NS`/`.BO` suffix) is added unquoted so articles using just "TCS"
are also caught.

### How agents use this tool (Phase 2 — T-024)

```python
# Inside NewsSentimentAgent
from backend.tools.news import fetch_news

result = fetch_news.invoke({
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "max_articles": 30,
})

if "error" in result:
    return {"error": result["error"], "message": result["message"]}

articles = result["articles"]          # list of dicts
total_coverage = result["total_results"]  # how much news exists
warnings = result["warnings"]          # non-fatal issues

for article in articles:
    title = article["title"]
    published = article["published_at"]   # ISO 8601 string after model_dump
    source = article["source_name"]
```

### Output model structure

```
NewsResult
├── company_name: str
├── ticker: str | None
├── query_used: str              (exact string sent to NewsAPI)
├── from_date: str               (YYYY-MM-DD, 30 days ago)
├── to_date: str                 (YYYY-MM-DD, today)
├── total_results: int           (NewsAPI's total count, may > articles_returned)
├── articles_returned: int       (len of articles list)
├── articles: list[NewsArticle]
│   ├── title: str
│   ├── description: str | None
│   ├── url: str
│   ├── source_name: str
│   ├── published_at: datetime   (UTC)
│   └── content_snippet: str | None
├── fetched_at: datetime
├── source: str                  ("newsapi")
└── warnings: list[str]
```

---

## EOD Update Template

```
EOD Update [DATE]:
Completed: T-012
Merged to main: feat/data-news
Current week: 2 | Current phase: 1
Blocker: None
Next session: T-013 — Build fetch_macro_data tool
  (RBI repo rate, CPI inflation, GDP growth — scraper + World Bank API)
```
