"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings.

    Values are loaded from environment variables and an optional ``.env`` file.
    Configuration is kept separate from application code.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="TradeLab", description="Product / service name")
    app_version: str = Field(default="0.1.0", description="Application version")
    app_description: str = Field(
        default="TradeLab Quant Engine — Indian Stock Market Analysis Platform",
        description="Short product description",
    )
    app_env: Literal["development", "staging", "production", "test"] = Field(
        default="development",
        description="Runtime environment name",
    )
    debug: bool = Field(default=True, description="Enable debug mode")
    api_v1_prefix: str = Field(default="/api/v1", description="Versioned API prefix")

    # Server
    host: str = Field(default="0.0.0.0", description="Bind host")
    port: int = Field(default=8000, ge=1, le=65535, description="Bind port")

    # Market data storage (Phase A2.1)
    metadata_database_url: str = Field(
        default="sqlite:///backend/data/metadata.db",
        description="SQLite URL for market metadata (company_metadata, ingestion_state)",
    )
    parquet_storage_dir: Path = Field(
        default=Path("backend/data/ohlcv"),
        description="Directory for per-symbol OHLCV Parquet files",
    )
    log_directory: Path = Field(
        default=Path("backend/data/logs"),
        description="Directory for application and storage logs",
    )

    # Application database (health checks; aligned with metadata DB by default)
    database_url: str = Field(
        default="sqlite:///backend/data/metadata.db",
        description="SQLAlchemy database URL used by the FastAPI app",
    )

    # Ingestion (Phase A2.2)
    bootstrap_history_years: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of years requested for first-time bootstrap downloads",
    )
    yfinance_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout for Yahoo Finance provider requests",
    )
    bootstrap_rate_limit_seconds: float = Field(
        default=0.75,
        ge=0.0,
        le=10.0,
        description="Delay between Yahoo Finance download requests during bulk bootstrap",
    )
    bootstrap_max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts per symbol during bulk bootstrap",
    )
    bootstrap_retry_base_delay_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Base delay in seconds for exponential backoff between bootstrap retries",
    )

    # Collaboration rooms (chat + shared paper portfolio)
    collab_enabled: bool = Field(
        default=True,
        description="Enable collaborative rooms and the room websocket",
    )
    chat_history_limit: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Messages replayed to a client when it joins a room",
    )
    room_default_capacity: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Default member capacity for a new room",
    )

    # AI assistant (Gemini primary, Groq fallback)
    ai_enabled: bool = Field(default=True, description="Enable the grounded room assistant")
    ai_primary_provider: Literal["gemini", "groq"] = Field(
        default="gemini",
        description="Provider tried first; the other becomes the fallback",
    )
    gemini_api_key: str | None = Field(default=None, description="Google Gemini API key")
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model id used for room replies",
    )
    groq_api_key: str | None = Field(default=None, description="Groq API key (fallback provider)")
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model id used for fallback replies",
    )
    ai_trigger: str = Field(
        default="@ai",
        description="Token in a chat message that routes it to the assistant",
    )
    ai_timeout_seconds: int = Field(
        default=45,
        ge=1,
        le=300,
        description="HTTP timeout per LLM provider request",
    )
    ai_max_tool_iterations: int = Field(
        default=5,
        ge=1,
        le=12,
        description="Maximum tool-call rounds before giving up on a turn",
    )
    ai_max_output_tokens: int = Field(
        default=800,
        ge=64,
        le=8192,
        description="Maximum tokens in a single AI reply (keeps cost predictable)",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Root log level")
    log_format: Literal["console", "json"] = Field(
        default="console",
        description="Log formatter style",
    )

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize log level to uppercase standard names."""
        normalized = value.upper().strip()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized

    @property
    def is_development(self) -> bool:
        """Return True when running in the development environment."""
        return self.app_env == "development"

    @property
    def is_test(self) -> bool:
        """Return True when running in the test environment."""
        return self.app_env == "test"

    @property
    def is_sqlite(self) -> bool:
        """Return True when the configured database is SQLite."""
        return self.database_url.startswith("sqlite")

    @property
    def is_ai_configured(self) -> bool:
        """Return True when at least one LLM provider has an API key."""
        return bool(self.gemini_api_key or self.groq_api_key)

    @property
    def metadata_db_path(self) -> Path:
        """Return the filesystem path to the metadata SQLite database file."""
        return _sqlite_url_to_path(self.metadata_database_url)

    @property
    def data_root(self) -> Path:
        """Return the root ``data`` directory containing metadata and ohlcv."""
        return self.metadata_db_path.parent


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Using a cached factory keeps configuration loading cheap and makes
    dependency injection straightforward in FastAPI.
    """
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache (useful in tests)."""
    get_settings.cache_clear()


def _sqlite_url_to_path(database_url: str) -> Path:
    """Convert a ``sqlite:///`` URL to a filesystem ``Path``."""
    if not database_url.startswith("sqlite:///"):
        msg = f"Expected sqlite URL, got: {database_url}"
        raise ValueError(msg)
    raw = database_url.removeprefix("sqlite:///")
    return Path(raw)
