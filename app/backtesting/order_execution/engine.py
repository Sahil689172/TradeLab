"""Order Execution Engine — TradeRecommendation → simulated market fills."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app.backtesting.order_execution.broker import SimulatedBroker
from app.backtesting.order_execution.exceptions import OrderRejectedError
from app.backtesting.order_execution.orders import MarketOrder, OrderSide, OrderStatus
from app.backtesting.order_execution.schemas import (
    ExecutionAttempt,
    ExecutionConfig,
    ExecutionResult,
    ExecutionSummary,
    ExitReason,
    RejectedOrderRecord,
    RejectionReason,
)
from app.backtesting.replay_engine.schemas import ReplayResult, ReplayStepResult
from app.core.logging import get_logger
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType

logger = get_logger(__name__)

DebugCallback = Callable[[str], None]


class OrderExecutionEngine:
    """Convert TradeRecommendations into simulated BUY/SELL market executions.

    Does not implement portfolio analytics — only correct trade execution,
    cash accounting, rejection diagnostics, and trade logs.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        *,
        broker: SimulatedBroker | None = None,
        debug: bool = False,
        debug_callback: DebugCallback | None = None,
    ) -> None:
        if broker is not None:
            self._broker = broker
            self._config = config or broker.config
        else:
            self._config = config or ExecutionConfig()
            self._broker = SimulatedBroker(self._config)
        self._debug = debug
        self._debug_callback = debug_callback or print
        self._rejected_orders: list[RejectedOrderRecord] = []

    @property
    def config(self) -> ExecutionConfig:
        return self._config

    @property
    def broker(self) -> SimulatedBroker:
        return self._broker

    @property
    def rejected_orders(self) -> list[RejectedOrderRecord]:
        return list(self._rejected_orders)

    def process_recommendation(
        self,
        recommendation: TradeRecommendation,
        *,
        market_price: float | None = None,
        timestamp: datetime | None = None,
    ) -> ExecutionAttempt:
        """Process one recommendation against the simulated broker."""
        ts = timestamp or recommendation.timestamp
        price = float(market_price if market_price is not None else recommendation.entry_price)
        account_before = self._broker.snapshot()

        side = _signal_to_side(recommendation.signal)
        if side is None:
            # HOLD (and similar) — not an order attempt / not a rejection.
            return ExecutionAttempt(
                accepted=False,
                reason=f"{RejectionReason.NO_ORDER_FOR_SIGNAL.value} {recommendation.signal.value}",
                reason_code=RejectionReason.NO_ORDER_FOR_SIGNAL,
                account=account_before,
            )

        validation = self._validate_recommendation(
            recommendation,
            side=side,
            ts=ts,
            price=price,
        )
        if validation is not None:
            return validation

        try:
            quantity = self._resolve_quantity(
                side=side,
                symbol=recommendation.symbol,
                reference_price=price,
            )
            order = MarketOrder(
                symbol=recommendation.symbol,
                side=side,
                quantity=quantity,
                submitted_at=ts,
                reference_price=price,
                strategy_name=recommendation.strategy_name,
                recommendation_trade_id=recommendation.trade_id,
            )
            fill = self._broker.submit_market_order(
                order,
                stop_loss=recommendation.stop_loss,
                target_1=recommendation.target_1,
                exit_reason=None,
            )
            filled_order = order.model_copy(update={"status": OrderStatus.FILLED})
            closed = (
                self._broker.closed_trades[-1]
                if side is OrderSide.SELL and self._broker.closed_trades
                else None
            )
            self._debug_fill(
                side=side,
                ts=ts,
                quantity=fill.quantity,
                cash=self._broker.cash,
                profit=fill.realized_pnl if side is OrderSide.SELL else None,
            )
            return ExecutionAttempt(
                accepted=True,
                reason="FILLED",
                order=filled_order,
                fill=fill,
                trade_log=self._broker.fill_log[-1],
                closed_trade=closed,
                account=self._broker.snapshot(),
            )
        except OrderRejectedError as exc:
            return self._reject(
                recommendation=recommendation,
                side=side,
                ts=ts,
                price=price,
                reason=str(exc),
                reason_code=getattr(exc, "reason_code", RejectionReason.VALIDATION_FAILURE),
            )

    def process_replay_result(self, replay: ReplayResult) -> ExecutionResult:
        """Run order execution over every replay step recommendation."""
        started = datetime.now(timezone.utc)
        attempts: list[ExecutionAttempt] = []
        filled = 0
        rejected = 0
        attempted = 0

        for step in replay.steps:
            attempt = self.process_step(step)
            attempts.append(attempt)
            if attempt.reason_code is RejectionReason.NO_ORDER_FOR_SIGNAL:
                pass
            elif attempt.accepted:
                attempted += 1
                filled += 1
            else:
                attempted += 1
                rejected += 1
            self._broker.mark_to_market({step.symbol: step.current_close})

        if self._config.close_open_at_replay_end:
            close_attempts = self._close_open_positions_at_replay_end(replay)
            for attempt in close_attempts:
                attempts.append(attempt)
                attempted += 1
                if attempt.accepted:
                    filled += 1
                else:
                    rejected += 1

        completed = datetime.now(timezone.utc)
        summary = self._build_summary(
            orders_attempted=attempted,
            orders_filled=filled,
            orders_rejected=rejected,
        )
        return ExecutionResult(
            config=self._config,
            started_at=started,
            completed_at=completed,
            trade_log=self._broker.closed_trades,
            fill_log=self._broker.fill_log,
            rejected_orders=self._rejected_orders,
            attempts=attempts,
            final_account=self._broker.snapshot(),
            summary=summary,
            orders_filled=filled,
            orders_rejected=rejected,
        )

    def process_step(self, step: ReplayStepResult) -> ExecutionAttempt:
        return self.process_recommendation(
            step.recommendation,
            market_price=step.current_close,
            timestamp=step.timestamp,
        )

    def _validate_recommendation(
        self,
        recommendation: TradeRecommendation,
        *,
        side: OrderSide,
        ts: datetime,
        price: float,
    ) -> ExecutionAttempt | None:
        if price <= 0 or recommendation.entry_price <= 0:
            return self._reject(
                recommendation=recommendation,
                side=side,
                ts=ts,
                price=price,
                reason=RejectionReason.INVALID_RECOMMENDATION.value,
                reason_code=RejectionReason.INVALID_RECOMMENDATION,
            )

        if self._config.min_confidence is not None:
            if recommendation.confidence < self._config.min_confidence:
                return self._reject(
                    recommendation=recommendation,
                    side=side,
                    ts=ts,
                    price=price,
                    reason=RejectionReason.CONFIDENCE_BELOW_THRESHOLD.value,
                    reason_code=RejectionReason.CONFIDENCE_BELOW_THRESHOLD,
                )

        if self._config.session_start is not None and ts < self._config.session_start:
            return self._reject(
                recommendation=recommendation,
                side=side,
                ts=ts,
                price=price,
                reason=RejectionReason.TRADE_OUTSIDE_REPLAY.value,
                reason_code=RejectionReason.TRADE_OUTSIDE_REPLAY,
            )
        if self._config.session_end is not None and ts > self._config.session_end:
            return self._reject(
                recommendation=recommendation,
                side=side,
                ts=ts,
                price=price,
                reason=RejectionReason.TRADE_OUTSIDE_REPLAY.value,
                reason_code=RejectionReason.TRADE_OUTSIDE_REPLAY,
            )
        return None

    def _resolve_quantity(
        self,
        *,
        side: OrderSide,
        symbol: str,
        reference_price: float,
    ) -> float:
        if side is OrderSide.SELL:
            position = self._broker.get_position(symbol)
            if not position.is_open:
                raise OrderRejectedError(
                    RejectionReason.NO_OPEN_POSITION.value,
                    reason_code=RejectionReason.NO_OPEN_POSITION,
                )
            return position.quantity
        return self._broker.size_buy_quantity(reference_price=reference_price)

    def _close_open_positions_at_replay_end(
        self,
        replay: ReplayResult,
    ) -> list[ExecutionAttempt]:
        attempts: list[ExecutionAttempt] = []
        last_prices: dict[str, float] = {}
        last_ts: dict[str, datetime] = {}
        for step in replay.steps:
            last_prices[step.symbol] = step.current_close
            last_ts[step.symbol] = step.timestamp

        open_symbols = [
            symbol
            for symbol, position in self._broker.snapshot().positions.items()
            if position.is_open
        ]
        for symbol in open_symbols:
            price = last_prices.get(symbol)
            ts = last_ts.get(symbol)
            if price is None or ts is None or price <= 0:
                continue
            position = self._broker.get_position(symbol)
            try:
                order = MarketOrder(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=position.quantity,
                    submitted_at=ts,
                    reference_price=price,
                    strategy_name=position.strategy_name,
                )
                fill = self._broker.submit_market_order(
                    order,
                    exit_reason=ExitReason.REPLAY_END,
                )
                closed = self._broker.closed_trades[-1]
                self._debug_fill(
                    side=OrderSide.SELL,
                    ts=ts,
                    quantity=fill.quantity,
                    cash=self._broker.cash,
                    profit=fill.realized_pnl,
                    note="Replay End",
                )
                attempts.append(
                    ExecutionAttempt(
                        accepted=True,
                        reason="FILLED (Replay End)",
                        order=order.model_copy(update={"status": OrderStatus.FILLED}),
                        fill=fill,
                        trade_log=self._broker.fill_log[-1],
                        closed_trade=closed,
                        account=self._broker.snapshot(),
                    ),
                )
            except OrderRejectedError as exc:
                attempts.append(
                    self._reject_raw(
                        timestamp=ts,
                        symbol=symbol,
                        side=OrderSide.SELL,
                        price=price,
                        reason=str(exc),
                        reason_code=getattr(
                            exc,
                            "reason_code",
                            RejectionReason.VALIDATION_FAILURE,
                        ),
                        strategy_name=position.strategy_name,
                        signal="REPLAY_END",
                        confidence=None,
                    ),
                )
        return attempts

    def _reject(
        self,
        *,
        recommendation: TradeRecommendation,
        side: OrderSide | None,
        ts: datetime,
        price: float,
        reason: str,
        reason_code: RejectionReason,
    ) -> ExecutionAttempt:
        return self._reject_raw(
            timestamp=ts,
            symbol=recommendation.symbol,
            side=side,
            price=price,
            reason=reason,
            reason_code=reason_code,
            strategy_name=recommendation.strategy_name,
            signal=recommendation.signal.value,
            confidence=recommendation.confidence,
        )

    def _reject_raw(
        self,
        *,
        timestamp: datetime,
        symbol: str,
        side: OrderSide | None,
        price: float,
        reason: str,
        reason_code: RejectionReason,
        strategy_name: str,
        signal: str,
        confidence: float | None,
    ) -> ExecutionAttempt:
        rejected = RejectedOrderRecord(
            timestamp=timestamp,
            symbol=symbol.strip().upper(),
            side=side,
            requested_price=price if price > 0 else None,
            reason=reason,
            reason_code=reason_code,
            strategy_name=strategy_name,
            signal=signal,
            confidence=confidence,
        )
        self._rejected_orders.append(rejected)
        logger.info("REJECT %s %s: %s", signal or (side.value if side else "?"), symbol, reason)
        self._debug_reject(ts=timestamp, side=side, reason=reason)

        order = None
        if side is not None and price > 0:
            order = MarketOrder(
                symbol=symbol,
                side=side,
                quantity=1.0,
                submitted_at=timestamp,
                reference_price=price,
                strategy_name=strategy_name,
                status=OrderStatus.REJECTED,
                reject_reason=reason,
            )
        return ExecutionAttempt(
            accepted=False,
            reason=reason,
            reason_code=reason_code,
            order=order,
            rejected=rejected,
            account=self._broker.snapshot(),
        )

    def _build_summary(
        self,
        *,
        orders_attempted: int,
        orders_filled: int,
        orders_rejected: int,
    ) -> ExecutionSummary:
        account = self._broker.snapshot()
        closed = self._broker.closed_trades
        wins = sum(1 for trade in closed if trade.net_profit > 0)
        losses = sum(1 for trade in closed if trade.net_profit < 0)
        profits = [trade.net_profit for trade in closed if trade.net_profit > 0]
        loss_vals = [trade.net_profit for trade in closed if trade.net_profit < 0]
        open_count = sum(1 for pos in account.positions.values() if pos.is_open)
        return ExecutionSummary(
            orders_attempted=orders_attempted,
            orders_filled=orders_filled,
            orders_rejected=orders_rejected,
            win_trades=wins,
            loss_trades=losses,
            open_positions=open_count,
            closed_positions=len(closed),
            current_cash=account.cash,
            current_equity=account.equity,
            largest_position=self._broker.largest_open_position_notional(),
            largest_profit=max(profits) if profits else 0.0,
            largest_loss=min(loss_vals) if loss_vals else 0.0,
        )

    def _debug_fill(
        self,
        *,
        side: OrderSide,
        ts: datetime,
        quantity: float,
        cash: float,
        profit: float | None,
        note: str | None = None,
    ) -> None:
        if not self._debug:
            return
        lines = [
            f"{ts.date()}",
            side.value,
            "Executed" + (f" ({note})" if note else ""),
            f"Qty {quantity:g}",
        ]
        if side is OrderSide.BUY:
            lines.append(f"Cash Left ₹{cash:,.2f}")
        else:
            lines.append(f"Profit ₹{(profit or 0.0):,.2f}")
        lines.append("-" * 19)
        self._debug_callback("\n".join(lines))

    def _debug_reject(
        self,
        *,
        ts: datetime,
        side: OrderSide | None,
        reason: str,
    ) -> None:
        if not self._debug:
            return
        lines = [
            f"{ts.date()}",
            side.value if side else "N/A",
            "Rejected",
            reason,
            "-" * 19,
        ]
        self._debug_callback("\n".join(lines))


def _signal_to_side(signal: SignalType) -> OrderSide | None:
    if signal is SignalType.BUY:
        return OrderSide.BUY
    if signal in {SignalType.SELL, SignalType.EXIT}:
        return OrderSide.SELL
    return None
