"""Unit tests for Phase A4X.4 Risk Management Filters."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.strategy_engine.filters import (
    ATRStopFilter,
    ATRTrailingStopFilter,
    FilterBase,
    FilterPipeline,
    FilterValidationError,
    FixedStopFilter,
    MaximumDrawdownFilter,
    MaximumPortfolioExposureFilter,
    MinimumConfidenceFilter,
    MinimumPositionSizeFilter,
    RiskRewardFilter,
    StrategyRecommendation,
)
from app.strategy_engine.models import SignalType


def _rec(
    *,
    signal: SignalType = SignalType.BUY,
    price: float = 100.0,
    stop: float | None = None,
    target: float | None = None,
    confidence: float = 0.8,
    risk_reward: float = 2.0,
    metadata: dict | None = None,
) -> StrategyRecommendation:
    if stop is None:
        stop = price * 0.95 if signal is SignalType.BUY else price * 1.05
    if target is None:
        target = price * 1.10 if signal is SignalType.BUY else price * 0.90
    return StrategyRecommendation(
        strategy_name="stub",
        symbol="RELIANCE",
        timestamp=datetime(2022, 6, 1, tzinfo=timezone.utc),
        signal=signal,
        entry_price=price,
        stop_loss=stop,
        take_profit_1=target,
        take_profit_2=target * 1.05 if signal is SignalType.BUY else target * 0.95,
        holding_period=10,
        risk_reward=risk_reward,
        confidence=confidence,
        reasons=["unit test"],
        metadata=metadata or {},
    )


RISK_FILTERS = (
    ATRStopFilter,
    ATRTrailingStopFilter,
    FixedStopFilter,
    RiskRewardFilter,
    MaximumDrawdownFilter,
    MinimumConfidenceFilter,
    MaximumPortfolioExposureFilter,
    MinimumPositionSizeFilter,
)


def test_all_risk_filters_inherit_filter_base() -> None:
    for cls in RISK_FILTERS:
        assert issubclass(cls, FilterBase)


def test_atr_stop_enforces_and_rejects_tight_stop() -> None:
    # atr=2, mult=1.5 → distance=3 → BUY stop=97
    filt = ATRStopFilter(atr_multiplier=1.5, enforce_stop=True)
    ok = _rec(stop=95.0, metadata={"atr_14": 2.0})
    filt.validate(ok)
    out = filt.apply(ok)
    assert out.stop_loss == pytest.approx(97.0)
    assert out.metadata["filter_atr_stop"] == pytest.approx(97.0)

    tight = _rec(stop=98.0, metadata={"atr_14": 2.0})
    with pytest.raises(FilterValidationError, match="tighter than ATR"):
        filt.validate(tight)


def test_atr_trailing_stop_from_extreme() -> None:
    filt = ATRTrailingStopFilter(atr_multiplier=2.0, enforce_trail=True)
    rec = _rec(
        stop=90.0,
        metadata={"atr_14": 2.0, "highest_high_since_entry": 110.0, "close": 108.0},
    )
    # trail = 110 - 4 = 106
    filt.validate(rec)
    out = filt.apply(rec)
    assert out.stop_loss == pytest.approx(106.0)

    # tighten_only: prior trail 107 should not loosen to 106
    prior = _rec(
        stop=90.0,
        metadata={
            "atr_14": 2.0,
            "highest_high_since_entry": 110.0,
            "close": 108.0,
            "trailing_stop": 107.0,
        },
    )
    out2 = filt.apply(prior)
    assert out2.stop_loss == pytest.approx(107.0)


def test_fixed_stop_pct_and_points() -> None:
    pct = FixedStopFilter(stop_pct=0.02, enforce_stop=True)
    out = pct.apply(_rec(stop=90.0))
    assert out.stop_loss == pytest.approx(98.0)

    pts = FixedStopFilter(stop_pct=None, stop_points=5.0, enforce_stop=True)
    out2 = pts.apply(_rec(stop=90.0))
    assert out2.stop_loss == pytest.approx(95.0)


def test_risk_reward_min_threshold() -> None:
    # entry 100, stop 95, target 110 → rr=2.0
    filt = RiskRewardFilter(min_risk_reward=1.5)
    ok = _rec(stop=95.0, target=110.0)
    filt.validate(ok)
    out = filt.apply(ok)
    assert out.risk_reward == pytest.approx(2.0)

    bad = _rec(stop=95.0, target=102.0)  # rr=0.4
    with pytest.raises(FilterValidationError, match="risk/reward"):
        filt.validate(bad)


def test_maximum_drawdown() -> None:
    filt = MaximumDrawdownFilter(max_drawdown_pct=10.0)
    filt.validate(_rec(metadata={"portfolio_drawdown_pct": 8.0}))
    with pytest.raises(FilterValidationError, match="drawdown"):
        filt.validate(_rec(metadata={"portfolio_drawdown_pct": 12.0}))
    # SELL not blocked when block_new_entries_only
    filt.validate(
        _rec(signal=SignalType.SELL, stop=105.0, target=90.0, metadata={"portfolio_drawdown_pct": 12.0}),
    )


def test_minimum_confidence() -> None:
    filt = MinimumConfidenceFilter(min_confidence=0.6)
    filt.validate(_rec(confidence=0.75))
    with pytest.raises(FilterValidationError, match="confidence"):
        filt.validate(_rec(confidence=0.4))


def test_maximum_portfolio_exposure() -> None:
    filt = MaximumPortfolioExposureFilter(
        max_exposure_pct=50.0,
        max_single_position_pct=25.0,
    )
    filt.validate(
        _rec(
            metadata={
                "current_exposure_pct": 20.0,
                "proposed_exposure_pct": 20.0,
            },
        ),
    )
    with pytest.raises(FilterValidationError, match="single-name"):
        filt.validate(_rec(metadata={"proposed_exposure_pct": 30.0, "current_exposure_pct": 0.0}))
    with pytest.raises(FilterValidationError, match="total exposure"):
        filt.validate(
            _rec(
                metadata={
                    "current_exposure_pct": 40.0,
                    "proposed_exposure_pct": 20.0,
                },
            ),
        )
    # derive from notional/equity
    filt.validate(
        _rec(
            metadata={
                "current_exposure_pct": 10.0,
                "position_notional": 10_000,
                "equity": 100_000,
            },
        ),
    )


def test_minimum_position_size() -> None:
    filt = MinimumPositionSizeFilter(min_quantity=1.0, min_notional=5_000.0, require_notional=True)
    filt.validate(_rec(metadata={"position_size": 10, "position_notional": 10_000}))
    with pytest.raises(FilterValidationError, match="position size"):
        filt.validate(_rec(metadata={"position_size": 0.5, "position_notional": 10_000}))
    with pytest.raises(FilterValidationError, match="notional"):
        filt.validate(_rec(metadata={"position_size": 5, "position_notional": 1000}))


def test_enable_disable() -> None:
    filt = MinimumConfidenceFilter(min_confidence=0.99, enabled=False)
    pipeline = FilterPipeline(filters=[filt, RiskRewardFilter(min_risk_reward=1.0)])
    result = pipeline.run(_rec(confidence=0.1, stop=95.0, target=110.0))
    assert result.output.rejected is False
    assert result.filters_skipped == 1


def test_risk_pipeline_chain() -> None:
    pipeline = FilterPipeline(
        filters=[
            ATRStopFilter(priority=1, atr_multiplier=1.5, enforce_stop=True),
            RiskRewardFilter(priority=2, min_risk_reward=1.0),
            MinimumConfidenceFilter(priority=3, min_confidence=0.5),
            MinimumPositionSizeFilter(priority=4, min_quantity=1.0),
            MaximumPortfolioExposureFilter(
                priority=5,
                max_exposure_pct=100.0,
                max_single_position_pct=50.0,
            ),
        ],
    )
    # After ATR enforce stop=97; target 110 → rr=(110-100)/(100-97)=3.33
    rec = _rec(
        stop=95.0,
        target=110.0,
        confidence=0.7,
        metadata={
            "atr_14": 2.0,
            "position_size": 5,
            "current_exposure_pct": 10.0,
            "proposed_exposure_pct": 15.0,
        },
    )
    result = pipeline.run(rec)
    assert result.filters_applied == 5
    assert result.output.rejected is False
    assert result.output.stop_loss == pytest.approx(97.0)


def test_hold_skips_risk_filters() -> None:
    for cls in RISK_FILTERS:
        cls().validate(_rec(signal=SignalType.HOLD, metadata={}))
