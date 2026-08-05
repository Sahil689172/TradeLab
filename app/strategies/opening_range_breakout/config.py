"""Configuration for the Opening Range Breakout strategy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ORBConfidenceWeights(BaseModel):
    """Confidence scorecard weights (default total = 100)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    opening_range_break: float = Field(default=30.0, ge=0.0)
    volume: float = Field(default=20.0, ge=0.0)
    trend: float = Field(default=20.0, ge=0.0)
    structure: float = Field(default=20.0, ge=0.0)
    momentum: float = Field(default=10.0, ge=0.0)

    @model_validator(mode="after")
    def require_positive_total(self) -> ORBConfidenceWeights:
        if self.total <= 0:
            raise ValueError("Confidence weights must sum to a positive total")
        return self

    @property
    def total(self) -> float:
        return (
            self.opening_range_break
            + self.volume
            + self.trend
            + self.structure
            + self.momentum
        )


class OpeningRangeBreakoutConfig(BaseModel):
    """Deterministic knobs for Opening Range Breakout (ORB)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "opening_range_breakout"
    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    filter_param_overrides: dict[str, dict] = {}
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    # Timeframe / OR window — never hardcode a single OR length.
    opening_range_minutes: Literal[5, 15, 30] = 15
    bar_minutes: int = Field(
        default=5,
        ge=1,
        description="Bar size of the intraday feature frame in minutes",
    )

    date_column: str = "date"
    open_column: str = "open"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"
    volume_column: str = "relative_volume_20"
    atr_column: str = "atr_14"
    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"

    relative_volume_threshold: float = Field(default=1.5, gt=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    atr_target_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)

    min_range_pct: float = Field(
        default=0.001,
        gt=0.0,
        lt=1.0,
        description="Minimum OR width as fraction of mid price",
    )
    max_range_pct: float = Field(
        default=0.03,
        gt=0.0,
        lt=1.0,
        description="Maximum OR width as fraction of mid price",
    )
    max_breakout_bars_after_or: int = Field(
        default=12,
        ge=1,
        description="Reject breakouts occurring more than N bars after OR completes",
    )
    max_gap_pct: float = Field(
        default=0.02,
        gt=0.0,
        lt=1.0,
        description="Skip session when open gap vs prior close exceeds this fraction",
    )

    min_history_bars: int = Field(default=20, ge=5)
    structure_swing_length: int = Field(default=2, ge=1)
    session_bars: int = Field(
        default=75,
        ge=1,
        description="Expected bars per cash session for intraday holding estimate",
    )
    confidence_weights: ORBConfidenceWeights = Field(default_factory=ORBConfidenceWeights)

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
    def validate_range_and_or_bars(self) -> OpeningRangeBreakoutConfig:
        if self.min_range_pct >= self.max_range_pct:
            raise ValueError("min_range_pct must be < max_range_pct")
        if self.opening_range_minutes % self.bar_minutes != 0:
            raise ValueError(
                f"opening_range_minutes ({self.opening_range_minutes}) must be divisible "
                f"by bar_minutes ({self.bar_minutes})",
            )
        return self

    @property
    def opening_range_bars(self) -> int:
        """Number of intraday bars that compose the configured opening range."""
        return self.opening_range_minutes // self.bar_minutes
