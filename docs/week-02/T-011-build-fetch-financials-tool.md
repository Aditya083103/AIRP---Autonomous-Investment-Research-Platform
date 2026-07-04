# T-011 — Build `fetch_financials` Tool

**Phase:** 1 — Data Layer & APIs
**Week:** 2
**Branch:** `feat/data-financials`
**Commit prefix:** `feat(tools):`
**PR title:** `feat(tools): add fetch_financials, fetch_income_statement, fetch_balance_sheet, fetch_cash_flow tools with INR normalisation`

---

## Overview

Implements T-011: four LangChain tools that wrap yFinance to provide annual
financial statements (income statement, balance sheet, cash flow) for the last
4 fiscal years. All monetary values are normalised to **INR Crores** regardless
of the company's native reporting currency, so the Fundamental Analyst agent
always works in the same unit.

**Four tools delivered:**

| Tool                     | Data returned                                     |
| ------------------------ | ------------------------------------------------- |
| `fetch_financials`       | All three statements in one call (used by agents) |
| `fetch_income_statement` | Revenue, EBITDA, margins, EPS                     |
| `fetch_balance_sheet`    | Assets, debt, equity, current ratio               |
| `fetch_cash_flow`        | FCF, capex, FCF margin                            |

**Acceptance criteria:**

- Returns `FinancialStatements` Pydantic model (serialised to dict)
- Tests cover missing data — `None` fields returned, no crash
- Currency normalised to INR Crores for all monetary fields
- USD companies converted via fixed `USD_TO_INR = 83.5` constant

---

## Files Created in This Task

| File                                    | Action     | Purpose                                                                                                                                    |
| --------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `backend/tools/financials.py`           | **CREATE** | Four LangChain tools, Pydantic models (`FinancialStatements`, `IncomeStatementYear`, `BalanceSheetYear`, `CashFlowYear`), internal helpers |
| `backend/tests/unit/test_financials.py` | **CREATE** | 50+ unit tests — all yfinance mocked, covers missing data, USD conversion, ratio derivation, error handling                                |

---

## Step-by-Step: Branch → Commit → PR

### Step 1 — Checkout feature branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feat/data-financials
git branch
# → * feat/data-financials
```

---

### Step 2 — Place the files

Copy both delivered files into your repo exactly at these paths:

```
backend/tools/financials.py
backend/tests/unit/test_financials.py
```

---

### Step 3 — Run the tests

```bash
# From repo root, venv active
set ENVIRONMENT=test   # Windows
# export ENVIRONMENT=test  (Mac/Linux/Git Bash)

python -m pytest backend/tests/unit/test_financials.py -v
```

**Expected output:**

```
backend/tests/unit/test_financials.py::TestSafeGet::test_returns_float_for_valid_key_and_index PASSED
backend/tests/unit/test_financials.py::TestToCrores::test_inr_conversion PASSED
backend/tests/unit/test_financials.py::TestToCrores::test_usd_conversion PASSED
backend/tests/unit/test_financials.py::TestToCrores::test_inr_not_double_converted PASSED
...
====== 50+ passed in X.XXs ======
```

Run the full suite to confirm no regressions:

```bash
python -m pytest --tb=short
# → all passed (includes T-010 tests)
```

Coverage check:

```bash
python -m pytest backend/tests/unit/test_financials.py -v --cov=backend.tools.financials --cov-report=term-missing
```

---

### Step 4 — Commit

```bash
git add backend/tools/financials.py
git add backend/tests/unit/test_financials.py

git commit -m "feat(tools): add fetch_financials tool with INR normalisation and typed Pydantic models

- Implement FinancialStatements, IncomeStatementYear, BalanceSheetYear,
  CashFlowYear Pydantic output models
- Wrap yFinance income statement, balance sheet, cash flow (4-year annual)
- Normalise all monetary values to INR Crores (USD converted via USD_TO_INR=83.5)
- Derive margin ratios: gross, operating, net margins; FCF margin
- Derive computed fields: net debt, debt-to-equity, current ratio, FCF
- Add graceful missing-data handling: None fields, data_warnings list
- Add FinancialsNotFoundError with descriptive .NS/.BO suffix guidance
- Expose four tools: fetch_financials (all), fetch_income_statement,
  fetch_balance_sheet, fetch_cash_flow
