"""Order and fill schemas for simulated market execution."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class MarketOrder(BaseModel):
    """Simulated market order (BUY/SELL)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str = Field(default_factory=lambda: uuid4().hex)
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float = Field(..., gt=0.0)
    submitted_at: datetime
    reference_price: float = Field(..., gt=0.0)
    strategy_name: str = ""
    recommendation_trade_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    reject_reason: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank")
        return cleaned


class Fill(BaseModel):
    """Execution fill for a market order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_id: str = Field(default_factory=lambda: uuid4().hex)
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float = Field(..., gt=0.0)
    reference_price: float = Field(..., gt=0.0)
    execution_price: float = Field(..., gt=0.0)
    slippage_per_unit: float = Field(..., ge=0.0)
    slippage_cost: float = Field(..., ge=0.0)
    brokerage: float = Field(..., ge=0.0)
    filled_at: datetime
    cash_delta: float
    realized_pnl: float = 0.0
