# T-014 — Build `fetch_macro_data` Tool

**Phase:** 1 — Data Layer & APIs
**Week:** 2
**Branch:** `feat/data-macro`
**Commit prefix:** `feat(data):`
**PR title:** `feat(data): implement macro economic data fetcher for Indian market`

---

## Overview

Implements T-014: a LangChain tool that returns India's three headline macro
indicators — **RBI repo rate**, **CPI inflation**, and **GDP growth** — as a
single validated `MacroData` object. The repo rate is scraped from the RBI
site, CPI from MOSPI, and GDP growth is pulled from the key-less World Bank
indicator API. Each source is fetched independently so that one blocked
scrape degrades a single field rather than failing the whole call. The result
is cached in Redis for 24 hours.

**Two tools delivered:**

| Tool | Data returned |
|------|--------------|
| `fetch_macro_data` | Full `MacroData` — repo rate, CPI, GDP growth, per-source `as_of` dates, sources map, warnings, cache flag |
| `fetch_macro_summary` | Lightweight: the three numbers + warnings only (saves LLM tokens for the Macro Economist agent) |

**Three indicators sourced:**

| Indicator | Source | Method |
|-----------|--------|--------|
| Repo rate (%) | RBI (`rbi.org.in`) | HTML scrape, label-driven regex |
| CPI inflation (% YoY) | MOSPI (`mospi.gov.in`) | HTML scrape, label-driven regex |
| GDP growth (% real) | World Bank API (`NY.GDP.MKTP.KD.ZG`, `mrnev=1`) | Key-less JSON |

**Key production features:**
- Three sources fetched **independently** — a blocked or failed source sets
  only its own field to `None` and appends a warning; the other two still
  populate. The tool never raises to the agent.
- `_http_get` raises a typed `ScrapeBlockedError` on the block-signal statuses
  (401/403/406/429/451/503) so a bot-block is distinguishable from a genuine
  parse miss in the warnings.
- GDP growth uses the **World Bank API rather than a scrape**: the task only
  mandates scraping RBI (repo) and MOSPI (CPI); World Bank exposes the same
  figure as a stable, key-less, rate-limit-free JSON endpoint, so there is no
  reason to add a third fragile scraper.
- Every parsed value is **bounds-checked** (`repo 0–25`, `CPI −5–50`,
  `GDP −25–25`) so a layout change that makes the regex grab a year or an
  index number is rejected rather than returned as a "rate".
- **Redis cache, 24h TTL** via `backend/tools/cache.py` (read-through). A
  result with no data at all is **not** cached, so a temporary block does not
  poison the cache for 24 hours. `force_refresh=True` bypasses the read.
- Standard error-dict return pattern — both `@tool`s always return a dict the
  agent can inspect, never an exception.

**Acceptance criteria:**
- Returns a valid `MacroData` object (verified against fixture HTML/JSON in the
  unit tests — repo 6.5, CPI 5.1, GDP 7.0).
- Fails gracefully if a scrape is blocked — the blocked field becomes `None`
  with a warning, the call still succeeds, and the partial result is cached.
- Cached in Redis for 24h (`cache_ttl_macro = 86400`); cache hit returns
  immediately with `cached=True`.

---

## Files Created in This Task

| File | Action | Purpose |
|------|--------|---------|
| `backend/tools/macro.py` | **CREATE** | Two LangChain tools, `MacroData` model, RBI/MOSPI scrapers, World Bank GDP fetcher, bounds-checked parsers |
| `backend/tools/cache.py` | **CREATE** | Minimal Redis JSON cache helper (`cache_get_json` / `cache_set_json`) — interim seed for T-018's cache decorator |
| `backend/tests/unit/test_macro.py` | **CREATE** | 44 unit tests — all scrapes/HTTP mocked, covers parsers, graceful degradation, cache short-circuit |
| `backend/tests/unit/test_cache.py` | **CREATE** | 12 unit tests — no-op under test env, fake-client round-trip, corrupt/non-dict handling |

