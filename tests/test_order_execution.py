"""Unit tests for Phase A5.2 Order Execution Engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.backtesting.order_execution import (
    ExecutionConfig,
    OrderExecutionEngine,
    OrderRejectedError,
    OrderSide,
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
) -> TradeRecommendation:
    return TradeRecommendation(
        strategy_name="ema_trend",
        symbol=symbol,
        timeframe="1 Day",
        timestamp=ts or datetime(2022, 6, 1, tzinfo=timezone.utc),
        signal=signal,
        entry_price=price,
        stop_loss=price * 0.98,
        target_1=price * 1.02,
        target_2=price * 1.04,
        risk_reward=1.0,
        confidence=60.0,
        expected_holding_period=10,
        reasons=["unit test"],
        trend_direction=TrendDirection.SIDEWAYS,
        market_structure=TrendDirection.SIDEWAYS,
    )


def test_buy_updates_cash_and_position() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=100_000.0,
            fixed_quantity=10.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
            brokerage_flat=0.0,
        ),
    )
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
    assert len(broker.trade_log) == 1
    assert broker.trade_log[0].remaining_cash == pytest.approx(99_000.0)


def test_sell_realizes_pnl_and_clears_position() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=100_000.0,
            fixed_quantity=10.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    sell = engine.process_recommendation(_rec(signal=SignalType.SELL, price=110.0))
    assert sell.accepted
    assert sell.fill is not None
    assert sell.fill.realized_pnl == pytest.approx(100.0)
    assert not broker.get_position("RELIANCE").is_open
    assert broker.cash == pytest.approx(100_100.0)
    assert broker.realized_pnl == pytest.approx(100.0)
    assert len(broker.trade_log) == 2
    assert broker.trade_log[-1].pnl == pytest.approx(100.0)
    assert broker.trade_log[-1].average_exit_price == pytest.approx(110.0)


def test_duplicate_buy_rejected() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(initial_capital=100_000.0, fixed_quantity=5.0, slippage_bps=0.0, brokerage_rate=0.0),
    )
    engine = OrderExecutionEngine(broker=broker)
    first = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    second = engine.process_recommendation(_rec(signal=SignalType.BUY, price=101.0))
    assert first.accepted
    assert not second.accepted
    assert "already holding" in second.reason.lower()
    assert broker.get_position("RELIANCE").quantity == pytest.approx(5.0)


def test_invalid_sell_rejected() -> None:
    broker = SimulatedBroker(ExecutionConfig(initial_capital=50_000.0))
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.SELL, price=100.0))
    assert not attempt.accepted
    assert "no open position" in attempt.reason.lower()
    assert broker.trade_log == []


def test_insufficient_cash_rejected() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=100.0,
            fixed_quantity=10.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=50.0))
    assert not attempt.accepted
    assert "insufficient cash" in attempt.reason.lower()


def test_slippage_and_brokerage_applied() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=100_000.0,
            fixed_quantity=10.0,
            slippage_bps=10.0,  # 0.10%
            brokerage_rate=0.001,
            brokerage_flat=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    assert attempt.accepted
    assert attempt.fill is not None
    # BUY exec = 100 * (1 + 0.001) = 100.1
    assert attempt.fill.execution_price == pytest.approx(100.1)
    notional = 100.1 * 10
    assert attempt.fill.brokerage == pytest.approx(notional * 0.001)
    assert attempt.trade_log is not None
    assert attempt.trade_log.slippage == pytest.approx(1.0)  # 0.1 * 10


def test_hold_does_not_trade() -> None:
    broker = SimulatedBroker(ExecutionConfig(initial_capital=10_000.0))
    engine = OrderExecutionEngine(broker=broker)
    attempt = engine.process_recommendation(_rec(signal=SignalType.HOLD, price=100.0))
    assert not attempt.accepted
    assert attempt.reason.startswith("No order")
    assert broker.cash == pytest.approx(10_000.0)
    assert broker.trade_log == []


def test_trade_log_fields() -> None:
    broker = SimulatedBroker(
        ExecutionConfig(
            initial_capital=100_000.0,
            fixed_quantity=10.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
        ),
    )
    engine = OrderExecutionEngine(broker=broker)
    engine.process_recommendation(_rec(signal=SignalType.BUY, price=100.0))
    row = broker.trade_log[0]
    assert row.symbol == "RELIANCE"
    assert row.side is OrderSide.BUY
    assert row.quantity == pytest.approx(10.0)
    assert row.execution_price == pytest.approx(100.0)
    assert row.brokerage == pytest.approx(0.0)
    assert row.slippage == pytest.approx(0.0)
    assert row.pnl == pytest.approx(0.0)
    assert row.remaining_cash == pytest.approx(99_000.0)


def test_broker_direct_reject_sell() -> None:
    broker = SimulatedBroker(ExecutionConfig(initial_capital=1_000.0))
    from app.backtesting.order_execution.orders import MarketOrder

    order = MarketOrder(
        symbol="TCS",
        side=OrderSide.SELL,
        quantity=1.0,
        submitted_at=datetime.now(timezone.utc),
        reference_price=10.0,
    )
    with pytest.raises(OrderRejectedError):
        broker.submit_market_order(order)
