"""Configuration for quantitative Momentum scoring and strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MomentumConfig(BaseModel):
    """Knobs for momentum scoring, ranking, and trade filters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "momentum"
    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)
    benchmark_symbol: str = Field(
        default="NIFTY50",
        min_length=1,
        description="Benchmark used for relative-strength confirmation",
    )

    date_column: str = "date"
    close_column: str = "close"
    volume_column: str = "volume"
    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"
    atr_column: str = "atr_14"
    vwap_column: str = "vwap"

    # Trading-day lookbacks (approx 1m / 3m / 6m / 12m)
    lookback_1m: int = Field(default=21, ge=5)
    lookback_3m: int = Field(default=63, ge=10)
    lookback_6m: int = Field(default=126, ge=20)
    lookback_12m: int = Field(default=252, ge=40)

    weight_1m: float = Field(default=0.15, ge=0.0)
    weight_3m: float = Field(default=0.25, ge=0.0)
    weight_6m: float = Field(default=0.30, ge=0.0)
    weight_12m: float = Field(default=0.30, ge=0.0)

    top_percentile: float = Field(
        default=0.20,
        gt=0.0,
        le=1.0,
        description="BUY only in the strongest momentum fraction",
    )
    momentum_sell_threshold: float = Field(
        default=0.0,
        description="SELL when momentum_score drops below this level",
    )
    relative_strength_threshold: float = Field(
        default=0.0,
        description="Minimum RS (stock − benchmark 6m return) for BUY",
    )
    relative_volume_threshold: float = Field(default=1.2, gt=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)
    min_history_bars: int = Field(default=260, ge=30)
    session_bars: int = Field(
        default=63,
        ge=1,
        description="Holding estimate in bars (~1 momentum month)",
    )

    @field_validator("symbol", "strategy_name", "benchmark_symbol")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("symbol", "benchmark_symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_windows_and_weights(self) -> MomentumConfig:
        if not (
            self.lookback_1m < self.lookback_3m < self.lookback_6m < self.lookback_12m
        ):
            raise ValueError("lookbacks must satisfy 1m < 3m < 6m < 12m")
        if self.weight_total <= 0:
            raise ValueError("momentum weights must sum to a positive total")
        if self.min_history_bars < self.lookback_12m + 1:
            raise ValueError("min_history_bars must exceed lookback_12m")
        return self

    @property
    def weight_total(self) -> float:
        return self.weight_1m + self.weight_3m + self.weight_6m + self.weight_12m
