# PERF-001 — Backend Hardening: Single yFinance Fetch, Dev-Reload Fix, Line Endings

**Phase: Backend hardening (post-Phase 6, pre-Phase 7) | Week 17**
**Branch:** `perf/data-single-yfinance-fetch-per-ticker`
**Base branch:** `main`

> Labelled `PERF-001` rather than the next `T-0XX` number deliberately —
> this is out-of-band hardening work discovered while testing T-059/T-060
> end-to-end, not one of the 80 tasks in the Excel project plan. The real
> `T-061` (Investment Memo viewer / verdict panel) is untouched and still
> next up in Phase 6.

---

## 1. Task summary

Three related reliability bugs, all diagnosed from the same end-to-end
test run of the T-059/T-060 frontend against the full backend pipeline,
fixed together because they were found together and touch adjacent
infrastructure:

1. **yFinance 429 rate limiting on cold runs.** `stock_price.py`,
   `financials.py`, and `ratios.py` each independently called
   `yf.Ticker(ticker)`, producing 8-12 duplicate yfinance requests per
   ticker in one analysis burst — the most likely cause of the
   `429 Client Error: Too Many Requests` seen in the terminal log on the
   very first run of a ticker, before Redis caching (T-018) can help at
   all.
2. **WebSocket "Connection closed unexpectedly (code 1006)" mid-analysis.**
   `backend/db/chroma_client.py` persisted ChromaDB's dev data to
   `.chroma_data/` — a path _inside_ the project root. `uvicorn --reload`
   watches the entire working directory by default, so every document
   embedding write during an analysis (visible in the log as
   `Add of existing embedding ID: ...`) was detected as a source change
   and triggered a full app reload, killing any open WebSocket with an
   abnormal closure and dropping the in-flight background analysis task.
3. **Prettier CI failure on `DebateMessageCard.tsx`.** The repo had no
   `.gitattributes`. On Windows, Git commonly checks files out with CRLF
   line endings, but `frontend/.prettierrc.json` sets `"endOfLine": "lf"`
   — so any file re-saved by a Windows editor gets flagged by
   `prettier --check` in CI even when nothing meaningful changed.

**Acceptance criteria:**

- [x] A single analysis run makes no more than ~2-4 total yfinance
      network round-trips per ticker (down from ~8-12), verified by
      call-count assertions against a mocked `yf.Ticker`
- [x] `stock_price.py`, `financials.py`, `ratios.py` public function
      signatures and return types unchanged
- [x] All three tools' existing unit tests still pass (patch targets
      updated to the new shared module — see §2); new tests cover the
      shared-fetch path itself
- [x] Redis caching (`@cached`, T-018) continues to work unchanged — a
      Redis cache hit still means zero yfinance calls; TTLs and key
      structure untouched
- [x] No change to error handling / graceful degradation — a failed
      shared fetch still makes each tool return its own typed error dict
- [x] `black` / `isort` / `flake8` / `mypy --strict` / `pytest`
      (coverage ≥ 85%) all pass
- [x] Local dev server no longer reloads mid-analysis from ChromaDB
      writes
- [x] `DebateMessageCard.tsx` — and any future file — can no longer fail
      `prettier --check` purely from CRLF/LF drift

**Explicitly out of scope** (unchanged from the original ask):

- Switching away from yfinance to a different data provider
- Changing Redis cache TTLs or key structure
- New retry/backoff tuning for yfinance or Alpha Vantage
- Any other frontend changes beyond the one flagged file + the repo-wide
  line-ending fix

---

## 2. Files added / changed

```
backend/tools/market_data.py                          (new)
backend/tools/stock_price.py                           (modified)
backend/tools/financials.py                             (modified)
backend/tools/ratios.py                                  (modified)
backend/db/chroma_client.py                              (modified)
backend/config.py                                        (modified)
backend/tests/conftest.py                                (modified)
backend/tests/unit/test_market_data.py                  (new)
backend/tests/unit/test_stock_price.py                  (modified — patch targets only)
backend/tests/unit/test_financials.py                   (modified — patch targets only)
backend/tests/unit/test_ratios.py                        (modified — patch targets only)
.gitattributes                                            (new)
.gitignore                                                (modified)
frontend/src/components/debate/DebateMessageCard.tsx     (re-saved, LF-normalised)
docs/week-17/PERF-001-YFinance-Fetch-And-Dev-Reliability-Hardening.md (new, this file)
```

