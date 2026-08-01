"""Schemas for quantitative Momentum scoring, ranking, and trades."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.risk_engine.schemas import TradeDirection
from app.strategy_engine.models import SignalType


class MomentumScore(BaseModel):
    """Per-symbol quantitative momentum metrics (not RSI)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    as_of: datetime
    return_1m: float
    return_3m: float
    return_6m: float
    return_12m: float
    momentum_score: float = Field(..., description="Weighted blend of period returns")
    acceleration: float = Field(..., description="Near-term minus medium-term return")
    persistence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of lookback windows with positive return",
    )
    relative_strength: float = Field(
        ...,
        description="Stock 6m return − benchmark 6m return",
    )


class RankedMomentum(BaseModel):
    """One row in a cross-sectional momentum ranking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    rank: int = Field(..., ge=1)
    percentile: float = Field(..., ge=0.0, le=1.0)
    score: MomentumScore


class MomentumUniverseRanking(BaseModel):
    """Full ranked momentum snapshot for a universe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: datetime
    universe_size: int = Field(..., ge=0)
    ranked: list[RankedMomentum]
    top_10: list[RankedMomentum] = Field(default_factory=list)
    top_25: list[RankedMomentum] = Field(default_factory=list)
    top_50: list[RankedMomentum] = Field(default_factory=list)
    portfolio: list[RankedMomentum] = Field(
        default_factory=list,
        description="Top-percentile sleeve for portfolio construction",
    )


class MomentumSetup(BaseModel):
    """Single-symbol momentum trade setup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    top_momentum: bool
    ema_trend_bullish: bool
    relative_strength_ok: bool
    above_vwap: bool
    volume_healthy: bool
    momentum_score: float | None = None
    relative_strength: float | None = None
    momentum_rank: int | None = None
    reasons: list[str] = Field(default_factory=list)


class MomentumPlan(BaseModel):
    """Trade plan enriched with momentum ranking metadata."""

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
    holding_estimate: str = "Momentum sleeve — rebalance monthly"
    reasons: list[str] = Field(..., min_length=1)
    momentum_score: float | None = None
    relative_strength: float | None = None
    momentum_rank: int | None = None
    setup: MomentumSetup
    timestamp: datetime
