"""Schemas for the Previous Day High/Low (Magic Box) strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategy_engine.models import SignalType


class SetupSide(str, Enum):
    """Which previous-day level the setup interacts with."""

    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"


class SetupStage(str, Enum):
    """Progress through the Magic Box sequence."""

    IDLE = "IDLE"
    APPROACHED = "APPROACHED"
    BROKEN = "BROKEN"
    RETESTED = "RETESTED"
    FAILED_RETEST = "FAILED_RETEST"
    ENTRY = "ENTRY"


class StopSource(str, Enum):
    """Stop-loss selection priority source."""

    PREVIOUS_CANDLE = "PREVIOUS_CANDLE"
    PREVIOUS_DAY_LEVEL = "PREVIOUS_DAY_LEVEL"
    ATR = "ATR"


class LevelsUsed(BaseModel):
    """Previous-day and target levels consumed by the plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    previous_day_high: float = Field(..., gt=0.0)
    previous_day_low: float = Field(..., gt=0.0)
    entry_level: float = Field(..., gt=0.0)
    target_2_level: float | None = Field(default=None, gt=0.0)
    target_2_label: str | None = None


class ConfidenceBreakdown(BaseModel):
    """Explainable confidence components on a 0–100 scale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level_break: float = Field(..., ge=0.0)
    retest: float = Field(..., ge=0.0)
    relative_volume: float = Field(..., ge=0.0)
    confirmation_candle: float = Field(..., ge=0.0)
    market_structure: float = Field(..., ge=0.0)
    total: float = Field(..., ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class SetupAssessment(BaseModel):
    """Latest-bar assessment of a long or short Magic Box setup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    side: SetupSide
    stage: SetupStage
    direction: TradeDirection | None = None
    signal: SignalType
    approached: bool
    broken: bool
    retested: bool
    failed_retest: bool
    confirmation_candle: bool
    relative_volume_ok: bool
    structure_ok: bool
    relative_volume: float | None = None
    entry_index: int | None = None
    break_index: int | None = None
    retest_index: int | None = None
    reasons: list[str] = Field(default_factory=list)


class PreviousDayBreakoutPlan(BaseModel):
    """Full Magic Box trade plan including structure and levels metadata."""

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
    holding_note: str = "Intraday only — close before market close"
    stop_source: StopSource
    reasons: list[str] = Field(..., min_length=1)
    market_structure: TrendDirection
    levels_used: LevelsUsed
    confidence_breakdown: ConfidenceBreakdown
    setup: SetupAssessment
    timestamp: datetime
