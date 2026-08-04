"""Simulated broker — cash, positions, brokerage, slippage, trade log."""

from __future__ import annotations

from datetime import datetime, timezone

from app.backtesting.order_execution.exceptions import (
    OrderConfigurationError,
    OrderRejectedError,
)
from app.backtesting.order_execution.orders import Fill, MarketOrder, OrderSide, OrderStatus
from app.backtesting.order_execution.schemas import (
    AccountSnapshot,
    ExecutionConfig,
    PositionState,
    TradeLogEntry,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class SimulatedBroker:
    """Long-only simulated market broker.

    Rules:
    - Cannot BUY when already holding the symbol.
    - Cannot SELL when flat.
    - BUY size respects available cash after estimated brokerage.
    """

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self._config = config or ExecutionConfig()
        if self._config.initial_capital <= 0:
            raise OrderConfigurationError("initial_capital must be > 0")
        self._cash = float(self._config.initial_capital)
        self._realized_pnl = 0.0
        self._positions: dict[str, PositionState] = {}
        self._trade_log: list[TradeLogEntry] = []
        self._last_prices: dict[str, float] = {}

    @property
    def config(self) -> ExecutionConfig:
        return self._config

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def trade_log(self) -> list[TradeLogEntry]:
        return list(self._trade_log)

    def get_position(self, symbol: str) -> PositionState:
        key = symbol.strip().upper()
        return self._positions.get(
            key,
            PositionState(symbol=key, quantity=0.0, average_entry_price=0.0),
        )

    def submit_market_order(self, order: MarketOrder) -> Fill:
        """Fill a market order or raise ``OrderRejectedError``."""
        if order.status is OrderStatus.REJECTED:
            raise OrderRejectedError(order.reject_reason or "order already rejected")
        if order.quantity <= 0:
            raise OrderRejectedError("quantity must be > 0")
        if order.reference_price <= 0:
            raise OrderRejectedError("reference_price must be > 0")

        symbol = order.symbol
        position = self.get_position(symbol)
        self._last_prices[symbol] = order.reference_price

        if order.side is OrderSide.BUY:
            return self._fill_buy(order, position)
        return self._fill_sell(order, position)

    def mark_to_market(self, prices: dict[str, float]) -> AccountSnapshot:
        for symbol, price in prices.items():
            if price > 0:
                self._last_prices[symbol.strip().upper()] = float(price)
        return self.snapshot()

    def snapshot(self) -> AccountSnapshot:
        unrealized = self._unrealized_pnl()
        equity = self._cash + self._positions_market_value()
        return AccountSnapshot(
            cash=self._cash,
            initial_capital=self._config.initial_capital,
            realized_pnl=self._realized_pnl,
            unrealized_pnl=unrealized,
            equity=equity,
            positions=dict(self._positions),
        )

    def size_buy_quantity(self, *, reference_price: float) -> float:
        """Compute BUY quantity from cash / config without mutating state."""
        if reference_price <= 0:
            raise OrderRejectedError("reference_price must be > 0")
        if self._config.fixed_quantity is not None:
            qty = float(self._config.fixed_quantity)
        else:
            budget = self._cash * self._config.position_size_pct
            # Leave room for brokerage on notional ≈ budget
            effective = budget / (1.0 + self._config.brokerage_rate) - self._config.brokerage_flat
            if effective <= 0:
                return 0.0
            exec_price = self._execution_price(OrderSide.BUY, reference_price)
            qty = effective / exec_price
        if not self._config.allow_fractional_shares:
            qty = float(int(qty))
        return max(0.0, qty)

    def _fill_buy(self, order: MarketOrder, position: PositionState) -> Fill:
        if position.is_open:
            raise OrderRejectedError(
                f"Cannot BUY {order.symbol}: already holding "
                f"{position.quantity:g} shares",
            )

        exec_price = self._execution_price(OrderSide.BUY, order.reference_price)
        slippage_per_unit = exec_price - order.reference_price
        notional = exec_price * order.quantity
        brokerage = self._brokerage(notional)
        total_cost = notional + brokerage
        if total_cost > self._cash + 1e-9:
            raise OrderRejectedError(
                f"Insufficient cash for BUY {order.symbol}: "
                f"need {total_cost:.4f}, have {self._cash:.4f}",
            )

        self._cash -= total_cost
        slippage_cost = abs(slippage_per_unit) * order.quantity
        opened = PositionState(
            symbol=order.symbol,
            quantity=order.quantity,
            average_entry_price=exec_price,
            entry_brokerage=brokerage,
            entry_slippage_cost=slippage_cost,
            opened_at=order.submitted_at,
        )
        self._positions[order.symbol] = opened

        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=OrderSide.BUY,
            quantity=order.quantity,
            reference_price=order.reference_price,
            execution_price=exec_price,
            slippage_per_unit=slippage_per_unit,
            slippage_cost=slippage_cost,
            brokerage=brokerage,
            filled_at=order.submitted_at,
            cash_delta=-total_cost,
            realized_pnl=0.0,
        )
        self._log_trade(
            order=order,
            fill=fill,
            pnl=0.0,
            average_entry_price=exec_price,
            average_exit_price=None,
        )
        logger.info(
            "FILL BUY %s qty=%.6g px=%.6g brokerage=%.4f cash=%.2f",
            order.symbol,
            order.quantity,
            exec_price,
            brokerage,
            self._cash,
        )
        return fill

    def _fill_sell(self, order: MarketOrder, position: PositionState) -> Fill:
        if not position.is_open:
            raise OrderRejectedError(f"Cannot SELL {order.symbol}: no open position")
        if order.quantity > position.quantity + 1e-12:
            raise OrderRejectedError(
                f"Cannot SELL {order.quantity:g} of {order.symbol}: "
                f"only holding {position.quantity:g}",
            )
        # This broker closes the full open lot (long-only single position).
        qty = position.quantity
        exec_price = self._execution_price(OrderSide.SELL, order.reference_price)
        slippage_per_unit = order.reference_price - exec_price
        notional = exec_price * qty
        brokerage = self._brokerage(notional)
        proceeds = notional - brokerage
        slippage_cost = abs(slippage_per_unit) * qty

        # Realized PnL vs average entry, net of entry+exit brokerage and slippage costs.
        gross = (exec_price - position.average_entry_price) * qty
        realized = (
            gross
            - position.entry_brokerage
            - brokerage
            - position.entry_slippage_cost
            - slippage_cost
        )
        self._cash += proceeds
        self._realized_pnl += realized
        self._positions.pop(order.symbol, None)

        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=OrderSide.SELL,
            quantity=qty,
            reference_price=order.reference_price,
            execution_price=exec_price,
            slippage_per_unit=slippage_per_unit,
            slippage_cost=slippage_cost,
            brokerage=brokerage,
            filled_at=order.submitted_at,
            cash_delta=proceeds,
            realized_pnl=realized,
        )
        self._log_trade(
            order=order,
            fill=fill,
            pnl=realized,
            average_entry_price=position.average_entry_price,
            average_exit_price=exec_price,
        )
        logger.info(
            "FILL SELL %s qty=%.6g px=%.6g pnl=%.4f cash=%.2f",
            order.symbol,
            qty,
            exec_price,
            realized,
            self._cash,
        )
        return fill

    def _execution_price(self, side: OrderSide, reference: float) -> float:
        slip = reference * (self._config.slippage_bps / 10_000.0)
        if side is OrderSide.BUY:
            return reference + slip
        return max(reference - slip, 1e-12)

    def _brokerage(self, notional: float) -> float:
        return abs(notional) * self._config.brokerage_rate + self._config.brokerage_flat

    def _positions_market_value(self) -> float:
        total = 0.0
        for symbol, position in self._positions.items():
            price = self._last_prices.get(symbol, position.average_entry_price)
            total += position.quantity * price
        return total

    def _unrealized_pnl(self) -> float:
        total = 0.0
        for symbol, position in self._positions.items():
            if not position.is_open:
                continue
            price = self._last_prices.get(symbol, position.average_entry_price)
            total += (price - position.average_entry_price) * position.quantity
        return total

    def _log_trade(
        self,
        *,
        order: MarketOrder,
        fill: Fill,
        pnl: float,
        average_entry_price: float | None,
        average_exit_price: float | None,
    ) -> None:
        entry = TradeLogEntry(
            timestamp=fill.filled_at,
            symbol=fill.symbol,
            side=fill.side,
            quantity=fill.quantity,
            execution_price=fill.execution_price,
            brokerage=fill.brokerage,
            slippage=fill.slippage_cost,
            pnl=pnl,
            remaining_cash=self._cash,
            order_id=order.order_id,
            fill_id=fill.fill_id,
            strategy_name=order.strategy_name,
            average_entry_price=average_entry_price,
            average_exit_price=average_exit_price,
        )
        self._trade_log.append(entry)
