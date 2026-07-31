"""Pydantic contracts for reusable price levels and pivots."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LevelKind(str, Enum):
    """Canonical identifiers for computed price levels."""

    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
    PREVIOUS_WEEK_HIGH = "PREVIOUS_WEEK_HIGH"
    PREVIOUS_WEEK_LOW = "PREVIOUS_WEEK_LOW"
    PREVIOUS_MONTH_HIGH = "PREVIOUS_MONTH_HIGH"
    PREVIOUS_MONTH_LOW = "PREVIOUS_MONTH_LOW"
    OPENING_RANGE_HIGH = "OPENING_RANGE_HIGH"
    OPENING_RANGE_LOW = "OPENING_RANGE_LOW"
    DAILY_PIVOT = "DAILY_PIVOT"
    WEEKLY_PIVOT = "WEEKLY_PIVOT"
    CLASSIC_RESISTANCE_1 = "CLASSIC_RESISTANCE_1"
    CLASSIC_RESISTANCE_2 = "CLASSIC_RESISTANCE_2"
    CLASSIC_RESISTANCE_3 = "CLASSIC_RESISTANCE_3"
    CLASSIC_SUPPORT_1 = "CLASSIC_SUPPORT_1"
    CLASSIC_SUPPORT_2 = "CLASSIC_SUPPORT_2"
    CLASSIC_SUPPORT_3 = "CLASSIC_SUPPORT_3"
    CAMARILLA_RESISTANCE_1 = "CAMARILLA_RESISTANCE_1"
    CAMARILLA_RESISTANCE_2 = "CAMARILLA_RESISTANCE_2"
    CAMARILLA_RESISTANCE_3 = "CAMARILLA_RESISTANCE_3"
    CAMARILLA_RESISTANCE_4 = "CAMARILLA_RESISTANCE_4"
    CAMARILLA_SUPPORT_1 = "CAMARILLA_SUPPORT_1"
    CAMARILLA_SUPPORT_2 = "CAMARILLA_SUPPORT_2"
    CAMARILLA_SUPPORT_3 = "CAMARILLA_SUPPORT_3"
    CAMARILLA_SUPPORT_4 = "CAMARILLA_SUPPORT_4"


class PriceLevel(BaseModel):
    """A single named price level reusable by strategies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: LevelKind
    price: float = Field(..., gt=0.0)
    label: str = Field(..., min_length=1)


class ClassicPivotLevels(BaseModel):
    """Classic floor-trader pivot set derived from a prior period H/L/C."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pivot: float = Field(..., gt=0.0)
    resistance_1: float = Field(..., gt=0.0)
    resistance_2: float = Field(..., gt=0.0)
    resistance_3: float = Field(..., gt=0.0)
    support_1: float = Field(..., gt=0.0)
    support_2: float = Field(..., gt=0.0)
    support_3: float = Field(..., gt=0.0)


class CamarillaPivotLevels(BaseModel):
    """Camarilla pivot set derived from a prior period H/L/C."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference_close: float = Field(..., gt=0.0)
    resistance_1: float = Field(..., gt=0.0)
    resistance_2: float = Field(..., gt=0.0)
    resistance_3: float = Field(..., gt=0.0)
    resistance_4: float = Field(..., gt=0.0)
    support_1: float = Field(..., gt=0.0)
    support_2: float = Field(..., gt=0.0)
    support_3: float = Field(..., gt=0.0)
    support_4: float = Field(..., gt=0.0)


class PeriodRange(BaseModel):
    """High/low (and optional close) aggregated over a prior period."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    high: float = Field(..., gt=0.0)
    low: float = Field(..., gt=0.0)
    close: float = Field(..., gt=0.0)
    start: datetime
    end: datetime


class LevelsSnapshot(BaseModel):
    """Full levels snapshot as-of a bar, consumable by downstream strategies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str | None = None
    as_of: datetime
    reference_price: float = Field(..., gt=0.0, description="Close used to split support/resistance")
    opening_range_bars: int = Field(..., ge=1)

    previous_day_high: float = Field(..., gt=0.0)
    previous_day_low: float = Field(..., gt=0.0)
    previous_week_high: float = Field(..., gt=0.0)
    previous_week_low: float = Field(..., gt=0.0)
    previous_month_high: float = Field(..., gt=0.0)
    previous_month_low: float = Field(
        ...,
        gt=0.0,
        description="Included for S/R completeness alongside previous month high",
    )
    opening_range_high: float = Field(..., gt=0.0)
    opening_range_low: float = Field(..., gt=0.0)

    daily_pivot: float = Field(..., gt=0.0)
    weekly_pivot: float = Field(..., gt=0.0)
    classic_pivot: ClassicPivotLevels
    camarilla_pivot: CamarillaPivotLevels

    supports: list[PriceLevel]
    resistances: list[PriceLevel]

    previous_day: PeriodRange
    previous_week: PeriodRange
    previous_month: PeriodRange

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank when provided")
        return cleaned
