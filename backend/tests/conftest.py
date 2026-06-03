# backend/tests/conftest.py
"""
Global pytest fixtures and configuration for the AIRP test suite.

This file is intentionally minimal in Phase 0.
Fixtures for database, Redis, and HTTP client are added in Phase 1 (T-009+)
once the actual application code exists.
"""
from collections.abc import Generator
import os

import pytest


# ── Environment guard ─────────────────────────────────────────────────────────
# Ensures tests never accidentally run against a production database.
# The CI workflow sets ENVIRONMENT=test; local runs must also set it.
@pytest.fixture(autouse=True)  # type: ignore[misc]
def require_test_environment() -> Generator[None, None, None]:
    """Block test execution if ENVIRONMENT is not set to 'test'."""
    env = os.getenv("ENVIRONMENT", "")
    if env != "test":
        pytest.fail(
            f"Tests must run with ENVIRONMENT=test (got '{env}'). "
            "Set it in your shell or .env.test file before running pytest."
        )
    yield
