"""Unit tests for the Daily VWAP strategy and shared VWAP service."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.levels.schemas import (
    CamarillaPivotLevels,
    ClassicPivotLevels,
    LevelKind,
    LevelsSnapshot,
    PeriodRange,
    PriceLevel,
)
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.services.strategy_engine.indicators import (
    VWAPMode,
    VWAPService,
    compute_daily_vwap,
)
from app.services.strategy_engine.indicators.vwap import VWAPNotImplementedError
from app.strategies.vwap import (
    VWAPStopSource,
    VWAPStrategy,
    VWAPStrategyConfig,
    register_vwap_strategy,
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


def make_levels(*, reference: float = 101.0) -> LevelsSnapshot:
    classic = ClassicPivotLevels(
        pivot=100.0,
        resistance_1=102.0,
        resistance_2=104.0,
        resistance_3=106.0,
        support_1=98.0,
        support_2=96.0,
        support_3=94.0,
    )
    camarilla = CamarillaPivotLevels(
        reference_close=100.0,
        resistance_1=101.0,
        resistance_2=102.0,
        resistance_3=103.0,
        resistance_4=104.0,
        support_1=99.0,
        support_2=98.0,
        support_3=97.0,
        support_4=96.0,
    )
    period = PeriodRange(
        high=105.0,
        low=95.0,
        close=reference,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
    )
    return LevelsSnapshot(
        symbol="RELIANCE",
        as_of=datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
        reference_price=reference,
        opening_range_bars=1,
        previous_day_high=105.0,
        previous_day_low=95.0,
        previous_week_high=110.0,
        previous_week_low=90.0,
        previous_month_high=115.0,
        previous_month_low=85.0,
        opening_range_high=reference + 1,
        opening_range_low=reference - 1,
        daily_pivot=100.0,
        weekly_pivot=99.0,
        classic_pivot=classic,
        camarilla_pivot=camarilla,
        supports=[
            PriceLevel(kind=LevelKind.PREVIOUS_DAY_LOW, price=95.0, label="Previous Day Low"),
            PriceLevel(kind=LevelKind.CLASSIC_SUPPORT_1, price=98.0, label="Classic S1"),
        ],
        resistances=[
            PriceLevel(kind=LevelKind.CLASSIC_RESISTANCE_1, price=102.0, label="Classic R1"),
            PriceLevel(kind=LevelKind.PREVIOUS_DAY_HIGH, price=105.0, label="Previous Day High"),
        ],
        previous_day=period,
        previous_week=period,
        previous_month=period,
    )


def build_frame(rows: list[dict[str, float]], *, total: int = 20) -> pd.DataFrame:
    """Pad quiet bars then append scenario rows with explicit VWAP columns."""
    first = rows[0]
    pad_count = max(0, total - len(rows))
    padded: list[dict[str, object]] = []
    start = pd.Timestamp("2024-01-02 09:15")
    base_vwap = float(first.get("vwap", 100.0))
    for index in range(pad_count):
        price = base_vwap - 1.0 + index * 0.02
        padded.append(
            {
                "date": start + pd.Timedelta(minutes=5 * index),
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": 1_000.0,
                "relative_volume_20": 1.0,
                "atr_14": 0.8,
                "vwap": base_vwap - 0.5 + index * 0.01,
                "vwap_slope": 0.05,
            },
        )
    offset = pad_count
    for index, row in enumerate(rows):
        padded.append(
            {
                "date": start + pd.Timedelta(minutes=5 * (offset + index)),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row.get("volume", 2_000.0),
                "relative_volume_20": row.get("relative_volume_20", 2.0),
                "atr_14": row.get("atr_14", 0.8),
                "vwap": row["vwap"],
                "vwap_slope": row["vwap_slope"],
            },
        )
    return pd.DataFrame(padded)


def bullish_retest_rows(*, rvol: float = 2.0) -> list[dict[str, float]]:
    """Price above rising VWAP with a successful retest on the last bar."""
    return [
        {
            "open": 100.4,
            "high": 100.8,
            "low": 100.3,
            "close": 100.6,
            "vwap": 100.0,
            "vwap_slope": 0.12,
            "relative_volume_20": 1.8,
        },
        {
            "open": 100.5,
            "high": 100.7,
            "low": 100.05,  # touches VWAP
            "close": 100.35,  # holds above
            "vwap": 100.0,
            "vwap_slope": 0.15,
            "relative_volume_20": rvol,
            "atr_14": 0.7,
        },
    ]


def bearish_rejection_rows(*, rvol: float = 2.0) -> list[dict[str, float]]:
    """Price below falling VWAP with rejection on the last bar."""
    return [
        {
            "open": 99.6,
            "high": 99.7,
            "low": 99.2,
            "close": 99.4,
            "vwap": 100.0,
            "vwap_slope": -0.12,
            "relative_volume_20": 1.8,
        },
        {
            "open": 99.5,
            "high": 99.95,  # touches VWAP from below
            "low": 99.2,
            "close": 99.45,  # rejects / holds below
            "vwap": 100.0,
            "vwap_slope": -0.15,
            "relative_volume_20": rvol,
            "atr_14": 0.7,
        },
    ]


def breakout_no_retest_rows() -> list[dict[str, float]]:
    """Bullish breakout above VWAP without a retest touch."""
    return [
        {
            "open": 100.5,
            "high": 101.2,
            "low": 100.4,
            "close": 101.0,
            "vwap": 100.0,
            "vwap_slope": 0.2,
            "relative_volume_20": 2.2,
        },
    ]


@pytest.fixture
def config() -> VWAPStrategyConfig:
    return VWAPStrategyConfig(
        symbol="RELIANCE",
        min_history_bars=10,
        slope_lookback=3,
        retest_tolerance=0.002,
    )


def build_strategy(
    config: VWAPStrategyConfig,
    trend: TrendDirection,
    *,
    levels: LevelsSnapshot | None = None,
) -> VWAPStrategy:
    return VWAPStrategy(
        config,
        market_structure=make_structure(trend),
        levels=levels,
    )


def test_bullish_trend(config: VWAPStrategyConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(build_frame(bullish_retest_rows())))
    assert signal.signal is SignalType.BUY
    assert signal.confidence > 0.5


def test_bearish_trend(config: VWAPStrategyConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BEARISH)
    signal = strategy.generate_signal(strategy.prepare(build_frame(bearish_rejection_rows())))
    assert signal.signal is SignalType.SELL


def test_vwap_rejection(config: VWAPStrategyConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BEARISH)
    prepared = strategy.prepare(build_frame(bearish_rejection_rows()))
    signal = strategy.generate_signal(prepared)
    assert signal.signal is SignalType.SELL
    assert "rejection" in signal.reason.lower()


def test_vwap_breakout_without_retest_holds(config: VWAPStrategyConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(build_frame(breakout_no_retest_rows())))
    assert signal.signal is SignalType.HOLD
    assert "retest" in signal.reason.lower()


def test_low_volume(config: VWAPStrategyConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BULLISH)
    signal = strategy.generate_signal(
        strategy.prepare(build_frame(bullish_retest_rows(rvol=1.1))),
    )
    assert signal.signal is SignalType.HOLD
    assert "volume" in signal.reason.lower()


def test_wrong_structure(config: VWAPStrategyConfig) -> None:
    strategy = build_strategy(config, TrendDirection.BEARISH)
    signal = strategy.generate_signal(strategy.prepare(build_frame(bullish_retest_rows())))
    assert signal.signal is SignalType.HOLD
    assert "structure" in signal.reason.lower()


def test_trade_plan_generation(config: VWAPStrategyConfig) -> None:
    strategy = build_strategy(
        config,
        TrendDirection.BULLISH,
        levels=make_levels(reference=100.4),
    )
    plan = StrategyRunner().run(build_frame(bullish_retest_rows()), strategy)
    detailed = strategy.last_detailed_plan

    assert plan.strategy_name == "vwap"
    assert plan.signal is SignalType.BUY
    assert plan.risk_reward == pytest.approx(2.0)
    assert plan.holding_period == config.session_bars
    assert plan.stop_loss < plan.entry_price < plan.take_profit_1
    assert any("intraday" in reason.lower() for reason in plan.reasons)
    assert detailed is not None
    assert detailed.stop_source is VWAPStopSource.VWAP
    assert detailed.vwap_mode is VWAPMode.DAILY
    assert detailed.take_profit_2 >= plan.take_profit_1


def test_vwap_service_daily_compute() -> None:
    rows = []
    start = pd.Timestamp("2024-01-02 09:15")
    for index in range(5):
        rows.append(
            {
                "date": start + pd.Timedelta(minutes=5 * index),
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + index * 0.1,
                "volume": 1_000.0,
            },
        )
    frame = pd.DataFrame(rows)
    series = compute_daily_vwap(frame)
    assert len(series) == 5
    assert series.iloc[-1] > 0

    service = VWAPService()
    attached = service.attach(frame)
    assert "vwap" in attached.columns
    assert "vwap_slope" in attached.columns
    snap = service.snapshot(attached)
    assert snap.mode is VWAPMode.DAILY
    assert snap.value == pytest.approx(float(attached.iloc[-1]["vwap"]))


def test_vwap_service_rejects_unimplemented_modes() -> None:
    service = VWAPService(mode=VWAPMode.DAILY)
    frame = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-02 09:15")],
            "high": [100.0],
            "low": [99.0],
            "close": [99.5],
            "volume": [1_000.0],
        },
    )
    with pytest.raises(VWAPNotImplementedError):
        service.compute_series(frame, mode=VWAPMode.ANCHORED)


def test_registry_integration(config: VWAPStrategyConfig) -> None:
    registry = StrategyRegistry()
    register_vwap_strategy(
        registry,
        config,
        market_structure=make_structure(TrendDirection.BULLISH),
        levels=make_levels(),
    )
    plan = StrategyRunner().run(
        build_frame(bullish_retest_rows()),
        registry.get("vwap"),
    )
    assert plan.signal is SignalType.BUY
