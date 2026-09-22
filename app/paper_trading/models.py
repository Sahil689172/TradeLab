"""SQLAlchemy ORM models for persistent paper trading state.

One row per user in paper_trading_accounts (cash + initial_capital).
One row per open position in paper_trading_positions.
One row per order in paper_trading_orders.

All tables are keyed by ``user_handle`` — a free-text handle matching
the rest of the app's identity model.  When real auth is added the
foreign key can be changed to a user_id integer without touching the
service layer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PaperTradingAccount(Base):
    """Cash balance and lifetime stats per user."""

    __tablename__ = "paper_trading_accounts"

    user_handle: Mapped[str] = mapped_column(String(40), primary_key=True)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=1_000_000.0)
    cash: Mapped[float] = mapped_column(Float, nullable=False, default=1_000_000.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )


class PaperTradingPosition(Base):
    """One open long position for a user."""

    __tablename__ = "paper_trading_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_handle: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    average_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_brokerage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_slippage_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False, default="paper_manual")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_pt_positions_user_symbol", "user_handle", "symbol", unique=True),
    )


class PaperTradingOrder(Base):
    """One executed or rejected paper order."""

    __tablename__ = "paper_trading_orders"

    order_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_handle: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)          # BUY / SELL
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MARKET")
    status: Mapped[str] = mapped_column(String(16), nullable=False)        # FILLED / REJECTED
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False, default="paper_manual")
    requested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_pt_orders_user_ts", "user_handle", "timestamp"),
    )


__all__ = ["PaperTradingAccount", "PaperTradingPosition", "PaperTradingOrder"]
