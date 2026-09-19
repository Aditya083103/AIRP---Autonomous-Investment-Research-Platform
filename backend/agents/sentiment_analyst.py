# backend/agents/sentiment_analyst.py
"""
AIRP -- News Sentiment Agent (T-024)

Persona: sharp financial journalist who has covered Indian equities for 15
years.  Reads market news the way a seasoned reporter does -- looking for the
story *behind* the story, spotting management credibility gaps, regulatory
smoke signals, and momentum shifts before they become consensus.

Mandate
-------
Analyse the last 30 days of news for a given company using two data sources:
  * fetch_news              -- NewsAPI articles (titles + descriptions, 30 days)
  * semantic_search         -- ChromaDB similarity search over previously
                               ingested news embeddings for richer context

Score the aggregate sentiment (-1.0 to +1.0) and surface specific red flags
such as regulatory notices, management misconduct, fraud rumours, and
earnings restatements.

Output: SentimentAnalysis (defined in output_models.py)
  * sentiment_score      -- float in [-1.0, 1.0]
  * sentiment_label      -- 'very_positive' | 'positive' | 'neutral' |
                            'negative' | 'very_negative'
  * articles_analysed    -- int
  * positive/negative/neutral_articles -- int counts
  * red_flags            -- list[str]  (empty when clean)
  * red_flag_count       -- int
  * top_positive_headlines -- list[str] (up to 3)
  * top_negative_headlines -- list[str] (up to 3)
  * dominant_topics      -- list[str] (3-5 themes)
  * summary              -- str (2-3 sentences, PM-ready)

Public interface
----------------
  run_sentiment_analysis(state)          -> dict   LangGraph node
  _run_sentiment_analysis_core(...)      -> SentimentAnalysis  testable core
  _score_article(title, description)     -> float  per-article scorer, pure
  _label_from_score(score)               -> str    band mapping, pure
  _detect_red_flags(texts)               -> list[str]  keyword scanner, pure
  _aggregate_scores(scores)              -> float  mean with clipping, pure
  _build_sentiment_prompt(...)           -> str    prompt builder, pure

Design decisions
----------------
* NO ``from __future__ import annotations`` -- breaks Pydantic v2.
* Per-article scoring uses a keyword-weighted approach (pure Python, no NLTK,
  no TextBlob) so CI has zero new dependencies.  The LLM synthesises the
  narrative -- it does NOT score individual articles.
* Red flag detection is keyword-based and deterministic (never relies on the
  LLM to identify SEBI notices, fraud words, etc.) so it is fully testable.
* ChromaDB semantic search is attempted but failures are non-fatal -- the
  agent degrades gracefully to NewsAPI data alone.
* Error convention: never raises.  On any failure SentimentAnalysis.error
  is set.

Usage in LangGraph (Phase 3)
----------------------------
    from backend.agents.sentiment_analyst import run_sentiment_analysis
    builder.add_node("news_sentiment", run_sentiment_analysis)
    # Reads:  state["job_id"], state["company_name"], state["ticker"]
    # Writes: state["sentiment"]  (dict from SentimentAnalysis.model_dump())
"""

import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import SentimentAnalysis
from backend.agents.tracing import traced_agent
from backend.config import settings
from backend.db.chroma_client import (
    COLLECTION_NEWS,
    build_chroma_client,
    ingest_news_articles,
    semantic_search,
)
from backend.tools.news import fetch_news

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sentiment score bands -> label mapping (upper-bound exclusive except last)
SCORE_BANDS: list[tuple[float, str]] = [
    (0.3, "very_positive"),
    (0.1, "positive"),
    (-0.1, "neutral"),
    (-0.3, "negative"),
]
# anything <= -0.3 falls through to "very_negative"

