# backend/tests/unit/test_placeholder.py
"""
Placeholder test suite for Phase 0.

This file exists solely so pytest has at least one test to collect,
preventing the 'no tests ran' warning and ensuring the CI coverage
step exits cleanly. It is replaced with real tests starting in Phase 1.
"""
import os

import pytest


def test_placeholder_always_passes() -> None:
    """Placeholder — confirms pytest is wired up correctly."""
    assert True


def test_environment_variable_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirms monkeypatch fixture works — used extensively in Phase 1+."""
    monkeypatch.setenv("TEST_KEY", "test_value")
    assert os.getenv("TEST_KEY") == "test_value"
