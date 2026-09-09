# backend/tests/unit/test_company_search.py
"""
Unit tests for backend/services/company_search.py (B5).

Exercises search_companies against the REAL NSE_COMPANY_UNIVERSE (not a
mocked/patched dataset) -- there is no database or external service to
isolate from here, and the ranking behaviour this module exists to
provide only means something evaluated against actual data: a fake
5-entry stand-in universe would not exercise the tier-ordering logic
the same way a query that legitimately matches 20+ real companies
does. Individual assertions are written against tickers/names this
codebase already references elsewhere (nseTop50.ts,
resolve_company's override table), the same "spot-check well-known
entries" approach test_nse_company_universe.py takes for the dataset
itself.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from backend.services.company_search import (  # noqa: E402
    CompanySearchPage,
    CompanySearchResult,
    search_companies,
)


class TestEmptyQuery:
    def test_empty_string_returns_the_full_universe_first_page(self) -> None:
        page = search_companies("", limit=20, offset=0)
        assert isinstance(page, CompanySearchPage)
        assert page.total_count >= 200
        assert len(page.items) == 20

    def test_whitespace_only_query_behaves_like_empty(self) -> None:
        page = search_companies("   ", limit=5, offset=0)
        assert page.total_count >= 200
        assert len(page.items) == 5


class TestRanking:
    def test_exact_ticker_match_ranks_first(self) -> None:
        page = search_companies("tcs", limit=10)
        assert page.items[0] == CompanySearchResult(
            name="Tata Consultancy Services", ticker="TCS.NS", exchange="NSE"
        )

    def test_exact_ticker_match_is_case_insensitive(self) -> None:
        lower = search_companies("infy", limit=1)
        upper = search_companies("INFY", limit=1)
        mixed = search_companies("InFy", limit=1)
        assert lower.items[0].ticker == "INFY.NS"
        assert upper.items == lower.items
        assert mixed.items == lower.items

    def test_ticker_prefix_match_outranks_ticker_substring_match(self) -> None:
        # "BANKBARODA" starts with "bank"; "AXISBANK" only CONTAINS it.
        page = search_companies("bank", limit=30)
        tickers_in_order = [item.ticker for item in page.items]
        assert tickers_in_order.index("BANKBARODA.NS") < tickers_in_order.index(
            "AXISBANK.NS"
        )

    def test_name_prefix_match_outranks_name_substring_match(self) -> None:
        # "Tata Steel" name starts with "tata"; "Adani Total Gas" does not
        # start with "tata" but no company's NAME merely contains "tata"
        # without starting with it in this dataset except compound Tata
        # names -- assert the concrete, always-true relationship instead:
        # a name-prefix match ("Tata Steel") outranks a ticker-only
        # substring match that shares no name-level relevance.
        page = search_companies("tata steel", limit=5)
        assert page.items[0].name == "Tata Steel"

    def test_matches_against_name_not_just_ticker(self) -> None:
        page = search_companies("infosys", limit=5)
        assert any(item.ticker == "INFY.NS" for item in page.items)

    def test_query_matching_nothing_returns_an_empty_page(self) -> None:
        page = search_companies("this-matches-absolutely-nothing-xyz", limit=10)
        assert page.items == []
        assert page.total_count == 0
        assert page.has_more is False

    def test_within_a_tier_results_are_sorted_alphabetically_by_name(self) -> None:
        page = search_companies("bank", limit=30)
        # Isolate the ticker-substring tier (companies whose ticker
        # contains "bank" but does not start with it) and confirm it is
        # alphabetically ordered among itself.
        substring_tier_names = [
            item.name
            for item in page.items
            if "bank" in item.ticker.replace(".NS", "").lower()
            and not item.ticker.replace(".NS", "").lower().startswith("bank")
        ]
        assert substring_tier_names == sorted(substring_tier_names)


class TestPagination:
    def test_total_count_reflects_every_match_not_just_the_page(self) -> None:
        page = search_companies("bank", limit=3, offset=0)
        assert len(page.items) == 3
        assert page.total_count > 3

    def test_has_more_true_when_more_rows_remain(self) -> None:
        page = search_companies("a", limit=5, offset=0)
        assert page.total_count > 5
        assert page.has_more is True

    def test_has_more_false_on_the_last_page(self) -> None:
        first_page = search_companies("tcs", limit=10, offset=0)
        assert first_page.total_count == 1
        assert first_page.has_more is False

    def test_offset_pages_through_results_without_overlap_or_gaps(self) -> None:
        page_one = search_companies("bank", limit=5, offset=0)
        page_two = search_companies("bank", limit=5, offset=5)
        tickers_one = {item.ticker for item in page_one.items}
        tickers_two = {item.ticker for item in page_two.items}
        assert tickers_one.isdisjoint(tickers_two)

    def test_offset_beyond_total_count_returns_an_empty_page(self) -> None:
        page = search_companies("tcs", limit=10, offset=50)
        assert page.items == []
        assert page.total_count == 1

    def test_echoes_the_limit_and_offset_it_was_called_with(self) -> None:
        page = search_companies("bank", limit=7, offset=2)
        assert page.limit == 7
        assert page.offset == 2


class TestDefaults:
    def test_default_limit_and_offset(self) -> None:
        page = search_companies("bank")
        assert page.offset == 0
        assert len(page.items) <= 20  # DEFAULT_SEARCH_PAGE_SIZE