# Positive signal keywords (each hit adds +KEYWORD_WEIGHT to raw score)
#
# T-095 audit fix: "order" and "raised" were removed as bare keywords --
# "order" collides with "regulatory order" / "court order" (bearish, not
# bullish), and "raised" collides with "raised concerns" (bearish). Both
# are replaced with the specific multi-word phrases that actually carry
# the intended bullish meaning.
POSITIVE_KEYWORDS: list[str] = [
    "record",
    "profit",
    "growth",
    "beat",
    "wins",
    "deal",
    "upgrade",
    "outperform",
    "strong",
    "order win",
    "new order",
    "order book",
    "bags order",
    "guidance raised",
    "outlook raised",
    "stake raised",
    "capital raised",
    "buyback",
    "dividend",
    "expansion",
    "milestone",
    "partnership",
    "acquisition",
    "inflow",
    "surge",
    "rally",
    "bullish",
    "robust",
    "resilient",
    "recovery",
    "accelerat",
]

# Negative signal keywords
#
# T-095 audit fix: the previous list had several bare, extremely common
# words that fire on routine, often-neutral-or-positive Indian financial
# news rather than genuine bad news -- "sebi" / "nse" / "bse" are simply
# the names of the regulator and the two stock exchanges, appearing in
# nearly every routine disclosure headline ("XYZ Ltd informs BSE, NSE of
# board meeting"); "debt", "risk", "notice", "concern", "warning", and
# "accounting" are standard vocabulary in neutral or even positive
# financial writing ("debt-free", "risk-adjusted returns are strong",
# "no material regulatory concerns"); "charged" false-positives inside
# "discharged" (e.g. "discharged its debt obligations" -- good news);
# "insider" false-positives on "industry insider" and on insider BUYING,
# which is a bullish signal, not bearish. Every one of these is now
# either removed or replaced with the specific multi-word phrase that
# actually carries the negative meaning.
NEGATIVE_KEYWORDS: list[str] = [
    "loss",
    "fraud",
    "scam",
    "investigation",
    "probe",
    "lawsuit",
    "penalty",
    "miss",
    "downgrade",
    "underperform",
    "weak",
    "decline",
    "fall",
    "slump",
    "raises concern",
    "flags concern",
    "growing concern",
    "profit warning",
    "issues warning",
    "debt burden",
    "mounting debt",
    "debt distress",
    "unsustainable debt",
    "default",
    "layoff",
    "restatement",
    "accounting irregularities",
    "accounting fraud",
    # T-095 follow-up: the six "sebi <action>" phrases that used to live
    # here were exact-adjacent literals ("sebi probe", "sebi notice", ...)
    # -- too rigid for real headlines ("SEBI has issued a notice to TCS"
    # doesn't contain the literal substring "sebi notice"). Replaced with
    # the _sebi_action_present() proximity check below, applied in
    # _score_article.
    "regulatory notice",
    "show cause notice",
    "resign",
    "fired",
    "arrested",
    "whistleblower",
    "manipulation",
    "insider trading",
]

# Red flag trigger phrases (any match surfaces a flag)
#
# T-095 audit fix: bare "sebi" flagged every routine regulator mention as
# a red flag (SEBI approving a rights issue is not a red flag). Bare
# "corporate governance" flagged the phrase even inside "strong corporate
# governance practices" -- the opposite of a red flag. Bare "resign" and
# "charged" are covered more precisely elsewhere below ("ceo quit" /
# "md resign" / "cfo resign", "arrested") and duplicated the same
# false-positive risk described above, so they are removed here too.
RED_FLAG_PHRASES: list[str] = [
    # T-095 follow-up: the six "sebi <action>" phrases and the three
    # "<role> <resign/quit>" phrases previously here were exact-adjacent
    # literals, too rigid for real headlines ("SEBI has issued a notice",
    # "TCS MD to resign"). Replaced with the _sebi_action_present() /
    # _resignation_present() proximity checks in _detect_red_flags below.
    "fraud",
    "scam",
    "investigation",
    "probe",
    "insider trading",
    "accounting restatement",
    "restatement",
    "whistleblower",
    "arrested",
    "default",
    "manipulation",
    "regulatory action",
    "nse notice",
    "bse notice",
    "ed raid",
    "cbi",
    "enforcement directorate",
    "money laundering",
    "bribery",
    "corporate governance concerns",
    "corporate governance lapse",
    "poor corporate governance",
    "promoter pledge",
    "pledging",
    "class action",
]

