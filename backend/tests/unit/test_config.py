# backend/tests/unit/test_config.py
"""
Unit tests for backend/config.py.

Tests validate that:
- Settings loads correctly from environment variables
- Computed properties return correct values
- active_database_url switches based on ENVIRONMENT
- cors_origins_list parses comma-separated string correctly
- tracing_enabled reflects key presence and flag state
"""


from backend.config import Settings


def make_settings(**overrides: str) -> Settings:
    """
    Helper — build a Settings instance with test defaults.

    Bypasses .env file by passing values directly. Any field can be
    overridden via keyword arguments.
    """
    defaults: dict[str, str] = {
        "environment": "test",
        "anthropic_api_key": "sk-ant-test-key",
        "database_url": "postgresql+asyncpg://airp:airp@localhost:5432/airp",
        "database_test_url": "postgresql+asyncpg://airp:airp@localhost:5432/airp_test",
    }
    defaults.update(overrides)
    result = Settings.model_construct(**defaults)
    assert isinstance(result, Settings)
    return result


def test_settings_loads_required_fields() -> None:
    """Settings initialises without error when required fields are provided."""
    s = make_settings()
    assert s.anthropic_api_key == "sk-ant-test-key"
    assert s.environment == "test"


def test_active_database_url_returns_test_url_in_test_env() -> None:
    """active_database_url returns the test DB URL when environment is test."""
    s = make_settings(environment="test")
    assert s.active_database_url == s.database_test_url
    assert "airp_test" in s.active_database_url


def test_active_database_url_returns_primary_url_in_dev() -> None:
    """active_database_url returns the primary DB URL in non-test environments."""
    s = make_settings(environment="development")
    assert s.active_database_url == s.database_url


def test_cors_origins_list_parses_single_origin() -> None:
    """Single CORS origin is returned as a one-item list."""
    s = make_settings(cors_origins="http://localhost:5173")
    assert s.cors_origins_list == ["http://localhost:5173"]


def test_cors_origins_list_parses_multiple_origins() -> None:
    """Multiple comma-separated CORS origins are split and stripped correctly."""
    s = make_settings(cors_origins="http://localhost:5173,https://airp.vercel.app")
    assert s.cors_origins_list == [
        "http://localhost:5173",
        "https://airp.vercel.app",
    ]


def test_is_production_false_in_development() -> None:
    """is_production is False for development environment."""
    s = make_settings(environment="development")
    assert s.is_production is False


def test_is_production_true_in_production() -> None:
    """is_production is True only for production environment."""
    s = make_settings(environment="production")
    assert s.is_production is True


def test_tracing_enabled_false_when_no_key() -> None:
    """tracing_enabled is False when langsmith_api_key is empty."""
    s = make_settings(langsmith_api_key="")
    assert s.tracing_enabled is False


def test_tracing_enabled_false_when_flag_off() -> None:
    """tracing_enabled is False when tracing flag is disabled, even with key."""
    s = make_settings(langsmith_api_key="ls__somekey", langchain_tracing_v2="false")
    assert s.tracing_enabled is False


def test_tracing_enabled_true_when_key_and_flag() -> None:
    """tracing_enabled is True when both key and flag are set."""
    s = make_settings(langsmith_api_key="ls__somekey", langchain_tracing_v2="true")
    assert s.tracing_enabled is True


def test_debate_rounds_default() -> None:
    """Default debate rounds is 2."""
    s = make_settings()
    assert s.debate_rounds == 2


def test_feature_flags_default_true() -> None:
    """Feature flags default to enabled."""
    s = make_settings()
    assert s.feature_debate_enabled is True
    assert s.feature_pdf_enabled is True
    assert s.feature_rate_limiting is True


def test_environment_accepts_valid_values() -> None:
    """All valid ENVIRONMENT values are accepted without error."""
    for env_value in ["development", "test", "staging", "production"]:
        s = make_settings(environment=env_value)
        assert s.environment == env_value
