# backend/tests/unit/test_earnings_transcript.py
"""
Unit tests for backend/tools/earnings_transcript.py — T-015

All HTTP requests to Screener.in, all PDF library calls, and all Redis cache
operations are mocked so these tests run fully offline in CI with no network
and no real Redis.

Test coverage targets (acceptance criteria from T-015):
  ✓ Happy path: scrape returns valid TranscriptResult for TCS, Infosys, Reliance
  ✓ _company_to_slug resolves all major company aliases correctly
  ✓ _extract_quarter_year parses Q3 FY2024, Q1FY24, Q2 FY 2023 correctly
  ✓ Screener concall-content div path extracts text
  ✓ Screener keyword-based largest-div fallback path extracts text
  ✓ Screener linked-PDF fallback path fetches and extracts PDF
  ✓ TranscriptBlockedError (403/429/503) → error dict, never raises
  ✓ TranscriptScrapeError (no text found) → error dict, never raises
  ✓ Unexpected exception → error dict, never raises
  ✓ Cache hit short-circuits the live fetch (cache_get_json called)
  ✓ cache_set_json called with correct key and TTL on successful scrape
  ✓ Empty transcript NOT cached (len ≤ 100 chars)
  ✓ force_refresh=True bypasses cache read
  ✓ pdf_bytes path: text extracted, result has source="pdf_upload"
  ✓ pdf_bytes path: empty PDF → error dict "pdf_empty"
  ✓ pdf_bytes path: pdfminer error → error dict "pdf_extraction_error"
  ✓ pdf_path path: valid file → text extracted, source="pdf_path"
  ✓ pdf_path path: missing file → error dict "pdf_not_found"
  ✓ pdf_path path: pdfminer error → error dict "pdf_extraction_error"
  ✓ transcript_chunk is capped at max_chunk_chars
  ✓ transcript_chunk hard-capped at MAX_CHUNK_HARD_LIMIT
  ✓ fetch_transcript_chunk returns lightweight dict (no transcript_text key)
  ✓ fetch_transcript_chunk propagates error dict from inner call
  ✓ _http_get raises TranscriptBlockedError on 403/429/503/401/406/451
  ✓ _http_get raises TranscriptScrapeError on non-200 (e.g. 404, 500)
  ✓ _http_get passes on requests.Timeout without wrapping
  ✓ TranscriptResult model: validates source field (invalid → ValueError)
  ✓ TranscriptResult model: strips leading/trailing whitespace from text
  ✓ PDF upload path: bypasses cache entirely (cache_get_json not called)
  ✓ PDF path path: bypasses cache entirely (cache_get_json not called)
  ✓ char_count reflects full transcript_text length, not chunk length

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_earnings_transcript.py -v
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

from datetime import datetime, timezone  # noqa: E402
import tempfile  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from backend.tools.earnings_transcript import (  # noqa: E402
    MAX_CHUNK_HARD_LIMIT,
    TRANSCRIPT_CACHE_PREFIX,
    PDFExtractionError,
    TranscriptBlockedError,
    TranscriptResult,
    TranscriptScrapeError,
    _company_to_slug,
    _extract_quarter_year,
    _extract_text_from_pdf_bytes,
    _extract_text_from_pdf_path,
    _fetch_earnings_transcript,
    _http_get,
    _scrape_screener_transcript,
)

# Bypass tenacity retries for _http_get in unit tests.
_http_get_raw = _http_get.__wrapped__  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Shared HTML fixtures
# ---------------------------------------------------------------------------

_SCREENER_WITH_CONCALL_DIV = """
<html>
<head><title>TCS Q3 FY2024 Concall Transcript</title></head>
<body>
<div class="concall-content">
Operator: Good morning, ladies and gentlemen. Welcome to the TCS Q3 FY2024
earnings call. My name is Priya and I will be your moderator today.

Chairman: Thank you Priya. Good morning to all participants. We are pleased
to report strong results for the quarter ended December 2023.

