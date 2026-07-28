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
