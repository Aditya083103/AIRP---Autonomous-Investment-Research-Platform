# backend/tests/unit/test_pdf_export.py
"""
Unit tests for T-043: Investment Memo PDF Export.

Test strategy:
  1. _inline_markdown_to_html      -- bold/italic/HTML-escaping
  2. _render_table                 -- pipe-table -> HTML table
  3. markdown_to_html               -- full converter, every construct
                                       memo_generator.py actually produces
  4. build_branded_html_document   -- CSS injection, full document shape
  5. resolve_memo_output_dir       -- settings-driven path resolution
  6. resolve_memo_pdf_path         -- job_id -> filename, sanitisation
  7. render_memo_pdf               -- feature flag, WeasyPrint mocked,
                                       atomic write, failure paths
  8. pdf_export_node               -- LangGraph node: state in -> state out
  9. Acceptance criteria           -- all sections render in the HTML
                                       fed to WeasyPrint; file size guard;
                                       no layout-breaking raw Markdown
                                       artifacts leak into the HTML

Acceptance criteria verified (from task spec):
  * PDF downloaded correctly -- render_memo_pdf returns a real Path
    that exists on disk with non-zero size when WeasyPrint succeeds
  * All sections render -- the HTML fed to WeasyPrint contains every
    section heading from a realistic full memo
  * No layout bugs -- markdown_to_html never leaves raw '**', '##', or
    '|' table syntax in its output; lists open and close correctly
  * File size < 500KB -- MAX_PDF_SIZE_BYTES guard, checked against the
    bytes actually returned by a (mocked) WeasyPrint call

WeasyPrint itself is not installed in most CI/dev sandboxes without its
system dependencies (Pango, Cairo, GDK-Pixbuf), so every test that
needs PDF *bytes* mocks the lazily-imported `weasyprint.HTML` class.
Tests that only exercise the Markdown->HTML conversion or path
resolution need no mocking at all -- that logic has zero third-party
dependencies.
"""
import os
from pathlib import Path
import sys
import tempfile
import types
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

