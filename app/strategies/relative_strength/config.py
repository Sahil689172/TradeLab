"""Configuration for Relative Strength ranking and strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RelativeStrengthConfig(BaseModel):
    """Knobs for RS scoring, ranking, screener, and trade filters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "relative_strength"
    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)
    benchmark_symbol: str = Field(
        default="NIFTY50",
        min_length=1,
        description="Benchmark index symbol (NIFTY50 / ^NSEI features)",
    )

    date_column: str = "date"
    close_column: str = "close"
    volume_column: str = "volume"
    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"
    atr_column: str = "atr_14"
    vwap_column: str = "vwap"

    # Trading-day lookbacks (approx 3m / 6m / 12m)
    lookback_3m: int = Field(default=63, ge=5)
    lookback_6m: int = Field(default=126, ge=10)
    lookback_12m: int = Field(default=252, ge=20)

    weight_3m: float = Field(default=0.2, ge=0.0)
    weight_6m: float = Field(default=0.3, ge=0.0)
    weight_12m: float = Field(default=0.5, ge=0.0)

    top_percentile: float = Field(
        default=0.20,
        gt=0.0,
        le=1.0,
        description="BUY only when rank percentile is within top fraction (0.20 = top 20%)",
    )
    sell_rank_percentile: float = Field(
        default=0.40,
        gt=0.0,
        le=1.0,
        description="SELL when rank percentile falls below this cut (worse than top 40%)",
    )
    relative_volume_threshold: float = Field(default=1.2, gt=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)
    min_history_bars: int = Field(default=260, ge=30)
    session_bars: int = Field(default=20, ge=1)
    improving_lookback_ranks: int = Field(
        default=1,
        ge=1,
        description="Compare current rank vs prior snapshot for improving/weakening lists",
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
    def validate_windows_and_weights(self) -> RelativeStrengthConfig:
        if not (self.lookback_3m < self.lookback_6m < self.lookback_12m):
            raise ValueError("lookbacks must satisfy 3m < 6m < 12m")
        total = self.weight_3m + self.weight_6m + self.weight_12m
        if total <= 0:
            raise ValueError("RS weights must sum to a positive total")
        if self.sell_rank_percentile < self.top_percentile:
            raise ValueError("sell_rank_percentile should be >= top_percentile")
        if self.min_history_bars < self.lookback_12m + 1:
            raise ValueError("min_history_bars must exceed lookback_12m")
        return self

    @property
    def weight_total(self) -> float:
        return self.weight_3m + self.weight_6m + self.weight_12m
