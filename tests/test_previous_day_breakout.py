"""Unit tests for the Previous Day High/Low (Magic Box) strategy."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.levels.calculator import cpr_levels
from app.levels.schemas import (
    CamarillaPivotLevels,
    ClassicPivotLevels,
    LevelKind,
    LevelsSnapshot,
    PeriodRange,
    PriceLevel,
)
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.strategies.previous_day_breakout import (
    PreviousDayBreakoutConfig,
    PreviousDayBreakoutStrategy,
    SetupStage,
    register_previous_day_breakout_strategy,
)
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner
from app.strategy_engine.exceptions import StrategyValidationError


def make_levels(*, pdh: float = 100.0, pdl: float = 90.0, reference: float = 101.0) -> LevelsSnapshot:
    classic = ClassicPivotLevels(
        pivot=95.0,
        resistance_1=100.0,
        resistance_2=105.0,
        resistance_3=110.0,
        support_1=90.0,
        support_2=85.0,
        support_3=80.0,
    )
    camarilla = CamarillaPivotLevels(
        reference_close=95.0,
        resistance_1=96.0,
        resistance_2=97.0,
        resistance_3=98.0,
        resistance_4=99.0,
        support_1=94.0,
        support_2=93.0,
        support_3=92.0,
        support_4=91.0,
    )
    period = PeriodRange(
        high=pdh,
        low=pdl,
        close=reference,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
    )
    return LevelsSnapshot(
        symbol="RELIANCE",
        as_of=datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
        reference_price=reference,
        opening_range_bars=1,
        previous_day_high=pdh,
        previous_day_low=pdl,
        previous_week_high=pdh + 5,
        previous_week_low=pdl - 5,
        previous_month_high=pdh + 10,
        previous_month_low=pdl - 10,
        opening_range_high=reference + 1,
        opening_range_low=reference - 1,
        daily_pivot=95.0,
        weekly_pivot=94.0,
        classic_pivot=classic,
        camarilla_pivot=camarilla,
        cpr=cpr_levels(pdh, pdl, reference),
        supports=[
            PriceLevel(kind=LevelKind.PREVIOUS_DAY_LOW, price=pdl, label="Previous Day Low"),
            PriceLevel(kind=LevelKind.CLASSIC_SUPPORT_1, price=88.0, label="Classic S1"),
        ],
        resistances=[
            PriceLevel(kind=LevelKind.PREVIOUS_DAY_HIGH, price=pdh, label="Previous Day High"),
            PriceLevel(kind=LevelKind.CLASSIC_RESISTANCE_2, price=108.0, label="Classic R2"),
        ],
        previous_day=period,
        previous_week=period,
        previous_month=period,
    )


def make_structure(trend: TrendDirection) -> MarketStructureResult:
    return MarketStructureResult(
        symbol="RELIANCE",
        swing_length=2,
        bar_count=30,
        trend=trend,
        swings=[],
        events=[],
        last_swing_high=None,
        last_swing_low=None,
    )


def _pad(rows: list[dict[str, float]], *, total: int = 25) -> pd.DataFrame:
    """Prepend quiet bars so min_history is satisfied."""
    base_close = float(rows[0]["close"])
    pad_count = max(0, total - len(rows))
    padded: list[dict[str, object]] = []
    start = pd.Timestamp("2024-01-02 09:15")
    for index in range(pad_count):
        price = base_close - 5 + index * 0.05
        padded.append(
            {
                "date": start + pd.Timedelta(minutes=15 * index),
                "open": price,
                "high": price + 0.3,
                "low": price - 0.3,
                "close": price,
                "relative_volume_20": 1.0,
                "atr_14": 1.5,
            },
        )
    offset = pad_count
    for index, row in enumerate(rows):
        padded.append(
            {
                "date": start + pd.Timedelta(minutes=15 * (offset + index)),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "relative_volume_20": row.get("relative_volume_20", 2.0),
                "atr_14": row.get("atr_14", 1.5),
            },
        )
    return pd.DataFrame(padded)


def bullish_breakout_frame(*, rvol: float = 2.0) -> pd.DataFrame:
    """Approach → break PDH 100 → retest → bullish confirmation."""
    return _pad(
        [
            {"open": 98.0, "high": 99.0, "low": 97.5, "close": 98.5, "relative_volume_20": 1.0},
            {"open": 98.5, "high": 100.2, "low": 98.4, "close": 99.2, "relative_volume_20": 1.2},  # approach
            {"open": 99.2, "high": 101.5, "low": 99.0, "close": 101.0, "relative_volume_20": 1.8},  # break
            {
                "open": 100.2,
                "high": 102.0,
                "low": 99.8,
                "close": 101.6,
                "relative_volume_20": rvol,
            },  # retest + bullish confirm
        ],
    )


def bearish_breakdown_frame(*, rvol: float = 2.0) -> pd.DataFrame:
    """Approach → break PDL 100 → retest → bearish confirmation."""
    return _pad(
        [
            {"open": 102.0, "high": 102.5, "low": 101.0, "close": 101.5, "relative_volume_20": 1.0},
            {"open": 101.5, "high": 101.8, "low": 99.8, "close": 100.5, "relative_volume_20": 1.2},  # approach
            {"open": 100.5, "high": 100.8, "low": 98.5, "close": 99.0, "relative_volume_20": 1.8},  # break
            {
                "open": 99.8,
                "high": 100.2,
                "low": 98.0,
                "close": 98.5,
                "relative_volume_20": rvol,
            },  # retest + bearish confirm
        ],
    )


def no_breakout_frame() -> pd.DataFrame:
    return _pad(
        [
            {"open": 98.0, "high": 99.0, "low": 97.5, "close": 98.5, "relative_volume_20": 1.0},
            {"open": 98.5, "high": 99.5, "low": 98.0, "close": 99.0, "relative_volume_20": 1.1},
            {"open": 99.0, "high": 99.8, "low": 98.8, "close": 99.4, "relative_volume_20": 1.0},
            {"open": 99.4, "high": 99.9, "low": 99.0, "close": 99.5, "relative_volume_20": 1.0},
        ],
    )


def failed_retest_frame() -> pd.DataFrame:
    return _pad(
        [
            {"open": 98.0, "high": 99.0, "low": 97.5, "close": 98.5, "relative_volume_20": 1.0},
            {"open": 98.5, "high": 100.2, "low": 98.4, "close": 99.2, "relative_volume_20": 1.2},
            {"open": 99.2, "high": 101.5, "low": 99.0, "close": 101.0, "relative_volume_20": 1.8},
            {"open": 100.5, "high": 100.8, "low": 98.5, "close": 99.0, "relative_volume_20": 2.0},  # fail
        ],
    )


@pytest.fixture
def config() -> PreviousDayBreakoutConfig:
    return PreviousDayBreakoutConfig(symbol="RELIANCE", min_history_bars=20)


def build_strategy(
    config: PreviousDayBreakoutConfig,
    *,
    trend: TrendDirection = TrendDirection.BULLISH,
    pdh: float = 100.0,
    pdl: float = 90.0,
) -> PreviousDayBreakoutStrategy:
    return PreviousDayBreakoutStrategy(
        config,
        levels=make_levels(pdh=pdh, pdl=pdl),
        market_structure=make_structure(trend),
    )


def test_bullish_breakout_generates_buy(config: PreviousDayBreakoutConfig) -> None:
    strategy = build_strategy(config, trend=TrendDirection.BULLISH, pdh=100.0, pdl=90.0)
    frame = bullish_breakout_frame()
    prepared = strategy.prepare(frame)
    signal = strategy.generate_signal(prepared)

    assert signal.signal is SignalType.BUY
    assert signal.symbol == "RELIANCE"
    assert signal.confidence == pytest.approx(1.0)


def test_bearish_breakdown_generates_sell(config: PreviousDayBreakoutConfig) -> None:
    strategy = build_strategy(config, trend=TrendDirection.BEARISH, pdh=110.0, pdl=100.0)
    frame = bearish_breakdown_frame()
    signal = strategy.generate_signal(strategy.prepare(frame))

    assert signal.signal is SignalType.SELL
    assert signal.confidence == pytest.approx(1.0)


def test_no_breakout_holds(config: PreviousDayBreakoutConfig) -> None:
    strategy = build_strategy(config, trend=TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(no_breakout_frame()))

    assert signal.signal is SignalType.HOLD


def test_failed_retest_holds(config: PreviousDayBreakoutConfig) -> None:
    strategy = build_strategy(config, trend=TrendDirection.BULLISH, pdh=100.0)
    prepared = strategy.prepare(failed_retest_frame())
    long_setup, _ = strategy._assess_both(prepared)

    assert long_setup.stage is SetupStage.FAILED_RETEST
    assert long_setup.failed_retest is True
    assert strategy.generate_signal(prepared).signal is SignalType.HOLD


def test_weak_volume_holds(config: PreviousDayBreakoutConfig) -> None:
    strategy = build_strategy(config, trend=TrendDirection.BULLISH, pdh=100.0)
    frame = bullish_breakout_frame(rvol=1.2)
    signal = strategy.generate_signal(strategy.prepare(frame))

    assert signal.signal is SignalType.HOLD
    assert "volume" in signal.reason.lower() or "Weak" in signal.reason


def test_broken_market_structure_holds(config: PreviousDayBreakoutConfig) -> None:
    strategy = build_strategy(config, trend=TrendDirection.BEARISH, pdh=100.0)
    signal = strategy.generate_signal(strategy.prepare(bullish_breakout_frame()))

    assert signal.signal is SignalType.HOLD
    assert "structure" in signal.reason.lower()


def test_trade_plan_generation(config: PreviousDayBreakoutConfig) -> None:
    strategy = build_strategy(config, trend=TrendDirection.BULLISH, pdh=100.0, pdl=90.0)
    frame = bullish_breakout_frame()
    plan = StrategyRunner().run(frame, strategy)
    detailed = strategy.last_detailed_plan

    assert plan.strategy_name == "previous_day_breakout"
    assert plan.signal is SignalType.BUY
    assert plan.stop_loss < plan.entry_price < plan.take_profit_1
    assert plan.take_profit_2 >= plan.take_profit_1
    assert plan.risk_reward == pytest.approx(2.0)
    assert plan.holding_period == config.session_bars
    assert any("PDH" in reason or "Previous Day" in reason or "Levels used" in reason for reason in plan.reasons)
    assert any("intraday" in reason.lower() for reason in plan.reasons)

    assert detailed is not None
    assert detailed.direction.value == "LONG"
    assert detailed.market_structure is TrendDirection.BULLISH
    assert detailed.levels_used.previous_day_high == pytest.approx(100.0)
    assert detailed.confidence_breakdown.total == pytest.approx(100.0)
    assert detailed.holding_note.lower().startswith("intraday")


def test_registry_integration(config: PreviousDayBreakoutConfig) -> None:
    registry = StrategyRegistry()
    strategy = register_previous_day_breakout_strategy(
        registry,
        config,
        levels=make_levels(pdh=100.0, pdl=90.0),
        market_structure=make_structure(TrendDirection.BULLISH),
    )

    assert registry.list() == ["previous_day_breakout"]
    plan = StrategyRunner().run(bullish_breakout_frame(), registry.get("previous_day_breakout"))
    assert plan.signal is SignalType.BUY
    assert strategy.last_detailed_plan is not None


def test_requires_daily_context(config: PreviousDayBreakoutConfig) -> None:
    strategy = PreviousDayBreakoutStrategy(config)
    with pytest.raises(StrategyValidationError, match="Daily context"):
        strategy.validate(bullish_breakout_frame())
