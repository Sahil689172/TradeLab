"""Schemas for the CPR strategy."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.levels.schemas import CPRLevels
from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategy_engine.models import SignalType


class CPRWidthClass(str, Enum):
    """CPR width regime for the session."""

    NARROW = "NARROW"
    WIDE = "WIDE"


class CPRPositionClass(str, Enum):
    """Price location relative to the CPR band."""

    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"


class CPRTradeMode(str, Enum):
    """Strategy mode derived from CPR width."""

    TREND = "TREND"  # Narrow CPR → breakout / continuation
    REVERSAL = "REVERSAL"  # Wide CPR → support / resistance reversal


class CPRStopSource(str, Enum):
    """Stop-loss selection priority source."""

    CPR_LEVEL = "CPR_LEVEL"
    PREVIOUS_SWING = "PREVIOUS_SWING"
    ATR = "ATR"


class CPRClassification(BaseModel):
    """Stored daily CPR market classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    width: CPRWidthClass
    position: CPRPositionClass
    virgin: bool
    mode: CPRTradeMode
    width_pct: float = Field(..., ge=0.0)
    reasons: list[str] = Field(default_factory=list)


class CPRConfidenceBreakdown(BaseModel):
    """Explainable confidence components on a 0–100 scale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpr_position: float = Field(..., ge=0.0)
    vwap_confirmation: float = Field(..., ge=0.0)
    structure: float = Field(..., ge=0.0)
    relative_volume: float = Field(..., ge=0.0)
    mode_alignment: float = Field(..., ge=0.0)
    total: float = Field(..., ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class CPRSetupAssessment(BaseModel):
    """Latest-bar CPR setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    price_above_cpr: bool
    price_below_cpr: bool
    vwap_ok: bool
    structure_ok: bool
    relative_volume_ok: bool
    mode_aligned: bool
    relative_volume: float | None = None
    classification: CPRClassification
    reasons: list[str] = Field(default_factory=list)


class CPRTradePlan(BaseModel):
    """Full CPR trade plan with classification metadata."""

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
    stop_source: CPRStopSource
    target_1_label: str
    target_2_label: str
    reasons: list[str] = Field(..., min_length=1)
    market_structure: TrendDirection
    cpr: CPRLevels
    classification: CPRClassification
    confidence_breakdown: CPRConfidenceBreakdown
    setup: CPRSetupAssessment
    timestamp: datetime
