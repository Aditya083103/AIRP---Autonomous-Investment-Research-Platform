# backend/services/preference_extractor.py
"""
AIRP -- AIRP Assistant Personalization: Preference Extraction (T-106)

Recognises a user stating their investing risk appetite and/or
preferred sectors in their own words, from plain chat text, so
``backend/routers/chat_stream.py`` can persist it to
``user_preferences`` (T-099's schema, extended by T-106's migration)
the first time it is mentioned -- the concrete mechanism behind this
task's "user_preferences populated after first relevant exchange"
acceptance criterion.

Why deterministic keyword matching, not a second LLM call
------------------------------------------------------------------------
An obvious alternative design is to ask the LLM itself to extract
structured preferences from its own conversation (e.g. a function-call
/ structured-output step alongside the reply). This module deliberately
does NOT do that, for three reasons that matter more here than the
extra flexibility a second model call would buy:

  1. Determinism and testability. Every one of this codebase's "never
     raises" agents (see backend/agents/*.py) treats an LLM call as
     something that can fail, hallucinate, or drift between runs --
     extraction feeding directly into a persisted database column is
     exactly the kind of write where a hallucinated or inconsistent
     result would be worse than a conservative miss. A keyword table is
     something this module's own test suite can assert byte-for-byte,
     forever, with zero network calls.
  2. Cost and latency. A second LLM round-trip on every single chat
     turn (to check "did they just state a preference") would roughly
     double the latency and token cost of every turn, for a feature
     this task's acceptance criteria scope to two enum-like fields with
     a small, enumerable vocabulary -- not open-ended extraction.
  3. Safety surface. This module writes directly to a persisted user
     preference. Keeping the write path deterministic and reviewable in
     a diff (this file) is a meaningfully smaller trust boundary than
     letting free-form model output flow into a database column.

The tradeoff this buys: recall is intentionally conservative. A user
who states their risk appetite in a way not covered by
``_RISK_APPETITE_PHRASES`` below simply is not detected this turn --
they can still be reached (see chat_llm.build_personalization_instruction)
by the assistant asking again in a later turn, since nothing is
persisted until this module actually recognises something. This is
the deliberate choice: silently under-detecting is a purely benign
miss (the assistant asks again later); over-detecting from a vague
heuristic risks writing a confidently-wrong preference into the
database and never asking again (see chat_stream.py's "only write when
still unknown" contract).

Ambiguity handling
------------------------------------------------------------------------
If a message appears to match MORE THAN ONE risk-appetite category
(e.g. it mentions both "conservative" and "aggressive" in the same
message -- plausibly comparing two different things), this module
returns ``risk_appetite=None`` rather than guessing which one the user
meant to self-describe as. The same "ambiguous means unset" rule does
not apply to sectors: a user can genuinely favour more than one sector
at once, so ``preferred_sectors`` collects every matching sector.

Design decisions
------------------------------------------------------------------------
* NO ``from __future__ import annotations`` -- matches every other
  backend/services/ module in the Phase 10 chat feature.
* Plain ASCII section comments (# ---).
* No bare ``type: ignore``.
* Pure functions, no I/O, no database or LLM access -- this module is
  independently testable with zero mocking.
"""

from dataclasses import dataclass, field
import re
from typing import Optional

__all__ = [
    "PreferenceExtractionResult",
    "RISK_APPETITE_VALUES",
    "SECTOR_VALUES",
    "extract_preferences",
]

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Multi-word (or otherwise low-false-positive) phrases mapped to the
#: canonical risk_appetite enum value they indicate. Deliberately avoids
#: bare single words like "risk" or "safe" that appear constantly in
#: ordinary investing conversation without describing the SPEAKER's own
#: appetite (e.g. "what's the risk here?" must not match).
_RISK_APPETITE_PHRASES: dict[str, list[str]] = {
    "conservative": [
        "conservative investor",
        "i'm conservative",
        "i am conservative",
        "risk-averse",
        "risk averse",
        "low risk investor",
        "low-risk investor",
        "prefer low risk",
        "play it safe",
        "capital preservation",
        "safe investor",
        "cautious investor",
    ],
    "moderate": [
        "moderate investor",
        "i'm moderate",
        "i am moderate",
        "moderate risk",
        "balanced investor",
        "medium risk investor",
        "medium-risk investor",
    ],
    "aggressive": [
        "aggressive investor",
        "i'm aggressive",
        "i am aggressive",
        "high risk investor",
        "high-risk investor",
        "risk-taker",
        "risk taker",
        "willing to take risks",
        "growth-oriented investor",
        "bold investor",
        "prefer high risk",
    ],
}

