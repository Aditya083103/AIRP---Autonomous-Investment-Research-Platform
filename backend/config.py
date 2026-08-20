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

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Placeholder secret_key value -- fine for local dev, never safe in
#: production (see Settings._reject_insecure_secret_key_in_production).
_INSECURE_DEFAULT_SECRET_KEY = "insecure-default-change-in-production"  # nosec B105


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

    # --- 1. Application ---
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_origins: str = "http://localhost:3000"
    secret_key: str = Field(
        default=_INSECURE_DEFAULT_SECRET_KEY,
        min_length=32,
        description="JWT signing secret — must be 32+ chars in production",
    )
    access_token_expire_minutes: int = 60

    # --- 2. LLM Provider ---
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
    # Live end-to-end verification (2026-08-19) found llama-3.3-70b-versatile
    # -- and llama-3.1-8b-instant -- both fully retired from Groq's catalog;
    # every LLM call in the pipeline 404'd with model_not_found. Confirmed
    # against GET https://api.groq.com/openai/v1/models with a real key that
    # no llama-3.x model remains available at all; openai/gpt-oss-120b is
    # the closest capability-tier replacement (120B open-weight, currently
    # active). If this 404s again in the future, check that endpoint first
    # -- Groq's free-tier model catalog changes without notice.
    groq_model: str = "openai/gpt-oss-120b"

    # --- 3. Observability ---
    langsmith_api_key: str = Field(
        default="",
        description="LangSmith API key — tracing disabled if empty",
    )
    langchain_tracing_v2: str = "true"  # kept as str — evaluated in tracing_enabled
    langchain_project: str = "airp-dev"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # --- 4. Database ---
    database_url: str = Field(
        description="PostgreSQL async connection string (asyncpg driver)"
    )
    database_test_url: str = Field(
        default="postgresql+asyncpg://airp:airp@localhost:5432/airp_test",
        description="Separate test database — never the same as database_url",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- 5. Cache ---
    redis_url: str = "redis://localhost:6379"
    redis_token: str = ""  # only for Upstash cloud
    cache_ttl_stock: int = 900
    cache_ttl_news: int = 3600
    cache_ttl_macro: int = 86400
    cache_ttl_fundamentals: int = 3600

    # --- 6. Vector Store ---
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection: str = "airp_documents"
    embedding_model: str = "all-MiniLM-L6-v2"
    chroma_persist_dir: str = Field(
        default="",
        description=(
            "Override for the local-dev ChromaDB PersistentClient directory. "
            "Empty string means 'use the default outside the repo root' "
            "(backend.db.chroma_client.CHROMA_PERSIST_DIR, ~/.airp/chroma_data). "
            "Set this only if you need PersistentClient data somewhere else — "
            "it must stay outside any directory 'uvicorn --reload' watches, "
            "or writes to it will trigger reloads mid-analysis."
        ),
    )

    # --- 7. Authentication ---
    # T-074 audit findings C9/F9: clerk_secret_key / clerk_publishable_key /
    # clerk_jwt_issuer were removed here -- dead since the self-hosted auth
    # migration (20260624_..._migrate_users_to_self_hosted_auth). Clerk is
    # not imported or referenced anywhere in backend/ runtime code; keeping
    # unenforced auth-adjacent config fields around is worse than not
    # having them.
    accuracy_service_token: str = Field(
        default="",
        description=(
            "Shared secret required in the X-Service-Token header for "
            "POST /api/v1/accuracy/run (T-090). Empty means the endpoint "
            "is disabled (fails closed) -- generate a long random value "
            "for staging/production and store it as a GitHub Actions "
            "secret for the scheduled evaluate-verdicts.yml workflow."
        ),
    )

    # --- 8. External Data APIs ---
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

    # --- 9. Feature Flags ---
    feature_debate_enabled: bool = True
    debate_rounds: int = 2
    feature_pdf_enabled: bool = True
    feature_rag_enabled: bool = Field(
        default=True,
        description=(
            "Enable ChromaDB-backed RAG (News Sentiment agent's semantic "
            "search over ingested articles). Defaults to True everywhere "
            "except production, where it defaults to False unless "
            "FEATURE_RAG_ENABLED is set explicitly -- ChromaDB has no "
            "managed backing service on the free-tier deploy target "
            "(T-074 audit findings C4/C5), and the News Sentiment agent "
            "degrades cleanly to non-RAG scoring when this is off."
        ),
    )
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
    rate_limit_requests_per_minute: int = Field(
        default=60,
        description=(
            "Maximum requests per client (by IP) per rolling 60-second "
            "window when FEATURE_RATE_LIMITING is on. Requests over this "
            "limit get 429 Too Many Requests. In-process only (T-074 "
            "audit findings C9/F9) -- see backend.services.rate_limiter."
        ),
    )
    max_concurrent_analyses: int = 3
    max_upload_size_mb: int = Field(
        default=20,
        description=(
            "Maximum accepted PDF upload size in megabytes for "
            "POST /api/v1/documents/upload. Requests above this are "
            "rejected with 413 before any text extraction is attempted."
        ),
    )

    # --- Input normalizers ---
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

    @model_validator(mode="after")
    def _default_rag_off_in_production(self) -> "Settings":
        """
        FEATURE_RAG_ENABLED defaults to True everywhere except production,
        where it defaults to False unless the operator sets it explicitly
        (T-074 audit findings C4/C5 -- ChromaDB has no managed backing
        service on the free-tier deploy target). Checking
        ``model_fields_set`` rather than just overwriting the field means an
        operator who explicitly sets ``FEATURE_RAG_ENABLED=true`` in a
        production .env is respected, not silently overridden.
        """
        if (
            self.environment == "production"
            and "feature_rag_enabled" not in self.model_fields_set
        ):
            self.feature_rag_enabled = False
        return self

    @model_validator(mode="after")
    def _reject_insecure_secret_key_in_production(self) -> "Settings":
        """
        Fail startup outright when ENVIRONMENT=production and SECRET_KEY
        is still the checked-into-source-control placeholder (T-074 audit
        finding C11). Before this validator, the app would boot
        successfully and silently sign every user's JWT with a
        publicly-known string, letting anyone forge a valid token for any
        user_id -- unlike ACCURACY_SERVICE_TOKEN (backend.dependencies.
        auth.verify_service_token), which already fails closed when unset.
        A deliberate decision, not an oversight: ACCURACY_SERVICE_TOKEN is
        NOT given the same hard-fail treatment here, because an empty
        value there disables one internal cron-triggered endpoint (a pure
        availability concern for the scheduled evaluate-verdicts.yml
        workflow), whereas an insecure SECRET_KEY is a live authentication
        bypass for every user of the running service.
        """
        if (
            self.environment == "production"
            and self.secret_key == _INSECURE_DEFAULT_SECRET_KEY
        ):
            raise ValueError(
                "SECRET_KEY must be set to a real random value when "
                "ENVIRONMENT=production -- refusing to start with the "
                "insecure default, which is checked into source control "
                "and would let anyone forge a valid JWT for any user."
            )
        return self

    # --- Computed properties ---
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


# --- get_settings must be OUTSIDE the class ---
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
