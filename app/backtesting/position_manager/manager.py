"""Position Manager — lifecycle of individual positions after fills.

Does not decide whether a trade should be opened. Strategies emit signals;
the execution engine fills or rejects orders; this manager tracks the result.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from app.backtesting.order_execution.orders import Fill, OrderSide
from app.backtesting.order_execution.schemas import (
    ClosedTradeRecord,
    ExecutionAttempt,
    ExitReason,
    RejectionReason,
)
from app.backtesting.position_manager.exceptions import (
    PositionInvariantError,
    PositionLookAheadError,
)
from app.backtesting.position_manager.schemas import (
    EndOfBacktestPolicy,
    Position,
    PositionActionResult,
    PositionEvent,
    PositionEventType,
    PositionExitReason,
    PositionManagerConfig,
    PositionRejectReason,
    PositionSide,
    PositionStatus,
)
from app.core.logging import get_logger
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType

logger = get_logger(__name__)

DebugCallback = Callable[[str], None]


class PositionManager:
    """Track open/closed positions per symbol (long-only, no pyramiding by default)."""

    def __init__(
        self,
        config: PositionManagerConfig | None = None,
        *,
        debug_callback: DebugCallback | None = None,
    ) -> None:
        self._config = config or PositionManagerConfig()
        self._debug_callback = debug_callback or print
        self._open: dict[str, Position] = {}
        self._closed: list[Position] = []
        self._events: list[PositionEvent] = []

    @property
    def config(self) -> PositionManagerConfig:
        return self._config

    @property
    def events(self) -> list[PositionEvent]:
        return list(self._events)

    def reset(self) -> None:
        """Clear all state (required between backtest runs)."""
        self._open.clear()
        self._closed.clear()
        self._events.clear()

    clear = reset

    def get_position(self, symbol: str) -> Position | None:
        return self._open.get(_norm_symbol(symbol))

    def get_open_positions(self) -> list[Position]:
        return list(self._open.values())

    def get_closed_positions(self) -> list[Position]:
        return list(self._closed)

    def has_open_position(self, symbol: str) -> bool:
        return _norm_symbol(symbol) in self._open

    def open_position(
        self,
        *,
        symbol: str,
        quantity: float,
        entry_price: float,
        entry_timestamp: datetime,
        stop_loss: float | None = None,
        target_1: float | None = None,
        target_2: float | None = None,
        strategy_name: str = "",
        confidence: float = 0.0,
        entry_order_id: str = "",
        position_id: str | None = None,
        side: PositionSide = PositionSide.LONG,
    ) -> PositionActionResult:
        """Create an OPEN position. Call only after a BUY fill."""
        key = _norm_symbol(symbol)
        if side is not PositionSide.LONG:
            return self._reject(
                symbol=key,
                timestamp=entry_timestamp,
                reason=PositionRejectReason.SHORT_NOT_SUPPORTED,
                message="short positions are not supported",
                quantity=quantity,
                price=entry_price,
            )
        existing = self._open.get(key)
        if existing is not None:
            return self._reject(
                symbol=key,
                timestamp=entry_timestamp,
                reason=PositionRejectReason.ALREADY_POSITIONED,
                message="ALREADY_POSITIONED",
                quantity=quantity,
                price=entry_price,
                position=existing,
            )

        pid = position_id or _deterministic_id(key, entry_order_id, entry_timestamp)
        position = Position(
            position_id=pid,
            symbol=key,
            side=PositionSide.LONG,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            entry_timestamp=entry_timestamp,
            last_updated_timestamp=entry_timestamp,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            status=PositionStatus.OPEN,
            strategy_name=strategy_name,
            confidence=confidence,
            entry_order_id=entry_order_id,
            holding_period=timedelta(0),
        )
        self._open[key] = position
        event = self._emit(
            event_type=PositionEventType.POSITION_OPENED,
            timestamp=entry_timestamp,
            symbol=key,
            position=position,
            action="OPEN",
            quantity=quantity,
            price=entry_price,
        )
        return PositionActionResult(
            accepted=True,
            event_type=PositionEventType.POSITION_OPENED,
            position=position,
            events=[event],
            message="POSITION_OPENED",
        )

    def update_position(
        self,
        symbol: str,
        *,
        current_price: float,
        timestamp: datetime,
    ) -> PositionActionResult:
        """Update mark price / holding period. Never mutates entry_price."""
        return self.mark_to_market(symbol, current_price=current_price, timestamp=timestamp)

    def mark_to_market(
        self,
        symbol: str,
        *,
        current_price: float,
        timestamp: datetime,
    ) -> PositionActionResult:
        position = self._require_open(symbol, timestamp=timestamp, price=current_price)
        if not position.accepted:
            return position
        opened = self._open[_norm_symbol(symbol)]
        self._assert_not_before(opened, timestamp)
        if current_price <= 0:
            raise PositionInvariantError(f"current_price must be > 0 (got {current_price})")

        unrealized = _gross_pnl(current_price, opened.entry_price, opened.quantity)
        updated = opened.model_copy(
            update={
                "current_price": current_price,
                "unrealized_pnl": unrealized,
                "last_updated_timestamp": timestamp,
                "holding_period": timestamp - opened.entry_timestamp,
            },
        )
        self._open[updated.symbol] = updated
        event = self._emit(
            event_type=PositionEventType.POSITION_UPDATED,
            timestamp=timestamp,
            symbol=updated.symbol,
            position=updated,
            action="MARK_TO_MARKET",
            quantity=updated.quantity,
            price=current_price,
        )
        return PositionActionResult(
            accepted=True,
            event_type=PositionEventType.POSITION_UPDATED,
            position=updated,
            events=[event],
            message="POSITION_UPDATED",
        )

    def close_position(
        self,
        symbol: str,
        *,
        exit_price: float,
        exit_timestamp: datetime,
        exit_reason: PositionExitReason,
        exit_order_id: str | None = None,
        realized_pnl: float | None = None,
    ) -> PositionActionResult:
        """Close the open lot. Preserves the record in closed history."""
        key = _norm_symbol(symbol)
        opened = self._open.get(key)
        if opened is None:
            return self._reject(
                symbol=key,
                timestamp=exit_timestamp,
                reason=PositionRejectReason.NO_OPEN_POSITION,
                message="NO_OPEN_POSITION",
                price=exit_price,
            )
        self._assert_not_before(opened, exit_timestamp)
        if exit_price <= 0:
            raise PositionInvariantError(f"exit_price must be > 0 (got {exit_price})")

        gross = _gross_pnl(exit_price, opened.entry_price, opened.quantity)
        net = gross if realized_pnl is None else realized_pnl
        closed = opened.model_copy(
            update={
                "status": PositionStatus.CLOSED,
                "current_price": exit_price,
                "exit_price": exit_price,
                "exit_timestamp": exit_timestamp,
                "exit_reason": exit_reason,
                "exit_order_id": exit_order_id,
                "realized_pnl": net,
                "gross_realized_pnl": gross,
                "unrealized_pnl": 0.0,
                "last_updated_timestamp": exit_timestamp,
                "holding_period": exit_timestamp - opened.entry_timestamp,
            },
        )
        self._open.pop(key)
        self._closed.append(closed)
        event = self._emit(
            event_type=PositionEventType.POSITION_CLOSED,
            timestamp=exit_timestamp,
            symbol=key,
            position=closed,
            action="CLOSE",
            quantity=closed.quantity,
            price=exit_price,
            extra_exit_reason=exit_reason,
        )
        return PositionActionResult(
            accepted=True,
            event_type=PositionEventType.POSITION_CLOSED,
            position=closed,
            events=[event],
            message=f"POSITION_CLOSED:{exit_reason.value}",
        )

    def apply_fill(
        self,
        fill: Fill,
        *,
        recommendation: TradeRecommendation | None = None,
        exit_reason: PositionExitReason | None = None,
        closed_trade: ClosedTradeRecord | None = None,
        signal: SignalType | None = None,
    ) -> PositionActionResult:
        """Apply an execution fill. Partial-fill extension: uses ``fill.quantity``."""
        if fill.quantity <= 0 or fill.execution_price <= 0:
            return self._reject(
                symbol=fill.symbol,
                timestamp=fill.filled_at,
                reason=PositionRejectReason.INVALID_FILL,
                message="INVALID_FILL",
                quantity=fill.quantity,
                price=fill.execution_price,
            )

        if fill.side is OrderSide.BUY:
            return self.open_position(
                symbol=fill.symbol,
                quantity=fill.quantity,
                entry_price=fill.execution_price,
                entry_timestamp=fill.filled_at,
                stop_loss=recommendation.stop_loss if recommendation else None,
                target_1=recommendation.target_1 if recommendation else None,
                target_2=recommendation.target_2 if recommendation else None,
                strategy_name=(
                    recommendation.strategy_name if recommendation else fill.symbol
                ),
                confidence=recommendation.confidence if recommendation else 0.0,
                entry_order_id=fill.order_id,
            )

        remaining = self.get_position(fill.symbol)
        if remaining is None:
            return self._reject(
                symbol=fill.symbol,
                timestamp=fill.filled_at,
                reason=PositionRejectReason.NO_OPEN_POSITION,
                message="NO_OPEN_POSITION",
                quantity=fill.quantity,
                price=fill.execution_price,
            )
        if fill.quantity + 1e-12 < remaining.quantity:
            return self._apply_partial_sell(fill, remaining)

        reason = exit_reason or _infer_exit_reason(
            signal=signal or (recommendation.signal if recommendation else None),
            closed_trade=closed_trade,
            position=remaining,
            exit_price=fill.execution_price,
        )
        return self.close_position(
            fill.symbol,
            exit_price=fill.execution_price,
            exit_timestamp=fill.filled_at,
            exit_reason=reason,
            exit_order_id=fill.order_id,
            realized_pnl=fill.realized_pnl,
        )

    def apply_attempt(
        self,
        attempt: ExecutionAttempt,
        recommendation: TradeRecommendation,
        *,
        exit_reason: PositionExitReason | None = None,
    ) -> PositionActionResult:
        """Map one A5.2 execution attempt onto position state."""
        if attempt.reason_code is RejectionReason.NO_ORDER_FOR_SIGNAL:
            return PositionActionResult(
                accepted=False,
                message="NO_ORDER_FOR_SIGNAL",
            )
        if not attempt.accepted or attempt.fill is None:
            return self.apply_rejection(attempt, recommendation)
        return self.apply_fill(
            attempt.fill,
            recommendation=recommendation,
            exit_reason=exit_reason,
            closed_trade=attempt.closed_trade,
            signal=recommendation.signal,
        )

    def apply_rejection(
        self,
        attempt: ExecutionAttempt,
        recommendation: TradeRecommendation,
    ) -> PositionActionResult:
        mapped = _map_rejection(attempt.reason_code)
        return self._reject(
            symbol=recommendation.symbol,
            timestamp=recommendation.timestamp,
            reason=mapped,
            message=attempt.reason or mapped.value,
            price=recommendation.entry_price,
            position=self.get_position(recommendation.symbol),
        )

    def process_bar(
        self,
        symbol: str,
        timestamp: datetime,
        *,
        open_price: float,
        high: float,
        low: float,
        close: float,
    ) -> list[PositionEvent]:
        """Apply one historical OHLC bar. Uses only this bar — no future data.

        Stop-loss takes priority over targets on the same bar. Does not submit
        orders; emits ``STOP_LOSS_TRIGGERED`` so the execution engine can exit.
        """
        position = self.get_position(symbol)
        if position is None:
            return []
        self._assert_not_before(position, timestamp)
        if close <= 0 or high <= 0 or low <= 0 or open_price <= 0:
            raise PositionInvariantError("bar OHLC prices must be > 0")
        if high < low:
            raise PositionInvariantError("bar high must be >= low")

        entry_bar = timestamp == position.entry_timestamp
        skip_protective = (
            self._config.skip_protective_checks_on_entry_bar and entry_bar
        )

        events: list[PositionEvent] = []
        if not skip_protective:
            stop_px = self.stop_fill_price(
                position,
                open_price=open_price,
                low=low,
            )
            if stop_px is not None:
                flagged = self._flag_stop(position, timestamp=timestamp)
                events.extend(flagged.events)
                return events

            t1 = self.check_target_1(position.symbol, high=high)
            if t1 and not position.target_1_hit:
                events.extend(self._flag_target(position, level=1, timestamp=timestamp).events)
                position = self._open[position.symbol]
            t2 = self.check_target_2(position.symbol, high=high)
            if t2 and not position.target_2_hit:
                events.extend(self._flag_target(position, level=2, timestamp=timestamp).events)

        mtm = self.mark_to_market(symbol, current_price=close, timestamp=timestamp)
        events.extend(mtm.events)
        return events

    def check_stop_loss(
        self,
        symbol: str,
        *,
        low: float,
        open_price: float | None = None,
    ) -> bool:
        position = self.get_position(symbol)
        if position is None or position.stop_loss is None:
            return False
        if open_price is not None and open_price <= position.stop_loss:
            return True
        return low <= position.stop_loss

    def stop_fill_price(
        self,
        position: Position,
        *,
        open_price: float,
        low: float,
    ) -> float | None:
        """Conservative stop fill from this bar only (gap at open, else stop)."""
        if position.stop_loss is None:
            return None
        if open_price <= position.stop_loss:
            return open_price
        if low <= position.stop_loss:
            return position.stop_loss
        return None

    def check_target_1(self, symbol: str, *, high: float) -> bool:
        position = self.get_position(symbol)
        if position is None or position.target_1 is None:
            return False
        return high >= position.target_1

    def check_target_2(self, symbol: str, *, high: float) -> bool:
        position = self.get_position(symbol)
        if position is None or position.target_2 is None:
            return False
        return high >= position.target_2

    def apply_end_of_backtest_mark(
        self,
        symbol: str,
        *,
        price: float,
        timestamp: datetime,
    ) -> PositionActionResult:
        """MARK_TO_MARKET / LEAVE_OPEN helper — does not close."""
        if self._config.end_of_backtest is EndOfBacktestPolicy.LEAVE_OPEN:
            current = self.get_position(symbol)
            return PositionActionResult(
                accepted=current is not None,
                position=current,
                message="LEAVE_OPEN",
            )
        return self.mark_to_market(symbol, current_price=price, timestamp=timestamp)

    def _apply_partial_sell(self, fill: Fill, position: Position) -> PositionActionResult:
        """Extension point: A5.2 does not emit partial fills. Keep remaining qty."""
        remaining_qty = position.quantity - fill.quantity
        if remaining_qty <= 0:
            raise PositionInvariantError("partial sell cannot reduce quantity below zero")
        gross_slice = _gross_pnl(fill.execution_price, position.entry_price, fill.quantity)
        updated = position.model_copy(
            update={
                "quantity": remaining_qty,
                "status": PositionStatus.PARTIALLY_CLOSED,
                "current_price": fill.execution_price,
                "last_updated_timestamp": fill.filled_at,
                "holding_period": fill.filled_at - position.entry_timestamp,
                "realized_pnl": position.realized_pnl + fill.realized_pnl,
                "gross_realized_pnl": position.gross_realized_pnl + gross_slice,
                "unrealized_pnl": _gross_pnl(
                    fill.execution_price,
                    position.entry_price,
                    remaining_qty,
                ),
            },
        )
        self._open[updated.symbol] = updated
        event = self._emit(
            event_type=PositionEventType.POSITION_UPDATED,
            timestamp=fill.filled_at,
            symbol=updated.symbol,
            position=updated,
            action="PARTIAL_SELL",
            quantity=remaining_qty,
            price=fill.execution_price,
        )
        return PositionActionResult(
            accepted=True,
            event_type=PositionEventType.POSITION_UPDATED,
            position=updated,
            events=[event],
            message="PARTIALLY_CLOSED",
        )

    def _flag_stop(self, position: Position, *, timestamp: datetime) -> PositionActionResult:
        flagged = position.model_copy(
            update={
                "stop_loss_hit": True,
                "stop_loss_hit_timestamp": timestamp,
                "last_updated_timestamp": timestamp,
            },
        )
        self._open[flagged.symbol] = flagged
        event = self._emit(
            event_type=PositionEventType.STOP_LOSS_TRIGGERED,
            timestamp=timestamp,
            symbol=flagged.symbol,
            position=flagged,
            action="STOP_LOSS",
            quantity=flagged.quantity,
            price=flagged.stop_loss,
            extra_exit_reason=PositionExitReason.STOP_LOSS,
        )
        return PositionActionResult(
            accepted=True,
            event_type=PositionEventType.STOP_LOSS_TRIGGERED,
            position=flagged,
            events=[event],
            message="STOP_LOSS_TRIGGERED",
        )

    def _flag_target(
        self,
        position: Position,
        *,
        level: int,
        timestamp: datetime,
    ) -> PositionActionResult:
        if level == 1:
            updated = position.model_copy(
                update={
                    "target_1_hit": True,
                    "target_1_hit_timestamp": timestamp,
                    "last_updated_timestamp": timestamp,
                },
            )
            event_type = PositionEventType.TARGET_1_HIT
            price = updated.target_1
        else:
            updated = position.model_copy(
                update={
                    "target_2_hit": True,
                    "target_2_hit_timestamp": timestamp,
                    "last_updated_timestamp": timestamp,
                },
            )
            event_type = PositionEventType.TARGET_2_HIT
            price = updated.target_2
        self._open[updated.symbol] = updated
        event = self._emit(
            event_type=event_type,
            timestamp=timestamp,
            symbol=updated.symbol,
            position=updated,
            action=event_type.value,
            quantity=updated.quantity,
            price=price,
        )
        return PositionActionResult(
            accepted=True,
            event_type=event_type,
            position=updated,
            events=[event],
            message=event_type.value,
        )

    def _require_open(
        self,
        symbol: str,
        *,
        timestamp: datetime,
        price: float | None,
    ) -> PositionActionResult:
        key = _norm_symbol(symbol)
        opened = self._open.get(key)
        if opened is None:
            closed = next((p for p in reversed(self._closed) if p.symbol == key), None)
            if closed is not None:
                raise PositionInvariantError(
                    f"closed position {key} cannot continue accumulating unrealized P&L",
                )
            return self._reject(
                symbol=key,
                timestamp=timestamp,
                reason=PositionRejectReason.NO_OPEN_POSITION,
                message="NO_OPEN_POSITION",
                price=price,
            )
        return PositionActionResult(accepted=True, position=opened)

    def _assert_not_before(self, position: Position, timestamp: datetime) -> None:
        if timestamp < position.last_updated_timestamp:
            raise PositionLookAheadError(
                f"{position.symbol}: timestamp {timestamp.isoformat()} is before "
                f"last_updated {position.last_updated_timestamp.isoformat()}",
            )

    def _reject(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        reason: PositionRejectReason,
        message: str,
        quantity: float | None = None,
        price: float | None = None,
        position: Position | None = None,
    ) -> PositionActionResult:
        event = self._emit(
            event_type=PositionEventType.POSITION_REJECTED,
            timestamp=timestamp,
            symbol=symbol,
            position=position,
            action="REJECT",
            quantity=quantity,
            price=price,
            extra_reject=reason,
            message=message,
        )
        return PositionActionResult(
            accepted=False,
            event_type=PositionEventType.POSITION_REJECTED,
            reject_reason=reason,
            position=position,
            events=[event],
            message=message,
        )

    def _emit(
        self,
        *,
        event_type: PositionEventType,
        timestamp: datetime,
        symbol: str,
        position: Position | None,
        action: str,
        quantity: float | None = None,
        price: float | None = None,
        extra_exit_reason: PositionExitReason | None = None,
        extra_reject: PositionRejectReason | None = None,
        message: str = "",
    ) -> PositionEvent:
        event = PositionEvent(
            event_type=event_type,
            timestamp=timestamp,
            symbol=symbol,
            position_id=position.position_id if position else None,
            action=action,
            quantity=quantity if quantity is not None else (position.quantity if position else None),
            price=price,
            status=position.status if position else None,
            realized_pnl=position.realized_pnl if position else None,
            unrealized_pnl=position.unrealized_pnl if position else None,
            exit_reason=extra_exit_reason or (position.exit_reason if position else None),
            reject_reason=extra_reject,
            message=message,
        )
        self._events.append(event)
        self._log_event(event)
        return event

    def _log_event(self, event: PositionEvent) -> None:
        noisy = event.event_type is PositionEventType.POSITION_UPDATED
        line = (
            f"{event.timestamp.isoformat()} {event.symbol} {event.event_type.value} "
            f"action={event.action} qty={event.quantity} px={event.price} "
            f"status={event.status.value if event.status else None} "
            f"realized={event.realized_pnl} unrealized={event.unrealized_pnl} "
            f"exit={event.exit_reason.value if event.exit_reason else None}"
        )
        if noisy:
            logger.debug(line)
        else:
            logger.info(line)
        if self._config.debug:
            self._debug_callback(line)


def _norm_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _deterministic_id(symbol: str, order_id: str, timestamp: datetime) -> str:
    stamp = timestamp.isoformat()
    if order_id:
        return f"{symbol}:{order_id}"
    return f"{symbol}:{stamp}"


def _gross_pnl(exit_or_mark: float, entry: float, quantity: float) -> float:
    return (exit_or_mark - entry) * quantity


def _map_rejection(code: RejectionReason | None) -> PositionRejectReason:
    if code is RejectionReason.ALREADY_HOLDING:
        return PositionRejectReason.ALREADY_POSITIONED
    if code is RejectionReason.NO_OPEN_POSITION:
        return PositionRejectReason.NO_OPEN_POSITION
    return PositionRejectReason.REJECTED_ORDER


def _infer_exit_reason(
    *,
    signal: SignalType | None,
    closed_trade: ClosedTradeRecord | None,
    position: Position,
    exit_price: float,
) -> PositionExitReason:
    if signal is SignalType.EXIT:
        return PositionExitReason.STRATEGY_EXIT
    if signal is SignalType.SELL:
        return PositionExitReason.STRATEGY_SELL
    if closed_trade is not None:
        if closed_trade.exit_reason is ExitReason.STOP_LOSS:
            return PositionExitReason.STOP_LOSS
        if closed_trade.exit_reason is ExitReason.REPLAY_END:
            return PositionExitReason.END_OF_BACKTEST
        if closed_trade.exit_reason is ExitReason.TARGET_HIT:
            if position.target_2_hit or (
                position.target_2 is not None and exit_price >= position.target_2
            ):
                return PositionExitReason.TARGET_2
            return PositionExitReason.TARGET_1
    if position.stop_loss_hit:
        return PositionExitReason.STOP_LOSS
    return PositionExitReason.STRATEGY_SELL