- Add 50+ unit tests with mocked yfinance (zero real API calls)

Closes #11"

git push -u origin feat/data-financials
```

---

### Step 5 — Open the Pull Request on GitHub

- **Base branch:** `main`
- **Compare branch:** `feat/data-financials`

---

## Pull Request Template

**PR Title:**
`feat(tools): add fetch_financials, fetch_income_statement, fetch_balance_sheet, fetch_cash_flow tools with INR normalisation`

---

### Summary

Implements T-011: four LangChain tools wrapping yFinance to provide 4-year annual
financial statements for Indian and global equities. All monetary values are
normalised to INR Crores so the Fundamental Analyst agent always works in a
single consistent unit. Partial/missing data is handled gracefully — agents
receive `None` fields and populated `data_warnings` rather than crashes.

### Changes

**`backend/tools/financials.py`**

- `IncomeStatementYear` — revenue, gross profit, EBITDA, net income, EPS, 3 margin ratios
- `BalanceSheetYear` — assets, liabilities, equity, debt, cash, net debt, D/E ratio, current ratio
- `CashFlowYear` — operating/investing/financing CF, FCF, capex, FCF margin
- `FinancialStatements` — top-level model wrapping all three statements + metadata + warnings
- `FinancialsNotFoundError` — custom exception for invalid tickers
- Internal helpers: `_safe_get`, `_to_crores`, `_fiscal_year_label`, `_build_income_statement`, `_build_balance_sheet`, `_build_cash_flow`
- Four `@tool` functions: `fetch_financials`, `fetch_income_statement`, `fetch_balance_sheet`, `fetch_cash_flow`

**`backend/tests/unit/test_financials.py`**

- 50+ unit tests — all yfinance mocked, zero network calls
- `TestSafeGet` — empty df, None df, out-of-range index, missing row key
- `TestToCrores` — INR no double conversion, USD conversion, None passthrough
- `TestFiscalYearLabel` — valid dates, empty df, out-of-range
- `TestBuildIncomeStatement` — crore conversion, margin derivation, USD conversion, missing fields
- `TestBuildBalanceSheet` — net debt, D/E ratio, current ratio, missing debt
- `TestBuildCashFlow` — FCF = operating + capex, FCF margin from revenue, missing capex
- `TestFetchFinancialsFromYfinance` — success, invalid ticker, partial years, missing statements
- `TestFetchFinancialsTool` + single-statement tool tests — success, error dicts
- `TestFinancialStatementsValidation` — empty ticker raises `ValueError`

### Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_financials.py -v
# → 50+ passed

python -m pytest --tb=short
# → all passed, 0 regressions from T-010
```

### LangSmith Trace

_Not applicable — data tool with no LLM calls. Traces appear when
Fundamental Analyst agent calls this tool in T-021._

### Screenshots

```
backend/tests/unit/test_financials.py::TestSafeGet::test_returns_float_for_valid_key_and_index PASSED
backend/tests/unit/test_financials.py::TestToCrores::test_inr_not_double_converted PASSED
backend/tests/unit/test_financials.py::TestBuildIncomeStatement::test_gross_margin_computed_correctly PASSED
backend/tests/unit/test_financials.py::TestBuildCashFlow::test_fcf_is_operating_plus_capex PASSED
backend/tests/unit/test_financials.py::TestFetchFinancialsFromYfinance::test_raises_financials_not_found_when_all_empty PASSED
backend/tests/unit/test_financials.py::TestFetchFinancialsTool::test_currency_output_always_inr PASSED
...
====== 50+ passed ======
```

### Related Issues

Closes #11

---

## Architecture Notes

### Key design decisions

