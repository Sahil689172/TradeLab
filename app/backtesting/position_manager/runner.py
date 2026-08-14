"""Replay + execution + position tracking orchestrator (A5.1 / A5.2 / A5.3).

Stop-loss exits are requested through ``OrderExecutionEngine`` — this module
does not implement a second broker.
"""

from __future__ import annotations

from datetime import datetime

from app.backtesting.order_execution.engine import OrderExecutionEngine
from app.backtesting.order_execution.schemas import (
    ExecutionAttempt,
    ExecutionResult,
    RejectionReason,
)
from app.backtesting.position_manager.manager import PositionManager
from app.backtesting.position_manager.schemas import (
    EndOfBacktestPolicy,
    PositionEventType,
    PositionExitReason,
    PositionReplayResult,
)
from app.backtesting.replay_engine.schemas import ReplayResult, ReplayStepResult
from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType


class ReplayPositionRunner:
    """Process replay steps: protective checks → execution → position state."""

    def __init__(
        self,
        execution: OrderExecutionEngine,
        positions: PositionManager | None = None,
    ) -> None:
        self._execution = execution
        self._positions = positions or PositionManager()

    @property
    def execution(self) -> OrderExecutionEngine:
        return self._execution

    @property
    def positions(self) -> PositionManager:
        return self._positions

    def process_replay(self, replay: ReplayResult) -> tuple[ExecutionResult, PositionReplayResult]:
        """Run A5.2 fills and A5.3 position tracking over a replay result."""
        started = datetime.now(replay.started_at.tzinfo)
        attempts: list[ExecutionAttempt] = []
        filled = 0
        rejected = 0
        attempted = 0
        last_bar: dict[str, tuple[datetime, float]] = {}

        for step in replay.steps:
            last_bar[step.symbol] = (step.timestamp, step.current_close)
            step_attempts = self.process_step(step)
            for attempt in step_attempts:
                attempts.append(attempt)
                if attempt.reason_code is RejectionReason.NO_ORDER_FOR_SIGNAL:
                    continue
                attempted += 1
                if attempt.accepted:
                    filled += 1
                else:
                    rejected += 1

        eob_attempts = self.apply_end_of_backtest(last_bar)
        for attempt in eob_attempts:
            attempts.append(attempt)
            attempted += 1
            if attempt.accepted:
                filled += 1
            else:
                rejected += 1

        completed = datetime.now(replay.completed_at.tzinfo)
        summary = self._execution._build_summary(
            orders_attempted=attempted,
            orders_filled=filled,
            orders_rejected=rejected,
        )
        exec_result = ExecutionResult(
            config=self._execution.config,
            started_at=started,
            completed_at=completed,
            trade_log=self._execution.broker.closed_trades,
            fill_log=self._execution.broker.fill_log,
            rejected_orders=self._execution.rejected_orders,
            attempts=attempts,
            final_account=self._execution.broker.snapshot(),
            summary=summary,
            orders_filled=filled,
            orders_rejected=rejected,
        )
        pm_result = PositionReplayResult(
            open_positions=self._positions.get_open_positions(),
            closed_positions=self._positions.get_closed_positions(),
            events=self._positions.events,
            end_of_backtest_policy=self._positions.config.end_of_backtest,
            steps_processed=len(replay.steps),
        )
        return exec_result, pm_result

    def process_step(self, step: ReplayStepResult) -> list[ExecutionAttempt]:
        attempts: list[ExecutionAttempt] = []
        open_px, high, low, close = _bar_ohlc(step)

        protective = self._positions.process_bar(
            step.symbol,
            step.timestamp,
            open_price=open_px,
            high=high,
            low=low,
            close=close,
        )
        if any(ev.event_type is PositionEventType.STOP_LOSS_TRIGGERED for ev in protective):
            opened = self._positions.get_position(step.symbol)
            if opened is not None:
                stop_px = self._positions.stop_fill_price(
                    opened,
                    open_price=open_px,
                    low=low,
                ) or opened.stop_loss or close
                rec = synthetic_exit_recommendation(
                    opened.symbol,
                    price=stop_px,
                    timestamp=step.timestamp,
                    strategy_name=opened.strategy_name,
                    stop_loss=opened.stop_loss or stop_px,
                    target_1=opened.target_1 or stop_px,
                    target_2=opened.target_2 or stop_px,
                    confidence=opened.confidence,
                    reason="Position Manager stop-loss trigger",
                )
                attempt = self._execution.process_recommendation(
                    rec,
                    market_price=stop_px,
                    timestamp=step.timestamp,
                )
                self._positions.apply_attempt(
                    attempt,
                    rec,
                    exit_reason=PositionExitReason.STOP_LOSS,
                )
                attempts.append(attempt)

            if step.signal in {SignalType.SELL, SignalType.EXIT}:
                still_open = self._positions.get_position(step.symbol)
                if still_open is None:
                    self._execution.broker.mark_to_market({step.symbol: close})
                    return attempts


        attempt = self._execution.process_recommendation(
            step.recommendation,
            market_price=close,
            timestamp=step.timestamp,
        )
        self._positions.apply_attempt(attempt, step.recommendation)
        attempts.append(attempt)

        still_open = self._positions.get_position(step.symbol)
        self._execution.broker.mark_to_market({step.symbol: close})
        if still_open is not None and (
            still_open.last_updated_timestamp != step.timestamp
            or still_open.current_price != close
        ):
            self._positions.mark_to_market(
                step.symbol,
                current_price=close,
                timestamp=step.timestamp,
            )
        return attempts

    def apply_end_of_backtest(
        self,
        last_bar: dict[str, tuple[datetime, float]],
    ) -> list[ExecutionAttempt]:
        policy = self._positions.config.end_of_backtest
        attempts: list[ExecutionAttempt] = []
        for position in list(self._positions.get_open_positions()):
            ts_price = last_bar.get(position.symbol)
            if ts_price is None:
                continue
            timestamp, price = ts_price
            if policy is EndOfBacktestPolicy.FORCE_CLOSE:
                rec = synthetic_exit_recommendation(
                    position.symbol,
                    price=price,
                    timestamp=timestamp,
                    strategy_name=position.strategy_name,
                    stop_loss=position.stop_loss or price,
                    target_1=position.target_1 or price,
                    target_2=position.target_2 or price,
                    confidence=position.confidence,
                    reason="End of backtest force-close",
                )
                attempt = self._execution.process_recommendation(
                    rec,
                    market_price=price,
                    timestamp=timestamp,
                )
                self._positions.apply_attempt(
                    attempt,
                    rec,
                    exit_reason=PositionExitReason.END_OF_BACKTEST,
                )
                attempts.append(attempt)
            elif policy is EndOfBacktestPolicy.MARK_TO_MARKET:
                self._execution.broker.mark_to_market({position.symbol: price})
                self._positions.apply_end_of_backtest_mark(
                    position.symbol,
                    price=price,
                    timestamp=timestamp,
                )
            else:
                # LEAVE_OPEN — explicit no-close.
                self._positions.apply_end_of_backtest_mark(
                    position.symbol,
                    price=price,
                    timestamp=timestamp,
                )
        return attempts


