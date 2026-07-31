"""Pydantic contracts for risk planning."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TradeDirection(str, Enum):
    """Trade side used for stop/target placement."""

    LONG = "LONG"
    SHORT = "SHORT"


class StopMethod(str, Enum):
    """Supported stop construction methods."""

    ATR = "ATR"
    SWING = "SWING"
    STRUCTURE = "STRUCTURE"
    PERCENTAGE = "PERCENTAGE"
    TIME = "TIME"


class RiskConfig(BaseModel):
    """Tunable parameters for stop, target, and position-risk sizing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preferred_stop: StopMethod = StopMethod.ATR
    atr_column: str = "atr_14"
    atr_multiplier: float = Field(default=1.5, gt=0.0)
    percentage_stop: float = Field(
        default=0.02,
        gt=0.0,
        lt=1.0,
        description="Fractional distance for percentage stops (e.g. 0.02 = 2%)",
    )
    swing_buffer: float = Field(
        default=0.0,
        ge=0.0,
        description="Absolute price buffer beyond swing/structure levels",
    )
    risk_reward: float = Field(default=2.0, gt=0.0)
    time_stop_bars: int = Field(default=10, ge=1)
    account_equity: float | None = Field(default=None, gt=0.0)
    risk_fraction: float = Field(
        default=0.01,
        gt=0.0,
        le=1.0,
        description="Fraction of equity risked on the position",
    )

    @model_validator(mode="after")
    def preferred_stop_must_be_price_or_time(self) -> RiskConfig:
        # TIME may be preferred only as holding constraint; price stop still required.
        return self


class StopLevel(BaseModel):
    """One computed stop candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: StopMethod
    price: float | None = Field(default=None, gt=0.0)
    bars: int | None = Field(default=None, ge=1)
    reason: str = Field(..., min_length=1)


class PositionRisk(BaseModel):
    """Capital risk implied by entry/stop distance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    risk_per_unit: float = Field(..., ge=0.0)
    risk_fraction: float = Field(..., gt=0.0, le=1.0)
    account_equity: float | None = Field(default=None, gt=0.0)
    position_size: float | None = Field(default=None, ge=0.0)
    capital_at_risk: float | None = Field(default=None, ge=0.0)


class RiskPlan(BaseModel):
    """Reusable risk output for strategies and trade planning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_price: float = Field(..., gt=0.0)
    direction: TradeDirection
    stop_loss: float = Field(..., gt=0.0)
    take_profit: float = Field(..., gt=0.0)
    risk_reward: float = Field(..., gt=0.0)
    holding_estimate: int = Field(..., ge=1, description="Estimated holding period in bars")
    confidence: float = Field(..., ge=0.0, le=1.0)
    stop_method: StopMethod
    stops: list[StopLevel]
    position_risk: PositionRisk
    reasons: list[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_geometry(self) -> RiskPlan:
        if self.direction is TradeDirection.LONG:
            if not (self.stop_loss < self.entry_price < self.take_profit):
                raise ValueError("LONG requires stop < entry < take_profit")
        else:
            if not (self.take_profit < self.entry_price < self.stop_loss):
                raise ValueError("SHORT requires take_profit < entry < stop")
        return self