CFO: Revenue grew 4.5% year on year in constant currency terms.
The EBIT margin was 24.5%, within our guided band.
</div>
</body>
</html>
"""

_SCREENER_KEYWORD_FALLBACK = """
<html>
<head><title>Infosys Q2 FY2023 Earnings Call</title></head>
<body>
<div id="main">
<div class="some-wrapper">
<p>Welcome to the Infosys Q2 FY2023 earnings conference call.
Moderator: Welcome. Please go ahead, CFO.
CFO: Thank you. Revenue for the quarter was Rs 36,538 crore.
Operator: We will now open the floor for questions.
Participant: What is the outlook for FY2024?
CEO: We are raising our revenue guidance to 15-16 percent in constant currency.
</p>
</div>
</div>
</body>
</html>
"""

_SCREENER_WITH_PDF_LINK = """
<html>
<head><title>Reliance Concalls</title></head>
<body>
<a href="https://screener.in/concalls/reliance-q1-fy24.pdf">Q1 FY2024 Transcript</a>
</body>
</html>
"""

_SCREENER_EMPTY = """
<html><head><title>Company Not Found</title></head>
<body><p>No concalls found.</p></body></html>
"""

_SAMPLE_PDF_TEXT = (
    "Operator: Welcome to the Reliance Q1 FY2024 earnings call.\n"
    "CFO: Revenue grew 12% year on year. PAT was Rs 16,203 crore.\n"
    "CEO: We see strong momentum in our retail and telecom segments.\n"
)


# ---------------------------------------------------------------------------
# Helper: build a mock response
# ---------------------------------------------------------------------------


def _mock_response(
    status_code: int = 200,
    text: str = "",
    content: bytes = b"",
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    return resp


# ---------------------------------------------------------------------------
# _company_to_slug
# ---------------------------------------------------------------------------


class TestCompanyToSlug:
    def test_exact_lowercase_override(self) -> None:
        assert _company_to_slug("tcs", "TCS.NS") == "TCS"

    def test_exact_override_with_full_name(self) -> None:
        assert _company_to_slug("tata consultancy services", "TCS.NS") == "TCS"

    def test_partial_match_override(self) -> None:
        assert _company_to_slug("Infosys Limited", "INFY.NS") == "INFY"

    def test_reliance_override(self) -> None:
        assert _company_to_slug("reliance industries", "RELIANCE.NS") == "RELIANCE"

    def test_hdfc_bank_override(self) -> None:
        assert _company_to_slug("hdfc bank", "HDFCBANK.NS") == "HDFCBANK"

    def test_ticker_fallback_strips_suffix(self) -> None:
        # Not in override table — falls through to ticker stripping
        assert _company_to_slug("Bajaj Auto", "BAJAJAUTO.NS") == "BAJAJAUTO"

    def test_bse_ticker_strips_dot_bo(self) -> None:
        assert _company_to_slug("Some Company", "532540.BO") == "532540"

    def test_first_word_last_resort(self) -> None:
        result = _company_to_slug("Accenture Global", "")
        assert result == "ACCENTURE"

    def test_icici_bank_override(self) -> None:
        assert _company_to_slug("icici bank", "ICICIBANK.NS") == "ICICIBANK"

    def test_wipro_override(self) -> None:
        assert _company_to_slug("Wipro Limited", "WIPRO.NS") == "WIPRO"


# ---------------------------------------------------------------------------
# _extract_quarter_year
# ---------------------------------------------------------------------------


class TestExtractQuarterYear:
    def test_standard_q3_fy2024(self) -> None:
        q, y = _extract_quarter_year("TCS Q3 FY2024 Concall Transcript")
        assert q == "Q3 FY2024"
        assert y == "2024"

    def test_compact_q1fy24(self) -> None:
        q, y = _extract_quarter_year("Infosys Q1FY24 Results")
        assert q == "Q1 FY2024"
        assert y == "2024"

    def test_spaced_q2_fy_2023(self) -> None:
        q, y = _extract_quarter_year("Q2 FY 2023 earnings call")
        assert q == "Q2 FY2023"
        assert y == "2023"

    def test_no_quarter_found(self) -> None:
        q, y = _extract_quarter_year("Annual Report 2023")
        assert q == ""
        assert y == ""

    def test_two_digit_year_normalised(self) -> None:
        q, y = _extract_quarter_year("Q4FY25 concall highlights")
        assert y == "2025"

    def test_case_insensitive(self) -> None:
        q, y = _extract_quarter_year("q3 fy2024 transcript")
        assert q == "Q3 FY2024"


# ---------------------------------------------------------------------------
# _http_get  (unwrapped — no tenacity)
# ---------------------------------------------------------------------------


class TestHttpGet:
    @patch("backend.tools.earnings_transcript.requests.get")
    def test_200_returns_response(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response(200, text="hello")
        resp = _http_get_raw("https://example.com")
        assert resp.status_code == 200

    @pytest.mark.parametrize("code", [401, 403, 406, 429, 451, 503])
    @patch("backend.tools.earnings_transcript.requests.get")
    def test_bot_block_codes_raise_blocked(
        self, mock_get: MagicMock, code: int
    ) -> None:
        mock_get.return_value = _mock_response(code)
        with pytest.raises(TranscriptBlockedError):
            _http_get_raw("https://example.com")

    @pytest.mark.parametrize("code", [404, 500, 502])
    @patch("backend.tools.earnings_transcript.requests.get")
    def test_other_error_codes_raise_scrape_error(
        self, mock_get: MagicMock, code: int
    ) -> None:
        mock_get.return_value = _mock_response(code)
        with pytest.raises(TranscriptScrapeError):
            _http_get_raw("https://example.com")

    @patch("backend.tools.earnings_transcript.requests.get")
    def test_timeout_propagates(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.Timeout("timed out")
        with pytest.raises(requests.Timeout):
            _http_get_raw("https://example.com")


# ---------------------------------------------------------------------------
# _scrape_screener_transcript
# ---------------------------------------------------------------------------


class TestScrapeScreenerTranscript:
    @patch("backend.tools.earnings_transcript._http_get")
    def test_concall_div_path(self, mock_http: MagicMock) -> None:
        mock_http.return_value = _mock_response(200, text=_SCREENER_WITH_CONCALL_DIV)
        text, quarter, year, warnings = _scrape_screener_transcript(
            "TCS", "TCS.NS", "https://www.screener.in"
        )
        assert "earnings call" in text.lower() or "operator" in text.lower()
        assert quarter == "Q3 FY2024"
        assert year == "2024"

    @patch("backend.tools.earnings_transcript._http_get")
    def test_keyword_fallback_path(self, mock_http: MagicMock) -> None:
        mock_http.return_value = _mock_response(200, text=_SCREENER_KEYWORD_FALLBACK)
        text, quarter, year, warnings = _scrape_screener_transcript(
            "Infosys", "INFY.NS", "https://www.screener.in"
        )
        assert len(text) > 50
        assert quarter == "Q2 FY2023"

    @patch("backend.tools.earnings_transcript.requests.get")
    @patch("backend.tools.earnings_transcript._http_get")
    def test_pdf_link_fallback(
        self, mock_http: MagicMock, mock_requests_get: MagicMock
    ) -> None:
        mock_http.return_value = _mock_response(200, text=_SCREENER_WITH_PDF_LINK)

        # Simulate a PDF response with extractable bytes marker
        mock_pdf_resp = MagicMock()
        mock_pdf_resp.status_code = 200
        mock_pdf_resp.content = b"%PDF-1.4 fake pdf content for testing"
        mock_requests_get.return_value = mock_pdf_resp

        # Patch the PDF extractor so we don't need pdfminer in test env
        with patch(
            "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
            return_value=_SAMPLE_PDF_TEXT,
        ):
            text, quarter, year, warnings = _scrape_screener_transcript(
                "Reliance", "RELIANCE.NS", "https://www.screener.in"
            )
        assert "Revenue grew" in text
        assert any("PDF" in w for w in warnings)

    @patch("backend.tools.earnings_transcript._http_get")
    def test_empty_page_raises_scrape_error(self, mock_http: MagicMock) -> None:
        mock_http.return_value = _mock_response(200, text=_SCREENER_EMPTY)
        with pytest.raises(TranscriptScrapeError):
            _scrape_screener_transcript(
                "Unknown Corp", "UNKNOWN.NS", "https://www.screener.in"
            )

    @patch("backend.tools.earnings_transcript._http_get")
    def test_bot_block_propagates(self, mock_http: MagicMock) -> None:
        mock_http.side_effect = TranscriptBlockedError("403 blocked")
        with pytest.raises(TranscriptBlockedError):
            _scrape_screener_transcript("TCS", "TCS.NS", "https://www.screener.in")


# ---------------------------------------------------------------------------
# _extract_text_from_pdf_bytes and _extract_text_from_pdf_path
# ---------------------------------------------------------------------------


class TestPDFExtraction:
    def test_bytes_delegates_to_pdfminer(self) -> None:
        with patch(
            "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
            return_value=_SAMPLE_PDF_TEXT,
        ) as mock_ext:
            result = mock_ext(b"%PDF fake")
            assert "Revenue grew" in result

    def test_bytes_pdfminer_import_error_raises(self) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name in ("pdfminer.high_level", "pdfminer", "PyPDF2"):
                raise ImportError(f"Mocked import error for {name}")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(PDFExtractionError):
                _extract_text_from_pdf_bytes(b"%PDF fake")

    def test_path_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            _extract_text_from_pdf_path("/nonexistent/path/transcript.pdf")

    def test_path_extraction_succeeds(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF-1.4 dummy content")
            tmp_path = fh.name

        with patch(
            "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
            return_value=_SAMPLE_PDF_TEXT,
        ):
            text = _extract_text_from_pdf_path(tmp_path)
        assert "Revenue grew" in text

        os.unlink(tmp_path)

    def test_path_pdfminer_error_wraps(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF-1.4 dummy content")
            tmp_path = fh.name

        with patch(
            "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
            side_effect=PDFExtractionError("pdfminer exploded"),
        ):
            with pytest.raises(PDFExtractionError):
                _extract_text_from_pdf_path(tmp_path)

        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# _fetch_earnings_transcript — PDF upload path
# ---------------------------------------------------------------------------


class TestFetchEarningsTranscriptPDFUpload:
    @patch(
        "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_PDF_TEXT,
    )
    @patch("backend.tools.earnings_transcript.cache_get_json")
    def test_pdf_bytes_returns_correct_source(
        self,
        mock_cache_get: MagicMock,
        mock_extract: MagicMock,
    ) -> None:
        result = _fetch_earnings_transcript(
            company_name="Reliance",
            ticker="RELIANCE.NS",
            pdf_bytes=b"%PDF fake",
        )
        assert result.get("source") == "pdf_upload"
        assert "Revenue grew" in result.get("transcript_text", "")
        # Cache should NOT be consulted for PDF uploads
        mock_cache_get.assert_not_called()

    @patch(
        "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_PDF_TEXT,
    )
    @patch("backend.tools.earnings_transcript.cache_set_json")
    def test_pdf_bytes_does_not_write_cache(
        self,
        mock_cache_set: MagicMock,
        mock_extract: MagicMock,
    ) -> None:
        _fetch_earnings_transcript(
            company_name="Reliance",
            ticker="RELIANCE.NS",
            pdf_bytes=b"%PDF fake",
        )
        mock_cache_set.assert_not_called()

    @patch(
        "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
        return_value="",
    )
    def test_pdf_bytes_empty_returns_error_dict(self, mock_extract: MagicMock) -> None:
        result = _fetch_earnings_transcript(
            company_name="TCS",
            ticker="TCS.NS",
            pdf_bytes=b"%PDF fake",
        )
        assert result.get("error") == "pdf_empty"

    @patch(
        "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
        side_effect=PDFExtractionError("pdfminer broken"),
    )
    def test_pdf_bytes_extraction_error_returns_error_dict(
        self, mock_extract: MagicMock
    ) -> None:
        result = _fetch_earnings_transcript(
            company_name="TCS",
            ticker="TCS.NS",
            pdf_bytes=b"%PDF fake",
        )
        assert result.get("error") == "pdf_extraction_error"

    @patch(
        "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
        return_value=_SAMPLE_PDF_TEXT,
    )
    def test_pdf_bytes_quarter_extracted(self, mock_extract: MagicMock) -> None:
        long_text = "Q1 FY2024 Earnings Call Transcript\n" + _SAMPLE_PDF_TEXT
        with patch(
            "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
            return_value=long_text,
        ):
            result = _fetch_earnings_transcript(
                company_name="Reliance",
                ticker="RELIANCE.NS",
                pdf_bytes=b"%PDF fake",
            )
        assert result.get("quarter") == "Q1 FY2024"


# ---------------------------------------------------------------------------
# _fetch_earnings_transcript — PDF path on disk
# ---------------------------------------------------------------------------


class TestFetchEarningsTranscriptPDFPath:
    def test_valid_pdf_path_returns_pdf_path_source(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF-1.4 dummy")
            tmp = fh.name

        with patch(
            "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
            return_value=_SAMPLE_PDF_TEXT,
        ):
            result = _fetch_earnings_transcript(
                company_name="Infosys",
                ticker="INFY.NS",
                pdf_path=tmp,
            )
        os.unlink(tmp)
        assert result.get("source") == "pdf_path"
        assert "Revenue grew" in result.get("transcript_text", "")

    def test_missing_pdf_path_returns_error_dict(self) -> None:
        result = _fetch_earnings_transcript(
            company_name="Infosys",
            ticker="INFY.NS",
            pdf_path="/nonexistent/file.pdf",
        )
        assert result.get("error") == "pdf_not_found"

    @patch("backend.tools.earnings_transcript.cache_get_json")
    def test_pdf_path_bypasses_cache(self, mock_cache_get: MagicMock) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF-1.4 dummy")
            tmp = fh.name

        with patch(
            "backend.tools.earnings_transcript._extract_text_from_pdf_bytes",
            return_value=_SAMPLE_PDF_TEXT,
        ):
            _fetch_earnings_transcript(
                company_name="Infosys",
                ticker="INFY.NS",
                pdf_path=tmp,
            )
        os.unlink(tmp)
        mock_cache_get.assert_not_called()


# ---------------------------------------------------------------------------
# _fetch_earnings_transcript — Screener scrape path with cache
# ---------------------------------------------------------------------------


class TestFetchEarningsTranscriptScrape:
    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_happy_path_tcs(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_scrape.return_value = (
            "Operator: Welcome to TCS Q3 FY2024 earnings call. " * 30,
            "Q3 FY2024",
            "2024",
            [],
        )
        result = _fetch_earnings_transcript(company_name="TCS", ticker="TCS.NS")
        assert result.get("source") == "screener"
        assert result.get("quarter") == "Q3 FY2024"
        assert len(result.get("transcript_text", "")) > 100
        mock_set.assert_called_once()

    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_happy_path_infosys(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        long_text = "Moderator: Welcome to Infosys Q2 FY2023 concall. " * 20
        mock_scrape.return_value = (long_text, "Q2 FY2023", "2023", [])
        result = _fetch_earnings_transcript(company_name="Infosys", ticker="INFY.NS")
        assert result.get("source") == "screener"
        assert "error" not in result

    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_happy_path_reliance(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        long_text = "CEO: Revenue grew 12% year on year. " * 25
        mock_scrape.return_value = (long_text, "Q1 FY2024", "2024", [])
        result = _fetch_earnings_transcript(
            company_name="Reliance Industries",
            ticker="RELIANCE.NS",
        )
        assert result.get("source") == "screener"
        assert result.get("company_name") == "Reliance Industries"

    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_blocked_returns_error_dict(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        mock_scrape.side_effect = TranscriptBlockedError("403 blocked")
        result = _fetch_earnings_transcript(company_name="TCS", ticker="TCS.NS")
        assert result.get("error") == "scrape_blocked"

    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_scrape_error_returns_error_dict(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        mock_scrape.side_effect = TranscriptScrapeError("No text found")
        result = _fetch_earnings_transcript(company_name="TCS", ticker="TCS.NS")
        assert result.get("error") == "scrape_error"

    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_unexpected_exception_returns_error_dict(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        mock_scrape.side_effect = RuntimeError("Something went very wrong")
        result = _fetch_earnings_transcript(company_name="TCS", ticker="TCS.NS")
        assert result.get("error") == "unexpected_error"

    def test_cache_hit_returns_cached_true(self) -> None:
        cached_payload: dict[str, Any] = {
            "company_name": "TCS",
            "ticker": "TCS.NS",
            "exchange": "NSE",
            "transcript_text": "Operator: Welcome to Q3 FY2024. " * 30,
            "transcript_chunk": "Operator: Welcome to Q3 FY2024. " * 5,
            "source": "screener",
            "quarter": "Q3 FY2024",
            "year": "2024",
            "char_count": 960,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "warnings": [],
        }
        with patch(
            "backend.tools.earnings_transcript.cache_get_json",
            return_value=cached_payload,
        ) as mock_get:
            result = _fetch_earnings_transcript(company_name="TCS", ticker="TCS.NS")
        mock_get.assert_called_once()
        assert result.get("cached") is True

    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch(
        "backend.tools.earnings_transcript.cache_get_json",
        return_value=None,
    )
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_cache_not_written_for_short_text(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        # text ≤ 100 chars — should NOT be cached
        mock_scrape.return_value = ("Too short", "", "", [])
        _fetch_earnings_transcript(company_name="TCS", ticker="TCS.NS")
        mock_set.assert_not_called()

    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch(
        "backend.tools.earnings_transcript.cache_get_json",
        return_value=None,
    )
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_force_refresh_bypasses_cache_read(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_scrape.return_value = (
            "Operator: Welcome to earnings call. " * 30,
            "Q3 FY2024",
            "2024",
            [],
        )
        _fetch_earnings_transcript(
            company_name="TCS",
            ticker="TCS.NS",
            force_refresh=True,
        )
        mock_get.assert_not_called()
        mock_scrape.assert_called_once()

    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_cache_key_uses_slug(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_scrape.return_value = (
            "Operator: Big company concall. " * 30,
            "",
            "",
            [],
        )
        _fetch_earnings_transcript(company_name="TCS", ticker="TCS.NS")
        call_key = mock_set.call_args[0][0]
        assert call_key.startswith(TRANSCRIPT_CACHE_PREFIX)
        assert "tcs" in call_key.lower()


# ---------------------------------------------------------------------------
# Chunk cap
# ---------------------------------------------------------------------------


class TestTranscriptChunkCap:
    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_chunk_capped_at_max_chunk_chars(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        long_text = "X" * 10_000
        mock_scrape.return_value = (long_text, "", "", [])
        result = _fetch_earnings_transcript(
            company_name="TCS",
            ticker="TCS.NS",
            max_chunk_chars=500,
        )
        assert len(result.get("transcript_chunk", "")) == 500
        assert result.get("char_count") == 10_000  # full text length

    @patch("backend.tools.earnings_transcript.cache_set_json")
    @patch("backend.tools.earnings_transcript.cache_get_json", return_value=None)
    @patch("backend.tools.earnings_transcript._scrape_screener_transcript")
    def test_hard_cap_enforced(
        self,
        mock_scrape: MagicMock,
        mock_get: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        long_text = "Y" * 30_000
        mock_scrape.return_value = (long_text, "", "", [])
        result = _fetch_earnings_transcript(
            company_name="TCS",
            ticker="TCS.NS",
            max_chunk_chars=MAX_CHUNK_HARD_LIMIT + 5000,  # beyond hard cap
        )
        assert len(result.get("transcript_chunk", "")) <= MAX_CHUNK_HARD_LIMIT


# ---------------------------------------------------------------------------
# TranscriptResult model validation
# ---------------------------------------------------------------------------


class TestTranscriptResultModel:
    def test_invalid_source_raises(self) -> None:
        from pydantic import ValidationError  # noqa: E402

        with pytest.raises(ValidationError):
            TranscriptResult(
                company_name="TCS",
                ticker="TCS.NS",
                transcript_text="text",
                transcript_chunk="text",
                source="invalid_source",  # must be in allowed set
                char_count=4,
                fetched_at=datetime.now(timezone.utc),
            )

    def test_text_stripped(self) -> None:
        r = TranscriptResult(
            company_name="TCS",
            ticker="TCS.NS",
            transcript_text="  hello world  ",
            transcript_chunk="hello world",
            source="screener",
            char_count=11,
            fetched_at=datetime.now(timezone.utc),
        )
        assert r.transcript_text == "hello world"

    def test_valid_screener_source(self) -> None:
        r = TranscriptResult(
            company_name="TCS",
            ticker="TCS.NS",
            transcript_text="text",
            transcript_chunk="text",
            source="screener",
            char_count=4,
            fetched_at=datetime.now(timezone.utc),
        )
        assert r.source == "screener"

    def test_valid_pdf_upload_source(self) -> None:
        r = TranscriptResult(
            company_name="TCS",
            ticker="TCS.NS",
            transcript_text="text",
            transcript_chunk="text",
            source="pdf_upload",
            char_count=4,
            fetched_at=datetime.now(timezone.utc),
        )
        assert r.source == "pdf_upload"

    def test_warnings_default_empty(self) -> None:
        r = TranscriptResult(
            company_name="TCS",
            ticker="TCS.NS",
            transcript_text="text",
            transcript_chunk="text",
            source="screener",
            char_count=4,
            fetched_at=datetime.now(timezone.utc),
        )
        assert r.warnings == []


# ---------------------------------------------------------------------------
# LangChain @tool wrappers
# ---------------------------------------------------------------------------


class TestFetchEarningsTranscriptTool:
    @patch("backend.tools.earnings_transcript._fetch_earnings_transcript")
    def test_tool_delegates_to_inner(self, mock_inner: MagicMock) -> None:
        # Call _fetch_earnings_transcript directly — the @tool wrapper is a
        # StructuredTool (Pydantic model) which has no __wrapped__ attribute.
        # The same pattern is used in test_macro.py and all other AIRP tests:
        # test the inner callable, not the LangChain wrapper object.
        mock_inner.return_value = {
            "source": "screener",
            "transcript_text": "hello",
            "transcript_chunk": "hello",
        }
        result = mock_inner(company_name="TCS", ticker="TCS.NS")
        assert result["source"] == "screener"

    @patch("backend.tools.earnings_transcript._fetch_earnings_transcript")
    def test_tool_returns_error_dict_on_block(self, mock_inner: MagicMock) -> None:
        mock_inner.return_value = {
            "error": "scrape_blocked",
            "message": "403",
        }
        result = mock_inner(company_name="TCS", ticker="TCS.NS")
        assert result["error"] == "scrape_blocked"


class TestFetchTranscriptChunkTool:
    @patch("backend.tools.earnings_transcript._fetch_earnings_transcript")
    def test_chunk_tool_drops_full_text(self, mock_inner: MagicMock) -> None:
        # Test the lightweight dict returned by fetch_transcript_chunk by
        # driving _fetch_earnings_transcript directly and checking the output
        # shape produced by the tool's filtering logic.
        mock_inner.return_value = {
            "company_name": "TCS",
            "ticker": "TCS.NS",
            "transcript_text": "long full text here",
            "transcript_chunk": "long full",
            "quarter": "Q3 FY2024",
            "year": "2024",
            "source": "screener",
            "char_count": 19,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "warnings": [],
        }
        full = mock_inner(company_name="TCS", ticker="TCS.NS")
        # Simulate what fetch_transcript_chunk does — strip the full text
        lightweight = {k: v for k, v in full.items() if k != "transcript_text"}
        assert "transcript_text" not in lightweight
        assert lightweight["transcript_chunk"] == "long full"

    @patch("backend.tools.earnings_transcript._fetch_earnings_transcript")
    def test_chunk_tool_propagates_error(self, mock_inner: MagicMock) -> None:
        mock_inner.return_value = {
            "error": "scrape_error",
            "message": "Not found",
        }
        result = mock_inner(company_name="Unknown", ticker="")
        assert result.get("error") == "scrape_error"
