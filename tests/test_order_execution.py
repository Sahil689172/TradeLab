"""Unit tests for Phase A5.2 / A5.2.1 Order Execution Engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.backtesting.order_execution import (
    ExecutionConfig,
    ExitReason,
    OrderExecutionEngine,
    OrderRejectedError,
    OrderSide,
    PositionSizingMode,
    RejectionReason,
    SimulatedBroker,
)
from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType


def _rec(
    *,
    signal: SignalType,
    symbol: str = "RELIANCE",
    price: float = 100.0,
    ts: datetime | None = None,
    confidence: float = 60.0,
    stop_loss: float | None = None,
    target_1: float | None = None,
) -> TradeRecommendation:
    return TradeRecommendation(
        strategy_name="ema_trend",
        symbol=symbol,
        timeframe="1 Day",
        timestamp=ts or datetime(2022, 6, 1, tzinfo=timezone.utc),
        signal=signal,
        entry_price=price,
        stop_loss=stop_loss if stop_loss is not None else price * 0.98,
        target_1=target_1 if target_1 is not None else price * 1.02,
        target_2=price * 1.04 if signal is SignalType.BUY else price * 0.96,
        risk_reward=1.0,
        confidence=confidence,
        expected_holding_period=10,
        reasons=["unit test"],
        trend_direction=TrendDirection.SIDEWAYS,
        market_structure=TrendDirection.SIDEWAYS,
    )


def _cfg(
    *,
    capital: float,
    mode: PositionSizingMode = PositionSizingMode.FIXED_QUANTITY,
    quantity: float | None = 10.0,
    amount: float | None = None,
    percent: float = 95.0,
    slippage_bps: float = 0.0,
    brokerage_rate: float = 0.0,
    **kwargs,
) -> ExecutionConfig:
    return ExecutionConfig(
        initial_capital=capital,
        position_sizing=mode,
        quantity=quantity if mode is PositionSizingMode.FIXED_QUANTITY else None,
        amount=amount if mode is PositionSizingMode.FIXED_AMOUNT else None,
        percent=percent,
        slippage_bps=slippage_bps,
        brokerage_rate=brokerage_rate,
        allow_fractional_shares=False,
        **kwargs,
    )


def test_buy_updates_cash_and_position() -> None:
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert attempt.accepted
    assert attempt.fill is not None
    assert attempt.fill.side is OrderSide.BUY
    assert broker.cash == pytest.approx(99_000.0)
    position = broker.get_position("RELIANCE")
    assert position.is_open
    assert position.quantity == pytest.approx(10.0)
    assert position.average_entry_price == pytest.approx(100.0)
    assert len(broker.fill_log) == 1
    assert broker.fill_log[0].remaining_cash == pytest.approx(99_000.0)


def test_sell_realizes_pnl_and_clears_position() -> None:
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)
    # target_1 above exit so reason stays SELL Recommendation (not Target Hit)
    engine.process_recommendation(
        _rec(signal=SignalType.BUY, price=100.0, stop_loss=90.0, target_1=120.0),
    )
    sell = engine.process_recommendation(
        _rec(
            signal=SignalType.SELL,
            price=110.0,
            ts=datetime(2022, 6, 15, tzinfo=timezone.utc),
        ),
    )
    assert sell.accepted
    assert sell.fill is not None
    assert sell.fill.realized_pnl == pytest.approx(100.0)
    assert not broker.get_position("RELIANCE").is_open
    assert broker.cash == pytest.approx(100_100.0)
    assert broker.realized_pnl == pytest.approx(100.0)
    assert len(broker.fill_log) == 2
    assert len(broker.closed_trades) == 1
    closed = broker.closed_trades[0]
    assert closed.net_profit == pytest.approx(100.0)
    assert closed.exit_price == pytest.approx(110.0)
    assert closed.holding_days == 14
    assert closed.exit_reason is ExitReason.SELL_RECOMMENDATION


def test_duplicate_buy_rejected() -> None:
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=5.0))
    engine = OrderExecutionEngine(broker=broker)
    first = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    second = engine.process_recommendation(_rec(signal=SignalType.BUY, price=101.0))
    assert first.accepted
    assert not second.accepted
    assert second.reason_code is RejectionReason.ALREADY_HOLDING
    assert "Already holding position" in second.reason
    assert second.rejected is not None
    assert len(engine.rejected_orders) == 1


def test_invalid_sell_rejected() -> None:
    broker = SimulatedBroker(_cfg(capital=50_000.0, quantity=1.0))
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.SELL, price=100.0))
    assert not attempt.accepted
    assert attempt.reason_code is RejectionReason.NO_OPEN_POSITION
    assert broker.fill_log == []
    assert engine.rejected_orders[0].reason == RejectionReason.NO_OPEN_POSITION.value


def test_insufficient_cash_rejected() -> None:
    broker = SimulatedBroker(_cfg(capital=100.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=50.0))
    assert not attempt.accepted
    assert attempt.reason_code is RejectionReason.INSUFFICIENT_CASH


def test_slippage_and_brokerage_applied() -> None:
    broker = SimulatedBroker(
        _cfg(
            capital=100_000.0,
            quantity=10.0,
            slippage_bps=10.0,
            brokerage_rate=0.001,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert attempt.accepted
    assert attempt.fill is not None
    assert attempt.fill.execution_price == pytest.approx(100.1)
    notional = 100.1 * 10
    assert attempt.fill.brokerage == pytest.approx(notional * 0.001)
    assert attempt.trade_log is not None
    assert attempt.trade_log.slippage == pytest.approx(1.0)


def test_hold_does_not_trade() -> None:
    broker = SimulatedBroker(_cfg(capital=10_000.0, quantity=1.0))
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.HOLD, price=100.0))
    assert not attempt.accepted
    assert attempt.reason_code is RejectionReason.NO_ORDER_FOR_SIGNAL
    assert engine.rejected_orders == []
    assert broker.cash == pytest.approx(10_000.0)


def test_trade_log_fields() -> None:
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)
    engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    row = broker.fill_log[0]
    assert row.symbol == "RELIANCE"
    assert row.side is OrderSide.BUY
    assert row.quantity == pytest.approx(10.0)
    assert row.execution_price == pytest.approx(100.0)
    assert row.brokerage == pytest.approx(0.0)
    assert row.slippage == pytest.approx(0.0)
    assert row.pnl == pytest.approx(0.0)
    assert row.remaining_cash == pytest.approx(99_000.0)


def test_broker_direct_reject_sell() -> None:
    broker = SimulatedBroker(_cfg(capital=1_000.0, quantity=1.0))
    from app.backtesting.order_execution.orders import MarketOrder

    order = MarketOrder(
        symbol="TCS",
        side=OrderSide.SELL,
        quantity=1.0,
        submitted_at=datetime.now(timezone.utc),
        reference_price=10.0,
    )
    with pytest.raises(OrderRejectedError) as exc:
        broker.submit_market_order(order)
    assert exc.value.reason_code is RejectionReason.NO_OPEN_POSITION


@pytest.mark.parametrize("capital", [200.0, 500.0, 1000.0])
def test_small_capital_cannot_buy_expensive_share(capital: float) -> None:
    """₹200/500/1000 cannot buy one RELIANCE-priced share at ₹2500."""
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=capital,
            position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
            percent=100.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=2500.0))
    assert not attempt.accepted
    assert attempt.reason == RejectionReason.CAPITAL_INSUFFICIENT_ONE_SHARE.value
    assert attempt.reason_code is RejectionReason.CAPITAL_INSUFFICIENT_ONE_SHARE


@pytest.mark.parametrize("capital", [100_000.0, 1_000_000.0])
def test_large_capital_buys_whole_shares(capital: float) -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=capital,
            position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
            percent=50.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert attempt.accepted
    qty = attempt.fill.quantity if attempt.fill else 0
    assert qty == int(qty)
    assert qty >= 1
    assert broker.cash < capital


def test_position_sizing_fixed_amount() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=10_000.0,
            position_sizing=PositionSizingMode.FIXED_AMOUNT,
            amount=500.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert attempt.accepted
    assert attempt.fill is not None
    assert attempt.fill.quantity == pytest.approx(5.0)
    assert broker.cash == pytest.approx(9_500.0)


def test_position_sizing_fixed_quantity() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=10_000.0,
            position_sizing=PositionSizingMode.FIXED_QUANTITY,
            quantity=3.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert attempt.accepted
    assert attempt.fill is not None
    assert attempt.fill.quantity == pytest.approx(3.0)


def test_position_sizing_percent_of_capital() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=10_000.0,
            position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
            percent=25.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert attempt.accepted
    assert attempt.fill is not None
    # 25% of 10_000 = 2500 → 25 shares
    assert attempt.fill.quantity == pytest.approx(25.0)


def test_fixed_amount_below_one_share_rejected() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=10_000.0,
            position_sizing=PositionSizingMode.FIXED_AMOUNT,
            amount=50.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert not attempt.accepted
    assert attempt.reason == RejectionReason.CAPITAL_INSUFFICIENT_ONE_SHARE.value


def test_confidence_below_threshold_rejected() -> None:
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=1.0, min_confidence=80.0))
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(
        _rec(signal=SignalType.BUY, price=100.0, confidence=50.0),
    )
    assert not attempt.accepted
    assert attempt.reason_code is RejectionReason.CONFIDENCE_BELOW_THRESHOLD


def test_trade_outside_session_rejected() -> None:
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end = datetime(2022, 6, 30, tzinfo=timezone.utc)
    broker = SimulatedBroker(
        _cfg(
            capital=100_000.0,
            quantity=1.0,
            session_start=start,
            session_end=end,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(
        _rec(
            signal=SignalType.BUY,
            price=100.0,
            ts=datetime(2022, 8, 1, tzinfo=timezone.utc),
        ),
    )
    assert not attempt.accepted
    assert attempt.reason_code is RejectionReason.TRADE_OUTSIDE_REPLAY


def test_closed_trade_log_target_hit() -> None:
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)
    engine.process_recommendation(
        _rec(signal=SignalType.BUY, price=100.0, stop_loss=95.0, target_1=105.0),
    )
    sell = engine.process_recommendation(
        _rec(
            signal=SignalType.SELL,
            price=106.0,
            ts=datetime(2022, 6, 10, tzinfo=timezone.utc),
        ),
    )
    assert sell.accepted
    assert sell.closed_trade is not None
    assert sell.closed_trade.exit_reason is ExitReason.TARGET_HIT
    assert sell.closed_trade.gross_profit == pytest.approx(60.0)
    assert sell.closed_trade.holding_days == 9


def test_closed_trade_log_stop_loss() -> None:
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)
    engine.process_recommendation(
        _rec(signal=SignalType.BUY, price=100.0, stop_loss=95.0, target_1=110.0),
    )
    sell = engine.process_recommendation(
        _rec(
            signal=SignalType.SELL,
            price=94.0,
            ts=datetime(2022, 6, 5, tzinfo=timezone.utc),
        ),
    )
    assert sell.accepted
    assert sell.closed_trade is not None
    assert sell.closed_trade.exit_reason is ExitReason.STOP_LOSS
    assert sell.closed_trade.net_profit == pytest.approx(-60.0)


def test_execution_summary_counts() -> None:
    from app.backtesting.replay_engine.schemas import (
        ReplayConfig,
        ReplayResult,
        ReplaySpeed,
        ReplayStepResult,
    )

    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=10.0))
    engine = OrderExecutionEngine(broker=broker)

    buy = _rec(signal=SignalType.BUY, price=100.0, ts=datetime(2022, 6, 1, tzinfo=timezone.utc))
    hold = _rec(signal=SignalType.HOLD, price=101.0, ts=datetime(2022, 6, 2, tzinfo=timezone.utc))
    sell = _rec(signal=SignalType.SELL, price=110.0, ts=datetime(2022, 6, 20, tzinfo=timezone.utc))

    steps = []
    for idx, (rec, close) in enumerate(((buy, 100.0), (hold, 101.0), (sell, 110.0))):
        steps.append(
            ReplayStepResult(
                symbol=rec.symbol,
                strategy_name=rec.strategy_name,
                timestamp=rec.timestamp,
                replay_index=idx,
                current_close=close,
                recommendation=rec,
                signal=rec.signal,
                confidence=rec.confidence,
                stop_loss=rec.stop_loss,
                target_1=rec.target_1,
                target_2=rec.target_2,
                expected_holding_period=rec.expected_holding_period,
            ),
        )

    replay = ReplayResult(
        config=ReplayConfig(
            symbols=["RELIANCE"],
            strategy_names=["ema_trend"],
            speed=ReplaySpeed.FAST,
        ),
        started_at=datetime(2022, 6, 1, tzinfo=timezone.utc),
        completed_at=datetime(2022, 6, 20, tzinfo=timezone.utc),
        steps=steps,
        candles_replayed=3,
        recommendations_generated=3,
        symbols=["RELIANCE"],
    )
    result = engine.process_replay_result(replay)
    assert result.summary.orders_filled >= 2
    assert result.summary.closed_positions == 1
    assert result.summary.win_trades == 1
    assert result.summary.open_positions == 0
    assert result.trade_log[0].exit_reason in {
        ExitReason.SELL_RECOMMENDATION,
        ExitReason.TARGET_HIT,
        ExitReason.STOP_LOSS,
        ExitReason.REPLAY_END,
    }
    assert result.summary.current_cash == pytest.approx(broker.cash)


def test_debug_orders_emits_messages() -> None:
    lines: list[str] = []
    broker = SimulatedBroker(_cfg(capital=100_000.0, quantity=2.0))
    engine = OrderExecutionEngine(
        broker=broker,
        debug=True,
        debug_callback=lines.append,
    )
    engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    engine.process_recommendation(_rec(signal=SignalType.BUY, price=101.0))
    assert any("Executed" in block for block in lines)
    assert any("Rejected" in block for block in lines)