# Per-keyword score contribution (clamped to [-1, 1] at article level)
KEYWORD_WEIGHT: float = 0.15

# T-095 audit fix: keywords deliberately used as a stem (matched with any
# trailing word characters, not a strict whole-word match) -- e.g.
# "accelerat" is meant to match "accelerating" / "accelerated" /
# "acceleration". Every other keyword gets a bounded inflection match
# (see _build_inflection_group) so a short keyword can never match as a
# mere substring of an unrelated, longer word.
_STEM_KEYWORDS: frozenset[str] = frozenset({"accelerat"})

_WORD_BOUNDARY_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _build_inflection_group(keyword: str) -> str:
    """
    Build the regex alternation matching ``keyword``'s regular English
    inflections, still anchored so it can never match as a substring of
    an unrelated, longer word.

    T-095 follow-up fix: the original word-boundary fix (`\\bkeyword\\b`,
    no suffix at all) was too strict in the other direction -- it also
    stopped matching completely ordinary inflected forms of the same
    word, which is how these keywords actually show up in real headlines:
    "miss" no longer matched "misses" ("revenue misses expectations"),
    "surge" no longer matched "surged"/"surging". This is what caused
    CI's mixed_profit_vs_revenue_miss eval case to regress from a
    genuine 0.0 (profit/strong exactly offsetting miss/weak) to +0.15,
    since "miss" stopped matching while every other keyword in that
    headline still did.

    Two cases:
      - Regular keyword (doesn't end in "e"): allow an appended
        -s/-es/-ed/-ing, e.g. "loss" -> "losses", "downgrade" -- wait,
        see the silent-e case below for that one; "probe" is likewise
        silent-e, not this branch.
      - Keyword ends in a silent "e" (e.g. "surge", "probe",
        "downgrade", "decline", or a phrase ending in one like
        "promoter pledge"): English drops the "e" before "-ing" but
        keeps it before "-s"/"-d" ("surges"/"surged"/"surging", not
        "surgeed"/"surgeing"). Applies to the phrase's last word for a
        multi-word ``keyword``, since that's the only word that ever
        inflects in these collocations.

    Neither branch reopens the original bug: the alternation is still
    fully anchored by the \\b...\\b the caller wraps around this, so
    "ban" (if it were still a bare keyword, which it no longer is) would
    still not match inside "banking" -- "king" isn't one of the allowed
    suffixes.
    """
    escaped = re.escape(keyword)
    if keyword in _STEM_KEYWORDS:
        return escaped + r"\w*"
    if keyword.endswith("e") and len(keyword) > 1:
        stem_no_e = re.escape(keyword[:-1])
        return r"(?:" + escaped + r"(?:s|d)?|" + stem_no_e + r"ing)"
    return escaped + r"(?:s|es|ed|ing)?"


def _keyword_present(keyword: str, text: str) -> bool:
    """
    True if ``keyword`` (or a regular English inflection of it) occurs
    in ``text`` as a whole word/phrase, not merely as a substring of a
    longer, unrelated word.

    T-095 audit fix: the previous implementation used plain Python `in`
    containment, which matches "ban" inside "Bangalore" or "banking", and
    "charged" inside "discharged" -- both false positives that previously
    counted as a real sentiment/red-flag signal. This still matches
    multi-word phrases (e.g. "sebi probe") as a unit, since regex `\\b`
    anchors on the phrase's own first/last characters. See
    _build_inflection_group's docstring for the T-095 follow-up fix that
    restored matching for ordinary inflected forms (misses, surged,
    probing, ...) without reopening the original substring bug.
    """
    pattern = _WORD_BOUNDARY_PATTERN_CACHE.get(keyword)
    if pattern is None:
        pattern = re.compile(r"\b" + _build_inflection_group(keyword) + r"\b")
        _WORD_BOUNDARY_PATTERN_CACHE[keyword] = pattern
    return pattern.search(text) is not None


