"""Pydantic schema for a single OHLCV bar."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class OHLCVRecord(BaseModel):
    """Public contract for one OHLCV row stored in Parquet files."""

    model_config = ConfigDict(extra="forbid")

    date: date
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    close: float = Field(..., ge=0)
    adj_close: float = Field(..., ge=0)
    volume: float = Field(..., ge=0)
