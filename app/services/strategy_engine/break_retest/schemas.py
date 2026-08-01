"""Schemas for reusable Break & Retest detection."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.risk_engine.schemas import TradeDirection


class BreakRetestStage(str, Enum):
    """Progress through a break → retest → confirmation sequence."""

    NONE = "NONE"
    BROKEN = "BROKEN"
    RETESTED = "RETESTED"
    FAILED_RETEST = "FAILED_RETEST"
    CONFIRMED = "CONFIRMED"


class BreakEvent(BaseModel):
    """Detected break of a level."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: TradeDirection
    level: float = Field(..., gt=0.0)
    bar_index: int = Field(..., ge=0)
    close: float


class RetestEvent(BaseModel):
    """Detected retest of a previously broken level."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: TradeDirection
    level: float = Field(..., gt=0.0)
    bar_index: int = Field(..., ge=0)
    retest_low: float = Field(..., gt=0.0)
    retest_high: float = Field(..., gt=0.0)
    successful: bool


class ConfirmationCandle(BaseModel):
    """Bullish or bearish confirmation candle assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bullish: bool
    bearish: bool
    body_ratio: float = Field(..., ge=0.0)
    open: float
    high: float
    low: float
    close: float
    confirmed: bool


class BreakRetestSequence(BaseModel):
    """Full sequence snapshot for strategy consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: TradeDirection
    stage: BreakRetestStage
    level: float = Field(..., ge=0.0)
    break_event: BreakEvent | None = None
    retest_event: RetestEvent | None = None
    confirmation: ConfirmationCandle | None = None
    false_breakout: bool = False
    reasons: list[str] = Field(default_factory=list)
