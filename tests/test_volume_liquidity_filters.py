"""Unit tests for Phase A4X.3 Volume & Liquidity Filters."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.strategy_engine.filters import (
    FilterBase,
    FilterPipeline,
    FilterValidationError,
    GapFilter,
    LiquidityFilter,
    MinimumVolumeFilter,
    OBVConfirmationFilter,
    RelativeVolumeFilter,
    StocksInPlayFilter,
    StrategyRecommendation,
    VolumeSMAFilter,
    VWAPConfirmationFilter,
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


VOLUME_FILTERS = (
    RelativeVolumeFilter,
    VolumeSMAFilter,
    OBVConfirmationFilter,
    VWAPConfirmationFilter,
    StocksInPlayFilter,
    LiquidityFilter,
    MinimumVolumeFilter,
    GapFilter,
)


def test_all_volume_filters_inherit_filter_base() -> None:
    for cls in VOLUME_FILTERS:
        assert issubclass(cls, FilterBase)


def test_relative_volume_pass_fail_and_config() -> None:
    filt = RelativeVolumeFilter(min_relative_volume=1.5)
    filt.validate(_rec(metadata={"relative_volume_20": 2.0}))
    with pytest.raises(FilterValidationError, match="below"):
        filt.validate(_rec(metadata={"relative_volume_20": 1.1}))
    filt2 = RelativeVolumeFilter(min_relative_volume=1.0, max_relative_volume=3.0)
    with pytest.raises(FilterValidationError, match="above"):
        filt2.validate(_rec(metadata={"relative_volume_20": 4.0}))


def test_volume_sma_ratio() -> None:
    filt = VolumeSMAFilter(min_volume_vs_sma=1.2)
    filt.validate(_rec(metadata={"volume": 1_200_000, "volume_sma_20": 1_000_000}))
    with pytest.raises(FilterValidationError, match="ratio"):
        filt.validate(_rec(metadata={"volume": 1_000_000, "volume_sma_20": 1_000_000}))


def test_obv_confirmation_buy_sell() -> None:
    buy_filt = OBVConfirmationFilter()
    buy_filt.validate(_rec(signal=SignalType.BUY, metadata={"obv": 100, "obv_prev": 90}))
    with pytest.raises(FilterValidationError, match="rising OBV"):
        buy_filt.validate(_rec(signal=SignalType.BUY, metadata={"obv": 80, "obv_prev": 90}))

    sell = _rec(signal=SignalType.SELL, metadata={"obv_slope": -10.0})
    buy_filt.validate(sell)
    with pytest.raises(FilterValidationError, match="falling OBV"):
        buy_filt.validate(_rec(signal=SignalType.SELL, metadata={"obv_slope": 5.0}))


def test_vwap_confirmation() -> None:
    filt = VWAPConfirmationFilter()
    filt.validate(_rec(metadata={"vwap": 98.0, "close": 100.0}))
    with pytest.raises(FilterValidationError, match="below VWAP"):
        filt.validate(_rec(metadata={"vwap": 105.0, "close": 100.0}))
    filt.validate(_rec(signal=SignalType.SELL, metadata={"vwap": 105.0, "close": 100.0}))
    with pytest.raises(FilterValidationError, match="above VWAP"):
        filt.validate(_rec(signal=SignalType.SELL, metadata={"vwap": 95.0, "close": 100.0}))


def test_stocks_in_play() -> None:
    filt = StocksInPlayFilter(min_relative_volume=2.0, min_range_pct=2.0, min_price=50.0)
    ok = _rec(
        metadata={
            "relative_volume_20": 2.5,
            "range_pct": 3.0,
            "close": 100.0,
        },
    )
    filt.validate(ok)
    out = filt.apply(ok)
    assert out.metadata["filter_stocks_in_play"] is True

    with pytest.raises(FilterValidationError, match="rvol"):
        filt.validate(_rec(metadata={"relative_volume_20": 1.0, "range_pct": 5.0}))


def test_stocks_in_play_range_or_gap() -> None:
    filt = StocksInPlayFilter(
        min_relative_volume=2.0,
        min_range_pct=5.0,
        min_abs_gap_pct=2.0,
        require_range_or_gap=True,
    )
    # weak range but strong gap
    filt.validate(
        _rec(metadata={"relative_volume_20": 2.5, "range_pct": 1.0, "gap_pct": 2.5}),
    )


def test_liquidity_avg_dollar_volume() -> None:
    filt = LiquidityFilter(min_avg_dollar_volume=10_000_000)
    filt.validate(_rec(metadata={"avg_dollar_volume": 25_000_000}))
    # derive from volume_sma * price
    filt.validate(_rec(metadata={"volume_sma_20": 150_000, "close": 100.0}))
    with pytest.raises(FilterValidationError, match="avg dollar volume"):
        filt.validate(_rec(metadata={"avg_dollar_volume": 1_000_000}))


def test_minimum_volume() -> None:
    filt = MinimumVolumeFilter(min_volume=100_000)
    filt.validate(_rec(metadata={"volume": 250_000}))
    with pytest.raises(FilterValidationError, match="below min"):
        filt.validate(_rec(metadata={"volume": 10_000}))


def test_gap_filter_max_and_min() -> None:
    filt = GapFilter(max_abs_gap_pct=5.0, min_abs_gap_pct=0.0)
    filt.validate(_rec(metadata={"gap_pct": 2.0}))
    with pytest.raises(FilterValidationError, match="above max"):
        filt.validate(_rec(metadata={"gap_pct": 8.0}))

    gap_go = GapFilter(max_abs_gap_pct=None, min_abs_gap_pct=1.5)
    with pytest.raises(FilterValidationError, match="below min"):
        gap_go.validate(_rec(metadata={"gap_pct": 0.5}))
    gap_go.validate(_rec(metadata={"gap_pct": -2.0}))


def test_enable_disable_skips_in_pipeline() -> None:
    rvol = RelativeVolumeFilter(enabled=False, min_relative_volume=5.0)
    vmin = MinimumVolumeFilter(min_volume=1000)
    pipeline = FilterPipeline(filters=[rvol, vmin])
    # Would fail rvol if enabled
    result = pipeline.run(_rec(metadata={"relative_volume_20": 1.0, "volume": 50_000}))
    assert result.output.rejected is False
    assert result.filters_skipped == 1


def test_volume_pipeline_chain() -> None:
    pipeline = FilterPipeline(
        filters=[
            RelativeVolumeFilter(priority=1, min_relative_volume=1.5),
            VolumeSMAFilter(priority=2, min_volume_vs_sma=1.0),
            VWAPConfirmationFilter(priority=3),
            MinimumVolumeFilter(priority=4, min_volume=50_000),
            GapFilter(priority=5, max_abs_gap_pct=10.0),
        ],
    )
    rec = _rec(
        metadata={
            "relative_volume_20": 2.0,
            "volume": 200_000,
            "volume_sma_20": 100_000,
            "vwap": 99.0,
            "close": 100.0,
            "gap_pct": 1.0,
        },
    )
    result = pipeline.run(rec)
    assert result.filters_applied == 5
    assert result.output.rejected is False
    assert len(result.output.filter_notes) == 5


def test_hold_skips_volume_filters() -> None:
    for cls in VOLUME_FILTERS:
        cls().validate(_rec(signal=SignalType.HOLD, metadata={}))
