# T-085 — Add Analysis Horizon selector

**Phase:** 7 — Bug Fixes & Verdict Calibration
**Week:** 19
**Branch:** `feat/analysis-horizon-selector`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 5

## Summary

Lets the user choose how much price history the Technical Analyst agent
looks at — previously this was hardcoded to `"1y"` everywhere. Adds a
7-option horizon (`1mo` / `3mo` / `6mo` / `1y` / `3y` / `5y` / `10y`) to
the `AnalysisPage` form, threads it through
`POST /api/v1/analysis/start` → `InvestmentState` → the Technical
Analyst's `fetch_stock_price` call, and defaults to `"1y"` everywhere
it is omitted so every existing caller (and every test written before
this task) keeps its old behaviour unchanged.

## Acceptance criteria (from task spec)

- [x] User can select horizon on `AnalysisPage`
- [x] `technical_analyst` fetches the selected period
- [x] Default remains `1y` when unset

## Changes

### Backend

- **`backend/tools/stock_price.py`** — `VALID_PERIODS` and `PERIOD_MAP`
  extended from `{"1y", "3y", "5y"}` to
  `{"1mo", "3mo", "6mo", "1y", "3y", "5y", "10y"}`. `PERIOD_MAP` remains
  the identity function since AIRP's period vocabulary already matches
  yFinance's own period strings 1:1; kept as an explicit dict (not a
  passthrough) so a future AIRP-only period label could still be
  translated without touching call sites. Docstrings for
  `fetch_stock_price`, `fetch_ohlcv`, and `StockPrice.period` updated to
  list the full set.

- **`backend/models/schemas.py`** — `AnalysisStartRequest` gains a
  `period: str = "1y"` field with its own `_validate_period` validator
  (lower-cases and rejects anything outside
  `_VALID_ANALYSIS_PERIODS`). This set is intentionally duplicated
  rather than imported from `backend.tools.stock_price` — the schemas
  module is the API-contract layer and the tools module is several
  layers deeper in the agent stack; this mirrors the same
  "small lookup table duplicated across layers" tradeoff
  `backend.services.analysis`'s own docstring already makes for its
  ticker-override table. `DEFAULT_ANALYSIS_PERIOD = "1y"` is exported
  for anything that wants the canonical default.

- **`backend/graph/state.py`** — `InvestmentState` gains a `period: str`
  field. `make_initial_state(..., period: str = "1y")` writes it into
  the initial state dict. Every existing call site that doesn't pass
  `period` gets `"1y"`, matching prior behaviour exactly.

- **`backend/services/analysis.py`** — `run_analysis_pipeline(...,
  period: str = "1y")` forwards `period` into `make_initial_state`.

- **`backend/routers/analysis.py`** — `start_analysis` passes
  `body.period` (already validated/normalised by the Pydantic model)
  into the `run_analysis_pipeline` background task call.

- **`backend/agents/technical_analyst.py`** — `_run_technical_analysis_core`
  gains a `period: str = "1y"` parameter and now calls
  `fetch_stock_price.invoke({"ticker": ticker, "period": period})`
  instead of the hardcoded `"1y"`. The `run_technical_analysis`
  LangGraph node reads `state.get("period") or "1y"` and forwards it —
  state built before this task (or any state dict missing the key)
  still resolves to `"1y"`, so no existing pipeline run is affected.

### Frontend

- **`frontend/src/lib/validation/analysisSchemas.ts`** — new
  `ANALYSIS_HORIZONS` tuple (mirrors the backend's valid-period set
  exactly), `ANALYSIS_HORIZON_LABELS` for display text,
  `DEFAULT_ANALYSIS_HORIZON = "1y"`, and a `horizon` field on
  `analysisInputSchema` using `.default(DEFAULT_ANALYSIS_HORIZON)` so a
  payload that omits `horizon` entirely still parses successfully —
  existing tests that only pass `companyTicker` are unaffected.

- **`frontend/src/components/analysis/HorizonSelect.tsx`** (new) — a
  labelled native `<select>` matching the design system's `Input.tsx`
  styling conventions. A plain native select (rather than
  `CompanyAutocomplete`'s custom listbox) is the right fit for seven
  fixed, short options — full keyboard support and label semantics for
  free, no positioning logic to write.

- **`frontend/src/pages/AnalysisPage.tsx`** — renders `<HorizonSelect>`
  between the company field and the PDF upload field, registered via
  `register("horizon")`; `defaultValues` seeds `horizon:
  DEFAULT_ANALYSIS_HORIZON`. `onSubmit` passes `period: values.horizon`
  to `startAnalysis`.

- **`frontend/src/api/analysis.ts`** — `startAnalysis` gains an optional
  `period?: AnalysisHorizon` param (default `DEFAULT_ANALYSIS_HORIZON`)
  and always includes `period` in the JSON body sent to
  `POST /analysis/start`.

## Testing

Backend (`ENVIRONMENT=test python -m pytest backend/tests/unit -v`):

- `test_stock_price.py` — `test_all_periods_accepted` extended to the
  full 7-value set; `test_raises_value_error_on_invalid_period` and
  `test_tool_returns_error_dict_on_invalid_period` updated from `"10y"`
  (now valid) to `"15y"` (still invalid); new
  `test_10y_period_now_valid` model test.
- `test_technical_analyst.py` — new `test_tool_called_with_explicit_period`,
  `test_tool_called_with_each_supported_period`,
  `test_defaults_to_1y_when_period_absent_from_state`,
  `test_reads_period_from_state`.
- `test_analysis_router.py` — new `TestAnalysisPeriod` class
  (default-to-1y, explicit-period-forwarded, every-period-accepted) plus
  `test_invalid_period_override_returns_422`.
- `test_analysis_service.py` — new
  `test_explicit_period_threads_into_initial_state`; existing
  `test_invokes_graph_with_initial_state` extended to assert
  `period == "1y"`.
- `test_investment_state.py` — new `test_period_defaults_to_1y`,
  `test_period_custom`, `test_round_trip_preserves_period`.

Frontend (`npm run test:run`):

- `analysisSchemas.test.ts` — new `describe("analysisInputSchema
  horizon field")` block: defaults to `"1y"`, accepts every supported
  horizon, rejects an unsupported one.
- `AnalysisPage.test.tsx` — updated the existing exact-body `toEqual`
  assertion (it would otherwise have failed the moment `period` was
  added to the request) to include `period: "1y"`; new test asserting
  a selected horizon (`"5y"`) is sent through.

## Verification gate run locally before pushing

Backend:

```bash
ENVIRONMENT=test python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
ENVIRONMENT=test python -m pytest backend/tests/unit -v
```

Frontend:

```bash
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

## LangSmith Trace

N/A — no LLM-facing prompt content changed; only the OHLCV fetch window
and a new request field.

## Related Issues

Closes #85 (adjust to your actual issue number if different).
