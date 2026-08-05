"""Configuration for the Darvas Box strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DarvasBoxStrategyConfig(BaseModel):
    """Trade knobs for Darvas Box breakouts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "darvas_box"
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
    atr_column: str = "atr_14"
    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"

    confirm_bars: int = Field(default=3, ge=1)
    min_box_bars: int = Field(default=2, ge=1)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    atr_target_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)
    min_history_bars: int = Field(default=30, ge=10)
    session_bars: int = Field(default=20, ge=1)

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
