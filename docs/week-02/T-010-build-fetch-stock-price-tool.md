# T-010 — Build `fetch_stock_price` Tool

**Phase:** 1 — Data Layer & APIs
**Week:** 2
**Branch:** `feat/data-stock-price`
**Commit prefix:** `feat(tools):`
**PR title:** `feat(tools): add fetch_stock_price and fetch_ohlcv LangChain tools with full test suite`

---

## Overview

This task implements the first LangChain data tool in the AIRP backend — `fetch_stock_price`. It wraps yFinance to provide daily OHLCV (Open, High, Low, Close, Volume) price data for Indian NSE/BSE and global equities. The tool returns a fully-typed Pydantic model so downstream agents always receive structured, validated data rather than raw dictionaries.

Two tools are delivered:

- **`fetch_stock_price`** — Full OHLCV series + derived statistics (52w high/low, moving averages, % returns)
- **`fetch_ohlcv`** — Lightweight candle-only format (no stats block), optimised for the frontend charting pipeline

**Acceptance criteria:**

- Tool returns `StockPrice` Pydantic model (serialised to dict via `.model_dump()`)
- `pytest` tests mock `yfinance` — zero real API calls during test runs
- `TickerNotFoundError` raised and gracefully handled when yFinance returns empty data
- Invalid period (`'10y'`) returns an error dict — no unhandled exception surfaces to the agent

---

## Files Changed / Created in This Task

| File                                     | Action     | Purpose                                                                                                                                 |
| ---------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/tools/stock_price.py`           | **CREATE** | Two LangChain tools (`fetch_stock_price`, `fetch_ohlcv`), Pydantic models (`StockPrice`, `OHLCVRecord`, `PriceStats`), internal helpers |
| `backend/tests/unit/test_stock_price.py` | **CREATE** | 30+ unit tests covering all tools, helpers, and Pydantic validation — yfinance mocked throughout                                        |

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Checkout feature branch from `develop`

```bash
# Make sure you are on develop and it is up to date
git checkout develop
git pull origin develop

# Create the feature branch
git checkout -b feat/data-stock-price

# Confirm you are on the right branch
git branch
# → * feat/data-stock-price
```

---

### Step 2 — Create `backend/tools/stock_price.py`

Place the file at `backend/tools/stock_price.py`. This is the only production file for T-010.

**Key design decisions documented in the file:**

| Decision                                                  | Rationale                                                                          |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `_fetch_from_yfinance()` separated from `@tool` decorator | Enables direct unit testing without LangChain tool machinery                       |
| Error dict returned (not exception raised) from `@tool`   | Agents receive structured error objects — LangGraph can route on `result["error"]` |
| `TickerNotFoundError` custom exception                    | Distinguishes "ticker doesn't exist" from unexpected failures                      |
| `.NS` / `.BO` suffix documented in docstring              | Prevents the most common Indian market mistake                                     |
| `auto_adjust=True` in `yf.history()`                      | Returns split/dividend-adjusted closes — correct for % return calculations         |

---

### Step 3 — Create `backend/tests/unit/test_stock_price.py`

Place the file at `backend/tests/unit/test_stock_price.py`.

**Test structure overview:**

| Test class                      | What it tests                                                                                                  |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `TestComputePctChange`          | Pure `_compute_pct_change()` helper — edge cases (empty, zero, oversized lookback)                             |
| `TestComputeSma`                | Pure `_compute_sma()` helper — insufficient data returns `None`                                                |
| `TestBuildStats`                | `_build_stats()` with 260 and 30 records — MA availability                                                     |
| `TestFetchFromYfinance`         | `_fetch_from_yfinance()` with mocked `yf.Ticker` — all periods, fallback company name, uppercase normalisation |
| `TestFetchStockPriceTool`       | `fetch_stock_price.invoke()` — success dict, error dicts, default period, unexpected exception                 |
| `TestFetchOhlcvTool`            | `fetch_ohlcv.invoke()` — lightweight format, no stats block, error handling                                    |
| `TestStockPriceModelValidation` | Pydantic validation — empty ticker and invalid period raise                                                    |

---

### Step 4 — Run the tests locally

```bash
# From the repo root — activate your venv first
cd /path/to/airp

