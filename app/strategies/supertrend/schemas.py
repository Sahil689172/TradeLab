"""Schemas for the SuperTrend strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.indicators.supertrend import SuperTrendSnapshot
from app.strategy_engine.models import SignalType


class SuperTrendStopSource(str, Enum):
    """Stop-loss selection priority source."""

    SUPERTREND = "SUPERTREND"
    PREVIOUS_SWING = "PREVIOUS_SWING"
    ATR = "ATR"


class SuperTrendConfidenceBreakdown(BaseModel):
    """Explainable confidence components on a 0–100 scale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_change: float = Field(..., ge=0.0)
    ema_confirmation: float = Field(..., ge=0.0)
    market_structure: float = Field(..., ge=0.0)
    relative_volume: float = Field(..., ge=0.0)
    atr_health: float = Field(..., ge=0.0)
    total: float = Field(..., ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class SuperTrendSetup(BaseModel):
    """Latest-bar SuperTrend setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    trend_flip_bullish: bool
    trend_flip_bearish: bool
    close_above_supertrend: bool
    close_below_supertrend: bool
    ema_bullish: bool
    volume_ok: bool
    structure_ok: bool
    atr_ok: bool
    sideways_blocked: bool
    snapshot: SuperTrendSnapshot
    reasons: list[str] = Field(default_factory=list)


class SuperTrendPlan(BaseModel):
    """Full SuperTrend trade plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str
    symbol: str
    entry_price: float = Field(..., gt=0.0)
    direction: TradeDirection
    signal: SignalType
    trend_direction: TrendDirection
    stop_loss: float = Field(..., gt=0.0)
    take_profit_1: float = Field(..., gt=0.0)
    take_profit_2: float = Field(..., gt=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_reward: float = Field(..., ge=0.0)
    expected_holding_bars: int = Field(..., ge=0)
    holding_note: str
    stop_source: SuperTrendStopSource
    target_2_label: str
    reasons: list[str] = Field(..., min_length=1)
    market_structure: TrendDirection
    snapshot: SuperTrendSnapshot
    confidence_breakdown: SuperTrendConfidenceBreakdown
    setup: SuperTrendSetup
    timestamp: datetime
