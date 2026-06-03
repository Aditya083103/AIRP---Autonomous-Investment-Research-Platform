# T-005 — Create .env.example and Environment Configuration

| Field | Detail |
|-------|--------|
| **Task ID** | T-005 |
| **Phase** | 0 — Project Setup & Standards |
| **Week** | 1 |
| **Branch** | `setup/env-config` |
| **Status** | ✅ Completed |
| **Merged into** | `main` |

---

## Objective

Document every environment variable the AIRP system will ever need, provide
a committed `.env.example` as the canonical reference, and build a type-safe
`config.py` using Pydantic Settings so the backend never reads raw
`os.getenv()` calls scattered through the codebase.

---

## Acceptance Criteria

| Criteria | Status |
|----------|--------|
| Every API key and config value documented in `.env.example` | ✅ |
| Real `.env` blocked by `.gitignore` | ✅ |
| `.env.example` committed and visible in repo | ✅ |
| All variables have descriptions, types, defaults, and source URLs | ✅ |
| `backend/config.py` provides type-safe access to all variables | ✅ |
| `pydantic-settings` added to `requirements-dev.txt` | ✅ |
| Unit tests for `config.py` computed properties pass | ✅ |
| PR merged via squash and merge | ✅ |

---

## Files Created / Modified

| File | Action | Purpose |
|------|--------|---------|
| `.env.example` | Modified | Fully documented — 10 sections, every variable has description, type, default, and where to get it |
| `.gitignore` | Modified | Tightened — added `.secret`, `generated/`, explicit `frontend/dist/`, cleaner section comments |
| `backend/config.py` | Created | Pydantic Settings v2 class — single source of truth for all env vars; computed fields for `cors_origins_list`, `active_database_url`, `is_production`, `tracing_enabled` |
| `backend/requirements-dev.txt` | Modified | Added `pydantic-settings==2.2.1` — required to import `config.py` in tests |
| `backend/tests/unit/test_config.py` | Created | 13 unit tests covering all computed fields, environment switching, feature flags, and parametrized env validation |

---

## `.env.example` Structure

The file is organised into 10 sections matching the system architecture:

| Section | Variables | Notes |
|---------|-----------|-------|
| 1. Application | `ENVIRONMENT`, `LOG_LEVEL`, `CORS_ORIGINS`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES` | Core app config |
| 2. LLM Provider | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS` | Claude API — all 8 agents |
| 3. Observability | `LANGSMITH_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT`, `LANGCHAIN_ENDPOINT` | LangSmith tracing |
| 4. Database | `DATABASE_URL`, `DATABASE_TEST_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | PostgreSQL (Neon) |
| 5. Cache | `REDIS_URL`, `REDIS_TOKEN`, `CACHE_TTL_*` (4 vars) | Redis (Upstash) |
| 6. Vector Store | `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_COLLECTION`, `EMBEDDING_MODEL` | ChromaDB + sentence-transformers |
| 7. Authentication | `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `CLERK_JWT_ISSUER` | Clerk auth |
| 8. External APIs | `NEWS_API_KEY`, `ALPHA_VANTAGE_KEY`, `SCREENER_BASE_URL`, `RBI_BASE_URL` | Market data sources |
| 9. Frontend (Vite) | `VITE_API_URL`, `VITE_CLERK_PUBLISHABLE_KEY`, `VITE_APP_NAME`, `VITE_ANALYSIS_TIMEOUT_MS` | React env vars |
| 10. Feature Flags | `FEATURE_DEBATE_ENABLED`, `DEBATE_ROUNDS`, `FEATURE_PDF_ENABLED`, `FEATURE_RATE_LIMITING`, `MAX_CONCURRENT_ANALYSES` | Runtime toggles |

---

## `config.py` Design

### Why Pydantic Settings instead of `os.getenv()`?
Raw `os.getenv()` calls scattered through the codebase have three problems:
1. **No type safety** — everything is `str | None`; you cast manually everywhere
2. **No validation** — a missing key is only discovered when that code path runs
3. **No discoverability** — there is no single place to see all variables