#: Canonical sector name -> phrases that indicate the user favours it.
#: Every phrase is multi-word (or a well-known standalone acronym like
#: "FMCG") specifically to avoid matching common short words ("IT",
#: "auto") inside unrelated sentences -- see the module docstring's
#: "over-detecting" tradeoff discussion.
_SECTOR_PHRASES: dict[str, list[str]] = {
    "IT": [
        "it sector",
        "it stocks",
        "tech sector",
        "tech stocks",
        "technology sector",
        "technology stocks",
        "software sector",
        "information technology",
    ],
    "Banking & Financials": [
        "banking sector",
        "banking stocks",
        "financial sector",
        "financials sector",
        "bank stocks",
        "nbfc",
        "nbfcs",
    ],
    "Pharma & Healthcare": [
        "pharma sector",
        "pharma stocks",
        "pharmaceutical sector",
        "healthcare sector",
        "healthcare stocks",
    ],
    "FMCG": [
        "fmcg",
        "consumer goods sector",
        "fast moving consumer goods",
        "fast-moving consumer goods",
    ],
    "Energy & Oil": [
        "energy sector",
        "energy stocks",
        "oil and gas",
        "oil & gas",
        "power sector",
    ],
    "Auto": [
        "auto sector",
        "auto stocks",
        "automobile sector",
        "automotive sector",
    ],
    "Metals & Mining": [
        "metals sector",
        "mining sector",
        "metal stocks",
        "steel sector",
    ],
    "Infrastructure & Realty": [
        "infrastructure sector",
        "real estate sector",
        "realty sector",
        "construction sector",
    ],
    "Telecom": [
        "telecom sector",
        "telecom stocks",
        "telecommunication sector",
        "telecommunications sector",
    ],
    "Consumer Durables": [
        "consumer durables",
        "consumer electronics sector",
    ],
}

#: Public, stable enumeration of every value this module can ever
#: return -- exposed so callers (and tests) can validate against it
#: without importing the private phrase tables above.
RISK_APPETITE_VALUES: tuple[str, ...] = tuple(_RISK_APPETITE_PHRASES.keys())
SECTOR_VALUES: tuple[str, ...] = tuple(_SECTOR_PHRASES.keys())


def _compile_phrase_pattern(phrase: str) -> "re.Pattern[str]":
    """Word-boundary, case-insensitive regex for one literal phrase."""
    return re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)


#: Precompiled once at import time -- this module is called on every
#: chat turn, so compiling ~40 short regexes per call would be wasted
#: work for something that never changes at runtime.
_RISK_APPETITE_PATTERNS: dict[str, list["re.Pattern[str]"]] = {
    value: [_compile_phrase_pattern(phrase) for phrase in phrases]
    for value, phrases in _RISK_APPETITE_PHRASES.items()
}
_SECTOR_PATTERNS: dict[str, list["re.Pattern[str]"]] = {
    sector: [_compile_phrase_pattern(phrase) for phrase in phrases]
    for sector, phrases in _SECTOR_PHRASES.items()
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreferenceExtractionResult:
    """
    What ``extract_preferences`` recognised in one message.

    ``risk_appetite`` is None when nothing was recognised OR when more
    than one category matched ambiguously (see module docstring).
    ``preferred_sectors`` is always a list (never None), possibly
    empty, in the stable canonical order ``SECTOR_VALUES`` defines --
    not the order phrases happened to appear in the message -- so two
    messages that mention the same sectors in a different order produce
    an identical result.
    """

    risk_appetite: Optional[str] = None
    preferred_sectors: list[str] = field(default_factory=list)

    @property
    def found_anything(self) -> bool:
        """True if this result has a risk appetite and/or at least one sector."""
        return self.risk_appetite is not None or len(self.preferred_sectors) > 0


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _match_risk_appetite(message: str) -> Optional[str]:
    matched = [
        value
        for value, patterns in _RISK_APPETITE_PATTERNS.items()
        if any(pattern.search(message) for pattern in patterns)
    ]
    if len(matched) == 1:
        return matched[0]
    # Zero matches (nothing recognised) or 2+ matches (ambiguous) both
    # resolve to None -- see module docstring's ambiguity-handling note.
    return None


def _match_sectors(message: str) -> list[str]:
    return [
        sector
        for sector in SECTOR_VALUES
        if any(pattern.search(message) for pattern in _SECTOR_PATTERNS[sector])
    ]


def extract_preferences(message: str) -> PreferenceExtractionResult:
    """
    Recognise a risk appetite and/or preferred sectors in one message.

    Pure, synchronous, and side-effect free -- callers are responsible
    for deciding whether/how to persist the result (see
    backend/services/preference_service.py's
    ``apply_extracted_preferences``, which only writes a field that is
    not already known, matching this feature's "ask and remember...
    once" acceptance criterion).

    Args:
        message: The user's chat message text, as sent over
            WS /api/v1/chat/{session_id}/stream.

    Returns:
        A PreferenceExtractionResult. Never raises -- an empty or
        unparseable message simply produces a result with nothing
        found, the same as any other message this module does not
        recognise a preference in.
    """
    if not message or not message.strip():
        return PreferenceExtractionResult()

    return PreferenceExtractionResult(
        risk_appetite=_match_risk_appetite(message),
        preferred_sectors=_match_sectors(message),
    )
