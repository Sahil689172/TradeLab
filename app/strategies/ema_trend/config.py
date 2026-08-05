"""Configuration for the EMA Trend Following strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EMATrendConfig(BaseModel):
    """Deterministic, reusable knobs for EMA trend following."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "ema_trend"
    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    filter_param_overrides: dict[str, dict] = {}
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"
    adx_column: str = "adx_14"
    atr_column: str = "atr_14"
    close_column: str = "close"
    date_column: str = "date"

    adx_threshold: float = Field(default=25.0, ge=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0, description="Target 1 R:R")
    risk_reward_2: float = Field(default=3.0, gt=0.0, description="Target 2 R:R")
    trailing_atr_multiplier: float = Field(default=2.0, gt=0.0)

    holding_period_min: int = Field(default=5, ge=1)
    holding_period_max: int = Field(default=20, ge=1)
    holding_period_default: int = Field(default=10, ge=1)

    min_history_bars: int = Field(default=60, ge=3)

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
    def validate_holding_window(self) -> EMATrendConfig:
        if self.holding_period_min > self.holding_period_max:
            raise ValueError("holding_period_min must be <= holding_period_max")
        if not (
            self.holding_period_min
            <= self.holding_period_default
            <= self.holding_period_max
        ):
            raise ValueError("holding_period_default must lie within min/max")
        if self.risk_reward_2 < self.risk_reward_1:
            raise ValueError("risk_reward_2 must be >= risk_reward_1")
        return self
