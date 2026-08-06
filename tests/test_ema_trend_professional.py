"""Unit tests for Phase A4Y.1 Professional EMA Strategy Upgrade."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.evaluation.backtester import (
    BacktestSettings,
    run_long_only_backtest,
)
from app.strategies.ema_trend import (
    EMATrendConfig,
    EMATrendStrategy,
    RejectionFilter,
    SignalFunnel,
    atr_stop_price,
    atr_trailing_stop_price,
)
from app.strategies.ema_trend.diagnostics import format_buy_sell_funnels
from app.strategy_engine import SignalType, StrategyRunner
from app.strategy_engine.audit import aggregate_metrics, audit_from_plans, format_signal_funnel
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import TradePlan


def make_professional_frame(
    *,
    rows: int = 80,
    cross: str = "above",
    adx: float = 30.0,
    close_vs_ema200: str = "above",
    relative_volume: float = 1.5,
    fast_col: str = "ema_9",
    slow_col: str = "ema_21",
) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    close = np.linspace(100.0, 120.0, rows)
    ema_fast = close - 0.5
    ema_slow = close - 1.5
    ema_200 = close - 5.0

    if cross == "above":
        ema_fast[-2] = 109.0
        ema_slow[-2] = 110.0
        ema_fast[-1] = 111.0
        ema_slow[-1] = 110.0
        close[-1] = 112.0
    elif cross == "below":
        ema_fast[-2] = 111.0
        ema_slow[-2] = 110.0
        ema_fast[-1] = 109.0
        ema_slow[-1] = 110.0
        close[-1] = 108.0
    else:
        ema_fast[-2] = 111.0
        ema_slow[-2] = 110.0
        ema_fast[-1] = 112.0
        ema_slow[-1] = 110.5
        close[-1] = 113.0

    if close_vs_ema200 == "below":
        ema_200[-1] = close[-1] + 2.0
    else:
        ema_200[-1] = close[-1] - 2.0

    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(rows, 200_000.0),
            "volume_sma_20": np.full(rows, 100_000.0),
            "relative_volume_20": relative_volume,
            fast_col: ema_fast,
            slow_col: ema_slow,
            "ema_20": close - 1.0,
            "ema_50": close - 2.0,
            "ema_200": ema_200,
            "adx_14": adx,
            "atr_14": 2.0,
            "rsi_14": 55.0,
        },
    )


@pytest.fixture
def pro_strategy() -> EMATrendStrategy:
    return EMATrendStrategy(
        EMATrendConfig.professional(symbol="RELIANCE", min_history_bars=60),
    )


def test_true_crossover_buy(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="above")
    signal = pro_strategy.generate_signal(pro_strategy.prepare(frame))
    assert signal.signal is SignalType.BUY
    assert pro_strategy.last_funnel.raw_buy == 1
    assert pro_strategy.last_funnel.final_buy == 1


def test_true_crossover_sell(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="below", close_vs_ema200="below")
    # For SELL, close must be below EMA200
    signal = pro_strategy.generate_signal(pro_strategy.prepare(frame))
    assert signal.signal is SignalType.SELL
    assert pro_strategy.last_funnel.raw_sell == 1
    assert pro_strategy.last_funnel.final_sell == 1


def test_no_duplicate_buy(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="above")
    prepared = pro_strategy.prepare(frame)
    first = pro_strategy.generate_signal(prepared)
    second = pro_strategy.generate_signal(prepared)
    assert first.signal is SignalType.BUY
    assert second.signal is SignalType.HOLD
    assert any(r.rejected_by is RejectionFilter.DUPLICATE for r in pro_strategy.last_rejections)


def test_sell_exit_never_suppressed(pro_strategy: EMATrendStrategy) -> None:
    """A4Y.1.6 #1: SELL is an exit — never blocked by duplicate suppression."""
    frame = make_professional_frame(cross="below", close_vs_ema200="below")
    prepared = pro_strategy.prepare(frame)
    first = pro_strategy.generate_signal(prepared)
    second = pro_strategy.generate_signal(prepared)
    assert first.signal is SignalType.SELL
    # Repeated exits are always allowed (harmless when already flat).
    assert second.signal is SignalType.SELL
    assert not any(
        r.rejected_by is RejectionFilter.DUPLICATE for r in pro_strategy.last_rejections
    )


