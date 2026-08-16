"""Simulated broker — cash, positions, brokerage, slippage, fill / trade logs."""

from __future__ import annotations

from datetime import datetime

from app.backtesting.order_execution.costs import (
    brokerage_charge,
    execution_price,
    quantity_from_budget,
)
from app.backtesting.order_execution.exceptions import (
    OrderConfigurationError,
    OrderRejectedError,
)
from app.backtesting.order_execution.orders import Fill, MarketOrder, OrderSide, OrderStatus
from app.backtesting.order_execution.schemas import (
    AccountSnapshot,
    ClosedTradeRecord,
    ExecutionConfig,
    ExitReason,
    FillLogEntry,
    PositionSizingMode,
    PositionState,
    RejectionReason,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class SimulatedBroker:
    """Long-only simulated market broker.

    Rules:
    - Cannot BUY when already holding the symbol.
    - Cannot SELL when flat.
    - BUY size respects available cash after estimated brokerage.
    - Whole shares only unless ``allow_fractional_shares`` is True.
    """

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self._config = config or ExecutionConfig()
        if self._config.initial_capital <= 0:
            raise OrderConfigurationError("initial_capital must be > 0")
        self._cash = float(self._config.initial_capital)
        self._realized_pnl = 0.0
        self._positions: dict[str, PositionState] = {}
        self._fill_log: list[FillLogEntry] = []
        self._closed_trades: list[ClosedTradeRecord] = []
        self._last_prices: dict[str, float] = {}
        self._peak_position_notional: float = 0.0

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
    def trade_log(self) -> list[FillLogEntry]:
        """Fill-level log (A5.2 back-compat name)."""
        return list(self._fill_log)

    @property
    def fill_log(self) -> list[FillLogEntry]:
        return list(self._fill_log)

    @property
    def closed_trades(self) -> list[ClosedTradeRecord]:
        return list(self._closed_trades)

    def get_position(self, symbol: str) -> PositionState:
        key = symbol.strip().upper()
        return self._positions.get(
            key,
            PositionState(symbol=key, quantity=0.0, average_entry_price=0.0),
        )

    def submit_market_order(
        self,
        order: MarketOrder,
        *,
        stop_loss: float | None = None,
        target_1: float | None = None,
        exit_reason: ExitReason | None = None,
    ) -> Fill:
        """Fill a market order or raise ``OrderRejectedError``."""
        if order.status is OrderStatus.REJECTED:
            raise OrderRejectedError(
                order.reject_reason or RejectionReason.VALIDATION_FAILURE.value,
                reason_code=RejectionReason.VALIDATION_FAILURE,
            )
        if order.quantity <= 0:
            raise OrderRejectedError(
                RejectionReason.BELOW_MIN_QUANTITY.value,
                reason_code=RejectionReason.BELOW_MIN_QUANTITY,
            )
        if order.reference_price <= 0:
            raise OrderRejectedError(
                RejectionReason.INVALID_RECOMMENDATION.value,
                reason_code=RejectionReason.INVALID_RECOMMENDATION,
            )

        symbol = order.symbol
        position = self.get_position(symbol)
        self._last_prices[symbol] = order.reference_price

        if order.side is OrderSide.BUY:
            return self._fill_buy(order, position, stop_loss=stop_loss, target_1=target_1)
        return self._fill_sell(order, position, exit_reason=exit_reason)

    def mark_to_market(self, prices: dict[str, float]) -> AccountSnapshot:
        for symbol, price in prices.items():
            if price > 0:
                self._last_prices[symbol.strip().upper()] = float(price)
        self._refresh_peak_position()
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
        """Compute BUY quantity from cash / config without mutating state.

        Raises ``OrderRejectedError`` when capital cannot buy the minimum lot.
        """
        if reference_price <= 0:
            raise OrderRejectedError(
                RejectionReason.INVALID_RECOMMENDATION.value,
                reason_code=RejectionReason.INVALID_RECOMMENDATION,
            )

        exec_price = execution_price(OrderSide.BUY, reference_price, self._config.slippage_bps)
        mode = self._config.position_sizing

        if mode is PositionSizingMode.FIXED_QUANTITY:
            qty = float(self._config.quantity or 0.0)
        elif mode is PositionSizingMode.FIXED_AMOUNT:
            budget = min(float(self._config.amount or 0.0), self._cash)
            qty = quantity_from_budget(
                budget,
                exec_price,
                self._config.brokerage_rate,
                self._config.brokerage_flat,
            )
        else:
            budget = self._cash * self._config.position_size_pct
            qty = quantity_from_budget(
                budget,
                exec_price,
                self._config.brokerage_rate,
                self._config.brokerage_flat,
            )

        if not self._config.allow_fractional_shares:
            qty = float(int(qty))

        if qty < self._config.min_quantity:
            # Prefer the A5.2.1 one-share message when whole-share floor is 1.
            if (
                not self._config.allow_fractional_shares
                and self._config.min_quantity >= 1.0
            ):
                raise OrderRejectedError(
                    RejectionReason.CAPITAL_INSUFFICIENT_ONE_SHARE.value,
                    reason_code=RejectionReason.CAPITAL_INSUFFICIENT_ONE_SHARE,
                )
            raise OrderRejectedError(
                RejectionReason.BELOW_MIN_QUANTITY.value,
                reason_code=RejectionReason.BELOW_MIN_QUANTITY,
            )
        return qty

    def largest_open_position_notional(self) -> float:
        """Peak position notional observed during the run (includes closed lots)."""
        return self._peak_position_notional

    def _refresh_peak_position(self) -> None:
        for symbol, position in self._positions.items():
            if not position.is_open:
                continue
            price = self._last_prices.get(symbol, position.average_entry_price)
            self._peak_position_notional = max(
                self._peak_position_notional,
                position.quantity * price,
            )

    def _quantity_from_budget(self, budget: float, exec_price: float) -> float:
        return quantity_from_budget(
            budget,
            exec_price,
            self._config.brokerage_rate,
            self._config.brokerage_flat,
        )

    def _fill_buy(
        self,
        order: MarketOrder,
        position: PositionState,
        *,
        stop_loss: float | None,
        target_1: float | None,
    ) -> Fill:
        if position.is_open:
            raise OrderRejectedError(
                RejectionReason.ALREADY_HOLDING.value,
                reason_code=RejectionReason.ALREADY_HOLDING,
            )

        exec_price = execution_price(OrderSide.BUY, order.reference_price, self._config.slippage_bps)
        slippage_per_unit = exec_price - order.reference_price
        notional = exec_price * order.quantity
        brokerage = brokerage_charge(notional, self._config.brokerage_rate, self._config.brokerage_flat)
        total_cost = notional + brokerage
        if total_cost > self._cash + 1e-9:
            raise OrderRejectedError(
                RejectionReason.INSUFFICIENT_CASH.value,
                reason_code=RejectionReason.INSUFFICIENT_CASH,
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
            stop_loss=stop_loss,
            target_1=target_1,
            strategy_name=order.strategy_name,
        )
        self._positions[order.symbol] = opened
        self._refresh_peak_position()

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
        self._log_fill(
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

    def _fill_sell(
        self,
        order: MarketOrder,
        position: PositionState,
        *,
        exit_reason: ExitReason | None,
    ) -> Fill:
        if not position.is_open:
            raise OrderRejectedError(
                RejectionReason.NO_OPEN_POSITION.value,
                reason_code=RejectionReason.NO_OPEN_POSITION,
            )
        if order.quantity > position.quantity + 1e-12:
            raise OrderRejectedError(
                RejectionReason.VALIDATION_FAILURE.value,
                reason_code=RejectionReason.VALIDATION_FAILURE,
            )

        qty = position.quantity
        exec_price = execution_price(OrderSide.SELL, order.reference_price, self._config.slippage_bps)
        slippage_per_unit = order.reference_price - exec_price
        notional = exec_price * qty
        brokerage = brokerage_charge(notional, self._config.brokerage_rate, self._config.brokerage_flat)
        proceeds = notional - brokerage
        slippage_cost = abs(slippage_per_unit) * qty

        gross = (exec_price - position.average_entry_price) * qty
        total_brokerage = position.entry_brokerage + brokerage
        total_slippage = position.entry_slippage_cost + slippage_cost
        realized = gross - total_brokerage - total_slippage

        self._cash += proceeds
        self._realized_pnl += realized
        opened_at = position.opened_at or order.submitted_at
        reason = exit_reason or self._infer_exit_reason(
            position=position,
            exit_price=exec_price,
        )
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
        self._log_fill(
            order=order,
            fill=fill,
            pnl=realized,
            average_entry_price=position.average_entry_price,
            average_exit_price=exec_price,
        )
        holding_days = max(0, (order.submitted_at.date() - opened_at.date()).days)
        self._closed_trades.append(
            ClosedTradeRecord(
                symbol=order.symbol,
                entry_timestamp=opened_at,
                exit_timestamp=order.submitted_at,
                entry_price=position.average_entry_price,
                exit_price=exec_price,
                quantity=qty,
                gross_profit=gross,
                brokerage=total_brokerage,
                slippage=total_slippage,
                net_profit=realized,
                holding_days=holding_days,
                exit_reason=reason,
                strategy_name=position.strategy_name or order.strategy_name,
            ),
        )
        logger.info(
            "FILL SELL %s qty=%.6g px=%.6g pnl=%.4f cash=%.2f reason=%s",
            order.symbol,
            qty,
            exec_price,
            realized,
            self._cash,
            reason.value,
        )
        return fill

    def _infer_exit_reason(
        self,
        *,
        position: PositionState,
        exit_price: float,
    ) -> ExitReason:
        if position.stop_loss is not None and exit_price <= position.stop_loss:
            return ExitReason.STOP_LOSS
        if position.target_1 is not None and exit_price >= position.target_1:
            return ExitReason.TARGET_HIT
        return ExitReason.SELL_RECOMMENDATION

    def _execution_price(self, side: OrderSide, reference: float) -> float:
        return execution_price(side, reference, self._config.slippage_bps)

    def _brokerage(self, notional: float) -> float:
        return brokerage_charge(notional, self._config.brokerage_rate, self._config.brokerage_flat)

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

    def _log_fill(
        self,
        *,
        order: MarketOrder,
        fill: Fill,
        pnl: float,
        average_entry_price: float | None,
        average_exit_price: float | None,
    ) -> None:
        entry = FillLogEntry(
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
        self._fill_log.append(entry)
