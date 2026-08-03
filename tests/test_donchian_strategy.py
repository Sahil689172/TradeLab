"""Unit tests for Donchian Channel service and Turtle-style strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from app.indicator_adapter import IndicatorAdapter
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.indicators.donchian import DonchianChannelService
from app.strategies.donchian import (
    DonchianExitReason,
    DonchianStopSource,
    DonchianStrategy,
    DonchianStrategyConfig,
    register_donchian_strategy,
)
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner


ENTRY = 10
EXIT = 5


def make_structure(trend: TrendDirection) -> MarketStructureResult:
    return MarketStructureResult(
        symbol="RELIANCE",
        swing_length=2,
        bar_count=50,
        trend=trend,
        swings=[],
        events=[],
        last_swing_high=None,
        last_swing_low=None,
    )


def _frame_from_rows(
    rows: list[dict[str, float]],
    *,
    rvol: float = 2.0,
    atr: float = 2.0,
    ema_bullish: bool = True,
) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-02")
    records = []
    for index, row in enumerate(rows):
        close = row["close"]
        if ema_bullish:
            ema_20, ema_50 = close * 1.01, close * 0.99
        else:
            ema_20, ema_50 = close * 0.99, close * 1.01
        records.append(
            {
                "date": start + pd.Timedelta(days=index),
                "open": row.get("open", close),
                "high": row["high"],
                "low": row["low"],
                "close": close,
                "volume": 1_000.0 + index * 10,
                "relative_volume_20": rvol,
                "atr_14": atr,
                "ema_20": ema_20,
                "ema_50": ema_50,
            },
        )
    return pd.DataFrame(records)


def consolidation_then(
    last: dict[str, float],
    *,
    bars: int = 30,
    center: float = 100.0,
    half_range: float = 1.0,
) -> list[dict[str, float]]:
    """Quiet range so entry channel is tight, then a scenario bar."""
    rows: list[dict[str, float]] = []
    for index in range(bars):
        mid = center + (0.05 if index % 2 == 0 else -0.05)
        rows.append(
            {
                "open": mid,
                "high": center + half_range,
                "low": center - half_range,
                "close": mid,
            },
        )
    rows.append(last)
    return rows


@pytest.fixture
def config() -> DonchianStrategyConfig:
    return DonchianStrategyConfig(
        symbol="RELIANCE",
        entry_lookback=ENTRY,
        exit_lookback=EXIT,
        breakout_cooldown_bars=0,
        relative_volume_threshold=1.5,
        min_atr=0.5,
        min_history_bars=25,
        min_holding_bars=10,
        max_holding_bars=60,
        expected_holding_bars=30,
    )


def build_strategy(
    config: DonchianStrategyConfig,
    *,
    trend: TrendDirection = TrendDirection.BULLISH,
) -> DonchianStrategy:
    return DonchianStrategy(
        config,
        donchian_service=DonchianChannelService(
            entry_lookback=config.entry_lookback,
            exit_lookback=config.exit_lookback,
        ),
        market_structure=make_structure(trend),
    )


def test_upper_breakout(config: DonchianStrategyConfig) -> None:
    rows = consolidation_then(
        {"open": 101.0, "high": 108.0, "low": 100.5, "close": 107.0},
    )
    frame = _frame_from_rows(rows, rvol=2.0, ema_bullish=True)
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    prepared = strategy.prepare(frame)
    snap = strategy.last_donchian_snapshot
    assert snap is not None
    assert snap.breakout_above is True
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.BUY


def test_lower_breakout(config: DonchianStrategyConfig) -> None:
    rows = consolidation_then(
        {"open": 99.0, "high": 99.5, "low": 92.0, "close": 93.0},
    )
    frame = _frame_from_rows(rows, rvol=1.2, ema_bullish=False)
    strategy = build_strategy(config, trend=TrendDirection.BEARISH)
    prepared = strategy.prepare(frame)
    snap = strategy.last_donchian_snapshot
    assert snap is not None
    assert snap.breakout_below is True
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.SELL


def test_false_breakout(config: DonchianStrategyConfig) -> None:
    # Wick above prior channel high, close back inside
    rows = consolidation_then(
        {"open": 100.0, "high": 106.0, "low": 99.0, "close": 100.2},
    )
    frame = _frame_from_rows(rows, rvol=2.0, ema_bullish=True)
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    prepared = strategy.prepare(frame)
    snap = strategy.last_donchian_snapshot
    assert snap is not None
    assert snap.false_breakout_above is True
    assert snap.breakout_above is False
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.HOLD
    assert "false" in signal.reason.lower()


def test_trend_exit(config: DonchianStrategyConfig) -> None:
    rows = consolidation_then(
        {"open": 101.0, "high": 105.0, "low": 100.5, "close": 104.0},
    )
    frame = _frame_from_rows(rows)
    strategy = build_strategy(config, trend=TrendDirection.BEARISH)
    prepared = strategy.prepare(frame)
    assessment = strategy.evaluate_exit(
        prepared,
        direction=TradeDirection.LONG,
        entry_price=102.0,
        bars_held=5,
    )
    assert assessment.should_exit is True
    assert assessment.reason is DonchianExitReason.TREND_BEARISH


def test_atr_exit(config: DonchianStrategyConfig) -> None:
    # Stay inside channel; force ATR exit via large adverse move vs entry
    rows = consolidation_then(
        {"open": 100.0, "high": 100.5, "low": 90.0, "close": 91.0},
        half_range=0.5,
    )
    frame = _frame_from_rows(rows, atr=2.0)
    # Bullish structure so trend-exit does not fire first
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    prepared = strategy.prepare(frame)
    assessment = strategy.evaluate_exit(
        prepared,
        direction=TradeDirection.LONG,
        entry_price=100.0,
        bars_held=3,
    )
    assert assessment.should_exit is True
    assert assessment.reason in {
        DonchianExitReason.ATR_EXIT,
        DonchianExitReason.ATR_TRAILING,
        DonchianExitReason.EXIT_CHANNEL,
    }


def test_trade_plan_generation(config: DonchianStrategyConfig) -> None:
    rows = consolidation_then(
        {"open": 101.0, "high": 108.0, "low": 100.5, "close": 107.0},
    )
    frame = _frame_from_rows(rows, rvol=2.0, ema_bullish=True)
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    prepared = strategy.prepare(frame)
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.BUY

    plan = strategy.generate_trade_plan(prepared, signal)
    detailed = strategy.last_detailed_plan
    assert detailed is not None
    assert plan.strategy_name == "donchian"
    assert plan.entry_price == pytest.approx(107.0)
    assert plan.stop_loss < plan.entry_price
    assert plan.take_profit_1 > plan.entry_price
    assert 0.0 < plan.confidence <= 1.0
    assert plan.reasons
    assert detailed.upper_channel >= detailed.lower_channel
    assert detailed.middle_channel == pytest.approx(
        (detailed.upper_channel + detailed.lower_channel) / 2.0,
    )
    assert detailed.stop_source in {
        DonchianStopSource.MIDDLE_CHANNEL,
        DonchianStopSource.ATR,
        DonchianStopSource.PREVIOUS_SWING,
    }
    assert "10–60" in detailed.holding_note
    assert detailed.confidence_breakdown.total > 0


def test_indicator_adapter_aliases() -> None:
    rows = consolidation_then(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
    )
    frame = _frame_from_rows(rows)
    attached = DonchianChannelService(entry_lookback=ENTRY, exit_lookback=EXIT).attach(frame)
    adapter = IndicatorAdapter(attached)
    assert adapter.indicator("donchian_upper").latest_value is not None
    assert adapter.indicator("donchian_lower").latest_value is not None
    assert adapter.indicator("donchian_middle").latest_value is not None


def test_registry_integration(config: DonchianStrategyConfig) -> None:
    rows = consolidation_then(
        {"open": 101.0, "high": 108.0, "low": 100.5, "close": 107.0},
    )
    frame = _frame_from_rows(rows, rvol=2.0, ema_bullish=True)
    registry = StrategyRegistry()
    register_donchian_strategy(
        registry,
        config,
        market_structure=make_structure(TrendDirection.BULLISH),
    )
    plan = StrategyRunner().run(frame, registry.get("donchian"))
    assert plan.strategy_name == "donchian"
    assert plan.signal is SignalType.BUY


def test_sell_targets_strictly_ordered(config: DonchianStrategyConfig) -> None:
    """SELL plans must satisfy target_2 < target_1 (never equal)."""
    rows = consolidation_then(
        {"open": 99.0, "high": 99.5, "low": 92.0, "close": 93.0},
    )
    frame = _frame_from_rows(rows, rvol=2.0, ema_bullish=False)
    strategy = build_strategy(config, trend=TrendDirection.BEARISH)
    prepared = strategy.prepare(frame)
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.SELL
    plan = strategy.generate_trade_plan(prepared, signal)
    assert plan.take_profit_1 < plan.entry_price
    assert plan.take_profit_2 < plan.take_profit_1
