# T-034 -- Add Graph Visualisation Export

**Phase:** 3 -- LangGraph Orchestration
**Week:** 8
**Branch:** `feat/graph-visualisation`
**Task status:** Ready to implement

---

## Overview

T-034 auto-exports the AIRP LangGraph Mermaid diagram to
`docs/GRAPH_DIAGRAM.md` on every `build_graph()` call. The diagram is
always in sync with the actual graph topology -- no manual update needed
when nodes or edges change.

**Acceptance criteria (both must pass):**

- `docs/GRAPH_DIAGRAM.md` updated after every graph compile
- Diagram shows all 12 nodes and their edges correctly

---

## What Was Built

### New file: `backend/graph/graph_visualisation.py`

`export_mermaid_diagram(compiled_graph)` -- the core export function:

1. Calls `compiled_graph.get_graph().draw_mermaid()` to get raw Mermaid source.
2. Wraps it in a Markdown document with header, timestamp, node count,
   topology notes, and a standard `mermaid` code fence.
3. Resolves the output path as `docs/GRAPH_DIAGRAM.md` relative to the
   repo root (by walking up 3 levels from `backend/graph/`).
4. Writes atomically: temp file + `os.replace()` so a partial write
   never leaves a corrupt file.
5. Returns the Path written, or `None` on I/O error or in test environment.

**I/O failures are non-fatal** -- caught and logged at WARNING level,
never re-raised. Graph compilation always succeeds.

**In ENVIRONMENT=test** the export is skipped entirely (returns None
immediately) so tests never write to the working tree.

`resolve_diagram_path()` -- resolves the absolute path to
`docs/GRAPH_DIAGRAM.md` by walking up `_LEVELS_UP=3` parent directories
from the source file. Importable for use in scripts and tests.

### Modified: `backend/graph/graph.py`

Added after `workflow.compile()` in `build_graph()`:

```python
# -- 11. Export Mermaid diagram (T-034) ------------------------------------
export_mermaid_diagram(compiled)
```

`export_mermaid_diagram` is now also included in `graph.py`'s `__all__`.

### New file: `docs/GRAPH_DIAGRAM.md`

Seed file committed to the repository. Automatically overwritten on the
first `build_graph()` call in a non-test environment. Contains the full
12-node diagram as of T-032/T-033.

### New file: `backend/tests/unit/test_graph_visualisation.py`

60+ unit tests across 8 test classes covering:

- `resolve_diagram_path()` -- absolute, correct suffix, deterministic
- `export_mermaid_diagram()` skip path in test env
- `export_mermaid_diagram()` success path (fully mocked FS)
- `export_mermaid_diagram()` I/O failure (non-fatal, temp file cleanup)
- `_build_markdown()` -- code fence, node count, timestamp, header
- `build_graph()` integration -- calls export exactly once
- `DIAGRAM_FILENAME` constant
- Public API completeness

---

## File Placement

```
backend/graph/graph_visualisation.py   (NEW)
backend/graph/graph.py                  (MODIFIED -- add export call)
backend/tests/unit/test_graph_visualisation.py  (NEW)
docs/GRAPH_DIAGRAM.md                   (NEW -- seed file)
docs/week-08/T-034-graph-visualisation.md  (NEW -- this file)
```

---

## Step-by-Step Workflow

### 0. Prerequisites

```bash
git checkout main
git pull origin main
git status   # clean working tree
```

Set test environment:

```cmd
set ENVIRONMENT=test
```

### 1. Create the feature branch

```bash
git checkout -b feat/graph-visualisation
```

### 2. Apply file changes

Place the files listed above into the repo at their respective paths.

### 3. Clear stale pycache

```bash
find backend/graph backend/tests -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
find backend/graph backend/tests -name "*.pyc" -delete 2>/dev/null; true
```

### 4. Run the full unit test suite

```bash
python -m pytest backend/tests/unit/ -v --tb=short -q
```

Key new tests to watch:

- `test_graph_visualisation.py` -- all 60+ T-034 tests
- `test_graph_skeleton.py` -- still passes (export is mocked in test env)
- `test_parallel_research.py` -- still passes
- `test_routing.py` -- still passes

### 5. Verify diagram generation manually (optional)

Run in a non-test environment to verify the file is written:

```bash
# Windows CMD (do NOT set ENVIRONMENT)
python -c "from backend.graph.graph import build_graph; g = build_graph(); print('done')"
# Check docs/GRAPH_DIAGRAM.md was created/updated
```

