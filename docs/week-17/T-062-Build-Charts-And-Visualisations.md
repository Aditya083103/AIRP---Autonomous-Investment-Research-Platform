# T-062 — Build Charts and Visualisations

**Phase 6 — React Frontend | Week 17**
**Branch:** `feat/ui-charts`
**Base branch:** `main`

---

## 1. Task summary

Build the 5 chart types the Analysis Results page needs: a 1-year
stock price chart, revenue/profit trend bars, a P/E-vs-peers bar
chart, a sentiment score gauge, and a risk radar chart -- all using
Recharts, all rendered with real data from the backend.

**Acceptance criteria:**

- [x] All 5 chart types render with real data (`StockPriceChart`,
      `RevenueProfitChart`, `PeerValuationChart`, `SentimentGaugeChart`,
      `RiskRadarChart`)
- [x] Tooltips work (custom price tooltip; Recharts' built-in
      `<Tooltip>` on the bar/radar charts)
- [x] Charts resize on mobile (every chart uses Recharts'
      `<ResponsiveContainer>`; `ChartsPanel`'s 3-column grid collapses
      to a single column below the `md` breakpoint)

---

## 2. A necessary backend addition

**No chart in this task can be built from data the frontend already
had.** `GET /api/v1/analysis/{job_id}/result` (T-050) returns only the
Portfolio Manager's `InvestmentDecision` -- verdict, memo prose, and a
handful of summary strings. None of the five charts' underlying
numbers (a year of daily closing prices, four years of revenue/net
income, P/E-vs-sector multiples, the sentiment score breakdown, or the
five risk sub-scores) were ever exposed by any existing endpoint --
they either live only inside `analyses.state_snapshot`'s
`valuation`/`sentiment`/`risk` keys (computed once during the pipeline
run, never returned to the frontend) or were never persisted anywhere
at all (a year of OHLCV data and four years of income-statement rows
are too large to store per-analysis, and were only ever summarised
into a handful of derived stats for the agents' own use).

So this task adds one new backend endpoint,
**`GET /api/v1/analysis/{job_id}/charts`**, alongside the frontend
work:

- `backend/models/schemas.py` -- 6 new response models
  (`PricePointResponse`, `RevenueProfitPointResponse`,
  `ValuationChartResponse`, `SentimentChartResponse`,
  `RiskRadarResponse`, `AnalysisChartDataResponse`).
- `backend/services/analysis.py` -- `get_analysis_chart_data`, reusing
  the _exact same_ `_SQL_LOAD_RESULT` query `get_analysis_result`
  already issues (both need only ownership/status/state_snapshot).
  Reads `valuation`/`sentiment`/`risk` straight out of the snapshot
  (already computed, zero extra cost) and makes two **live** calls to
  existing yFinance tools -- `fetch_ohlcv` (T-018) and
  `fetch_income_statement` (T-019) -- for the two sources that were
  never persisted, each offloaded to a worker thread via
  `asyncio.to_thread` so the blocking yFinance call never ties up the
  event loop.
- `backend/routers/analysis.py` -- `GET /{job_id}/charts`, same
  404/409 semantics as `GET /result`.

**Each of the five chart sources degrades independently.** A missing
agent output or a failed live yFinance call empties that one field and
adds a plain-English note to `data_warnings` -- it never fails the
whole response. This was a deliberate design choice, not an
afterthought: the terminal log from the T-061 session showed
`sentiment_analyst` timing out mid-run under Groq's free-tier rate
limit and the pipeline degrading gracefully to a neutral result rather
than failing outright -- the exact same philosophy applies here, one
level up the stack, for data sources that can fail for reasons
completely unrelated to whether the underlying analysis succeeded (a
transient yFinance blip should never take down four other charts that
have nothing to do with it).

---

## 3. Files added / changed

```
backend/models/schemas.py                              (modified — 6 new chart response schemas)
backend/services/analysis.py                            (modified — get_analysis_chart_data + 2 fetch helpers)
backend/routers/analysis.py                             (modified — GET /{job_id}/charts endpoint)
backend/tests/unit/test_analysis_charts_service.py      (new)
backend/tests/unit/test_analysis_charts_router.py       (new)

frontend/src/types/analysis.ts                          (modified — adds 6 chart response types)
frontend/src/api/analysis.ts                            (modified — adds fetchAnalysisCharts)
frontend/src/hooks/useAnalysisCharts.ts                 (new)
frontend/src/lib/chartColors.ts                         (new)
frontend/src/components/charts/StockPriceChart.tsx      (new)
frontend/src/components/charts/RevenueProfitChart.tsx   (new)
frontend/src/components/charts/PeerValuationChart.tsx   (new)
frontend/src/components/charts/SentimentGaugeChart.tsx  (new)
frontend/src/components/charts/RiskRadarChart.tsx       (new)
frontend/src/components/charts/ChartsPanel.tsx          (new)
frontend/src/components/charts/index.ts                 (new)
frontend/src/pages/AnalysisResultPage.tsx               (modified — renders ChartsPanel on completion)
frontend/src/test/setup.ts                              (modified — ResizeObserver stub + getBoundingClientRect mock)
frontend/src/test/analysisApi.test.ts                   (modified — adds fetchAnalysisCharts tests)
frontend/src/test/useAnalysisCharts.test.tsx            (new)
frontend/src/test/StockPriceChart.test.tsx              (new)
frontend/src/test/RevenueProfitChart.test.tsx           (new)
frontend/src/test/PeerValuationChart.test.tsx           (new)
frontend/src/test/SentimentGaugeChart.test.tsx          (new)
frontend/src/test/RiskRadarChart.test.tsx               (new)
frontend/src/test/ChartsPanel.test.tsx                  (new)
frontend/src/test/AnalysisResultPage.test.tsx           (modified — URL-routed fetch mock, charts assertions)
docs/week-17/T-062-Build-Charts-And-Visualisations.md   (new, this file)
```

### Design notes

- **Backend degrade-independently philosophy** -- see Section 2 above;
  fully documented in `get_analysis_chart_data`'s own docstring and in
  a new "Why GET /charts returns 200 with data_warnings..." section in
  `backend/routers/analysis.py`'s module docstring, alongside the
  file's existing "Why GET /result returns 409..." explanation.
- **`fetch_income_statement` is not Redis-cached** (no `@cached`
  decorator on the underlying `_fetch_financials_from_yfinance`) --
  every `GET /charts` call re-hits yFinance for financials, even
  though the Fundamental Analyst already fetched the same statements
  once during the original pipeline run. `fetch_ohlcv`, by contrast,
  shares its cache key with `fetch_stock_price` (`airp:stock:{ticker}:
{period}`, `STOCK_TTL`), so it is almost always a cache hit -- the
  Technical Analyst already warmed it. Tracked as a known gap, out of
  scope for this task.
- **`StockPriceChart`** is a filled area chart (not candlestick) --
  chart data only ever carries `close`/`volume` per day, not the full
  OHLC candle, and a single price line under a gradient fill is the
  more legible choice for this dashboard than trying to squeeze
  open/high/low into a chart that doesn't have that context anyway.
- **`RevenueProfitChart`** groups revenue and net income (both INR
  Crores, already currency-normalised by `backend.tools.financials`)
  per fiscal year as paired bars.
- **`PeerValuationChart`** reshapes `ValuationChartResponse`'s
  "one field per metric" response (`pe_ratio`/`sector_avg_pe`, etc.)
  into the "one row per metric" grouped-bar shape Recharts expects,
  dropping any metric where both the company and sector value are
  null rather than rendering an empty pair of bars for it.
- **`SentimentGaugeChart`** uses Recharts' `RadialBarChart` -- the
  -1.0..+1.0 sentiment score is normalised to 0-100 purely for the
  gauge's internal scale; the actual score and label are overlaid as
  plain text on top of the SVG (absolutely positioned), alongside the
  positive/neutral/negative article-count breakdown.
- **`RiskRadarChart`** plots all 5 `RiskRadarResponse` scores
  (overall + governance/regulatory/financial/concentration) on the
  same 1-10 scale -- no normalisation needed, since every risk field
  already shares that scale.
- **`ChartsPanel`** composes all 5: price and revenue/profit each get
  a full-width row (they read best wide), while valuation, sentiment,
  and risk share a responsive 3-column row. `data_warnings`, if any,
  surface in a banner above all five charts.
- **Wiring:** `AnalysisResultPage.tsx` fetches charts via
  `useAnalysisCharts`, gated identically to T-061's
  `useAnalysisResult` (`isComplete && !hasFailed`) but as a
  **separate, independent query** -- the two endpoints have very
  different failure characteristics and payload sizes (see that
  page's updated docstring), so a slow/failed charts fetch never
  blocks the Investment Memo from rendering, and vice versa.
- **Test environment fix required for any Recharts test:** jsdom does
  not implement `ResizeObserver` and always reports a 0x0
  `getBoundingClientRect`, both of which Recharts'
  `<ResponsiveContainer>` depends on to size and render its children.
  `frontend/src/test/setup.ts` now stubs both globally so every chart
  actually renders its SVG content under Vitest instead of silently
  staying empty.

---

## 4. Full workflow — checkout to PR

### 4.1 Sync `main` and create the feature branch

```bash
git checkout main
git pull origin main
git checkout -b feat/ui-charts
```

### 4.2 Add the new/changed files

Copy the following into the working tree at the exact paths shown,
overwriting `backend/models/schemas.py`, `backend/services/analysis.py`,
`backend/routers/analysis.py`, `frontend/src/types/analysis.ts`,
`frontend/src/api/analysis.ts`, `frontend/src/pages/AnalysisResultPage.tsx`,
`frontend/src/test/setup.ts`, `frontend/src/test/analysisApi.test.ts`,
and `frontend/src/test/AnalysisResultPage.test.tsx` in place:

```
backend/models/schemas.py
backend/services/analysis.py
backend/routers/analysis.py
backend/tests/unit/test_analysis_charts_service.py
backend/tests/unit/test_analysis_charts_router.py

frontend/src/types/analysis.ts
frontend/src/api/analysis.ts
frontend/src/hooks/useAnalysisCharts.ts
frontend/src/lib/chartColors.ts
frontend/src/components/charts/StockPriceChart.tsx
frontend/src/components/charts/RevenueProfitChart.tsx
frontend/src/components/charts/PeerValuationChart.tsx
frontend/src/components/charts/SentimentGaugeChart.tsx
frontend/src/components/charts/RiskRadarChart.tsx
frontend/src/components/charts/ChartsPanel.tsx
frontend/src/components/charts/index.ts
frontend/src/pages/AnalysisResultPage.tsx
frontend/src/test/setup.ts
frontend/src/test/analysisApi.test.ts
frontend/src/test/useAnalysisCharts.test.tsx
frontend/src/test/StockPriceChart.test.tsx
frontend/src/test/RevenueProfitChart.test.tsx
frontend/src/test/PeerValuationChart.test.tsx
frontend/src/test/SentimentGaugeChart.test.tsx
frontend/src/test/RiskRadarChart.test.tsx
frontend/src/test/ChartsPanel.test.tsx
frontend/src/test/AnalysisResultPage.test.tsx
docs/week-17/T-062-Build-Charts-And-Visualisations.md
```

### 4.3 Verify locally before committing

This task touches **both** backend and frontend -- run both gates,
exactly as CI does:

```bash
cd backend
black --check .
isort --check-only .
flake8 .
mypy .
pytest --tb=short --cov=backend --cov-report=term-missing -v
```

```bash
cd frontend
npm ci
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

If `black`/`isort` report issues, run `black .` and `isort .` once to
let them auto-fix, then re-run `--check`.

If a chart test fails with something like _"Warning: The width(0) and
height(0) of chart should be greater than 0"_ or renders an empty
`<svg>`, double-check `frontend/src/test/setup.ts` actually landed --
every chart component in this task needs its `ResizeObserver` stub and
`getBoundingClientRect` mock to render anything at all under jsdom.

If `mypy` flags `fetch_ohlcv`/`fetch_income_statement`'s `.invoke(...)`
return value, this mirrors the exact same untyped-`.invoke()` pattern
already used throughout `backend/agents/*.py` (e.g.
`fetch_stock_price.invoke({...})` in `technical_analyst.py`) -- no new
`cast()` is needed beyond what `_fetch_price_history_sync` already
does for `currency`.

### 4.4 Commit (two-commit pattern: content, then any auto-fixes)

```bash
git add backend/models/schemas.py \
        backend/services/analysis.py \
        backend/routers/analysis.py \
        backend/tests/unit/test_analysis_charts_service.py \
        backend/tests/unit/test_analysis_charts_router.py \
        frontend/src/types/analysis.ts \
        frontend/src/api/analysis.ts \
        frontend/src/hooks/useAnalysisCharts.ts \
        frontend/src/lib/chartColors.ts \
        frontend/src/components/charts/ \
        frontend/src/pages/AnalysisResultPage.tsx \
        frontend/src/test/setup.ts \
        frontend/src/test/analysisApi.test.ts \
        frontend/src/test/useAnalysisCharts.test.tsx \
        frontend/src/test/StockPriceChart.test.tsx \
        frontend/src/test/RevenueProfitChart.test.tsx \
        frontend/src/test/PeerValuationChart.test.tsx \
        frontend/src/test/SentimentGaugeChart.test.tsx \
        frontend/src/test/RiskRadarChart.test.tsx \
        frontend/src/test/ChartsPanel.test.tsx \
        frontend/src/test/AnalysisResultPage.test.tsx \
        docs/week-17/T-062-Build-Charts-And-Visualisations.md

git commit -m "feat(ui): add financial charts and visualisation components (T-062)"

# If a formatter/linter --fix step changed anything after the first
# commit, stage and recommit:
git add -A
git commit -m "chore: apply lint/format fixes for T-062" --allow-empty
```

Use `git commit --no-verify` only if Windows App Control blocks a
pre-commit hook shim (per the project's documented Windows
workaround) -- CI's Linux runners remain the real enforcement gate.

### 4.5 Push and open the PR

```bash
git push -u origin feat/ui-charts
```

Then open a PR from `feat/ui-charts` → `main` (squash and merge) with
the title and description below.

---

## 5. Pull Request

### Title

```
feat(ui): add financial charts and visualisation components (T-062)
```

### Description

```markdown
## Summary

Adds the 5 chart types the Analysis Results page needs -- a 1-year
stock price chart, revenue/profit trend bars, a P/E-vs-peers bar
chart, a sentiment score gauge, and a risk radar chart -- all built
with Recharts and rendered with real data. Required a new backend
endpoint, GET /api/v1/analysis/{job_id}/charts, since none of this
data was previously exposed to the frontend (see the PR's linked
docs/week-17/T-062-*.md for the full rationale).

## Changes

- Add GET /api/v1/analysis/{job_id}/charts: reuses GET /result's exact
  ownership/status query, reads valuation/sentiment/risk straight out
  of state_snapshot (already computed, no extra cost), and makes two
  live yFinance calls (fetch_ohlcv, fetch_income_statement -- both
  pre-existing tools) for the 1-year price series and 4-year
  revenue/profit trend, each offloaded to a worker thread.
- Each of the five chart sources degrades independently -- a missing
  agent output or a failed live fetch empties that one field and adds
  a note to data_warnings, never a 500 for the whole response.
- Add 6 new Pydantic response schemas (PricePointResponse through
  AnalysisChartDataResponse) and their frontend TypeScript mirrors.
- Add fetchAnalysisCharts (api client) and useAnalysisCharts (React
  Query hook, staleTime: Infinity -- chart data for a completed
  analysis never changes).
- Add components/charts/: StockPriceChart, RevenueProfitChart,
  PeerValuationChart, SentimentGaugeChart, RiskRadarChart, and the
  top-level ChartsPanel composition, all using Recharts.
- Wire ChartsPanel into AnalysisResultPage as a second, independent
  query alongside T-061's ResultsPanel -- a slow/failed charts fetch
  never blocks the Investment Memo, and vice versa.
- Add a ResizeObserver stub + getBoundingClientRect mock to
  test/setup.ts -- required for Recharts' ResponsiveContainer to
  render anything under jsdom.
- Add unit/component tests for every new backend and frontend module,
  plus new AnalysisResultPage.test.tsx cases for the charts panel
  appearing on success, a degraded chart source, and an independent
  charts-fetch failure that doesn't block the memo.

## Testing

- Backend: `black --check .`, `isort --check-only .`, `flake8 .`,
  `mypy .`, `pytest` -- all pass, including:
  - `test_analysis_charts_service.py` -- the two live-fetch helpers'
    success/error paths, and get_analysis_chart_data's ownership/
    status/snapshot logic with each of valuation/sentiment/risk
    independently missing
  - `test_analysis_charts_router.py` -- 404/409/200 semantics
    end-to-end, all 5 chart types present in a successful response,
    and each of the five sources degrading independently without
    affecting the other four
- Frontend: `npm run type-check`, `npm run lint`, `npm run format:check`,
  `npm run test:run`, `npm run build` -- all pass, including:
  - `analysisApi.test.ts` / `useAnalysisCharts.test.tsx` -- request
    shape, success, partial-degradation, 409/404 error handling
  - One test file per chart -- title, empty/null fallback, and (where
    the content isn't Recharts-internal SVG) the actual data rendered
  - `ChartsPanel.test.tsx` -- all 5 charts wired in, data_warnings
    banner shown/hidden correctly
  - `AnalysisResultPage.test.tsx` -- all pre-existing T-059/T-060/T-061
    tests still pass, plus: charts panel appears on success, an
    independent charts-fetch failure doesn't block the memo, and a
    degraded chart source shows its warnings banner

## LangSmith Trace

N/A -- no agent/graph behaviour touched. The two live yFinance calls
this task adds run outside the LangGraph pipeline entirely (in the new
GET /charts request handler, not in any agent node).

## Screenshots

_Add a screenshot of the completed charts panel (desktop and mobile
375px width) with a sample BUY analysis, before merging._

## Related Issues

Closes #T-062
```

---

## 6. Post-merge checklist

- [ ] Confirm CI's `backend`, `frontend`, and `ci-pass` summary jobs
      are all green on the PR
- [ ] Delete `feat/ui-charts` after squash-merge
- [ ] Update local `main`: `git checkout main && git pull origin main`
- [ ] Next session: T-063 (Build Investment Memo page -- render the
      full memo as formatted HTML with collapsible sections, a PDF
      download button calling the existing GET /memo/pdf endpoint, and
      a share-URL button), Phase 6, Week 17
