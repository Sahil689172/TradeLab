"""Unit tests for SuperTrend indicator service and strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from app.indicator_adapter import IndicatorAdapter
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.services.strategy_engine.indicators.supertrend import (
    SuperTrendService,
    compute_supertrend,
)
from app.strategies.supertrend import (
    SuperTrendStopSource,
    SuperTrendStrategy,
    SuperTrendStrategyConfig,
    register_supertrend_strategy,
)
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner


ATR_PERIOD = 7
MULTIPLIER = 2.0


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


def _ohlc_frame(
    closes: list[float],
    *,
    rvol: float = 2.0,
    atr: float = 2.0,
    ema_bullish: bool = True,
) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-02")
    records = []
    for index, close in enumerate(closes):
        high = close + 1.0
        low = max(close - 1.0, 0.1)
        if ema_bullish:
            ema_20 = close * 1.01
            ema_50 = close * 0.99
        else:
            ema_20 = close * 0.99
            ema_50 = close * 1.01
        records.append(
            {
                "date": start + pd.Timedelta(days=index),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000.0 + index * 10,
                "relative_volume_20": rvol,
                "atr_14": atr,
                "ema_20": ema_20,
                "ema_50": ema_50,
            },
        )
    return pd.DataFrame(records)


def _force_flip(*, to_bullish: bool) -> list[float]:
    """Build closes that end with a SuperTrend direction flip on the last bar."""
    service = SuperTrendService(atr_period=ATR_PERIOD, multiplier=MULTIPLIER)
    if to_bullish:
        closes = [150.0 - i for i in range(30)]
        shock = 5.0
        for _ in range(40):
            closes.append(closes[-1] + shock)
            shock *= 1.35
            frame = _ohlc_frame(closes)
            computed = service.compute(frame)
            if (
                float(computed["direction"].iloc[-2]) < 0
                and float(computed["direction"].iloc[-1]) > 0
            ):
                return closes
    else:
        closes = [50.0 + i for i in range(30)]
        shock = 5.0
        for _ in range(40):
            closes.append(max(closes[-1] - shock, 1.0))
            shock *= 1.35
            frame = _ohlc_frame(closes)
            computed = service.compute(frame)
            if (
                float(computed["direction"].iloc[-2]) > 0
                and float(computed["direction"].iloc[-1]) < 0
            ):
                return closes
    raise AssertionError("Unable to synthesize SuperTrend flip series")


def steady_uptrend() -> list[float]:
    return [100 + i * 0.8 for i in range(40)]


def steady_downtrend() -> list[float]:
    return [130 - i * 0.8 for i in range(40)]


@pytest.fixture
def config() -> SuperTrendStrategyConfig:
    return SuperTrendStrategyConfig(
        symbol="RELIANCE",
        atr_period=ATR_PERIOD,
        atr_multiplier=MULTIPLIER,
        relative_volume_threshold=1.5,
        min_atr=0.5,
        min_history_bars=30,
    )


def build_strategy(
    config: SuperTrendStrategyConfig,
    *,
    trend: TrendDirection = TrendDirection.BULLISH,
) -> SuperTrendStrategy:
    service = SuperTrendService(
        atr_period=config.atr_period,
        multiplier=config.atr_multiplier,
    )
    return SuperTrendStrategy(
        config,
        supertrend_service=service,
        market_structure=make_structure(trend),
    )


def test_bullish_trend() -> None:
    frame = _ohlc_frame(steady_uptrend())
    snap = SuperTrendService(atr_period=ATR_PERIOD, multiplier=MULTIPLIER).snapshot(frame)
    assert snap.bullish is True
    assert snap.close_above is True


def test_bearish_trend() -> None:
    frame = _ohlc_frame(steady_downtrend())
    snap = SuperTrendService(atr_period=ATR_PERIOD, multiplier=MULTIPLIER).snapshot(frame)
    assert snap.bearish is True
    assert snap.close_below is True


def test_trend_flip(config: SuperTrendStrategyConfig) -> None:
    bullish_closes = _force_flip(to_bullish=True)
    frame = _ohlc_frame(bullish_closes, rvol=2.0, ema_bullish=True)
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.BUY
    setup = strategy.last_setup
    assert setup is not None
    assert setup.trend_flip_bullish is True

    bearish_closes = _force_flip(to_bullish=False)
    frame = _ohlc_frame(bearish_closes, rvol=1.2, ema_bullish=False)
    strategy = build_strategy(config, trend=TrendDirection.BEARISH)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.SELL
    setup = strategy.last_setup
    assert setup is not None
    assert setup.trend_flip_bearish is True


def test_low_volume(config: SuperTrendStrategyConfig) -> None:
    frame = _ohlc_frame(_force_flip(to_bullish=True), rvol=0.8, ema_bullish=True)
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert "volume" in signal.reason.lower()


def test_false_signal(config: SuperTrendStrategyConfig) -> None:
    frame = _ohlc_frame(_force_flip(to_bullish=True), rvol=2.0, ema_bullish=True)
    strategy = build_strategy(config, trend=TrendDirection.SIDEWAYS)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert "false signal" in signal.reason.lower() or "sideways" in signal.reason.lower()


def test_trade_plan_generation(config: SuperTrendStrategyConfig) -> None:
    frame = _ohlc_frame(_force_flip(to_bullish=True), rvol=2.0, ema_bullish=True)
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    prepared = strategy.prepare(frame)
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.BUY

    plan = strategy.generate_trade_plan(prepared, signal)
    detailed = strategy.last_detailed_plan
    assert detailed is not None
    assert plan.strategy_name == "supertrend"
    assert plan.entry_price == pytest.approx(float(prepared.iloc[-1]["close"]))
    assert plan.signal is SignalType.BUY
    assert plan.stop_loss < plan.entry_price < plan.take_profit_1
    assert plan.take_profit_2 >= plan.take_profit_1
    assert plan.risk_reward == pytest.approx(2.0)
    assert 0.0 < plan.confidence <= 1.0
    assert plan.reasons
    assert detailed.trend_direction is TrendDirection.BULLISH
    assert detailed.stop_source is SuperTrendStopSource.SUPERTREND
    assert "5–25" in detailed.holding_note
    assert detailed.confidence_breakdown.total > 0


def test_indicator_adapter_aliases() -> None:
    frame = _ohlc_frame(steady_uptrend())
    attached = SuperTrendService(atr_period=ATR_PERIOD, multiplier=MULTIPLIER).attach(frame)
    adapter = IndicatorAdapter(attached)
    st = adapter.indicator("supertrend")
    direction = adapter.indicator("supertrend_direction")
    assert st.latest_value is not None
    assert direction.latest_value in {1.0, -1.0}


def test_exit_engine_reexport_matches_service() -> None:
    from app.exit_engine.supertrend import compute_supertrend as exit_compute

    frame = _ohlc_frame(steady_uptrend())
    a = compute_supertrend(
        frame["high"], frame["low"], frame["close"], period=ATR_PERIOD, multiplier=MULTIPLIER,
    )
    b = exit_compute(
        frame["high"], frame["low"], frame["close"], period=ATR_PERIOD, multiplier=MULTIPLIER,
    )
    pd.testing.assert_frame_equal(a, b)


def test_registry_integration(config: SuperTrendStrategyConfig) -> None:
    frame = _ohlc_frame(_force_flip(to_bullish=True), rvol=2.0, ema_bullish=True)
    registry = StrategyRegistry()
    register_supertrend_strategy(
        registry,
        config,
        market_structure=make_structure(TrendDirection.BULLISH),
    )
    plan = StrategyRunner().run(frame, registry.get("supertrend"))
    assert plan.strategy_name == "supertrend"
    assert plan.signal is SignalType.BUY
