"""Schemas for the Trade Recommendation & Strategy Validation Engine.

``TradeRecommendation`` is the sole contract the Backtesting Engine, Monte Carlo,
Paper/Live trading, Frontend, and AI Assistant may consume from strategies.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.market_structure.schemas import TrendDirection
from app.strategy_engine.models import SignalType


class ConsensusSignal(str, Enum):
    """Aggregated multi-strategy recommendation."""

    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    EXIT = "EXIT"


class TradeRecommendation(BaseModel):
    """Canonical trade output — every strategy funnel ends here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = Field(..., min_length=1, max_length=128)
    symbol: str = Field(..., min_length=1, max_length=32)
    timeframe: str = Field(..., min_length=1, max_length=64)
    timestamp: datetime
    signal: SignalType
    entry_price: float = Field(..., gt=0.0)
    stop_loss: float = Field(..., gt=0.0)
    target_1: float = Field(..., gt=0.0)
    target_2: float = Field(..., gt=0.0)
    risk_reward: float = Field(..., ge=0.0)
    confidence: float = Field(..., ge=0.0, le=100.0, description="0–100 confidence")
    expected_holding_period: int = Field(..., ge=0)
    holding_note: str = ""
    trend_direction: TrendDirection = TrendDirection.SIDEWAYS
    market_structure: TrendDirection = TrendDirection.SIDEWAYS
    indicators_used: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(..., min_length=1)
    warnings: list[str] = Field(default_factory=list)
    trade_id: str = Field(default_factory=lambda: uuid4().hex)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank")
        return cleaned

    @field_validator("strategy_name", "timeframe", "trade_id")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("reasons must contain at least one non-empty entry")
        return cleaned

    @field_validator("warnings", "indicators_used")
    @classmethod
    def strip_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class RecommendationConfig(BaseModel):
    """Tunable knobs for validation and confidence combining."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_risk_reward: float = Field(default=1.0, ge=0.0)
    default_timeframe: str = Field(default="15 Minute", min_length=1)
    currency_symbol: str = Field(default="₹", min_length=1)
    # Confidence blend weights (normalized at evaluate time)
    weight_strategy: float = Field(default=40.0, ge=0.0)
    weight_trend: float = Field(default=15.0, ge=0.0)
    weight_volume: float = Field(default=15.0, ge=0.0)
    weight_structure: float = Field(default=15.0, ge=0.0)
    weight_risk_reward: float = Field(default=10.0, ge=0.0)
    weight_confluence: float = Field(default=5.0, ge=0.0)
    # Aggregator
    strong_consensus_min_count: int = Field(default=5, ge=2)
    strong_consensus_min_confidence: float = Field(default=95.0, ge=0.0, le=100.0)
    min_agreement_ratio: float = Field(default=0.6, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def require_positive_confidence_weights(self) -> RecommendationConfig:
        total = (
            self.weight_strategy
            + self.weight_trend
            + self.weight_volume
            + self.weight_structure
            + self.weight_risk_reward
            + self.weight_confluence
        )
        if total <= 0:
            raise ValueError("At least one confidence weight must be > 0")
        return self


class ConfidenceBreakdown(BaseModel):
    """Explainable final confidence components (0–100 scale contributions)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: float = Field(..., ge=0.0)
    trend: float = Field(..., ge=0.0)
    volume: float = Field(..., ge=0.0)
    structure: float = Field(..., ge=0.0)
    risk_reward: float = Field(..., ge=0.0)
    confluence: float = Field(..., ge=0.0)
    total: float = Field(..., ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)


class ConfidenceInputs(BaseModel):
    """Optional external inputs for the confidence engine (0–100 each)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_confidence: float = Field(..., ge=0.0, le=100.0)
    trend_strength: float = Field(default=50.0, ge=0.0, le=100.0)
    volume_score: float = Field(default=50.0, ge=0.0, le=100.0)
    structure_score: float = Field(default=50.0, ge=0.0, le=100.0)
    risk_reward_score: float = Field(default=50.0, ge=0.0, le=100.0)
    confluence_score: float = Field(default=50.0, ge=0.0, le=100.0)


class AggregatedRecommendation(BaseModel):
    """Multi-strategy consensus output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    timeframe: str
    timestamp: datetime
    consensus: ConsensusSignal
    confidence: float = Field(..., ge=0.0, le=100.0)
    confidence_breakdown: ConfidenceBreakdown
    recommendation: TradeRecommendation | None = None
    contributing: list[TradeRecommendation] = Field(default_factory=list)
    buy_count: int = Field(..., ge=0)
    sell_count: int = Field(..., ge=0)
    hold_count: int = Field(..., ge=0)
    exit_count: int = Field(..., ge=0)
    explanation: str
    warnings: list[str] = Field(default_factory=list)


class StrategyValidationRow(BaseModel):
    """Per-strategy validation summary row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str
    status: str
    signals_generated: int = Field(..., ge=0)
    buy_count: int = Field(..., ge=0)
    sell_count: int = Field(..., ge=0)
    hold_count: int = Field(..., ge=0)
    exit_count: int = Field(..., ge=0)
    average_confidence: float = Field(..., ge=0.0)
    average_holding: float = Field(..., ge=0.0)
    validation_errors: list[str] = Field(default_factory=list)


class StrategyValidationReport(BaseModel):
    """Batch validation report across strategies / symbols."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    timeframe: str
    generated_at: datetime
    rows: list[StrategyValidationRow]
    total_errors: int = Field(..., ge=0)
    passed: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)


class RecommendationReport(BaseModel):
    """Human-readable recommendation report payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = "Trade Recommendation"
    strategy_used: str
    signal: str
    entry: str
    stop_loss: str
    target_1: str
    target_2: str
    risk_reward: str
    holding_period: str
    confidence: str
    trend: str
    reasons: list[str]
    warnings: list[str]
    overall_recommendation: str
    body: str
