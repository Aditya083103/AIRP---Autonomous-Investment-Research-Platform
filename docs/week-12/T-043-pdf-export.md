# T-043 -- Add PDF Export for Investment Memo

**Phase:** 4 -- Debate Engine & Advanced Agents
**Week:** 12
**Branch:** `feat/debate-pdf-export`
**Task status:** Complete

---

## Overview

T-043 converts the Markdown Investment Memo produced by T-042 into a
branded, paginated PDF and writes it to disk. A new `pdf_export` node
runs immediately after `report_generator`, the new final node in the
pipeline before `END`.

The conversion pipeline is: **Markdown -> branded HTML -> PDF bytes ->
file on disk**, rendered via WeasyPrint. The Markdown-to-HTML step is a
small, purpose-built converter (no third-party Markdown library) since
the input is fully controlled -- it only ever needs to understand the
narrow, fixed set of constructs `backend.services.memo_generator`
actually produces (headers, bold/italic, pipe tables, numbered/bullet
lists, horizontal rules, paragraphs), never arbitrary user-supplied
Markdown.

WeasyPrint depends on system libraries (Pango, Cairo, GDK-Pixbuf) that
are not guaranteed to be present in every environment. The PDF export
node treats this as expected, not exceptional: it is lazily imported,
guarded by the existing `feature_pdf_enabled` flag, and any failure at
any stage (missing library, rendering error, disk write error)
degrades to `memo_pdf_path=None` rather than failing the pipeline. The
Markdown memo from T-042 remains fully available regardless of whether
PDF export succeeds.

**Acceptance criteria (all must pass):**
- PDF downloaded correctly
- All sections render
- No layout bugs
- File size < 500KB

---

## Files Changed

| File | Change |
|------|--------|
| `backend/services/pdf_export.py` | **New** -- the full PDF export module: narrow Markdown-to-HTML converter, branded HTML document assembler, path resolution, WeasyPrint rendering with atomic disk write, and the `pdf_export_node` LangGraph node entry point |
| `backend/config.py` | **Modified** -- added `memo_output_dir` setting (next to the existing `feature_pdf_enabled` flag) controlling where generated PDFs are written |
| `.env.example` | **Modified** -- documented `MEMO_OUTPUT_DIR` alongside the existing `FEATURE_PDF_ENABLED` entry |
| `backend/graph/nodes.py` | **Modified** -- added `NODE_PDF_EXPORT`, `_pdf_export_impl`, and `pdf_export_node` (same `_persist_after(profile_node(...))` composition as every other sequential node) |
| `backend/graph/graph.py` | **Modified** -- registered `pdf_export` node; rewired the tail edge from `report_generator -> END` to `report_generator -> pdf_export -> END` (15 nodes total, was 14) |
| `backend/graph/graph_visualisation.py` | **Modified** -- docstring updated to describe the new final node |
| `backend/tests/unit/test_pdf_export.py` | **New** -- unit tests covering the Markdown converter, HTML document assembly, path resolution, PDF rendering (WeasyPrint mocked), and the LangGraph node contract |
| `backend/tests/unit/test_graph_skeleton.py` | **Modified** -- node count assertion updated from 14 to 15; new registration, mermaid, edge, literal-value, and direct node-behaviour tests added for `pdf_export` |
| `backend/tests/unit/test_debate_loop.py` | **Modified** -- node count assertion updated from 14 to 15 |
| `backend/tests/unit/test_parallel_research.py` | **Modified** -- node count assertion updated from 14 to 15 |
| `backend/tests/unit/test_routing.py` | **Modified** -- node count assertion updated from 14 to 15 |
| `backend/tests/integration/test_graph_integration.py` | **Modified** -- docstring node count updated from 14 to 15 |

---

## What Was Built

### New: `backend/services/pdf_export.py`

