"""Pydantic contracts for strategy signals and trade plans."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalType(str, Enum):
    """Discrete trading signal categories."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"


class Signal(BaseModel):
    """Immutable trading signal produced by a strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(..., min_length=1, max_length=32)
    timestamp: datetime
    signal: SignalType
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., min_length=1)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank")
        return cleaned


class TradePlan(BaseModel):
    """Immutable trade plan derived from a strategy signal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(..., min_length=1, max_length=32)
    entry_price: float = Field(..., gt=0.0)
    signal: SignalType
    stop_loss: float = Field(..., gt=0.0)
    take_profit_1: float = Field(..., gt=0.0)
    take_profit_2: float = Field(..., gt=0.0)
    holding_period: int = Field(..., ge=0, description="Planned holding period in bars/days")
    risk_reward: float = Field(..., ge=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons: list[str] = Field(..., min_length=1)
    strategy_name: str = Field(..., min_length=1, max_length=128)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank")
        return cleaned

    @field_validator("strategy_name")
    @classmethod
    def normalize_strategy_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("strategy_name must not be blank")
        return cleaned

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, value: list[str]) -> list[str]:
        cleaned = [reason.strip() for reason in value if reason and reason.strip()]
        if not cleaned:
            raise ValueError("reasons must contain at least one non-empty entry")
        return cleaned
