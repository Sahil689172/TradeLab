"""Unit tests for Phase A4X.5 Higher Timeframe Confirmation filters."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.strategy_engine.filters import (
    DailyConfirmationFilter,
    FilterBase,
    FilterPipeline,
    FilterValidationError,
    HigherTimeframeTrendFilter,
    MultiTimeframeEMAFilter,
    MultiTimeframeRSIFilter,
    MultiTimeframeSuperTrendFilter,
    StrategyRecommendation,
    WeeklyConfirmationFilter,
    request_confirmations,
    requested_confirmations,
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
        stop_loss=price * 0.95 if signal is SignalType.BUY else price * 1.05,
        take_profit_1=price * 1.10 if signal is SignalType.BUY else price * 0.90,
        take_profit_2=price * 1.15 if signal is SignalType.BUY else price * 0.85,
        holding_period=10,
        risk_reward=2.0,
        confidence=0.8,
        reasons=["unit test"],
        metadata=metadata or {},
    )


HTF_FILTERS = (
    HigherTimeframeTrendFilter,
    DailyConfirmationFilter,
    WeeklyConfirmationFilter,
    MultiTimeframeEMAFilter,
    MultiTimeframeRSIFilter,
    MultiTimeframeSuperTrendFilter,
)


def test_all_htf_filters_inherit_filter_base() -> None:
    for cls in HTF_FILTERS:
        assert issubclass(cls, FilterBase)


def test_strategy_can_request_confirmations() -> None:
    rec = request_confirmations(
        _rec(),
        "daily",
        "mtf_ema",
        snapshot={
            "daily_trend": "BULLISH",
            "daily_ema_fast": 105.0,
            "daily_ema_slow": 100.0,
        },
    )
    assert requested_confirmations(rec) == {"daily", "mtf_ema"}
    assert rec.metadata["daily_trend"] == "BULLISH"


def test_htf_trend_buy_sell() -> None:
    filt = HigherTimeframeTrendFilter()
    filt.validate(_rec(metadata={"htf_trend": "BULLISH"}))
    with pytest.raises(FilterValidationError, match="HTF BULLISH"):
        filt.validate(_rec(metadata={"htf_trend": "BEARISH"}))
    filt.validate(_rec(signal=SignalType.SELL, metadata={"htf_trend": "BEARISH"}))


def test_daily_and_weekly_confirmation() -> None:
    daily = DailyConfirmationFilter()
    weekly = WeeklyConfirmationFilter()
    daily.validate(_rec(metadata={"daily_trend": "BULLISH"}))
    weekly.validate(_rec(metadata={"weekly_trend": "BULLISH"}))
    with pytest.raises(FilterValidationError, match="daily BULLISH"):
        daily.validate(_rec(metadata={"daily_trend": "SIDEWAYS"}))
    with pytest.raises(FilterValidationError, match="weekly BULLISH"):
        weekly.validate(_rec(metadata={"weekly_trend": "BEARISH"}))


def test_mtf_ema_alignment() -> None:
    filt = MultiTimeframeEMAFilter(require_htf_stack=True)
    filt.validate(
        _rec(metadata={"htf_ema_fast": 110.0, "htf_ema_slow": 100.0}),
    )
    with pytest.raises(FilterValidationError, match="HTF EMA not bullish"):
        filt.validate(
            _rec(metadata={"htf_ema_fast": 90.0, "htf_ema_slow": 100.0}),
        )


def test_mtf_rsi_bands() -> None:
    filt = MultiTimeframeRSIFilter(buy_min_rsi=45.0, buy_max_rsi=70.0)
    filt.validate(_rec(metadata={"htf_rsi": 55.0}))
    with pytest.raises(FilterValidationError, match="BUY RSI"):
        filt.validate(_rec(metadata={"htf_rsi": 80.0}))
    sell = MultiTimeframeRSIFilter()
    sell.validate(_rec(signal=SignalType.SELL, metadata={"daily_rsi": 40.0}))


def test_mtf_supertrend() -> None:
    filt = MultiTimeframeSuperTrendFilter()
    filt.validate(
        _rec(
            metadata={
                "htf_supertrend_direction": "BULLISH",
                "htf_supertrend": 95.0,
                "htf_close": 100.0,
            },
        ),
    )
    with pytest.raises(FilterValidationError, match="bullish HTF SuperTrend"):
        filt.validate(
            _rec(
                metadata={
                    "htf_supertrend_direction": "BEARISH",
                    "htf_supertrend": 95.0,
                    "htf_close": 100.0,
                },
            ),
        )
    with pytest.raises(FilterValidationError, match="below ST"):
        filt.validate(
            _rec(
                metadata={
                    "htf_supertrend_direction": "UP",
                    "htf_supertrend": 105.0,
                    "htf_close": 100.0,
                },
            ),
        )


def test_only_when_requested_skips_without_request() -> None:
    filt = DailyConfirmationFilter(only_when_requested=True)
    # No request + missing daily_trend would fail if evaluated — should skip
    filt.validate(_rec(metadata={}))
    out = filt.apply(_rec(metadata={}))
    assert "not requested" in out.filter_notes[0]


def test_only_when_requested_enforces_when_requested() -> None:
    filt = DailyConfirmationFilter(only_when_requested=True)
    rec = request_confirmations(
        _rec(metadata={"daily_trend": "BEARISH"}),
        "daily",
    )
    with pytest.raises(FilterValidationError, match="daily BULLISH"):
        filt.validate(rec)


def test_htf_pipeline_with_strategy_request() -> None:
    pipeline = FilterPipeline(
        filters=[
            DailyConfirmationFilter(priority=1, only_when_requested=True),
            WeeklyConfirmationFilter(priority=2, only_when_requested=True),
            MultiTimeframeEMAFilter(priority=3, only_when_requested=True),
            MultiTimeframeRSIFilter(priority=4, only_when_requested=True),
        ],
    )
    rec = request_confirmations(
        _rec(),
        "daily",
        "mtf_ema",
        snapshot={
            "daily_trend": "BULLISH",
            "htf_ema_fast": 102.0,
            "htf_ema_slow": 98.0,
            # weekly / rsi not requested — filters skip
        },
    )
    result = pipeline.run(rec)
    assert result.output.rejected is False
    # daily + mtf_ema applied; weekly + rsi skipped as not requested
    assert result.filters_applied == 4  # skipped still calls apply with note
    notes = " ".join(result.output.filter_notes)
    assert "daily_confirmation: pass" in notes
    assert "mtf_ema: pass" in notes
    assert "not requested" in notes


def test_hold_skips_htf_filters() -> None:
    for cls in HTF_FILTERS:
        cls().validate(_rec(signal=SignalType.HOLD, metadata={}))