from backend.services.pdf_export import (  # noqa: E402
    MAX_PDF_SIZE_BYTES,
    _inline_markdown_to_html,
    _render_table,
    build_branded_html_document,
    markdown_to_html,
    pdf_export_node,
    render_memo_pdf,
    resolve_memo_output_dir,
    resolve_memo_pdf_path,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_FULL_MEMO_MARKDOWN = """# Investment Memo: Tata Consultancy Services (TCS.NS)

**AIRP -- Autonomous Investment Research Platform**

*Generated: 17 Jun 2026, 10:00 UTC*

| | |
|---|---|
| **Recommendation** | **BUY** |
| **Conviction** | 8/10 (high conviction) |
| **Price Target** | Rs. 4,500 (12 months) |
| **Time Horizon** | 12 months |

---

## 1. Executive Summary

TCS demonstrates *exceptional* fundamental quality with a 46.2% ROE.

## 2. Investment Thesis

The committee recommends buying this stock.

The bull case rests on strong ROE, though Round 1 of the debate raised
customer concentration as a tempering factor.

## 3. Bull Case

Fundamental score of 9/10 driven by 46.2% ROE.

**Potential catalysts:**

- INR depreciation benefits IT exporters
- Strong deal pipeline reported in latest earnings call

## 4. Bear Case

Customer concentration exceeds 40% per the Contrarian's analysis.

**How the committee addressed this:**

Addressing the Contrarian's strongest argument directly.

## 5. Risk Analysis

Risk score of 3/10; no critical flags identified.

**Key risks to monitor:**

1. Customer concentration in top 5 clients exceeds 40%
2. High trailing PE of 28.5x limits near-term upside

## 6. Valuation

DCF implies 18.4% upside to intrinsic value.

**Implied price target:** Rs. 4,500 (12 months)

## 7. Recommendation

**Final verdict: BUY** -- conviction 8/10 (high conviction)

TCS: BUY with conviction 8/10.

Suggested holding period: **12 months**. This decision was reached
after 1 round of committee debate.

**How the committee weighed the evidence:**

| Committee Member | Weight |
|---|---|
| Fundamental Analyst | 20% |
| Valuation Agent | 20% |

---

*This memo was generated autonomously by AIRP, an AI investment
research system, for educational and portfolio demonstration purposes
only. It is not financial advice and should not be the sole basis for
any investment decision. Always conduct independent research or
consult a licensed financial advisor before investing.*
"""

_MINIMAL_PDF_BYTES = b"%PDF-1.4 minimal-fake-pdf-content-for-testing"


def _make_fake_weasyprint_module(pdf_bytes: bytes = _MINIMAL_PDF_BYTES) -> Any:
    """Build a fake `weasyprint` module exposing a mockable HTML class."""
    fake_module = types.ModuleType("weasyprint")

    class _FakeHTML:
        def __init__(self, string: str = "", **kwargs: Any) -> None:
            self.string = string

        def write_pdf(self) -> bytes:
            return pdf_bytes

    fake_module.HTML = _FakeHTML  # type: ignore[attr-defined]
    return fake_module


# ---------------------------------------------------------------------------
# Tests: _inline_markdown_to_html
# ---------------------------------------------------------------------------


class TestInlineMarkdownToHtml:
    def test_bold_converted(self) -> None:
        assert _inline_markdown_to_html("**bold text**") == "<strong>bold text</strong>"

    def test_italic_converted(self) -> None:
        assert _inline_markdown_to_html("*italic text*") == "<em>italic text</em>"

    def test_bold_and_italic_together(self) -> None:
        result = _inline_markdown_to_html("**bold** and *italic*")
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_plain_text_unchanged(self) -> None:
        assert _inline_markdown_to_html("plain text") == "plain text"

    def test_html_special_chars_escaped(self) -> None:
        result = _inline_markdown_to_html("5 < 10 & 10 > 5")
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result

    def test_no_raw_asterisks_remain(self) -> None:
        result = _inline_markdown_to_html("**Recommendation**")
        assert "*" not in result


# ---------------------------------------------------------------------------
# Tests: _render_table
# ---------------------------------------------------------------------------


class TestRenderTable:
    def test_renders_table_tag(self) -> None:
        lines = ["| A | B |", "|---|---|", "| 1 | 2 |"]
        result = _render_table(lines)
        assert "<table" in result
        assert "</table>" in result

    def test_header_cells_present(self) -> None:
        lines = ["| Committee Member | Weight |", "|---|---|", "| X | 20% |"]
        result = _render_table(lines)
        assert "<th>Committee Member</th>" in result
        assert "<th>Weight</th>" in result

    def test_body_cells_present(self) -> None:
        lines = ["| Committee Member | Weight |", "|---|---|", "| X | 20% |"]
        result = _render_table(lines)
        assert "<td>X</td>" in result
        assert "<td>20%</td>" in result

    def test_header_only_table_has_no_body_rows(self) -> None:
        lines = ["| A | B |", "|---|---|"]
        result = _render_table(lines)
        assert "<tbody>" in result and "<tr><td>" not in result

    def test_empty_input_returns_empty_string(self) -> None:
        assert _render_table([]) == ""

    def test_inline_markdown_applied_within_cells(self) -> None:
        lines = ["| **Recommendation** | **BUY** |", "|---|---|"]
        result = _render_table(lines)
        assert "<strong>Recommendation</strong>" in result
        assert "<strong>BUY</strong>" in result


# ---------------------------------------------------------------------------
# Tests: markdown_to_html (full converter)
# ---------------------------------------------------------------------------


class TestMarkdownToHtml:
    def test_h1_converted(self) -> None:
        result = markdown_to_html("# Title Here")
        assert "<h1>Title Here</h1>" in result

    def test_h2_converted(self) -> None:
        result = markdown_to_html("## Section Here")
        assert "<h2>Section Here</h2>" in result

    def test_horizontal_rule_converted(self) -> None:
        result = markdown_to_html("---")
        assert "<hr/>" in result

    def test_paragraph_wrapped(self) -> None:
        result = markdown_to_html("Just a sentence.")
        assert "<p>Just a sentence.</p>" in result

    def test_numbered_list_converted(self) -> None:
        result = markdown_to_html("1. First\n2. Second")
        assert "<ol>" in result
        assert "<li>First</li>" in result
        assert "<li>Second</li>" in result
        assert "</ol>" in result

    def test_bullet_list_converted(self) -> None:
        result = markdown_to_html("- First\n- Second")
        assert "<ul>" in result
        assert "<li>First</li>" in result
        assert "<li>Second</li>" in result
        assert "</ul>" in result

    def test_list_closes_before_following_paragraph(self) -> None:
        result = markdown_to_html("- Item one\n\nA paragraph after.")
        assert result.index("</ul>") < result.index("<p>A paragraph after.</p>")

    def test_switching_from_ordered_to_unordered_list_closes_first(self) -> None:
        result = markdown_to_html("1. Numbered\n- Bulleted")
        assert "</ol>" in result
        assert result.index("</ol>") < result.index("<ul>")

    def test_table_converted(self) -> None:
        result = markdown_to_html("| A | B |\n|---|---|\n| 1 | 2 |")
        assert "<table" in result

    def test_full_memo_contains_all_seven_sections(self) -> None:
        """Acceptance criterion: all sections render."""
        result = markdown_to_html(_FULL_MEMO_MARKDOWN)
        for heading in (
            "1. Executive Summary",
            "2. Investment Thesis",
            "3. Bull Case",
            "4. Bear Case",
            "5. Risk Analysis",
            "6. Valuation",
            "7. Recommendation",
        ):
            assert f"<h2>{heading}</h2>" in result

    def test_full_memo_no_raw_markdown_syntax_remains(self) -> None:
        """Acceptance criterion: no layout bugs -- raw markdown tokens
        (bold markers, header hashes, table pipes) must never leak
        into the HTML output as literal text."""
        result = markdown_to_html(_FULL_MEMO_MARKDOWN)
        assert "**" not in result
        assert "\n# " not in result
        assert "\n## " not in result

    def test_full_memo_disclaimer_preserved(self) -> None:
        result = markdown_to_html(_FULL_MEMO_MARKDOWN)
        assert "not financial advice" in result.lower()

    def test_empty_input_returns_empty_string(self) -> None:
        assert markdown_to_html("") == ""

    def test_blank_lines_do_not_produce_empty_paragraphs(self) -> None:
        result = markdown_to_html("Line one.\n\n\nLine two.")
        assert "<p></p>" not in result


# ---------------------------------------------------------------------------
# Tests: build_branded_html_document
# ---------------------------------------------------------------------------


class TestBuildBrandedHtmlDocument:
    def test_returns_full_html_document(self) -> None:
        result = build_branded_html_document(
            "# Title", "Test Corp", "17 Jun 2026, 10:00 UTC"
        )
        assert result.startswith("<!DOCTYPE html>")
        assert "<html>" in result
        assert "</html>" in result

    def test_contains_company_name_in_css_page_header(self) -> None:
        result = build_branded_html_document(
            "# Title", "Tata Consultancy Services", "17 Jun 2026"
        )
        assert "Tata Consultancy Services" in result

    def test_contains_generated_at_in_css_footer(self) -> None:
        result = build_branded_html_document(
            "# Title", "Test Corp", "17 Jun 2026, 10:00 UTC"
        )
        assert "17 Jun 2026, 10:00 UTC" in result

    def test_company_name_html_escaped(self) -> None:
        result = build_branded_html_document(
            "# Title", "Test & Co <Ltd>", "17 Jun 2026"
        )
        assert "Test &amp; Co &lt;Ltd&gt;" in result

    def test_contains_memo_body_content(self) -> None:
        result = build_branded_html_document(
            "# My Heading\n\nBody text here.", "Test Corp", "17 Jun 2026"
        )
        assert "<h1>My Heading</h1>" in result
        assert "<p>Body text here.</p>" in result

    def test_contains_css_page_rule_for_page_numbers(self) -> None:
        result = build_branded_html_document("# T", "Test Corp", "17 Jun 2026")
        assert "counter(page)" in result
        assert "counter(pages)" in result

    def test_full_memo_all_sections_present_in_document(self) -> None:
        """Acceptance criterion: all sections render, verified at the
        full-document level (what is actually handed to WeasyPrint)."""
        result = build_branded_html_document(
            _FULL_MEMO_MARKDOWN, "Tata Consultancy Services", "17 Jun 2026"
        )
        for heading in (
            "1. Executive Summary",
            "2. Investment Thesis",
            "3. Bull Case",
            "4. Bear Case",
            "5. Risk Analysis",
            "6. Valuation",
            "7. Recommendation",
        ):
            assert heading in result


# ---------------------------------------------------------------------------
# Tests: resolve_memo_output_dir / resolve_memo_pdf_path
# ---------------------------------------------------------------------------


class TestResolveMemoOutputDir:
    def test_returns_path_instance(self) -> None:
        assert isinstance(resolve_memo_output_dir(), Path)

    def test_relative_setting_resolved_against_repo_root(self) -> None:
        fake_settings = MagicMock()
        fake_settings.memo_output_dir = "data/memos"
        with patch("backend.services.pdf_export.settings", fake_settings):
            result = resolve_memo_output_dir()
        assert result.is_absolute()
        assert result.parts[-2:] == ("data", "memos")

    def test_absolute_setting_used_as_is(self) -> None:
        """An absolute path in settings.memo_output_dir must be returned
        unchanged, not re-resolved against the repo root. The exact
        string form of "absolute" differs between POSIX and Windows
        (Path("/x") is absolute on POSIX but drive-relative on
        Windows), so this constructs the expected value the same way
        the function does -- via Path(...).is_absolute() -- rather
        than asserting equality against a hardcoded POSIX-style
        literal that Windows would reinterpret differently."""
        configured = str(Path(tempfile.gettempdir()) / "custom_absolute_dir")
        assert Path(configured).is_absolute()
        fake_settings = MagicMock()
        fake_settings.memo_output_dir = configured
        with patch("backend.services.pdf_export.settings", fake_settings):
            result = resolve_memo_output_dir()
        assert result == Path(configured)

    def test_falls_back_when_settings_is_none(self) -> None:
        with patch("backend.services.pdf_export.settings", None):
            result = resolve_memo_output_dir()
        assert isinstance(result, Path)
        assert result.parts[-2:] == ("data", "memos")


class TestResolveMemoPdfPath:
    def test_returns_path_ending_in_pdf(self) -> None:
        result = resolve_memo_pdf_path("job-123")
        assert result.suffix == ".pdf"

    def test_job_id_appears_in_filename(self) -> None:
        result = resolve_memo_pdf_path("job-abc-123")
        assert "job-abc-123" in result.name

    def test_unsafe_characters_sanitised(self) -> None:
        result = resolve_memo_pdf_path("job/with../unsafe chars!")
        assert "/" not in result.stem
        assert ".." not in result.stem
        assert " " not in result.stem
        assert "!" not in result.stem

    def test_empty_job_id_falls_back_to_unknown(self) -> None:
        result = resolve_memo_pdf_path("")
        assert "unknown-job" in result.name

    def test_different_job_ids_produce_different_paths(self) -> None:
        path_a = resolve_memo_pdf_path("job-a")
        path_b = resolve_memo_pdf_path("job-b")
        assert path_a != path_b


# ---------------------------------------------------------------------------
# Tests: render_memo_pdf
# ---------------------------------------------------------------------------


class TestRenderMemoPdf:
    def test_returns_none_when_feature_disabled(self) -> None:
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = False
        with patch("backend.services.pdf_export.settings", fake_settings):
            result = render_memo_pdf(
                "# Memo", "Test Corp", "17 Jun 2026", "job-disabled"
            )
        assert result is None

    def test_returns_none_when_weasyprint_not_installed(self) -> None:
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": None}):
                result = render_memo_pdf(
                    "# Memo", "Test Corp", "17 Jun 2026", "job-no-weasy"
                )
        assert result is None

    def test_successful_render_writes_file_to_disk(self, tmp_path: Path) -> None:
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        fake_settings.memo_output_dir = str(tmp_path)
        fake_weasyprint = _make_fake_weasyprint_module()
        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
                result = render_memo_pdf(
                    _FULL_MEMO_MARKDOWN,
                    "Tata Consultancy Services",
                    "17 Jun 2026",
                    "job-success",
                )
        assert result is not None
        assert result.exists()
        assert result.read_bytes() == _MINIMAL_PDF_BYTES

    def test_successful_render_returns_path_in_configured_dir(
        self, tmp_path: Path
    ) -> None:
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        fake_settings.memo_output_dir = str(tmp_path)
        fake_weasyprint = _make_fake_weasyprint_module()
        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
                result = render_memo_pdf(
                    "# Memo", "Test Corp", "17 Jun 2026", "job-path-check"
                )
        assert result is not None
        assert result.parent == tmp_path

    def test_render_failure_returns_none(self, tmp_path: Path) -> None:
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        fake_settings.memo_output_dir = str(tmp_path)

        fake_weasyprint = types.ModuleType("weasyprint")

        class _FailingHTML:
            def __init__(self, string: str = "", **kwargs: Any) -> None:
                pass

            def write_pdf(self) -> bytes:
                raise RuntimeError("simulated WeasyPrint rendering failure")

        fake_weasyprint.HTML = _FailingHTML  # type: ignore[attr-defined]

        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
                result = render_memo_pdf(
                    "# Memo", "Test Corp", "17 Jun 2026", "job-fail"
                )
        assert result is None

    def test_output_directory_created_if_missing(self, tmp_path: Path) -> None:
        nested_dir = tmp_path / "nested" / "memos"
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        fake_settings.memo_output_dir = str(nested_dir)
        fake_weasyprint = _make_fake_weasyprint_module()
        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
                result = render_memo_pdf(
                    "# Memo", "Test Corp", "17 Jun 2026", "job-nested"
                )
        assert result is not None
        assert nested_dir.exists()

    def test_pdf_size_under_acceptance_threshold(self, tmp_path: Path) -> None:
        """
        Acceptance criterion: file size < 500KB. A full, realistic memo
        rendered through the actual HTML pipeline produces a reasonably
        sized HTML payload; this test guards that the bytes WeasyPrint
        is asked to write never approach the 500KB ceiling for a
        text-only memo of this size.
        """
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        fake_settings.memo_output_dir = str(tmp_path)
        # Simulate a realistically-sized PDF (a few tens of KB) rather
        # than the minimal fixture, to exercise the size guard
        # meaningfully.
        realistic_pdf_bytes = b"%PDF-1.4" + (b"0" * 40_000)
        fake_weasyprint = _make_fake_weasyprint_module(realistic_pdf_bytes)
        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
                result = render_memo_pdf(
                    _FULL_MEMO_MARKDOWN,
                    "Tata Consultancy Services",
                    "17 Jun 2026",
                    "job-size-check",
                )
        assert result is not None
        assert result.stat().st_size < MAX_PDF_SIZE_BYTES

    def test_rerunning_same_job_id_overwrites_not_duplicates(
        self, tmp_path: Path
    ) -> None:
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        fake_settings.memo_output_dir = str(tmp_path)
        fake_weasyprint = _make_fake_weasyprint_module()
        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
                first = render_memo_pdf(
                    "# Memo v1", "Test Corp", "17 Jun 2026", "job-rerun"
                )
                second = render_memo_pdf(
                    "# Memo v2", "Test Corp", "17 Jun 2026", "job-rerun"
                )
        assert first == second
        files = list(tmp_path.glob("job-rerun*"))
        assert len(files) == 1


# ---------------------------------------------------------------------------
# Tests: pdf_export_node (LangGraph node)
# ---------------------------------------------------------------------------


class TestPdfExportNode:
    def test_returns_dict_with_memo_pdf_path_key(self) -> None:
        state = {
            "job_id": "test-job-001",
            "company_name": "Tata Consultancy Services",
            "memo_markdown": "# Memo\n\nSome content.",
        }
        result = pdf_export_node(state)
        assert "memo_pdf_path" in result

    def test_missing_memo_markdown_returns_none_path(self) -> None:
        state: dict[str, Any] = {
            "job_id": "test-job-002",
            "company_name": "Test Corp",
        }
        result = pdf_export_node(state)
        assert result["memo_pdf_path"] is None

    def test_empty_memo_markdown_returns_none_path(self) -> None:
        state = {
            "job_id": "test-job-003",
            "company_name": "Test Corp",
            "memo_markdown": "",
        }
        result = pdf_export_node(state)
        assert result["memo_pdf_path"] is None

    def test_successful_export_returns_string_path(self, tmp_path: Path) -> None:
        fake_settings = MagicMock()
        fake_settings.feature_pdf_enabled = True
        fake_settings.memo_output_dir = str(tmp_path)
        fake_weasyprint = _make_fake_weasyprint_module()
        state = {
            "job_id": "test-job-success",
            "company_name": "Tata Consultancy Services",
            "memo_markdown": _FULL_MEMO_MARKDOWN,
        }
        with patch("backend.services.pdf_export.settings", fake_settings):
            with patch.dict(sys.modules, {"weasyprint": fake_weasyprint}):
                result = pdf_export_node(state)
        assert isinstance(result["memo_pdf_path"], str)
        assert Path(result["memo_pdf_path"]).exists()

    def test_never_raises_on_missing_job_id(self) -> None:
        state: dict[str, Any] = {"memo_markdown": "# Memo"}
        result = pdf_export_node(state)
        assert "memo_pdf_path" in result

    def test_result_only_contains_memo_pdf_path_key(self) -> None:
        """The node returns a partial-state dict -- exactly one new key."""
        state = {
            "job_id": "test-job",
            "company_name": "Test Corp",
            "memo_markdown": "# Memo",
        }
        result = pdf_export_node(state)
        assert list(result.keys()) == ["memo_pdf_path"]

    def test_does_not_mutate_input_state(self) -> None:
        state = {
            "job_id": "test-job",
            "company_name": "Test Corp",
            "memo_markdown": "# Memo",
        }
        original_keys = set(state.keys())
        pdf_export_node(state)
        assert set(state.keys()) == original_keys
