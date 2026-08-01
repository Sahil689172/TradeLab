"""Schemas for the Opening Range Breakout strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategy_engine.models import SignalType


class ORBStopSource(str, Enum):
    """Stop-loss selection priority source."""

    OPENING_RANGE = "OPENING_RANGE"
    PREVIOUS_SWING = "PREVIOUS_SWING"
    ATR = "ATR"


class OpeningRangeLevels(BaseModel):
    """Opening range geometry for the current session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    high: float = Field(..., gt=0.0)
    low: float = Field(..., gt=0.0)
    mid: float = Field(..., gt=0.0)
    bars: int = Field(..., ge=1)
    minutes: int = Field(..., ge=1)
    range_pct: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def validate_geometry(self) -> OpeningRangeLevels:
        if self.high < self.low:
            raise ValueError("opening range high must be >= low")
        expected_mid = (self.high + self.low) / 2.0
        if abs(self.mid - expected_mid) > 1e-9:
            raise ValueError("opening range mid must equal (high + low) / 2")
        return self


class ORBConfidenceBreakdown(BaseModel):
    """Explainable confidence components on a 0–100 scale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    opening_range_break: float = Field(..., ge=0.0)
    volume: float = Field(..., ge=0.0)
    trend: float = Field(..., ge=0.0)
    structure: float = Field(..., ge=0.0)
    momentum: float = Field(..., ge=0.0)
    total: float = Field(..., ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class ORBSetupAssessment(BaseModel):
    """Latest-bar ORB setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    breakout: bool
    relative_volume_ok: bool
    structure_ok: bool
    trend_ok: bool
    momentum_ok: bool
    already_traded: bool
    range_ok: bool
    late_breakout: bool
    gap_blocked: bool
    relative_volume: float | None = None
    reasons: list[str] = Field(default_factory=list)


class OpeningRangeBreakoutPlan(BaseModel):
    """Full ORB trade plan with explainable metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str
    symbol: str
    entry_price: float = Field(..., gt=0.0)
    direction: TradeDirection
    signal: SignalType
    stop_loss: float = Field(..., gt=0.0)
    take_profit_1: float = Field(..., gt=0.0)
    take_profit_2: float = Field(..., gt=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_reward: float = Field(..., ge=0.0)
    expected_holding_bars: int = Field(..., ge=0)
    holding_note: str = "Intraday only — exit before market close"
    stop_source: ORBStopSource
    reasons: list[str] = Field(..., min_length=1)
    market_structure: TrendDirection
    opening_range: OpeningRangeLevels
    confidence_breakdown: ORBConfidenceBreakdown
    setup: ORBSetupAssessment
    timestamp: datetime
