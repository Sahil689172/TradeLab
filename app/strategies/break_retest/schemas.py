"""Schemas for the Break & Retest strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.break_retest.schemas import BreakRetestSequence
from app.strategy_engine.models import SignalType


class BreakRetestStopSource(str, Enum):
    RETEST_LOW = "RETEST_LOW"
    RETEST_HIGH = "RETEST_HIGH"
    ATR = "ATR"


class BreakRetestSetup(BaseModel):
    """Latest setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    volume_ok: bool
    structure_ok: bool
    long_sequence: BreakRetestSequence
    short_sequence: BreakRetestSequence
    reasons: list[str] = Field(default_factory=list)


class BreakRetestPlan(BaseModel):
    """Trade plan for a confirmed break & retest entry."""

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
    stop_source: BreakRetestStopSource
    reasons: list[str] = Field(..., min_length=1)
    market_structure: TrendDirection
    sequence: BreakRetestSequence
    setup: BreakRetestSetup
    timestamp: datetime
