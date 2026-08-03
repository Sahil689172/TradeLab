"""Unit tests for the CPR strategy and Levels Engine CPR component."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.levels.calculator import classic_pivot_levels, cpr_levels
from app.levels.schemas import (
    CamarillaPivotLevels,
    LevelKind,
    LevelsSnapshot,
    PeriodRange,
    PriceLevel,
)
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.strategies.cpr import (
    CPRPositionClass,
    CPRStrategy,
    CPRStrategyConfig,
    CPRTradeMode,
    CPRWidthClass,
    register_cpr_strategy,
)
from app.strategies.cpr.evaluation import classify_cpr
from app.conditions import ConditionEngine
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


def make_levels(
    *,
    high: float,
    low: float,
    close: float,
    reference: float | None = None,
) -> LevelsSnapshot:
    """Build a LevelsSnapshot with CPR + classic pivots from prior-day H/L/C."""
    classic = classic_pivot_levels(high, low, close)
    cpr = cpr_levels(high, low, close)
    ref = reference if reference is not None else classic.pivot + 1.0
    camarilla = CamarillaPivotLevels(
        reference_close=close,
        resistance_1=close + 1,
        resistance_2=close + 2,
        resistance_3=close + 3,
        resistance_4=close + 4,
        support_1=close - 1,
        support_2=close - 2,
        support_3=close - 3,
        support_4=close - 4,
    )
    period = PeriodRange(
        high=high,
        low=low,
        close=close,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
    )
    return LevelsSnapshot(
        symbol="RELIANCE",
        as_of=datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
        reference_price=ref,
        opening_range_bars=1,
        previous_day_high=high,
        previous_day_low=low,
        previous_week_high=high + 5,
        previous_week_low=low - 5,
        previous_month_high=high + 10,
        previous_month_low=low - 10,
        opening_range_high=ref + 0.5,
        opening_range_low=ref - 0.5,
        daily_pivot=classic.pivot,
        weekly_pivot=classic.pivot - 1,
        classic_pivot=classic,
        camarilla_pivot=camarilla,
        cpr=cpr,
        supports=[
            PriceLevel(kind=LevelKind.CPR_BC, price=cpr.bc, label="CPR Bottom Central"),
            PriceLevel(kind=LevelKind.CLASSIC_SUPPORT_1, price=classic.support_1, label="Classic S1"),
        ],
        resistances=[
            PriceLevel(kind=LevelKind.CPR_TC, price=cpr.tc, label="CPR Top Central"),
            PriceLevel(kind=LevelKind.CLASSIC_RESISTANCE_1, price=classic.resistance_1, label="Classic R1"),
        ],
        previous_day=period,
        previous_week=period,
        previous_month=period,
    )


# Narrow: tiny prior range → trend day
NARROW_LEVELS = make_levels(high=100.5, low=100.0, close=100.15)
# Wide: skewed close → range / reversal day
WIDE_LEVELS = make_levels(high=110.0, low=90.0, close=108.0)


def build_frame(
    rows: list[dict[str, float]],
    *,
    total: int = 20,
) -> pd.DataFrame:
    first = rows[0]
    pad_count = max(0, total - len(rows))
    padded: list[dict[str, object]] = []
    start = pd.Timestamp("2024-01-02 09:15")
    base = float(first["close"])
    for index in range(pad_count):
        price = base - 2 + index * 0.05
        padded.append(
            {
                "date": start + pd.Timedelta(minutes=5 * index),
                "open": price,
                "high": price + 0.1,
                "low": price - 0.1,
                "close": price,
                "volume": 1_000.0,
                "relative_volume_20": 1.0,
                "atr_14": 0.8,
                "vwap": price - 0.5,
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
                "vwap_slope": row.get("vwap_slope", 0.1),
            },
        )
    return pd.DataFrame(padded)


def trend_breakout_rows(*, rvol: float = 2.0, vwap_below: bool = True) -> list[dict[str, float]]:
    """Gap above narrow CPR TC — virgin-friendly breakout."""
    upper = NARROW_LEVELS.cpr.upper
    close = upper + 0.35
    vwap = close - 0.4 if vwap_below else close + 0.4
    return [
        {
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.08,  # stays above CPR → virgin
            "close": close,
            "vwap": vwap,
            "vwap_slope": 0.12,
            "relative_volume_20": rvol,
            "atr_14": 0.5,
        },
    ]


def wide_support_reversal_rows(*, rvol: float = 2.0) -> list[dict[str, float]]:
    lower = WIDE_LEVELS.cpr.lower
    return [
        {
            "open": lower + 0.3,
            "high": lower + 0.5,
            "low": lower - 0.05,  # touches BC
            "close": lower + 0.25,  # holds above
            "vwap": lower - 0.5,  # price above VWAP
            "vwap_slope": 0.08,
            "relative_volume_20": rvol,
            "atr_14": 1.2,
        },
    ]


def touched_cpr_rows() -> list[dict[str, float]]:
    """Session that trades through narrow CPR (not virgin)."""
    mid = (NARROW_LEVELS.cpr.lower + NARROW_LEVELS.cpr.upper) / 2.0
    return [
        {
            "open": mid,
            "high": mid + 0.2,
            "low": mid - 0.2,
            "close": mid + 0.05,
            "vwap": mid - 0.1,
            "vwap_slope": 0.05,
            "relative_volume_20": 1.8,
        },
    ]


@pytest.fixture
def config() -> CPRStrategyConfig:
    return CPRStrategyConfig(
        symbol="RELIANCE",
        min_history_bars=10,
        narrow_cpr_threshold=0.005,
    )


def build_strategy(
    config: CPRStrategyConfig,
    levels: LevelsSnapshot,
    trend: TrendDirection,
) -> CPRStrategy:
    return CPRStrategy(
        config,
        market_structure=make_structure(trend),
        levels=levels,
    )


def test_narrow_cpr_classification(config: CPRStrategyConfig) -> None:
    assert NARROW_LEVELS.cpr.width_pct <= config.narrow_cpr_threshold
    frame = build_frame(trend_breakout_rows())
    classification = classify_cpr(
        cpr=NARROW_LEVELS.cpr,
        close=float(frame.iloc[-1]["close"]),
        session=frame,
        config=config,
        conditions=ConditionEngine(),
    )
    assert classification.width is CPRWidthClass.NARROW
    assert classification.mode is CPRTradeMode.TREND
    assert classification.position is CPRPositionClass.OUTSIDE


def test_wide_cpr_classification(config: CPRStrategyConfig) -> None:
    assert WIDE_LEVELS.cpr.width_pct > config.narrow_cpr_threshold
    frame = build_frame(wide_support_reversal_rows())
    classification = classify_cpr(
        cpr=WIDE_LEVELS.cpr,
        close=float(frame.iloc[-1]["close"]),
        session=frame,
        config=config,
        conditions=ConditionEngine(),
    )
    assert classification.width is CPRWidthClass.WIDE
    assert classification.mode is CPRTradeMode.REVERSAL


def test_trend_day_breakout(config: CPRStrategyConfig) -> None:
    strategy = build_strategy(config, NARROW_LEVELS, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(build_frame(trend_breakout_rows())))
    assert signal.signal is SignalType.BUY
    assert "breakout" in signal.reason.lower() or "narrow" in signal.reason.lower()


def test_range_day_reversal(config: CPRStrategyConfig) -> None:
    strategy = build_strategy(config, WIDE_LEVELS, TrendDirection.BULLISH)
    signal = strategy.generate_signal(strategy.prepare(build_frame(wide_support_reversal_rows())))
    assert signal.signal is SignalType.BUY
    assert "reversal" in signal.reason.lower() or "wide" in signal.reason.lower()


def test_wide_cpr(config: CPRStrategyConfig) -> None:
    strategy = build_strategy(config, WIDE_LEVELS, TrendDirection.BULLISH)
    prepared = strategy.prepare(build_frame(wide_support_reversal_rows()))
    setup = strategy._assess(prepared)
    assert setup.classification.width is CPRWidthClass.WIDE


def test_narrow_cpr(config: CPRStrategyConfig) -> None:
    strategy = build_strategy(config, NARROW_LEVELS, TrendDirection.BULLISH)
    prepared = strategy.prepare(build_frame(trend_breakout_rows()))
    setup = strategy._assess(prepared)
    assert setup.classification.width is CPRWidthClass.NARROW


def test_virgin_cpr(config: CPRStrategyConfig) -> None:
    strategy = build_strategy(config, NARROW_LEVELS, TrendDirection.BULLISH)
    upper = NARROW_LEVELS.cpr.upper
    rows = [
        {
            "date": pd.Timestamp("2024-01-02 09:15") + pd.Timedelta(minutes=5 * i),
            "open": upper + 0.4,
            "high": upper + 0.5,
            "low": upper + 0.3,
            "close": upper + 0.45,
            "volume": 1_500.0,
            "relative_volume_20": 2.0,
            "atr_14": 0.5,
            "vwap": upper + 0.1,
            "vwap_slope": 0.1,
        }
        for i in range(12)
    ]
    prepared = strategy.prepare(pd.DataFrame(rows))
    setup = strategy._assess(prepared)
    assert setup.classification.virgin is True

    strategy2 = build_strategy(config, NARROW_LEVELS, TrendDirection.BULLISH)
    setup2 = strategy2._assess(strategy2.prepare(build_frame(touched_cpr_rows())))
    assert setup2.classification.virgin is False


def test_vwap_confirmation_required(config: CPRStrategyConfig) -> None:
    strategy = build_strategy(config, NARROW_LEVELS, TrendDirection.BULLISH)
    signal = strategy.generate_signal(
        strategy.prepare(build_frame(trend_breakout_rows(vwap_below=False))),
    )
    assert signal.signal is SignalType.HOLD
    assert "vwap" in signal.reason.lower()


def test_trade_plan_generation(config: CPRStrategyConfig) -> None:
    strategy = build_strategy(config, NARROW_LEVELS, TrendDirection.BULLISH)
    plan = StrategyRunner().run(build_frame(trend_breakout_rows()), strategy)
    detailed = strategy.last_detailed_plan

    assert plan.strategy_name == "cpr"
    assert plan.signal is SignalType.BUY
    assert plan.holding_period == config.session_bars
    assert plan.stop_loss < plan.entry_price
    assert plan.take_profit_1 > plan.entry_price
    assert any("classification" in reason.lower() or "cpr" in reason.lower() for reason in plan.reasons)
    assert detailed is not None
    assert detailed.classification.width is CPRWidthClass.NARROW
    assert detailed.classification.mode is CPRTradeMode.TREND
    assert detailed.cpr.pivot == pytest.approx(NARROW_LEVELS.cpr.pivot)


def test_registry_integration(config: CPRStrategyConfig) -> None:
    registry = StrategyRegistry()
    register_cpr_strategy(
        registry,
        config,
        market_structure=make_structure(TrendDirection.BULLISH),
        levels=NARROW_LEVELS,
    )
    plan = StrategyRunner().run(
        build_frame(trend_breakout_rows()),
        registry.get("cpr"),
    )
    assert plan.signal is SignalType.BUY


def test_cpr_targets_respect_minimum_risk_reward() -> None:
    """Classic pivots that yield RR < 1 must be upgraded to the RR floor."""
    from app.levels.schemas import ClassicPivotLevels
    from app.risk_engine.schemas import TradeDirection
    from app.strategies.cpr.evaluation import select_cpr_targets

    # Tight R1/R2 above entry relative to a wide stop → raw RR ≪ 1
    classic = ClassicPivotLevels(
        pivot=100.0,
        resistance_1=100.4,
        resistance_2=100.6,
        resistance_3=101.0,
        support_1=99.0,
        support_2=98.0,
        support_3=97.0,
    )
    (tp1, _), (tp2, _), rr = select_cpr_targets(
        direction=TradeDirection.LONG,
        entry_price=100.0,
        classic=classic,
        stop_loss=98.0,  # risk = 2.0; R1 reward = 0.4 → RR = 0.2
        risk_reward_fallback=2.0,
        min_risk_reward=1.0,
    )
    assert rr >= 1.0
    assert tp1 > 100.0
    assert tp2 > tp1