> **Note on `cache.py`.** Redis caching is referenced in earlier tools'
> docstrings but no cache module existed yet; **T-018 ("Setup Redis caching
> layer")** is the dedicated task that will turn this into a reusable
> `@cached` decorator. T-014 needs the 24h-cache acceptance criterion now, so
> this ships a deliberately small, well-tested helper that T-018 will absorb
> and generalise. It is scoped to JSON get/set only and is a no-op when
> `ENVIRONMENT=test`, so it never touches Redis in CI.

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Checkout feature branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feat/data-macro
git branch
# → * feat/data-macro
```

---

### Step 2 — Place the files

```
backend/tools/macro.py
backend/tools/cache.py
backend/tests/unit/test_macro.py
backend/tests/unit/test_cache.py
```

---

### Step 3 — Run the tests

```bash
# From repo root, venv active
set ENVIRONMENT=test          # Windows
# export ENVIRONMENT=test     # Git Bash / Mac / Linux

python -m pytest backend/tests/unit/test_macro.py backend/tests/unit/test_cache.py -v
```

**Expected output:**
```
backend/tests/unit/test_macro.py::TestParseRbiRepoRate::test_extracts_repo_rate PASSED
backend/tests/unit/test_macro.py::TestParseMospiCpi::test_extracts_cpi PASSED
backend/tests/unit/test_macro.py::TestParseWorldbankGdp::test_extracts_latest_value PASSED
backend/tests/unit/test_macro.py::TestHttpGet::test_blocked_status_raises[403] PASSED
backend/tests/unit/test_macro.py::TestFetchRepoRate::test_success PASSED
backend/tests/unit/test_macro.py::TestFetchMacroDataCore::test_blocked_source_degrades_others_fill PASSED
backend/tests/unit/test_macro.py::TestFetchMacroDataCore::test_cache_hit_short_circuits PASSED
backend/tests/unit/test_macro.py::TestFetchMacroDataCore::test_all_fail_not_cached PASSED
backend/tests/unit/test_macro.py::TestFetchMacroDataTool::test_returns_all_schema_keys PASSED
...
backend/tests/unit/test_cache.py::TestTestEnvironmentNoOp::test_get_client_returns_none PASSED
backend/tests/unit/test_cache.py::TestWithFakeClient::test_set_then_get_round_trip PASSED
...
====== 56 passed in X.XXs ======
```

Full suite — verify no regressions from T-010 through T-013:

```bash
python -m pytest --tb=short
# → all passed
```

Coverage report for the two new modules:

```bash
python -m pytest backend/tests/unit/test_macro.py backend/tests/unit/test_cache.py -v \
  --cov=backend.tools.macro \
  --cov=backend.tools.cache \
  --cov-report=term-missing
```

---

### Step 4 — Commit

```bash
git add backend/tools/macro.py
git add backend/tools/cache.py
git add backend/tests/unit/test_macro.py
git add backend/tests/unit/test_cache.py

git commit -m "feat(data): add fetch_macro_data tool

- Add MacroData Pydantic model: repo_rate, cpi_inflation, gdp_growth with
  per-source as_of dates, sources map, warnings, fetched_at, cached flag
- Scrape RBI for repo rate and MOSPI for CPI; source GDP growth from the
  key-less World Bank indicator API (NY.GDP.MKTP.KD.ZG, mrnev=1) rather
  than a third fragile scrape
- Fetch all three sources independently: a blocked/failed source sets only
  its own field to None + appends a warning, the other two still populate
- _http_get raises typed ScrapeBlockedError on block statuses
  (401/403/406/429/451/503) vs MacroDataError on other 4xx, ConnectionError
  on 5xx; wrapped in tenacity retry (3 attempts, exp backoff 2-30s)
- Bounds-check every parsed value (repo 0-25, CPI -5-50, GDP -25-25) so a
  layout change cannot return a year or index as a rate
- Add backend/tools/cache.py: minimal Redis JSON get/set helper, no-op under
  ENVIRONMENT=test (interim seed for T-018 cache decorator); cache macro
  result for 24h, never cache an all-None result (avoids poisoning cache)
- force_refresh=True bypasses the cache read
- Add fetch_macro_summary @tool: three numbers + warnings only
- Both tools use the standard error-dict pattern, never raise to the agent
- Add 44 macro + 12 cache unit tests, all HTTP/Redis mocked (zero network
  in CI); covers parsers, graceful degradation, cache short-circuit, and
  the all-fail-not-cached path

Closes #14"

git push -u origin feat/data-macro
```

---

### Step 5 — Open the Pull Request on GitHub

- **Base branch:** `main`
- **Compare branch:** `feat/data-macro`

---

## Pull Request Template

**PR Title:**
`feat(data): implement macro economic data fetcher for Indian market`

---

### Summary

Implements T-014: a LangChain tool that returns India's repo rate, CPI
inflation, and GDP growth as a single validated `MacroData` object. The repo
rate is scraped from RBI and CPI from MOSPI; GDP growth is pulled from the
key-less World Bank indicator API. Each source is fetched independently, so a
blocked scrape degrades exactly one field instead of failing the call. The
result is cached in Redis for 24 hours via a new minimal cache helper that
T-018 will later generalise into a reusable decorator.

### Changes

**`backend/tools/macro.py`**
- `MacroData` — Pydantic output model: `repo_rate`, `cpi_inflation`,
  `gdp_growth` (each `float | None`), per-source `*_as_of` dates, `sources`
  map, `warnings` list, `fetched_at`, `cached`, `source`; `has_any_data`
  property
- `MacroDataError`, `ScrapeBlockedError` — typed exceptions for clean routing
- `_http_get(url)` — tenacity-retried GET; raises `ScrapeBlockedError` on
  block statuses, `ConnectionError` on 5xx, `MacroDataError` on other 4xx
- `_make_soup` — BeautifulSoup with `lxml` → `html.parser` fallback
- `_parse_rbi_repo_rate` / `_parse_mospi_cpi` / `_parse_worldbank_gdp` — pure,
  offline-testable parsers; label-driven regex, all bounds-checked via
  `_in_bounds`
- `_fetch_repo_rate` / `_fetch_cpi` / `_fetch_gdp` — per-source fetchers, each
  returns `(value, as_of, warnings)` and never raises
- `_fetch_macro_data(force_refresh=False)` — read-through cache; on miss,
  fetches the three sources independently, assembles `MacroData`, and caches
  only when `has_any_data`
- `fetch_macro_data` `@tool` — full `MacroData` dict
- `fetch_macro_summary` `@tool` — three numbers + warnings only

**`backend/tools/cache.py`**
- `get_client()` — lazy, memoised Redis connect with `.ping()` verify; returns
  `None` under test env / missing URL / unreachable, and latches unavailable
- `cache_get_json(key)` — returns `dict | None`; never raises; handles miss,
  corrupt JSON, non-dict payloads, and client errors
- `cache_set_json(key, value, ttl_seconds)` — `json.dumps(default=str)`,
  `ex=max(1, ttl)`; returns success bool
- `reset_client()` — test helper
- No-op when `ENVIRONMENT=test` so CI never touches Redis

**`backend/tests/unit/test_macro.py`** (44 tests)
- `TestParseRbiRepoRate` / `TestParseMospiCpi` / `TestParseWorldbankGdp` —
  pure parsers against fixture HTML/JSON, plus bounds-rejection cases
- `TestHttpGet` — parametrized block statuses → `ScrapeBlockedError`,
  500 → `ConnectionError`, 404 → `MacroDataError`
- `TestFetchRepoRate` / `TestFetchCpi` / `TestFetchGdp` — success, blocked,
  parse-miss, error (mocked `requests.get`)
- `TestFetchMacroDataCore` — happy path, writes-to-cache, blocked-source
  degrades while others fill, all-fail-not-cached, cache-hit short-circuits
  (`cached=True`), `force_refresh` bypasses read, corrupt cache falls through
- `TestFetchMacroDataTool` / `TestFetchMacroSummaryTool` — schema keys, error
  dict on failure
- `TestMacroDataModel` — valid, all-None, empty-country raises

**`backend/tests/unit/test_cache.py`** (12 tests)
- `TestTestEnvironmentNoOp` — `get_client` returns `None`, get/set are no-ops
- `TestWithFakeClient` — set→get round-trip, miss, corrupt, non-dict,
  client-error, TTL passed to `set`, datetime serialised via `default=str`
- `TestResetClient` — clears memoised client

### Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_macro.py backend/tests/unit/test_cache.py -v
# → 56 passed

python -m pytest --tb=short
# → all passed, 0 regressions from T-010 … T-013
```

### LangSmith Trace

_Not applicable for this PR — data tool with no LLM calls. Traces appear when
the Macro Economist agent calls this tool in Phase 2 (T-024)._

### Screenshots

Terminal output showing `56 passed` with test class names visible.

### Related Issues

Closes #14

---

## Architecture Notes

### Independent-source fetch and graceful degradation

The core function fetches the three indicators in isolation and merges
whatever succeeds:

```
_fetch_macro_data(force_refresh=False)
    ├── cache_get_json("airp:macro:india")     ← read-through
    │       └── hit → MacroData(**cached, cached=True)   (short-circuit)
    │
    ├── _fetch_repo_rate()   → (6.5,  "as of …", [])      RBI scrape
    ├── _fetch_cpi()         → (None, None, ["MOSPI blocked (403)"])  ← degraded
    ├── _fetch_gdp()         → (7.0,  "2023", [])         World Bank API
    │
    ├── assemble MacroData(repo_rate=6.5, cpi_inflation=None, gdp_growth=7.0,
    │                      sources={"repo_rate": "rbi", "gdp_growth": "worldbank"},
    │                      warnings=["MOSPI blocked (403)"])
    │
    └── if has_any_data: cache_set_json(key, data, ttl=86400)
        else:            skip cache  (don't poison for 24h)
```

A single blocked source (here MOSPI) yields a `MacroData` with `cpi_inflation
= None` and a warning, while `repo_rate` and `gdp_growth` are still returned —
satisfying the "fails gracefully if scrape blocked" criterion.

### Why World Bank for GDP

The task mandates scraping RBI for the repo rate and MOSPI for CPI. It does
not require scraping GDP. The World Bank exposes Indian real GDP growth at
`api.worldbank.org/v2/country/IND/indicator/NY.GDP.MKTP.KD.ZG` as key-less
JSON with `mrnev=1` (most-recent non-empty value), which is far more stable
than scraping a government portal. Using it for the one indicator that has a
clean API keeps two fragile scrapers instead of three.

### Why bounds-check every parsed value

Scraped pages change layout. A regex that today grabs `6.50` from "Policy Repo
Rate: 6.50%" could tomorrow grab `2024` from a nearby date. `_in_bounds`
rejects any value outside a realistic range (`repo 0–25`, `CPI −5–50`,
`GDP −25–25`), so a layout drift produces a `None` + warning rather than a
plausible-looking wrong number reaching the Macro Economist agent.

### `cache.py` and its relationship to T-018

`cache.py` is intentionally minimal — JSON get/set against Redis, nothing
more. It exists because T-014's acceptance criteria require a 24h cache now,
and no cache layer existed yet. **T-018 ("Setup Redis caching layer")** will
generalise this into a reusable `@cached(ttl=...)` decorator applied across
all data tools; at that point `macro.py`'s explicit `cache_get_json` /
`cache_set_json` calls can be replaced by the decorator. Until then this
helper is the single, tested place Redis is touched, and it is a complete
no-op under `ENVIRONMENT=test`.

### Output model structure

```
MacroData
├── country: str                     ("India")
├── repo_rate: float | None          (%, e.g. 6.5)
├── cpi_inflation: float | None      (% YoY, e.g. 5.1)
├── gdp_growth: float | None         (% real, e.g. 7.0)
├── repo_rate_as_of: str | None
├── cpi_as_of: str | None
├── gdp_as_of: str | None
├── sources: dict[str, str]          (e.g. {"repo_rate": "rbi"})
├── warnings: list[str]              (blocked-source / parse-miss alerts)
├── fetched_at: datetime             (UTC)
├── cached: bool                     (True when served from Redis)
└── source: str                      ("live" | "cache")
```

### How the agent uses this tool (Phase 2 — T-024)

```python
# Inside MacroEconomistAgent
from backend.tools.macro import fetch_macro_data

result = fetch_macro_data.invoke({})

if "error" in result:
    return {"error": result["error"], "message": result["message"]}

repo = result["repo_rate"]        # float | None
cpi  = result["cpi_inflation"]    # float | None
gdp  = result["gdp_growth"]       # float | None
warns = result["warnings"]        # flag to agent if a source was blocked
```

### Tool-name reconciliation (`README.md`)

`backend/tools/README.md` currently lists the macro tools as `fetch_rbi_rate`
/ `fetch_gdp` / `fetch_inflation` (one tool per indicator). This task instead
ships a single consolidated `fetch_macro_data` (+ `fetch_macro_summary`),
which matches the T-014 spec — one `MacroData` object covering all three
indicators, fetched and cached together. The README line is left for a
docs-sync pass so this PR stays focused on the tool (same approach as T-013).

---

## EOD Update Template

```
EOD Update [DATE]:
Completed: T-014
Merged to main: feat/data-macro
Current week: 2 | Current phase: 1
Blocker: None
Next session: T-015 — Build fetch_earnings_transcript tool
  (earnings-call transcript fetch + chunk for ChromaDB RAG)
```
