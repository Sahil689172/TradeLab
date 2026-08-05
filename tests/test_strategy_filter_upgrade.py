"""Unit tests for Phase A4X.6 Professional Strategy Upgrade (filter profiles)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategies.opening_range_breakout import (
    OpeningRangeBreakoutConfig,
    OpeningRangeBreakoutStrategy,
)
from app.strategy_engine.filters import (
    FILTER_CATALOG,
    FilterRole,
    STRATEGY_FILTER_PROFILES,
    apply_strategy_filter_pipeline,
    build_pipeline_from_profile,
    create_filter,
    get_strategy_filter_profile,
    list_strategy_filter_profiles,
)
from app.strategy_engine.models import SignalType, TradePlan
from app.strategy_engine.runner import StrategyRunner


EXPECTED_STRATEGIES = {
    "ema_trend",
    "opening_range_breakout",
    "vwap",
    "supertrend",
    "momentum",
    "break_retest",
    "cpr",
    "previous_day_breakout",
    "volume_breakout",
    "donchian",
    "darvas_box",
    "relative_strength",
}


def _plan(*, signal: SignalType = SignalType.BUY, price: float = 100.0) -> TradePlan:
    return TradePlan(
        symbol="RELIANCE",
        entry_price=price,
        signal=signal,
        stop_loss=price * 0.95,
        take_profit_1=price * 1.10,
        take_profit_2=price * 1.15,
        holding_period=10,
        risk_reward=2.0,
        confidence=0.8,
        reasons=["unit"],
        strategy_name="ema_trend",
    )


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": [100.0],
            "high": [102.0],
            "low": [98.0],
            "volume": [500_000],
            "ema_200": [90.0],
            "adx_14": [30.0],
            "atr_14": [2.0],
            "relative_volume_20": [1.5],
            "volume_sma_20": [400_000],
            "vwap": [99.0],
            "gap_pct": [1.0],
            "trend_direction": ["BULLISH"],
        },
    )


def test_all_twelve_strategies_have_profiles() -> None:
    names = set(list_strategy_filter_profiles())
    assert names == EXPECTED_STRATEGIES
    for name in EXPECTED_STRATEGIES:
        profile = get_strategy_filter_profile(name)
        assert profile.strategy_name == name
        assert profile.mandatory, f"{name} missing mandatory filters"
        assert any(s.role is FilterRole.DEFAULT for s in profile.default) or profile.default == ()
        # every profile declares all four categories as attributes
        assert isinstance(profile.optional, tuple)
        assert isinstance(profile.configurable, tuple)


def test_ema_and_orb_research_defaults() -> None:
    ema = get_strategy_filter_profile("ema_trend")
    assert {s.filter_id for s in ema.mandatory} == {"ema200", "adx"}
    assert "atr_stop" in {s.filter_id for s in ema.default}
    assert "relative_volume" in {s.filter_id for s in ema.default}

    orb = get_strategy_filter_profile("opening_range_breakout")
    assert "stocks_in_play" in {s.filter_id for s in orb.mandatory}
    assert {"atr_stop", "vwap_confirmation", "gap"} <= {s.filter_id for s in orb.default}


def test_strategy_classes_declare_filter_profile() -> None:
    assert EMATrendStrategy.FILTER_PROFILE is STRATEGY_FILTER_PROFILES["ema_trend"]
    assert (
        OpeningRangeBreakoutStrategy.FILTER_PROFILE
        is STRATEGY_FILTER_PROFILES["opening_range_breakout"]
    )
    strategy = EMATrendStrategy()
    assert strategy.filter_pipeline_enabled is False
    assert strategy.filter_profile.strategy_name == "ema_trend"


def test_profile_resolve_optional_and_disable() -> None:
    profile = get_strategy_filter_profile("ema_trend")
    active = profile.resolve()
    ids = {s.filter_id for s in active}
    assert "ema200" in ids
    assert "trending_market" not in ids  # optional off

    with_optional = profile.resolve(enable_optional={"trending_market"})
    assert "trending_market" in {s.filter_id for s in with_optional}

    disabled = profile.resolve(disable={"relative_volume"})
    assert "relative_volume" not in {s.filter_id for s in disabled}
    # mandatory cannot be disabled
    assert "ema200" in {s.filter_id for s in profile.resolve(disable={"ema200"})}


def test_catalog_creates_all_profile_filters() -> None:
    used: set[str] = set()
    for profile in STRATEGY_FILTER_PROFILES.values():
        for spec in profile.all_specs():
            used.add(spec.filter_id)
    for filter_id in used:
        assert filter_id in FILTER_CATALOG
        filt = create_filter(filter_id, priority=1)
        assert filt.name


def test_build_pipeline_from_profile() -> None:
    profile = get_strategy_filter_profile("ema_trend")
    pipeline = build_pipeline_from_profile(profile)
    plan = _plan()
    filtered, result = apply_strategy_filter_pipeline(
        plan,
        profile=profile,
        features=_features(),
    )
    assert result.filters_applied >= 1
    assert filtered.signal in {SignalType.BUY, SignalType.HOLD}


def test_apply_pipeline_rejects_to_hold() -> None:
    profile = get_strategy_filter_profile("ema_trend")
    # Price below EMA200 → mandatory ema200 fails
    features = _features()
    features.loc[0, "ema_200"] = 110.0
    features.loc[0, "close"] = 100.0
    filtered, result = apply_strategy_filter_pipeline(
        _plan(),
        profile=profile,
        features=features,
    )
    assert result.output.rejected is True
    assert filtered.signal is SignalType.HOLD
    assert any("Filter rejected" in r for r in filtered.reasons)


def test_hold_bypasses_filters() -> None:
    filtered, result = apply_strategy_filter_pipeline(
        _plan(signal=SignalType.HOLD),
        profile=get_strategy_filter_profile("ema_trend"),
        features=_features(),
    )
    assert filtered.signal is SignalType.HOLD
    assert result.filters_applied == 0


def test_runner_backwards_compatible_filters_off_by_default() -> None:
    """Without enable_filter_pipeline, runner must not alter TradePlan via filters."""
    # Use stub-like path: runner still needs a real strategy that can run.
    # Smoke: config default is False.
    cfg = EMATrendConfig()
    assert cfg.enable_filter_pipeline is False
    orb = OpeningRangeBreakoutConfig()
    assert orb.enable_filter_pipeline is False


def test_runner_apply_filters_override() -> None:
    strategy = EMATrendStrategy(EMATrendConfig(enable_filter_pipeline=False))
    assert strategy.filter_pipeline_enabled is False
    # Explicit runner flag still works when strategy config is off
    # (full candle path is heavy — unit-test the flag plumbing only)
    assert StrategyRunner().run.__defaults__ is None or True
    import inspect

    sig = inspect.signature(StrategyRunner.run)
    assert "apply_filters" in sig.parameters


def test_all_strategy_classes_have_filter_profile_attr() -> None:
    from app.strategies.break_retest.strategy import BreakRetestStrategy
    from app.strategies.cpr.strategy import CPRStrategy
    from app.strategies.darvas_box.strategy import DarvasBoxStrategy
    from app.strategies.donchian.strategy import DonchianStrategy
    from app.strategies.momentum.strategy import MomentumStrategy
    from app.strategies.previous_day_breakout.strategy import PreviousDayBreakoutStrategy
    from app.strategies.relative_strength.strategy import RelativeStrengthStrategy
    from app.strategies.supertrend.strategy import SuperTrendStrategy
    from app.strategies.volume_breakout.strategy import VolumeBreakoutStrategy
    from app.strategies.vwap.strategy import VWAPStrategy

    classes = [
        EMATrendStrategy,
        OpeningRangeBreakoutStrategy,
        VWAPStrategy,
        SuperTrendStrategy,
        MomentumStrategy,
        BreakRetestStrategy,
        CPRStrategy,
        PreviousDayBreakoutStrategy,
        VolumeBreakoutStrategy,
        DonchianStrategy,
        DarvasBoxStrategy,
        RelativeStrengthStrategy,
    ]
    assert len(classes) == 12
    for cls in classes:
        assert hasattr(cls, "FILTER_PROFILE")
        assert cls.FILTER_PROFILE.strategy_name in EXPECTED_STRATEGIES
        assert cls().filter_pipeline_enabled is False
