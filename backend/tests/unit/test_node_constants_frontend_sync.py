# backend/tests/unit/test_node_constants_frontend_sync.py
"""
T-074 audit finding (Part B2): the prompt asks for "a test that fails if
[backend/graph/nodes.py's NODE_* constants and
frontend/src/lib/graph/pipelineTopology.ts] ever diverge."

frontend/src/test/pipelineTopology.test.ts already asserts the frontend
file is internally consistent, but it compares PIPELINE_NODE_IDS against a
second, hand-copied list of string literals inside that same TypeScript
file -- it never reads backend/graph/nodes.py, so it cannot catch someone
renaming a NODE_* value on only one side of the split.

This test closes that gap from the Python side: it parses the actual
string literal assigned to each `export const NODE_*` in
pipelineTopology.ts and asserts it is byte-for-byte identical to the
corresponding NODE_* constant imported from backend.graph.nodes. If either
file changes a value without updating the other, this test fails.
"""

import os
from pathlib import Path
import re

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.graph import nodes  # noqa: E402

# ---------------------------------------------------------------------------
# Locate the frontend source file relative to the repo root.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOPOLOGY_TS_PATH = (
    _REPO_ROOT / "frontend" / "src" / "lib" / "graph" / "pipelineTopology.ts"
)

# NODE_* names that exist only in the frontend as LangGraph's own START/END
# sentinels -- backend/graph/nodes.py has no corresponding Python constant
# for these (langgraph.graph.START/END are used directly instead), so they
# are intentionally excluded from the cross-file comparison.
_FRONTEND_ONLY_SENTINELS = {"NODE_START", "NODE_END"}

_EXPORT_CONST_RE = re.compile(r'export const (NODE_[A-Z_]+)\s*=\s*"([^"]*)"\s*;')


def _parse_frontend_node_constants() -> dict[str, str]:
    """Extract every `export const NODE_X = "value";` from pipelineTopology.ts."""
    text = _TOPOLOGY_TS_PATH.read_text(encoding="utf-8")
    return dict(_EXPORT_CONST_RE.findall(text))


def _backend_node_constants() -> dict[str, str]:
    """Every NODE_* attribute defined on backend.graph.nodes."""
    return {
        name: getattr(nodes, name)
        for name in dir(nodes)
        if name.startswith("NODE_") and isinstance(getattr(nodes, name), str)
    }


class TestNodeConstantsMatchFrontend:
    def test_topology_file_exists(self) -> None:
        assert _TOPOLOGY_TS_PATH.is_file(), (
            f"Expected frontend topology file at {_TOPOLOGY_TS_PATH}; "
            "if it moved, update this test's path alongside it."
        )

    def test_frontend_file_declares_at_least_one_node_constant(self) -> None:
        frontend = _parse_frontend_node_constants()
        assert frontend, (
            'Regex found zero `export const NODE_* = "...";` declarations '
            "in pipelineTopology.ts -- either the file's export style changed "
            "(update _EXPORT_CONST_RE) or the file is empty/broken."
        )

    def test_every_backend_node_constant_exists_in_frontend_with_same_value(
        self,
    ) -> None:
        backend = _backend_node_constants()
        frontend = _parse_frontend_node_constants()

        missing = sorted(set(backend) - set(frontend))
        assert not missing, (
            f"backend/graph/nodes.py defines {missing} but "
            "frontend/src/lib/graph/pipelineTopology.ts has no matching "
            "`export const` for them -- add the constant on the frontend "
            "side (or remove it from nodes.py if it's dead)."
        )

        mismatched = {
            name: (backend[name], frontend[name])
            for name in backend
            if backend[name] != frontend[name]
        }
        assert not mismatched, (
            "NODE_* string values diverged between backend/graph/nodes.py "
            f"and pipelineTopology.ts: {mismatched} (format: "
            "{name: (backend_value, frontend_value)}). Live WebSocket "
            "node_started/node_completed events use the backend value, so a "
            "mismatch here means the frontend graph will never highlight "
            "the affected node."
        )

    def test_every_frontend_node_constant_exists_in_backend(self) -> None:
        backend = _backend_node_constants()
        frontend = _parse_frontend_node_constants()

        extra = sorted(set(frontend) - set(backend) - _FRONTEND_ONLY_SENTINELS)
        assert not extra, (
            f"pipelineTopology.ts declares {extra} with no corresponding "
            "NODE_* constant in backend/graph/nodes.py -- either it's a "
            "stale/renamed node id, or backend/graph/nodes.py is missing a "
            "constant that should exist."
        )

    def test_backend_defines_exactly_fifteen_node_constants(self) -> None:
        """
        Sanity check matching graph.py's own documented node count (T-074
        audit finding F-G noted graph_visualisation.py's stale "12 nodes"
        text -- the real, current count is 15).
        """
        assert len(_backend_node_constants()) == 15


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
