# backend/tests/unit/test_env_example_sync.py
"""
T-074 audit finding C10: T-079's own acceptance criterion is literally
"ensure all env vars documented" -- this test makes that machine-checked
instead of manually maintained, so root .env.example can never silently
drift out of sync with backend.config.Settings again the way it had
(stale GROQ_MODEL/ANTHROPIC_MODEL, fictional VITE_* entries, missing
CHROMA_PERSIST_DIR/MAX_UPLOAD_SIZE_MB) before this test existed.

Two directions are checked:
  1. Every Settings field has a matching KEY= line in .env.example
     (nothing the app actually reads is undocumented).
  2. Every KEY= line in .env.example corresponds to a real Settings field
     (nothing fictional is documented, e.g. a variable no code reads).

Frontend VITE_* variables are deliberately out of scope here -- they live
in frontend/.env.example, a separate file for a separate build, and are
not backend.config.Settings fields at all.
"""

import os
from pathlib import Path
import re

os.environ.setdefault("ENVIRONMENT", "test")

from backend.config import Settings  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_EXAMPLE_PATH = _REPO_ROOT / ".env.example"

#: Settings fields deliberately not documented as KEY= lines in
#: .env.example. database_test_url IS documented (needed to run pytest
#: locally) so nothing is currently in this set -- kept as an explicit,
#: named escape hatch so a future genuinely-internal-only field doesn't
#: have to fight this test, rather than silently weakening the assertion.
_FIELDS_INTENTIONALLY_UNDOCUMENTED: frozenset[str] = frozenset()

_KEY_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _documented_keys() -> set[str]:
    text = _ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    return set(_KEY_LINE_RE.findall(text))


def _settings_field_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


class TestEnvExampleDocumentsEverySetting:
    def test_env_example_file_exists(self) -> None:
        assert _ENV_EXAMPLE_PATH.is_file()

    def test_every_settings_field_is_documented(self) -> None:
        documented = _documented_keys()
        required = _settings_field_keys() - _FIELDS_INTENTIONALLY_UNDOCUMENTED
        missing = sorted(required - documented)
        assert not missing, (
            f"backend/config.py's Settings declares {missing} but "
            ".env.example has no matching KEY= line for them -- add an "
            "entry (see the file's existing sections for the format), or "
            "add the field name (lowercase) to "
            "_FIELDS_INTENTIONALLY_UNDOCUMENTED above with a comment "
            "explaining why it should stay undocumented."
        )

    def test_every_documented_key_is_a_real_setting(self) -> None:
        documented = _documented_keys()
        real = _settings_field_keys()
        fictional = sorted(documented - real)
        assert not fictional, (
            f".env.example documents {fictional} but backend/config.py's "
            "Settings has no matching field -- either the variable is "
            "stale (rename/remove it here) or Settings is missing a field "
            "that should exist."
        )
