"""Configuration for the Central Pivot Range (CPR) strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CPRConfidenceWeights(BaseModel):
    """Confidence scorecard weights (default total = 100)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpr_position: float = Field(default=30.0, ge=0.0)
    vwap_confirmation: float = Field(default=20.0, ge=0.0)
    structure: float = Field(default=20.0, ge=0.0)
    relative_volume: float = Field(default=20.0, ge=0.0)
    mode_alignment: float = Field(default=10.0, ge=0.0)

    @model_validator(mode="after")
    def require_positive_total(self) -> CPRConfidenceWeights:
        if self.total <= 0:
            raise ValueError("Confidence weights must sum to a positive total")
        return self

    @property
    def total(self) -> float:
        return (
            self.cpr_position
            + self.vwap_confirmation
            + self.structure
            + self.relative_volume
            + self.mode_alignment
        )


class CPRStrategyConfig(BaseModel):
    """Deterministic knobs for the CPR strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "cpr"
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
    slope_column: str = "vwap_slope"

    # Narrow when CPR width_pct <= threshold; otherwise wide (range/reversal day).
    narrow_cpr_threshold: float = Field(
        default=0.005,
        gt=0.0,
        lt=0.2,
        description="Max CPR width / pivot to classify as Narrow CPR",
    )
    cpr_touch_tolerance_pct: float = Field(
        default=0.0015,
        ge=0.0,
        lt=0.05,
        description="Fractional tolerance for CPR touch / virgin detection",
    )
    relative_volume_threshold: float = Field(default=1.5, gt=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_fallback: float = Field(default=2.0, gt=0.0)
    vwap_slope_lookback: int = Field(default=3, ge=1)

    min_history_bars: int = Field(default=20, ge=5)
    structure_swing_length: int = Field(default=2, ge=1)
    session_bars: int = Field(default=75, ge=1)
    confidence_weights: CPRConfidenceWeights = Field(default_factory=CPRConfidenceWeights)

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
