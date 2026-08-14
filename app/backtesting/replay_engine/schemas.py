"""Replay configuration and per-step / run result schemas."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType


class ReplaySpeed(str, Enum):
    """How fast the scheduler advances between candles."""

    REALTIME = "realtime"
    FAST = "fast"


class ReplayConfig(BaseModel):
    """Tunable knobs for a historical replay run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbols: list[str] = Field(..., min_length=1)
    strategy_names: list[str] = Field(default_factory=lambda: ["ema_trend"])
    start_date: date | None = None
    end_date: date | None = None
    speed: ReplaySpeed = ReplaySpeed.FAST
    timeframe: str = "1 Day"
    storage_dir: Path | None = None
    realtime_sleep_seconds: float = Field(default=0.0, ge=0.0)
    min_history_bars: int = Field(
        default=60,
        ge=1,
        description=(
            "Minimum bars before evaluation. Raised automatically to each "
            "strategy's min_history_bars when higher."
        ),
    )
    # Cap candles after filtering (tests / smoke runs)
    max_steps: int | None = Field(default=None, ge=1)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip().upper() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("symbols must not be empty")
        # Preserve order, drop duplicates
        seen: set[str] = set()
        ordered: list[str] = []
        for symbol in cleaned:
            if symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
        return ordered

    @field_validator("strategy_names")
    @classmethod
    def normalize_strategies(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("strategy_names must not be empty")
        return cleaned


class ReplayStepResult(BaseModel):
    """Engine output for one replayed candle × strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    symbol: str
    strategy_name: str
    current_close: float = Field(..., gt=0.0)
    current_open: float | None = Field(default=None, gt=0.0)
    current_high: float | None = Field(default=None, gt=0.0)
    current_low: float | None = Field(default=None, gt=0.0)
    replay_index: int = Field(..., ge=0)
    signal: SignalType
    confidence: float = Field(..., ge=0.0, le=100.0)
    stop_loss: float = Field(..., gt=0.0)
    target_1: float = Field(..., gt=0.0)
    target_2: float = Field(..., gt=0.0)
    expected_holding_period: int = Field(..., ge=0)
    recommendation: TradeRecommendation


class ReplayResult(BaseModel):
    """Aggregate result for one or more symbols."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    started_at: datetime
    completed_at: datetime
    config: ReplayConfig
    steps: list[ReplayStepResult] = Field(default_factory=list)
    candles_replayed: int = Field(default=0, ge=0)
    recommendations_generated: int = Field(default=0, ge=0)
    symbols: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
