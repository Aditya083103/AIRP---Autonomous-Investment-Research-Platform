# backend/tools/financials.py
"""
AIRP — fetch_financials LangChain Tools

Wraps yFinance to provide annual financial statements for Indian and global
equities. Returns fully-typed Pydantic models so agents always receive
structured, validated data — never raw DataFrames.

Tools exposed:
    fetch_income_statement  — Revenue, EBITDA, net income, EPS (4 years)
    fetch_balance_sheet     — Assets, liabilities, equity, debt (4 years)
    fetch_cash_flow         — Operating, investing, financing cash flows (4 years)
    fetch_financials        — All three statements in one call (convenience tool)

Data source: yFinance (unofficial Yahoo Finance API — no key required)
Currency:    All monetary values normalised to INR (Crores).
             USD figures are converted using a hardcoded exchange rate constant
             (USD_TO_INR) so agents always work in the same unit regardless of
             the stock's native reporting currency.

Indian ticker convention:
    NSE stocks → append `.NS`  (e.g. TCS → TCS.NS)
    BSE stocks → append `.BO`  (e.g. TCS → 532540.BO)

Usage (inside an agent):
    from backend.tools.financials import fetch_financials
    result = fetch_financials.invoke({"ticker": "TCS.NS"})
    revenue_crores = result["income_statement"][0]["revenue_crores"]
"""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

from backend.tools.market_data import get_shared_ticker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Approximate USD → INR conversion rate used when yFinance reports in USD.
# This is intentionally a constant — financial ratios and trend analysis
# don't require live FX rates; consistency across years matters more.
USD_TO_INR: float = 83.5

# yFinance reports raw numbers (e.g. 1_000_000_000 for 1 billion).
# Indian financial reports use Crores (1 Crore = 10 million = 1e7).
# All monetary output fields are in Crores INR.
UNITS_TO_CRORES: float = 1e7  # divide raw yFinance numbers by this

MAX_YEARS: int = 4  # always fetch the last 4 annual periods


# ---------------------------------------------------------------------------
# Helper: safe extraction from yFinance financials DataFrame
# ---------------------------------------------------------------------------


def _safe_get(df: Any, row_key: str, col_index: int) -> float | None:
    """
    Safely extract a single float value from a yFinance financials DataFrame.

    yFinance returns transposed DataFrames where:
      - Rows    = financial line items  (e.g. "Total Revenue")
      - Columns = fiscal year dates     (most recent first)

    Returns None (not 0.0) when data is missing, so agents can distinguish
    "company had zero revenue" from "data unavailable for this period".

    Args:
        df:         yFinance financials DataFrame (may be empty).
        row_key:    Exact row label as yFinance returns it.
        col_index:  Column index (0 = most recent year).

    Returns:
        Float value in original yFinance units, or None.
    """
    if df is None or df.empty:
        return None
    if row_key not in df.index:
        return None
    cols = list(df.columns)
    if col_index >= len(cols):
        return None
    val = df.loc[row_key, cols[col_index]]
    if val is None:
        return None
    try:
        fval = float(val)
        return None if (fval != fval) else fval  # NaN check without math import
    except (TypeError, ValueError):
        return None


def _to_crores(raw: float | None, currency: str) -> float | None:
    """
    Convert a raw yFinance monetary value to INR Crores.

    Steps:
      1. If currency is USD, multiply by USD_TO_INR exchange rate.
      2. Divide by UNITS_TO_CRORES (1e7) to get Crores.

    Returns None if input is None.
    """
    if raw is None:
        return None
    inr_raw = raw * USD_TO_INR if currency.upper() == "USD" else raw
    return round(inr_raw / UNITS_TO_CRORES, 2)


def _fiscal_year_label(df: Any, col_index: int) -> str:
    """
    Extract a human-readable fiscal year label from a yFinance DataFrame column.

    yFinance column headers are Timestamps. We format them as "FY YYYY"
    using the calendar year of the fiscal year-end date.

    Returns "FY Unknown" if the column cannot be parsed.
    """
    if df is None or df.empty:
        return "FY Unknown"
    cols = list(df.columns)
    if col_index >= len(cols):
        return "FY Unknown"
    col = cols[col_index]
    try:
        year = col.year if hasattr(col, "year") else int(str(col)[:4])
        return f"FY {year}"
    except Exception:
        return "FY Unknown"


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------


