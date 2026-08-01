"""Configuration for the VWAP strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.strategy_engine.indicators.vwap import VWAPMode


class VWAPConfidenceWeights(BaseModel):
    """Confidence scorecard weights (default total = 100)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vwap_position: float = Field(default=30.0, ge=0.0)
    slope: float = Field(default=20.0, ge=0.0)
    relative_volume: float = Field(default=20.0, ge=0.0)
    structure: float = Field(default=20.0, ge=0.0)
    retest_confirmation: float = Field(default=10.0, ge=0.0)

    @model_validator(mode="after")
    def require_positive_total(self) -> VWAPConfidenceWeights:
        if self.total <= 0:
            raise ValueError("Confidence weights must sum to a positive total")
        return self

    @property
    def total(self) -> float:
        return (
            self.vwap_position
            + self.slope
            + self.relative_volume
            + self.structure
            + self.retest_confirmation
        )


class VWAPStrategyConfig(BaseModel):
    """Deterministic knobs for the Daily VWAP strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "vwap"
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    # Future-ready: only DAILY is supported by VWAPService today.
    vwap_mode: VWAPMode = VWAPMode.DAILY
    slope_lookback: int = Field(default=3, ge=1)

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

    relative_volume_threshold: float = Field(default=1.5, gt=0.0)
    retest_tolerance: float = Field(
        default=0.0015,
        ge=0.0,
        lt=0.05,
        description="Fractional tolerance around VWAP for retest/rejection touch",
    )
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)

    min_history_bars: int = Field(default=20, ge=5)
    structure_swing_length: int = Field(default=2, ge=1)
    session_bars: int = Field(
        default=75,
        ge=1,
        description="Expected bars per cash session for intraday holding estimate",
    )
    confidence_weights: VWAPConfidenceWeights = Field(default_factory=VWAPConfidenceWeights)

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
    def require_daily_mode(self) -> VWAPStrategyConfig:
        if self.vwap_mode is not VWAPMode.DAILY:
            raise ValueError(
                f"vwap_mode '{self.vwap_mode.value}' is not implemented; use daily",
            )
        return self
