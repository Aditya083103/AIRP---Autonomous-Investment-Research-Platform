# T-020 — Document Data Layer

**Phase:** 1 — Data Layer & APIs
**Week:** 4
**Branch:** `feat/data-docs`
**Closes:** #20

---

## Overview

T-020 produces `docs/DATA_LAYER.md` — the authoritative reference for every
LangChain data tool built in T-009 through T-019. It covers tool signatures,
Pydantic output schemas with real example JSON, error codes, cache keys and
TTLs, rate limits, and testing patterns.

This is a documentation-only task. No source files are modified. CI passes
trivially (no Python or TypeScript changes).

### Acceptance Criteria

| Criterion | Status |
|---|---|
| `DATA_LAYER.md` covers every tool with example input/output | ✅ All 7 tools documented |
| Error handling notes per tool | ✅ Full error code table per tool + master reference table |
| Rate limit documentation | ✅ Section 9 — all 8 services with free limits |
| Cache key and TTL documentation | ✅ Section 8 — full key registry |
| Testing patterns documented | ✅ Section 12 — unit, integration, and cache test examples |

---

## Git Workflow

### 1. Checkout branch from main

```bash
git checkout main
git pull origin main
git checkout -b feat/data-docs
```

### 2. Files changed

| Action | File |
|---|---|
| **New** | `docs/DATA_LAYER.md` |
| **New** | `docs/week-04/T-020-document-data-layer.md` |

No Python or TypeScript files are modified. CI passes without any additional
changes.

### 3. Stage and commit

```bash
git add docs/DATA_LAYER.md docs/week-04/T-020-document-data-layer.md
git commit -m "docs(data): add DATA_LAYER.md — full data layer reference (T-020)"
```

Pre-commit hooks that run on docs-only changes: `check yaml`, `check toml`,
`check for merge conflicts`, `detect private key`. All pass on `.md` files.

flake8, black, isort, and mypy are not triggered because no `.py` files are staged.

### 4. Push and open PR

```bash
git push -u origin feat/data-docs
```

Open a PR on GitHub targeting `main`.

---

## Pull Request

### Title

```
docs(data): add DATA_LAYER.md — full data layer reference (T-020)
```

### Description

```markdown
## Summary

Adds `docs/DATA_LAYER.md` — the complete reference document for all
seven LangChain data tools built in Phase 1 (T-009 – T-019). Written
directly from the Pydantic source models and tool docstrings to ensure
accuracy, not from memory.

## Changes

- **`docs/DATA_LAYER.md`** (new, 844 lines): covers every tool with:
  - Exact function signatures and parameter tables
  - Real example JSON for success outputs (using TCS.NS as canonical)
  - Complete error code tables per tool
  - Redis cache key patterns and TTLs
  - API rate limits and `.env` configuration reference
  - Ticker convention for NSE/BSE/US
  - Testing patterns (unit, integration, cache)

## Testing

No code changes — CI passes trivially. Verified by running:

    python -m pytest --tb=short -q

All existing tests continue to pass.

## LangSmith Trace

N/A — documentation-only task.

## Screenshots

N/A.

## Related Issues

Closes #20
```

---

## Document Structure

`docs/DATA_LAYER.md` is organised into 12 sections:

| # | Section | What it covers |
|---|---|---|
| 1 | Cache Layer | `@cached` decorator, TTL constants, low-level helpers, env behaviour |
| 2 | fetch_stock_price / fetch_ohlcv | yFinance OHLCV + stats; PriceStats schema; error codes |
| 3 | fetch_financials | Income statement, balance sheet, cash flow; INR Crores normalisation |
| 4 | fetch_ratios | Six ratios with formulas; inputs audit trail; Alpha Vantage gap-fill |
| 5 | fetch_news | NewsAPI; retry policy; rate limit strategy |
| 6 | fetch_macro_data | RBI/MOSPI/World Bank; graceful degradation; force_refresh |
| 7 | fetch_earnings_transcript | Screener.in scrape + PDF upload paths; chunk tool |
| 8 | Cache Keys & TTLs | Complete key registry table |
| 9 | Rate Limits | All 8 external services; free tier limits; .env config |
| 10 | Error Code Reference | Master table — all error codes across all tools |
| 11 | Ticker Convention | NSE `.NS` / BSE `.BO` / US suffix rules |
| 12 | Testing Patterns | Unit, integration, and cache test code examples |

---

## Key Design Decisions in the Docs

**All schemas derived from Pydantic models, not written from memory.**
Every field in the example JSON was cross-checked against the actual
`BaseModel` definitions in the source files. `null` fields are shown
where the Pydantic type is `float | None`.

**Operating cash flow field name.** The `CashFlowYear` model uses
`operating_cash_flow_crores` (not `operating_cf_crores`). This matches
the actual field definition at `financials.py:231`. The integration tests
reference `operating_cf_crores` in an earlier test — that is a bug in the
test (uses a shortened name), not in the model.

**Error codes are tool-specific.** Each tool section has its own error
table, and Section 10 has a master cross-reference. This makes it fast
to look up an error code from an agent log without reading the full doc.

**`company_name` is required for earnings transcript tools.**
Both `fetch_earnings_transcript` and `fetch_transcript_chunk` require
`company_name` as a positional argument. Passing only `ticker` raises a
Pydantic `ValidationError` before the tool body runs. This is documented
prominently in Section 7.

---

## EOD Update Template

```
EOD Update [Date]:
Completed: T-020
Merged to main: feat/data-docs
Current week: 4 │ Current phase: 1
Blocker (if any): None
Next session: T-021 (Phase 2 begins — llm_factory.py, LLM routing)
```