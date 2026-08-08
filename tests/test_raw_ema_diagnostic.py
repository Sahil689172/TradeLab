"""A4Y.1.7.1 — Raw EMA diagnostic / feature-prep tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.evaluation.backtester import BacktestSettings, run_long_only_backtest
from app.backtesting.evaluation.integrity import diagnose_raw_signals
from app.feature_engine.strategy_frame import ensure_strategy_indicators
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.models import SignalType
from tests.test_ema_trend_strategy import make_strategy_frame


def _ohlcv_only(rows: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=rows, freq="B")
    close = np.linspace(100.0, 140.0, rows) + np.sin(np.arange(rows) / 7.0) * 3.0
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(rows, 150_000.0),
        },
    )


def test_ensure_strategy_indicators_adds_ema_columns() -> None:
    frame = _ohlcv_only(100)
    assert "ema_20" not in frame.columns
    prepared = ensure_strategy_indicators(frame)
    assert "ema_20" in prepared.columns
    assert "ema_50" in prepared.columns
    assert "adx_14" in prepared.columns
    assert "atr_14" in prepared.columns
    assert "volume_sma_20" in prepared.columns


def test_diagnose_bars_examined_gt_zero_on_ohlcv_only() -> None:
    frame = ensure_strategy_indicators(_ohlcv_only(150))
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60),
    )
    diag = diagnose_raw_signals(strategy, frame, symbol="TEST", min_history_bars=60)
    assert diag.ema20_available is True
    assert diag.ema50_available is True
    assert diag.bars_examined > 0
    assert diag.warmup_bars == 60
    assert diag.first_valid_timestamp is not None
    assert diag.last_valid_timestamp is not None
    assert "prepare failed" not in " ".join(diag.notes)


def test_known_crossover_produces_buy() -> None:
    frame = make_strategy_frame(cross="above", adx=30.0, close_vs_slow="above")
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60),
    )
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.BUY

    diag = diagnose_raw_signals(strategy, frame, symbol="TEST", min_history_bars=60)
    assert diag.cross_above_count >= 1
    assert diag.buy_count >= 1


def test_known_reverse_crossover_produces_exit() -> None:
    frame = make_strategy_frame(cross="below")
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60),
    )
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.EXIT

    diag = diagnose_raw_signals(strategy, frame, symbol="TEST", min_history_bars=60)
    assert diag.cross_below_count >= 1
    assert diag.exit_count >= 1


def test_no_crossover_produces_hold() -> None:
    frame = make_strategy_frame(cross="none")
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60),
    )
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD


def test_future_data_cannot_affect_earlier_raw_signal() -> None:
    """Look-ahead guard: mutating bars after cut must not change signal at cut."""
    frame = make_strategy_frame(rows=100, cross="above")
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60),
    )
    prepared = strategy.prepare(frame)
    cut = len(prepared) - 5
    window = prepared.iloc[:cut]
    baseline = strategy.generate_signal(window)

    mutated = prepared.copy()
    # Corrupt only future rows (after cut)
    mutated.loc[cut:, "close"] = mutated.loc[cut:, "close"] * 3.0
    mutated.loc[cut:, "ema_20"] = mutated.loc[cut:, "close"] + 50.0
    mutated.loc[cut:, "ema_50"] = mutated.loc[cut:, "close"] - 50.0
    mutated.loc[cut:, "adx_14"] = 5.0

    after = strategy.generate_signal(mutated.iloc[:cut])
    assert after.signal is baseline.signal
    assert after.reason == baseline.reason


def test_diagnostic_processes_all_bars_after_warmup() -> None:
    rows = 200
    frame = ensure_strategy_indicators(_ohlcv_only(rows))
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="RELIANCE", min_history_bars=60),
    )
    diag = diagnose_raw_signals(
        strategy,
        frame,
        symbol="RELIANCE",
        min_history_bars=60,
        stride=1,
    )
    # After prepare() dropna, examined bars == prepared_len - warmup + 1
    prepared = strategy.prepare(frame)
    expected = len(prepared) - 60 + 1
    assert diag.bars_examined == expected
    assert diag.bars_examined > 0


def test_raw_evaluation_produces_trades_when_signals_exist() -> None:
    """When frame has a valid raw BUY then EXIT, backtester must form a trade."""
    # Build a longer walk: prefix history + buy bar + later exit bar
    dates = pd.date_range("2024-01-01", periods=85, freq="B")
    close = np.linspace(100.0, 120.0, 85)
    ema_20 = close - 1.0
    ema_50 = close - 2.0
    # Bar 79: cross above
    ema_20[78] = 109.0
    ema_50[78] = 110.0
    ema_20[79] = 111.0
    ema_50[79] = 110.0
    close[79] = 112.0
    # Bar 84: cross below
    ema_20[83] = 111.0
    ema_50[83] = 110.0
    ema_20[84] = 109.0
    ema_50[84] = 110.0
    close[84] = 108.0
    frame = pd.DataFrame(
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
            "adx_14": 30.0,
            "atr_14": 2.0,
            "rsi_14": 55.0,
        },
    )
    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60),
    )
    result = run_long_only_backtest(
        strategy,
        frame,
        mode="raw",
        settings=BacktestSettings(
            initial_capital=100_000.0,
            percent=95.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
            min_history_bars=60,
            stride=1,
        ),
        symbol="TEST",
    )
    assert result.signal_counts.get("BUY", 0) >= 1
    assert result.signal_counts.get("EXIT", 0) >= 1
    assert len(result.trades) >= 1

    diag = diagnose_raw_signals(strategy, frame, symbol="TEST", min_history_bars=60)
    assert diag.buy_count >= 1
    assert diag.exit_count >= 1
    assert diag.trade_count >= 1
