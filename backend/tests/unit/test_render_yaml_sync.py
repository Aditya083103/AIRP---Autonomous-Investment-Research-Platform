# backend/tests/unit/test_render_yaml_sync.py
"""
Section C audit finding (unit 9): render.yaml -- the actual Render
Blueprint used to deploy the backend -- was missing all 8 B6 (password
reset) Settings fields (FRONTEND_BASE_URL, SMTP_HOST, SMTP_PORT,
SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_USE_TLS,
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES). A production deploy from this
blueprint would silently run with SMTP unset -- Settings.smtp_host
defaults to "" -- so Settings.email_service_configured is False and
POST /auth/password-reset/request degrades to logging the reset link
instead of emailing it (backend/routers/auth.py), while production
deliberately never logs the raw token (see that router's own
docstring). Net effect: password reset would appear to succeed via the
API but no user could ever actually complete one on a deploy from this
blueprint, with no error or startup failure to signal the gap.

This test is the render.yaml analogue of test_env_example_sync.py's
existing .env.example guard, so this specific class of drift (a real
Settings field with no corresponding `- key:` entry in the Render
Blueprint) is machine-checked and cannot silently reappear the way it
did here -- B6 shipped its own .env.example entries (verified by
test_env_example_sync.py) but nothing ever cross-checked render.yaml
against the same source of truth.

Only one direction is checked (every Settings field needing a real
production value has a `- key:` entry) -- the reverse (documented but
fictional) is deliberately not enforced, since render.yaml is also
allowed to carry Render-platform-only concerns .env.example doesn't
(e.g. none currently, but the file's own header comment reserves that
possibility).
"""

import os
from pathlib import Path
import re

os.environ.setdefault("ENVIRONMENT", "test")

from backend.config import Settings  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RENDER_YAML_PATH = _REPO_ROOT / "render.yaml"

#: Settings fields deliberately absent from render.yaml's envVars list, as
#: the upper-cased env var name (matching _settings_field_keys()'s casing).
#: DATABASE_TEST_URL is pytest-only plumbing (see test_env_example_sync.py's
#: identical reasoning) -- it has no place in a production deploy blueprint.
_FIELDS_INTENTIONALLY_ABSENT: frozenset[str] = frozenset({"DATABASE_TEST_URL"})

_KEY_LINE_RE = re.compile(r"^\s*-\s*key:\s*([A-Z][A-Z0-9_]*)\s*$", re.MULTILINE)


def _declared_keys() -> set[str]:
    text = _RENDER_YAML_PATH.read_text(encoding="utf-8")
    # A lightweight regex scan (mirroring test_env_example_sync.py's own
    # approach) rather than a full YAML parse of Render's Blueprint schema
    # -- envVars entries are a flat "- key: NAME" list either way, and this
    # sidesteps depending on render.yaml's exact block structure staying
    # parseable by a generic YAML loader forever.
    return set(_KEY_LINE_RE.findall(text))


def _settings_field_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


class TestRenderYamlDocumentsEverySetting:
    def test_render_yaml_file_exists(self) -> None:
        assert _RENDER_YAML_PATH.is_file()

    def test_every_settings_field_needed_in_production_is_declared(self) -> None:
        declared = _declared_keys()
        required = _settings_field_keys() - _FIELDS_INTENTIONALLY_ABSENT
        missing = sorted(required - declared)
        assert not missing, (
            f"backend/config.py's Settings declares {missing} but "
            "render.yaml has no matching '- key:' entry for them in its "
            "envVars list -- add one (see the file's existing sections "
            "for the format: `value:` for a safe-to-commit default, "
            "`sync: false` for a secret Render should prompt for), or add "
            "the field name (lowercase) to _FIELDS_INTENTIONALLY_ABSENT "
            "above with a comment explaining why it belongs out of the "
            "production deploy blueprint."
        )