### 6. Pre-commit hooks (two-commit pattern)

```bash
git add .
git commit -m "feat(graph): auto-export Mermaid diagram to GRAPH_DIAGRAM.md T-034"
# If formatters auto-fix:
git add .
git commit -m "feat(graph): auto-export Mermaid diagram to GRAPH_DIAGRAM.md T-034"
```

### 7. Push and open PR

```bash
git push -u origin feat/graph-visualisation
```

---

## PR Details

**PR Title:**

```
feat(graph): auto-export Mermaid diagram to docs/GRAPH_DIAGRAM.md (T-034)
```

**PR Description:**

````markdown
## Summary

Implements T-034 graph visualisation export. Every call to `build_graph()`
now auto-exports the LangGraph Mermaid diagram to `docs/GRAPH_DIAGRAM.md`
using an atomic write (temp file + `os.replace()`). The diagram stays in
sync with the graph topology automatically -- no manual maintenance needed.

## Changes

- `backend/graph/graph_visualisation.py` (new): `export_mermaid_diagram()`
  function that gets Mermaid source from LangGraph, wraps it in a Markdown
  document, and writes it atomically. Skipped in ENVIRONMENT=test.
  Non-fatal: I/O errors are logged and swallowed.

- `backend/graph/graph.py` (modified): Calls `export_mermaid_diagram(compiled)`
  at the end of `build_graph()` before returning. Added to `__all__`.

- `docs/GRAPH_DIAGRAM.md` (new): Seed file with the T-032/T-033 12-node
  diagram. Auto-updated on every graph compile outside of test env.

- `backend/tests/unit/test_graph_visualisation.py` (new): 60+ unit tests
  covering skip path, success path (mocked FS), I/O failure handling,
  Markdown template, build_graph() integration, and public API.

## Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/ -v --tb=short -q
```
````

All 60+ new tests pass. All existing tests still pass.
Filesystem is fully mocked in tests -- no real file writes.

## LangSmith Trace

N/A -- no LLM calls in this task.

## Related Issues

Closes #34

```

---

## Commit Message

```

feat(graph): auto-export Mermaid diagram to docs/GRAPH_DIAGRAM.md (T-034)

- graph_visualisation.py: export_mermaid_diagram() calls
  compiled.get_graph().draw_mermaid(), wraps in Markdown with timestamp
  and node count, writes atomically (mkstemp + os.replace())
- ENVIRONMENT=test: export skipped entirely -- returns None, no FS writes
- I/O failures: caught and logged at WARNING level, never re-raised
- resolve_diagram_path(): walks 3 levels up from backend/graph/ to
  find repo root, appends docs/GRAPH_DIAGRAM.md
- graph.py: calls export_mermaid_diagram(compiled) after workflow.compile()
- docs/GRAPH_DIAGRAM.md: seed file with full 12-node diagram (T-032/T-033)
- test_graph_visualisation.py: 60+ unit tests; FS fully mocked

Closes #34

```

---

## Key Design Decisions

### Why atomic write?

A partial write (process killed mid-write) leaves a corrupt
`GRAPH_DIAGRAM.md` that fails Mermaid rendering.  Writing to a temp file
first and then `os.replace()` is atomic on POSIX (rename syscall) and
best-effort on Windows.  If the rename fails, the original file is
untouched.

### Why skip in ENVIRONMENT=test?

Tests call `build_graph()` hundreds of times across the test suite.
Writing to `docs/GRAPH_DIAGRAM.md` on every call would:
- Cause race conditions in parallel test runs
- Pollute the working tree with auto-generated content during CI
- Slow down tests with unnecessary I/O

The skip is inside `export_mermaid_diagram` itself, not in `build_graph`,
so there is no conditional in the graph builder.

### Why non-fatal?

The Mermaid export is a developer convenience.  A missing or stale
`GRAPH_DIAGRAM.md` does not break the investment pipeline, FastAPI
server, or any test.  Making it fatal would cause production outages
for a documentation issue.

### Why walk up 3 levels instead of using __file__ tricks?

`backend/graph/graph_visualisation.py` is always at:
`{repo_root}/backend/graph/graph_visualisation.py`

Walking up 3 levels from the file gives `{repo_root}`.  This approach
works regardless of the current working directory and is safe for both
direct `python` invocations and pytest runs.
```
