"""Unit tests for Break & Retest engine and strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.break_retest import (
    BreakRetestEngine,
    BreakRetestStage,
)
from app.strategies.break_retest import (
    BreakRetestStopSource,
    BreakRetestStrategy,
    BreakRetestStrategyConfig,
    register_break_retest_strategy,
)
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner


def make_structure(trend: TrendDirection) -> MarketStructureResult:
    return MarketStructureResult(
        symbol="RELIANCE",
        swing_length=2,
        bar_count=30,
        trend=trend,
        swings=[],
        events=[],
        last_swing_high=None,
        last_swing_low=None,
    )


def _row(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1_000.0,
    rvol: float = 1.0,
) -> dict[str, float]:
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "relative_volume_20": rvol,
        "atr_14": 1.5,
    }


def build_frame(scenario_rows: list[dict[str, float]], *, pad: int = 22) -> pd.DataFrame:
    """Quiet bars below resistance 100, then scenario bars."""
    rows: list[dict[str, float]] = []
    for index in range(pad):
        price = 95.0 + index * 0.05
        rows.append(
            _row(
                open_=price,
                high=min(price + 0.4, 99.5),
                low=price - 0.3,
                close=price,
                volume=800 + index * 5,
                rvol=1.0,
            ),
        )
    # Explicit resistance touch at 100 before the scenario
    rows.append(
        _row(open_=98.5, high=100.0, low=98.0, close=99.0, volume=1_000, rvol=1.1),
    )
    rows.append(
        _row(open_=99.0, high=99.5, low=98.2, close=98.8, volume=1_050, rvol=1.1),
    )
    rows.extend(scenario_rows)

    start = pd.Timestamp("2024-01-02 09:15")
    records = []
    for index, row in enumerate(rows):
        records.append(
            {
                "date": start + pd.Timedelta(minutes=15 * index),
                **row,
            },
        )
    return pd.DataFrame(records)


@pytest.fixture
def config() -> BreakRetestStrategyConfig:
    return BreakRetestStrategyConfig(
        symbol="RELIANCE",
        lookback=20,
        min_history_bars=25,
        relative_volume_threshold=1.5,
        min_body_ratio=0.4,
    )


def build_strategy(
    config: BreakRetestStrategyConfig,
    *,
    trend: TrendDirection = TrendDirection.BULLISH,
    resistance: float = 100.0,
    support: float = 90.0,
) -> BreakRetestStrategy:
    return BreakRetestStrategy(
        config,
        resistance=resistance,
        support=support,
        market_structure=make_structure(trend),
    )


def test_successful_retest(config: BreakRetestStrategyConfig) -> None:
    frame = build_frame(
        [
            # Break above 100
            _row(open_=99.5, high=101.5, low=99.2, close=101.2, volume=2_000, rvol=1.2),
            # Successful retest — touch 100, hold above
            _row(open_=101.0, high=101.3, low=100.0, close=100.5, volume=1_800, rvol=1.3),
            # Bullish confirmation + healthy RVOL
            _row(open_=100.6, high=102.5, low=100.4, close=102.2, volume=3_500, rvol=2.0),
        ],
    )
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    prepared = strategy.prepare(frame)
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.BUY
    setup = strategy.last_setup
    assert setup is not None
    assert setup.long_sequence.stage is BreakRetestStage.CONFIRMED
    assert setup.long_sequence.retest_event is not None
    assert setup.long_sequence.retest_event.successful is True


def test_failed_retest(config: BreakRetestStrategyConfig) -> None:
    frame = build_frame(
        [
            _row(open_=99.5, high=101.5, low=99.2, close=101.2, volume=2_000, rvol=1.2),
            # Close back through level → failed retest
            _row(open_=100.8, high=101.0, low=98.5, close=99.0, volume=2_200, rvol=1.8),
            _row(open_=99.0, high=99.5, low=98.0, close=98.5, volume=2_000, rvol=1.6),
        ],
    )
    engine = BreakRetestEngine()
    sequence = engine.scan(frame, direction=TradeDirection.LONG, level=100.0)
    assert sequence.stage is BreakRetestStage.FAILED_RETEST
    assert sequence.retest_event is not None
    assert sequence.retest_event.successful is False

    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD


def test_false_breakout(config: BreakRetestStrategyConfig) -> None:
    frame = build_frame(
        [
            # Break, then drift higher without revisiting the level
            _row(open_=99.5, high=101.5, low=99.2, close=101.2, volume=2_000, rvol=1.2),
            _row(open_=101.3, high=102.0, low=101.0, close=101.8, volume=1_500, rvol=1.1),
            _row(open_=101.8, high=103.0, low=101.5, close=102.5, volume=1_600, rvol=1.2),
        ],
    )
    engine = BreakRetestEngine()
    sequence = engine.scan(frame, direction=TradeDirection.LONG, level=100.0)
    assert sequence.stage is BreakRetestStage.BROKEN
    assert sequence.false_breakout is True
    assert sequence.retest_event is None

    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert "false breakout" in signal.reason.lower()


def test_trade_plan(config: BreakRetestStrategyConfig) -> None:
    frame = build_frame(
        [
            _row(open_=99.5, high=101.5, low=99.2, close=101.2, volume=2_000, rvol=1.2),
            _row(open_=101.0, high=101.3, low=99.8, close=100.4, volume=1_800, rvol=1.3),
            _row(open_=100.6, high=102.5, low=100.4, close=102.2, volume=3_500, rvol=2.0),
        ],
    )
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    prepared = strategy.prepare(frame)
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.BUY

    plan = strategy.generate_trade_plan(prepared, signal)
    detailed = strategy.last_detailed_plan
    assert detailed is not None
    assert plan.entry_price == pytest.approx(102.2)
    assert plan.stop_loss > 0
    assert plan.take_profit_1 > plan.entry_price
    assert plan.take_profit_2 > plan.take_profit_1
    assert 0.0 < plan.confidence <= 1.0
    assert plan.reasons
    assert detailed.stop_source is BreakRetestStopSource.RETEST_LOW
    assert detailed.stop_loss == pytest.approx(99.8)
    assert detailed.market_structure is TrendDirection.BULLISH
    assert "Successful retest" in " ".join(detailed.reasons)


def test_registration(config: BreakRetestStrategyConfig) -> None:
    frame = build_frame(
        [
            _row(open_=99.5, high=101.5, low=99.2, close=101.2, volume=2_000, rvol=1.2),
            _row(open_=101.0, high=101.3, low=99.8, close=100.4, volume=1_800, rvol=1.3),
            _row(open_=100.6, high=102.5, low=100.4, close=102.2, volume=3_500, rvol=2.0),
        ],
    )
    registry = StrategyRegistry()
    register_break_retest_strategy(
        registry,
        config,
        resistance=100.0,
        support=90.0,
        market_structure=make_structure(TrendDirection.BULLISH),
    )
    plan = StrategyRunner().run(frame, registry.get("break_retest"))
    assert plan.strategy_name == "break_retest"
    assert plan.signal is SignalType.BUY