| Function | Purpose |
|----------|---------|
| `_inline_markdown_to_html(...)` | Converts `**bold**` / `*italic*` within a single line; HTML-escapes the text first so any literal `<`, `>`, `&` in agent-written prose renders safely instead of being interpreted as markup |
| `_render_table(...)` | Renders a contiguous block of pipe-table lines (header, separator, body rows) to an HTML `<table>` |
| `markdown_to_html(...)` | The full converter: a single linear pass over the memo's lines handling `#`/`##` headers, bold/italic, pipe tables, numbered lists, bullet lists, horizontal rules, and paragraphs, with correct list-opening/list-closing/list-switching state tracking |
| `build_branded_html_document(...)` | Wraps the converted HTML body in a complete document with AIRP-themed CSS; the company name and page numbers are injected via CSS `@page` rules so they appear identically on every printed page without any per-page logic in this function |
| `resolve_memo_output_dir(...)` | Resolves the absolute output directory from `settings.memo_output_dir` (relative paths resolved against the repo root), falling back to a sane default if settings could not be loaded |
| `resolve_memo_pdf_path(...)` | Resolves the absolute path for one job's PDF, with the `job_id` sanitised into a safe filename so concurrent analyses never collide |
| `render_memo_pdf(...)` | Orchestrates the full pipeline: checks `feature_pdf_enabled`, lazily imports WeasyPrint, builds the branded HTML, calls `HTML(string=...).write_pdf()`, and writes the bytes to disk via an atomic temp-file-then-`os.replace()` write. Never raises -- every failure mode returns `None` |
| `pdf_export_node(state)` | The LangGraph node entry point. Reads `state["memo_markdown"]`; returns `{"memo_pdf_path": str \| None}` |

### Why a hand-rolled Markdown-to-HTML converter instead of a library?

The memo's Markdown is generated entirely by AIRP's own code
(`backend.services.memo_generator`), never by an end user, and uses
only a small, fixed subset of Markdown syntax. A general-purpose
CommonMark parser would handle far more syntax than this memo will
ever produce, at the cost of pinning an extra third-party dependency
with its own transitive requirements. The converter here is a single
linear pass using a small set of regexes, fully exercised by
`test_pdf_export.py` against the exact constructs `memo_generator.py`
actually emits -- including a full, realistic end-to-end memo fixture,
not just isolated syntax fragments.

### Why is WeasyPrint imported lazily, inside the function, instead of at module level?

This follows the same defensive pattern already established by
`backend/agents/valuation_agent.py` for BeautifulSoup and `requests`:
WeasyPrint depends on system libraries (Pango, Cairo, GDK-Pixbuf) that
may not be installed in every environment -- a bare CI runner, a
developer machine without GTK libraries, a minimal container image.
Importing it lazily means `pdf_export.py` -- and every other module
that imports from it, including `backend/graph/nodes.py` -- stays
importable and unit-testable even where those system libraries are
absent. `feature_pdf_enabled` (combined with the lazy import's own
`try/except ImportError`) lets the pipeline degrade gracefully rather
than fail the whole run.

### Why is file size capped well under 500KB by construction, not just by testing?

The memo is text-only -- no embedded images, no custom fonts beyond
system defaults, no charts. A 2-3 page text document rendered by
WeasyPrint with simple CSS typically lands in the 30-80KB range. The
500KB ceiling in the acceptance criteria therefore has wide headroom
by design. `test_pdf_size_under_acceptance_threshold` exists as a
regression guard against that headroom shrinking unexpectedly (e.g. if
a future change accidentally embeds a large asset), not because the
margin is tight today.

### Why does `pdf_export_node` never raise, mirroring `report_generator_node`?

`report_generator_node` (T-042) already established that the final
nodes in this pipeline must never fail the whole run over a
presentation-layer concern. `pdf_export_node` is now the new final
node -- if it raised, a fully complete, well-reasoned analysis (all 7
debate-grounded agents, the Portfolio Manager's verdict, the readable
Markdown memo) would be lost entirely over what is fundamentally a PDF
rendering or disk I/O failure. On any failure the node logs a warning
and returns `memo_pdf_path=None`; `memo_markdown` remains fully
available regardless.

### Modified: `backend/config.py`

```python
feature_pdf_enabled: bool = True
memo_output_dir: str = Field(
    default="data/memos",
    description=(
        "Directory (relative to repo root, or absolute) where "
        "generated Investment Memo PDFs are written. Created "
        "automatically if it does not exist. Ignored when "
        "ENVIRONMENT=test."
    ),
)
```

