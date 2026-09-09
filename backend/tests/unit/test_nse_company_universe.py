# backend/tests/unit/test_nse_company_universe.py
"""
Unit tests for backend/data/nse_company_universe.py (B5).

Guards the two properties everything downstream (company_search.py,
the /api/v1/companies/search endpoint, and ultimately
CompanyAutocomplete's dropdown) silently depends on: every ticker is
unique (a duplicate would make search results non-deterministic and
would double-count in total_count) and every entry is well-formed
(non-empty name, a bare-symbol-plus-.NS ticker, a known exchange code).

ENVIRONMENT must be set to 'test' before any backend import (project
convention, even though this module has no FastAPI/DB dependency of
its own).
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from backend.data.nse_company_universe import (  # noqa: E402
    _RAW_ENTRIES,
    NSE_COMPANY_UNIVERSE,
    CompanyEntry,
    _deduplicate_by_ticker,
)


class TestRawEntries:
    def test_has_no_duplicate_tickers(self) -> None:
        """The dedup safety net in NSE_COMPANY_UNIVERSE's own
        construction exists for a FUTURE accidental duplicate --
        _RAW_ENTRIES itself must have none today."""
        tickers = [ticker for _name, ticker in _RAW_ENTRIES]
        assert len(tickers) == len(set(tickers))

    def test_has_no_duplicate_names(self) -> None:
        names = [name for name, _ticker in _RAW_ENTRIES]
        assert len(names) == len(set(names))

    def test_is_meaningfully_larger_than_the_old_top_50_list(self) -> None:
        """The whole point of B5: the universe must be well beyond the
        51-entry frontend/src/data/nseTop50.ts it replaces as the
        search backend."""
        assert len(_RAW_ENTRIES) >= 200


class TestDeduplicateByTicker:
    def test_keeps_the_first_occurrence_of_a_duplicate_ticker(self) -> None:
        entries = [("First Co", "DUP"), ("Second Co", "DUP")]
        result = _deduplicate_by_ticker(entries)
        assert result == [("First Co", "DUP")]

    def test_preserves_order_and_leaves_non_duplicates_untouched(self) -> None:
        entries = [("A", "AAA"), ("B", "BBB"), ("C", "CCC")]
        assert _deduplicate_by_ticker(entries) == entries

    def test_empty_input_returns_empty_output(self) -> None:
        assert _deduplicate_by_ticker([]) == []


class TestNseCompanyUniverse:
    def test_every_entry_is_a_company_entry(self) -> None:
        assert all(isinstance(entry, CompanyEntry) for entry in NSE_COMPANY_UNIVERSE)

    def test_every_ticker_is_unique(self) -> None:
        tickers = [entry.ticker for entry in NSE_COMPANY_UNIVERSE]
        assert len(tickers) == len(set(tickers))

    def test_every_ticker_carries_the_ns_suffix(self) -> None:
        assert all(entry.ticker.endswith(".NS") for entry in NSE_COMPANY_UNIVERSE)

    def test_every_entry_is_exchange_nse(self) -> None:
        assert all(entry.exchange == "NSE" for entry in NSE_COMPANY_UNIVERSE)

    def test_no_entry_has_a_blank_name_or_ticker(self) -> None:
        assert all(
            entry.name.strip() and entry.ticker.strip()
            for entry in NSE_COMPANY_UNIVERSE
        )

    def test_well_known_large_caps_are_present(self) -> None:
        """Spot-check a handful of names/tickers this codebase already
        references elsewhere (nseTop50.ts, resolve_company's override
        table) to guard against a typo silently dropping a well-known
        company from the universe."""
        tickers = {entry.ticker for entry in NSE_COMPANY_UNIVERSE}
        for expected in (
            "TCS.NS",
            "INFY.NS",
            "RELIANCE.NS",
            "HDFCBANK.NS",
            "ICICIBANK.NS",
            "SBIN.NS",
            "ITC.NS",
        ):
            assert expected in tickers

    def test_the_original_top_50_tickers_are_a_subset(self) -> None:
        """B5's dataset supersedes -- never regresses -- nseTop50.ts's
        own coverage: every ticker that list already carried must still
        resolve here (spot-checked via a representative sample rather
        than importing the frontend file, which this backend test
        cannot do)."""
        tickers = {entry.ticker for entry in NSE_COMPANY_UNIVERSE}
        sample = {
            "BAJFINANCE.NS",
            "MARUTI.NS",
            "ASIANPAINT.NS",
            "TITAN.NS",
            "ADANIENT.NS",
            "TATASTEEL.NS",
            "HEROMOTOCO.NS",
        }
        assert sample.issubset(tickers)