class IncomeStatementYear(BaseModel):
    """Income statement data for a single fiscal year."""

    fiscal_year: str = Field(description="Fiscal year label, e.g. 'FY 2024'")
    revenue_crores: float | None = Field(
        default=None,
        description="Total revenue in INR Crores",
    )
    gross_profit_crores: float | None = Field(
        default=None,
        description="Gross profit in INR Crores",
    )
    operating_income_crores: float | None = Field(
        default=None,
        description="Operating income (EBIT) in INR Crores",
    )
    ebitda_crores: float | None = Field(
        default=None,
        description="EBITDA in INR Crores",
    )
    net_income_crores: float | None = Field(
        default=None,
        description="Net income (PAT) in INR Crores",
    )
    basic_eps: float | None = Field(
        default=None,
        description="Basic earnings per share in INR",
    )
    gross_margin_pct: float | None = Field(
        default=None,
        description="Gross margin as a percentage (0–100)",
    )
    operating_margin_pct: float | None = Field(
        default=None,
        description="Operating margin as a percentage (0–100)",
    )
    net_margin_pct: float | None = Field(
        default=None,
        description="Net profit margin as a percentage (0–100)",
    )

    model_config = {"frozen": True}


class BalanceSheetYear(BaseModel):
    """Balance sheet data for a single fiscal year."""

    fiscal_year: str = Field(description="Fiscal year label, e.g. 'FY 2024'")
    total_assets_crores: float | None = Field(
        default=None,
        description="Total assets in INR Crores",
    )
    total_liabilities_crores: float | None = Field(
        default=None,
        description="Total liabilities in INR Crores",
    )
    total_equity_crores: float | None = Field(
        default=None,
        description="Shareholders equity in INR Crores",
    )
    total_debt_crores: float | None = Field(
        default=None,
        description="Total debt (short + long term) in INR Crores",
    )
    cash_crores: float | None = Field(
        default=None,
        description="Cash and cash equivalents in INR Crores",
    )
    net_debt_crores: float | None = Field(
        default=None,
        description="Net debt (total debt minus cash) in INR Crores",
    )
    debt_to_equity: float | None = Field(
        default=None,
        description="Debt-to-equity ratio (unitless)",
    )
    current_ratio: float | None = Field(
        default=None,
        description="Current assets divided by current liabilities",
    )

    model_config = {"frozen": True}


class CashFlowYear(BaseModel):
    """Cash flow statement data for a single fiscal year."""

    fiscal_year: str = Field(description="Fiscal year label, e.g. 'FY 2024'")
    operating_cash_flow_crores: float | None = Field(
        default=None,
        description="Cash from operating activities in INR Crores",
    )
    investing_cash_flow_crores: float | None = Field(
        default=None,
        description="Cash from investing activities in INR Crores",
    )
    financing_cash_flow_crores: float | None = Field(
        default=None,
        description="Cash from financing activities in INR Crores",
    )
    free_cash_flow_crores: float | None = Field(
        default=None,
        description="Free cash flow (operating minus capex) in INR Crores",
    )
    capital_expenditure_crores: float | None = Field(
        default=None,
        description="Capital expenditure in INR Crores (positive = outflow)",
    )
    fcf_margin_pct: float | None = Field(
        default=None,
        description="Free cash flow as % of revenue (requires income statement)",
    )

    model_config = {"frozen": True}