# Set test environment variable
export ENVIRONMENT=test

# Run only the T-010 tests
python -m pytest backend/tests/unit/test_stock_price.py -v

# Run with coverage report
python -m pytest backend/tests/unit/test_stock_price.py -v --cov=backend/tools/stock_price --cov-report=term-missing

# Run the full test suite to confirm nothing regressed
python -m pytest --tb=short
```

**Expected output (all passing):**

```
backend/tests/unit/test_stock_price.py::TestComputePctChange::test_normal_positive_return PASSED
backend/tests/unit/test_stock_price.py::TestComputePctChange::test_negative_return PASSED
... (30+ tests)
====== 30+ passed in X.XXs ======
```

---

### Step 5 — Verify the tool works manually (optional smoke test)

```python
# Run from repo root with venv active
# Set a valid .env or export ENVIRONMENT=development DATABASE_URL=...

from unittest.mock import MagicMock, patch
import pandas as pd

# Create a minimal mock
mock = MagicMock()
mock.history.return_value = pd.DataFrame({
    "Open": [3000.0] * 260,
    "High": [3010.0] * 260,
    "Low":  [2990.0] * 260,
    "Close":[3005.0] * 260,
    "Volume":[1_000_000] * 260,
}, index=pd.date_range(end="2024-01-15", periods=260, freq="B"))
mock.info = {"longName": "TCS", "exchange": "NSE", "currency": "INR"}

with patch("backend.tools.stock_price.yf.Ticker", return_value=mock):
    from backend.tools.stock_price import fetch_stock_price
    result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})
    print(result["ticker"])               # TCS.NS
    print(result["stats"]["current_price"]) # 3005.0
    print(result["stats"]["ma_50d"])      # 3005.0
```

---

### Step 6 — Commit the work

```bash
# Stage only the two files created in this task
git add backend/tools/stock_price.py
git add backend/tests/unit/test_stock_price.py

# Commit with AIRP commit format: type(scope): description
git commit -m "feat(tools): add fetch_stock_price and fetch_ohlcv tools with Pydantic models

- Implement StockPrice, OHLCVRecord, PriceStats Pydantic output models
- Wrap yFinance OHLCV fetch with 1y/3y/5y period support
- Add graceful TickerNotFoundError handling (returns error dict to agents)
- Implement fetch_ohlcv lightweight tool for frontend charting pipeline
- Separate _fetch_from_yfinance() from @tool decorator for testability
- Add 30+ unit tests with mocked yfinance (zero real API calls)

Closes #10"

