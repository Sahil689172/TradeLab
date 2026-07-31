"""Pydantic contracts for deterministic market structure analysis."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SwingType(str, Enum):
    """Pivot classification for a confirmed swing point."""

    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"


class StructureLabel(str, Enum):
    """Relative structure label versus the previous same-type swing."""

    HIGHER_HIGH = "HIGHER_HIGH"
    HIGHER_LOW = "HIGHER_LOW"
    LOWER_HIGH = "LOWER_HIGH"
    LOWER_LOW = "LOWER_LOW"
    EQUAL_HIGH = "EQUAL_HIGH"
    EQUAL_LOW = "EQUAL_LOW"


class TrendDirection(str, Enum):
    """Market structure trend state."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"


class StructureEventType(str, Enum):
    """Discrete structure events derived from swing breaks."""

    BREAK_OF_STRUCTURE = "BREAK_OF_STRUCTURE"
    CHANGE_OF_CHARACTER = "CHANGE_OF_CHARACTER"


class SwingPoint(BaseModel):
    """A confirmed swing high or swing low."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(..., ge=0, description="Row index in the source OHLCV frame")
    timestamp: datetime
    price: float = Field(..., gt=0.0)
    swing_type: SwingType
    structure_label: StructureLabel | None = Field(
        default=None,
        description="Relative label vs prior same-type swing; None for the first of that type",
    )
    confirmation_index: int = Field(
        ...,
        ge=0,
        description="Bar index at which the swing becomes confirmed (index + swing_length)",
    )


class StructureEvent(BaseModel):
    """Break of Structure or Change of Character event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(..., ge=0)
    timestamp: datetime
    event_type: StructureEventType
    direction: TrendDirection = Field(
        ...,
        description="Bullish or bearish bias of the event (never SIDEWAYS)",
    )
    broken_level: float = Field(..., gt=0.0)
    reference_swing_index: int = Field(..., ge=0)
    confirmation_price: float = Field(..., gt=0.0, description="Close that confirmed the break")

    @field_validator("direction")
    @classmethod
    def direction_must_be_directional(cls, value: TrendDirection) -> TrendDirection:
        if value is TrendDirection.SIDEWAYS:
            raise ValueError("Structure event direction must be BULLISH or BEARISH")
        return value


class MarketStructureResult(BaseModel):
    """Reusable market-structure snapshot for downstream strategies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str | None = None
    swing_length: int = Field(..., ge=1)
    bar_count: int = Field(..., ge=0)
    trend: TrendDirection
    swings: list[SwingPoint]
    events: list[StructureEvent]
    last_swing_high: SwingPoint | None = None
    last_swing_low: SwingPoint | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank when provided")
        return cleaned
