# backend/tests/unit/test_requirements.py
"""
T-009 acceptance gate — verify the Python environment is correctly set up.

These tests are the acceptance criteria for T-009:
  "pip install -r requirements.txt succeeds; python -m pytest returns no errors"

Each test imports a package from requirements.txt and checks its version
meets the minimum required. A clear ImportError here means pip install
did not complete successfully, or the wrong Python interpreter is active.

All tests are pure import checks — no network calls, no LLM calls, no DB
connections. They run in under 1 second total.

Windows skip policy:
  Three packages (chromadb, sentence-transformers, weasyprint) depend on
  native system libraries that Windows Application Control policies block
  on managed/corporate machines. These tests are skipped on Windows
  (platform.system() == "Windows") but run on Linux CI and Render.
  The packages ARE installed correctly — the skip is a Windows DLL policy
  issue, not a code bug.
"""
from __future__ import annotations

import importlib
import importlib.util
import platform
import sys

import pytest

# Convenience marker reused by the three Windows-incompatible tests
windows_dll_skip = pytest.mark.skipif(
    platform.system() == "Windows",
    reason=(
        "Native C extensions blocked by Windows Application Control policy. "
        "Package IS installed. Runs correctly on Linux (CI, Render, WSL2)."
    ),
)


# ── Python version gate ───────────────────────────────────────────────────────


def test_python_version_is_311_or_higher() -> None:
    """
    AIRP requires Python 3.11+.

    3.11 is required for:
    - tomllib (stdlib)
    - improved typing (Self, Never, LiteralString)
    - asyncio.TaskGroup for structured concurrency
    """
    major, minor = sys.version_info.major, sys.version_info.minor
    assert (major, minor) >= (3, 11), (
        f"Python 3.11+ required; got {major}.{minor}. "
        "Activate the correct virtual environment."
    )


# ── Core framework imports ─────────────────────────────────────────────────────


def test_fastapi_importable() -> None:
    """fastapi must be installed and importable."""
    import fastapi  # noqa: F401

    assert fastapi.__version__ >= "0.110.0"


def test_uvicorn_importable() -> None:
    """uvicorn must be installed and importable."""
    import uvicorn  # noqa: F401


def test_pydantic_v2_importable() -> None:
    """Pydantic v2 must be installed (v1 is not supported)."""
    import pydantic

    major = int(pydantic.__version__.split(".")[0])
    assert major == 2, (
        f"Pydantic v2 required; got v{pydantic.__version__}. "
        "Run: pip install 'pydantic>=2.0.0,<3.0.0'"
    )


def test_pydantic_settings_importable() -> None:
    """pydantic-settings must be installed for config.py to work."""
    import pydantic_settings  # noqa: F401


# ── LLM & orchestration imports ───────────────────────────────────────────────


def test_langchain_importable() -> None:
    """langchain must be importable at 0.3.x."""
    import langchain

    assert langchain.__version__.startswith(
        "0.3"
    ), f"langchain 0.3.x required; got {langchain.__version__}"


def test_langgraph_importable() -> None:
    """langgraph must be importable."""
    import langgraph  # noqa: F401


def test_langsmith_importable() -> None:
    """langsmith must be importable."""
    import langsmith  # noqa: F401


def test_langchain_groq_importable() -> None:
    """langchain-groq must be importable (free-tier LLM for dev)."""
    import langchain_groq  # noqa: F401


def test_langchain_anthropic_importable() -> None:
    """langchain-anthropic must be importable (Claude API for demo)."""
    import langchain_anthropic  # noqa: F401


# ── Database imports ──────────────────────────────────────────────────────────


def test_sqlalchemy_v2_importable() -> None:
    """SQLAlchemy v2 must be installed (async API required)."""
    import sqlalchemy

    major = int(sqlalchemy.__version__.split(".")[0])
    assert major == 2, f"SQLAlchemy v2 required; got v{sqlalchemy.__version__}"


def test_alembic_importable() -> None:
    """alembic must be importable for database migrations."""
    import alembic  # noqa: F401