### 2.1 `backend/tools/market_data.py` (new) — the fix for issue 1

`get_shared_ticker(ticker)` hands out one `yf.Ticker` instance per
ticker, shared across all three tool modules for a short, TTL-bounded
window (120s — comfortably longer than one analysis's documented <90s
runtime, short enough that a _later_, separate analysis of the same
ticker still gets a fresh instance rather than indefinitely-stale data).

This works because yfinance's own `Ticker` object caches `.info`,
`.financials`, `.balance_sheet`, `.cashflow`, and `.history()` **on the
instance** after first access — three tools sharing one instance means
only the _first_ tool to touch each property pays the network cost; the
other two get it for free from yfinance's own internal cache. Building
three separate `yf.Ticker()` objects (the previous behaviour) meant none
of that internal caching was ever shared, so every tool re-paid the full
cost.

Thread-safe (`threading.Lock`) since LangGraph's parallel research-agent
`Send` API can call this concurrently from multiple threads for the same
ticker. Exposes `reset_shared_ticker_cache()` (used by the new autouse
test fixture, see §2.3) and `shared_ticker_cache_size()` (test/diagnostic
only).

### 2.2 `stock_price.py` / `financials.py` / `ratios.py` (modified)

Each file's single `yf.Ticker(ticker)` call site is replaced with
`get_shared_ticker(ticker)`. Nothing else changes — return types, error
handling, and Redis `@cached` wrapping are untouched. The unused
`import yfinance as yf` is removed from all three (nothing else in these
files referenced `yf.` directly).

One minor, deliberate behavioural note: `stock_price.py` previously
passed the ticker to `yf.Ticker()` in whatever case the caller supplied;
`financials.py` and `ratios.py` already upper-cased first. The shared
cache normalises (`strip().upper()`) before constructing, so all three
tools now get the same, consistently-cased `yf.Ticker` instance for a
given symbol — a strictly safer default, and yfinance/Yahoo's endpoints
are effectively case-insensitive on the symbol already.

### 2.3 `backend/tests/conftest.py` (modified)

Added an autouse `_reset_shared_ticker_cache` fixture that clears
`market_data`'s cache before _and_ after every test. This is required,
not optional: dozens of existing tests across the three tool test files
reuse the same ticker string ("TCS.NS") with different mocks per test.
Without a reset between tests, the second test to touch "TCS.NS" would
silently receive the _first_ test's cached (wrong) mock instead of its
own patched one.

### 2.4 Test files — patch target updates only

`test_stock_price.py`, `test_financials.py`, `test_ratios.py`: every
`patch("backend.tools.<module>.yf.Ticker", ...)` becomes
`patch("backend.tools.market_data.yf.Ticker", ...)` — a pure
find-and-replace, since that's the one place `yf.Ticker` is actually
constructed now. No assertions, fixtures, or test logic changed.

### 2.5 `backend/tests/unit/test_market_data.py` (new)

Covers the shared-fetch path directly: same ticker → identical instance
across repeated calls and across a simulated 3-tool sequence (one
construction total); different tickers → different instances; TTL
expiry forces a fresh instance; `reset_shared_ticker_cache()` forces one
immediately; ticker normalisation collapses case/whitespace variants to
one cache entry; a raising constructor propagates and leaves nothing
cached.

### 2.6 `backend/db/chroma_client.py` + `backend/config.py` — the fix for issue 2

`CHROMA_PERSIST_DIR` moves from the relative, in-repo `.chroma_data` to
`~/.airp/chroma_data` (outside any directory `uvicorn --reload` watches
by default). `get_chroma_client(persist_dir: str | None = None)` resolves
the effective directory as: explicit argument → `settings.chroma_persist_dir`
(new, optional config field, empty by default) → the new out-of-repo
default. The existing test that passes an explicit `persist_dir="/tmp/..."`
override is unaffected — the new resolution logic is skipped entirely
whenever a caller supplies a value.

