"""Configuration for the SuperTrend strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SuperTrendConfidenceWeights(BaseModel):
    """Confidence scorecard weights (default total = 100)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_change: float = Field(default=30.0, ge=0.0)
    ema_confirmation: float = Field(default=20.0, ge=0.0)
    market_structure: float = Field(default=20.0, ge=0.0)
    relative_volume: float = Field(default=20.0, ge=0.0)
    atr_health: float = Field(default=10.0, ge=0.0)

    @model_validator(mode="after")
    def require_positive_total(self) -> SuperTrendConfidenceWeights:
        if self.total <= 0:
            raise ValueError("Confidence weights must sum to a positive total")
        return self

    @property
    def total(self) -> float:
        return (
            self.trend_change
            + self.ema_confirmation
            + self.market_structure
            + self.relative_volume
            + self.atr_health
        )


class SuperTrendStrategyConfig(BaseModel):
    """Deterministic knobs for SuperTrend trading."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "supertrend"
    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    date_column: str = "date"
    open_column: str = "open"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"
    volume_column: str = "volume"
    relative_volume_column: str = "relative_volume_20"
    atr_column: str = "atr_14"
    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"
    supertrend_column: str = "supertrend"
    supertrend_direction_column: str = "supertrend_direction"

    atr_period: int = Field(default=10, ge=1)
    atr_multiplier: float = Field(default=3.0, gt=0.0)
    relative_volume_threshold: float = Field(default=1.5, gt=0.0)
    min_atr: float = Field(
        default=0.0,
        ge=0.0,
        description="Reject entries when ATR is at/below this absolute threshold",
    )
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    atr_target_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)

    min_holding_bars: int = Field(default=5, ge=1)
    max_holding_bars: int = Field(default=25, ge=1)
    expected_holding_bars: int = Field(default=15, ge=1)
    min_history_bars: int = Field(default=30, ge=15)
    structure_swing_length: int = Field(default=2, ge=1)

    confidence_weights: SuperTrendConfidenceWeights = Field(
        default_factory=SuperTrendConfidenceWeights,
    )

    @field_validator("symbol", "strategy_name")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def holding_bounds(self) -> SuperTrendStrategyConfig:
        if self.min_holding_bars > self.max_holding_bars:
            raise ValueError("min_holding_bars must be <= max_holding_bars")
        if not (
            self.min_holding_bars
            <= self.expected_holding_bars
            <= self.max_holding_bars
        ):
            raise ValueError(
                "expected_holding_bars must be within [min_holding_bars, max_holding_bars]",
            )
        return self
