"""Tests for strategy validation framework and CLI wiring."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import runpy

from app.services.trade_recommendation import (
    StrategyValidationFramework,
    known_strategy_aliases,
)
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.symbols import attach_symbol, resolve_symbol_from_features


def synthetic_features(*, bars: int = 80, symbol: str = "RELIANCE") -> pd.DataFrame:
    sessions: list[pd.Timestamp] = []
    day = pd.Timestamp("2024-06-03 09:15")
    while len(sessions) < bars:
        for minute in range(0, 6 * 60, 15):
            sessions.append(day + pd.Timedelta(minutes=minute))
            if len(sessions) >= bars:
                break
        day = day + pd.Timedelta(days=1)
        while day.weekday() >= 5:
            day = day + pd.Timedelta(days=1)

    rows = []
    price = 100.0
    for index, ts in enumerate(sessions[:bars]):
        price = 100 + index * 0.3
        close = price
        if index < bars - 3:
            ema_20 = close - 1.0
            ema_50 = close + 1.0
        else:
            ema_20 = close + 1.0
            ema_50 = close - 1.0
        rows.append(
            {
                "date": ts,
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_500 + index * 10,
                "relative_volume_20": 2.0,
                "atr_14": 1.5,
                "ema_9": close,
                "ema_20": ema_20,
                "ema_21": ema_20,
                "ema_50": ema_50,
                "adx_14": 30.0,
                "rsi_14": 55.0,
                "vwap": close * 0.999,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def test_known_aliases() -> None:
    aliases = known_strategy_aliases()
    assert "ema" in aliases
    assert "donchian" in aliases
    assert "supertrend" in aliases


def test_resolve_ema_strategy() -> None:
    framework = StrategyValidationFramework()
    strategies = framework.resolve_strategies(["ema"])
    assert len(strategies) == 1
    assert strategies[0].name == "ema_trend"


def test_symbol_propagates_to_recommendation() -> None:
    framework = StrategyValidationFramework(timeframe="15 Minute")
    strategy = EMATrendStrategy(EMATrendConfig(adx_threshold=20.0))  # default UNKNOWN
    assert strategy.active_symbol == "UNKNOWN"
    row = framework.validate_strategy(
        strategy,
        synthetic_features(symbol="RELIANCE"),
        symbol="RELIANCE",
    )
    assert row.status == "PASS", row.validation_errors
    assert strategy.active_symbol == "RELIANCE"


def test_validate_ema_strategy_row() -> None:
    framework = StrategyValidationFramework(timeframe="15 Minute")
    strategy = EMATrendStrategy(EMATrendConfig(symbol="RELIANCE", adx_threshold=20.0))
    row = framework.validate_strategy(strategy, synthetic_features(), symbol="RELIANCE")
    assert row.strategy == "ema_trend"
    assert row.status == "PASS", row.validation_errors
    assert row.signals_generated == 1


def test_validate_many_report() -> None:
    framework = StrategyValidationFramework()
    report = framework.validate_many(
        synthetic_features(symbol="RELIANCE"),
        strategy_names=["ema"],
        symbol="RELIANCE",
    )
    assert report.symbol == "RELIANCE"
    assert len(report.rows) == 1
    assert report.failed == 0
    text = framework.format_report(report)
    assert "Strategy Validation Report" in text
    assert "ema_trend" in text


def test_cli_module_importable() -> None:
    script = Path("backend/scripts/validate_strategies.py")
    assert script.exists()
    ns = runpy.run_path(str(script), run_name="not_main")
    assert "parse_args" in ns
    assert "synthetic_features" in ns
    frame = ns["synthetic_features"](bars=40, symbol="TESTCO")
    assert len(frame) == 40
    assert resolve_symbol_from_features(frame) == "TESTCO"
    assert frame.iloc[-1]["close"] > 0
