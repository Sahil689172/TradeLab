"""Schemas for the Darvas Box strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.darvas.schemas import DarvasBox, DarvasBoxSnapshot
from app.strategy_engine.models import SignalType


class DarvasStopSource(str, Enum):
    LOWER_BOX = "LOWER_BOX"
    UPPER_BOX = "UPPER_BOX"
    ATR = "ATR"


class DarvasSetup(BaseModel):
    """Latest-bar Darvas setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    breakout: bool
    breakdown: bool
    volume_expansion: bool
    ema_trend_bullish: bool
    snapshot: DarvasBoxSnapshot
    reasons: list[str] = Field(default_factory=list)


class DarvasBoxPlan(BaseModel):
    """Trade plan with current Darvas box context."""

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
    stop_source: DarvasStopSource
    reasons: list[str] = Field(..., min_length=1)
    current_box: DarvasBox | None = None
    setup: DarvasSetup
    timestamp: datetime