# ---------------------------------------------------------------------------
# Proximity matching (T-095 follow-up)
# ---------------------------------------------------------------------------
#
# Exact adjacent multi-word phrases (e.g. "sebi notice") are too rigid for
# real headlines, which rarely place the two words directly next to each
# other ("SEBI has issued a notice to TCS", "TCS MD to resign amid board
# dispute"). A proximity match -- an anchor word (e.g. "sebi") within a
# small window of a trigger word (e.g. "notice"), both whole words -- keeps
# the original word-boundary fix's guarantee (a bare anchor with no nearby
# trigger still never fires, so routine mentions like "as per SEBI
# regulations" stay silent) while catching natural phrasing of a genuine
# event.
_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


def _anchor_near_trigger(
    anchors: frozenset[str], triggers: frozenset[str], text: str, window: int
) -> bool:
    """True if any ``anchors`` word is within ``window`` words of any
    ``triggers`` word in ``text`` (whole-word matches only)."""
    tokens = _tokenize(text)
    anchor_idxs = [i for i, t in enumerate(tokens) if t in anchors]
    if not anchor_idxs:
        return False
    trigger_idxs = [i for i, t in enumerate(tokens) if t in triggers]
    if not trigger_idxs:
        return False
    return any(abs(a - t) <= window for a in anchor_idxs for t in trigger_idxs)


_SEBI_ANCHORS: frozenset[str] = frozenset({"sebi"})
_SEBI_TRIGGERS: frozenset[str] = frozenset(
    {
        "probe",
        "notice",
        "penalty",
        "fine",
        "fined",
        "ban",
        "banned",
        "action",
        "order",
        "investigating",
        "investigation",
        "debar",
        "debarred",
    }
)
_SEBI_PROXIMITY_WINDOW = 8

_RESIGNATION_ANCHORS: frozenset[str] = frozenset(
    {"ceo", "md", "cfo", "director", "chairman", "chairperson"}
)
_RESIGNATION_TRIGGERS: frozenset[str] = frozenset(
    {"resign", "resigns", "resigned", "resignation", "quit", "quits", "quitting"}
)
_RESIGNATION_PROXIMITY_WINDOW = 4


def _sebi_action_present(text: str) -> bool:
    """True if 'sebi' appears near a regulatory-action trigger word."""
    return _anchor_near_trigger(
        _SEBI_ANCHORS, _SEBI_TRIGGERS, text, _SEBI_PROXIMITY_WINDOW
    )


def _resignation_present(text: str) -> bool:
    """True if a leadership role appears near a resignation trigger word."""
    return _anchor_near_trigger(
        _RESIGNATION_ANCHORS,
        _RESIGNATION_TRIGGERS,
        text,
        _RESIGNATION_PROXIMITY_WINDOW,
    )


# ChromaDB semantic search: number of results to retrieve
CHROMA_N_RESULTS: int = 5

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a sharp financial journalist who has covered Indian equities for \
15 years. You read market news the way a seasoned reporter does -- looking \
for the story behind the story, spotting management credibility gaps, \
regulatory smoke signals, and momentum shifts before they become consensus.

Your job is to synthesise pre-scored news data into a concise, \
investment-committee-ready sentiment assessment.