# Push the branch to remote
git push -u origin feat/data-stock-price
```

---

### Step 7 — Open the Pull Request

**Go to GitHub → your repo → Pull requests → New pull request**

- **Base branch:** `develop`
- **Compare branch:** `feat/data-stock-price`

---

## Pull Request Template

Use the following as your PR description (copy-paste into GitHub):

---

**PR Title:** `feat(tools): add fetch_stock_price and fetch_ohlcv LangChain tools with full test suite`

---

### Summary

Implements T-010: the `fetch_stock_price` and `fetch_ohlcv` LangChain tools that wrap yFinance to provide OHLCV daily price data and derived statistics for Indian and global equities. Returns a fully-typed `StockPrice` Pydantic model to agents — no raw dicts, no unvalidated data.

### Changes

- **`backend/tools/stock_price.py`** — Production tool implementation
  - `StockPrice`, `OHLCVRecord`, `PriceStats` Pydantic models
  - `fetch_stock_price` LangChain `@tool` — full OHLCV + statistics
  - `fetch_ohlcv` LangChain `@tool` — lightweight candle-only format
  - `TickerNotFoundError` custom exception with descriptive messages
  - `_fetch_from_yfinance()` internal helper (separated for testability)
  - Pure helpers: `_compute_pct_change()`, `_compute_sma()`, `_build_stats()`
  - Indian market ticker convention documented (`.NS` / `.BO` suffixes)

- **`backend/tests/unit/test_stock_price.py`** — 30+ unit tests
  - All yfinance calls mocked via `unittest.mock.patch` — no real network calls
  - Covers: success path, ticker-not-found, invalid period, unexpected exceptions
  - Tests pure helper functions independently (no mocking needed)
  - Validates Pydantic model enforcement (empty ticker, invalid period raise)

### Testing

```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_stock_price.py -v
# → 30+ passed
```

No regression in the existing test suite:

```bash
python -m pytest --tb=short
# → all passed
```

Coverage on `stock_price.py`: **>90%**

### LangSmith Trace

_Not applicable — this PR adds a data tool (no LLM calls). LangSmith traces will appear once agents call this tool in Phase 2 (T-021)._

### Screenshots

```
backend/tests/unit/test_stock_price.py::TestComputePctChange::test_normal_positive_return PASSED
backend/tests/unit/test_stock_price.py::TestComputePctChange::test_negative_return PASSED
backend/tests/unit/test_stock_price.py::TestComputeSma::test_50_period_sma PASSED
backend/tests/unit/test_stock_price.py::TestFetchFromYfinance::test_returns_stock_price_model PASSED
backend/tests/unit/test_stock_price.py::TestFetchFromYfinance::test_raises_ticker_not_found_on_empty_df PASSED
backend/tests/unit/test_stock_price.py::TestFetchStockPriceTool::test_tool_returns_dict_on_success PASSED
backend/tests/unit/test_stock_price.py::TestFetchStockPriceTool::test_tool_returns_error_dict_on_ticker_not_found PASSED
...
====== 30+ passed ======
```

### Related Issues

Closes #10

---

## Architecture Notes for Future Tasks

### How agents will call this tool (Phase 2 — T-021 onwards)

```python
# Inside FundamentalAnalystAgent (T-021)
from backend.tools.stock_price import fetch_stock_price

result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "3y"})

if "error" in result:
    # Route to error state in LangGraph
    return {"error": result["error"], "message": result["message"]}

current_price = result["stats"]["current_price"]
pct_change_1y = result["stats"]["pct_change_1y"]
ma_50d = result["stats"]["ma_50d"]
```

### Indian ticker conventions

| Exchange | Suffix | Example                            |
| -------- | ------ | ---------------------------------- |
| NSE      | `.NS`  | `TCS.NS`, `INFY.NS`, `RELIANCE.NS` |
| BSE      | `.BO`  | `532540.BO` (TCS BSE code)         |
| US       | none   | `AAPL`, `MSFT`                     |

> **Why `.NS` and not just `TCS`?** yFinance uses Yahoo Finance's ticker namespace. Indian NSE stocks require the `.NS` suffix to distinguish them from US tickers with the same symbol. This is documented in the tool's docstring and is a common gotcha for Indian market developers.

### Output model used by downstream agents

```
StockPrice
├── ticker: str                    (e.g. "TCS.NS")
├── company_name: str              (e.g. "Tata Consultancy Services Limited")
├── exchange: str                  (e.g. "NSE")
├── currency: str                  (e.g. "INR")
├── period: str                    (e.g. "1y")
├── data_points: int               (e.g. 248)
├── first_date: date
├── last_date: date
├── stats: PriceStats
│   ├── current_price: float
│   ├── price_52w_high: float
│   ├── price_52w_low: float
│   ├── avg_volume_30d: int
│   ├── pct_change_1m: float
│   ├── pct_change_3m: float
│   ├── pct_change_1y: float
│   ├── ma_50d: float | None
│   ├── ma_200d: float | None
│   ├── above_ma_50d: bool | None
│   └── above_ma_200d: bool | None
├── ohlcv: list[OHLCVRecord]
│   └── {date, open, high, low, close, volume}
├── fetched_at: datetime
└── source: str                    (always "yfinance")
```

---

## EOD Update Template

At the end of your working session, paste this into the Claude Project chat:

```
EOD Update [DATE]:
Completed: T-010
Merged to develop: feat/data-stock-price
Current week: 2 | Current phase: 1
Blocker (if any): None
Next session: T-011 — fetch_income_statement (Alpha Vantage + yFinance financials)
```
