"""Configuration for the Break & Retest strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BreakRetestStrategyConfig(BaseModel):
    """Trade knobs for Break & Retest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "break_retest"
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    date_column: str = "date"
    open_column: str = "open"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"
    volume_column: str = "volume"
    relative_volume_column: str = "relative_volume_20"
    atr_column: str = "atr_14"

    lookback: int = Field(default=20, ge=3)
    retest_tolerance_pct: float = Field(default=0.0015, ge=0.0, lt=0.05)
    min_body_ratio: float = Field(default=0.4, gt=0.0, lt=1.0)
    relative_volume_threshold: float = Field(default=1.5, gt=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    atr_target_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)
    min_history_bars: int = Field(default=25, ge=10)
    structure_swing_length: int = Field(default=2, ge=1)
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
