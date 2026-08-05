"""Unit tests for Phase A4X.2 Trend & Regime Filters."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.market_structure.schemas import TrendDirection
from app.strategy_engine.filters import (
    ADXFilter,
    EMA200Filter,
    FilterBase,
    FilterPipeline,
    FilterRegistry,
    FilterValidationError,
    SMA200Filter,
    SidewaysMarketFilter,
    StrategyRecommendation,
    TrendingMarketFilter,
    VolatilityRegime,
    VolatilityRegimeFilter,
)
from app.strategy_engine.models import SignalType


def _rec(
    *,
    signal: SignalType = SignalType.BUY,
    price: float = 100.0,
    metadata: dict | None = None,
) -> StrategyRecommendation:
    return StrategyRecommendation(
        strategy_name="stub",
        symbol="RELIANCE",
        timestamp=datetime(2022, 6, 1, tzinfo=timezone.utc),
        signal=signal,
        entry_price=price,
        stop_loss=price * 0.95,
        take_profit_1=price * 1.05,
        take_profit_2=price * 1.10,
        holding_period=10,
        risk_reward=2.0,
        confidence=0.8,
        reasons=["unit test"],
        metadata=metadata or {},
    )


def test_all_filters_inherit_filter_base() -> None:
    classes = (
        EMA200Filter,
        SMA200Filter,
        ADXFilter,
        TrendingMarketFilter,
        SidewaysMarketFilter,
        VolatilityRegimeFilter,
    )
    for cls in classes:
        assert issubclass(cls, FilterBase)


def test_ema200_pass_and_fail() -> None:
    filt = EMA200Filter(min_distance_pct=0.0)
    ok = _rec(metadata={"ema_200": 95.0, "close": 100.0})
    filt.validate(ok)
    out = filt.apply(ok)
    assert "ema200: pass" in out.filter_notes[0]

    bad = _rec(metadata={"ema_200": 105.0, "close": 100.0})
    with pytest.raises(FilterValidationError, match="below EMA200"):
        filt.validate(bad)


def test_ema200_enable_disable() -> None:
    filt = EMA200Filter()
    assert filt.enabled
    filt.disable()
    assert not filt.enabled
    registry = FilterRegistry([filt, SMA200Filter()])
    assert [f.name for f in registry.list_enabled()] == ["sma200"]
    filt.enable()
    assert "ema200" in {f.name for f in registry.list_enabled()}


def test_sma200_configurable_threshold() -> None:
    filt = SMA200Filter(min_distance_pct=2.0)
    # price must be >= sma * 1.02
    with pytest.raises(FilterValidationError):
        filt.validate(_rec(metadata={"sma_200": 100.0, "close": 101.0}))
    filt.validate(_rec(metadata={"sma_200": 100.0, "close": 103.0}))


def test_adx_min_threshold() -> None:
    filt = ADXFilter(min_adx=25.0)
    with pytest.raises(FilterValidationError, match="below min_adx"):
        filt.validate(_rec(metadata={"adx_14": 18.0}))
    out = filt.apply(_rec(metadata={"adx_14": 30.0}))
    assert out.metadata["filter_adx"] == pytest.approx(30.0)


def test_adx_max_threshold() -> None:
    filt = ADXFilter(min_adx=20.0, max_adx=40.0)
    with pytest.raises(FilterValidationError, match="above max_adx"):
        filt.validate(_rec(metadata={"adx_14": 55.0}))


def test_trending_market_rejects_sideways() -> None:
    filt = TrendingMarketFilter()
    with pytest.raises(FilterValidationError, match="not in allowed"):
        filt.validate(_rec(metadata={"trend_direction": TrendDirection.SIDEWAYS}))
    out = filt.apply(_rec(metadata={"trend_direction": "BULLISH"}))
    assert out.metadata["filter_trend"] == "BULLISH"


def test_trending_require_bullish_for_buy() -> None:
    filt = TrendingMarketFilter(require_bullish_for_buy=True)
    with pytest.raises(FilterValidationError, match="BUY requires BULLISH"):
        filt.validate(_rec(metadata={"trend_direction": "BEARISH"}))


def test_sideways_market_requires_sideways() -> None:
    filt = SidewaysMarketFilter()
    with pytest.raises(FilterValidationError, match="not sideways"):
        filt.validate(_rec(metadata={"trend_direction": "BULLISH"}))
    out = filt.apply(_rec(metadata={"trend_direction": TrendDirection.SIDEWAYS}))
    assert "sideways" in out.filter_notes[0]


def test_volatility_regime_atr_classification() -> None:
    filt = VolatilityRegimeFilter(
        low_atr_pct_max=1.0,
        high_atr_pct_min=3.0,
        allowed_regimes=(VolatilityRegime.NORMAL.value,),
    )
    # atr 2 on price 100 => 2% => NORMAL
    ok = _rec(metadata={"atr_14": 2.0, "close": 100.0})
    assert filt.classify(ok) is VolatilityRegime.NORMAL
    filt.validate(ok)

    high = _rec(metadata={"atr_14": 5.0, "close": 100.0})
    assert filt.classify(high) is VolatilityRegime.HIGH
    with pytest.raises(FilterValidationError, match="HIGH"):
        filt.validate(high)


def test_volatility_only_low_allowed() -> None:
    filt = VolatilityRegimeFilter(allowed_regimes=("LOW",))
    low = _rec(metadata={"atr_14": 0.5, "close": 100.0})
    filt.validate(low)
    with pytest.raises(FilterValidationError):
        filt.validate(_rec(metadata={"atr_14": 2.0, "close": 100.0}))


def test_hold_skips_hard_checks() -> None:
    filt = EMA200Filter()
    # missing ema metadata — HOLD should not fail validate
    filt.validate(_rec(signal=SignalType.HOLD, metadata={}))


def test_pipeline_chain_trend_filters() -> None:
    registry = FilterRegistry(
        [
            EMA200Filter(priority=10),
            ADXFilter(priority=20, min_adx=20.0),
            TrendingMarketFilter(priority=30),
            VolatilityRegimeFilter(
                priority=40,
                allowed_regimes=("LOW", "NORMAL", "HIGH"),
            ),
        ],
    )
    pipeline = FilterPipeline(registry)
    rec = _rec(
        metadata={
            "ema_200": 90.0,
            "close": 100.0,
            "adx_14": 28.0,
            "trend_direction": "BULLISH",
            "atr_14": 1.5,
        },
    )
    result = pipeline.run(rec)
    assert result.filters_applied == 4
    assert result.output.rejected is False
    assert len(result.output.filter_notes) == 4


def test_pipeline_rejects_on_failed_filter() -> None:
    pipeline = FilterPipeline(
        filters=[
            EMA200Filter(priority=1),
            ADXFilter(priority=2, min_adx=25.0),
        ],
    )
    result = pipeline.run(
        _rec(metadata={"ema_200": 90.0, "close": 100.0, "adx_14": 10.0}),
    )
    assert result.output.rejected is True
    assert "min_adx" in result.output.rejection_reason


def test_disabled_filter_not_applied() -> None:
    ema = EMA200Filter(enabled=False)
    adx = ADXFilter(min_adx=20.0)
    pipeline = FilterPipeline(filters=[ema, adx])
    # Would fail EMA (price below) if enabled
    result = pipeline.run(
        _rec(metadata={"ema_200": 120.0, "close": 100.0, "adx_14": 30.0}),
    )
    assert result.output.rejected is False
    assert result.filters_skipped == 1
    assert result.filters_applied == 1
