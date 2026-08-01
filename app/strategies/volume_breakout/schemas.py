"""Schemas for the Volume Breakout strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.indicators.volume_analysis import VolumeStatistics
from app.strategy_engine.models import SignalType


class VolumeBreakoutStopSource(str, Enum):
    """Stop-loss selection priority source."""

    PREVIOUS_SWING = "PREVIOUS_SWING"
    ATR = "ATR"
    VWAP = "VWAP"


class VolumeBreakoutConfidenceBreakdown(BaseModel):
    """Explainable confidence components on a 0–100 scale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level_break: float = Field(..., ge=0.0)
    relative_volume: float = Field(..., ge=0.0)
    structure: float = Field(..., ge=0.0)
    vwap: float = Field(..., ge=0.0)
    candle_quality: float = Field(..., ge=0.0)
    total: float = Field(..., ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class VolumeBreakoutSetupAssessment(BaseModel):
    """Latest-bar volume breakout setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    broke_resistance: bool
    broke_support: bool
    relative_volume_ok: bool
    above_average_volume: bool
    structure_ok: bool
    vwap_ok: bool
    candle_ok: bool
    late_session: bool
    false_breakout: bool
    resistance_level: float | None = None
    support_level: float | None = None
    volume_stats: VolumeStatistics
    reasons: list[str] = Field(default_factory=list)


class VolumeBreakoutPlan(BaseModel):
    """Full volume breakout trade plan with volume statistics."""

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
    stop_source: VolumeBreakoutStopSource
    target_2_label: str
    reasons: list[str] = Field(..., min_length=1)
    market_structure: TrendDirection
    volume_stats: VolumeStatistics
    confidence_breakdown: VolumeBreakoutConfidenceBreakdown
    setup: VolumeBreakoutSetupAssessment
    timestamp: datetime
