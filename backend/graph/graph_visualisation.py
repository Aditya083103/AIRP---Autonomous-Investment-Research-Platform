# backend/graph/graph_visualisation.py
"""
AIRP -- Graph Visualisation Export (T-034)

Auto-exports the LangGraph Mermaid diagram to ``docs/GRAPH_DIAGRAM.md``
every time ``build_graph()`` compiles the StateGraph.

Behaviour
---------
``export_mermaid_diagram(compiled_graph)`` is called at the end of
``build_graph()`` (before returning the compiled graph).  It:

1. Calls ``compiled_graph.get_graph().draw_mermaid()`` to get the raw
   Mermaid source string from LangGraph.
2. Wraps it in a Markdown document with a header, generation timestamp,
   topology summary, and the standard Mermaid code fence (``mermaid``).
3. Resolves the output path as ``docs/GRAPH_DIAGRAM.md`` relative to the
   repository root (located by walking up from this file's directory).
4. Writes the file atomically -- writes to a temp file then renames --
   so a partial write never leaves a corrupt ``GRAPH_DIAGRAM.md``.
5. Returns the path that was written so callers can log it.

Failure handling
----------------
Any I/O error (permissions, disk full, missing docs/ directory) is
caught, logged at WARNING level, and NOT re-raised.  Graph compilation
must succeed even when the docs export fails -- the visualisation is a
developer convenience, not a correctness requirement.

In ENVIRONMENT=test the export is skipped entirely (returns None without
touching the filesystem) so tests that call build_graph() directly do
not leave stale GRAPH_DIAGRAM.md files in the working tree.

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``type: ignore`` -- cast() and explicit annotations only.
* Atomic write via tempfile in the same directory as the target, then
  os.replace(), which is atomic on POSIX and best-effort on Windows.
* Path resolution uses pathlib; no hard-coded absolute paths.
* The function is importable and callable in isolation (no circular
  imports -- it takes the compiled graph as an argument).

Public API
----------
    from backend.graph.graph_visualisation import (
        export_mermaid_diagram,
        resolve_diagram_path,
        DIAGRAM_FILENAME,
    )
"""

from datetime import datetime
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Output filename relative to the docs/ directory.
DIAGRAM_FILENAME: str = "GRAPH_DIAGRAM.md"

#: Name of the docs directory (relative to repo root).
DOCS_DIR_NAME: str = "docs"

#: Number of parent directories to walk up from this file to find repo root.
#: backend/graph/graph_visualisation.py -> backend/graph -> backend -> repo root
_LEVELS_UP: int = 3

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_diagram_path() -> Path:
    """
    Resolve the absolute path to docs/GRAPH_DIAGRAM.md.

    Walks up ``_LEVELS_UP`` parent directories from this source file to
    find the repository root, then appends ``docs/GRAPH_DIAGRAM.md``.

    Returns:
        Absolute Path to the diagram file.  The file may or may not exist.
    """
    this_file: Path = Path(__file__).resolve()
    repo_root: Path = this_file
    for _ in range(_LEVELS_UP):
        repo_root = repo_root.parent
    return repo_root / DOCS_DIR_NAME / DIAGRAM_FILENAME


# ---------------------------------------------------------------------------
# Markdown template
# ---------------------------------------------------------------------------

_HEADER_TEMPLATE = """\
# AIRP -- Investment Pipeline Graph Diagram

> **Auto-generated** by `backend/graph/graph_visualisation.py`
> on every `build_graph()` call.  **Do not edit manually** -- your
> changes will be overwritten on the next graph compile.
>
> Generated: {timestamp}

## Overview

The diagram below shows the complete AIRP LangGraph StateGraph topology
as of the most recent graph compilation.  All 12 nodes and their edges
are shown including the parallel research fan-out, the conditional routing
join, the debate loop, and the sequential tail.

Node categories:

- **planner** -- Pipeline entry point; validates state and fans out to research agents
- **fundamental_analyst, technical_analyst, sentiment_analyst,
  macro_economist** -- Four research agents; run in parallel (T-031)
- **research_join** -- Join choke-point; route_after_research fires exactly once (T-032)
- **error_handler** -- Catches failed fetch_financials; marks pipeline degraded (T-032)
- **sentiment_escalation** -- Flags severely negative news environment (T-032)
- **contrarian_investor** -- Challenges every bullish thesis; drives the debate loop
- **risk_officer, valuation_agent, portfolio_manager** -- Final analysis sequence
- **report_generator** -- Renders the Investment Memo (Markdown) from the
  Portfolio Manager's decision
- **pdf_export** -- Converts the Markdown memo to a branded PDF via
  WeasyPrint; final node before END

## Graph

```mermaid
{mermaid_source}
```

## Node Count

Total nodes: {node_count}

## Edge Notes

- Planner uses the LangGraph Send API to fan out to all 4 research agents
  **simultaneously** in the same super-step.
- All 4 research agents have **direct edges** to `research_join` (not to
  `contrarian_investor` directly) so that conditional routing fires exactly
  once after the parallel join barrier.
- The `contrarian_investor` self-loop (debate round) fires when
  `bear_conviction >= 7` and fewer than 2 debate rounds have completed.
- `error_handler` and `sentiment_escalation` both edge unconditionally to
  `contrarian_investor` after writing their state flags.
"""