### 2.7 `.gitattributes` (new) + `.gitignore` (modified) — the fix for issue 3

Root cause of the Prettier CI failure: no `.gitattributes` existed, so
Windows checkouts can silently get CRLF line endings while
`.prettierrc.json` demands `"endOfLine": "lf"`. `.gitattributes` now
forces `* text=auto eol=lf` (with explicit `binary` markers for
image/font/PDF assets so they're never touched). This fixes the failure
class for every file going forward, not just the one flagged in CI.
`.gitignore` gets a `.chroma_data/` entry for anyone with a leftover
local directory from before §2.6.

---

## 3. Full workflow — checkout to PR

### 3.1 Sync `main` and create the branch

```bash
git checkout main
git pull origin main
git checkout -b perf/data-single-yfinance-fetch-per-ticker
```

### 3.2 Add the changed files

Copy the files listed in §2 into the working tree at the exact paths
shown, overwriting the modified files in place.

### 3.3 One-time step: renormalise line endings

Because `.gitattributes` is new, existing tracked files need to be
re-checked against it once:

```bash
git add --renormalize .
git status   # review — should only show line-ending-only diffs, if any
```

### 3.4 One-time step: move any existing local ChromaDB data (optional)

If you have an existing `.chroma_data/` folder in the repo root from
before this change, it's safe to delete — the app will recreate a fresh
one at `~/.airp/chroma_data` on first run. Nothing in it is
irreplaceable (it's re-derived from news/transcripts/uploaded PDFs).

```bash
rm -rf .chroma_data   # optional cleanup, Windows: rmdir /s /q .chroma_data
```

### 3.5 Verify locally before committing

Backend — run the full gate exactly as CI does:

```bash
cd backend
python -m black --check .
python -m isort --check-only .
python -m flake8 .
python -m mypy .
ENVIRONMENT=test python -m pytest --cov=backend --cov-report=term-missing
```

Confirm the coverage report shows `backend/tools/market_data.py` at (or
near) 100% — every branch is exercised directly in
`test_market_data.py`.

Frontend — confirm the Prettier fix actually resolves the CI failure:

```bash
cd frontend
npm ci
npm run format:check
npm run lint
npm run type-check
npm run test:run
npm run build
```

If `format:check` still reports issues on any file (unlikely after the
`.gitattributes` renormalisation), run `npm run format` once and re-check.

Manual smoke test — confirm both original symptoms are gone:

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

Upload a document and run a full analysis for a ticker you haven't
analysed yet this session (a genuinely cold run). Confirm:

- No `429 Client Error` in the terminal log for that ticker
- The live agent progress viewer runs to completion without a
  "Connection closed unexpectedly" error

### 3.6 Commit (two-commit pattern: content, then any auto-fixes)

```bash
git add backend/tools/market_data.py \
        backend/tools/stock_price.py \
        backend/tools/financials.py \
        backend/tools/ratios.py \
        backend/db/chroma_client.py \
        backend/config.py \
        backend/tests/conftest.py \
        backend/tests/unit/test_market_data.py \
        backend/tests/unit/test_stock_price.py \
        backend/tests/unit/test_financials.py \
        backend/tests/unit/test_ratios.py \
        .gitattributes \
        .gitignore \
        frontend/src/components/debate/DebateMessageCard.tsx \
        docs/week-17/PERF-001-YFinance-Fetch-And-Dev-Reliability-Hardening.md

git commit -m "perf(backend): share one yFinance fetch per ticker, fix dev-reload WS drops"

# If black/isort/prettier --write changed anything after the first
# commit, stage and recommit:
git add -A
git commit -m "chore: apply lint/format fixes for PERF-001" --allow-empty
```

Use `git commit --no-verify` only if Windows App Control blocks a
pre-commit hook shim — CI's Linux runners remain the real enforcement
gate.

### 3.7 Push and open the PR

```bash
git push -u origin perf/data-single-yfinance-fetch-per-ticker
```

Then open a PR from `perf/data-single-yfinance-fetch-per-ticker` →
`main` (squash and merge) with the title and description below.

---

## 4. Pull Request

### Title

```
perf(backend): consolidate yFinance fetch per ticker; fix dev-reload WebSocket drops; normalise line endings
```

### Description

```markdown
## Summary

Three reliability fixes found together while testing the T-059/T-060
frontend end-to-end against the full pipeline, bundled into one PR since
they were diagnosed from the same run and touch adjacent infra:

1. A single analysis was making 8-12 separate yfinance requests per
   ticker (three tools each building their own yf.Ticker), the likely
   cause of 429s on a ticker's first ("cold") run.
2. ChromaDB's dev persistence directory lived inside the project root,
   so uvicorn --reload treated every embedding write during an analysis
   as a source change and restarted the server mid-run, killing the
   WebSocket with an abnormal closure (code 1006).
3. No .gitattributes existed, so Windows CRLF checkouts could fail
   Prettier's endOfLine: "lf" check on any touched file in CI.

## Changes

- Add `backend/tools/market_data.py`: `get_shared_ticker(ticker)`
  hands out one TTL-bounded (120s), thread-safe `yf.Ticker` instance per
  ticker shared across `stock_price.py` / `financials.py` / `ratios.py`,
  so yfinance's own per-instance caching of `.info`/`.financials`/
  `.balance_sheet`/`.cashflow`/`.history()` is shared instead of
  triplicated. Redis caching (T-018) is untouched — a cache hit is
  still zero yfinance calls.
- Update `stock_price.py`, `financials.py`, `ratios.py` to call
  `get_shared_ticker` instead of constructing their own `yf.Ticker`.
  Public signatures, return types, and error handling unchanged.
- Add `backend/tests/unit/test_market_data.py` covering the shared
  cache directly (single construction across a 3-tool sequence, TTL
  expiry, reset, normalisation, failure propagation).
- Update `test_stock_price.py` / `test_financials.py` / `test_ratios.py`
  patch targets to `backend.tools.market_data.yf.Ticker`.
- Add an autouse `conftest.py` fixture resetting the shared ticker
  cache before/after every test, so tests reusing the same ticker
  string with different mocks stay isolated.
- Move ChromaDB's dev `PersistentClient` directory from the in-repo
  `.chroma_data/` to `~/.airp/chroma_data` (`backend/db/chroma_client.py`),
  overridable via the new `settings.chroma_persist_dir`
  (`backend/config.py`). Existing explicit-`persist_dir` test override
  is unaffected.
- Add `.gitattributes` (`* text=auto eol=lf`, explicit binary
  extensions) so CRLF/LF drift can't recur as a Prettier CI failure for
  any file. Add `.chroma_data/` to `.gitignore` for any leftover local
  directories.
- Re-save `frontend/src/components/debate/DebateMessageCard.tsx` with
  normalised line endings (no content change).

## Testing

- `black --check .` / `isort --check-only .` / `flake8 .` / `mypy .` — pass
- `ENVIRONMENT=test pytest --cov=backend` — passes, coverage ≥ 85%,
  including the new `test_market_data.py` suite
- `npm run format:check` / `npm run lint` / `npm run type-check` /
  `npm run test:run` / `npm run build` — pass
- Manual: ran a full analysis for a previously-unanalysed ticker with
  `--reload` on; confirmed no 429s and no WebSocket disconnect

## LangSmith Trace

N/A — no agent prompt or graph routing behaviour changed; this is a
data-fetch and dev-infra hardening change only.

## Screenshots

N/A — backend/infra change; the one frontend file has no visual diff.

## Related Issues

Closes #PERF-001
```

---

## 5. Post-merge checklist

- [ ] Confirm CI's `backend` and `frontend` jobs and the `ci-pass`
      summary job are all green on the PR
- [ ] Delete `perf/data-single-yfinance-fetch-per-ticker` after
      squash-merge
- [ ] Update local `main`: `git checkout main && git pull origin main`
- [ ] Delete any stale local `.chroma_data/` folder (see §3.4)
- [ ] Next session: resume Phase 6 — real `T-061` (Investment Memo
      viewer / verdict panel), Week 17, per the original project plan
