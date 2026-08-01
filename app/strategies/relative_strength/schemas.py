"""Schemas for Relative Strength scoring, ranking, screener, and trades."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.risk_engine.schemas import TradeDirection
from app.strategy_engine.models import SignalType


class RelativeStrengthScore(BaseModel):
    """Per-symbol RS metrics vs benchmark (not RSI)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    as_of: datetime
    return_3m: float
    return_6m: float
    return_12m: float
    benchmark_return_3m: float
    benchmark_return_6m: float
    benchmark_return_12m: float
    rs_3m: float = Field(..., description="Stock return − benchmark return (3m)")
    rs_6m: float
    rs_12m: float
    strength_score: float = Field(..., description="Weighted blend of RS windows")
    relative_momentum: float = Field(..., description="Near-term RS acceleration")
    sector: str | None = None
    sector_strength: float | None = None


class RankedSymbol(BaseModel):
    """One row in a cross-sectional RS ranking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    rank: int = Field(..., ge=1)
    previous_rank: int | None = None
    percentile: float = Field(..., ge=0.0, le=1.0)
    score: RelativeStrengthScore
    rank_change: int | None = Field(
        default=None,
        description="previous_rank − rank (positive = improving)",
    )


class RankBucket(str, Enum):
    TOP_10 = "TOP_10"
    TOP_25 = "TOP_25"
    TOP_50 = "TOP_50"
    TOP_100 = "TOP_100"
    STRONGEST = "STRONGEST"


class UniverseRanking(BaseModel):
    """Full ranked NIFTY500 (or subset) snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: datetime
    benchmark_symbol: str
    universe_size: int = Field(..., ge=0)
    ranked: list[RankedSymbol]
    top_10: list[RankedSymbol] = Field(default_factory=list)
    top_25: list[RankedSymbol] = Field(default_factory=list)
    top_50: list[RankedSymbol] = Field(default_factory=list)
    top_100: list[RankedSymbol] = Field(default_factory=list)
    strongest: list[RankedSymbol] = Field(default_factory=list)


class ScreenerResult(BaseModel):
    """Relative Strength Screener output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: datetime
    benchmark_symbol: str
    top_ranked: list[RankedSymbol]
    worst_ranked: list[RankedSymbol]
    fastest_improving: list[RankedSymbol]
    fastest_weakening: list[RankedSymbol]
    ranking: UniverseRanking


class RelativeStrengthSetup(BaseModel):
    """Single-symbol trade setup assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: SignalType
    direction: TradeDirection | None = None
    in_top_percentile: bool
    ema_trend_bullish: bool
    volume_healthy: bool
    above_vwap: bool
    current_rank: int | None = None
    previous_rank: int | None = None
    percentile: float | None = None
    reasons: list[str] = Field(default_factory=list)


class RelativeStrengthPlan(BaseModel):
    """Trade plan enriched with RS ranking metadata."""

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
    reasons: list[str] = Field(..., min_length=1)
    current_rank: int | None = None
    previous_rank: int | None = None
    strength_score: float | None = None
    momentum_score: float | None = None
    benchmark_comparison: str | None = None
    sector_comparison: str | None = None
    setup: RelativeStrengthSetup
    timestamp: datetime