Pydantic Settings solves all three: types are declared, missing required fields
raise `ValidationError` at startup (fail fast), and `config.py` is the single
source of truth.

### `@lru_cache` on `get_settings()`
Without `lru_cache`, every `from config import settings` call would re-read
`.env` from disk. With `lru_cache`, `.env` is read exactly once per process.
In tests, `get_settings.cache_clear()` resets it so you can test different
configurations.

### `active_database_url` computed field
Returns `database_test_url` when `ENVIRONMENT=test`, otherwise `database_url`.
This means application code never needs to check the environment — it always
calls `settings.active_database_url` and gets the right database automatically.

### `VITE_` prefix rule
All frontend environment variables must be prefixed with `VITE_`. Vite's build
process strips all non-`VITE_` variables from the browser bundle for security.
`CLERK_PUBLISHABLE_KEY` is therefore duplicated as `VITE_CLERK_PUBLISHABLE_KEY`
— same value, different variable name for frontend consumption.

---

## Problems Encountered & Solutions

### 1. `pydantic-settings` is a separate package in Pydantic v2
**Problem:** In Pydantic v1, `BaseSettings` was part of `pydantic` itself.
In Pydantic v2, it was extracted into a separate package `pydantic-settings`.
Attempting to `from pydantic import BaseSettings` fails with `ImportError`.

**Solution:** Added `pydantic-settings==2.2.1` to `requirements-dev.txt`. The
import becomes `from pydantic_settings import BaseSettings, SettingsConfigDict`.

### 2. mypy flags `@computed_field` decorated properties
**Problem:** mypy strict mode raises `[misc]` on `@computed_field` decorated
properties, the same issue seen with `@pytest.fixture` in T-004.

**Solution:** Added `# type: ignore[misc]` on each `@computed_field` decorator
line. This is the established pattern in this codebase for decorators that
mypy strict cannot type — suppress the specific error code rather than
disabling broader checks.

### 3. `DATABASE_TEST_URL` must be a genuinely separate database
**Problem:** If `DATABASE_TEST_URL` pointed to the same database as
`DATABASE_URL`, running `pytest` could delete or corrupt development data
(especially once database migration tests exist in Phase 1).

**Solution:** `DATABASE_TEST_URL` defaults to `airp_test` (a separate database)
and `active_database_url` automatically selects it when `ENVIRONMENT=test`. The
`conftest.py` environment guard from T-004 prevents tests from running unless
`ENVIRONMENT=test` is explicitly set, adding a second layer of protection.

---

## Key Decisions

**Why document `SCREENER_BASE_URL` and `RBI_BASE_URL` if they're just defaults?**
These URLs could change — Screener.in might restructure their site, RBI might
move their data portal. Documenting them as configurable variables means they
can be overridden without a code change. It also makes the scraping targets
visible and auditable from the `.env.example`.

**Why a `FEATURE_*` section at all in Phase 0?**
Feature flags are cheapest to design at the start. Adding them later requires
finding and updating every place that assumes a feature is always on. With
`FEATURE_DEBATE_ENABLED=false`, the debate loop can be bypassed entirely during
early Phase 2 development — running 4 agents without the debate round is much
faster and cheaper for iteration.

**Why `ANTHROPIC_MODEL` as a configurable variable?**
The model string is the single most impactful configuration choice in the
system. Having it in `.env` means switching from Sonnet to Haiku for development
(to reduce cost) or to Opus for final demo quality requires zero code changes.

---

## Learnings

- `pydantic-settings` is a separate pip package from `pydantic` in v2. Always
  install both when using `BaseSettings`.
- The `VITE_` prefix rule is strict — any React environment variable without
  it is silently unavailable in the browser. No error, just `undefined`.
- `lru_cache` on `get_settings()` is not optional — without it, `.env` is
  re-read on every import, which slows down tests significantly.
- Feature flags belong in environment config, not hardcoded in source. The
  cost to add them upfront is near zero; the cost to add them later is high.
- `DATABASE_TEST_URL` and the `active_database_url` computed field together
  mean application code is database-environment-agnostic by default.
