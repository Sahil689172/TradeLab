"""Unit tests for Volume Breakout strategy and VolumeAnalysisService."""

from __future__ import annotations

import pandas as pd
import pytest

from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.services.strategy_engine.indicators import VolumeAnalysisService
from app.strategies.volume_breakout import (
    VolumeBreakoutConfig,
    VolumeBreakoutStrategy,
    register_volume_breakout_strategy,
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


def build_base_rows(
    *,
    n: int = 24,
    resistance: float = 100.5,
    support: float = 99.0,
    volume: float = 1_000.0,
) -> list[dict[str, float]]:
    """Quiet range below resistance / above support with rising volume."""
    rows: list[dict[str, float]] = []
    for index in range(n):
        close = 100.0 + (index % 5) * 0.05
        rows.append(
            {
                "open": close - 0.05,
                "high": min(resistance - 0.05, close + 0.15),
                "low": max(support + 0.05, close - 0.15),
                "close": close,
                "volume": volume + index * 20.0,  # rising → not decreasing
            },
        )
    return rows


def to_frame(rows: list[dict[str, float]]) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-02 09:15")
    records = []
    for index, row in enumerate(rows):
        records.append(
            {
                "date": start + pd.Timedelta(minutes=5 * index),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "atr_14": row.get("atr_14", 0.6),
            },
        )
    return pd.DataFrame(records)


def strong_breakout_frame(*, volume_mult: float = 3.5) -> pd.DataFrame:
    rows = build_base_rows()
    prior_vol = rows[-1]["volume"]
    rows.append(
        {
            "open": 100.4,
            "high": 101.4,
            "low": 100.3,
            "close": 101.2,  # breaks above ~100.45 resistance
            "volume": prior_vol * volume_mult,
            "atr_14": 0.6,
        },
    )
    return to_frame(rows)


def weak_volume_frame() -> pd.DataFrame:
    return strong_breakout_frame(volume_mult=1.05)


def false_breakout_weak_body_frame() -> pd.DataFrame:
    rows = build_base_rows()
    prior_vol = rows[-1]["volume"]
    rows.append(
        {
            "open": 101.05,
            "high": 101.3,
            "low": 100.2,
            "close": 101.1,  # breaks but tiny body vs range
            "volume": prior_vol * 3.0,
            "atr_14": 0.6,
        },
    )
    return to_frame(rows)


def bearish_breakdown_frame() -> pd.DataFrame:
    rows = build_base_rows(support=99.0)
    # Keep lows above support until last bar
    for row in rows:
        row["low"] = max(row["low"], 99.15)
        row["close"] = max(row["close"], 99.4)
    prior_vol = rows[-1]["volume"]
    rows.append(
        {
            "open": 99.5,
            "high": 99.6,
            "low": 98.4,
            "close": 98.6,  # breaks below ~99.15 support
            "volume": prior_vol * 3.5,
            "atr_14": 0.6,
        },
    )
    return to_frame(rows)


@pytest.fixture
def config() -> VolumeBreakoutConfig:
    return VolumeBreakoutConfig(
        symbol="RELIANCE",
        min_history_bars=20,
        resistance_lookback=20,
        relative_volume_threshold=1.8,
        min_body_ratio=0.45,
        max_session_bar_index=70,
    )


def build_strategy(
    config: VolumeBreakoutConfig,
    trend: TrendDirection,
) -> VolumeBreakoutStrategy:
    return VolumeBreakoutStrategy(
        config,
        market_structure=make_structure(trend),
    )


def test_strong_breakout(config: VolumeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(strong_breakout_frame()))
    assert signal.signal is SignalType.BUY
    assert signal.confidence > 0.5


def test_weak_volume(config: VolumeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(weak_volume_frame()))
    assert signal.signal is SignalType.HOLD
    assert "volume" in signal.reason.lower()


def test_false_breakout(config: VolumeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(false_breakout_weak_body_frame()))
    assert signal.signal is SignalType.HOLD
    assert "weak" in signal.reason.lower() or "false" in signal.reason.lower()


def test_bearish_breakdown(config: VolumeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BEARISH)
    signal = strategy.generate_signal(strategy.prepare(bearish_breakdown_frame()))
    assert signal.signal is SignalType.SELL


def test_trade_plan_generation(config: VolumeBreakoutConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    plan = StrategyRunner().run(strong_breakout_frame(), strategy)
    detailed = strategy.last_detailed_plan

    assert plan.strategy_name == "volume_breakout"
    assert plan.signal is SignalType.BUY
    assert plan.risk_reward == pytest.approx(2.0)
    assert plan.stop_loss < plan.entry_price < plan.take_profit_1
    assert any("volume" in reason.lower() for reason in plan.reasons)
    assert detailed is not None
    assert detailed.volume_stats.relative_volume_20 is not None
    assert detailed.volume_stats.relative_volume_20 > config.relative_volume_threshold
    assert detailed.volume_stats.above_average_20 is True


def test_volume_analysis_service() -> None:
    frame = strong_breakout_frame()
    service = VolumeAnalysisService(spike_multiple=1.8)
    attached = service.attach(frame)
    assert "relative_volume_20" in attached.columns
    assert "volume_sma_5" in attached.columns
    assert "volume_spike" in attached.columns
    stats = service.snapshot(attached)
    assert stats.volume > 0
    assert stats.relative_volume_20 is not None
    assert stats.spike is True or stats.relative_volume_20 >= 1.8


def test_registry_integration(config: VolumeBreakoutConfig) -> None:
    registry = StrategyRegistry()
    register_volume_breakout_strategy(
        registry,
        config,
        market_structure=make_structure(TrendDirection.BULLISH),
    )
    plan = StrategyRunner().run(
        strong_breakout_frame(),
        registry.get("volume_breakout"),
    )
    assert plan.signal is SignalType.BUY
