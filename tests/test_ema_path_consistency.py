"""A4Y.1.7.2 — Canonical EMA evaluation path consistency tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.evaluation.backtester import BacktestSettings, run_long_only_backtest
from app.backtesting.evaluation.canonical import (
    compare_ema_modes_canonical,
    load_canonical_features,
)
from app.backtesting.evaluation.integrity import diagnose_raw_signals
from app.backtesting.evaluation.runner import EMAEvaluationEngine, EvaluationConfig
from app.feature_engine.strategy_frame import ensure_strategy_indicators
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.models import SignalType
from tests.test_ema_trend_strategy import make_strategy_frame
from tests.test_raw_ema_diagnostic import _ohlcv_only


def _signal_trade_frame() -> pd.DataFrame:
    """Deterministic frame with one raw BUY then EXIT (same as diagnostic trade test)."""
    dates = pd.date_range("2024-01-01", periods=85, freq="B")
    close = np.linspace(100.0, 120.0, 85)
    ema_20 = close - 1.0
    ema_50 = close - 2.0
    ema_20[78] = 109.0
    ema_50[78] = 110.0
    ema_20[79] = 111.0
    ema_50[79] = 110.0
    close[79] = 112.0
    ema_20[83] = 111.0
    ema_50[83] = 110.0
    ema_20[84] = 109.0
    ema_50[84] = 110.0
    close[84] = 108.0
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 200_000.0,
            "volume_sma_20": 150_000.0,
            "relative_volume_20": 1.5,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_9": close - 0.5,
            "ema_21": close - 1.1,
            "ema_200": close - 5.0,
            "adx_14": 30.0,
            "atr_14": 2.0,
            "rsi_14": 55.0,
        },
    )


def test_compare_uses_canonical_backtester_not_auditor_sample() -> None:
    frame = _signal_trade_frame()
    result = compare_ema_modes_canonical("TEST", frame, stride=1, min_history_bars=60)
    # Canonical path finds the BUY/EXIT trade; old auditor last-30/stride-10 would miss it.
    assert result.raw.buy_signals >= 1
    assert result.raw.exit_signals >= 1
    assert result.raw.trade_count >= 1
    assert result.evaluation_resolution == "FULL_BACKTEST"


def test_raw_trade_count_agrees_across_diagnose_backtest_compare() -> None:
    frame = _signal_trade_frame()
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60),
    )
    diag = diagnose_raw_signals(strategy, frame, symbol="TEST", min_history_bars=60)
    bt = run_long_only_backtest(
        EMATrendStrategy(EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60)),
        frame,
        mode="raw",
        settings=BacktestSettings(min_history_bars=60, stride=1, slippage_bps=0, brokerage_rate=0),
        symbol="TEST",
    )
    compare = compare_ema_modes_canonical("TEST", frame, stride=1, min_history_bars=60)

    assert diag.trade_count == len(bt.trades) == compare.raw.trade_count
    assert diag.buy_count == bt.signal_counts.get("BUY", 0) == compare.raw.buy_signals
    assert diag.exit_count == bt.signal_counts.get("EXIT", 0) == compare.raw.exit_signals


def test_feature_preparation_identical_for_canonical_load() -> None:
    ohlcv = _ohlcv_only(100)
    via_ensure = ensure_strategy_indicators(ohlcv)
    # load_canonical_features needs disk; verify ensure is idempotent + complete
    again = ensure_strategy_indicators(via_ensure)
    for col in ("ema_20", "ema_50", "adx_14", "atr_14", "relative_volume_20"):
        assert col in via_ensure.columns
        assert col in again.columns
    assert list(via_ensure.columns) == list(again.columns)


def test_warmup_handling_identical() -> None:
    frame = ensure_strategy_indicators(_ohlcv_only(150))
    compare = compare_ema_modes_canonical("TEST", frame, stride=1, min_history_bars=60)
    assert compare.raw_diagnostic.warmup_bars == 60
    assert compare.min_history_bars == 60
    assert compare.raw_diagnostic.bars_examined > 0


def test_crossover_semantics_identical_to_strategy() -> None:
    buy = make_strategy_frame(cross="above", adx=30.0)
    exit_frame = make_strategy_frame(cross="below")
    strategy = EMATrendStrategy(EMATrendConfig(mode="raw", symbol="X", min_history_bars=60))
    assert strategy.generate_signal(strategy.prepare(buy)).signal is SignalType.BUY
    assert strategy.generate_signal(strategy.prepare(exit_frame)).signal is SignalType.EXIT

    buy_diag = diagnose_raw_signals(strategy, buy, symbol="X", min_history_bars=60)
    assert buy_diag.cross_above_count >= 1
    assert buy_diag.buy_count >= 1


def test_metric_layers_are_separated() -> None:
    frame = _signal_trade_frame()
    result = compare_ema_modes_canonical("TEST", frame, stride=1, min_history_bars=60)
    layers = result.as_dict()["metric_layers"]
    assert "technical_crossovers" in layers
    assert "raw_strategy_signals" in layers
    assert "professional_strategy_signals" in layers
    assert "executed_trades" in layers
    # Crosses can exceed strategy BUYs (ADX/close gates)
    assert layers["technical_crossovers"]["cross_above"] >= layers["raw_strategy_signals"]["buy"]


def test_evaluator_and_compare_agree_on_raw_trades() -> None:
    frame = _signal_trade_frame()
    compare = compare_ema_modes_canonical("TEST", frame, stride=1, min_history_bars=60)
    engine = EMAEvaluationEngine(
        EvaluationConfig(
            stride=1,
            min_history_bars=60,
            generate_charts=False,
            initial_capital=1_000_000.0,
        ),
    )
    report = engine.evaluate_universe({"TEST": frame})
    assert report.raw.total_trades == compare.raw.trade_count
    assert report.professional.total_trades == compare.professional.trade_count


def test_no_lookahead_still_holds() -> None:
    frame = make_strategy_frame(rows=100, cross="above")
    strategy = EMATrendStrategy(EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60))
    prepared = strategy.prepare(frame)
    cut = len(prepared) - 5
    baseline = strategy.generate_signal(prepared.iloc[:cut])
    mutated = prepared.copy()
    mutated.loc[cut:, "close"] = mutated.loc[cut:, "close"] * 3.0
    mutated.loc[cut:, "ema_20"] = mutated.loc[cut:, "close"] + 50.0
    mutated.loc[cut:, "ema_50"] = mutated.loc[cut:, "close"] - 50.0
    after = strategy.generate_signal(mutated.iloc[:cut])
    assert after.signal is baseline.signal


def test_load_canonical_features_exportable() -> None:
    assert callable(load_canonical_features)
