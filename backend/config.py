# backend/config.py
"""
AIRP — Application Configuration

Single source of truth for all environment variables in the backend.
Uses Pydantic Settings v2 to:
  - Load variables from .env automatically
  - Validate types and required fields at startup
  - Provide IDE autocomplete for all config values

Usage:
    from config import settings

    db_url = settings.database_url
    api_key = settings.anthropic_api_key

Never import os.getenv() directly in application code — always use settings.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All AIRP environment variables with types, defaults, and validation.

    Variables are loaded from .env automatically via pydantic-settings.
    Missing REQUIRED fields raise a ValidationError at startup — fail fast,
    never silently run with missing configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # DATABASE_URL and database_url both work
        extra="ignore",  # ignore unknown env vars (don't crash on extras)
    )

    # ── 1. Application ────────────────────────────────────────────────────
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_origins: str = "http://localhost:5173"
    secret_key: str = Field(
        default="insecure-default-change-in-production",
        min_length=32,
        description="JWT signing secret — must be 32+ chars in production",
    )
    access_token_expire_minutes: int = 60

    # ── 2. LLM Provider ───────────────────────────────────────────────────
    # Switch between providers by changing LLM_PROVIDER in .env.
    # groq      = free tier, used for all development (22 weeks)
    # anthropic = Claude API, used for final demo only
    llm_provider: Literal["anthropic", "groq"] = "groq"

    # Anthropic (Claude) — kept for final demo only
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key — used only when LLM_PROVIDER=anthropic",
    )
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_max_tokens: int = 4096

    # Groq — free tier, primary LLM during development
    groq_api_key: str = Field(
        default="",
        description="Groq API key — used when LLM_PROVIDER=groq (free tier)",
    )
    groq_model: str = "llama-3.3-70b-versatile"

    # ── 3. Observability ──────────────────────────────────────────────────
    langsmith_api_key: str = Field(
        default="",
        description="LangSmith API key — tracing disabled if empty",
    )
    langchain_tracing_v2: str = "true"  # kept as str — evaluated in tracing_enabled
    langchain_project: str = "airp-dev"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # ── 4. Database ───────────────────────────────────────────────────────
    database_url: str = Field(
        description="PostgreSQL async connection string (asyncpg driver)"
    )
    database_test_url: str = Field(
        default="postgresql+asyncpg://airp:airp@localhost:5432/airp_test",
        description="Separate test database — never the same as database_url",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # ── 5. Cache ──────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"
    redis_token: str = ""  # only for Upstash cloud
    cache_ttl_stock: int = 900
    cache_ttl_news: int = 3600
    cache_ttl_macro: int = 86400
    cache_ttl_fundamentals: int = 3600

    # ── 6. Vector Store ───────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection: str = "airp_documents"
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── 7. Authentication ─────────────────────────────────────────────────
    clerk_secret_key: str = Field(
        default="",
        description="Clerk secret key — required in Phase 5 (FastAPI auth)",
    )
    clerk_publishable_key: str = Field(
        default="",
        description="Clerk publishable key — required in Phase 6 (React auth)",
    )
    clerk_jwt_issuer: str = Field(
        default="",
        description="Clerk JWT issuer URL — required in Phase 5",
    )

    # ── 8. External Data APIs ─────────────────────────────────────────────
    news_api_key: str = Field(
        default="",
        description="NewsAPI key — required for News Sentiment Agent (Phase 2)",
    )
    alpha_vantage_key: str = Field(
        default="",
        description="Alpha Vantage key — required for Fundamental Analyst (Phase 2)",
    )
    screener_base_url: str = "https://www.screener.in"
    rbi_base_url: str = "https://www.rbi.org.in"

    # ── 9. Feature Flags ──────────────────────────────────────────────────
    feature_debate_enabled: bool = True
    debate_rounds: int = 2
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
    feature_rate_limiting: bool = True
    max_concurrent_analyses: int = 3

    # ── Input normalizers ─────────────────────────────────────────────────
    # Run BEFORE the Literal check so a stray trailing space (a classic
    # Windows `set VAR=value ` artefact) or wrong casing can't fail startup.
    @field_validator("environment", "llm_provider", mode="before")
    @classmethod
    def _normalize_lower_literal(cls, value: object) -> object:
        """Trim whitespace and lowercase so 'test ' or 'TEST' both resolve."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Trim whitespace and uppercase so 'info ' or 'info' both resolve."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    # ── Computed properties ───────────────────────────────────────────────
    @computed_field  # type: ignore[misc]
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS_ORIGINS string into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        """True only in production — used to enable strict security checks."""
        return self.environment == "production"

    @computed_field  # type: ignore[misc]
    @property
    def active_database_url(self) -> str:
        """Returns test DB URL when running under pytest, primary URL otherwise."""
        if self.environment == "test":
            return self.database_test_url
        return self.database_url

    @computed_field  # type: ignore[misc]
    @property
    def tracing_enabled(self) -> bool:
        """True only when tracing flag is 'true' AND a LangSmith key is present."""
        return self.langchain_tracing_v2.lower() == "true" and bool(
            self.langsmith_api_key
        )

    @computed_field  # type: ignore[misc]
    @property
    def active_llm_api_key(self) -> str:
        """Returns the API key for the currently configured LLM provider."""
        if self.llm_provider == "groq":
            return self.groq_api_key
        return self.anthropic_api_key

    @computed_field  # type: ignore[misc]
    @property
    def active_llm_model(self) -> str:
        """Returns the model name for the currently configured LLM provider."""
        if self.llm_provider == "groq":
            return self.groq_model
        return self.anthropic_model


# ── get_settings must be OUTSIDE the class ────────────────────────────────────
@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    lru_cache means .env is read exactly once per process — not on every
    import. Use get_settings() as a FastAPI dependency in route handlers:

        @router.get("/")
        def route(settings: Settings = Depends(get_settings)):
            ...

    In tests, override with:
        app.dependency_overrides[get_settings] = lambda: Settings(_env_file=".env.test")
    """
    return Settings()


# Module-level singleton for non-FastAPI code (agents, tools, etc.)
# Import this directly where Depends() is not available:
#   from config import settings
settings: Settings = get_settings()
