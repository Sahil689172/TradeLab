"""Load and save per-user paper trading state to/from the database.

The SimulatedBroker keeps its state in memory; this module is the bridge
that persists cash, positions, and orders between server restarts.

Usage (in route handlers)::

    book = load_user_book(session, user_handle="alice")
    result = book.place_order(...)
    save_user_book(session, user_handle="alice", book=book)
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.backtesting.order_execution.schemas import (
    ExecutionConfig,
    PositionSizingMode,
    PositionState,
)
from app.paper_trading.models import (
    PaperTradingAccount,
    PaperTradingOrder,
    PaperTradingPosition,
)
from app.services.dashboard.paper_trading_service import (
    DEFAULT_INITIAL_CAPITAL,
    PaperOrderRecord,
    PaperTradingBook,
)
from app.services.dashboard.schemas import OrderSide as ApiOrderSide, OrderStatus as ApiOrderStatus


def load_user_book(session: Session, *, user_handle: str) -> PaperTradingBook:
    """Reconstruct a PaperTradingBook from persisted state.

    If the user has no account row yet an empty book is returned (and will be
    persisted on the first save).
    """
    account_row = session.get(PaperTradingAccount, user_handle)
    initial_capital = DEFAULT_INITIAL_CAPITAL
    cash = initial_capital
    realized_pnl = 0.0

    if account_row is not None:
        initial_capital = account_row.initial_capital
        cash = account_row.cash
        realized_pnl = account_row.realized_pnl

    book = PaperTradingBook(
        initial_capital=initial_capital,
    )
    # Restore cash and realized P&L directly into the broker.
    book.broker._cash = cash
    book.broker._realized_pnl = realized_pnl
    book.broker._config = ExecutionConfig(
        initial_capital=initial_capital,
        position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
        percent=10.0,
    )

    # Restore open positions.
    pos_stmt = select(PaperTradingPosition).where(
        PaperTradingPosition.user_handle == user_handle
    )
    for row in session.execute(pos_stmt).scalars():
        position = PositionState(
            symbol=row.symbol,
            quantity=row.quantity,
            average_entry_price=row.average_entry_price,
            entry_brokerage=row.entry_brokerage,
            entry_slippage_cost=row.entry_slippage_cost,
            opened_at=_as_aware(row.opened_at),
            stop_loss=row.stop_loss,
            target_1=row.target,
            strategy_name=row.strategy_name,
        )
        book.broker._positions[row.symbol] = position
        # Seed last price to entry so unrealized P&L starts at 0 (will be
        # updated when the portfolio endpoint provides a gateway).
        book.broker._last_prices[row.symbol] = row.average_entry_price

    # Restore order log (most-recent-first, capped for memory).
    ord_stmt = (
        select(PaperTradingOrder)
        .where(PaperTradingOrder.user_handle == user_handle)
        .order_by(PaperTradingOrder.timestamp.desc())
        .limit(500)
    )
    for row in session.execute(ord_stmt).scalars():
        record = PaperOrderRecord(
            order_id=row.order_id,
            timestamp=_as_aware(row.timestamp),
            symbol=row.symbol,
            side=ApiOrderSide(row.side),
            quantity=row.quantity,
            price=row.price,
            order_type=row.order_type,
            status=ApiOrderStatus(row.status),
            rejection_reason=row.rejection_reason,
            strategy_name=row.strategy_name,
            requested_price=row.requested_price,
            execution_price=row.execution_price,
            stop_loss=row.stop_loss,
            target=row.target,
        )
        book.orders.append(record)

    return book


def save_user_book(session: Session, *, user_handle: str, book: PaperTradingBook) -> None:
    """Persist the current state of a PaperTradingBook to the database.

    This is a full-replace strategy for positions (delete + insert) and an
    upsert for the account row.  Orders are append-only — only those not
    already in the DB are inserted.
    """
    broker = book.broker
    snapshot = broker.snapshot()

    # ── Account ─────────────────────────────────────────────────────────────
    account_row = session.get(PaperTradingAccount, user_handle)
    now = datetime.now(timezone.utc)
    if account_row is None:
        account_row = PaperTradingAccount(
            user_handle=user_handle,
            initial_capital=book.initial_capital,
            cash=snapshot.cash,
            realized_pnl=snapshot.realized_pnl,
            created_at=now,
            updated_at=now,
        )
        session.add(account_row)
    else:
        account_row.cash = snapshot.cash
        account_row.realized_pnl = snapshot.realized_pnl
        account_row.updated_at = now

    # ── Positions (full replace) ─────────────────────────────────────────────
    session.execute(
        delete(PaperTradingPosition).where(
            PaperTradingPosition.user_handle == user_handle
        )
    )
    for symbol, position in snapshot.positions.items():
        if not position.is_open:
            continue
        session.add(
            PaperTradingPosition(
                user_handle=user_handle,
                symbol=symbol,
                quantity=position.quantity,
                average_entry_price=position.average_entry_price,
                entry_brokerage=position.entry_brokerage,
                entry_slippage_cost=position.entry_slippage_cost,
                stop_loss=position.stop_loss,
                target=position.target_1,
                strategy_name=position.strategy_name,
                opened_at=_as_aware(position.opened_at),
            )
        )

    # ── Orders (append-only) ─────────────────────────────────────────────────
    existing_ids_stmt = select(PaperTradingOrder.order_id).where(
        PaperTradingOrder.user_handle == user_handle
    )
    existing_ids: set[str] = set(session.execute(existing_ids_stmt).scalars())

    for record in book.orders:
        if record.order_id in existing_ids:
            continue
        session.add(
            PaperTradingOrder(
                order_id=record.order_id,
                user_handle=user_handle,
                timestamp=_as_aware(record.timestamp),
                symbol=record.symbol,
                side=record.side.value,
                quantity=record.quantity,
                price=record.price,
                order_type=record.order_type,
                status=record.status.value,
                rejection_reason=record.rejection_reason,
                strategy_name=record.strategy_name,
                requested_price=record.requested_price,
                execution_price=record.execution_price,
                stop_loss=record.stop_loss,
                target=record.target,
            )
        )

    session.commit()


def _as_aware(dt: datetime | None) -> datetime:
    """Ensure a datetime is timezone-aware UTC."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
