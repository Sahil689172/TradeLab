"""Pydantic schema for ingestion state."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class IngestionState(BaseModel):
    """Public contract for per-symbol ingestion tracking state."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str = Field(..., min_length=1, max_length=32)
    first_available_date: date | None = None
    last_available_date: date | None = None
    last_fetch_timestamp: datetime | None = None
    last_fetch_status: str | None = Field(default=None, max_length=32)
    row_count: int | None = Field(default=None, ge=0)