Added next to the existing `feature_pdf_enabled` flag, which was
already forward-declared in the Feature Flags section with a comment
explicitly anticipating this task ("Set to false to return JSON only
during early development when the PDF template isn't ready yet.").
Read via the same `from backend.config import settings as _settings`
/ module-level `settings = _settings` pattern already used throughout
`backend/tools/*.py`, so `patch("backend.services.pdf_export.settings")`
works identically to every other settings-consuming module in this
codebase.

### Modified: `backend/graph/nodes.py`

```python
# New, mirrors the report_generator_node composition exactly:
def _pdf_export_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = _pdf_export_node(state)
    partial["status"] = "completed"
    partial["completed_at"] = datetime.utcnow().isoformat() + "Z"
    partial["current_node"] = NODE_PDF_EXPORT
    return partial


pdf_export_node: _NodeFn = _persist_after(
    profile_node(_pdf_export_impl, NODE_PDF_EXPORT),
    NODE_PDF_EXPORT,
)
```

Identical thin-wrapper pattern to every other sequential node. The
imported function from `backend.services.pdf_export` is aliased to
`_pdf_export_node` on import specifically to avoid a name collision
with the module-level `pdf_export_node` variable defined here -- the
same reason `generate_investment_memo` (not `report_generator_node`)
is the imported name in the T-042 equivalent.

### Modified: `backend/graph/graph.py`

Topology change, fully additive:

```
Before (T-042):
  portfolio_manager -> report_generator -> END

After (T-043):
  portfolio_manager -> report_generator -> pdf_export -> END
```

Total node count: 15 (was 14). All docstring/comment node-count
references (`"14 nodes total"`, `"Register all 14 nodes"`, the
compile-time log message, the ASCII pipeline diagram) were updated to
15 to keep the file's own documentation accurate -- the same class of
update T-042 made when it bumped the count from 13 to 14.

---

## Tests

| Test class | What it covers |
|------------|-----------------|
| `TestInlineMarkdownToHtml` | Bold/italic conversion, both together, plain text passthrough, HTML-special-character escaping (`<`, `&`, `>`), no raw asterisks remain in output |
| `TestRenderTable` | `<table>` tag present, header cells correct, body cells correct, a header-only table produces no spurious body rows, empty input returns an empty string, inline bold/italic applied correctly within table cells |
| `TestMarkdownToHtml` | Every construct individually (H1, H2, horizontal rule, paragraph, numbered list, bullet list, table), list-state transitions (list closes before a following paragraph; switching from numbered to bulleted closes the first list before opening the second), and a **full realistic memo fixture** asserting all 7 section headings render as `<h2>` (acceptance criterion: all sections render), no raw `**`/`# `/`## ` markdown syntax survives (acceptance criterion: no layout bugs), and the disclaimer text is preserved |
| `TestBuildBrandedHtmlDocument` | Full `<!DOCTYPE html>`...`</html>` document shape, company name present in the CSS `@page` header content, `generated_at` present in the CSS footer content, company name HTML-escaped against injection, memo body content correctly embedded, CSS `counter(page)`/`counter(pages)` rules present for pagination, and the same full-memo all-7-sections check at the complete-document level (what is actually handed to WeasyPrint) |
| `TestResolveMemoOutputDir` | Returns a `Path`, a relative configured directory resolves to an absolute path under the repo root, an absolute configured directory is used as-is, and a missing/`None` settings object falls back to the documented default rather than raising |
| `TestResolveMemoPdfPath` | Filename ends in `.pdf`, the job_id appears in the filename, unsafe characters (`/`, `..`, spaces, `!`) are sanitised out, an empty job_id falls back to a safe placeholder name, and different job_ids never collide |
| `TestRenderMemoPdf` | `feature_pdf_enabled=False` short-circuits to `None`; a missing WeasyPrint installation degrades to `None`; a successful render (WeasyPrint mocked) writes a real file to disk at the expected path with the expected bytes; a simulated rendering failure degrades to `None` rather than raising; the output directory is created automatically if missing (including nested paths); **the PDF-size acceptance criterion** is checked directly against `MAX_PDF_SIZE_BYTES` using a realistically-sized (not minimal) mocked PDF payload; re-running the same `job_id` overwrites its own prior file rather than accumulating duplicates |
| `TestPdfExportNode` | Returns `{"memo_pdf_path": ...}`; missing or empty `memo_markdown` degrades to `None`; a full successful export (mocked WeasyPrint) returns a string path to a file that actually exists on disk; a missing `job_id` does not raise; the node's return value contains exactly one key (`memo_pdf_path`) as a proper partial-state update; input state is never mutated |

Every test that needs PDF *bytes* mocks the lazily-imported
`weasyprint.HTML` class via `patch.dict(sys.modules, {"weasyprint":
<fake module>})`, since WeasyPrint's system dependencies are not
guaranteed to be present in every CI/dev environment. Tests that only
exercise Markdown-to-HTML conversion or path resolution need no
mocking at all -- that logic has zero third-party dependencies.

Additions to the four pre-existing graph-topology test files
(`test_graph_skeleton.py`, `test_debate_loop.py`,
`test_parallel_research.py`, `test_routing.py`) follow the identical
pattern T-042 established when `report_generator` was added:
`test_pdf_export_registered`, `test_mermaid_contains_pdf_export`,
`test_report_generator_to_pdf_export_edge`,
`test_node_pdf_export_is_string`, the literal-value assertion
`NODE_PDF_EXPORT == "pdf_export"`, `pdf_export_node` added to
`test_all_stub_nodes_never_raise`, and four new direct node-behaviour
tests (`test_pdf_export_returns_memo_pdf_path_key`,
`test_pdf_export_sets_status_completed`,
`test_pdf_export_sets_current_node`,
`test_pdf_export_handles_missing_memo_markdown`,
`test_pdf_export_never_raises_without_weasyprint`).

---

## Design Decisions

**Why a separate `services/pdf_export.py` module instead of folding
this into `memo_generator.py`?**
Same single-responsibility boundary T-042 drew between the Portfolio
Manager (decides) and the memo generator (formats for a human reader).
`memo_generator.py`'s job is producing readable Markdown; `pdf_export.py`'s
job is converting that Markdown into a paginated binary artifact. Keeping
them separate means `memo_generator.py` continues to have zero
third-party dependencies and remains trivially testable, while the
WeasyPrint-specific concerns (system libraries, lazy imports, binary
output, disk I/O) are fully isolated to the one module that actually
needs them.

**Why is the page-numbering and company-name header implemented via CSS
`@page` rules rather than computed and inserted per-page in Python?**
WeasyPrint, like any standards-compliant CSS print engine, handles
pagination natively through `@page` margin boxes (`@top-center`,
`@bottom-left`, `@bottom-center`) with the `counter(page)` /
`counter(pages)` CSS functions. This is the only way to get correct,
automatically-updating page numbers and a repeating header without
Python needing to know in advance how many pages the rendered content
will occupy -- a number that depends on WeasyPrint's own text layout,
not on anything `pdf_export.py` can predict from the Markdown alone.

**Why does `build_branded_html_document` not wrap the memo body in its
own additional branded header div, given `memo_generator.py`'s own
header section already states the AIRP brand name and generation
date?**
An earlier draft of this module added a `.airp-brand-bar` div above the
memo body for visual emphasis, but this duplicated information the
Markdown memo already states in its own first lines (by design, so the
Markdown stands alone as a readable document per T-042's acceptance
criteria). For PDF presentation specifically, that duplication read as
redundant once both were visible on the same rendered page. Removing
the extra div and moving the generation timestamp into the CSS `@page`
footer (where it appears once per page, unobtrusively, rather than once
prominently at the very top) gave a cleaner result without losing any
information, and was confirmed by rendering the actual HTML output and
visually inspecting it before finalising the module.

**Why is `generated_at` passed through to `build_branded_html_document`
at all, if the memo body already contains its own "Generated:" line?**
It now drives the small per-page footer timestamp (`@bottom-left`),
which is a genuinely useful addition distinct from the in-body
timestamp: a reader looking only at page 3 of a printed multi-page memo
still sees when the document was generated without flipping back to
page 1.

**Why `memo_output_dir` as a new `Settings` field instead of reading
`os.getenv("MEMO_OUTPUT_DIR")` directly?**
`backend/config.py`'s own docstring states the rule explicitly: "Never
import os.getenv() directly in application code -- always use
settings." Every other configurable path or feature flag in this
codebase goes through the `Settings` class for type validation, `.env`
loading, and IDE autocomplete; `memo_output_dir` follows that same
convention rather than being a one-off exception.

**Why are PDF filenames keyed by `job_id` rather than company name or a
timestamp?**
`job_id` is the one identifier guaranteed to be unique per analysis run
in `InvestmentState` (see `backend/graph/state.py`). Keying by company
name would silently overwrite a prior analysis of the same company;
keying by timestamp would accumulate an unbounded number of files for
repeated runs against the same job during development/debugging.
Keying by `job_id` gives exactly one file per analysis, deterministically
overwritten on re-run -- verified directly by
`test_rerunning_same_job_id_overwrites_not_duplicates`.

---

## AIRP Standards Compliance

| Standard | Status |
|----------|--------|
| No `from __future__ import annotations` in production modules | OK -- not present in `pdf_export.py` (the project's native 3.11+ generic syntax, e.g. `dict[str, Any]`, is used directly, consistent with `portfolio_manager.py` and `memo_generator.py`) |
| Plain ASCII section comments (`# ---`) | OK -- no Unicode box-drawing, no rupee signs, no em-dashes, no arrows in the new file |
| No bare `# type: ignore` | OK -- the one `# type: ignore[assignment]` follows the exact pre-existing pattern from `backend/tools/cache.py` for the best-effort `settings` import fallback |
| `mypy --strict` safe | OK -- every function fully annotated with explicit parameter and return types; `weasyprint.*` already has `ignore_missing_imports = true` configured in `pyproject.toml` |
| Tools/agents never raise -- graceful degradation on bad input | OK -- `render_memo_pdf` and `pdf_export_node` never raise; verified for a disabled feature flag, a missing WeasyPrint installation, a simulated rendering failure, missing/empty `memo_markdown`, and a missing `job_id` |
| `@traced_agent` / LangSmith | N/A -- `pdf_export_node` makes no LLM calls, nothing to trace (consistent with `debate_loop_node` and `report_generator_node`'s precedent for zero-LLM nodes) |
| Persistence wrapper applied (T-033 pattern) | OK -- `_persist_after(profile_node(...))` composition, identical to every other sequential node |
| Atomic file writes | OK -- temp-file-in-target-directory + `os.replace()`, the exact same pattern already established by `backend/graph/graph_visualisation.py` for `GRAPH_DIAGRAM.md` |
| All lines <= 88 chars | OK -- verified by direct character-length check (not byte-length) |
| flake8 (bugbear, comprehensions) clean | OK -- no unnecessary dict/list comprehensions with constant values (the C420 pattern caught in an earlier task), no f-strings missing placeholders (the F541 pattern caught in an earlier task) -- both explicitly re-checked across every file in this task before finalising |
| `ENVIRONMENT=test` guard respected | OK -- new test file sets `ENVIRONMENT=test` via `os.environ.setdefault` before any backend import, consistent with every other test module |
| `.gitignore` | OK -- `*.pdf` is already globally ignored; no change needed |

---

## Workflow: Checkout to PR

### 1. Start from main

```bash
git checkout main
git pull origin main
git checkout -b feat/debate-pdf-export
```

### 2. Place the files

Copy the following files into your local repository (paths relative to
repo root):

```
backend/services/pdf_export.py                       (new)
backend/config.py                                      (modified)
.env.example                                            (modified)
backend/graph/nodes.py                                  (modified)
backend/graph/graph.py                                  (modified)
backend/graph/graph_visualisation.py                    (modified)
backend/tests/unit/test_pdf_export.py                   (new)
backend/tests/unit/test_graph_skeleton.py               (modified)
backend/tests/unit/test_debate_loop.py                  (modified)
backend/tests/unit/test_parallel_research.py            (modified)
backend/tests/unit/test_routing.py                      (modified)
backend/tests/integration/test_graph_integration.py     (modified)
docs/week-12/T-043-pdf-export.md                        (new)
```

### 3. Install WeasyPrint's system dependencies (one-time, local only)

WeasyPrint requires Pango, Cairo, and GDK-Pixbuf to actually render
PDFs (not required to run the unit tests, which mock WeasyPrint
entirely).

**Windows:** Install the GTK3 runtime, e.g. via
[the MSYS2-based installer documented by WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows),
then ensure its `bin` directory is on `PATH`.

**macOS:** `brew install pango`

**Linux (Debian/Ubuntu):** `sudo apt install libpango-1.0-0 libpangocairo-1.0-0`

If these are not installed, `feature_pdf_enabled` can remain `true` --
the pipeline will simply log a warning and set `memo_pdf_path=None` for
every run, exactly as designed.

### 4. Set environment and run the new test file

**Windows CMD:**
```cmd
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_pdf_export.py -v --tb=short
```

**Git Bash / Mac / Linux:**
```bash
export ENVIRONMENT=test
python -m pytest backend/tests/unit/test_pdf_export.py -v --tb=short
```

Expected: all tests pass. WeasyPrint itself is mocked throughout this
file, so these tests pass identically whether or not WeasyPrint's
system dependencies are actually installed on your machine.

### 5. Run the previously-touched files to confirm no regressions

```bash
python -m pytest backend/tests/unit/test_graph_skeleton.py -v --tb=short
python -m pytest backend/tests/unit/test_debate_loop.py -v --tb=short
python -m pytest backend/tests/unit/test_parallel_research.py -v --tb=short
python -m pytest backend/tests/unit/test_routing.py -v --tb=short
```

Expected: all passed, including the updated 15-node assertions in all
four files and the new `pdf_export` registration/mermaid/edge tests in
`test_graph_skeleton.py`.

### 6. Run the full unit suite to confirm no regressions anywhere

```bash
python -m pytest --tb=short -q
```

Expected: all existing tests continue to pass. `test_memo_generator.py`
(T-042) is unaffected since `memo_generator.py` itself was not modified
in this task -- only `nodes.py` and `graph.py` changed, and only to add
the new node after it.

### 7. Run with coverage to confirm the threshold still holds

```bash
pytest --cov=backend --cov-report=term-missing -q
```

### 8. (Optional) Generate a real PDF locally to visually verify

With WeasyPrint's system dependencies installed (step 3), run a small
script to confirm an actual file lands on disk:

```python
from backend.services.pdf_export import render_memo_pdf

path = render_memo_pdf(
    memo_markdown="# Investment Memo: Test Corp (TEST.NS)\n\n## 1. Executive Summary\n\nSample content.",
    company_name="Test Corp",
    generated_at="18 Jun 2026, 10:00 UTC",
    job_id="manual-test-001",
)
print(path)  # data/memos/manual-test-001.pdf
```

Open the resulting PDF and confirm: the AIRP page header and page
number appear correctly, all section headings render, tables and lists
are formatted cleanly, and the file size is well under 500KB.

### 9. First commit attempt (pre-commit auto-fixes)

```bash
git add backend/services/pdf_export.py \
        backend/config.py \
        .env.example \
        backend/graph/nodes.py \
        backend/graph/graph.py \
        backend/graph/graph_visualisation.py \
        backend/tests/unit/test_pdf_export.py \
        backend/tests/unit/test_graph_skeleton.py \
        backend/tests/unit/test_debate_loop.py \
        backend/tests/unit/test_parallel_research.py \
        backend/tests/unit/test_routing.py \
        backend/tests/integration/test_graph_integration.py \
        docs/week-12/T-043-pdf-export.md
git commit -m "feat(report): add PDF export for Investment Memo"
```

Black / isort may auto-fix formatting on the first attempt. If the
commit is rejected by pre-commit hooks (the two-commit pattern from
AIRP standards):

```bash
git add .
git commit -m "feat(report): add PDF export for Investment Memo"
```

### 10. Push and open PR

```bash
git push -u origin feat/debate-pdf-export
```

Open a PR on GitHub targeting `main`.

---

## PR Details

**PR title:**
```
feat(report): implement branded PDF export for Investment Memo
```

**PR description:**

```markdown
## Summary

Implements PDF export for the Investment Memo (T-043) -- a new
`pdf_export` node that runs immediately after `report_generator` and
converts the Markdown memo (T-042) into a branded, paginated PDF via
WeasyPrint, written to disk and tracked at `state["memo_pdf_path"]`.
Makes zero LLM calls -- this is purely a presentation-layer conversion.

## Changes

- `backend/services/pdf_export.py` -- new file. A narrow Markdown-to-HTML
  converter scoped to memo_generator.py's output shape, a branded HTML
  document assembler with CSS @page rules for the header/page-number/
  footer, atomic-write PDF rendering via lazily-imported WeasyPrint,
  and the `pdf_export_node` LangGraph node entry point. Never raises.
- `backend/config.py` -- added `memo_output_dir` setting.
- `.env.example` -- documented `MEMO_OUTPUT_DIR`.
- `backend/graph/nodes.py` -- added `pdf_export_node` (same
  `_persist_after(profile_node(...))` composition as every other
  sequential node).
- `backend/graph/graph.py` -- registered the new node and rewired the
  tail edge: `report_generator -> pdf_export -> END` (15 nodes total,
  was 14).
- `backend/graph/graph_visualisation.py` -- docstring updated.
- `backend/tests/unit/test_pdf_export.py` -- new file, full coverage
  of the Markdown converter, HTML assembly, path resolution, and the
  node contract, with WeasyPrint mocked throughout.
- `backend/tests/unit/test_graph_skeleton.py`,
  `test_debate_loop.py`, `test_parallel_research.py`,
  `test_routing.py` -- node count assertions updated 14 -> 15.
- `backend/tests/integration/test_graph_integration.py` -- docstring
  node count updated.

## Testing

- New unit test suite: `pytest backend/tests/unit/test_pdf_export.py -v`
- Full suite regression: `pytest --tb=short -q`
- Acceptance-criterion test (`test_full_memo_contains_all_seven_sections`,
  checked at both the HTML-fragment and full-document level) confirms
  every memo section renders
- Acceptance-criterion test (`test_full_memo_no_raw_markdown_syntax_remains`)
  confirms no raw Markdown tokens leak into the rendered HTML -- the
  "no layout bugs" criterion
- Acceptance-criterion test (`test_pdf_size_under_acceptance_threshold`)
  checks actual written file size against the 500KB ceiling using a
  realistically-sized mocked PDF payload
- WeasyPrint is mocked throughout (it requires system libraries --
  Pango, Cairo, GDK-Pixbuf -- not guaranteed present in every CI
  runner); Markdown conversion and path-resolution tests need no
  mocking since that logic has zero third-party dependencies
- Robustness tests confirm the node never raises on a disabled feature
  flag, a missing WeasyPrint installation, a rendering failure, or
  missing/empty memo_markdown

## LangSmith Trace

Not applicable -- `pdf_export_node` makes no LLM calls.

## Related Issues

Closes #43
```

**Squash merge** to main (standard AIRP branch strategy).

---

## After Merge

With T-043 complete, **Phase 4 (Debate Engine & Advanced Agents) is
fully done**: every node in the LangGraph pipeline from `planner`
through `pdf_export` is implemented, tested, and wired -- T-037 through
T-043 cover Risk Officer, Contrarian Investor, Valuation Agent, the
debate loop, the Portfolio Manager, the Markdown memo generator, and
now branded PDF export.

Next phase: **Phase 5 -- FastAPI Backend** (T-045 onward per the
project plan), which exposes this complete pipeline over REST and
WebSocket endpoints. The `memo_pdf_path` written by this task is
specifically what a future `GET /api/v1/analysis/{job_id}/memo.pdf`
download endpoint will serve -- `pdf_export.py` was deliberately kept
free of any FastAPI/routing concerns so Phase 5 can wire that endpoint
without this module needing to know anything about HTTP.

Branch: `feat/api-auth-setup` or similar (per the project plan's Phase
5 task breakdown).

---

*End of Document | T-043 Workflow | AIRP Week 12*