def test_sell_exit_bypasses_ema200(pro_strategy: EMATrendStrategy) -> None:
    """A4Y.1.6 #1/#3: EMA200 must never block an exit (close ABOVE EMA200)."""
    frame = make_professional_frame(cross="below", close_vs_ema200="above")
    signal = pro_strategy.generate_signal(pro_strategy.prepare(frame))
    assert signal.signal is SignalType.SELL
    assert pro_strategy.last_funnel.final_sell == 1
    assert pro_strategy.last_funnel.rejected_ema200 == 0


def test_no_signal_without_true_cross(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="none")
    signal = pro_strategy.generate_signal(pro_strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert pro_strategy.last_funnel.raw_buy == 0
    assert pro_strategy.last_funnel.raw_sell == 0


def test_ema200_filter_blocks_buy(pro_strategy: EMATrendStrategy) -> None:
    # >= 200 bars so the EMA200 warm-up guard (A4Y.1.6 #5) is satisfied.
    frame = make_professional_frame(rows=210, cross="above", close_vs_ema200="below")
    signal = pro_strategy.generate_signal(pro_strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert pro_strategy.last_funnel.rejected_ema200 == 1
    assert pro_strategy.last_rejections[0].rejected_by is RejectionFilter.EMA200
    assert pro_strategy.last_rejections[0].symbol == "RELIANCE"


def test_adx_filter_blocks(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="above", adx=20.0)
    signal = pro_strategy.generate_signal(pro_strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert pro_strategy.last_funnel.rejected_adx == 1


def test_volume_filter_blocks(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="above", relative_volume=0.8)
    frame["volume"] = 50_000.0
    frame["volume_sma_20"] = 100_000.0
    signal = pro_strategy.generate_signal(pro_strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert pro_strategy.last_funnel.rejected_volume == 1


def test_confirm_on_close(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="above")
    prepared = pro_strategy.prepare(frame)
    prepared.attrs["bar_closed"] = False
    signal = pro_strategy.generate_signal(prepared)
    assert signal.signal is SignalType.HOLD
    assert any(
        r.rejected_by is RejectionFilter.CONFIRM_ON_CLOSE
        for r in pro_strategy.last_rejections
    )


def test_atr_stop_calculation() -> None:
    stop = atr_stop_price(entry=100.0, atr=2.0, multiplier=1.5, side=SignalType.BUY)
    assert stop == pytest.approx(97.0)
    stop_short = atr_stop_price(entry=100.0, atr=2.0, multiplier=1.5, side=SignalType.SELL)
    assert stop_short == pytest.approx(103.0)


def test_atr_trailing_stop() -> None:
    trail = atr_trailing_stop_price(
        extreme=110.0,
        atr=2.0,
        multiplier=1.5,
        side=SignalType.BUY,
    )
    assert trail == pytest.approx(107.0)


def test_professional_trade_plan_atr_multiplier(pro_strategy: EMATrendStrategy) -> None:
    frame = make_professional_frame(cross="above")
    plan = StrategyRunner().run(frame, pro_strategy, apply_filters=False)
    assert plan.signal is SignalType.BUY
    atr = 2.0
    assert plan.stop_loss == pytest.approx(plan.entry_price - 1.5 * atr)
    assert any("Mode: professional" in r for r in plan.reasons)


def test_configuration_loading_professional() -> None:
    cfg = EMATrendConfig.model_validate(
        {
            "mode": "professional",
            "fast_ema": 9,
            "slow_ema": 21,
            "confirm_on_close": True,
            "trend_filter": True,
            "ema200_filter": True,
            "adx_filter": True,
            "adx_threshold": 25,
            "volume_filter": True,
            "relative_volume": 1.2,
            "atr_stop": True,
            "atr_multiplier": 1.5,
            "atr_trailing": False,
            "symbol": "TCS",
        },
    )
    assert cfg.mode == "professional"
    assert cfg.ema_fast_column == "ema_9"
    assert cfg.ema_slow_column == "ema_21"
    assert cfg.atr_stop_multiplier == pytest.approx(1.5)


def test_ema_pair_presets() -> None:
    for preset, (fast, slow) in {
        "9_21": (9, 21),
        "12_26": (12, 26),
        "20_50": (20, 50),
        "50_200": (50, 200),
    }.items():
        cfg = EMATrendConfig(mode="professional", ema_pair_preset=preset, symbol="X")
        assert cfg.fast_ema == fast
        assert cfg.slow_ema == slow
        assert cfg.ema_fast_column == f"ema_{fast}"
        assert cfg.ema_slow_column == f"ema_{slow}"


def test_backwards_compatible_raw_defaults() -> None:
    """Raw mode keeps legacy EMA20/50 + EXIT on cross-below behaviour."""
    from tests.test_ema_trend_strategy import make_strategy_frame

    strategy = EMATrendStrategy(EMATrendConfig(symbol="RELIANCE"))
    assert strategy.config.mode == "raw"
    assert strategy.config.ema_fast_column == "ema_20"
    assert strategy.config.atr_stop_multiplier == pytest.approx(2.0)

    buy = strategy.generate_signal(strategy.prepare(make_strategy_frame(cross="above")))
    assert buy.signal is SignalType.BUY

    exit_sig = strategy.generate_signal(strategy.prepare(make_strategy_frame(cross="below")))
    assert exit_sig.signal is SignalType.EXIT

    plan = StrategyRunner().run(make_strategy_frame(cross="above"), strategy)
    assert plan.stop_loss == pytest.approx(plan.entry_price - 2.0 * 2.0)


def test_audit_funnel_statistics() -> None:
    plans = [
        TradePlan(
            symbol="RELIANCE",
            entry_price=100.0,
            signal=SignalType.BUY,
            stop_loss=97.0,
            take_profit_1=106.0,
            take_profit_2=109.0,
            holding_period=10,
            risk_reward=2.0,
            confidence=0.7,
            reasons=["unit"],
            strategy_name="ema_trend",
        ),
        TradePlan(
            symbol="RELIANCE",
            entry_price=100.0,
            signal=SignalType.HOLD,
            stop_loss=97.0,
            take_profit_1=106.0,
            take_profit_2=109.0,
            holding_period=10,
            risk_reward=2.0,
            confidence=0.2,
            reasons=["filtered"],
            strategy_name="ema_trend",
        ),
    ]
    metrics = audit_from_plans(
        strategy_name="ema_trend",
        symbol="RELIANCE",
        plans=plans,
        filter_integration_ok=True,
        funnel={
            "raw_buy": 3,
            "raw_sell": 1,
            "rejected_ema200": 1,
            "rejected_adx": 1,
            "rejected_volume": 0,
            "rejected_atr": 0,
            "rejected_other": 0,
            "final_buy": 1,
            "final_sell": 1,
        },
    )
    assert metrics.raw_buy_signals == 3
    assert metrics.rejected_ema200 == 1
    assert metrics.rejected_adx == 1
    assert metrics.final_buy_signals == 1
    assert metrics.funnel_acceptance_rate == pytest.approx(0.5)
    assert metrics.funnel_rejection_rate == pytest.approx(0.5)
    text = format_signal_funnel(metrics)
    assert "Raw BUY" in text
    assert "Rejected by EMA200" in text
    assert "Final BUY" in text


def test_aggregate_metrics_includes_funnel_defaults() -> None:
    metrics = aggregate_metrics(
        strategy_name="ema_trend",
        symbol="X",
        plans=[],
        filter_integration_ok=True,
    )
    assert metrics.raw_buy_signals == 0
    assert metrics.funnel_acceptance_rate == 0.0


# ---------------------------------------------------------------------------
# A4Y.1.6 – Professional EMA Root Cause Fixes
# ---------------------------------------------------------------------------


def make_multi_cross_frame(rows: int = 240) -> pd.DataFrame:
    """Oscillating EMAs that cross many times, close above EMA200 throughout."""
    dates = pd.date_range("2023-01-01", periods=rows, freq="B")
    t = np.arange(rows)
    ema_fast = 100.0 + 4.0 * np.sin(2 * np.pi * t / 20.0)
    ema_slow = 100.0 + 4.0 * np.sin(2 * np.pi * t / 20.0 - 0.8)
    close = ema_fast + 2.0
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(rows, 200_000.0),
            "volume_sma_20": np.full(rows, 100_000.0),
            "relative_volume_20": np.full(rows, 1.5),
            "ema_9": ema_fast,
            "ema_21": ema_slow,
            "ema_20": close - 1.0,
            "ema_50": close - 2.0,
            "ema_200": np.full(rows, 96.0),
            "adx_14": np.full(rows, 30.0),
            "atr_14": np.full(rows, 2.0),
            "rsi_14": np.full(rows, 55.0),
        },
    )


def test_duplicate_lock_resets_after_exit(pro_strategy: EMATrendStrategy) -> None:
    """A4Y.1.6 #2: after a SELL exit, a second BUY is allowed again."""
    buy_frame = pro_strategy.prepare(make_professional_frame(cross="above"))
    exit_frame = pro_strategy.prepare(
        make_professional_frame(cross="below", close_vs_ema200="above"),
    )

    first_buy = pro_strategy.generate_signal(buy_frame)
    exit_signal = pro_strategy.generate_signal(exit_frame)
    second_buy = pro_strategy.generate_signal(buy_frame)

    assert first_buy.signal is SignalType.BUY
    assert exit_signal.signal is SignalType.SELL
    assert second_buy.signal is SignalType.BUY  # no permanent duplicate lock


def test_ema200_warmup_skips_filter_before_200_bars() -> None:
    """A4Y.1.6 #5: EMA200 filter is skipped until >= 200 bars are available."""
    strat = EMATrendStrategy(
        EMATrendConfig.professional(symbol="X", min_history_bars=60),
    )
    # close BELOW ema200 would normally block a BUY, but warm-up skips the gate.
    frame = make_professional_frame(rows=120, cross="above", close_vs_ema200="below")
    signal = strat.generate_signal(strat.prepare(frame))
    assert signal.signal is SignalType.BUY
    assert strat.last_funnel.rejected_ema200 == 0


def test_professional_adx_default_threshold() -> None:
    """A4Y.1.6 #6: professional default ADX threshold is 20; raw stays 25."""
    assert EMATrendConfig.professional(symbol="X").adx_threshold == pytest.approx(20.0)
    assert EMATrendConfig(symbol="X").adx_threshold == pytest.approx(25.0)


def test_signal_funnel_buy_sell_separation() -> None:
    """A4Y.1.6 #4: BUY and SELL funnels are reported separately."""
    funnel = SignalFunnel(
        raw_buy=5,
        rejected_ema200=2,
        rejected_adx=1,
        final_buy=2,
        raw_sell=3,
        final_sell=3,
    )
    assert funnel.buy_acceptance_rate == pytest.approx(2 / 5)
    assert funnel.sell_exit_rate == pytest.approx(1.0)
    text = format_buy_sell_funnels(funnel)
    assert "BUY Funnel" in text
    assert "SELL Funnel" in text
    assert "never blocked" in text


def test_feature_validation_requires_volume_source() -> None:
    """A4Y.1.6 #7: meaningful diagnostic when volume features are missing."""
    strat = EMATrendStrategy(
        EMATrendConfig.professional(symbol="X", min_history_bars=60),
    )
    frame = make_professional_frame(rows=80).drop(
        columns=["volume", "volume_sma_20", "relative_volume_20"],
    )
    with pytest.raises(StrategyValidationError, match="volume feature"):
        strat.validate(frame)


def test_replay_no_permanent_lock() -> None:
    """A4Y.1.6: expanding-window replay yields multiple BUYs and SELL exits."""
    strat = EMATrendStrategy(
        EMATrendConfig.professional(symbol="RELIANCE", min_history_bars=60),
    )
    frame = make_multi_cross_frame(rows=240)
    buys = 0
    sells = 0
    for cut in range(60, len(frame) + 1):
        window = frame.iloc[:cut]
        signal = strat.generate_signal(strat.prepare(window))
        if signal.signal is SignalType.BUY:
            buys += 1
        elif signal.signal is SignalType.SELL:
            sells += 1
    assert buys > 1
    assert sells >= 1


def test_backtest_professional_produces_multiple_trades() -> None:
    """A4Y.1.6: professional backtest closes positions (trades > 1)."""
    strat = EMATrendStrategy(
        EMATrendConfig.professional(symbol="RELIANCE", min_history_bars=60),
    )
    frame = make_multi_cross_frame(rows=240)
    result = run_long_only_backtest(
        strat,
        frame,
        mode="professional",
        settings=BacktestSettings(min_history_bars=60),
        symbol="RELIANCE",
    )
    assert result.signal_counts.get("BUY", 0) > 1
    assert result.signal_counts.get("SELL", 0) >= 1
    assert len(result.trades) > 1
    # Exits close positions, so not everything is a forced "Replay End".
    assert any(t.exit_reason == "SELL" for t in result.trades)
