# backend/tests/unit/test_no_future_annotations.py
"""
T-074 audit finding C8: `from __future__ import annotations` is banned in
AIRP production code -- it breaks Pydantic v2 union-type resolution for
modules that import a module using it (the exact failure mode that
motivated the original rule, restated in nearly every production module's
own docstring). The rule existed only as scattered prose before this test:
nothing actually enforced it, and it had silently crept back into ~10
production files (db/session.py, db/chroma_client.py, agents/llm_factory.py,
agents/portfolio_manager.py, models/orm.py, services/memo_generator.py,
tools/financials.py, tools/macro.py, tools/news.py, tools/ratios.py) before
this pass removed them. This test is the permanent guard against
recurrence -- it runs on every CI pytest invocation, no separate flake8
plugin or pre-commit hook installation required.

Scope: every backend/*.py file EXCEPT:
  * backend/tests/**        -- test infrastructure, not production code;
                                the future import is pervasive there and
                                out of scope for this rule.
  * backend/migrations/**   -- Alembic-generated, historical, and (per
                                project convention) never edited once
                                applied.
  * backend/tools/portfolio_tools.py -- a DOCUMENTED, deliberate exception
                                (see that file's own module docstring):
                                it defines no Pydantic models, so the
                                union-resolution risk the rule exists to
                                prevent does not apply there.
"""

import os
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "test")

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

_EXCLUDED_DIRS = ("tests", "migrations", "__pycache__")

#: Files with a documented, reviewed exception -- see this file's own
#: docstring above and each excepted file's own module docstring for why.
_DOCUMENTED_EXCEPTIONS = frozenset(
    {
        _BACKEND_ROOT / "tools" / "portfolio_tools.py",
    }
)

_BANNED_IMPORT = "from __future__ import annotations"


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for path in _BACKEND_ROOT.rglob("*.py"):
        relative_parts = path.relative_to(_BACKEND_ROOT).parts
        if any(part in _EXCLUDED_DIRS for part in relative_parts):
            continue
        files.append(path)
    return files


def test_scan_finds_at_least_one_production_file() -> None:
    """Sanity check that the scan itself is actually finding files, so a
    silently-empty result can't make the real test below pass vacuously."""
    assert len(_production_python_files()) > 20


def test_no_future_annotations_import_in_production_code() -> None:
    offenders: list[str] = []
    for path in _production_python_files():
        if path in _DOCUMENTED_EXCEPTIONS:
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == _BANNED_IMPORT:
                offenders.append(str(path.relative_to(_BACKEND_ROOT)))
                break

    assert not offenders, (
        f"'{_BANNED_IMPORT}' found in production file(s): {offenders}. "
        "This is a banned import in AIRP production code -- it breaks "
        "Pydantic v2 union-type resolution for modules that import a "
        "module using it (T-074 audit finding C8). Remove the import; if "
        "removing it surfaces a genuine forward-reference NameError (e.g. "
        "an ORM relationship referencing a class defined later in the same "
        "file), quote just that one type annotation instead of "
        "reintroducing the future import module-wide -- see "
        "backend/models/orm.py's User.analyses for the pattern. If this "
        "file has a genuinely reviewed reason to be exempt (no Pydantic "
        "models, e.g. backend/tools/portfolio_tools.py), add it to "
        "_DOCUMENTED_EXCEPTIONS above with a comment explaining why."
    )
