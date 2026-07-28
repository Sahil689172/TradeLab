"""Pydantic schema for company metadata."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CompanyMetadata(BaseModel):
    """Public contract for company metadata stored in SQLite."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str = Field(..., min_length=1, max_length=32)
    company_name: str = Field(..., min_length=1, max_length=256)
    sector: str | None = Field(default=None, max_length=128)
    industry: str | None = Field(default=None, max_length=128)
    exchange: str = Field(..., min_length=1, max_length=32)
    currency: str = Field(default="INR", min_length=1, max_length=8)
    market_cap: float | None = Field(default=None, ge=0)
    market_cap_date: date | None = None
    last_updated: datetime
