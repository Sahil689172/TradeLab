"""Tests for strategy validation framework and CLI wiring."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.trade_recommendation import (
    StrategyValidationFramework,
    known_strategy_aliases,
)
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.models import SignalType


def synthetic_features(*, bars: int = 80) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-02 09:15")
    rows = []
    price = 100.0
    for index in range(bars):
        # Craft a late bullish EMA cross for ema_trend when possible
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
                "date": start + pd.Timedelta(minutes=15 * index),
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
            },
        )
    return pd.DataFrame(rows)


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


def test_validate_ema_strategy_row() -> None:
    framework = StrategyValidationFramework(timeframe="15 Minute")
    strategy = EMATrendStrategy(EMATrendConfig(symbol="RELIANCE", adx_threshold=20.0))
    row = framework.validate_strategy(strategy, synthetic_features())
    assert row.strategy == "ema_trend"
    assert row.status in {"PASS", "FAIL"}
    assert row.signals_generated in {0, 1}
    if row.status == "PASS":
        assert row.buy_count + row.sell_count + row.hold_count + row.exit_count == 1
        assert row.average_confidence >= 0.0


def test_validate_many_report() -> None:
    framework = StrategyValidationFramework()
    report = framework.validate_many(
        synthetic_features(),
        strategy_names=["ema"],
        symbol="RELIANCE",
    )
    assert report.symbol == "RELIANCE"
    assert len(report.rows) == 1
    text = framework.format_report(report)
    assert "Strategy Validation Report" in text
    assert "ema_trend" in text


def test_cli_module_importable() -> None:
    # Ensure the CLI script is importable as a path-run module pattern
    from pathlib import Path
    import runpy

    script = Path("backend/scripts/validate_strategies.py")
    assert script.exists()
    # Smoke: parse_args path exists via loading namespace without executing main
    ns = runpy.run_path(str(script), run_name="not_main")
    assert "parse_args" in ns
    assert "synthetic_features" in ns
    frame = ns["synthetic_features"](bars=40, symbol="TEST")
    assert len(frame) == 40
    assert frame.iloc[-1]["close"] > 0
