"""Canonical Position model, events, and configuration (Phase A5.3).

Broker ``PositionState`` remains the cash/lot tracker inside A5.2. This module
is the lifecycle view consumed by future Portfolio / Risk / Performance layers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PositionSide(str, Enum):
    LONG = "LONG"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PositionExitReason(str, Enum):
    STRATEGY_EXIT = "STRATEGY_EXIT"
    STRATEGY_SELL = "STRATEGY_SELL"
    STOP_LOSS = "STOP_LOSS"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    END_OF_BACKTEST = "END_OF_BACKTEST"
    MANUAL = "MANUAL"


class PositionEventType(str, Enum):
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_UPDATED = "POSITION_UPDATED"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
    POSITION_CLOSED = "POSITION_CLOSED"
    POSITION_REJECTED = "POSITION_REJECTED"


class PositionRejectReason(str, Enum):
    ALREADY_POSITIONED = "ALREADY_POSITIONED"
    NO_OPEN_POSITION = "NO_OPEN_POSITION"
    REJECTED_ORDER = "REJECTED_ORDER"
    SHORT_NOT_SUPPORTED = "SHORT_NOT_SUPPORTED"
    INVALID_FILL = "INVALID_FILL"


class EndOfBacktestPolicy(str, Enum):
    FORCE_CLOSE = "FORCE_CLOSE"
    MARK_TO_MARKET = "MARK_TO_MARKET"
    LEAVE_OPEN = "LEAVE_OPEN"


class PositionManagerConfig(BaseModel):
    """Lifecycle knobs. Does not decide whether a trade should be opened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_pyramiding: bool = False  # reserved; duplicate opens are always rejected
    allow_short: bool = False
    end_of_backtest: EndOfBacktestPolicy = EndOfBacktestPolicy.FORCE_CLOSE
    close_on_target_1: bool = False
    close_on_target_2: bool = False
    skip_protective_checks_on_entry_bar: bool = True
    debug: bool = False


class Position(BaseModel):
    """Canonical long position lifecycle record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position_id: str = Field(default_factory=lambda: uuid4().hex)
    symbol: str
    side: PositionSide = PositionSide.LONG
    quantity: float = Field(..., gt=0.0)
    entry_price: float = Field(..., gt=0.0)
    current_price: float = Field(..., gt=0.0)
    entry_timestamp: datetime
    last_updated_timestamp: datetime
    stop_loss: float | None = Field(default=None, gt=0.0)
    target_1: float | None = Field(default=None, gt=0.0)
    target_2: float | None = Field(default=None, gt=0.0)
    target_1_hit: bool = False
    target_2_hit: bool = False
    target_1_hit_timestamp: datetime | None = None
    target_2_hit_timestamp: datetime | None = None
    stop_loss_hit: bool = False
    stop_loss_hit_timestamp: datetime | None = None
    status: PositionStatus = PositionStatus.OPEN
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    gross_realized_pnl: float = 0.0
    exit_price: float | None = Field(default=None, gt=0.0)
    exit_timestamp: datetime | None = None
    exit_reason: PositionExitReason | None = None
    holding_period: timedelta = Field(default_factory=lambda: timedelta(0))
    strategy_name: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=100.0)
    entry_order_id: str = ""
    exit_order_id: str | None = None

    @property
    def order_id(self) -> str:
        return self.entry_order_id

    @property
    def is_open(self) -> bool:
        return self.status in {PositionStatus.OPEN, PositionStatus.PARTIALLY_CLOSED}

    @property
    def holding_period_days(self) -> int:
        return max(0, int(self.holding_period.days))

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("symbol must not be blank")
        return cleaned

    @model_validator(mode="after")
    def enforce_invariants(self) -> Position:
        from app.backtesting.position_manager.invariants import validate_position

        validate_position(self)
        return self


class PositionEvent(BaseModel):
    """Structured lifecycle event for later Portfolio / Risk / UI consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: PositionEventType
    timestamp: datetime
    symbol: str
    position_id: str | None = None
    action: str = ""
    quantity: float | None = None
    price: float | None = None
    status: PositionStatus | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    exit_reason: PositionExitReason | None = None
    reject_reason: PositionRejectReason | None = None
    message: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class PositionActionResult(BaseModel):
    """Result of a Position Manager mutation (open / update / close / reject)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    event_type: PositionEventType | None = None
    reject_reason: PositionRejectReason | None = None
    position: Position | None = None
    events: list[PositionEvent] = Field(default_factory=list)
    message: str = ""


class PositionReplayResult(BaseModel):
    """Aggregate A5.1 + A5.2 + A5.3 run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    open_positions: list[Position] = Field(default_factory=list)
    closed_positions: list[Position] = Field(default_factory=list)
    events: list[PositionEvent] = Field(default_factory=list)
    end_of_backtest_policy: EndOfBacktestPolicy
    steps_processed: int = 0