def synthetic_exit_recommendation(
    symbol: str,
    *,
    price: float,
    timestamp: datetime,
    strategy_name: str,
    stop_loss: float,
    target_1: float,
    target_2: float,
    confidence: float,
    reason: str,
) -> TradeRecommendation:
    """EXIT recommendation used to request a SELL through A5.2 (not a new signal)."""
    sl = stop_loss if stop_loss > 0 else max(price * 0.99, 1e-9)
    t1 = target_1 if target_1 > 0 else price
    t2 = target_2 if target_2 > 0 else price
    return TradeRecommendation(
        strategy_name=strategy_name or "position_manager",
        symbol=symbol,
        timeframe="1 Day",
        timestamp=timestamp,
        signal=SignalType.EXIT,
        entry_price=price,
        stop_loss=sl,
        target_1=t1 if t1 > 0 else price,
        target_2=t2 if t2 > 0 else price,
        risk_reward=0.0,
        confidence=min(max(confidence, 0.0), 100.0),
        expected_holding_period=0,
        reasons=[reason],
        trend_direction=TrendDirection.SIDEWAYS,
        market_structure=TrendDirection.SIDEWAYS,
    )


def _bar_ohlc(step: ReplayStepResult) -> tuple[float, float, float, float]:
    close = float(step.current_close)
    open_px = float(step.current_open) if step.current_open else close
    high = float(step.current_high) if step.current_high else close
    low = float(step.current_low) if step.current_low else close
    return open_px, high, low, close
