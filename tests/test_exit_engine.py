"""Unit tests for the exit engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.exit_engine import (
    ExitAction,
    ExitConfig,
    ExitEngine,
    ExitMethod,
    TradeDirection,
    make_state,
)
from app.exit_engine.supertrend import compute_supertrend
from app.feature_engine.pipeline import FeaturePipeline
from app.feature_engine.strategy_frame import merge_ohlcv_features
from tests.test_indicators import make_prices


def make_market(
    *,
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    atr: float | None = 2.0,
    ema: float | None = None,
) -> pd.DataFrame:
    n = len(closes)
    if highs is None:
        highs = [close + 1.0 for close in closes]
    if lows is None:
        lows = [close - 1.0 for close in closes]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1_000] * n,
        },
    )
    if atr is not None:
        frame["atr_14"] = atr
    if ema is not None:
        frame["ema_21"] = ema
    return frame


@pytest.fixture
def engine() -> ExitEngine:
    return ExitEngine(
        ExitConfig(
            take_profit=110.0,
            initial_stop=95.0,
            atr_multiplier=1.5,
            trailing_atr_multiplier=1.5,
            break_even_trigger_r=1.0,
            partial_trigger_r=1.0,
            partial_fraction=0.5,
            max_bars=10,
            ema_column="ema_21",
        ),
    )


def test_hold_when_nothing_triggers(engine: ExitEngine) -> None:
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction="LONG",
            bars_held=2,
            extreme_high=102.0,
            extreme_low=99.0,
        ),
        market=make_market(closes=[100, 101, 102], ema=99.0),
        config=engine.config.model_copy(
            update={
                "enabled_methods": (
                    ExitMethod.FIXED_TARGET,
                    ExitMethod.EMA_EXIT,
                    ExitMethod.TIME_EXIT,
                ),
                "take_profit": 120.0,
            },
        ),
    )

    assert decision.decision is ExitAction.HOLD
    assert decision.exit_price is None
    assert "No exit conditions" in decision.reason


def test_fixed_target_exit(engine: ExitEngine) -> None:
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=3,
            extreme_high=111.0,
            extreme_low=99.0,
        ),
        market=make_market(closes=[100, 105, 111], highs=[101, 106, 111.5]),
        config=engine.config.model_copy(
            update={"enabled_methods": (ExitMethod.FIXED_TARGET,), "take_profit": 110.0},
        ),
    )

    assert decision.decision is ExitAction.FULL_EXIT
    assert decision.method is ExitMethod.FIXED_TARGET
    assert decision.exit_price == pytest.approx(110.0)
    assert "Fixed target" in decision.reason


def test_atr_exit(engine: ExitEngine) -> None:
    # ATR=2, mult=1.5 => long exit at 100-3=97
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=2,
            extreme_high=101.0,
            extreme_low=96.0,
        ),
        market=make_market(closes=[100, 99, 96.5], atr=2.0),
        config=engine.config.model_copy(update={"enabled_methods": (ExitMethod.ATR_EXIT,)}),
    )

    assert decision.decision is ExitAction.FULL_EXIT
    assert decision.method is ExitMethod.ATR_EXIT
    assert decision.exit_price == pytest.approx(97.0)


def test_ema_exit(engine: ExitEngine) -> None:
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=2,
            extreme_high=103.0,
            extreme_low=98.0,
        ),
        market=make_market(closes=[100, 101, 99.0], ema=100.0),
        config=engine.config.model_copy(update={"enabled_methods": (ExitMethod.EMA_EXIT,)}),
    )

    assert decision.decision is ExitAction.FULL_EXIT
    assert decision.method is ExitMethod.EMA_EXIT
    assert decision.exit_price == pytest.approx(99.0)


def test_trailing_stop_exit(engine: ExitEngine) -> None:
    # extreme_high=110, atr=2*1.5=3 => stop=107; close=106 triggers
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=5,
            extreme_high=110.0,
            extreme_low=99.0,
        ),
        market=make_market(closes=[100, 110, 106], atr=2.0),
        config=engine.config.model_copy(update={"enabled_methods": (ExitMethod.TRAILING_STOP,)}),
    )

    assert decision.decision is ExitAction.FULL_EXIT
    assert decision.method is ExitMethod.TRAILING_STOP
    assert decision.exit_price == pytest.approx(107.0)


def test_break_even_exit(engine: ExitEngine) -> None:
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=4,
            extreme_high=106.0,
            extreme_low=99.0,
            break_even_armed=True,
        ),
        market=make_market(
            closes=[100, 105, 101, 99.5],
            highs=[101, 106, 102, 100.5],
            lows=[99, 104, 100, 99.0],
            atr=2.0,
        ),
        config=engine.config.model_copy(update={"enabled_methods": (ExitMethod.BREAK_EVEN,)}),
    )

    assert decision.decision is ExitAction.FULL_EXIT
    assert decision.method is ExitMethod.BREAK_EVEN
    assert decision.exit_price == pytest.approx(100.0)


def test_partial_exit(engine: ExitEngine) -> None:
    # 1R long trigger at 105 with stop 95
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=3,
            extreme_high=106.0,
            extreme_low=99.0,
        ),
        market=make_market(closes=[100, 104, 105.5], highs=[101, 105, 106]),
        config=engine.config.model_copy(update={"enabled_methods": (ExitMethod.PARTIAL_EXIT,)}),
    )

    assert decision.decision is ExitAction.PARTIAL_EXIT
    assert decision.method is ExitMethod.PARTIAL_EXIT
    assert decision.exit_fraction == pytest.approx(0.5)
    assert decision.exit_price == pytest.approx(105.0)


def test_time_exit(engine: ExitEngine) -> None:
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=10,
            extreme_high=103.0,
            extreme_low=99.0,
        ),
        market=make_market(closes=[100, 101, 102]),
        config=engine.config.model_copy(
            update={"enabled_methods": (ExitMethod.TIME_EXIT,), "max_bars": 10},
        ),
    )

    assert decision.decision is ExitAction.FULL_EXIT
    assert decision.method is ExitMethod.TIME_EXIT
    assert decision.exit_price == pytest.approx(102.0)


def test_supertrend_exit_on_bearish_flip() -> None:
    # Strong up then sharp down to force SuperTrend flip.
    closes = [100 + i for i in range(30)] + [125, 120, 110, 100, 90]
    highs = [close + 1 for close in closes]
    lows = [close - 1 for close in closes]
    market = make_market(closes=closes, highs=highs, lows=lows, atr=None)
    # Attach real ATR from feature pipeline-compatible true range path via supertrend internal.
    engine = ExitEngine(
        ExitConfig(
            enabled_methods=(ExitMethod.SUPERTREND_EXIT,),
            supertrend_period=7,
            supertrend_multiplier=2.0,
        ),
    )
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=len(closes) - 1,
            extreme_high=max(highs),
            extreme_low=min(lows),
        ),
        market=market,
    )

    st = compute_supertrend(market["high"], market["low"], market["close"], period=7, multiplier=2.0)
    if float(st["direction"].iloc[-1]) < 0:
        assert decision.decision is ExitAction.FULL_EXIT
        assert decision.method is ExitMethod.SUPERTREND_EXIT
    else:
        assert decision.decision is ExitAction.HOLD


def test_priority_prefers_time_over_target(engine: ExitEngine) -> None:
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.LONG,
            bars_held=10,
            extreme_high=112.0,
            extreme_low=99.0,
        ),
        market=make_market(closes=[100, 110, 111], highs=[101, 111, 112]),
        config=engine.config.model_copy(
            update={
                "enabled_methods": (ExitMethod.TIME_EXIT, ExitMethod.FIXED_TARGET),
                "max_bars": 10,
                "take_profit": 110.0,
            },
        ),
    )

    assert decision.method is ExitMethod.TIME_EXIT


def test_short_fixed_target(engine: ExitEngine) -> None:
    decision = engine.evaluate(
        state=make_state(
            entry_price=100.0,
            direction=TradeDirection.SHORT,
            bars_held=2,
            extreme_high=101.0,
            extreme_low=89.0,
        ),
        market=make_market(
            closes=[100, 95, 89],
            highs=[101, 96, 90],
            lows=[99, 94, 88.5],
        ),
        config=engine.config.model_copy(
            update={"enabled_methods": (ExitMethod.FIXED_TARGET,), "take_profit": 90.0},
        ),
    )

    assert decision.decision is ExitAction.FULL_EXIT
    assert decision.exit_price == pytest.approx(90.0)


def test_works_with_feature_pipeline_columns() -> None:
    ohlcv = make_prices(80)
    features = FeaturePipeline().transform(ohlcv)
    market = merge_ohlcv_features(ohlcv, features)
    engine = ExitEngine(
        ExitConfig(
            enabled_methods=(ExitMethod.EMA_EXIT, ExitMethod.ATR_EXIT),
            take_profit=None,
            initial_stop=None,
        ),
    )
    decision = engine.evaluate(
        state=make_state(
            entry_price=float(ohlcv.iloc[-5]["close"]),
            direction=TradeDirection.LONG,
            bars_held=5,
            extreme_high=float(ohlcv["high"].iloc[-5:].max()),
            extreme_low=float(ohlcv["low"].iloc[-5:].min()),
        ),
        market=market,
    )

    assert decision.decision in {ExitAction.HOLD, ExitAction.FULL_EXIT}
    assert decision.reason
    assert isinstance(decision.signals, list)


def test_supertrend_helper_returns_columns() -> None:
    close = pd.Series(np.linspace(100, 120, 40))
    high = close + 1
    low = close - 1
    result = compute_supertrend(high, low, close, period=10, multiplier=3.0)

    assert set(result.columns) == {"supertrend", "direction"}
    assert len(result) == 40
    assert result["direction"].iloc[-1] in {-1.0, 1.0}
