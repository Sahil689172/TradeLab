"""Pydantic contracts for exit evaluation."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.risk_engine.schemas import TradeDirection


class ExitMethod(str, Enum):
    """Supported exit evaluation methods."""

    FIXED_TARGET = "FIXED_TARGET"
    ATR_EXIT = "ATR_EXIT"
    EMA_EXIT = "EMA_EXIT"
    SUPERTREND_EXIT = "SUPERTREND_EXIT"
    TRAILING_STOP = "TRAILING_STOP"
    BREAK_EVEN = "BREAK_EVEN"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    TIME_EXIT = "TIME_EXIT"


class ExitAction(str, Enum):
    """High-level exit decision."""

    HOLD = "HOLD"
    FULL_EXIT = "FULL_EXIT"
    PARTIAL_EXIT = "PARTIAL_EXIT"


class ExitConfig(BaseModel):
    """Tunable parameters for exit rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    take_profit: float | None = Field(default=None, gt=0.0)
    initial_stop: float | None = Field(default=None, gt=0.0)
    atr_column: str = "atr_14"
    atr_multiplier: float = Field(default=1.5, gt=0.0)
    ema_column: str = "ema_21"
    trailing_atr_multiplier: float = Field(default=1.5, gt=0.0)
    trailing_percent: float | None = Field(default=None, gt=0.0, lt=1.0)
    break_even_trigger_r: float = Field(default=1.0, gt=0.0)
    partial_fraction: float = Field(default=0.5, gt=0.0, lt=1.0)
    partial_trigger_r: float = Field(default=1.0, gt=0.0)
    max_bars: int = Field(default=20, ge=1)
    supertrend_period: int = Field(default=10, ge=1)
    supertrend_multiplier: float = Field(default=3.0, gt=0.0)
    enabled_methods: tuple[ExitMethod, ...] = (
        ExitMethod.TIME_EXIT,
        ExitMethod.FIXED_TARGET,
        ExitMethod.PARTIAL_EXIT,
        ExitMethod.BREAK_EVEN,
        ExitMethod.TRAILING_STOP,
        ExitMethod.ATR_EXIT,
        ExitMethod.EMA_EXIT,
        ExitMethod.SUPERTREND_EXIT,
    )


class TradeExitState(BaseModel):
    """Open-trade state required to evaluate exits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_price: float = Field(..., gt=0.0)
    direction: TradeDirection
    bars_held: int = Field(..., ge=0)
    extreme_high: float = Field(..., gt=0.0, description="Highest high since entry")
    extreme_low: float = Field(..., gt=0.0, description="Lowest low since entry")
    remaining_fraction: float = Field(default=1.0, gt=0.0, le=1.0)
    break_even_armed: bool = False

    @model_validator(mode="after")
    def validate_extremes(self) -> TradeExitState:
        if self.extreme_high < self.extreme_low:
            raise ValueError("extreme_high must be >= extreme_low")
        return self


class ExitSignal(BaseModel):
    """One method-level exit trigger assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: ExitMethod
    triggered: bool
    exit_price: float | None = Field(default=None, gt=0.0)
    exit_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(..., min_length=1)


class ExitDecision(BaseModel):
    """Final exit recommendation returned by the exit engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: ExitAction
    exit_price: float | None = Field(default=None, gt=0.0)
    reason: str = Field(..., min_length=1)
    method: ExitMethod | None = None
    exit_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    signals: list[ExitSignal] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_payload(self) -> ExitDecision:
        if self.decision is ExitAction.HOLD:
            if self.exit_price is not None or self.exit_fraction != 0.0:
                raise ValueError("HOLD decisions must not include an exit price or fraction")
            return self
        if self.exit_price is None:
            raise ValueError("Exit decisions require an exit_price")
        if self.exit_fraction <= 0.0:
            raise ValueError("Exit decisions require a positive exit_fraction")
        if self.decision is ExitAction.FULL_EXIT and self.exit_fraction != 1.0:
            raise ValueError("FULL_EXIT requires exit_fraction == 1.0")
        if self.decision is ExitAction.PARTIAL_EXIT and self.exit_fraction >= 1.0:
            raise ValueError("PARTIAL_EXIT requires exit_fraction < 1.0")
        return self
