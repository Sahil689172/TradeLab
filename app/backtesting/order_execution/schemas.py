"""Configuration, account state, and trade-log schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.backtesting.order_execution.orders import Fill, MarketOrder, OrderSide


class ExecutionConfig(BaseModel):
    """Simulated broker knobs (no portfolio analytics)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float = Field(default=1_000_000.0, gt=0.0)
    # Fraction of *available cash* allocated to each BUY (before brokerage).
    position_size_pct: float = Field(default=0.95, gt=0.0, le=1.0)
    # Slippage as a fraction of reference price (BUY pays more, SELL receives less).
    slippage_bps: float = Field(default=5.0, ge=0.0)
    # Brokerage as a fraction of notional + optional flat fee.
    brokerage_rate: float = Field(default=0.0003, ge=0.0)
    brokerage_flat: float = Field(default=0.0, ge=0.0)
    # Optional fixed share quantity; when set, overrides percent sizing.
    fixed_quantity: float | None = Field(default=None, gt=0.0)
    allow_fractional_shares: bool = True


class PositionState(BaseModel):
    """Open long position for one symbol (flat = quantity 0)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    quantity: float = Field(default=0.0, ge=0.0)
    average_entry_price: float = Field(default=0.0, ge=0.0)
    entry_brokerage: float = Field(default=0.0, ge=0.0)
    entry_slippage_cost: float = Field(default=0.0, ge=0.0)
    opened_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.quantity > 0.0

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class AccountSnapshot(BaseModel):
    """Cash + positions snapshot after an execution attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cash: float
    initial_capital: float
    realized_pnl: float
    unrealized_pnl: float
    equity: float
    positions: dict[str, PositionState] = Field(default_factory=dict)


class TradeLogEntry(BaseModel):
    """One executed trade row for the trade log."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: float
    execution_price: float
    brokerage: float
    slippage: float
    pnl: float
    remaining_cash: float
    order_id: str
    fill_id: str
    strategy_name: str = ""
    average_entry_price: float | None = None
    average_exit_price: float | None = None


class ExecutionAttempt(BaseModel):
    """Result of processing one TradeRecommendation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    reason: str = ""
    order: MarketOrder | None = None
    fill: Fill | None = None
    trade_log: TradeLogEntry | None = None
    account: AccountSnapshot


class ExecutionResult(BaseModel):
    """Aggregate output of an execution run over many recommendations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config: ExecutionConfig
    started_at: datetime
    completed_at: datetime
    trade_log: list[TradeLogEntry] = Field(default_factory=list)
    attempts: list[ExecutionAttempt] = Field(default_factory=list)
    final_account: AccountSnapshot
    orders_filled: int = 0
    orders_rejected: int = 0
