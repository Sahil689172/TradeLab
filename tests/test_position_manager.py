"""Phase A5.3 Position Manager — lifecycle, invariants, replay integration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.backtesting.order_execution import (
    ExecutionConfig,
    OrderExecutionEngine,
    OrderSide,
    PositionSizingMode,
    RejectionReason,
    SimulatedBroker,
)
from app.backtesting.order_execution.orders import Fill, OrderStatus
from app.backtesting.position_manager import (
    EndOfBacktestPolicy,
    Position,
    PositionEventType,
    PositionExitReason,
    PositionInvariantError,
    PositionLookAheadError,
    PositionManager,
    PositionManagerConfig,
    PositionRejectReason,
    PositionStatus,
    ReplayPositionRunner,
)
from app.backtesting.replay_engine.schemas import (
    ReplayConfig,
    ReplayResult,
    ReplaySpeed,
    ReplayStepResult,
)
from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType

TS0 = datetime(2022, 6, 1, tzinfo=timezone.utc)
TS1 = datetime(2022, 6, 2, tzinfo=timezone.utc)
TS2 = datetime(2022, 6, 10, tzinfo=timezone.utc)
TS3 = datetime(2022, 6, 20, tzinfo=timezone.utc)


def _rec(
    *,
    signal: SignalType,
    symbol: str = "RELIANCE",
    price: float = 100.0,
    ts: datetime | None = None,
    stop_loss: float | None = None,
    target_1: float | None = None,
    target_2: float | None = None,
    confidence: float = 60.0,
) -> TradeRecommendation:
    return TradeRecommendation(
        strategy_name="ema_trend",
        symbol=symbol,
        timeframe="1 Day",
        timestamp=ts or TS0,
        signal=signal,
        entry_price=price,
        stop_loss=stop_loss if stop_loss is not None else price * 0.95,
        target_1=target_1 if target_1 is not None else price * 1.05,
        target_2=target_2 if target_2 is not None else price * 1.10,
        risk_reward=1.0,
        confidence=confidence,
        expected_holding_period=10,
        reasons=["unit test"],
        trend_direction=TrendDirection.SIDEWAYS,
        market_structure=TrendDirection.SIDEWAYS,
    )


def _cfg(*, capital: float = 100_000.0, quantity: float = 10.0) -> ExecutionConfig:
    return ExecutionConfig(
        initial_capital=capital,
        position_sizing=PositionSizingMode.FIXED_QUANTITY,
        quantity=quantity,
        slippage_bps=0.0,
        brokerage_rate=0.0,
        allow_fractional_shares=False,
        close_open_at_replay_end=False,
    )


def _fill(
    *,
    side: OrderSide,
    quantity: float = 10.0,
    price: float = 1200.0,
    ts: datetime | None = None,
    symbol: str = "RELIANCE",
    order_id: str = "ord-1",
    realized_pnl: float = 0.0,
) -> Fill:
    return Fill(
        order_id=order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        reference_price=price,
        execution_price=price,
        slippage_per_unit=0.0,
        slippage_cost=0.0,
        brokerage=0.0,
        filled_at=ts or TS0,
        cash_delta=(-price * quantity) if side is OrderSide.BUY else (price * quantity),
        realized_pnl=realized_pnl,
    )


def _step(
    rec: TradeRecommendation,
    *,
    close: float,
    replay_index: int,
    high: float | None = None,
    low: float | None = None,
    open_px: float | None = None,
) -> ReplayStepResult:
    return ReplayStepResult(
        timestamp=rec.timestamp,
        symbol=rec.symbol,
        strategy_name=rec.strategy_name,
        current_close=close,
        current_open=open_px if open_px is not None else close,
        current_high=high if high is not None else close,
        current_low=low if low is not None else close,
        replay_index=replay_index,
        signal=rec.signal,
        confidence=rec.confidence,
        stop_loss=rec.stop_loss,
        target_1=rec.target_1,
        target_2=rec.target_2,
        expected_holding_period=rec.expected_holding_period,
        recommendation=rec,
    )


def _replay(steps: list[ReplayStepResult], symbols: list[str] | None = None) -> ReplayResult:
    return ReplayResult(
        config=ReplayConfig(
            symbols=symbols or sorted({s.symbol for s in steps}),
            strategy_names=["ema_trend"],
            speed=ReplaySpeed.FAST,
        ),
        started_at=steps[0].timestamp,
        completed_at=steps[-1].timestamp,
        steps=steps,
        candles_replayed=len(steps),
        recommendations_generated=len(steps),
        symbols=symbols or sorted({s.symbol for s in steps}),
    )


def _snapshot(positions: list[Position]) -> list[dict[str, object]]:
    rows = []
    for pos in positions:
        rows.append(
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "exit_price": pos.exit_price,
                "status": pos.status.value,
                "realized_pnl": pos.realized_pnl,
                "unrealized_pnl": pos.unrealized_pnl,
                "exit_reason": pos.exit_reason.value if pos.exit_reason else None,
                "target_1_hit": pos.target_1_hit,
                "target_2_hit": pos.target_2_hit,
                "holding_period": pos.holding_period,
            },
        )
    return rows


def test_buy_fill_opens_position() -> None:
    pm = PositionManager()
    rec = _rec(signal=SignalType.BUY, price=1200.0)
    result = pm.apply_fill(_fill(side=OrderSide.BUY, quantity=10.0, price=1200.0), recommendation=rec)
    assert result.accepted
    assert result.event_type is PositionEventType.POSITION_OPENED
    pos = pm.get_position("RELIANCE")
    assert pos is not None
    assert pos.status is PositionStatus.OPEN
    assert pos.quantity == pytest.approx(10.0)
    assert pos.entry_price == pytest.approx(1200.0)
    assert pos.strategy_name == "ema_trend"


def test_buy_rejection_does_not_open_position() -> None:
    broker = SimulatedBroker(_cfg(capital=100.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)
    pm = PositionManager()
    rec = _rec(signal=SignalType.BUY, price=50.0)
    attempt = engine.process_recommendation(rec)
    assert not attempt.accepted
    result = pm.apply_attempt(attempt, rec)
    assert not result.accepted
    assert pm.get_position("RELIANCE") is None
    assert pm.get_open_positions() == []
    assert pm.get_closed_positions() == []


def test_sell_without_position_rejected() -> None:
    pm = PositionManager()
    result = pm.apply_fill(_fill(side=OrderSide.SELL, price=100.0, ts=TS1))
    assert not result.accepted
    assert result.reject_reason is PositionRejectReason.NO_OPEN_POSITION
    broker = SimulatedBroker(_cfg())
    cash_before = broker.cash
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.SELL, price=100.0))
    assert attempt.reason_code is RejectionReason.NO_OPEN_POSITION
    assert broker.cash == pytest.approx(cash_before)
    pm.apply_attempt(attempt, _rec(signal=SignalType.SELL, price=100.0))
    assert pm.get_open_positions() == []


def test_position_quantity_and_immutable_entry_price() -> None:
    pm = PositionManager()
    pm.apply_fill(
        _fill(side=OrderSide.BUY, quantity=7.0, price=1200.0),
        recommendation=_rec(signal=SignalType.BUY, price=1200.0),
    )
    entry = pm.get_position("RELIANCE").entry_price  # type: ignore[union-attr]
    pm.mark_to_market("RELIANCE", current_price=1300.0, timestamp=TS1)
    pos = pm.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == pytest.approx(7.0)
    assert pos.entry_price == pytest.approx(entry)
    assert pos.current_price == pytest.approx(1300.0)


def test_current_price_and_unrealized_pnl() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=1200.0,
        entry_timestamp=TS0,
        stop_loss=1140.0,
        target_1=1260.0,
        target_2=1320.0,
        entry_order_id="e1",
    )
    pm.mark_to_market("RELIANCE", current_price=1210.0, timestamp=TS1)
    pos = pm.get_position("RELIANCE")
    assert pos is not None
    assert pos.unrealized_pnl == pytest.approx((1210.0 - 1200.0) * 10.0)


def test_stop_loss_detection() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=100.0,
        entry_timestamp=TS0,
        stop_loss=95.0,
        target_1=110.0,
        target_2=120.0,
        entry_order_id="e1",
    )
    events = pm.process_bar(
        "RELIANCE",
        TS1,
        open_price=99.0,
        high=100.0,
        low=94.0,
        close=96.0,
    )
    assert any(e.event_type is PositionEventType.STOP_LOSS_TRIGGERED for e in events)
    assert pm.get_position("RELIANCE") is not None
    assert pm.get_position("RELIANCE").stop_loss_hit  # type: ignore[union-attr]


def test_target_1_and_target_2_detection_does_not_close() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=100.0,
        entry_timestamp=TS0,
        stop_loss=90.0,
        target_1=105.0,
        target_2=112.0,
        entry_order_id="e1",
    )
    events = pm.process_bar(
        "RELIANCE",
        TS1,
        open_price=101.0,
        high=106.0,
        low=100.0,
        close=104.0,
    )
    assert any(e.event_type is PositionEventType.TARGET_1_HIT for e in events)
    pos = pm.get_position("RELIANCE")
    assert pos is not None
    assert pos.target_1_hit
    assert pos.target_1_hit_timestamp == TS1
    assert pos.status is PositionStatus.OPEN

    events = pm.process_bar(
        "RELIANCE",
        TS2,
        open_price=106.0,
        high=113.0,
        low=105.0,
        close=111.0,
    )
    assert any(e.event_type is PositionEventType.TARGET_2_HIT for e in events)
    pos = pm.get_position("RELIANCE")
    assert pos is not None
    assert pos.target_2_hit
    assert pos.status is PositionStatus.OPEN
    assert pos.quantity == pytest.approx(10.0)


def test_strategy_exit_and_sell_close_position() -> None:
    engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg()))
    pm = PositionManager()
    buy = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0, ts=TS0))
    pm.apply_attempt(buy, _rec(signal=SignalType.BUY, price=100.0, ts=TS0))
    exit_rec = _rec(signal=SignalType.EXIT, price=108.0, ts=TS2)
    closed = engine.process_recommendation(exit_rec)
    result = pm.apply_attempt(closed, exit_rec)
    assert result.accepted
    assert result.position is not None
    assert result.position.status is PositionStatus.CLOSED
    assert result.position.exit_reason is PositionExitReason.STRATEGY_EXIT
    assert result.position.realized_pnl == pytest.approx(80.0)
    assert pm.get_open_positions() == []
    assert len(pm.get_closed_positions()) == 1

    engine2 = OrderExecutionEngine(broker=SimulatedBroker(_cfg()))
    pm2 = PositionManager()
    pm2.apply_attempt(
        engine2.process_recommendation(_rec(signal=SignalType.BUY, price=100.0, ts=TS0)),
        _rec(signal=SignalType.BUY, price=100.0, ts=TS0),
    )
    sell_rec = _rec(signal=SignalType.SELL, price=90.0, ts=TS2, stop_loss=85.0, target_1=80.0, target_2=70.0)
    sell = engine2.process_recommendation(sell_rec)
    result2 = pm2.apply_attempt(sell, sell_rec)
    assert result2.position is not None
    assert result2.position.exit_reason is PositionExitReason.STRATEGY_SELL
    assert result2.position.realized_pnl == pytest.approx(-100.0)


def test_holding_period_and_exit_reason_recorded() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=100.0,
        entry_timestamp=TS0,
        stop_loss=90.0,
        target_1=110.0,
        target_2=120.0,
        entry_order_id="e1",
    )
    closed = pm.close_position(
        "RELIANCE",
        exit_price=105.0,
        exit_timestamp=TS3,
        exit_reason=PositionExitReason.MANUAL,
        exit_order_id="x1",
    )
    pos = closed.position
    assert pos is not None
    assert pos.holding_period == TS3 - TS0
    assert pos.holding_period_days == 19
    assert pos.exit_reason is PositionExitReason.MANUAL
    assert pos.exit_timestamp == TS3


def test_closed_position_remains_in_history() -> None:
    pm = PositionManager()
    pm.apply_fill(
        _fill(side=OrderSide.BUY, quantity=10.0, price=100.0, ts=TS0),
        recommendation=_rec(signal=SignalType.BUY, price=100.0, ts=TS0),
    )
    pm.apply_fill(
        _fill(side=OrderSide.SELL, quantity=10.0, price=110.0, ts=TS2, order_id="ord-2", realized_pnl=100.0),
        recommendation=_rec(signal=SignalType.EXIT, price=110.0, ts=TS2),
        signal=SignalType.EXIT,
    )
    assert pm.get_position("RELIANCE") is None
    history = pm.get_closed_positions()
    assert len(history) == 1
    assert history[0].status is PositionStatus.CLOSED
    assert history[0].entry_price == pytest.approx(100.0)


def test_multiple_symbols_are_isolated() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=100.0,
        entry_timestamp=TS0,
        stop_loss=90.0,
        target_1=110.0,
        target_2=120.0,
        entry_order_id="r1",
    )
    pm.open_position(
        symbol="TCS",
        quantity=5.0,
        entry_price=200.0,
        entry_timestamp=TS0,
        stop_loss=180.0,
        target_1=220.0,
        target_2=240.0,
        entry_order_id="t1",
    )
    pm.mark_to_market("RELIANCE", current_price=105.0, timestamp=TS1)
    pm.close_position(
        "TCS",
        exit_price=210.0,
        exit_timestamp=TS1,
        exit_reason=PositionExitReason.STRATEGY_SELL,
    )
    rel = pm.get_position("RELIANCE")
    assert rel is not None
    assert rel.status is PositionStatus.OPEN
    assert rel.unrealized_pnl == pytest.approx(50.0)
    assert pm.get_position("TCS") is None
    assert pm.get_closed_positions()[0].symbol == "TCS"
    assert rel.entry_price == pytest.approx(100.0)


def test_duplicate_buy_protection() -> None:
    pm = PositionManager()
    rec = _rec(signal=SignalType.BUY, price=100.0)
    first = pm.apply_fill(_fill(side=OrderSide.BUY, price=100.0), recommendation=rec)
    second = pm.apply_fill(
        _fill(side=OrderSide.BUY, price=101.0, order_id="ord-2"),
        recommendation=_rec(signal=SignalType.BUY, price=101.0),
    )
    assert first.accepted
    assert not second.accepted
    assert second.reject_reason is PositionRejectReason.ALREADY_POSITIONED
    assert pm.get_position("RELIANCE") is not None
    assert pm.get_position("RELIANCE").quantity == pytest.approx(10.0)  # type: ignore[union-attr]


def test_end_of_backtest_policies() -> None:
    def _open_run(policy: EndOfBacktestPolicy) -> tuple[OrderExecutionEngine, PositionManager, ReplayPositionRunner]:
        engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg(quantity=10.0)))
        pm = PositionManager(PositionManagerConfig(end_of_backtest=policy))
        runner = ReplayPositionRunner(engine, pm)
        steps = [
            _step(_rec(signal=SignalType.BUY, price=100.0, ts=TS0), close=100.0, replay_index=0),
            _step(_rec(signal=SignalType.HOLD, price=101.0, ts=TS1), close=101.0, replay_index=1),
        ]
        runner.process_replay(_replay(steps))
        return engine, pm, runner

    _, pm_close, _ = _open_run(EndOfBacktestPolicy.FORCE_CLOSE)
    assert pm_close.get_open_positions() == []
    assert pm_close.get_closed_positions()[0].exit_reason is PositionExitReason.END_OF_BACKTEST

    _, pm_mtm, _ = _open_run(EndOfBacktestPolicy.MARK_TO_MARKET)
    opened = pm_mtm.get_open_positions()
    assert len(opened) == 1
    assert opened[0].current_price == pytest.approx(101.0)
    assert opened[0].unrealized_pnl == pytest.approx(10.0)

    _, pm_leave, _ = _open_run(EndOfBacktestPolicy.LEAVE_OPEN)
    assert len(pm_leave.get_open_positions()) == 1
    assert pm_leave.get_closed_positions() == []


def test_stop_loss_closes_through_execution() -> None:
    engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg(quantity=10.0)))
    pm = PositionManager()
    runner = ReplayPositionRunner(engine, pm)
    steps = [
        _step(
            _rec(signal=SignalType.BUY, price=100.0, ts=TS0, stop_loss=95.0, target_1=110.0, target_2=120.0),
            close=100.0,
            replay_index=0,
            high=101.0,
            low=99.0,
        ),
        _step(
            _rec(signal=SignalType.HOLD, price=96.0, ts=TS1, stop_loss=95.0, target_1=110.0, target_2=120.0),
            close=96.0,
            replay_index=1,
            high=98.0,
            low=94.0,
            open_px=97.0,
        ),
    ]
    exec_result, pos_result = runner.process_replay(_replay(steps))
    assert pos_result.closed_positions[0].exit_reason is PositionExitReason.STOP_LOSS
    assert exec_result.trade_log[0].net_profit == pytest.approx(-50.0)
    assert pm.get_open_positions() == []


def test_no_lookahead_same_bar_low_ignored_and_future_bar_not_used() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=100.0,
        entry_timestamp=TS0,
        stop_loss=95.0,
        target_1=110.0,
        target_2=120.0,
        entry_order_id="e1",
    )
    # Entry bar low 90 already happened before the close entry — must not trigger.
    events = pm.process_bar(
        "RELIANCE",
        TS0,
        open_price=100.0,
        high=101.0,
        low=90.0,
        close=100.0,
    )
    assert not any(e.event_type is PositionEventType.STOP_LOSS_TRIGGERED for e in events)
    assert pm.get_position("RELIANCE") is not None

    # Only TS1 is supplied; a hypothetical TS2 low of 80 must not affect TS1.
    events = pm.process_bar(
        "RELIANCE",
        TS1,
        open_price=99.0,
        high=100.0,
        low=96.0,
        close=97.0,
    )
    assert not any(e.event_type is PositionEventType.STOP_LOSS_TRIGGERED for e in events)

    with pytest.raises(PositionLookAheadError):
        pm.process_bar(
            "RELIANCE",
            TS0,
            open_price=100.0,
            high=101.0,
            low=80.0,
            close=100.0,
        )


def test_deterministic_replay_position_history() -> None:
    def run() -> list[dict[str, object]]:
        engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg(quantity=10.0)))
        pm = PositionManager()
        runner = ReplayPositionRunner(engine, pm)
        steps = [
            _step(_rec(signal=SignalType.BUY, price=100.0, ts=TS0), close=100.0, replay_index=0),
            _step(_rec(signal=SignalType.HOLD, price=103.0, ts=TS1), close=103.0, replay_index=1, high=106.0, low=102.0),
            _step(_rec(signal=SignalType.EXIT, price=108.0, ts=TS2), close=108.0, replay_index=2),
        ]
        _, pos = runner.process_replay(_replay(steps))
        return _snapshot(pos.closed_positions)

    assert run() == run()


def test_small_capital_rupees() -> None:
    engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg(capital=1_000.0, quantity=1.0)))
    pm = PositionManager()
    runner = ReplayPositionRunner(engine, pm)
    steps = [
        _step(_rec(signal=SignalType.BUY, price=100.0, ts=TS0), close=100.0, replay_index=0),
        _step(_rec(signal=SignalType.EXIT, price=110.0, ts=TS1), close=110.0, replay_index=1),
    ]
    exec_result, pos_result = runner.process_replay(_replay(steps))
    assert pos_result.closed_positions[0].quantity == pytest.approx(1.0)
    assert pos_result.closed_positions[0].realized_pnl == pytest.approx(10.0)
    assert exec_result.final_account.cash == pytest.approx(1_010.0)

    engine2 = OrderExecutionEngine(broker=SimulatedBroker(_cfg(capital=10_000.0, quantity=10.0)))
    pm2 = PositionManager()
    runner2 = ReplayPositionRunner(engine2, pm2)
    exec2, pos2 = runner2.process_replay(_replay(steps))
    assert pos2.closed_positions[0].quantity == pytest.approx(10.0)
    assert exec2.final_account.cash == pytest.approx(10_100.0)


def test_a52_process_replay_result_unchanged_without_position_manager() -> None:
    engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg()))
    buy = _rec(signal=SignalType.BUY, price=100.0, ts=TS0)
    hold = _rec(signal=SignalType.HOLD, price=101.0, ts=TS1)
    sell = _rec(signal=SignalType.SELL, price=110.0, ts=TS2)
    steps = [
        _step(buy, close=100.0, replay_index=0),
        _step(hold, close=101.0, replay_index=1),
        _step(sell, close=110.0, replay_index=2),
    ]
    result = engine.process_replay_result(_replay(steps))
    assert result.summary.closed_positions == 1
    assert result.summary.open_positions == 0
    assert result.final_account.cash == pytest.approx(100_100.0)


def test_invariants_fail_loudly() -> None:
    with pytest.raises((PositionInvariantError, ValidationError)):
        Position(
            symbol="RELIANCE",
            quantity=10.0,
            entry_price=100.0,
            current_price=100.0,
            entry_timestamp=TS0,
            last_updated_timestamp=TS0,
            status=PositionStatus.CLOSED,
        )
    with pytest.raises((PositionInvariantError, ValidationError)):
        Position(
            symbol="RELIANCE",
            quantity=10.0,
            entry_price=100.0,
            current_price=100.0,
            entry_timestamp=TS0,
            last_updated_timestamp=TS0,
            status=PositionStatus.OPEN,
            exit_price=110.0,
            stop_loss=90.0,
            target_1=110.0,
            target_2=120.0,
        )
    with pytest.raises((PositionInvariantError, ValidationError)):
        Position(
            symbol="RELIANCE",
            quantity=0.0,
            entry_price=100.0,
            current_price=100.0,
            entry_timestamp=TS0,
            last_updated_timestamp=TS0,
        )
    with pytest.raises((PositionInvariantError, ValidationError)):
        Position(
            symbol="RELIANCE",
            quantity=10.0,
            entry_price=100.0,
            current_price=100.0,
            entry_timestamp=TS0,
            last_updated_timestamp=TS0,
            stop_loss=101.0,
            target_1=110.0,
            target_2=120.0,
        )
    with pytest.raises((PositionInvariantError, ValidationError)):
        Position(
            symbol="RELIANCE",
            quantity=10.0,
            entry_price=100.0,
            current_price=100.0,
            entry_timestamp=TS0,
            last_updated_timestamp=TS0,
            stop_loss=90.0,
            target_1=110.0,
            target_2=109.0,
        )

    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=100.0,
        entry_timestamp=TS0,
        stop_loss=90.0,
        target_1=110.0,
        target_2=120.0,
        entry_order_id="e1",
    )
    pm.close_position(
        "RELIANCE",
        exit_price=105.0,
        exit_timestamp=TS1,
        exit_reason=PositionExitReason.MANUAL,
    )
    with pytest.raises(PositionInvariantError):
        pm.mark_to_market("RELIANCE", current_price=106.0, timestamp=TS2)


def test_sell_cannot_reduce_quantity_below_zero() -> None:
    pm = PositionManager()
    pm.apply_fill(
        _fill(side=OrderSide.BUY, quantity=5.0, price=100.0),
        recommendation=_rec(signal=SignalType.BUY, price=100.0),
    )
    result = pm.apply_fill(
        _fill(side=OrderSide.SELL, quantity=50.0, price=110.0, ts=TS1, order_id="s1", realized_pnl=50.0),
        recommendation=_rec(signal=SignalType.SELL, price=110.0, ts=TS1),
        signal=SignalType.SELL,
    )
    assert result.accepted
    assert result.position is not None
    assert result.position.quantity == pytest.approx(5.0)
    assert result.position.status is PositionStatus.CLOSED
    assert pm.get_open_positions() == []


def test_partial_sell_extension_point() -> None:
    pm = PositionManager()
    pm.apply_fill(
        _fill(side=OrderSide.BUY, quantity=10.0, price=100.0),
        recommendation=_rec(signal=SignalType.BUY, price=100.0),
    )
    result = pm.apply_fill(
        _fill(side=OrderSide.SELL, quantity=4.0, price=110.0, ts=TS1, order_id="s1", realized_pnl=40.0),
        recommendation=_rec(signal=SignalType.SELL, price=110.0, ts=TS1),
        signal=SignalType.SELL,
    )
    assert result.message == "PARTIALLY_CLOSED"
    pos = pm.get_position("RELIANCE")
    assert pos is not None
    assert pos.status is PositionStatus.PARTIALLY_CLOSED
    assert pos.quantity == pytest.approx(6.0)


def test_reset_clears_state() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=100.0,
        entry_timestamp=TS0,
        stop_loss=90.0,
        target_1=110.0,
        target_2=120.0,
        entry_order_id="e1",
    )
    pm.reset()
    assert pm.get_open_positions() == []
    assert pm.get_closed_positions() == []
    assert pm.events == []


def test_replay_step_without_ohlc_still_constructs() -> None:
    rec = _rec(signal=SignalType.HOLD, price=100.0)
    step = ReplayStepResult(
        timestamp=rec.timestamp,
        symbol=rec.symbol,
        strategy_name=rec.strategy_name,
        current_close=100.0,
        replay_index=0,
        signal=rec.signal,
        confidence=rec.confidence,
        stop_loss=rec.stop_loss,
        target_1=rec.target_1,
        target_2=rec.target_2,
        expected_holding_period=rec.expected_holding_period,
        recommendation=rec,
    )
    assert step.current_high is None
    assert step.current_low is None


def test_runner_multi_symbol_isolation() -> None:
    engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg(quantity=10.0)))
    pm = PositionManager(
        PositionManagerConfig(end_of_backtest=EndOfBacktestPolicy.MARK_TO_MARKET),
    )
    runner = ReplayPositionRunner(engine, pm)
    steps = [
        _step(_rec(signal=SignalType.BUY, symbol="RELIANCE", price=100.0, ts=TS0), close=100.0, replay_index=0),
        _step(_rec(signal=SignalType.BUY, symbol="TCS", price=200.0, ts=TS0), close=200.0, replay_index=0),
        _step(
            _rec(signal=SignalType.HOLD, symbol="RELIANCE", price=105.0, ts=TS1),
            close=105.0,
            replay_index=1,
        ),
        _step(
            _rec(signal=SignalType.EXIT, symbol="TCS", price=210.0, ts=TS1),
            close=210.0,
            replay_index=1,
        ),
    ]
    _, pos = runner.process_replay(_replay(steps, symbols=["RELIANCE", "TCS"]))
    rel = next(p for p in pos.open_positions if p.symbol == "RELIANCE")
    tcs = next(p for p in pos.closed_positions if p.symbol == "TCS")
    assert rel.quantity == pytest.approx(10.0)
    assert rel.unrealized_pnl == pytest.approx(50.0)
    assert tcs.realized_pnl == pytest.approx(100.0)
    assert tcs.exit_reason is PositionExitReason.STRATEGY_EXIT


def test_gross_realized_matches_spec_formula() -> None:
    pm = PositionManager()
    pm.open_position(
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=1200.0,
        entry_timestamp=TS0,
        stop_loss=1140.0,
        target_1=1260.0,
        target_2=1320.0,
        entry_order_id="e1",
    )
    closed = pm.close_position(
        "RELIANCE",
        exit_price=1250.0,
        exit_timestamp=TS2,
        exit_reason=PositionExitReason.STRATEGY_EXIT,
    )
    assert closed.position is not None
    assert closed.position.gross_realized_pnl == pytest.approx((1250.0 - 1200.0) * 10.0)
    assert closed.position.realized_pnl == pytest.approx(500.0)
    assert closed.position.unrealized_pnl == pytest.approx(0.0)


def test_full_lifecycle_buy_filled_open_mtm_exit_filled_closed() -> None:
    """Deterministic A5.3 guarantee: BUY FILLED → OPEN → MTM → EXIT FILLED → CLOSED.

    Does not call the Strategy Engine. Recommendations are a fixed fixture so the
    path cannot depend on RELIANCE parquet emitting a BUY.
    """
    engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg(capital=10_000.0, quantity=10.0)))
    pm = PositionManager(
        PositionManagerConfig(end_of_backtest=EndOfBacktestPolicy.LEAVE_OPEN),
    )
    runner = ReplayPositionRunner(engine, pm)

    buy_rec = _rec(
        signal=SignalType.BUY,
        price=100.0,
        ts=TS0,
        stop_loss=90.0,
        target_1=110.0,
        target_2=120.0,
    )
    buy_attempts = runner.process_step(_step(buy_rec, close=100.0, replay_index=0))
    buy_attempt = next(a for a in buy_attempts if a.accepted)
    assert buy_attempt.order is not None
    assert buy_attempt.order.side is OrderSide.BUY
    assert buy_attempt.order.status is OrderStatus.FILLED
    assert buy_attempt.fill is not None
    assert buy_attempt.fill.side is OrderSide.BUY
    assert buy_attempt.fill.quantity == pytest.approx(10.0)
    assert buy_attempt.fill.execution_price == pytest.approx(100.0)
    opened = pm.get_position("RELIANCE")
    assert opened is not None
    assert opened.status is PositionStatus.OPEN
    assert opened.quantity == pytest.approx(10.0)
    assert opened.entry_price == pytest.approx(100.0)
    assert any(e.event_type is PositionEventType.POSITION_OPENED for e in pm.events)

    hold_rec = _rec(
        signal=SignalType.HOLD,
        price=103.0,
        ts=TS1,
        stop_loss=90.0,
        target_1=110.0,
        target_2=120.0,
    )
    runner.process_step(
        _step(hold_rec, close=103.0, replay_index=1, high=104.0, low=102.0, open_px=102.5),
    )
    marked = pm.get_position("RELIANCE")
    assert marked is not None
    assert marked.status is PositionStatus.OPEN
    assert marked.entry_price == pytest.approx(100.0)
    assert marked.current_price == pytest.approx(103.0)
    assert marked.unrealized_pnl == pytest.approx(30.0)
    assert marked.realized_pnl == pytest.approx(0.0)
    assert any(e.event_type is PositionEventType.POSITION_UPDATED for e in pm.events)

    exit_rec = _rec(
        signal=SignalType.EXIT,
        price=108.0,
        ts=TS2,
        stop_loss=90.0,
        target_1=110.0,
        target_2=120.0,
    )
    exit_attempts = runner.process_step(_step(exit_rec, close=108.0, replay_index=2))
    exit_attempt = next(a for a in exit_attempts if a.accepted)
    assert exit_attempt.order is not None
    assert exit_attempt.order.side is OrderSide.SELL
    assert exit_attempt.order.status is OrderStatus.FILLED
    assert exit_attempt.fill is not None
    assert exit_attempt.fill.side is OrderSide.SELL

    assert pm.get_open_positions() == []
    closed = pm.get_closed_positions()
    assert len(closed) == 1
    pos = closed[0]
    assert pos.status is PositionStatus.CLOSED
    assert pos.quantity == pytest.approx(10.0)
    assert pos.entry_price == pytest.approx(100.0)
    assert pos.exit_price == pytest.approx(108.0)
    assert pos.realized_pnl == pytest.approx(80.0)
    assert pos.unrealized_pnl == pytest.approx(0.0)
    assert pos.exit_reason is PositionExitReason.STRATEGY_EXIT
    assert any(e.event_type is PositionEventType.POSITION_CLOSED for e in pm.events)

    fills = engine.broker.fill_log
    assert len(fills) == 2
    assert fills[0].side is OrderSide.BUY
    assert fills[1].side is OrderSide.SELL
    assert engine.broker.cash == pytest.approx(10_080.0)

    opened_count = sum(
        1 for e in pm.events if e.event_type is PositionEventType.POSITION_OPENED
    )
    closed_count = sum(
        1 for e in pm.events if e.event_type is PositionEventType.POSITION_CLOSED
    )
    print()
    print("A5.3 LIFECYCLE REPORT")
    print(f"orders attempted: {len(fills)}")
    print(f"orders filled:     {len(fills)}")
    print(f"positions opened:  {opened_count}")
    print(f"positions closed:  {closed_count}")
    print(f"entry price:       {pos.entry_price}")
    print(f"exit price:        {pos.exit_price}")
    print(f"quantity:          {pos.quantity:g}")
    print(f"realized P&L:      {pos.realized_pnl}")
    print(f"unrealized P&L:    {pos.unrealized_pnl}")
    print(f"exit reason:       {pos.exit_reason.value if pos.exit_reason else None}")


def test_lifecycle_negative_rejected_buy_naked_sell_duplicate_buy() -> None:
    """Rejected BUY / SELL-with-no-lot / duplicate BUY must not open extra positions."""
    engine = OrderExecutionEngine(broker=SimulatedBroker(_cfg(capital=100.0, quantity=10.0)))
    pm = PositionManager()
    runner = ReplayPositionRunner(engine, pm)

    rejected_buy = runner.process_step(
        _step(_rec(signal=SignalType.BUY, price=50.0, ts=TS0), close=50.0, replay_index=0),
    )
    buy_attempt = rejected_buy[-1]
    assert not buy_attempt.accepted
    assert buy_attempt.reason_code is RejectionReason.INSUFFICIENT_CASH
    assert pm.get_open_positions() == []
    assert pm.get_closed_positions() == []

    engine2 = OrderExecutionEngine(broker=SimulatedBroker(_cfg(capital=10_000.0, quantity=10.0)))
    pm2 = PositionManager()
    runner2 = ReplayPositionRunner(engine2, pm2)
    naked_sell = runner2.process_step(
        _step(_rec(signal=SignalType.SELL, price=100.0, ts=TS0), close=100.0, replay_index=0),
    )
    sell_attempt = naked_sell[-1]
    assert not sell_attempt.accepted
    assert sell_attempt.reason_code is RejectionReason.NO_OPEN_POSITION
    assert pm2.get_open_positions() == []
    assert engine2.broker.cash == pytest.approx(10_000.0)

    runner2.process_step(
        _step(_rec(signal=SignalType.BUY, price=100.0, ts=TS0), close=100.0, replay_index=0),
    )
    assert pm2.get_position("RELIANCE") is not None
    dup = runner2.process_step(
        _step(_rec(signal=SignalType.BUY, price=101.0, ts=TS1), close=101.0, replay_index=1),
    )
    dup_attempt = dup[-1]
    assert not dup_attempt.accepted
    assert dup_attempt.reason_code is RejectionReason.ALREADY_HOLDING
    pos = pm2.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == pytest.approx(10.0)
    assert pos.entry_price == pytest.approx(100.0)
    assert len(pm2.get_open_positions()) == 1
    assert pm2.get_closed_positions() == []
