"""Unit tests for the EMA Trend Following strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.feature_engine.pipeline import FeaturePipeline
from app.strategies.ema_trend import (
    EMATrendConfig,
    EMATrendStrategy,
    register_ema_trend_strategy,
)
from app.strategy_engine import StrategyRegistry, StrategyRunner, SignalType
from app.strategy_engine.exceptions import StrategyValidationError
from tests.test_indicators import make_prices


def make_strategy_frame(
    *,
    rows: int = 80,
    cross: str = "none",
    adx: float = 30.0,
    close_vs_slow: str = "above",
) -> pd.DataFrame:
    """Build a deterministic feature frame for EMA trend tests.

    cross:
        "above" — EMA20 crosses above EMA50 on the last bar
        "below" — EMA20 crosses below EMA50 on the last bar
        "none" — no cross on the last bar (fast remains above slow)
    """
    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    close = np.linspace(100.0, 120.0, rows)
    ema_20 = close - 1.0
    ema_50 = close - 2.0

    if cross == "above":
        ema_20[-2] = 109.0
        ema_50[-2] = 110.0
        ema_20[-1] = 111.0
        ema_50[-1] = 110.0
        close[-1] = 112.0
    elif cross == "below":
        ema_20[-2] = 111.0
        ema_50[-2] = 110.0
        ema_20[-1] = 109.0
        ema_50[-1] = 110.0
        close[-1] = 108.0
    else:
        ema_20[-2] = 111.0
        ema_50[-2] = 110.0
        ema_20[-1] = 112.0
        ema_50[-1] = 110.5
        close[-1] = 113.0

    if close_vs_slow == "below":
        close[-1] = float(ema_50[-1]) - 1.0

    frame = pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "ema_9": close - 0.5,
            "ema_20": ema_20,
            "ema_21": close - 1.1,
            "ema_50": ema_50,
            "adx_14": adx,
            "atr_14": 2.0,
            "rsi_14": 60.0,
            "relative_volume_20": 1.2,
        },
    )
    return frame


@pytest.fixture
def buy_frame() -> pd.DataFrame:
    return make_strategy_frame(cross="above", adx=30.0, close_vs_slow="above")


@pytest.fixture
def strategy() -> EMATrendStrategy:
    return EMATrendStrategy(EMATrendConfig(symbol="RELIANCE"))


def test_buy_signal_when_entry_rules_met(strategy: EMATrendStrategy, buy_frame: pd.DataFrame) -> None:
    prepared = strategy.prepare(buy_frame)
    signal = strategy.generate_signal(prepared)

    assert signal.signal is SignalType.BUY
    assert signal.symbol == "RELIANCE"
    assert 0.0 <= signal.confidence <= 1.0
    assert "Entry" in signal.reason or "cross above" in signal.reason.lower()


def test_trade_plan_contains_risk_targets_and_reasons(
    strategy: EMATrendStrategy,
    buy_frame: pd.DataFrame,
) -> None:
    runner = StrategyRunner()
    plan = runner.run(buy_frame, strategy)

    assert plan.strategy_name == "ema_trend"
    assert plan.symbol == "RELIANCE"
    assert plan.signal is SignalType.BUY
    assert plan.entry_price == pytest.approx(float(buy_frame.iloc[-1]["close"]))
    assert plan.stop_loss < plan.entry_price < plan.take_profit_1 < plan.take_profit_2
    assert plan.risk_reward == pytest.approx(2.0)
    assert 5 <= plan.holding_period <= 20
    assert any(reason.startswith("Entry:") for reason in plan.reasons)
    assert any(reason.startswith("Exit:") for reason in plan.reasons)
    # ATR x 2 stop
    atr = float(buy_frame.iloc[-1]["atr_14"])
    assert plan.stop_loss == pytest.approx(plan.entry_price - 2.0 * atr)


def test_exit_signal_on_ema_cross_below(strategy: EMATrendStrategy) -> None:
    frame = make_strategy_frame(cross="below", adx=30.0)
    signal = strategy.generate_signal(strategy.prepare(frame))

    assert signal.signal is SignalType.EXIT
    assert "cross below" in signal.reason.lower() or "Exit" in signal.reason


def test_hold_when_adx_too_low(strategy: EMATrendStrategy) -> None:
    frame = make_strategy_frame(cross="above", adx=20.0, close_vs_slow="above")
    signal = strategy.generate_signal(strategy.prepare(frame))

    assert signal.signal is SignalType.HOLD


def test_hold_when_close_below_ema50(strategy: EMATrendStrategy) -> None:
    frame = make_strategy_frame(cross="above", adx=30.0, close_vs_slow="below")
    signal = strategy.generate_signal(strategy.prepare(frame))

    assert signal.signal is SignalType.HOLD


def test_validate_requires_columns(strategy: EMATrendStrategy) -> None:
    frame = make_strategy_frame().drop(columns=["ema_20"])
    with pytest.raises(StrategyValidationError, match="missing required columns"):
        strategy.validate(frame)


def test_registry_and_runner_integration(buy_frame: pd.DataFrame) -> None:
    registry = StrategyRegistry()
    strategy = register_ema_trend_strategy(
        registry,
        EMATrendConfig(symbol="RELIANCE", risk_reward_1=2.0, risk_reward_2=3.0),
    )

    assert registry.list() == ["ema_trend"]
    assert registry.get("ema_trend") is strategy

    plan = StrategyRunner().run(buy_frame, registry.get("ema_trend"))
    assert plan.strategy_name == "ema_trend"
    assert plan.take_profit_2 > plan.take_profit_1


def test_risk_reward_is_configurable(buy_frame: pd.DataFrame) -> None:
    strategy = EMATrendStrategy(
        EMATrendConfig(symbol="RELIANCE", risk_reward_1=1.5, risk_reward_2=2.5),
    )
    plan = StrategyRunner().run(buy_frame, strategy)
    risk = plan.entry_price - plan.stop_loss

    assert plan.take_profit_1 == pytest.approx(plan.entry_price + risk * 1.5)
    assert plan.take_profit_2 == pytest.approx(plan.entry_price + risk * 2.5)
    assert plan.risk_reward == pytest.approx(1.5)


def test_deterministic_repeated_runs(strategy: EMATrendStrategy, buy_frame: pd.DataFrame) -> None:
    runner = StrategyRunner()
    first = runner.run(buy_frame, strategy)
    second = runner.run(buy_frame.copy(), strategy)

    assert first.model_dump() == second.model_dump()


def test_feature_pipeline_integration() -> None:
    """End-to-end: FeaturePipeline columns + close are readable without recalculation."""
    ohlcv = make_prices(120)
    features = FeaturePipeline().transform(ohlcv)
    assert "ema_20" in features.columns
    assert "ema_50" in features.columns
    assert "adx_14" in features.columns
    assert "atr_14" in features.columns

    market = ohlcv.merge(features, on="date", how="left")
    strategy = EMATrendStrategy(EMATrendConfig(symbol="TEST", min_history_bars=60))
    plan = StrategyRunner().run(market, strategy)

    assert plan.strategy_name == "ema_trend"
    assert plan.signal in {SignalType.BUY, SignalType.SELL, SignalType.HOLD, SignalType.EXIT}
    assert plan.stop_loss > 0
    assert plan.take_profit_1 > 0
    assert plan.take_profit_2 > 0
