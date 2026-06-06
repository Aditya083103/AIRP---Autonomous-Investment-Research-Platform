# backend/tests/unit/test_financials.py
"""
Unit tests for backend/tools/financials.py — T-011

All yFinance calls are mocked via unittest.mock.patch so these tests run
offline, in CI, and without consuming any real API quota.

Test coverage targets (acceptance criteria from T-011):
  ✓ fetch_financials returns dict matching the FinancialStatements schema
  ✓ fetch_income_statement / fetch_balance_sheet / fetch_cash_flow return
    single-statement slices (correct keys, no other statements present)
  ✓ Missing data (None fields) handled gracefully — no crash,
    data_warnings populated
  ✓ Completely empty DataFrames raise FinancialsNotFoundError (graceful error dict)
  ✓ USD → INR currency conversion applied correctly
  ✓ INR values NOT double-converted (no extra multiplication)
  ✓ Margin ratios derived correctly from raw figures
  ✓ FCF = operating CF + capex (capex negative in yFinance)
  ✓ FCF margin computed from FCF / revenue
  ✓ Fewer than 4 years available → data_warnings populated, no crash
  ✓ Invalid ticker returns error dict with 'financials_not_found' key
  ✓ Unexpected exception returns error dict with 'unexpected_error' key
  ✓ ticker normalised to uppercase

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_financials.py -v
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

from datetime import datetime  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend.tools.financials import (  # noqa: E402
    UNITS_TO_CRORES,
    USD_TO_INR,
    FinancialsNotFoundError,
    FinancialStatements,
    _build_balance_sheet,
    _build_cash_flow,
    _build_income_statement,
    _fetch_financials_from_yfinance,
    _fiscal_year_label,
    _safe_get,
    _to_crores,
    fetch_balance_sheet,
    fetch_cash_flow,
    fetch_financials,
    fetch_income_statement,
)

# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

# Realistic scale: TCS FY2024 revenue ~240,000 Crores → raw INR = 240,000 * 1e7
_REVENUE_RAW = 240_000 * UNITS_TO_CRORES  # ~2.4e12
_GROSS_PROFIT_RAW = 80_000 * UNITS_TO_CRORES  # 80,000 Cr
_OP_INCOME_RAW = 50_000 * UNITS_TO_CRORES  # 50,000 Cr
_EBITDA_RAW = 60_000 * UNITS_TO_CRORES  # 60,000 Cr
_NET_INCOME_RAW = 45_000 * UNITS_TO_CRORES  # 45,000 Cr
_EPS_RAW = 122.5  # INR per share (not divided by crores)

_TOTAL_ASSETS_RAW = 150_000 * UNITS_TO_CRORES
_TOTAL_LIAB_RAW = 60_000 * UNITS_TO_CRORES
_TOTAL_EQUITY_RAW = 90_000 * UNITS_TO_CRORES
_TOTAL_DEBT_RAW = 5_000 * UNITS_TO_CRORES
_CASH_RAW = 30_000 * UNITS_TO_CRORES
_CURRENT_ASSETS_RAW = 70_000 * UNITS_TO_CRORES
_CURRENT_LIAB_RAW = 35_000 * UNITS_TO_CRORES

_OPERATING_CF_RAW = 55_000 * UNITS_TO_CRORES
_INVESTING_CF_RAW = -20_000 * UNITS_TO_CRORES
_FINANCING_CF_RAW = -15_000 * UNITS_TO_CRORES
_CAPEX_RAW = -8_000 * UNITS_TO_CRORES  # negative = cash outflow


def _make_dates(n: int = 4) -> pd.DatetimeIndex:
    """Return n fiscal year-end dates, most recent first."""
    return pd.to_datetime([f"{2024 - i}-03-31" for i in range(n)])


def _make_income_df(n_years: int = 4) -> pd.DataFrame:
    """Build a realistic income statement DataFrame.

    yFinance shape: rows=items, cols=dates.
    """
    dates = _make_dates(n_years)
    return pd.DataFrame(
        {
            "Total Revenue": [_REVENUE_RAW] * n_years,
            "Gross Profit": [_GROSS_PROFIT_RAW] * n_years,
            "Operating Income": [_OP_INCOME_RAW] * n_years,
            "EBITDA": [_EBITDA_RAW] * n_years,
            "Net Income": [_NET_INCOME_RAW] * n_years,
            "Basic EPS": [_EPS_RAW] * n_years,
        },
        index=dates,
    ).T  # transpose so rows = items, cols = dates


def _make_balance_df(n_years: int = 4) -> pd.DataFrame:
    dates = _make_dates(n_years)
    return pd.DataFrame(
        {
            "Total Assets": [_TOTAL_ASSETS_RAW] * n_years,
            "Total Liabilities Net Minority Interest": [_TOTAL_LIAB_RAW] * n_years,
            "Stockholders Equity": [_TOTAL_EQUITY_RAW] * n_years,
            "Total Debt": [_TOTAL_DEBT_RAW] * n_years,
            "Cash And Cash Equivalents": [_CASH_RAW] * n_years,
            "Current Assets": [_CURRENT_ASSETS_RAW] * n_years,
            "Current Liabilities": [_CURRENT_LIAB_RAW] * n_years,
        },
        index=dates,
    ).T


def _make_cashflow_df(n_years: int = 4) -> pd.DataFrame:
    dates = _make_dates(n_years)
    return pd.DataFrame(
        {
            "Operating Cash Flow": [_OPERATING_CF_RAW] * n_years,
            "Investing Cash Flow": [_INVESTING_CF_RAW] * n_years,
            "Financing Cash Flow": [_FINANCING_CF_RAW] * n_years,
            "Capital Expenditure": [_CAPEX_RAW] * n_years,
        },
        index=dates,
    ).T


def _make_ticker_mock(
    income_df: pd.DataFrame | None = None,
    balance_df: pd.DataFrame | None = None,
    cashflow_df: pd.DataFrame | None = None,
    currency: str = "INR",
) -> MagicMock:
    """Build a fully configured mocked yf.Ticker object."""
    mock = MagicMock()
    mock.financials = income_df if income_df is not None else _make_income_df()
    mock.balance_sheet = balance_df if balance_df is not None else _make_balance_df()
    mock.cashflow = cashflow_df if cashflow_df is not None else _make_cashflow_df()
    mock.info = {
        "longName": "Tata Consultancy Services Limited",
        "exchange": "NSE",
        "currency": currency,
        "financialCurrency": currency,
    }
    return mock


def _make_empty_ticker_mock() -> MagicMock:
    """Mocked ticker that returns empty DataFrames for all three statements."""
    mock = MagicMock()
    mock.financials = pd.DataFrame()
    mock.balance_sheet = pd.DataFrame()
    mock.cashflow = pd.DataFrame()
    mock.info = {}
    return mock


# ---------------------------------------------------------------------------
# Tests: _safe_get (pure helper)
# ---------------------------------------------------------------------------


class TestSafeGet:
    def test_returns_float_for_valid_key_and_index(self) -> None:
        df = _make_income_df()
        val = _safe_get(df, "Total Revenue", 0)
        assert val == pytest.approx(_REVENUE_RAW)

    def test_returns_none_for_missing_row_key(self) -> None:
        df = _make_income_df()
        assert _safe_get(df, "Nonexistent Line Item", 0) is None

    def test_returns_none_for_out_of_range_col_index(self) -> None:
        df = _make_income_df(n_years=2)
        assert _safe_get(df, "Total Revenue", 5) is None

    def test_returns_none_for_empty_dataframe(self) -> None:
        assert _safe_get(pd.DataFrame(), "Total Revenue", 0) is None

    def test_returns_none_for_none_dataframe(self) -> None:
        assert _safe_get(None, "Total Revenue", 0) is None


# ---------------------------------------------------------------------------
# Tests: _to_crores (pure helper)
# ---------------------------------------------------------------------------


class TestToCrores:
    def test_inr_conversion(self) -> None:
        raw = 1e7  # 1 Crore in raw INR
        result = _to_crores(raw, "INR")
        assert result == pytest.approx(1.0, abs=0.01)

    def test_usd_conversion(self) -> None:
        raw = 1e7  # USD
        result = _to_crores(raw, "USD")
        expected = (1e7 * USD_TO_INR) / UNITS_TO_CRORES
        assert result == pytest.approx(expected, abs=0.01)

    def test_none_input_returns_none(self) -> None:
        assert _to_crores(None, "INR") is None

    def test_inr_not_double_converted(self) -> None:
        raw = 100 * UNITS_TO_CRORES  # 100 Crores in raw INR
        result = _to_crores(raw, "INR")
        assert result == pytest.approx(100.0, abs=0.01)

    def test_currency_case_insensitive(self) -> None:
        raw = 1e7
        assert _to_crores(raw, "usd") == pytest.approx(_to_crores(raw, "USD"))


# ---------------------------------------------------------------------------
# Tests: _fiscal_year_label (pure helper)
# ---------------------------------------------------------------------------


class TestFiscalYearLabel:
    def test_returns_fy_year_string(self) -> None:
        df = _make_income_df()
        label = _fiscal_year_label(df, 0)
        assert label == "FY 2024"

    def test_second_column_is_one_year_earlier(self) -> None:
        df = _make_income_df()
        assert _fiscal_year_label(df, 1) == "FY 2023"

    def test_returns_unknown_for_empty_df(self) -> None:
        assert _fiscal_year_label(pd.DataFrame(), 0) == "FY Unknown"

    def test_returns_unknown_for_none_df(self) -> None:
        assert _fiscal_year_label(None, 0) == "FY Unknown"

    def test_returns_unknown_for_out_of_range_index(self) -> None:
        df = _make_income_df(n_years=2)
        assert _fiscal_year_label(df, 5) == "FY Unknown"


# ---------------------------------------------------------------------------
# Tests: _build_income_statement (pure builder)
# ---------------------------------------------------------------------------


class TestBuildIncomeStatement:
    def test_returns_correct_number_of_years(self) -> None:
        records = _build_income_statement(_make_income_df(), 4, "INR")
        assert len(records) == 4

    def test_revenue_converted_to_crores(self) -> None:
        records = _build_income_statement(_make_income_df(), 4, "INR")
        assert records[0].revenue_crores == pytest.approx(240_000.0, abs=1.0)

    def test_gross_margin_computed_correctly(self) -> None:
        records = _build_income_statement(_make_income_df(), 4, "INR")
        expected = (_GROSS_PROFIT_RAW / _REVENUE_RAW) * 100
        assert records[0].gross_margin_pct == pytest.approx(expected, abs=0.1)

    def test_net_margin_computed_correctly(self) -> None:
        records = _build_income_statement(_make_income_df(), 4, "INR")
        expected = (_NET_INCOME_RAW / _REVENUE_RAW) * 100
        assert records[0].net_margin_pct == pytest.approx(expected, abs=0.1)

    def test_eps_not_divided_by_crores(self) -> None:
        records = _build_income_statement(_make_income_df(), 4, "INR")
        assert records[0].basic_eps == pytest.approx(_EPS_RAW, abs=0.01)

    def test_usd_revenue_multiplied_by_exchange_rate(self) -> None:
        records_inr = _build_income_statement(_make_income_df(), 1, "INR")
        records_usd = _build_income_statement(_make_income_df(), 1, "USD")
        assert records_usd[0].revenue_crores == pytest.approx(
            records_inr[0].revenue_crores * USD_TO_INR, rel=0.01
        )

    def test_missing_ebitda_field_returns_none(self) -> None:
        df = _make_income_df()
        df = df.drop("EBITDA", errors="ignore")
        records = _build_income_statement(df, 4, "INR")
        assert records[0].ebitda_crores is None

    def test_empty_df_returns_records_with_none_fields(self) -> None:
        records = _build_income_statement(pd.DataFrame(), 1, "INR")
        assert records[0].revenue_crores is None
        assert records[0].gross_margin_pct is None

    def test_fiscal_year_label_matches_expected(self) -> None:
        records = _build_income_statement(_make_income_df(), 4, "INR")
        assert records[0].fiscal_year == "FY 2024"
        assert records[1].fiscal_year == "FY 2023"


# ---------------------------------------------------------------------------
# Tests: _build_balance_sheet (pure builder)
# ---------------------------------------------------------------------------


class TestBuildBalanceSheet:
    def test_total_assets_in_crores(self) -> None:
        records = _build_balance_sheet(_make_balance_df(), 4, "INR")
        assert records[0].total_assets_crores == pytest.approx(150_000.0, abs=1.0)

    def test_net_debt_computed_as_debt_minus_cash(self) -> None:
        records = _build_balance_sheet(_make_balance_df(), 4, "INR")
        expected = 5_000.0 - 30_000.0  # total_debt - cash = -25,000 (net cash)
        assert records[0].net_debt_crores == pytest.approx(expected, abs=1.0)

    def test_debt_to_equity_ratio(self) -> None:
        records = _build_balance_sheet(_make_balance_df(), 4, "INR")
        expected = 5_000.0 / 90_000.0
        assert records[0].debt_to_equity == pytest.approx(expected, abs=0.0001)

    def test_current_ratio(self) -> None:
        records = _build_balance_sheet(_make_balance_df(), 4, "INR")
        expected = _CURRENT_ASSETS_RAW / _CURRENT_LIAB_RAW
        assert records[0].current_ratio == pytest.approx(expected, abs=0.001)

    def test_missing_debt_field_gives_none_net_debt(self) -> None:
        df = _make_balance_df()
        df = df.drop("Total Debt", errors="ignore")
        records = _build_balance_sheet(df, 4, "INR")
        assert records[0].total_debt_crores is None
        assert records[0].net_debt_crores is None

    def test_empty_df_returns_none_fields(self) -> None:
        records = _build_balance_sheet(pd.DataFrame(), 1, "INR")
        assert records[0].total_assets_crores is None
        assert records[0].debt_to_equity is None


# ---------------------------------------------------------------------------
# Tests: _build_cash_flow (pure builder)
# ---------------------------------------------------------------------------


class TestBuildCashFlow:
    def _income_records(self) -> list[Any]:
        return _build_income_statement(_make_income_df(), 4, "INR")

    def test_operating_cf_in_crores(self) -> None:
        records = _build_cash_flow(
            _make_cashflow_df(), self._income_records(), 4, "INR"
        )
        assert records[0].operating_cash_flow_crores == pytest.approx(55_000.0, abs=1.0)

    def test_fcf_is_operating_plus_capex(self) -> None:
        records = _build_cash_flow(
            _make_cashflow_df(), self._income_records(), 4, "INR"
        )
        expected = 55_000.0 + (-8_000.0)  # 47,000 Crores
        assert records[0].free_cash_flow_crores == pytest.approx(expected, abs=1.0)

    def test_fcf_margin_computed_from_revenue(self) -> None:
        income = self._income_records()
        records = _build_cash_flow(_make_cashflow_df(), income, 4, "INR")
        fcf = records[0].free_cash_flow_crores
        revenue = income[0].revenue_crores
        expected = (fcf / revenue) * 100
        assert records[0].fcf_margin_pct == pytest.approx(expected, abs=0.1)

    def test_missing_capex_gives_none_fcf(self) -> None:
        df = _make_cashflow_df()
        df = df.drop("Capital Expenditure", errors="ignore")
        records = _build_cash_flow(df, self._income_records(), 4, "INR")
        assert records[0].free_cash_flow_crores is None
        assert records[0].fcf_margin_pct is None

    def test_empty_df_returns_none_fields(self) -> None:
        records = _build_cash_flow(pd.DataFrame(), [], 1, "INR")
        assert records[0].operating_cash_flow_crores is None


# ---------------------------------------------------------------------------
# Tests: _fetch_financials_from_yfinance (core fetch — yf.Ticker mocked)
# ---------------------------------------------------------------------------


class TestFetchFinancialsFromYfinance:
    def test_returns_financial_statements_model(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("TCS.NS")
        assert isinstance(result, FinancialStatements)
        assert result.ticker == "TCS.NS"
        assert result.source == "yfinance"

    def test_ticker_uppercased(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("tcs.ns")
        assert result.ticker == "TCS.NS"

    def test_years_available_is_4_for_full_data(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("TCS.NS")
        assert result.years_available == 4

    def test_currency_output_always_inr(self) -> None:
        mock = _make_ticker_mock(currency="USD")
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("AAPL")
        assert result.currency_output == "INR"

    def test_raises_financials_not_found_when_all_empty(self) -> None:
        mock = _make_empty_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            with pytest.raises(FinancialsNotFoundError, match="TCS.NS"):
                _fetch_financials_from_yfinance("TCS.NS")

    def test_warning_added_when_fewer_than_4_years(self) -> None:
        mock = _make_ticker_mock(
            income_df=_make_income_df(n_years=2),
            balance_df=_make_balance_df(n_years=2),
            cashflow_df=_make_cashflow_df(n_years=2),
        )
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("TCS.NS")
        assert result.years_available == 2
        assert any("2 annual period" in w for w in result.data_warnings)

    def test_warning_added_when_income_statement_missing(self) -> None:
        mock = _make_ticker_mock(income_df=pd.DataFrame())
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("TCS.NS")
        assert any("Income statement" in w for w in result.data_warnings)

    def test_no_crash_when_balance_sheet_empty(self) -> None:
        mock = _make_ticker_mock(balance_df=pd.DataFrame())
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("TCS.NS")
        assert result.balance_sheet[0].total_assets_crores is None

    def test_company_name_from_info(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("TCS.NS")
        assert result.company_name == "Tata Consultancy Services Limited"

    def test_all_three_statement_lists_present(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = _fetch_financials_from_yfinance("TCS.NS")
        assert len(result.income_statement) == 4
        assert len(result.balance_sheet) == 4
        assert len(result.cash_flow) == 4


# ---------------------------------------------------------------------------
# Tests: fetch_financials (LangChain @tool)
# ---------------------------------------------------------------------------


class TestFetchFinancialsTool:
    def test_returns_dict_on_success(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_financials.invoke({"ticker": "TCS.NS"})
        assert isinstance(result, dict)
        assert "error" not in result
        assert "income_statement" in result
        assert "balance_sheet" in result
        assert "cash_flow" in result

    def test_income_statement_has_expected_keys(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_financials.invoke({"ticker": "TCS.NS"})
        first = result["income_statement"][0]
        for key in ("fiscal_year", "revenue_crores", "net_margin_pct", "basic_eps"):
            assert key in first

    def test_balance_sheet_has_expected_keys(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_financials.invoke({"ticker": "TCS.NS"})
        first = result["balance_sheet"][0]
        for key in (
            "total_assets_crores",
            "net_debt_crores",
            "debt_to_equity",
            "current_ratio",
        ):
            assert key in first

    def test_cash_flow_has_expected_keys(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_financials.invoke({"ticker": "TCS.NS"})
        first = result["cash_flow"][0]
        for key in (
            "operating_cash_flow_crores",
            "free_cash_flow_crores",
            "fcf_margin_pct",
        ):
            assert key in first

    def test_error_dict_on_invalid_ticker(self) -> None:
        mock = _make_empty_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_financials.invoke({"ticker": "FAKE.NS"})
        assert result["error"] == "financials_not_found"
        assert "FAKE.NS" in result["ticker"]

    def test_error_dict_on_unexpected_exception(self) -> None:
        # Raise at the Ticker() constructor level so it bypasses the
        # all_empty guard and hits the bare `except Exception` branch.
        with patch(
            "backend.tools.financials.yf.Ticker",
            side_effect=RuntimeError("yfinance internal crash"),
        ):
            result = fetch_financials.invoke({"ticker": "TCS.NS"})
        assert result["error"] == "unexpected_error"

    def test_currency_output_always_inr(self) -> None:
        mock = _make_ticker_mock(currency="USD")
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_financials.invoke({"ticker": "AAPL"})
        assert result.get("currency_output") == "INR"

    def test_data_warnings_key_present(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_financials.invoke({"ticker": "TCS.NS"})
        assert "data_warnings" in result
        assert isinstance(result["data_warnings"], list)


# ---------------------------------------------------------------------------
# Tests: fetch_income_statement (single-statement @tool)
# ---------------------------------------------------------------------------


class TestFetchIncomeStatementTool:
    def test_returns_income_statement_only(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_income_statement.invoke({"ticker": "TCS.NS"})
        assert "income_statement" in result
        assert "balance_sheet" not in result
        assert "cash_flow" not in result

    def test_error_on_empty_data(self) -> None:
        mock = _make_empty_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_income_statement.invoke({"ticker": "FAKE.NS"})
        assert result["error"] == "financials_not_found"


# ---------------------------------------------------------------------------
# Tests: fetch_balance_sheet (single-statement @tool)
# ---------------------------------------------------------------------------


class TestFetchBalanceSheetTool:
    def test_returns_balance_sheet_only(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_balance_sheet.invoke({"ticker": "TCS.NS"})
        assert "balance_sheet" in result
        assert "income_statement" not in result
        assert "cash_flow" not in result

    def test_error_on_empty_data(self) -> None:
        mock = _make_empty_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_balance_sheet.invoke({"ticker": "FAKE.NS"})
        assert result["error"] == "financials_not_found"


# ---------------------------------------------------------------------------
# Tests: fetch_cash_flow (single-statement @tool)
# ---------------------------------------------------------------------------


class TestFetchCashFlowTool:
    def test_returns_cash_flow_only(self) -> None:
        mock = _make_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_cash_flow.invoke({"ticker": "TCS.NS"})
        assert "cash_flow" in result
        assert "income_statement" not in result
        assert "balance_sheet" not in result

    def test_error_on_empty_data(self) -> None:
        mock = _make_empty_ticker_mock()
        with patch("backend.tools.financials.yf.Ticker", return_value=mock):
            result = fetch_cash_flow.invoke({"ticker": "FAKE.NS"})
        assert result["error"] == "financials_not_found"


# ---------------------------------------------------------------------------
# Tests: Pydantic model validation
# ---------------------------------------------------------------------------


class TestFinancialStatementsValidation:
    def test_empty_ticker_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="ticker"):
            FinancialStatements(
                ticker="",
                company_name="Test",
                currency_reported="INR",
                currency_output="INR",
                years_available=4,
                income_statement=[],
                balance_sheet=[],
                cash_flow=[],
                fetched_at=datetime.utcnow(),
            )

    def test_valid_model_instantiates_correctly(self) -> None:
        model = FinancialStatements(
            ticker="TCS.NS",
            company_name="TCS",
            currency_reported="INR",
            currency_output="INR",
            years_available=4,
            income_statement=[],
            balance_sheet=[],
            cash_flow=[],
            fetched_at=datetime.utcnow(),
        )
        assert model.ticker == "TCS.NS"
        assert model.data_warnings == []
