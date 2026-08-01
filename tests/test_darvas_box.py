"""Unit tests for Darvas Box engine and strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.strategy_engine.darvas import (
    DarvasBoxEngine,
    DarvasBoxEngineConfig,
    DarvasBoxState,
)
from app.strategies.darvas_box import (
    DarvasBoxStrategy,
    DarvasBoxStrategyConfig,
    DarvasStopSource,
    register_darvas_box_strategy,
)
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner


def _row(
    *,
    high: float,
    low: float,
    close: float,
    volume: float = 1_000.0,
    open_: float | None = None,
) -> dict[str, float]:
    return {
        "open": open_ if open_ is not None else (high + low) / 2.0,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def build_box_then(
    after_rows: list[dict[str, float]],
    *,
    confirm_bars: int = 3,
) -> pd.DataFrame:
    """Build a confirmed box [100, 110] then append scenario bars."""
    # Quiet lead-in so min_history is satisfied
    rows = [
        _row(high=102, low=100, close=101, volume=800 + i * 10)
        for i in range(6)
    ]
    # Top candidate at 110, then confirm_bars without higher high; low sinks to 100
    rows.extend(
        [
            _row(high=105, low=101, close=103, volume=900),
            _row(high=110, low=104, close=108, volume=950),  # box top
            _row(high=109, low=103, close=106, volume=980),
            _row(high=108, low=101, close=104, volume=1_000),
            _row(high=107, low=100, close=102, volume=1_020),  # box forms (lower=100)
            _row(high=108, low=101, close=105, volume=1_050),  # consolidation
        ],
    )
    rows.extend(after_rows)

    start = pd.Timestamp("2024-01-02")
    records = []
    for index, row in enumerate(rows):
        close = row["close"]
        records.append(
            {
                "date": start + pd.Timedelta(days=index),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": close,
                "volume": row["volume"],
                "ema_20": close * 1.01,
                "ema_50": close * 0.99,
                "atr_14": 1.5,
            },
        )
    frame = pd.DataFrame(records)
    assert confirm_bars == 3
    return frame


@pytest.fixture
def config() -> DarvasBoxStrategyConfig:
    return DarvasBoxStrategyConfig(
        symbol="RELIANCE",
        confirm_bars=3,
        min_box_bars=2,
        min_history_bars=10,
    )


def test_box_detection() -> None:
    frame = build_box_then(
        [_row(high=108, low=102, close=105, volume=1_100)],
    )
    snap = DarvasBoxEngine(DarvasBoxEngineConfig(confirm_bars=3)).detect(frame)
    assert snap.box is not None
    assert snap.box.upper == pytest.approx(110.0)
    assert snap.box.lower == pytest.approx(100.0)
    assert snap.state in {DarvasBoxState.CONSOLIDATION, DarvasBoxState.NEW_BOX}
    assert snap.consolidating or snap.state is DarvasBoxState.NEW_BOX


def test_breakout(config: DarvasBoxStrategyConfig) -> None:
    frame = build_box_then(
        [
            _row(high=112, low=108, close=111, volume=3_500),  # breakout + volume
        ],
    )
    strategy = DarvasBoxStrategy(config)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.BUY
    snap = strategy.last_box_snapshot
    assert snap is not None
    assert snap.breakout is True
    assert snap.state is DarvasBoxState.BREAKOUT


def test_false_breakout(config: DarvasBoxStrategyConfig) -> None:
    # Wick above box but close back inside → not a breakout signal
    frame = build_box_then(
        [
            _row(high=112, low=104, close=109, volume=3_500),
        ],
    )
    strategy = DarvasBoxStrategy(config)
    prepared = strategy.prepare(frame)
    snap = strategy.last_box_snapshot
    assert snap is not None
    assert snap.breakout is False
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.HOLD


def test_false_breakout_no_volume(config: DarvasBoxStrategyConfig) -> None:
    # Close above box but volume contracts → reject BUY
    frame = build_box_then(
        [
            _row(high=112, low=108, close=111, volume=800),  # lower than prior ~1050
        ],
    )
    strategy = DarvasBoxStrategy(config)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.HOLD
    assert "volume" in signal.reason.lower()


def test_trade_plan(config: DarvasBoxStrategyConfig) -> None:
    frame = build_box_then(
        [
            _row(high=112, low=108, close=111, volume=3_500),
        ],
    )
    strategy = DarvasBoxStrategy(config)
    plan = StrategyRunner().run(frame, strategy)
    detailed = strategy.last_detailed_plan

    assert plan.strategy_name == "darvas_box"
    assert plan.signal is SignalType.BUY
    assert plan.risk_reward == pytest.approx(2.0)
    assert plan.stop_loss < plan.entry_price < plan.take_profit_1
    assert detailed is not None
    assert detailed.current_box is not None
    assert detailed.current_box.upper == pytest.approx(110.0)
    assert detailed.stop_source is DarvasStopSource.LOWER_BOX
    assert detailed.stop_loss == pytest.approx(100.0)
    assert any("box" in reason.lower() for reason in plan.reasons)


def test_sell_breakdown(config: DarvasBoxStrategyConfig) -> None:
    frame = build_box_then(
        [
            _row(high=102, low=98, close=99, volume=2_000),
        ],
    )
    strategy = DarvasBoxStrategy(config)
    signal = strategy.generate_signal(strategy.prepare(frame))
    assert signal.signal is SignalType.SELL


def test_registry_integration(config: DarvasBoxStrategyConfig) -> None:
    frame = build_box_then(
        [_row(high=112, low=108, close=111, volume=3_500)],
    )
    registry = StrategyRegistry()
    register_darvas_box_strategy(registry, config)
    plan = StrategyRunner().run(frame, registry.get("darvas_box"))
    assert plan.signal is SignalType.BUY
