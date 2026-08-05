"""Configuration for the Previous Day High/Low (Magic Box) strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfidenceWeights(BaseModel):
    """Confidence scorecard weights (default total = 100)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level_break: float = Field(default=30.0, ge=0.0)
    retest: float = Field(default=20.0, ge=0.0)
    relative_volume: float = Field(default=20.0, ge=0.0)
    confirmation_candle: float = Field(default=10.0, ge=0.0)
    market_structure: float = Field(default=20.0, ge=0.0)

    @model_validator(mode="after")
    def require_positive_total(self) -> ConfidenceWeights:
        total = (
            self.level_break
            + self.retest
            + self.relative_volume
            + self.confirmation_candle
            + self.market_structure
        )
        if total <= 0:
            raise ValueError("Confidence weights must sum to a positive total")
        return self

    @property
    def total(self) -> float:
        return (
            self.level_break
            + self.retest
            + self.relative_volume
            + self.confirmation_candle
            + self.market_structure
        )


class PreviousDayBreakoutConfig(BaseModel):
    """Deterministic knobs for the Magic Box breakout strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "previous_day_breakout"
    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    date_column: str = "date"
    open_column: str = "open"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"
    volume_column: str = "relative_volume_20"
    atr_column: str = "atr_14"

    approach_tolerance_pct: float = Field(
        default=0.002,
        gt=0.0,
        lt=1.0,
        description="Fraction of level price used to detect approach/touch",
    )
    relative_volume_threshold: float = Field(default=1.5, gt=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)
    min_history_bars: int = Field(default=20, ge=5)
    structure_swing_length: int = Field(default=2, ge=1)
    session_bars: int = Field(
        default=25,
        ge=1,
        description="Expected 15m bars per cash session (intraday holding estimate)",
    )
    confidence_weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)

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
