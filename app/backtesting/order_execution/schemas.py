"""Configuration, account state, rejection diagnostics, and trade-log schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.backtesting.order_execution.orders import Fill, MarketOrder, OrderSide


class PositionSizingMode(str, Enum):
    """Exactly one sizing mode is active per run."""

    FIXED_AMOUNT = "fixed_amount"
    FIXED_QUANTITY = "fixed_quantity"
    PERCENT_OF_CAPITAL = "percent_of_capital"


class ExitReason(str, Enum):
    TARGET_HIT = "Target Hit"
    STOP_LOSS = "Stop Loss"
    SELL_RECOMMENDATION = "SELL Recommendation"
    REPLAY_END = "Replay End"


class RejectionReason(str, Enum):
    """Canonical rejection messages for diagnostics."""

    ALREADY_HOLDING = "Already holding position"
    NO_OPEN_POSITION = "No open position to sell"
    INSUFFICIENT_CASH = "Insufficient cash"
    BELOW_MIN_QUANTITY = "Position size below minimum quantity"
    CAPITAL_INSUFFICIENT_ONE_SHARE = "Capital insufficient to purchase one share."
    INVALID_RECOMMENDATION = "Invalid recommendation"
    CONFIDENCE_BELOW_THRESHOLD = "Confidence below configured threshold"
    TRADE_OUTSIDE_REPLAY = "Trade outside replay session"
    NO_ORDER_FOR_SIGNAL = "No order for signal"
    VALIDATION_FAILURE = "Validation failure"


class ExecutionConfig(BaseModel):
    """Simulated broker knobs (no portfolio analytics)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float = Field(default=1_000_000.0, gt=0.0)
    position_sizing: PositionSizingMode = PositionSizingMode.PERCENT_OF_CAPITAL
    # fixed_amount: rupees of cash to allocate per BUY (before/with brokerage).
    amount: float | None = Field(default=None, gt=0.0)
    # fixed_quantity: whole shares per BUY.
    quantity: float | None = Field(default=None, gt=0.0)
    # percent_of_capital: percent of *available cash* (e.g. 25 = 25%).
    percent: float = Field(default=95.0, gt=0.0, le=100.0)
    slippage_bps: float = Field(default=5.0, ge=0.0)
    brokerage_rate: float = Field(default=0.0003, ge=0.0)
    brokerage_flat: float = Field(default=0.0, ge=0.0)
    # Whole shares only by default (A5.2.1).
    allow_fractional_shares: bool = False
    min_quantity: float = Field(default=1.0, gt=0.0)
    # Optional filters (do not alter strategy / recommendation generation).
    min_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    session_start: datetime | None = None
    session_end: datetime | None = None
    # Close open lots at end of replay with ExitReason.REPLAY_END.
    close_open_at_replay_end: bool = True

    @model_validator(mode="after")
    def validate_sizing_params(self) -> ExecutionConfig:
        mode = self.position_sizing
        if mode is PositionSizingMode.FIXED_AMOUNT and self.amount is None:
            raise ValueError("position_sizing=fixed_amount requires amount > 0")
        if mode is PositionSizingMode.FIXED_QUANTITY and self.quantity is None:
            raise ValueError("position_sizing=fixed_quantity requires quantity > 0")
        if (
            self.session_start is not None
            and self.session_end is not None
            and self.session_start > self.session_end
        ):
            raise ValueError("session_start must be <= session_end")
        return self

    @property
    def position_size_pct(self) -> float:
        """Fraction of cash for percent mode (0–1)."""
        return self.percent / 100.0


class PositionState(BaseModel):
    """Open long position for one symbol (flat = quantity 0)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    quantity: float = Field(default=0.0, ge=0.0)
    average_entry_price: float = Field(default=0.0, ge=0.0)
    entry_brokerage: float = Field(default=0.0, ge=0.0)
    entry_slippage_cost: float = Field(default=0.0, ge=0.0)
    opened_at: datetime | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    strategy_name: str = ""

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


class FillLogEntry(BaseModel):
    """One executed fill row (BUY or SELL leg)."""

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


# Back-compat alias used by earlier A5.2 tests / imports.
TradeLogEntry = FillLogEntry


class ClosedTradeRecord(BaseModel):
    """Round-trip trade for trade_log.json (entry → exit)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_profit: float
    brokerage: float
    slippage: float
    net_profit: float
    holding_days: int = Field(..., ge=0)
    exit_reason: ExitReason
    strategy_name: str = ""


class RejectedOrderRecord(BaseModel):
    """One rejected order for rejected_orders.json."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    symbol: str
    side: OrderSide | None = None
    requested_price: float | None = None
    reason: str
    reason_code: RejectionReason = RejectionReason.VALIDATION_FAILURE
    strategy_name: str = ""
    signal: str = ""
    confidence: float | None = None


class ExecutionSummary(BaseModel):
    """Console / JSON replay execution summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    orders_attempted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    open_positions: int = 0
    closed_positions: int = 0
    current_cash: float = 0.0
    current_equity: float = 0.0
    largest_position: float = 0.0
    largest_profit: float = 0.0
    largest_loss: float = 0.0


class ExecutionAttempt(BaseModel):
    """Result of processing one TradeRecommendation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    reason: str = ""
    reason_code: RejectionReason | None = None
    order: MarketOrder | None = None
    fill: Fill | None = None
    trade_log: FillLogEntry | None = None
    closed_trade: ClosedTradeRecord | None = None
    rejected: RejectedOrderRecord | None = None
    account: AccountSnapshot


class ExecutionResult(BaseModel):
    """Aggregate output of an execution run over many recommendations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config: ExecutionConfig
    started_at: datetime
    completed_at: datetime
    trade_log: list[ClosedTradeRecord] = Field(default_factory=list)
    fill_log: list[FillLogEntry] = Field(default_factory=list)
    rejected_orders: list[RejectedOrderRecord] = Field(default_factory=list)
    attempts: list[ExecutionAttempt] = Field(default_factory=list)
    final_account: AccountSnapshot
    summary: ExecutionSummary
    orders_filled: int = 0
    orders_rejected: int = 0
