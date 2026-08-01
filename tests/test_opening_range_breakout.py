"""Unit tests for the Opening Range Breakout strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.strategies.opening_range_breakout import (
    OpeningRangeBreakoutConfig,
    OpeningRangeBreakoutStrategy,
    ORBStopSource,
    register_opening_range_breakout_strategy,
)
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner


def make_structure(trend: TrendDirection) -> MarketStructureResult:
    return MarketStructureResult(
        symbol="RELIANCE",
        swing_length=2,
        bar_count=40,
        trend=trend,
        swings=[],
        events=[],
        last_swing_high=None,
        last_swing_low=None,
    )


def build_session(
    *,
    or_rows: list[dict[str, float]],
    after_rows: list[dict[str, float]],
    prior_day: bool = False,
) -> pd.DataFrame:
    """Build a same-day session with optional prior-day bar for gap tests."""
    rows: list[dict[str, object]] = []
    if prior_day:
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01 15:15"),
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.0,
                "relative_volume_20": 1.0,
                "atr_14": 1.0,
                "ema_20": 99.5,
                "ema_50": 99.0,
            },
        )
    start = pd.Timestamp("2024-01-02 09:15")
    for index, row in enumerate([*or_rows, *after_rows]):
        rows.append(
            {
                "date": start + pd.Timedelta(minutes=5 * index),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "relative_volume_20": row.get("relative_volume_20", 2.0),
                "atr_14": row.get("atr_14", 1.0),
                "ema_20": row.get("ema_20", row["close"] + 0.5),
                "ema_50": row.get("ema_50", row["close"] - 0.5),
            },
        )
    return pd.DataFrame(rows)


def bullish_frame(*, rvol: float = 2.0) -> pd.DataFrame:
    # 15m OR with 5m bars => 3 OR bars, then one inside-range bar + breakout
    or_rows = [
        {"open": 100.0, "high": 100.4, "low": 99.6, "close": 100.1, "relative_volume_20": 1.0},
        {"open": 100.1, "high": 100.5, "low": 99.7, "close": 100.2, "relative_volume_20": 1.1},
        {"open": 100.2, "high": 100.6, "low": 99.8, "close": 100.3, "relative_volume_20": 1.0},
    ]
    after = [
        {
            "open": 100.3,
            "high": 100.5,
            "low": 100.0,
            "close": 100.4,  # still inside OR
            "relative_volume_20": 1.2,
            "ema_20": 100.4,
            "ema_50": 100.0,
            "atr_14": 0.8,
        },
        {
            "open": 100.4,
            "high": 101.5,
            "low": 100.3,
            "close": 101.2,
            "relative_volume_20": rvol,
            "ema_20": 101.0,
            "ema_50": 100.0,
            "atr_14": 0.8,
        },
    ]
    return build_session(or_rows=or_rows, after_rows=after)


def bearish_frame(*, rvol: float = 2.0) -> pd.DataFrame:
    or_rows = [
        {"open": 100.0, "high": 100.4, "low": 99.6, "close": 99.9, "relative_volume_20": 1.0},
        {"open": 99.9, "high": 100.3, "low": 99.5, "close": 99.8, "relative_volume_20": 1.1},
        {"open": 99.8, "high": 100.2, "low": 99.4, "close": 99.7, "relative_volume_20": 1.0},
    ]
    after = [
        {
            "open": 99.7,
            "high": 100.0,
            "low": 99.5,
            "close": 99.6,  # still inside OR
            "relative_volume_20": 1.2,
            "ema_20": 99.5,
            "ema_50": 100.0,
            "atr_14": 0.8,
        },
        {
            "open": 99.6,
            "high": 99.7,
            "low": 98.5,
            "close": 98.8,
            "relative_volume_20": rvol,
            "ema_20": 99.0,
            "ema_50": 100.0,
            "atr_14": 0.8,
        },
    ]
    return build_session(or_rows=or_rows, after_rows=after)


def false_breakout_frame() -> pd.DataFrame:
    """Wick above ORH but close back inside."""
    or_rows = [
        {"open": 100.0, "high": 100.4, "low": 99.6, "close": 100.1, "relative_volume_20": 1.0},
        {"open": 100.1, "high": 100.5, "low": 99.7, "close": 100.2, "relative_volume_20": 1.1},
        {"open": 100.2, "high": 100.6, "low": 99.8, "close": 100.3, "relative_volume_20": 1.0},
    ]
    after = [
        {
            "open": 100.3,
            "high": 100.5,
            "low": 100.0,
            "close": 100.35,
            "relative_volume_20": 1.2,
            "ema_20": 100.4,
            "ema_50": 100.0,
        },
        {
            "open": 100.3,
            "high": 101.2,
            "low": 100.0,
            "close": 100.4,  # still inside OR (ORH=100.6)
            "relative_volume_20": 2.0,
            "ema_20": 100.5,
            "ema_50": 100.0,
        },
    ]
    return build_session(or_rows=or_rows, after_rows=after)


def already_traded_frame() -> pd.DataFrame:
    or_rows = [
        {"open": 100.0, "high": 100.4, "low": 99.6, "close": 100.1, "relative_volume_20": 1.0},
        {"open": 100.1, "high": 100.5, "low": 99.7, "close": 100.2, "relative_volume_20": 1.1},
        {"open": 100.2, "high": 100.6, "low": 99.8, "close": 100.3, "relative_volume_20": 1.0},
    ]
    after = [
        {
            "open": 100.5,
            "high": 101.4,
            "low": 100.4,
            "close": 101.1,  # prior breakout
            "relative_volume_20": 2.0,
            "ema_20": 101.0,
            "ema_50": 100.0,
        },
        {
            "open": 101.0,
            "high": 101.8,
            "low": 100.9,
            "close": 101.5,  # second breakout attempt
            "relative_volume_20": 2.2,
            "ema_20": 101.2,
            "ema_50": 100.0,
        },
    ]
    return build_session(or_rows=or_rows, after_rows=after)


@pytest.fixture
def config() -> OpeningRangeBreakoutConfig:
    return OpeningRangeBreakoutConfig(
        symbol="RELIANCE",
        opening_range_minutes=15,
        bar_minutes=5,
        min_history_bars=5,
        max_breakout_bars_after_or=20,
    )


def build_strategy(
    config: OpeningRangeBreakoutConfig,
    trend: TrendDirection,
) -> OpeningRangeBreakoutStrategy:
    return OpeningRangeBreakoutStrategy(
        config,
        market_structure=make_structure(trend),
    )


def test_bullish_breakout(config: OpeningRangeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(bullish_frame()))

    assert signal.signal is SignalType.BUY
    assert signal.confidence > 0.5


def test_bearish_breakout(config: OpeningRangeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BEARISH)
    signal = strategy.generate_signal(strategy.prepare(bearish_frame()))

    assert signal.signal is SignalType.SELL


def test_false_breakout_holds(config: OpeningRangeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(false_breakout_frame()))

    assert signal.signal is SignalType.HOLD


def test_low_volume_holds(config: OpeningRangeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(bullish_frame(rvol=1.1)))

    assert signal.signal is SignalType.HOLD
    assert "volume" in signal.reason.lower()


def test_already_traded_holds(config: OpeningRangeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(already_traded_frame()))

    assert signal.signal is SignalType.HOLD
    assert "already" in signal.reason.lower() or "prior" in signal.reason.lower()


def test_stop_loss_uses_opening_range(config: OpeningRangeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    frame = bullish_frame()
    plan = StrategyRunner().run(frame, strategy)
    detailed = strategy.last_detailed_plan

    assert detailed is not None
    assert detailed.stop_source is ORBStopSource.OPENING_RANGE
    assert plan.stop_loss == pytest.approx(detailed.opening_range.low)
    assert plan.stop_loss < plan.entry_price < plan.take_profit_1


def test_trade_plan_generation(config: OpeningRangeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    plan = StrategyRunner().run(bullish_frame(), strategy)
    detailed = strategy.last_detailed_plan

    assert plan.strategy_name == "opening_range_breakout"
    assert plan.signal is SignalType.BUY
    assert plan.risk_reward == pytest.approx(2.0)
    assert plan.holding_period == config.session_bars
    assert any("Opening range" in reason for reason in plan.reasons)
    assert any("intraday" in reason.lower() for reason in plan.reasons)
    assert detailed is not None
    assert detailed.opening_range.minutes == 15
    assert detailed.opening_range.bars == 3
    assert detailed.opening_range.mid == pytest.approx(
        (detailed.opening_range.high + detailed.opening_range.low) / 2.0,
    )


def test_configurable_opening_range_30m() -> None:
    config = OpeningRangeBreakoutConfig(
        symbol="RELIANCE",
        opening_range_minutes=30,
        bar_minutes=5,
        min_history_bars=7,
        max_breakout_bars_after_or=20,
    )
    assert config.opening_range_bars == 6

    or_rows = [
        {"open": 100.0, "high": 100.3, "low": 99.8, "close": 100.0, "relative_volume_20": 1.0}
        for _ in range(6)
    ]
    # Raise OR high on last OR bar
    or_rows[-1] = {
        "open": 100.0,
        "high": 100.5,
        "low": 99.7,
        "close": 100.2,
        "relative_volume_20": 1.0,
    }
    after = [
        {
            "open": 100.3,
            "high": 101.4,
            "low": 100.2,
            "close": 101.1,
            "relative_volume_20": 2.0,
            "ema_20": 101.0,
            "ema_50": 100.0,
            "atr_14": 0.7,
        },
    ]
    strategy = build_strategy(config, TrendDirection.BULLISH)
    prepared = strategy.prepare(build_session(or_rows=or_rows, after_rows=after))
    assert strategy.last_detailed_plan is None
    assert strategy._cached_opening is not None
    assert strategy._cached_opening.bars == 6
    assert strategy._cached_opening.minutes == 30
    assert strategy.generate_signal(prepared).signal is SignalType.BUY


def test_registry_integration(config: OpeningRangeBreakoutConfig) -> None:
    registry = StrategyRegistry()
    register_opening_range_breakout_strategy(
        registry,
        config,
        market_structure=make_structure(TrendDirection.BULLISH),
    )
    plan = StrategyRunner().run(bullish_frame(), registry.get("opening_range_breakout"))
    assert plan.signal is SignalType.BUY
