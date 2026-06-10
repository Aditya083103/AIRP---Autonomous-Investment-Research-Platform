# T-018 — Setup Redis Caching Layer

**Phase:** 1 — Data Layer & APIs
**Week:** 4
**Branch:** `feat/data-redis-cache`
**Closes:** #18

---

## Overview

T-018 promotes the minimal Redis helper introduced in T-014 into a full,
production-grade caching layer. The deliverable is a `@cached` decorator
that any `_fetch_*()` data tool can use to transparently read from Redis
on a cache hit and write on a miss — with no changes to the tool's core
logic.

### Acceptance Criteria (all met)

| Criterion | How it is satisfied |
|-----------|---------------------|
| Cached calls return in `<10 ms` | Redis GET is O(1); decorator short-circuits before any network call |
| TTLs respected: stock=15 min, news=1 h, macro=24 h, ratios=1 h | `STOCK_TTL=900`, `NEWS_TTL=3600`, `RATIOS_TTL=3600`, `MACRO_TTL=86400` in `redis_client.py` |
| Tests verify cache hits | `TestCachedDecoratorCacheHit` — wrapped function call count = 0 on hit |
| Tests verify cache misses | `TestCachedDecoratorCacheMiss` — live function called + result cached |
| Tests verify TTL forwarding | `TestCachedDecoratorTTL` — parametrised over all four TTL constants |

---

## Git Workflow

### 1. Checkout branch from main

```bash
git checkout main
git pull origin main
git checkout -b feat/data-redis-cache
```

### 2. Files changed

| Action | File |
|--------|------|
| **New** | `backend/db/redis_client.py` |
| **Updated** | `backend/db/__init__.py` |
| **Updated** | `backend/tools/cache.py` |
| **Updated** | `backend/tools/stock_price.py` |
| **Updated** | `backend/tools/news.py` |
| **Updated** | `backend/tools/ratios.py` |
| **Updated** | `backend/tools/macro.py` |
| **New** | `backend/tests/unit/test_redis_client.py` |
| **Updated** | `backend/tests/unit/test_cache.py` |
| **New** | `docs/week-04/T-018-setup-redis-caching-layer.md` |

### 3. Run pre-commit and tests

```bash
# Windows Git Bash — set env first (separate command, no &&)
set ENVIRONMENT=test

# Pre-commit (formatters will auto-fix; if hooks abort, re-add and commit)
git add .
git commit -m "feat(data): setup Redis caching layer with @cached decorator"

# If pre-commit auto-fixes files:
git add .
git commit -m "feat(data): setup Redis caching layer with @cached decorator"

# Run tests
python -m pytest backend/tests/unit/test_redis_client.py -v
python -m pytest backend/tests/unit/test_cache.py -v
python -m pytest --tb=short -q
```

### 4. Push and open PR

```bash
git push -u origin feat/data-redis-cache
```

Then open a PR on GitHub targeting `main`.

---

## Pull Request

### Title

```
feat(data): setup Redis caching layer with @cached decorator (T-018)
```

### Description

```markdown
## Summary

Promotes the minimal T-014 Redis helper into a production-grade caching
layer. Introduces `backend/db/redis_client.py` as the single source of
truth for the Redis connection and TTL constants, and adds a `@cached`
decorator in `backend/tools/cache.py` that wraps any `_fetch_*()` function
with transparent Redis read-through caching.

All four data tools (stock_price, news, ratios, macro) are now wired to
the cache with the correct per-resource TTLs.

## Changes

- **`backend/db/redis_client.py`** (new): centralised Redis client with
  lazy memoised connection, Upstash token support, short timeouts (3 s),
  graceful degradation on failure, and TTL constants for all four tool
  domains.
- **`backend/db/__init__.py`**: exports `get_redis_client`,
  `reset_redis_client`, and all four TTL constants.
- **`backend/tools/cache.py`**: adds `@cached(key=..., ttl=...)` decorator
  with key-template resolution, cache-hit short-circuit, error-result
  bypass (errors never cached), and `functools.wraps` metadata preservation.
  Low-level `cache_get_json` / `cache_set_json` helpers remain for backward
  compatibility with `macro.py`.
- **`backend/tools/stock_price.py`**: `_fetch_stock_cached` wraps
  `_fetch_stock_data` with `@cached(key="airp:stock:{ticker}:{period}",
  ttl=STOCK_TTL)`. `_fetch_from_yfinance` legacy alias preserved for
  existing tests.
- **`backend/tools/news.py`**: `_fetch_news_cached` wraps
  `_fetch_news_from_api` with `@cached(key="airp:news:{company_name}",
  ttl=NEWS_TTL)`.
- **`backend/tools/ratios.py`**: `_fetch_ratios_cached` wraps
  `_fetch_ratios_from_sources` with `@cached(key="airp:ratios:{ticker}",
  ttl=RATIOS_TTL)`. Both `fetch_ratios` and `fetch_ratios_summary` use the
  cache.
- **`backend/tools/macro.py`**: updated to import `MACRO_TTL` from cache
  module; `_cache_ttl()` falls back to it instead of the private
  `_DEFAULT_CACHE_TTL_MACRO` constant.
- **`backend/tests/unit/test_redis_client.py`** (new): 20 tests covering
  test-env no-op, no URL configured, unreachable server, happy path,
  memoisation, Upstash token, and reset.
- **`backend/tests/unit/test_cache.py`** (updated): expanded to 35 tests
  covering all decorator behaviour — hit/miss/error/bad-key/TTL/metadata —
  plus backward-compatible low-level helper tests from T-014.

## Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_redis_client.py -v
python -m pytest backend/tests/unit/test_cache.py -v
python -m pytest --tb=short -q --cov=backend --cov-report=term-missing
```

