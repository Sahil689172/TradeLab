"""Configuration for the Donchian Channel (Turtle) strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DonchianConfidenceWeights(BaseModel):
    """Confidence scorecard weights (default total = 100)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_breakout: float = Field(default=30.0, ge=0.0)
    trend: float = Field(default=20.0, ge=0.0)
    volume: float = Field(default=20.0, ge=0.0)
    market_structure: float = Field(default=20.0, ge=0.0)
    atr: float = Field(default=10.0, ge=0.0)

    @model_validator(mode="after")
    def require_positive_total(self) -> DonchianConfidenceWeights:
        if self.total <= 0:
            raise ValueError("Confidence weights must sum to a positive total")
        return self

    @property
    def total(self) -> float:
        return (
            self.channel_breakout
            + self.trend
            + self.volume
            + self.market_structure
            + self.atr
        )


class DonchianStrategyConfig(BaseModel):
    """Deterministic knobs for Donchian / Turtle-style trading."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = "donchian"
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
    ema_fast_column: str = "ema_20"
    ema_slow_column: str = "ema_50"

    # Channel lookbacks (Turtle: entry 20 or 55, exit 10)
    entry_lookback: int = Field(default=20, ge=2)
    exit_lookback: int = Field(default=10, ge=2)
    breakout_cooldown_bars: int = Field(
        default=5,
        ge=0,
        description="Reject new entries if a same-side breakout occurred within N prior bars",
    )

    relative_volume_threshold: float = Field(default=1.5, gt=0.0)
    min_atr: float = Field(default=0.0, ge=0.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.0)
    atr_trail_multiplier: float = Field(default=2.0, gt=0.0)
    atr_exit_multiplier: float = Field(default=2.0, gt=0.0)
    risk_reward_1: float = Field(default=2.0, gt=0.0)
    use_fixed_risk_reward: bool = Field(
        default=True,
        description="When True, Target 1 uses fixed RR; trend-following still noted in plan",
    )

    min_holding_bars: int = Field(default=10, ge=1)
    max_holding_bars: int = Field(default=60, ge=1)
    expected_holding_bars: int = Field(default=30, ge=1)
    min_history_bars: int = Field(default=40, ge=20)
    structure_swing_length: int = Field(default=2, ge=1)

    confidence_weights: DonchianConfidenceWeights = Field(
        default_factory=DonchianConfidenceWeights,
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

    @model_validator(mode="after")
    def holding_and_lookbacks(self) -> DonchianStrategyConfig:
        if self.min_holding_bars > self.max_holding_bars:
            raise ValueError("min_holding_bars must be <= max_holding_bars")
        if not (
            self.min_holding_bars
            <= self.expected_holding_bars
            <= self.max_holding_bars
        ):
            raise ValueError(
                "expected_holding_bars must be within [min_holding_bars, max_holding_bars]",
            )
        if self.exit_lookback > self.entry_lookback:
            raise ValueError("exit_lookback should be <= entry_lookback (Turtle-style)")
        return self
