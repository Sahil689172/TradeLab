"""Standard API response models for TradeLab."""

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Structured error information returned to API clients."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., description="Stable machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    details: Any | None = Field(
        default=None,
        description="Optional validation or contextual error details",
    )


class ErrorResponse(BaseModel):
    """Uniform error envelope for failed requests."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(default=False, description="Always false for errors")
    error: ErrorDetail


class SuccessResponse(BaseModel, Generic[T]):
    """Uniform success envelope for successful requests."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(default=True, description="Always true for success")
    data: T
    message: str | None = Field(
        default=None,
        description="Optional human-readable success message",
    )


class HealthData(BaseModel):
    """Payload for the health check endpoint."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="Overall health status, e.g. healthy")
    application: str = Field(..., description="Application name")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Runtime environment")
    database: str = Field(
        ...,
        description="Database connectivity status (connected / disconnected)",
    )
    timestamp: datetime = Field(
        ...,
        description="UTC timestamp when the health check was evaluated",
    )


class HealthResponse(SuccessResponse[HealthData]):
    """Success envelope wrapping health check data."""

    pass


class RootData(BaseModel):
    """Payload for the API root endpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    description: str
    documentation: dict[str, str]


class RootResponse(SuccessResponse[RootData]):
    """Success envelope wrapping root endpoint data."""

    pass


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)
