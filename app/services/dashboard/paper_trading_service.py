"""In-memory paper trading book using A5.2 broker (simulated only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.backtesting.order_execution.broker import SimulatedBroker
from app.backtesting.order_execution.engine import OrderExecutionEngine
from app.backtesting.order_execution.orders import MarketOrder, OrderSide, OrderStatus
from app.backtesting.order_execution.schemas import ExecutionConfig, PositionSizingMode, RejectionReason
from app.backtesting.portfolio_risk.limits import check_entry_limits
from app.backtesting.portfolio_risk.schemas import PortfolioRiskLimits
from app.market_data.utils.symbols import parquet_basename
from app.services.dashboard.schemas import (
    OrderRequest,
    OrderResponse,
    OrderRow,
    OrderSide as ApiOrderSide,
    OrderStatus as ApiOrderStatus,
)


DEFAULT_INITIAL_CAPITAL = 1_000_000.0


@dataclass
class PaperOrderRecord:
    order_id: str
    timestamp: datetime
    symbol: str
    side: ApiOrderSide
    quantity: float
    price: float
    order_type: str
    status: ApiOrderStatus
    rejection_reason: str | None = None
    strategy_name: str = "paper_manual"
    requested_price: float | None = None
    execution_price: float | None = None
    stop_loss: float | None = None
    target: float | None = None


@dataclass
class PaperTradingBook:
    """Process-local simulated brokerage (paper only — not live execution)."""

    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    execution: OrderExecutionEngine = field(default_factory=lambda: OrderExecutionEngine(
        ExecutionConfig(
            initial_capital=DEFAULT_INITIAL_CAPITAL,
            position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
            percent=10.0,
        ),
    ))
    orders: list[PaperOrderRecord] = field(default_factory=list)
    watchlist: set[str] = field(default_factory=set)
    favorites: set[str] = field(default_factory=set)

    @property
    def broker(self) -> SimulatedBroker:
        return self.execution.broker

    def place_order(
        self,
        side: ApiOrderSide,
        request: OrderRequest,
        *,
        market_price: float,
    ) -> OrderResponse:
        symbol = parquet_basename(request.symbol).upper()
        ts = datetime.now(timezone.utc)
        price = float(request.price if request.price is not None else market_price)
        validation_error = self._validate(side, request, symbol, price)
        if validation_error:
            record = PaperOrderRecord(
                order_id=uuid4().hex,
                timestamp=ts,
                symbol=symbol,
                side=side,
                quantity=request.quantity,
                price=price,
                order_type=request.order_type,
                status=ApiOrderStatus.REJECTED,
                rejection_reason=validation_error,
                requested_price=price,
                stop_loss=request.stop_loss,
                target=request.target,
            )
            self.orders.insert(0, record)
            return OrderResponse(
                accepted=False,
                status=ApiOrderStatus.REJECTED,
                message=validation_error,
                order=_to_order_row(record),
            )

        order_side = OrderSide.BUY if side is ApiOrderSide.BUY else OrderSide.SELL
        qty = request.quantity
        if side is ApiOrderSide.SELL:
            position = self.broker.get_position(symbol)
            qty = min(request.quantity, position.quantity)
        try:
            order = MarketOrder(
                order_id=uuid4().hex[:12],
                symbol=symbol,
                side=order_side,
                quantity=qty,
                submitted_at=ts,
                reference_price=price,
                strategy_name="paper_manual",
                status=OrderStatus.PENDING,
            )
            fill = self.broker.submit_market_order(
                order,
                stop_loss=request.stop_loss,
                target_1=request.target,
            )
            record = PaperOrderRecord(
                order_id=fill.fill_id,
                timestamp=ts,
                symbol=symbol,
                side=side,
                quantity=fill.quantity,
                price=float(fill.execution_price),
                order_type=request.order_type,
                status=ApiOrderStatus.FILLED,
                requested_price=price,
                execution_price=float(fill.execution_price),
                stop_loss=request.stop_loss,
                target=request.target,
            )
            self.orders.insert(0, record)
            from app.services.dashboard.portfolio_service import PortfolioService

            kpis = PortfolioService(self).kpis()
            return OrderResponse(
                accepted=True,
                status=ApiOrderStatus.FILLED,
                message="FILLED",
                order=_to_order_row(record),
                portfolio=kpis,
            )
        except Exception as exc:
            record = PaperOrderRecord(
                order_id=uuid4().hex,
                timestamp=ts,
                symbol=symbol,
                side=side,
                quantity=request.quantity,
                price=price,
                order_type=request.order_type,
                status=ApiOrderStatus.REJECTED,
                rejection_reason=str(exc),
                requested_price=price,
                stop_loss=request.stop_loss,
                target=request.target,
            )
            self.orders.insert(0, record)
            return OrderResponse(
                accepted=False,
                status=ApiOrderStatus.REJECTED,
                message=str(exc),
                order=_to_order_row(record),
            )

    def _validate(
        self,
        side: ApiOrderSide,
        request: OrderRequest,
        symbol: str,
        price: float,
    ) -> str | None:
        if price <= 0:
            return "Invalid price"
        if request.quantity <= 0:
            return "Invalid quantity"
        if request.stop_loss is not None and request.stop_loss >= price and side is ApiOrderSide.BUY:
            return "Stop loss must be below entry price for BUY"
        if request.target is not None and request.target <= price and side is ApiOrderSide.BUY:
            return "Target must be above entry price for BUY"
        if request.stop_loss is not None and request.stop_loss <= price and side is ApiOrderSide.SELL:
            return "Stop loss must be above exit price for SELL"
        if request.target is not None and request.target >= price and side is ApiOrderSide.SELL:
            return "Target must be below exit price for SELL"
        if side is ApiOrderSide.BUY:
            notional = price * request.quantity
            if notional > self.broker.cash + 1e-6:
                return RejectionReason.INSUFFICIENT_CASH.value
            snap = self.broker.snapshot()
            open_positions = [p for p in snap.positions.values() if p.is_open]
            already = any(p.symbol == symbol and p.is_open for p in snap.positions.values())
            gross = sum(p.quantity * p.average_entry_price for p in open_positions)
            symbol_notional = sum(
                p.quantity * p.average_entry_price for p in open_positions if p.symbol == symbol
            )
            reason, message, _allowed = check_entry_limits(
                limits=PortfolioRiskLimits(),
                open_positions=len(open_positions),
                already_holding=already,
                equity=snap.equity or self.initial_capital,
                gross_exposure=gross,
                proposed_notional=notional,
                symbol=symbol,
                strategy="paper_manual",
                symbol_notional=symbol_notional,
                strategy_notional=gross,
                drawdown_pct=0.0,
                daily_loss_pct=0.0,
            )
            if reason is not None:
                return message
        if side is ApiOrderSide.SELL:
            position = self.broker.get_position(symbol)
            if not position.is_open:
                return RejectionReason.NO_OPEN_POSITION.value
            if request.quantity > position.quantity + 1e-9:
                return "Sell quantity exceeds open position"
        return None


def _to_order_row(record: PaperOrderRecord) -> OrderRow:
    return OrderRow(
        order_id=record.order_id,
        timestamp=record.timestamp,
        symbol=record.symbol,
        side=record.side,
        quantity=record.quantity,
        price=record.price,
        order_type=record.order_type,
        status=record.status,
        rejection_reason=record.rejection_reason,
        strategy_name=record.strategy_name,
        requested_price=record.requested_price,
        execution_price=record.execution_price,
        stop_loss=record.stop_loss,
        target=record.target,
    )


_book: PaperTradingBook | None = None


def get_paper_book() -> PaperTradingBook:
    global _book
    if _book is None:
        _book = PaperTradingBook()
    return _book


def reset_paper_book() -> None:
    global _book
    _book = PaperTradingBook()