def _build_markdown(mermaid_source: str, node_count: int) -> str:
    """
    Wrap the raw Mermaid source in a Markdown document.

    Args:
        mermaid_source: Raw Mermaid diagram string from draw_mermaid().
        node_count:     Number of content nodes (excludes __start__/__end__).

    Returns:
        Full Markdown string ready to write to GRAPH_DIAGRAM.md.
    """
    timestamp: str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return _HEADER_TEMPLATE.format(
        timestamp=timestamp,
        mermaid_source=mermaid_source.strip(),
        node_count=node_count,
    )


# ---------------------------------------------------------------------------
# Export function
# ---------------------------------------------------------------------------


def export_mermaid_diagram(compiled_graph: Any) -> Optional[Path]:
    """
    Export the Mermaid diagram of the compiled graph to docs/GRAPH_DIAGRAM.md.

    Called automatically at the end of ``build_graph()``.  Safe to call
    in any context -- I/O errors are swallowed and logged, never re-raised.

    In ENVIRONMENT=test, returns None immediately without touching the
    filesystem.

    Args:
        compiled_graph: The compiled LangGraph CompiledGraph object returned
                        by ``workflow.compile()``.  Must support
                        ``.get_graph().draw_mermaid()``.

    Returns:
        The Path that was written on success, or None when skipped or on error.
    """
    # Skip in test environment -- never write to the working tree during tests.
    env: str = os.getenv("ENVIRONMENT", "").strip().lower()
    if env == "test":
        logger.debug(
            "export_mermaid_diagram: ENVIRONMENT=test -- skipping diagram export"
        )
        return None

    try:
        # -- 1. Get Mermaid source from LangGraph -------------------------
        mermaid_source: str = compiled_graph.get_graph().draw_mermaid()

        # Count content nodes (exclude __start__ and __end__ sentinels).
        all_nodes: Any = compiled_graph.get_graph().nodes
        node_count: int = len([n for n in all_nodes if not str(n).startswith("__")])

        # -- 2. Build Markdown document ------------------------------------
        markdown: str = _build_markdown(
            mermaid_source=mermaid_source,
            node_count=node_count,
        )

        # -- 3. Resolve target path ----------------------------------------
        target: Path = resolve_diagram_path()

        # -- 4. Ensure docs/ directory exists ------------------------------
        target.parent.mkdir(parents=True, exist_ok=True)

        # -- 5. Atomic write: temp file + os.replace() --------------------
        # Write to a temp file in the same directory as the target so that
        # os.replace() is atomic (same filesystem, no cross-device rename).
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            dir=target.parent,
            prefix=".GRAPH_DIAGRAM_tmp_",
            suffix=".md",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(markdown)
            os.replace(tmp_path_str, str(target))
        except Exception:
            # Clean up temp file if the write or rename failed.
            try:
                os.unlink(tmp_path_str)
            except OSError:
                pass
            raise

        logger.info(
            "export_mermaid_diagram: diagram written to %s (%d nodes, %d chars)",
            target,
            node_count,
            len(markdown),
        )
        return target

    except Exception as exc:
        logger.warning(
            "export_mermaid_diagram: failed to export diagram -- %s: %s",
            type(exc).__name__,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "export_mermaid_diagram",
    "resolve_diagram_path",
    "DIAGRAM_FILENAME",
    "DOCS_DIR_NAME",
]
