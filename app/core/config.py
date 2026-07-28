"""Application configuration loaded from environment variables."""

from functools import lru_cache
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

    # Database
    database_url: str = Field(
        default="sqlite:///./data/tradlab.db",
        description="SQLAlchemy database URL",
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