All tests run offline with no live Redis server (ENVIRONMENT=test bypasses
the connection entirely; fake clients injected via `unittest.mock.patch`).

## LangSmith Trace

N/A — no agent calls in this task.

## Screenshots

N/A — no UI changes.

## Related Issues

Closes #18
```

---

## Architecture Notes

### Module dependency graph (T-018)

```
backend/db/redis_client.py       ← no AIRP deps; pure Redis + stdlib
        ↑
backend/tools/cache.py           ← imports from redis_client (TTLs + client)
        ↑
backend/tools/stock_price.py     ← imports cached, STOCK_TTL from cache
backend/tools/news.py            ← imports cached, NEWS_TTL from cache
backend/tools/ratios.py          ← imports cached, RATIOS_TTL from cache
backend/tools/macro.py           ← imports MACRO_TTL, cache_get_json,
                                   cache_set_json from cache (manual style)
```

`macro.py` still uses the manual `cache_get_json` / `cache_set_json` pattern
rather than `@cached` because its cache key is a fixed constant (`airp:macro:india`)
rather than a function-argument-derived template. Both patterns are valid and
co-exist in the codebase.

### Cache key namespace

| Tool | Redis key pattern | TTL |
|------|-------------------|-----|
| Stock price | `airp:stock:{ticker}:{period}` | 15 min |
| News | `airp:news:{company_name}` | 1 h |
| Ratios | `airp:ratios:{ticker}` | 1 h |
| Macro | `airp:macro:india` (fixed) | 24 h |

All keys are prefixed `airp:` to avoid collisions if the Upstash Redis
instance is shared with other services.

### Graceful degradation chain

```
get_redis_client() called
│
├── ENVIRONMENT=test? → return None (tests always hermetic)
├── _client_unavailable latched? → return None (fast path after first failure)
├── REDIS_URL empty? → latch flag, return None
├── redis.Redis.from_url(url) raises? → latch flag, return None
└── client.ping() raises? → latch flag, return None
    └── PING passes → memoise client, return it
```

A `None` client propagates through `cache_get_json` → returns `None` (miss)
and `cache_set_json` → returns `False` (no-op). The tool continues with live
data as if the cache were not there.

### `@cached` decorator behaviour

```
@cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
def _fetch_stock_cached(ticker: str, period: str) -> dict[str, Any]:
    return _fetch_stock_data(ticker=ticker, period=period)

Call: _fetch_stock_cached(ticker="TCS.NS", period="1y")

  1. Resolve key: "airp:stock:{ticker}:{period}" → "airp:stock:TCS.NS:1y"
  2. cache_get_json("airp:stock:TCS.NS:1y")
     ├── HIT  → return cached dict immediately (0 yFinance calls)
     └── MISS → call _fetch_stock_data(ticker="TCS.NS", period="1y")
                 ├── Result has "error" key? → return without caching
                 └── Success → cache_set_json(key, result, 900)
                               return result
```

### Why errors are not cached

Error responses (dicts containing an `"error"` key) are explicitly not
written to Redis. If yFinance is temporarily unavailable or a ticker is
momentarily unresolvable, caching the error would serve stale failure
responses for up to 15 minutes to every subsequent caller. Transient errors
should resolve on the next request.

---

## Key Learnings

- **`redis.Redis.from_url` + `ping()`** is the correct connection-validation
  pattern. Constructing the client alone does not test connectivity — the
  lazy connection is only established on the first command. Calling `ping()`
  at setup time ensures the "unavailable" latch fires immediately on startup
  rather than on the first tool call mid-analysis.

- **`decode_responses=True` is mandatory.** Without it, `client.get(key)`
  returns `bytes`, not `str`, which causes `json.loads` to accept it (it
  handles `bytes`) but can produce subtle bugs if the byte-string assumption
  leaks elsewhere. Explicit is better.

- **`functools.wraps` on decorators matters for LangSmith tracing.** LangSmith
  reads `__name__` and `__qualname__` to label nodes in traces. Without
  `wraps`, all cached functions would appear as `wrapper` in LangSmith traces,
  making observability useless.

- **Key template resolution via `inspect.signature` + `bind`** is safer than
  `**kwargs` unpacking because it handles positional arguments correctly. A
  caller passing `_fetch(ticker, period)` positionally would fail a naive
  `key.format(**kwargs)` if `ticker` was not in kwargs.

---

## EOD Update Template

```
EOD Update [Date]:
Completed: T-018
Merged to main: feat/data-redis-cache
Current week: 4 │ Current phase: 1
Blocker (if any): None
Next session: T-019 (earnings transcript caching / Phase 1 wrap-up)
```