"""Order Execution Engine — TradeRecommendation → simulated market fills."""

from __future__ import annotations

from datetime import datetime, timezone

from app.backtesting.order_execution.broker import SimulatedBroker
from app.backtesting.order_execution.exceptions import OrderRejectedError
from app.backtesting.order_execution.orders import MarketOrder, OrderSide, OrderStatus
from app.backtesting.order_execution.schemas import (
    ExecutionAttempt,
    ExecutionConfig,
    ExecutionResult,
)
from app.backtesting.replay_engine.schemas import ReplayResult, ReplayStepResult
from app.core.logging import get_logger
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType

logger = get_logger(__name__)


class OrderExecutionEngine:
    """Convert TradeRecommendations into simulated BUY/SELL market executions.

    Does not implement portfolio analytics — only correct trade execution,
    cash accounting, and a durable trade log.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        *,
        broker: SimulatedBroker | None = None,
    ) -> None:
        self._config = config or ExecutionConfig()
        self._broker = broker or SimulatedBroker(self._config)

    @property
    def config(self) -> ExecutionConfig:
        return self._config

    @property
    def broker(self) -> SimulatedBroker:
        return self._broker

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
            return ExecutionAttempt(
                accepted=False,
                reason=f"No order for signal {recommendation.signal.value}",
                account=account_before,
            )

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
            fill = self._broker.submit_market_order(order)
            filled_order = order.model_copy(update={"status": OrderStatus.FILLED})
            return ExecutionAttempt(
                accepted=True,
                reason="FILLED",
                order=filled_order,
                fill=fill,
                trade_log=self._broker.trade_log[-1],
                account=self._broker.snapshot(),
            )
        except OrderRejectedError as exc:
            logger.info(
                "REJECT %s %s: %s",
                recommendation.signal.value,
                recommendation.symbol,
                exc,
            )
            return ExecutionAttempt(
                accepted=False,
                reason=str(exc),
                order=MarketOrder(
                    symbol=recommendation.symbol,
                    side=side,
                    quantity=1.0,
                    submitted_at=ts,
                    reference_price=price,
                    strategy_name=recommendation.strategy_name,
                    recommendation_trade_id=recommendation.trade_id,
                    status=OrderStatus.REJECTED,
                    reject_reason=str(exc),
                ),
                account=self._broker.snapshot(),
            )

    def process_replay_result(self, replay: ReplayResult) -> ExecutionResult:
        """Run order execution over every replay step recommendation."""
        started = datetime.now(timezone.utc)
        attempts: list[ExecutionAttempt] = []
        filled = 0
        rejected = 0

        for step in replay.steps:
            attempt = self.process_step(step)
            attempts.append(attempt)
            if attempt.accepted:
                filled += 1
            elif not attempt.reason.startswith("No order"):
                rejected += 1
            self._broker.mark_to_market({step.symbol: step.current_close})

        completed = datetime.now(timezone.utc)
        return ExecutionResult(
            config=self._config,
            started_at=started,
            completed_at=completed,
            trade_log=self._broker.trade_log,
            attempts=attempts,
            final_account=self._broker.snapshot(),
            orders_filled=filled,
            orders_rejected=rejected,
        )

    def process_step(self, step: ReplayStepResult) -> ExecutionAttempt:
        return self.process_recommendation(
            step.recommendation,
            market_price=step.current_close,
            timestamp=step.timestamp,
        )

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
                raise OrderRejectedError(f"Cannot SELL {symbol}: no open position")
            return position.quantity

        qty = self._broker.size_buy_quantity(reference_price=reference_price)
        if qty <= 0:
            raise OrderRejectedError(f"Cannot BUY {symbol}: sized quantity is 0")
        return qty


def _signal_to_side(signal: SignalType) -> OrderSide | None:
    if signal is SignalType.BUY:
        return OrderSide.BUY
    if signal in {SignalType.SELL, SignalType.EXIT}:
        return OrderSide.SELL
    return None
