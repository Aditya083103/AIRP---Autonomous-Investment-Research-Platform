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
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import SentimentAnalysis
from backend.db.chroma_client import COLLECTION_NEWS, semantic_search
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
    "raised",
    "buyback",
    "dividend",
    "expansion",
    "milestone",
    "partnership",
    "acquisition",
    "order",
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
NEGATIVE_KEYWORDS: list[str] = [
    "loss",
    "fraud",
    "scam",
    "investigation",
    "probe",
    "lawsuit",
    "penalty",
    "fine",
    "miss",
    "downgrade",
    "underperform",
    "weak",
    "decline",
    "fall",
    "slump",
    "concern",
    "warning",
    "risk",
    "debt",
    "default",
    "layoff",
    "restatement",
    "accounting",
    "sebi",
    "nse",
    "bse",
    "notice",
    "resign",
    "fired",
    "arrested",
    "charged",
    "whistleblower",
    "manipulation",
    "insider",
]

# Red flag trigger phrases (any match surfaces a flag)
RED_FLAG_PHRASES: list[str] = [
    "sebi",
    "fraud",
    "scam",
    "investigation",
    "probe",
    "insider trading",
    "accounting restatement",
    "restatement",
    "whistleblower",
    "arrested",
    "charged",
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
    "corporate governance",
    "promoter pledge",
    "pledging",
    "class action",
    "resign",
    "ceo quit",
    "md resign",
]

# Per-keyword score contribution (clamped to [-1, 1] at article level)
KEYWORD_WEIGHT: float = 0.15

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
        if kw in text:
            raw += KEYWORD_WEIGHT

    for kw in NEGATIVE_KEYWORDS:
        if kw in text:
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
        for phrase in RED_FLAG_PHRASES:
            if phrase in lower and phrase not in found:
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

    # --- Step 5: ChromaDB semantic search (non-fatal on failure)
    chroma_snippets: list[dict[str, Any]] = []
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
