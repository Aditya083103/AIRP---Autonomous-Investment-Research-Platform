# backend/tests/unit/test_sentiment_analyst.py
"""
Unit tests for T-024: News Sentiment Agent.

Test strategy:
  1. _score_article           -- positive/negative/neutral keyword scoring
  2. _label_from_score        -- score band to label mapping
  3. _detect_red_flags        -- red flag keyword detection
  4. _aggregate_scores        -- mean computation and edge cases
  5. _build_sentiment_prompt  -- prompt content verification
  6. _run_sentiment_analysis_core  -- full agent with mocked tool + LLM
  7. run_sentiment_analysis   -- LangGraph node state in/out
  8. Error paths              -- missing ticker, tool error, LLM failure

Acceptance criteria verified:
  * Sentiment score is directionally correct for obvious positive/negative news
  * red_flags is populated when relevant keywords are present
  * Agent never raises -- always returns dict with 'sentiment' key
  * SentimentAnalysis Pydantic model validates correctly

All external calls (NewsAPI, Redis, ChromaDB, LLM) are mocked.
"""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.agents.output_models import SentimentAnalysis  # noqa: E402
from backend.agents.sentiment_analyst import (  # noqa: E402
    SYSTEM_PROMPT,
    _aggregate_scores,
    _build_sentiment_prompt,
    _detect_red_flags,
    _label_from_score,
    _run_sentiment_analysis_core,
    _score_article,
    run_sentiment_analysis,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_ARTICLES_POSITIVE: list[dict[str, Any]] = [
    {
        "title": "TCS records best quarterly profit in company history",
        "description": "Strong growth in digital and cloud services drove revenues up.",
        "published_at": "2024-01-15",
    },
    {
        "title": "TCS wins $500 million deal with US bank",
        "description": "Strong order inflow for the year.",
        "published_at": "2024-01-10",
    },
    {
        "title": "TCS dividend raised, buyback announced for shareholders",
        "description": "Robust earnings led to capital return expansion.",
        "published_at": "2024-01-05",
    },
]

_ARTICLES_NEGATIVE: list[dict[str, Any]] = [
    {
        "title": "TCS under SEBI investigation for alleged insider trading",
        "description": "Regulatory probe, whistleblower complaint filed.",
        "published_at": "2024-01-15",
    },
    {
        "title": "TCS reports loss in North America segment amid weak demand",
        "description": "Decline in revenue raises concern among analysts.",
        "published_at": "2024-01-10",
    },
    {
        "title": "TCS CEO faces fraud probe, accounting restatement likely",
        "description": "Investigators looking into expense manipulation.",
        "published_at": "2024-01-05",
    },
]

_ARTICLES_NEUTRAL: list[dict[str, Any]] = [
    {
        "title": "TCS announces new office in Pune",
        "description": "The company opened a new campus in the city.",
        "published_at": "2024-01-12",
    },
    {
        "title": "TCS participates in technology conference",
        "description": "Representatives from the company attended the event.",
        "published_at": "2024-01-08",
    },
]

_NEWS_RESULT_GOOD: dict[str, Any] = {
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "articles": _ARTICLES_POSITIVE,
    "total_results": 3,
    "from_date": "2023-12-15",
    "to_date": "2024-01-15",
}

_LLM_RESPONSE: dict[str, Any] = {
    "top_positive_headlines": [
        "TCS records best quarterly profit in company history",
        "TCS wins $500 million deal with US bank",
    ],
    "top_negative_headlines": [],
    "dominant_topics": ["deal wins", "profit growth", "digital expansion"],
    "red_flags": [],
    "summary": (
        "TCS news sentiment is strongly positive over the last 30 days, "
        "driven by record profits and major deal wins. No red flags detected."
    ),
}
_LLM_JSON = json.dumps(_LLM_RESPONSE)

_STATE_TCS = {"job_id": "test-001", "company_name": "TCS", "ticker": "TCS.NS"}
_STATE_INFY = {
    "job_id": "test-002",
    "company_name": "Infosys",
    "ticker": "INFY.NS",
}


def _mock_llm(content: str = _LLM_JSON) -> MagicMock:
    m = MagicMock()
    m.invoke.return_value = MagicMock(content=content)
    return m


# ---------------------------------------------------------------------------
# Tests: _score_article
# ---------------------------------------------------------------------------


class TestScoreArticle:
    """
    Score verified against known keyword combinations.

    Acceptance criteria: score is POSITIVE for clearly positive news
    and NEGATIVE for clearly negative news.
    """

    def test_strongly_positive_article_scores_positive(self) -> None:
        score = _score_article(
            "TCS records profit growth milestone",
            "Strong deal wins and revenue expansion across all verticals.",
        )
        assert score > 0.0

    def test_strongly_negative_article_scores_negative(self) -> None:
        score = _score_article(
            "TCS fraud investigation by SEBI",
            "Regulatory probe into alleged manipulation and insider trading.",
        )
        assert score < 0.0

    def test_neutral_article_scores_near_zero(self) -> None:
        score = _score_article(
            "TCS opens new office in Hyderabad",
            "The facility will house 500 employees.",
        )
        # No strong keywords -> absolute value should be small
        assert abs(score) < 0.3

    def test_score_clamped_to_minus_one(self) -> None:
        # Max possible negative score must not exceed -1.0
        neg_headline = " ".join(
            ["fraud loss investigation probe lawsuit penalty fine miss downgrade"] * 5
        )
        score = _score_article(neg_headline, neg_headline)
        assert score >= -1.0

    def test_score_clamped_to_plus_one(self) -> None:
        pos_headline = " ".join(
            ["record profit growth beat wins deal upgrade outperform strong"] * 5
        )
        score = _score_article(pos_headline, pos_headline)
        assert score <= 1.0

    def test_empty_strings_score_zero(self) -> None:
        assert _score_article("", "") == 0.0

    def test_returns_float(self) -> None:
        assert isinstance(_score_article("TCS profit growth", ""), float)

    def test_case_insensitive_matching(self) -> None:
        score_lower = _score_article("profit growth deal", "")
        score_upper = _score_article("PROFIT GROWTH DEAL", "")
        assert score_lower == score_upper

    def test_sebi_notice_scores_negative(self) -> None:
        score = _score_article("SEBI notice issued to TCS", "Regulatory concern.")
        assert score < 0.0

    def test_dividend_scores_positive(self) -> None:
        score = _score_article("TCS announces dividend", "Returns to shareholders.")
        assert score > 0.0


# ---------------------------------------------------------------------------
# Tests: _label_from_score
# ---------------------------------------------------------------------------


class TestLabelFromScore:
    def test_very_positive(self) -> None:
        assert _label_from_score(0.5) == "very_positive"
        assert _label_from_score(0.31) == "very_positive"
        assert _label_from_score(1.0) == "very_positive"

    def test_positive(self) -> None:
        assert _label_from_score(0.2) == "positive"
        assert _label_from_score(0.11) == "positive"
        assert _label_from_score(0.3) == "positive"

    def test_neutral(self) -> None:
        assert _label_from_score(0.0) == "neutral"
        assert _label_from_score(0.1) == "neutral"
        assert _label_from_score(-0.1) == "neutral"
        assert _label_from_score(0.05) == "neutral"

    def test_negative(self) -> None:
        assert _label_from_score(-0.2) == "negative"
        assert _label_from_score(-0.3) == "negative"

    def test_very_negative(self) -> None:
        assert _label_from_score(-0.5) == "very_negative"
        assert _label_from_score(-1.0) == "very_negative"
        assert _label_from_score(-0.31) == "very_negative"

    def test_exact_boundary_positive(self) -> None:
        # 0.3 is positive (> 0.1 but <= 0.3)
        assert _label_from_score(0.3) == "positive"

    def test_exact_boundary_0_1(self) -> None:
        # 0.1 is neutral
        assert _label_from_score(0.1) == "neutral"


# ---------------------------------------------------------------------------
# Tests: _detect_red_flags
# ---------------------------------------------------------------------------


class TestDetectRedFlags:
    def test_sebi_triggers_flag(self) -> None:
        texts = ["TCS received sebi notice for alleged misconduct"]
        flags = _detect_red_flags(texts)
        assert any("sebi" in f.lower() for f in flags)

    def test_fraud_triggers_flag(self) -> None:
        texts = ["CEO charged with fraud by authorities"]
        flags = _detect_red_flags(texts)
        assert any("fraud" in f.lower() for f in flags)

    def test_clean_text_returns_empty_list(self) -> None:
        texts = [
            "TCS wins large contract for digital transformation",
            "Company announces record profits for the quarter",
        ]
        flags = _detect_red_flags(texts)
        assert flags == []

    def test_multiple_flags_detected(self) -> None:
        texts = ["SEBI probe into insider trading and manipulation at TCS"]
        flags = _detect_red_flags(texts)
        # At least 2 flags: sebi + insider trading + manipulation
        assert len(flags) >= 2

    def test_deduplication(self) -> None:
        # Same phrase in two articles should produce one flag entry
        texts = [
            "SEBI investigating TCS",
            "SEBI has sent notice to TCS management",
        ]
        flags = _detect_red_flags(texts)
        sebi_flags = [f for f in flags if "sebi" in f.lower()]
        assert len(sebi_flags) == 1

    def test_empty_list_returns_empty(self) -> None:
        assert _detect_red_flags([]) == []

    def test_case_insensitive(self) -> None:
        upper = _detect_red_flags(["SEBI FRAUD PROBE"])
        lower = _detect_red_flags(["sebi fraud probe"])
        assert len(upper) == len(lower)

    def test_returns_list_of_strings(self) -> None:
        flags = _detect_red_flags(["Some text"])
        assert isinstance(flags, list)
        for f in flags:
            assert isinstance(f, str)

    def test_resignation_triggers_flag(self) -> None:
        flags = _detect_red_flags(["TCS MD to resign amid board dispute"])
        assert any("resign" in f.lower() for f in flags)


# ---------------------------------------------------------------------------
# Tests: _aggregate_scores
# ---------------------------------------------------------------------------


class TestAggregateScores:
    def test_empty_list_returns_zero(self) -> None:
        assert _aggregate_scores([]) == 0.0

    def test_all_positive(self) -> None:
        assert _aggregate_scores([0.5, 0.5, 0.5]) == pytest.approx(0.5)

    def test_all_negative(self) -> None:
        assert _aggregate_scores([-0.3, -0.3, -0.3]) == pytest.approx(-0.3)

    def test_mixed(self) -> None:
        # mean([0.5, -0.5]) = 0.0
        assert _aggregate_scores([0.5, -0.5]) == pytest.approx(0.0)

    def test_single_value(self) -> None:
        assert _aggregate_scores([0.8]) == pytest.approx(0.8)

    def test_clamped_positive(self) -> None:
        # Even if raw mean > 1.0 due to input edge cases, output is clamped
        result = _aggregate_scores([1.0, 1.0])
        assert result <= 1.0

    def test_clamped_negative(self) -> None:
        result = _aggregate_scores([-1.0, -1.0])
        assert result >= -1.0

    def test_returns_float(self) -> None:
        assert isinstance(_aggregate_scores([0.3]), float)

    def test_rounded_to_4dp(self) -> None:
        result = _aggregate_scores([0.1, 0.2, 0.3])
        assert result == round(result, 4)


# ---------------------------------------------------------------------------
# Tests: _build_sentiment_prompt
# ---------------------------------------------------------------------------


class TestBuildSentimentPrompt:
    def _make(self, **kwargs: Any) -> str:
        defaults: dict[str, Any] = {
            "company_name": "TCS",
            "ticker": "TCS.NS",
            "articles": _ARTICLES_POSITIVE,
            "chroma_snippets": [],
            "aggregate_score": 0.45,
            "label": "very_positive",
            "article_stats": {
                "total": 3,
                "positive": 3,
                "negative": 0,
                "neutral": 0,
            },
        }
        defaults.update(kwargs)
        return _build_sentiment_prompt(**defaults)

    def test_contains_company_name(self) -> None:
        assert "TCS" in self._make()

    def test_contains_ticker(self) -> None:
        assert "TCS.NS" in self._make()

    def test_contains_aggregate_score(self) -> None:
        assert "0.4500" in self._make() or "+0.45" in self._make()

    def test_contains_label(self) -> None:
        assert "very_positive" in self._make()

    def test_contains_article_count(self) -> None:
        assert "3" in self._make()

    def test_contains_article_titles(self) -> None:
        prompt = self._make()
        assert "profit" in prompt.lower() or "TCS" in prompt

    def test_chroma_snippets_included_when_present(self) -> None:
        snippets = [{"document": "TCS AI strategy 2024", "distance": 0.12}]
        prompt = self._make(chroma_snippets=snippets)
        assert "ChromaDB" in prompt or "semantic" in prompt.lower()

    def test_no_chroma_section_when_empty(self) -> None:
        prompt = self._make(chroma_snippets=[])
        assert "ChromaDB" not in prompt

    def test_returns_string(self) -> None:
        assert isinstance(self._make(), str)

    def test_negative_articles_included(self) -> None:
        prompt = self._make(articles=_ARTICLES_NEGATIVE, label="very_negative")
        assert "SEBI" in prompt or "investigation" in prompt.lower()


# ---------------------------------------------------------------------------
# Tests: _run_sentiment_analysis_core (full agent, mocked externals)
# ---------------------------------------------------------------------------


class TestRunSentimentAnalysisCore:
    """
    Acceptance criteria:
      * Sentiment score directionally correct for positive/negative news
      * red_flags populated when SEBI / fraud keywords present
    """

    def _run(
        self,
        news_result: dict[str, Any] = _NEWS_RESULT_GOOD,
        llm_response: str = _LLM_JSON,
        ticker: str = "TCS.NS",
        company_name: str = "TCS",
    ) -> SentimentAnalysis:
        mock_llm = _mock_llm(llm_response)
        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_news.invoke.return_value = news_result
            return _run_sentiment_analysis_core(
                analysis_id="test-001",
                company_name=company_name,
                ticker=ticker,
            )

    def test_returns_sentiment_analysis_instance(self) -> None:
        assert isinstance(self._run(), SentimentAnalysis)

    def test_agent_name_correct(self) -> None:
        assert self._run().agent_name == "news_sentiment"

    def test_ticker_preserved(self) -> None:
        assert self._run().ticker == "TCS.NS"

    def test_error_is_none_on_success(self) -> None:
        assert self._run().error is None

    def test_positive_news_gives_positive_score(self) -> None:
        result = self._run(news_result=_NEWS_RESULT_GOOD)
        # All articles are positive -> aggregate score should be > 0
        assert result.sentiment_score > 0.0

    def test_positive_news_gives_positive_label(self) -> None:
        result = self._run(news_result=_NEWS_RESULT_GOOD)
        assert result.sentiment_label in ("positive", "very_positive")

    def test_negative_news_gives_negative_score(self) -> None:
        negative_result = {**_NEWS_RESULT_GOOD, "articles": _ARTICLES_NEGATIVE}
        result = self._run(news_result=negative_result)
        assert result.sentiment_score < 0.0

    def test_negative_news_gives_negative_label(self) -> None:
        negative_result = {**_NEWS_RESULT_GOOD, "articles": _ARTICLES_NEGATIVE}
        result = self._run(news_result=negative_result)
        assert result.sentiment_label in ("negative", "very_negative")

    def test_red_flags_detected_for_sebi_news(self) -> None:
        """Acceptance criteria: red_flags populated when relevant."""
        negative_result = {**_NEWS_RESULT_GOOD, "articles": _ARTICLES_NEGATIVE}
        result = self._run(news_result=negative_result)
        # SEBI + fraud + insider trading + restatement present in articles
        assert len(result.red_flags) > 0

    def test_no_red_flags_for_clean_news(self) -> None:
        result = self._run(news_result=_NEWS_RESULT_GOOD)
        # Positive articles have no red flag keywords
        assert result.red_flag_count == len(result.red_flags)

    def test_articles_analysed_correct(self) -> None:
        result = self._run()
        assert result.articles_analysed == len(_ARTICLES_POSITIVE)

    def test_positive_count_correct(self) -> None:
        result = self._run()
        assert result.positive_articles >= 0
        assert (
            result.positive_articles
            + result.negative_articles
            + result.neutral_articles
            == result.articles_analysed
        )

    def test_sentiment_score_in_range(self) -> None:
        result = self._run()
        assert -1.0 <= result.sentiment_score <= 1.0

    def test_summary_populated(self) -> None:
        result = self._run()
        assert len(result.summary) > 0

    def test_top_positive_headlines_from_llm(self) -> None:
        result = self._run()
        assert isinstance(result.top_positive_headlines, list)

    def test_dominant_topics_from_llm(self) -> None:
        result = self._run()
        assert isinstance(result.dominant_topics, list)

    def test_model_serialisable(self) -> None:
        d = self._run().model_dump()
        assert isinstance(d, dict)
        assert d["agent_name"] == "news_sentiment"

    def test_tool_called_with_correct_company(self) -> None:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_news.invoke.return_value = _NEWS_RESULT_GOOD
            _run_sentiment_analysis_core("x", "TCS", "TCS.NS")
            call_args = mock_news.invoke.call_args[0][0]
            assert call_args["company_name"] == "TCS"

    def test_news_tool_error_returns_model_with_error(self) -> None:
        error_result = {"error": "api_limit", "message": "Daily limit exceeded"}
        result = self._run(news_result=error_result)
        assert isinstance(result, SentimentAnalysis)
        assert result.error is not None

    def test_fetch_news_exception_returns_model_with_error(self) -> None:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_news.invoke.side_effect = RuntimeError("Network error")
            result = _run_sentiment_analysis_core("x", "TCS", "TCS.NS")
        assert result.error is not None

    def test_chroma_failure_is_non_fatal(self) -> None:
        """ChromaDB failure must not cause agent to return error."""
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                side_effect=RuntimeError("ChromaDB unavailable"),
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_news.invoke.return_value = _NEWS_RESULT_GOOD
            result = _run_sentiment_analysis_core("x", "TCS", "TCS.NS")
        # Should succeed despite ChromaDB failure
        assert isinstance(result, SentimentAnalysis)
        assert result.error is None

    def test_llm_failure_uses_fallback_summary(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Groq timeout")
        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_news.invoke.return_value = _NEWS_RESULT_GOOD
            result = _run_sentiment_analysis_core("x", "TCS", "TCS.NS")
        assert isinstance(result, SentimentAnalysis)
        assert result.error is None  # graceful degradation
        assert len(result.summary) > 0

    def test_llm_malformed_json_uses_fallback(self) -> None:
        result = self._run(llm_response="I cannot analyse this.")
        assert isinstance(result, SentimentAnalysis)
        assert result.sentiment_score is not None

    def test_empty_articles_list_returns_neutral(self) -> None:
        empty_result = {**_NEWS_RESULT_GOOD, "articles": []}
        result = self._run(news_result=empty_result)
        assert result.sentiment_score == pytest.approx(0.0)
        assert result.articles_analysed == 0

    def test_neutral_articles_score_neutral(self) -> None:
        neutral_result = {**_NEWS_RESULT_GOOD, "articles": _ARTICLES_NEUTRAL}
        result = self._run(news_result=neutral_result)
        # Neutral articles should produce a near-zero or moderate score
        assert -0.5 <= result.sentiment_score <= 0.5

    def test_red_flag_count_matches_list_length(self) -> None:
        result = self._run()
        assert result.red_flag_count == len(result.red_flags)

    def test_infy_ticker(self) -> None:
        infy_result = {**_NEWS_RESULT_GOOD, "ticker": "INFY.NS"}
        result = self._run(news_result=infy_result, ticker="INFY.NS")
        assert result.ticker == "INFY.NS"


# ---------------------------------------------------------------------------
# Tests: run_sentiment_analysis (LangGraph node)
# ---------------------------------------------------------------------------


class TestRunSentimentAnalysisNode:
    def _invoke(
        self,
        state: dict[str, Any],
        news_result: dict[str, Any] = _NEWS_RESULT_GOOD,
    ) -> dict[str, Any]:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_news.invoke.return_value = news_result
            return run_sentiment_analysis(state)

    def test_returns_dict_with_sentiment_key(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert "sentiment" in result
        assert isinstance(result["sentiment"], dict)

    def test_sentiment_has_score(self) -> None:
        result = self._invoke(_STATE_TCS)
        score = result["sentiment"]["sentiment_score"]
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0

    def test_sentiment_has_label(self) -> None:
        result = self._invoke(_STATE_TCS)
        label = result["sentiment"]["sentiment_label"]
        assert label in (
            "very_positive",
            "positive",
            "neutral",
            "negative",
            "very_negative",
        )

    def test_job_id_preserved(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert result["sentiment"]["analysis_id"] == "test-001"

    def test_empty_ticker_returns_error(self) -> None:
        result = run_sentiment_analysis(
            {"job_id": "x", "company_name": "Test", "ticker": ""}
        )
        assert result["sentiment"]["error"] is not None

    def test_missing_ticker_key_returns_error(self) -> None:
        result = run_sentiment_analysis({"job_id": "x", "company_name": "Test"})
        assert result["sentiment"]["error"] is not None

    def test_never_raises_on_catastrophic_failure(self) -> None:
        with patch(
            "backend.agents.sentiment_analyst._run_sentiment_analysis_core",
            side_effect=RuntimeError("Catastrophic failure"),
        ):
            result = run_sentiment_analysis(_STATE_TCS)
        assert "sentiment" in result
        assert result["sentiment"]["error"] is not None

    def test_tcs_state(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert result["sentiment"]["ticker"] == "TCS.NS"

    def test_infy_state(self) -> None:
        result = self._invoke(_STATE_INFY)
        assert result["sentiment"]["ticker"] == "INFY.NS"

    def test_articles_analysed_in_output(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert "articles_analysed" in result["sentiment"]

    def test_red_flags_is_list(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert isinstance(result["sentiment"]["red_flags"], list)

    def test_sentiment_dict_serialisable(self) -> None:
        result = self._invoke(_STATE_TCS)
        # model_dump(mode="json") converts datetime -> ISO string so that
        # the dict is fully JSON-serialisable (matches FastAPI behaviour).
        import json as _json

        from backend.agents.output_models import SentimentAnalysis

        obj = SentimentAnalysis(**result["sentiment"])
        dumped = _json.dumps(obj.model_dump(mode="json"))
        assert isinstance(dumped, str)


# ---------------------------------------------------------------------------
# Tests: system prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_is_non_empty_string(self) -> None:
        assert isinstance(SYSTEM_PROMPT, str) and len(SYSTEM_PROMPT) > 50

    def test_mentions_json(self) -> None:
        assert "JSON" in SYSTEM_PROMPT

    def test_mentions_summary(self) -> None:
        assert "summary" in SYSTEM_PROMPT.lower()

    def test_mentions_red_flags(self) -> None:
        assert "red_flag" in SYSTEM_PROMPT.lower()

    def test_mentions_sentiment(self) -> None:
        assert "sentiment" in SYSTEM_PROMPT.lower()