class FinancialStatements(BaseModel):
    """
    Complete financial statements output model for the fetch_financials tool.

    Contains up to 4 years of income statement, balance sheet, and cash flow
    data. All monetary values are in INR Crores regardless of the company's
    native reporting currency.
    """

    ticker: str = Field(description="Ticker symbol as passed (e.g. 'TCS.NS')")
    company_name: str = Field(description="Company display name from Yahoo Finance")
    currency_reported: str = Field(
        description="Native reporting currency from yFinance (e.g. 'INR', 'USD')"
    )
    currency_output: str = Field(
        default="INR",
        description="All monetary output fields are always in INR Crores",
    )
    years_available: int = Field(
        description="Number of annual periods returned (max 4)"
    )
    income_statement: list[IncomeStatementYear] = Field(
        description="Annual income statement — most recent year first"
    )
    balance_sheet: list[BalanceSheetYear] = Field(
        description="Annual balance sheet — most recent year first"
    )
    cash_flow: list[CashFlowYear] = Field(
        description="Annual cash flow statement — most recent year first"
    )
    fetched_at: datetime = Field(description="UTC timestamp of this data fetch")
    source: str = Field(default="yfinance", description="Data provider identifier")
    data_warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings about missing or incomplete data",
    )

    @field_validator("ticker")
    @classmethod
    def ticker_must_be_non_empty(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("ticker must not be empty")
        return v


class FinancialsNotFoundError(Exception):
    """Raised when yFinance returns no financial data for the requested ticker."""


# ---------------------------------------------------------------------------
# Internal fetch logic
# ---------------------------------------------------------------------------


def _build_income_statement(
    income_df: Any,
    n_years: int,
    currency: str,
) -> list[IncomeStatementYear]:
    """Parse yFinance income statement DataFrame into typed yearly records."""
    records: list[IncomeStatementYear] = []

    for i in range(n_years):
        fy = _fiscal_year_label(income_df, i)

        revenue_raw = _safe_get(income_df, "Total Revenue", i)
        gross_profit_raw = _safe_get(income_df, "Gross Profit", i)
        operating_income_raw = _safe_get(income_df, "Operating Income", i)
        ebitda_raw = _safe_get(income_df, "EBITDA", i)
        net_income_raw = _safe_get(income_df, "Net Income", i)
        basic_eps_raw = _safe_get(income_df, "Basic EPS", i)

        revenue = _to_crores(revenue_raw, currency)
        gross_profit = _to_crores(gross_profit_raw, currency)
        operating_income = _to_crores(operating_income_raw, currency)
        ebitda = _to_crores(ebitda_raw, currency)
        net_income = _to_crores(net_income_raw, currency)

        # EPS is per-share — only currency conversion, no crore division
        basic_eps: float | None = None
        if basic_eps_raw is not None:
            raw_eps = (
                basic_eps_raw * USD_TO_INR
                if currency.upper() == "USD"
                else basic_eps_raw
            )
            basic_eps = round(raw_eps, 2)

        # Derived margin ratios
        gross_margin: float | None = None
        operating_margin: float | None = None
        net_margin: float | None = None

        if revenue and revenue != 0:
            if gross_profit is not None:
                gross_margin = round((gross_profit / revenue) * 100, 2)
            if operating_income is not None:
                operating_margin = round((operating_income / revenue) * 100, 2)
            if net_income is not None:
                net_margin = round((net_income / revenue) * 100, 2)

        records.append(
            IncomeStatementYear(
                fiscal_year=fy,
                revenue_crores=revenue,
                gross_profit_crores=gross_profit,
                operating_income_crores=operating_income,
                ebitda_crores=ebitda,
                net_income_crores=net_income,
                basic_eps=basic_eps,
                gross_margin_pct=gross_margin,
                operating_margin_pct=operating_margin,
                net_margin_pct=net_margin,
            )
        )
    return records


def _build_balance_sheet(
    balance_df: Any,
    n_years: int,
    currency: str,
) -> list[BalanceSheetYear]:
    """Parse yFinance balance sheet DataFrame into typed yearly records."""
    records: list[BalanceSheetYear] = []

    for i in range(n_years):
        fy = _fiscal_year_label(balance_df, i)

        total_assets_raw = _safe_get(balance_df, "Total Assets", i)
        total_liabilities_raw = _safe_get(
            balance_df, "Total Liabilities Net Minority Interest", i
        )
        total_equity_raw = _safe_get(balance_df, "Stockholders Equity", i)
        total_debt_raw = _safe_get(balance_df, "Total Debt", i)
        cash_raw = _safe_get(balance_df, "Cash And Cash Equivalents", i)
        current_assets_raw = _safe_get(balance_df, "Current Assets", i)
        current_liabilities_raw = _safe_get(balance_df, "Current Liabilities", i)

        total_assets = _to_crores(total_assets_raw, currency)
        total_liabilities = _to_crores(total_liabilities_raw, currency)
        total_equity = _to_crores(total_equity_raw, currency)
        total_debt = _to_crores(total_debt_raw, currency)
        cash = _to_crores(cash_raw, currency)

        # Net debt = total debt - cash
        net_debt: float | None = None
        if total_debt is not None and cash is not None:
            net_debt = round(total_debt - cash, 2)

        # Debt-to-equity ratio
        debt_to_equity: float | None = None
        if total_debt is not None and total_equity and total_equity != 0:
            debt_to_equity = round(total_debt / total_equity, 4)

        # Current ratio
        current_ratio: float | None = None
        if current_assets_raw is not None and current_liabilities_raw:
            if current_liabilities_raw != 0:
                current_ratio = round(current_assets_raw / current_liabilities_raw, 4)

        records.append(
            BalanceSheetYear(
                fiscal_year=fy,
                total_assets_crores=total_assets,
                total_liabilities_crores=total_liabilities,
                total_equity_crores=total_equity,
                total_debt_crores=total_debt,
                cash_crores=cash,
                net_debt_crores=net_debt,
                debt_to_equity=debt_to_equity,
                current_ratio=current_ratio,
            )
        )
    return records


def _build_cash_flow(
    cashflow_df: Any,
    income_records: list[IncomeStatementYear],
    n_years: int,
    currency: str,
) -> list[CashFlowYear]:
    """Parse yFinance cash flow DataFrame into typed yearly records."""
    records: list[CashFlowYear] = []

    for i in range(n_years):
        fy = _fiscal_year_label(cashflow_df, i)

        operating_raw = _safe_get(cashflow_df, "Operating Cash Flow", i)
        investing_raw = _safe_get(cashflow_df, "Investing Cash Flow", i)
        financing_raw = _safe_get(cashflow_df, "Financing Cash Flow", i)
        capex_raw = _safe_get(cashflow_df, "Capital Expenditure", i)

        operating_cf = _to_crores(operating_raw, currency)
        investing_cf = _to_crores(investing_raw, currency)
        financing_cf = _to_crores(financing_raw, currency)
        capex = _to_crores(capex_raw, currency)

        # FCF = operating CF + capex (capex is negative in yFinance)
        free_cash_flow: float | None = None
        if operating_cf is not None and capex is not None:
            free_cash_flow = round(operating_cf + capex, 2)

        # FCF margin (requires revenue from the same year's income statement)
        fcf_margin: float | None = None
        if free_cash_flow is not None and i < len(income_records):
            revenue = income_records[i].revenue_crores
            if revenue and revenue != 0:
                fcf_margin = round((free_cash_flow / revenue) * 100, 2)

        records.append(
            CashFlowYear(
                fiscal_year=fy,
                operating_cash_flow_crores=operating_cf,
                investing_cash_flow_crores=investing_cf,
                financing_cash_flow_crores=financing_cf,
                free_cash_flow_crores=free_cash_flow,
                capital_expenditure_crores=capex,
                fcf_margin_pct=fcf_margin,
            )
        )
    return records


def _fetch_financials_from_yfinance(ticker: str) -> FinancialStatements:
    """
    Core yFinance fetch logic — separated from @tool decorator for testability.

    Fetches income statement, balance sheet, and cash flow for the last
    MAX_YEARS (4) annual periods. Handles partially missing data gracefully
    by returning None for unavailable fields and appending to data_warnings.

    Raises:
        FinancialsNotFoundError: if yFinance returns no financial data at all.
    """
    ticker = ticker.strip().upper()
    logger.info("Fetching yFinance financials: ticker=%s", ticker)

    yf_ticker = get_shared_ticker(ticker)

    # Fetch all three statements (annual=True is the default)
    income_df = yf_ticker.financials  # income statement
    balance_df = yf_ticker.balance_sheet  # balance sheet
    cashflow_df = yf_ticker.cashflow  # cash flow statement

    # Guard: if ALL three are empty, the ticker is invalid
    all_empty = (
        (income_df is None or income_df.empty)
        and (balance_df is None or balance_df.empty)
        and (cashflow_df is None or cashflow_df.empty)
    )
    if all_empty:
        raise FinancialsNotFoundError(
            f"No financial data found for ticker '{ticker}'. "
            "Verify the ticker symbol — Indian NSE stocks use '.NS' suffix "
            "(e.g. 'TCS.NS'), BSE stocks use '.BO'."
        )

    # Determine available years (use whichever statement has the most columns)
    n_years = MAX_YEARS
    for df in (income_df, balance_df, cashflow_df):
        if df is not None and not df.empty:
            n_years = min(MAX_YEARS, len(df.columns))
            break

    # Ticker metadata
    info: dict[str, Any] = {}
    try:
        info = yf_ticker.info or {}
    except Exception:
        logger.warning("Could not fetch ticker info for %s", ticker)

    company_name: str = info.get("longName") or info.get("shortName") or ticker
    currency: str = info.get("financialCurrency") or info.get("currency") or "INR"

    # Collect non-fatal warnings
    warnings: list[str] = []
    if income_df is None or income_df.empty:
        warnings.append("Income statement data unavailable from yFinance")
    if balance_df is None or balance_df.empty:
        warnings.append("Balance sheet data unavailable from yFinance")
    if cashflow_df is None or cashflow_df.empty:
        warnings.append("Cash flow data unavailable from yFinance")
    if n_years < MAX_YEARS:
        warnings.append(
            f"Only {n_years} annual period(s) available (expected {MAX_YEARS})"
        )

    # Build typed records
    income_records = _build_income_statement(income_df, n_years, currency)
    balance_records = _build_balance_sheet(balance_df, n_years, currency)
    cashflow_records = _build_cash_flow(cashflow_df, income_records, n_years, currency)

    return FinancialStatements(
        ticker=ticker,
        company_name=company_name,
        currency_reported=currency,
        currency_output="INR",
        years_available=n_years,
        income_statement=income_records,
        balance_sheet=balance_records,
        cash_flow=cashflow_records,
        fetched_at=datetime.utcnow(),
        source="yfinance",
        data_warnings=warnings,
    )


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def fetch_financials(ticker: str) -> dict[str, Any]:
    """
    Fetch the last 4 years of annual financial statements for a stock.

    Returns income statement, balance sheet, and cash flow data in a single
    call. All monetary values are normalised to INR Crores regardless of
    the company's native reporting currency (USD companies are converted
    using a fixed USD/INR rate).

    Args:
        ticker: Stock ticker with exchange suffix. Indian NSE stocks require
                '.NS' suffix (e.g. 'TCS.NS', 'INFY.NS', 'RELIANCE.NS').
                BSE stocks use '.BO'. US stocks use plain symbols ('AAPL').

    Returns:
        Dict representation of FinancialStatements model containing:
        - ticker, company_name, currency_reported, currency_output
        - years_available (int, max 4)
        - income_statement: list of IncomeStatementYear (revenue, margins, EPS)
        - balance_sheet: list of BalanceSheetYear (assets, debt, equity ratios)
        - cash_flow: list of CashFlowYear (FCF, capex, FCF margin)
        - data_warnings: list of strings for missing/partial data
        - fetched_at, source

    On error, returns a dict with an 'error' key instead of raising.

    Example:
        >>> result = fetch_financials.invoke({"ticker": "TCS.NS"})
        >>> result["income_statement"][0]["revenue_crores"]
        240890.5
    """
    try:
        data = _fetch_financials_from_yfinance(ticker=ticker)
        return data.model_dump(mode="json")
    except FinancialsNotFoundError as exc:
        logger.error("Financials not found: %s — %s", ticker, exc)
        return {
            "error": "financials_not_found",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_financials: ticker=%s", ticker)
        return {
            "error": "unexpected_error",
            "ticker": ticker.strip().upper(),
            "message": f"An unexpected error occurred: {exc}",
        }


@tool
def fetch_income_statement(ticker: str) -> dict[str, Any]:
    """
    Fetch the last 4 years of annual income statement data for a stock.

    Returns revenue, gross profit, operating income, EBITDA, net income,
    EPS, and derived margin ratios. All monetary values in INR Crores.

    Args:
        ticker: Stock ticker with exchange suffix (e.g. 'INFY.NS').

    Returns:
        Dict with keys: ticker, currency_reported, years_available,
        income_statement (list), data_warnings, fetched_at, source.
        Returns error dict on failure.
    """
    try:
        data = _fetch_financials_from_yfinance(ticker=ticker)
        return {
            "ticker": data.ticker,
            "currency_reported": data.currency_reported,
            "currency_output": data.currency_output,
            "years_available": data.years_available,
            "income_statement": [r.model_dump() for r in data.income_statement],
            "data_warnings": data.data_warnings,
            "fetched_at": data.fetched_at.isoformat(),
            "source": data.source,
        }
    except FinancialsNotFoundError as exc:
        return {
            "error": "financials_not_found",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception(
            "Unexpected error in fetch_income_statement: ticker=%s", ticker
        )
        return {
            "error": "unexpected_error",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }


@tool
def fetch_balance_sheet(ticker: str) -> dict[str, Any]:
    """
    Fetch the last 4 years of annual balance sheet data for a stock.

    Returns total assets, liabilities, equity, debt, cash, net debt,
    debt-to-equity ratio, and current ratio. All monetary values in INR Crores.

    Args:
        ticker: Stock ticker with exchange suffix (e.g. 'TCS.NS').

    Returns:
        Dict with keys: ticker, currency_reported, years_available,
        balance_sheet (list), data_warnings, fetched_at, source.
        Returns error dict on failure.
    """
    try:
        data = _fetch_financials_from_yfinance(ticker=ticker)
        return {
            "ticker": data.ticker,
            "currency_reported": data.currency_reported,
            "currency_output": data.currency_output,
            "years_available": data.years_available,
            "balance_sheet": [r.model_dump() for r in data.balance_sheet],
            "data_warnings": data.data_warnings,
            "fetched_at": data.fetched_at.isoformat(),
            "source": data.source,
        }
    except FinancialsNotFoundError as exc:
        return {
            "error": "financials_not_found",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_balance_sheet: ticker=%s", ticker)
        return {
            "error": "unexpected_error",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }


@tool
def fetch_cash_flow(ticker: str) -> dict[str, Any]:
    """
    Fetch the last 4 years of annual cash flow data for a stock.

    Returns operating, investing, financing cash flows, free cash flow,
    capex, and FCF margin. All monetary values in INR Crores.

    Args:
        ticker: Stock ticker with exchange suffix (e.g. 'RELIANCE.NS').

    Returns:
        Dict with keys: ticker, currency_reported, years_available,
        cash_flow (list), data_warnings, fetched_at, source.
        Returns error dict on failure.
    """
    try:
        data = _fetch_financials_from_yfinance(ticker=ticker)
        return {
            "ticker": data.ticker,
            "currency_reported": data.currency_reported,
            "currency_output": data.currency_output,
            "years_available": data.years_available,
            "cash_flow": [r.model_dump() for r in data.cash_flow],
            "data_warnings": data.data_warnings,
            "fetched_at": data.fetched_at.isoformat(),
            "source": data.source,
        }
    except FinancialsNotFoundError as exc:
        return {
            "error": "financials_not_found",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
    except Exception as exc:
        logger.exception("Unexpected error in fetch_cash_flow: ticker=%s", ticker)
        return {
            "error": "unexpected_error",
            "ticker": ticker.strip().upper(),
            "message": str(exc),
        }