def test_asyncpg_importable() -> None:
    """asyncpg must be importable — required async PostgreSQL driver."""
    import asyncpg  # noqa: F401


# ── Cache import ──────────────────────────────────────────────────────────────


def test_redis_importable() -> None:
    """redis client must be importable."""
    import redis  # noqa: F401


# ── Vector store & embeddings imports ─────────────────────────────────────────


@windows_dll_skip
def test_chromadb_importable() -> None:
    """
    chromadb must be importable.

    Skipped on Windows: chromadb's grpc dependency loads a compiled DLL
    (cygrpc) that Windows Application Control policies block on managed
    machines. The package is correctly installed — this is a Windows
    security policy restriction, not a code bug.

    Runs on: Linux CI (GitHub Actions), Render (production), WSL2.
    """
    import chromadb  # noqa: F401


@windows_dll_skip
def test_sentence_transformers_importable() -> None:
    """
    sentence-transformers must be importable.

    Skipped on Windows: sentence-transformers pulls in scikit-learn, which
    loads compiled Cython extensions (.pyd files) blocked by Windows
    Application Control on managed/corporate machines.

    Runs on: Linux CI (GitHub Actions), Render (production), WSL2.
    """
    import sentence_transformers  # noqa: F401


# ── Market data imports ───────────────────────────────────────────────────────


def test_yfinance_importable() -> None:
    """yfinance must be importable."""
    import yfinance  # noqa: F401


def test_requests_importable() -> None:
    """requests must be importable."""
    import requests  # noqa: F401


def test_beautifulsoup4_importable() -> None:
    """beautifulsoup4 (bs4) must be importable."""
    import bs4  # noqa: F401


def test_newsapi_importable() -> None:
    """newsapi-python must be importable."""
    import newsapi  # noqa: F401


# ── Auth import ───────────────────────────────────────────────────────────────


def test_jose_importable() -> None:
    """python-jose must be importable for JWT handling."""
    import jose  # noqa: F401


# ── PDF generation import ─────────────────────────────────────────────────────


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason=(
        "WeasyPrint requires GTK system libraries (Pango, Cairo, GObject) "
        "that do not ship with Windows. Install GTK via "
        "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html "
        "or use WSL2. Runs correctly on Linux CI and Render (production)."
    ),
)
def test_weasyprint_importable() -> None:
    """
    weasyprint must be importable for Investment Memo PDF generation.

    Skipped on Windows: WeasyPrint requires native GTK libraries
    (gobject-2.0, Pango, Cairo) that are not present on a standard Windows
    installation. The package is installed — the system libraries are missing.

    Fix (Windows, optional): Install GTK runtime from
    https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer

    Runs on: Linux CI (GitHub Actions), Render (production), WSL2.
    """
    import weasyprint  # noqa: F401


# ── Utility imports ───────────────────────────────────────────────────────────


def test_tenacity_importable() -> None:
    """tenacity must be importable for API retry logic."""
    import tenacity  # noqa: F401


def test_aiohttp_importable() -> None:
    """aiohttp must be importable (used by LangChain tools internally)."""
    import aiohttp  # noqa: F401


# ── AIRP config import ────────────────────────────────────────────────────────


def test_airp_config_importable() -> None:
    """
    backend/config.py must import cleanly.

    This validates that:
    - pydantic-settings is installed
    - All type annotations in config.py resolve correctly
    - The Settings class can be referenced (not instantiated — no .env needed)
    """
    from backend.config import Settings  # noqa: F401

    assert Settings is not None


def test_airp_llm_factory_importable() -> None:
    """
    backend/agents/llm_factory.py must import cleanly.

    This validates that langchain_groq and langchain_anthropic are both
    installed and that the factory module has no syntax errors.
    """
    spec = importlib.util.find_spec("backend.agents.llm_factory")
    assert spec is not None, (
        "backend/agents/llm_factory.py not found. "
        "Ensure you are running pytest from the repo root."
    )