RULES:
1. Be specific -- reference actual headlines or topics from the data.
2. Red flags must reference the specific article or topic that triggered them.
3. The summary must be 2-3 sentences maximum, written for a Portfolio Manager.
4. Dominant topics should be concrete (e.g. "AI cloud deal wins", "margin \
pressure") not generic ("business news").
5. Do NOT use markdown, bullet symbols, or headers in your output.
6. Respond ONLY with valid JSON matching the exact schema below.
7. Do not invent news. Use only the headlines and snippets provided.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "top_positive_headlines": ["<headline>", ...],
  "top_negative_headlines": ["<headline>", ...],
  "dominant_topics": ["<topic>", ...],
  "red_flags": ["<specific flag description>", ...],
  "summary": "<2-3 sentence sentiment summary>"
}

Provide up to 3 top_positive_headlines and up to 3 top_negative_headlines. \
Provide 3-5 dominant_topics. Provide red_flags only when genuinely present -- \
an empty list is correct when there are no flags.\
"""

# ---------------------------------------------------------------------------
# Pure helper functions (no I/O, fully unit-testable)
# ---------------------------------------------------------------------------


def _score_article(title: str, description: str) -> float:
    """
    Score a single news article in the range [-1.0, +1.0].

    Uses a keyword-weighted approach: each positive keyword match adds
    KEYWORD_WEIGHT to the raw score and each negative keyword match
    subtracts KEYWORD_WEIGHT.  The result is clamped to [-1.0, +1.0].

    This is deliberately simple and dependency-free -- no NLTK, no TextBlob,
    no external API calls.  The LLM synthesises the narrative; this function
    produces the numerical inputs.

    Args:
        title:       Article headline (case-insensitive matching).
        description: Article snippet or description (case-insensitive).

    Returns:
        Float in [-1.0, 1.0].  0.0 for articles with no keyword matches.
    """
    text = (title + " " + description).lower()
    raw: float = 0.0

    for kw in POSITIVE_KEYWORDS:
        if _keyword_present(kw, text):
            raw += KEYWORD_WEIGHT

    for kw in NEGATIVE_KEYWORDS:
        if _keyword_present(kw, text):
            raw -= KEYWORD_WEIGHT

    if _sebi_action_present(text):
        raw -= KEYWORD_WEIGHT

    return max(-1.0, min(1.0, round(raw, 4)))


def _label_from_score(score: float) -> str:
    """
    Map a sentiment score to a human-readable label.

    Bands (inclusive upper bound):
      score > 0.3   -> 'very_positive'
      0.1 < score <= 0.3   -> 'positive'
      -0.1 <= score <= 0.1 -> 'neutral'
      -0.3 <= score < -0.1 -> 'negative'
      score < -0.3  -> 'very_negative'

    Args:
        score: Aggregate sentiment score in [-1.0, 1.0].

    Returns:
        One of: 'very_positive', 'positive', 'neutral', 'negative',
        'very_negative'.
    """
    if score > 0.3:
        return "very_positive"
    if score > 0.1:
        return "positive"
    if score >= -0.1:
        return "neutral"
    if score >= -0.3:
        return "negative"
    return "very_negative"


def _detect_red_flags(texts: list[str]) -> list[str]:
    """
    Scan article texts for red flag trigger phrases.

    Each article text is checked against RED_FLAG_PHRASES (case-insensitive).
    When a phrase is found, a formatted flag string is appended to the results.
    Duplicates are de-duplicated (same phrase found in multiple articles
    produces a single flag entry).

    Args:
        texts: List of strings (each string is title + description of one
               article).

    Returns:
        Deduplicated list of flag strings, each formatted as:
        "<PHRASE> mentioned in news coverage".
    """
    found: set[str] = set()
    for text in texts:
        lower = text.lower()
        if _sebi_action_present(lower):
            found.add("sebi regulatory action")
        if _resignation_present(lower):
            found.add("executive resignation")
        for phrase in RED_FLAG_PHRASES:
            if phrase not in found and _keyword_present(phrase, lower):
                found.add(phrase)
    return [f"{p} mentioned in news coverage" for p in sorted(found)]


def _aggregate_scores(scores: list[float]) -> float:
    """
    Compute the aggregate sentiment score from a list of article scores.

    Returns the arithmetic mean, clamped to [-1.0, 1.0] and rounded to
    4 decimal places.  Returns 0.0 when the list is empty (no articles =
    neutral sentiment by convention).

    Args:
        scores: List of per-article scores from _score_article().

    Returns:
        Float in [-1.0, 1.0].
    """
    if not scores:
        return 0.0
    mean = sum(scores) / len(scores)
    return max(-1.0, min(1.0, round(mean, 4)))


def _build_sentiment_prompt(
    company_name: str,
    ticker: str,
    articles: list[dict[str, Any]],
    chroma_snippets: list[dict[str, Any]],
    aggregate_score: float,
    label: str,
    article_stats: dict[str, int],
) -> str:
    """
    Build the user-turn prompt for the LLM synthesis call.

    The LLM receives the pre-scored aggregate, article stats, and a
    formatted list of headlines and snippets.  It does NOT recompute
    scores -- it only synthesises narrative, selects top headlines,
    identifies dominant topics, and validates/augments red flags.

    Args:
        company_name:    Human-readable company name.
        ticker:          Yahoo Finance ticker.
        articles:        List of article dicts from fetch_news tool.
        chroma_snippets: Results from semantic_search (may be empty).
        aggregate_score: Pre-computed aggregate sentiment score.
        label:           Pre-computed sentiment label.
        article_stats:   Dict with keys 'total', 'positive', 'negative',
                         'neutral'.

    Returns:
        Formatted prompt string.
    """
    lines: list[str] = [
        f"Analyse the news sentiment for {company_name} ({ticker}).",
        "",
        "PRE-COMPUTED SENTIMENT METRICS:",
        f"  Aggregate score   : {aggregate_score:+.4f} (range -1 to +1)",
        f"  Sentiment label   : {label}",
        f"  Articles analysed : {article_stats.get('total', 0)}",
        f"  Positive articles : {article_stats.get('positive', 0)}",
        f"  Negative articles : {article_stats.get('negative', 0)}",
        f"  Neutral articles  : {article_stats.get('neutral', 0)}",
        "",
        "NEWS ARTICLES (last 30 days):",
    ]

    for i, art in enumerate(articles[:20], start=1):
        title = art.get("title") or art.get("headline") or "No title"
        description = art.get("description") or art.get("snippet") or ""
        published = art.get("published_at") or art.get("publishedAt") or ""
        score = _score_article(title, description)
        score_str = f"({score:+.2f})"
        lines.append(f"  [{i:02d}] {score_str} {title[:120]}")
        if description:
            lines.append(f"       {description[:120]}")
        if published:
            lines.append(f"       Published: {published[:10]}")

    if chroma_snippets:
        lines.extend(
            [
                "",
                "ADDITIONAL CONTEXT (ChromaDB semantic search):",
            ]
        )
        for snippet in chroma_snippets[:CHROMA_N_RESULTS]:
            doc = snippet.get("document") or ""
            dist = snippet.get("distance")
            dist_str = f"(similarity distance: {dist:.3f})" if dist is not None else ""
            lines.append(f"  {dist_str} {doc[:200]}")

    lines.extend(
        [
            "",
            "Using only the data above, provide the JSON output as specified "
            "in the system prompt. Be specific about which headlines or topics "
            "drive the sentiment and any red flags.",
        ]
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core agent logic (separated from LangGraph node for testability)
# ---------------------------------------------------------------------------


def _run_sentiment_analysis_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
) -> SentimentAnalysis:
    """
    Core agent logic -- fetch news, score articles, call LLM for synthesis.

    Never raises -- on any failure returns SentimentAnalysis with error set.

    Args:
        analysis_id:  UUID of the parent Analysis job (from InvestmentState).
        company_name: Human-readable company name.
        ticker:       Yahoo Finance ticker (e.g. 'TCS.NS').

    Returns:
        SentimentAnalysis Pydantic model (frozen, serialisable).
    """
    # --- Step 1: Fetch news articles via fetch_news tool
    logger.info(
        "Sentiment agent: fetching news company=%s analysis=%s",
        company_name,
        analysis_id,
    )
    try:
        news_result = fetch_news.invoke(
            {
                "company_name": company_name,
                "ticker": ticker,
                "max_articles": 20,
            }
        )
    except Exception as exc:
        logger.exception("fetch_news failed for %s", company_name)
        return SentimentAnalysis(
            agent_name="news_sentiment",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            sentiment_score=0.0,
            sentiment_label="neutral",
            articles_analysed=0,
            positive_articles=0,
            negative_articles=0,
            neutral_articles=0,
            error=f"fetch_news failed: {exc}",
        )

    if "error" in news_result:
        return SentimentAnalysis(
            agent_name="news_sentiment",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            sentiment_score=0.0,
            sentiment_label="neutral",
            articles_analysed=0,
            positive_articles=0,
            negative_articles=0,
            neutral_articles=0,
            error=news_result.get("message", "news data unavailable"),
        )

    articles: list[dict[str, Any]] = news_result.get("articles", [])

    # --- Step 1.5: Ingest fetched articles into ChromaDB (non-fatal)
    #
    # Without this, the airp_news collection is permanently empty --
    # `fetch_news` above only returns articles in-memory for this run's
    # own scoring; nothing was ever writing them into ChromaDB, so the
    # semantic_search() call in Step 5 below always ran against an empty
    # collection ("query_documents: collection 'airp_news' is empty."
    # logged on every single analysis, regardless of ticker). Ingesting
    # here means each analysis both queries *and* grows the corpus, so
    # semantic_search has something to find on this and future runs.
    if articles and settings.environment != "test" and settings.feature_rag_enabled:
        try:
            ingest_news_articles(
                articles=articles,
                company=company_name,
                ticker=ticker,
                chroma=build_chroma_client(),
            )
        except Exception as exc:
            logger.warning(
                "ingest_news_articles failed for %s (non-fatal): %s",
                company_name,
                exc,
            )

    # --- Step 2: Per-article scoring (pure Python, deterministic)
    article_scores: list[float] = []
    article_texts: list[str] = []
    positive_count = 0
    negative_count = 0
    neutral_count = 0

    for art in articles:
        title = art.get("title") or art.get("headline") or ""
        description = art.get("description") or art.get("snippet") or ""
        score = _score_article(title, description)
        article_scores.append(score)
        article_texts.append(title + " " + description)
        if score > 0.1:
            positive_count += 1
        elif score < -0.1:
            negative_count += 1
        else:
            neutral_count += 1

    # --- Step 3: Aggregate score and label
    aggregate_score = _aggregate_scores(article_scores)
    label = _label_from_score(aggregate_score)

    # --- Step 4: Deterministic red flag detection
    keyword_flags = _detect_red_flags(article_texts)

    # --- Step 5: ChromaDB semantic search (non-fatal on failure; skipped
    # entirely when FEATURE_RAG_ENABLED is off -- T-074 audit findings
    # C4/C5. News Sentiment's score is already fully determined by Step 2's
    # deterministic per-article scoring above; chroma_snippets only ever
    # add narrative colour for the LLM synthesis step below, so skipping
    # them is a clean degradation, not a partial-failure state.)
    chroma_snippets: list[dict[str, Any]] = []
    if settings.feature_rag_enabled:
        try:
            chroma_snippets = semantic_search(
                query=f"{company_name} news sentiment risk",
                collection_name=COLLECTION_NEWS,
                n_results=CHROMA_N_RESULTS,
                company_filter=company_name,
            )
        except Exception as exc:
            logger.warning(
                "ChromaDB search failed for %s (non-fatal): %s", company_name, exc
            )

    # --- Step 6: LLM call for narrative synthesis
    logger.info(
        "Sentiment agent: invoking LLM company=%s articles=%d",
        company_name,
        len(articles),
    )

    article_stats = {
        "total": len(articles),
        "positive": positive_count,
        "negative": negative_count,
        "neutral": neutral_count,
    }

    top_positive: list[str] = []
    top_negative: list[str] = []
    dominant_topics: list[str] = []
    llm_flags: list[str] = []
    summary = ""

    try:
        import json
        import re

        llm = get_llm()
        prompt = _build_sentiment_prompt(
            company_name=company_name,
            ticker=ticker,
            articles=articles,
            chroma_snippets=chroma_snippets,
            aggregate_score=aggregate_score,
            label=label,
            article_stats=article_stats,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
        cleaned = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed = json.loads(cleaned)

        top_positive = parsed.get("top_positive_headlines", [])[:3]
        top_negative = parsed.get("top_negative_headlines", [])[:3]
        dominant_topics = parsed.get("dominant_topics", [])[:5]
        llm_flags = parsed.get("red_flags", [])
        summary = parsed.get("summary", "")

    except Exception as exc:
        logger.warning(
            "LLM call failed in sentiment agent for %s: %s", company_name, exc
        )
        # Fallback: build summary from deterministic data
        summary = (
            f"{company_name} sentiment is {label} "
            f"(score {aggregate_score:+.2f}) based on {len(articles)} articles. "
            f"{positive_count} positive, {negative_count} negative, "
            f"{neutral_count} neutral. LLM synthesis unavailable."
        )
        # Build top headlines from sorted article scores
        scored_articles = sorted(
            zip(article_scores, articles),
            key=lambda x: x[0],
            reverse=True,
        )
        top_positive = [
            (a.get("title") or a.get("headline") or "")
            for s, a in scored_articles
            if s > 0.1
        ][:3]
        top_negative = [
            (a.get("title") or a.get("headline") or "")
            for s, a in sorted(zip(article_scores, articles), key=lambda x: x[0])
            if s < -0.1
        ][:3]

    # Merge keyword-detected flags with LLM-identified flags (deduplicate)
    all_flags = list(dict.fromkeys(keyword_flags + llm_flags))

    # --- Step 7: Build and return SentimentAnalysis
    return SentimentAnalysis(
        agent_name="news_sentiment",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        sentiment_score=aggregate_score,
        sentiment_label=label,
        articles_analysed=len(articles),
        positive_articles=positive_count,
        negative_articles=negative_count,
        neutral_articles=neutral_count,
        red_flags=all_flags,
        red_flag_count=len(all_flags),
        top_positive_headlines=top_positive,
        top_negative_headlines=top_negative,
        dominant_topics=dominant_topics,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


@traced_agent("news_sentiment")
def run_sentiment_analysis(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the News Sentiment Agent.

    Reads from InvestmentState:
      - job_id       -> analysis_id for the output model
      - company_name -> human-readable company name for news query
      - ticker       -> Yahoo Finance ticker (e.g. 'TCS.NS')

    Writes to InvestmentState:
      - sentiment    -> dict representation of SentimentAnalysis

    Never raises.  On failure ``sentiment["error"]`` is non-null.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_sentiment_analysis called with empty ticker")
        result = SentimentAnalysis(
            agent_name="news_sentiment",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            sentiment_score=0.0,
            sentiment_label="neutral",
            articles_analysed=0,
            positive_articles=0,
            negative_articles=0,
            neutral_articles=0,
            error="ticker field is missing from InvestmentState",
        )
        return {"sentiment": result.model_dump()}

    try:
        result = _run_sentiment_analysis_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
        )
    except Exception as exc:
        logger.exception(
            "Unhandled error in sentiment agent node: company=%s", company_name
        )
        result = SentimentAnalysis(
            agent_name="news_sentiment",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            sentiment_score=0.0,
            sentiment_label="neutral",
            articles_analysed=0,
            positive_articles=0,
            negative_articles=0,
            neutral_articles=0,
            error=f"Unhandled agent error: {exc}",
        )

    return {"sentiment": result.model_dump()}
