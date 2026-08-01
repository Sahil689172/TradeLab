"""Schemas for the Donchian Channel strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.indicators.donchian import DonchianSnapshot
from app.strategy_engine.models import SignalType


class DonchianStopSource(str, Enum):
    """Stop-loss selection priority source."""

    MIDDLE_CHANNEL = "MIDDLE_CHANNEL"
    ATR = "ATR"
    PREVIOUS_SWING = "PREVIOUS_SWING"


class DonchianExitReason(str, Enum):
    """Exit evaluation outcomes for open Turtle-style trades."""

    NONE = "NONE"
    EXIT_CHANNEL = "EXIT_CHANNEL"
    ATR_TRAILING = "ATR_TRAILING"
    ATR_EXIT = "ATR_EXIT"
    TREND_BEARISH = "TREND_BEARISH"
    TREND_BULLISH = "TREND_BULLISH"


class DonchianConfidenceBreakdown(BaseModel):
    """Explainable confidence components on a 0–100 scale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_breakout: float = Field(..., ge=0.0)
    trend: float = Field(..., ge=0.0)
    volume: float = Field(..., ge=0.0)
    market_structure: float = Field(..., ge=0.0)
    atr: float = Field(..., ge=0.0)
    total: float = Field(..., ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class DonchianSetup(BaseModel):
    """Latest-bar Donchian setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    breakout_above: bool
    breakout_below: bool
    false_breakout: bool
    ema_bullish: bool
    volume_ok: bool
    structure_ok: bool
    atr_ok: bool
    cooldown_ok: bool
    sideways_blocked: bool
    snapshot: DonchianSnapshot
    reasons: list[str] = Field(default_factory=list)


class DonchianExitAssessment(BaseModel):
    """Exit-rule evaluation for an open Donchian position."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    should_exit: bool
    reason: DonchianExitReason
    detail: str
    exit_price: float | None = None


class DonchianPlan(BaseModel):
    """Full Donchian / Turtle trade plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str
    symbol: str
    entry_price: float = Field(..., gt=0.0)
    direction: TradeDirection
    signal: SignalType
    upper_channel: float
    lower_channel: float
    middle_channel: float
    entry_upper: float
    entry_lower: float
    stop_loss: float = Field(..., gt=0.0)
    take_profit_1: float | None = Field(default=None, gt=0.0)
    take_profit_2: float | None = Field(default=None, gt=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_reward: float = Field(..., ge=0.0)
    expected_holding_bars: int = Field(..., ge=0)
    holding_note: str
    stop_source: DonchianStopSource
    target_note: str
    reasons: list[str] = Field(..., min_length=1)
    market_structure: TrendDirection
    snapshot: DonchianSnapshot
    confidence_breakdown: DonchianConfidenceBreakdown
    setup: DonchianSetup
    timestamp: datetime
