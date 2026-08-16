# backend/tests/unit/test_preference_extractor.py
"""
Unit tests for T-106: backend/services/preference_extractor.py

Pure-function tests -- no I/O, no mocking, no database. Covers:
  * Risk appetite recognition for each of the three canonical values,
    across several phrasings each.
  * Ambiguity handling (2+ risk-appetite categories matching the same
    message resolves to None, not a guess).
  * No false positives from short, common words that happen to overlap
    with a category name in an unrelated sentence.
  * Sector recognition, including multiple sectors in one message, and
    the stable canonical ordering guarantee.
  * Empty/whitespace-only messages.
  * PreferenceExtractionResult.found_anything.

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_preference_extractor.py -v
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from backend.services.preference_extractor import (  # noqa: E402
    RISK_APPETITE_VALUES,
    SECTOR_VALUES,
    PreferenceExtractionResult,
    extract_preferences,
)

# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


class TestVocabulary:
    def test_risk_appetite_values_match_the_orm_enum(self) -> None:
        # Mirrors backend.models.orm.RiskAppetiteEnum's three values --
        # if either side ever drifts, a persisted extraction result
        # would silently fail the database's own CHECK/ENUM constraint
        # at write time instead of being caught here.
        assert set(RISK_APPETITE_VALUES) == {"conservative", "moderate", "aggressive"}

    def test_sector_values_non_empty_and_unique(self) -> None:
        assert len(SECTOR_VALUES) > 0
        assert len(SECTOR_VALUES) == len(set(SECTOR_VALUES))


# ---------------------------------------------------------------------------
# Risk appetite -- conservative
# ---------------------------------------------------------------------------


class TestRiskAppetiteConservative:
    def test_conservative_investor_phrase(self) -> None:
        result = extract_preferences(
            "I'm a conservative investor, please keep that in mind."
        )
        assert result.risk_appetite == "conservative"

    def test_risk_averse_phrase(self) -> None:
        result = extract_preferences("I tend to be pretty risk-averse with my money.")
        assert result.risk_appetite == "conservative"

    def test_risk_averse_no_hyphen(self) -> None:
        result = extract_preferences("I am risk averse overall.")
        assert result.risk_appetite == "conservative"

    def test_capital_preservation_phrase(self) -> None:
        result = extract_preferences("Capital preservation matters most to me.")
        assert result.risk_appetite == "conservative"

    def test_case_insensitive_match(self) -> None:
        result = extract_preferences("I'M A CONSERVATIVE INVESTOR.")
        assert result.risk_appetite == "conservative"


# ---------------------------------------------------------------------------
# Risk appetite -- moderate
# ---------------------------------------------------------------------------


class TestRiskAppetiteModerate:
    def test_moderate_investor_phrase(self) -> None:
        result = extract_preferences("I'd say I'm a moderate investor overall.")
        assert result.risk_appetite == "moderate"

    def test_balanced_investor_phrase(self) -> None:
        result = extract_preferences("Call me a balanced investor.")
        assert result.risk_appetite == "moderate"


# ---------------------------------------------------------------------------
# Risk appetite -- aggressive
# ---------------------------------------------------------------------------


class TestRiskAppetiteAggressive:
    def test_aggressive_investor_phrase(self) -> None:
        result = extract_preferences("I'm an aggressive investor chasing growth.")
        assert result.risk_appetite == "aggressive"

    def test_high_risk_investor_phrase(self) -> None:
        result = extract_preferences(
            "I'm a high-risk investor, don't sugar-coat things."
        )
        assert result.risk_appetite == "aggressive"

    def test_willing_to_take_risks_phrase(self) -> None:
        result = extract_preferences("I'm willing to take risks for bigger returns.")
        assert result.risk_appetite == "aggressive"


# ---------------------------------------------------------------------------
# No match / ambiguity
# ---------------------------------------------------------------------------


class TestRiskAppetiteNoMatchOrAmbiguous:
    def test_unrelated_question_matches_nothing(self) -> None:
        result = extract_preferences("What was the verdict on TCS?")
        assert result.risk_appetite is None

    def test_bare_word_risk_does_not_match(self) -> None:
        # "risk" alone (as in "what's the risk here?") must not be
        # mistaken for a self-description -- see module docstring's
        # "avoids bare single words" design note.
        result = extract_preferences("What's the risk here?")
        assert result.risk_appetite is None

    def test_bare_word_safe_does_not_match(self) -> None:
        result = extract_preferences("Is this stock safe to buy?")
        assert result.risk_appetite is None

    def test_mentioning_two_categories_is_ambiguous(self) -> None:
        result = extract_preferences(
            "I used to be a conservative investor, but now I'm an aggressive investor."
        )
        assert result.risk_appetite is None

    def test_empty_message(self) -> None:
        result = extract_preferences("")
        assert result.risk_appetite is None
        assert result.preferred_sectors == []

    def test_whitespace_only_message(self) -> None:
        result = extract_preferences("   \n\t  ")
        assert result.risk_appetite is None
        assert result.preferred_sectors == []


# ---------------------------------------------------------------------------
# Sectors
# ---------------------------------------------------------------------------


class TestSectors:
    def test_it_sector_phrase(self) -> None:
        result = extract_preferences("I mostly follow the IT sector.")
        assert "IT" in result.preferred_sectors

    def test_banking_sector_phrase(self) -> None:
        result = extract_preferences("I like the banking sector a lot.")
        assert "Banking & Financials" in result.preferred_sectors

    def test_fmcg_standalone_acronym(self) -> None:
        result = extract_preferences("FMCG stocks are my thing.")
        assert "FMCG" in result.preferred_sectors

    def test_multiple_sectors_in_one_message(self) -> None:
        result = extract_preferences(
            "I'm mostly interested in the IT sector and pharma stocks."
        )
        assert "IT" in result.preferred_sectors
        assert "Pharma & Healthcare" in result.preferred_sectors
        assert len(result.preferred_sectors) == 2

    def test_stable_canonical_order_regardless_of_mention_order(self) -> None:
        mentioned_first = extract_preferences(
            "I like pharma stocks and the IT sector."
        ).preferred_sectors
        mentioned_second = extract_preferences(
            "I like the IT sector and pharma stocks."
        ).preferred_sectors
        assert mentioned_first == mentioned_second

    def test_no_sector_mentioned_yields_empty_list(self) -> None:
        result = extract_preferences("What was the verdict on TCS?")
        assert result.preferred_sectors == []

    def test_short_word_auto_requires_multiword_phrase(self) -> None:
        # Bare "auto" (e.g. "auto-generated") must not match the Auto
        # sector -- only a genuine sector phrase should.
        result = extract_preferences("This report was auto-generated.")
        assert "Auto" not in result.preferred_sectors

    def test_auto_sector_phrase_does_match(self) -> None:
        result = extract_preferences("I want more exposure to the auto sector.")
        assert "Auto" in result.preferred_sectors


# ---------------------------------------------------------------------------
# Combined risk appetite + sectors in one message
# ---------------------------------------------------------------------------


class TestCombinedExtraction:
    def test_risk_appetite_and_sectors_together(self) -> None:
        result = extract_preferences(
            "I'm a conservative investor and I mostly follow FMCG and banking stocks."
        )
        assert result.risk_appetite == "conservative"
        assert "FMCG" in result.preferred_sectors
        assert "Banking & Financials" in result.preferred_sectors


# ---------------------------------------------------------------------------
# PreferenceExtractionResult
# ---------------------------------------------------------------------------


class TestPreferenceExtractionResult:
    def test_found_anything_false_when_empty(self) -> None:
        result = PreferenceExtractionResult()
        assert result.found_anything is False

    def test_found_anything_true_with_risk_appetite_only(self) -> None:
        result = PreferenceExtractionResult(risk_appetite="moderate")
        assert result.found_anything is True

    def test_found_anything_true_with_sectors_only(self) -> None:
        result = PreferenceExtractionResult(preferred_sectors=["IT"])
        assert result.found_anything is True

    def test_default_preferred_sectors_is_a_fresh_list_each_time(self) -> None:
        # Guards against the classic Python mutable-default-argument
        # bug -- two independently constructed results must not share
        # the same underlying list object.
        first = PreferenceExtractionResult()
        second = PreferenceExtractionResult()
        first.preferred_sectors.append("IT")
        assert second.preferred_sectors == []

    def test_extract_preferences_never_raises_on_odd_input(self) -> None:
        odd_messages = [
            "",
            "   ",
            "a" * 5000,
            "\x00\x01",
            "\U0001f600\U0001f600\U0001f600",
        ]
        for message in odd_messages:
            result = extract_preferences(message)
            assert isinstance(result, PreferenceExtractionResult)