| Decision                                                                     | Rationale                                                                                                     |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `_fetch_financials_from_yfinance()` separated from `@tool`                   | Same testability pattern as T-010 — internal function is callable without LangChain tool machinery            |
| Fixed `USD_TO_INR = 83.5` constant                                           | Consistent unit across all 4 years. Live FX would mean year-over-year values are incomparable due to FX noise |
| `None` not `0.0` for missing data                                            | Agents must distinguish "zero revenue" from "data unavailable" — `None` is unambiguous                        |
| `data_warnings` list                                                         | Non-fatal issues surfaced to agents without crashing the pipeline                                             |
| All three statements fetched in one `_fetch_financials_from_yfinance()` call | Avoids 3 separate yFinance round-trips; individual tools slice the result                                     |

### yFinance row key reference

These are the exact string keys used from yFinance DataFrames. If yFinance changes its schema, update `_build_*` functions here:

**Income statement:**

```
"Total Revenue", "Gross Profit", "Operating Income",
"EBITDA", "Net Income", "Basic EPS"
```

**Balance sheet:**

```
"Total Assets", "Total Liabilities Net Minority Interest",
"Stockholders Equity", "Total Debt", "Cash And Cash Equivalents",
"Current Assets", "Current Liabilities"
```

**Cash flow:**

```
"Operating Cash Flow", "Investing Cash Flow",
"Financing Cash Flow", "Capital Expenditure"
```

### How agents use this tool (Phase 2 — T-021)

```python
# Inside FundamentalAnalystAgent
from backend.tools.financials import fetch_financials

result = fetch_financials.invoke({"ticker": "TCS.NS"})

if "error" in result:
    return {"error": result["error"], "message": result["message"]}

# Access 4 years of data — most recent first
latest = result["income_statement"][0]
revenue_crores = latest["revenue_crores"]       # e.g. 240890.5
net_margin = latest["net_margin_pct"]           # e.g. 18.7
fcf = result["cash_flow"][0]["free_cash_flow_crores"]  # e.g. 47000.0
net_debt = result["balance_sheet"][0]["net_debt_crores"]  # e.g. -25000.0 (net cash)

# Check data warnings before trusting the data
if result["data_warnings"]:
    # Log warnings but continue — partial data is still useful
    pass
```

### Output model structure

```
FinancialStatements
├── ticker: str                        ("TCS.NS")
├── company_name: str
├── currency_reported: str             ("INR" or "USD")
├── currency_output: str               (always "INR")
├── years_available: int               (max 4)
├── income_statement: list[IncomeStatementYear]
│   ├── fiscal_year: str               ("FY 2024")
│   ├── revenue_crores: float | None
│   ├── gross_profit_crores: float | None
│   ├── operating_income_crores: float | None
│   ├── ebitda_crores: float | None
│   ├── net_income_crores: float | None
│   ├── basic_eps: float | None        (INR per share, not divided by crores)
│   ├── gross_margin_pct: float | None
│   ├── operating_margin_pct: float | None
│   └── net_margin_pct: float | None
├── balance_sheet: list[BalanceSheetYear]
│   ├── fiscal_year: str
│   ├── total_assets_crores: float | None
│   ├── total_liabilities_crores: float | None
│   ├── total_equity_crores: float | None
│   ├── total_debt_crores: float | None
│   ├── cash_crores: float | None
│   ├── net_debt_crores: float | None  (negative = net cash position)
│   ├── debt_to_equity: float | None
│   └── current_ratio: float | None
├── cash_flow: list[CashFlowYear]
│   ├── fiscal_year: str
│   ├── operating_cash_flow_crores: float | None
│   ├── investing_cash_flow_crores: float | None
│   ├── financing_cash_flow_crores: float | None
│   ├── free_cash_flow_crores: float | None
│   ├── capital_expenditure_crores: float | None
│   └── fcf_margin_pct: float | None
├── fetched_at: datetime
├── source: str                        ("yfinance")
└── data_warnings: list[str]          (non-fatal issues)
```

---

## EOD Update Template

```
EOD Update [DATE]:
Completed: T-011
Merged to main: feat/data-financials
Current week: 2 | Current phase: 1
Blocker: None
Next session: T-012 — fetch_ratios tool (Screener.in scraping — PE, PB, EV/EBITDA, peer comparison)
```
