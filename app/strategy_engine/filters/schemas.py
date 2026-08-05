"""Schemas for the strategy filter framework."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.strategy_engine.models import SignalType, TradePlan


class StrategyRecommendation(BaseModel):
    """Portable recommendation DTO that flows through the filter pipeline.

    Strategies do not depend on this type. Callers may build it from a
    ``TradePlan`` (or any upstream artifact) before entering the pipeline.
    Filters may annotate ``metadata`` / ``filter_notes`` without strategies
    knowing which filters exist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = Field(..., min_length=1, max_length=128)
    symbol: str = Field(..., min_length=1, max_length=32)
    timestamp: datetime | None = None
    signal: SignalType
    entry_price: float = Field(..., gt=0.0)
    stop_loss: float = Field(..., gt=0.0)
    take_profit_1: float = Field(..., gt=0.0)
    take_profit_2: float = Field(..., gt=0.0)
    holding_period: int = Field(..., ge=0)
    risk_reward: float = Field(..., ge=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    filter_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    rejected: bool = False
    rejection_reason: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank")
        return cleaned

    @field_validator("strategy_name")
    @classmethod
    def normalize_strategy_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("strategy_name must not be blank")
        return cleaned

    @classmethod
    def from_trade_plan(
        cls,
        plan: TradePlan,
        *,
        timestamp: datetime | None = None,
    ) -> StrategyRecommendation:
        """Adapt a strategy-engine ``TradePlan`` into pipeline input."""
        return cls(
            strategy_name=plan.strategy_name,
            symbol=plan.symbol,
            timestamp=timestamp,
            signal=plan.signal,
            entry_price=plan.entry_price,
            stop_loss=plan.stop_loss,
            take_profit_1=plan.take_profit_1,
            take_profit_2=plan.take_profit_2,
            holding_period=plan.holding_period,
            risk_reward=plan.risk_reward,
            confidence=plan.confidence,
            reasons=list(plan.reasons),
        )


class FilterConfig(BaseModel):
    """Declarative knobs for a registered filter instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1)
    enabled: bool = True
    priority: int = Field(
        default=100,
        description="Lower values run earlier in the pipeline",
    )


class FilterStepResult(BaseModel):
    """Outcome of one filter step inside a pipeline run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filter_name: str
    priority: int
    enabled: bool
    applied: bool
    skipped: bool = False
    skip_reason: str = ""
    recommendation: StrategyRecommendation | None = None


class PipelineResult(BaseModel):
    """Aggregate result after running the filter pipeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: StrategyRecommendation
    output: StrategyRecommendation
    steps: list[FilterStepResult] = Field(default_factory=list)
    filters_applied: int = 0
    filters_skipped: int = 0
