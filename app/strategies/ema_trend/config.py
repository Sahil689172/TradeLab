"""Configuration for the EMA Trend Following strategy.

Supports ``mode="raw"`` (legacy behaviour, default) and ``mode="professional"``
(institutional crossover system with modular filters). Backwards compatible.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.strategies.ema_trend.presets import EMA_PAIR_PRESETS, ema_column_for_period


class EMATrendConfig(BaseModel):
    """Deterministic, reusable knobs for EMA trend following."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "ema_trend"
    mode: Literal["raw", "professional"] = "raw"

    enable_filter_pipeline: bool = False
    filter_enable_optional: tuple[str, ...] = ()
    filter_disable: tuple[str, ...] = ()
    filter_param_overrides: dict[str, dict] = {}
    symbol: str = Field(default="UNKNOWN", min_length=1, max_length=32)

    # Period-based EMA lengths (professional). Columns are derived unless overridden.
    fast_ema: int = Field(default=20, ge=2, le=500)
    slow_ema: int = Field(default=50, ge=2, le=500)
    ema_pair_preset: str | None = Field(
        default=None,
        description="Optional preset key: 9_21, 12_26, 20_50, 50_200",
    )

    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"
    ema200_column: str = "ema_200"
    adx_column: str = "adx_14"
    atr_column: str = "atr_14"
    close_column: str = "close"
    date_column: str = "date"
    volume_column: str = "volume"
    volume_sma_column: str = "volume_sma_20"
    relative_volume_column: str = "relative_volume_20"

    # Professional confirmation / filters (ignored in raw mode except ADX/ATR knobs)
    confirm_on_close: bool = True
    trend_filter: bool = True
    ema200_filter: bool = True
    adx_filter: bool = True
    adx_threshold: float = Field(default=25.0, ge=0.0)
    volume_filter: bool = True
    relative_volume: float = Field(default=1.2, gt=0.0)

    atr_stop: bool = True
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    atr_multiplier: float | None = Field(
        default=None,
        gt=0.0,
        description="Alias for atr_stop_multiplier (professional JSON)",
    )
    atr_trailing: bool = False
    trailing_atr_multiplier: float = Field(default=2.0, gt=0.0)

    risk_reward_1: float = Field(default=2.0, gt=0.0, description="Target 1 R:R")
    risk_reward_2: float = Field(default=3.0, gt=0.0, description="Target 2 R:R")

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

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("ema_pair_preset", mode="before")
    @classmethod
    def normalize_preset(cls, value: object) -> object:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            cleaned = value.strip().lower().replace("/", "_").replace("-", "_")
            return cleaned
        return value

    @model_validator(mode="before")
    @classmethod
    def apply_preset_and_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)

        # atr_multiplier alias → atr_stop_multiplier when provided
        if payload.get("atr_multiplier") is not None and "atr_stop_multiplier" not in payload:
            payload["atr_stop_multiplier"] = payload["atr_multiplier"]
        elif payload.get("atr_multiplier") is not None:
            payload["atr_stop_multiplier"] = payload["atr_multiplier"]

        preset = payload.get("ema_pair_preset")
        if isinstance(preset, str) and preset.strip():
            key = preset.strip().lower().replace("/", "_").replace("-", "_")
            if key not in EMA_PAIR_PRESETS:
                raise ValueError(
                    f"Unknown ema_pair_preset '{preset}'. "
                    f"Known: {sorted(EMA_PAIR_PRESETS)}",
                )
            fast, slow = EMA_PAIR_PRESETS[key]
            payload.setdefault("fast_ema", fast)
            payload.setdefault("slow_ema", slow)

        # Sync column names from periods when periods are set / preset applied
        if "fast_ema" in payload or "slow_ema" in payload or preset:
            fast = int(payload.get("fast_ema", 20))
            slow = int(payload.get("slow_ema", 50))
            # Only override columns if caller did not explicitly set them alongside periods
            # Always sync when professional fields are present for predictable presets.
            if "ema_fast_column" not in data or preset or "fast_ema" in data:
                payload["ema_fast_column"] = ema_column_for_period(fast)
            if "ema_slow_column" not in data or preset or "slow_ema" in data:
                payload["ema_slow_column"] = ema_column_for_period(slow)

        return payload

    @model_validator(mode="after")
    def validate_windows_and_pairs(self) -> EMATrendConfig:
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
        if self.fast_ema >= self.slow_ema:
            raise ValueError("fast_ema must be < slow_ema")
        if self.ema_pair_preset is not None and self.ema_pair_preset not in EMA_PAIR_PRESETS:
            raise ValueError(f"Unknown ema_pair_preset '{self.ema_pair_preset}'")
        return self

    @classmethod
    def professional(cls, **overrides: object) -> EMATrendConfig:
        """Factory for institutional defaults (9/21, ATR×1.5, filters on)."""
        defaults: dict[str, object] = {
            "mode": "professional",
            "fast_ema": 9,
            "slow_ema": 21,
            "ema_pair_preset": "9_21",
            "confirm_on_close": True,
            "trend_filter": True,
            "ema200_filter": True,
            "adx_filter": True,
            "adx_threshold": 25.0,
            "volume_filter": True,
            "relative_volume": 1.2,
            "atr_stop": True,
            "atr_stop_multiplier": 1.5,
            "atr_trailing": False,
            "trailing_atr_multiplier": 1.5,
        }
        defaults.update(overrides)
        return cls.model_validate(defaults)
