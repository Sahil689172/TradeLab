"""Configuration for the Volume Breakout strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VolumeBreakoutConfidenceWeights(BaseModel):
    """Confidence scorecard weights (default total = 100)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level_break: float = Field(default=30.0, ge=0.0)
    relative_volume: float = Field(default=25.0, ge=0.0)
    structure: float = Field(default=20.0, ge=0.0)
    vwap: float = Field(default=15.0, ge=0.0)
    candle_quality: float = Field(default=10.0, ge=0.0)

    @model_validator(mode="after")
    def require_positive_total(self) -> VolumeBreakoutConfidenceWeights:
        if self.total <= 0:
            raise ValueError("Confidence weights must sum to a positive total")
        return self

    @property
    def total(self) -> float:
        return (
            self.level_break
            + self.relative_volume
            + self.structure
            + self.vwap
            + self.candle_quality
        )


class VolumeBreakoutConfig(BaseModel):
    """Deterministic knobs for Volume Breakout."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "volume_breakout"
    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    filter_param_overrides: dict[str, dict] = {}
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    date_column: str = "date"
    open_column: str = "open"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"
    volume_column: str = "volume"
    relative_volume_column: str = "relative_volume_20"
    atr_column: str = "atr_14"
    vwap_column: str = "vwap"

    relative_volume_threshold: float = Field(default=1.8, gt=0.0)
    resistance_lookback: int = Field(
        default=20,
        ge=3,
        description="Bars used to derive recent resistance/support when Levels absent",
    )
    min_body_ratio: float = Field(
        default=0.45,
        gt=0.0,
        lt=1.0,
        description="Minimum |close-open| / (high-low) to accept candle strength",
    )
    max_session_bar_index: int = Field(
        default=60,
        ge=1,
        description="Reject breakouts after this bar index within the session (0-based)",
    )
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    atr_target_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)
    vwap_slope_lookback: int = Field(default=3, ge=1)
    volume_spike_multiple: float = Field(default=1.8, gt=0.0)

    min_history_bars: int = Field(default=25, ge=10)
    structure_swing_length: int = Field(default=2, ge=1)
    session_bars: int = Field(default=75, ge=1)
    confidence_weights: VolumeBreakoutConfidenceWeights = Field(
        default_factory=VolumeBreakoutConfidenceWeights,
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
