"""Tests for TradeRecommendation schema, validation, confidence, and reports."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation import (
    ConfidenceInputs,
    RecommendationConfig,
    TradeRecommendation,
    TradeRecommendationEngine,
    TradeRecommendationValidationError,
    TradeRecommendationValidator,
    build_recommendation_report,
    build_trade_recommendation,
    combine_confidence,
    confidence_to_percent,
)
from app.strategy_engine.models import SignalType, TradePlan


def make_plan(
    *,
    signal: SignalType = SignalType.BUY,
    entry: float = 100.0,
    stop: float = 95.0,
    t1: float = 110.0,
    t2: float = 120.0,
    rr: float = 2.0,
    confidence: float = 0.85,
) -> TradePlan:
    return TradePlan(
        symbol="RELIANCE",
        entry_price=entry,
        signal=signal,
        stop_loss=stop,
        take_profit_1=t1,
        take_profit_2=t2,
        holding_period=8,
        risk_reward=rr,
        confidence=confidence,
        reasons=["EMA20 crossed EMA50", "ADX Strong"],
        strategy_name="ema_trend",
    )


def test_confidence_to_percent() -> None:
    assert confidence_to_percent(0.91) == pytest.approx(91.0)
    assert confidence_to_percent(91.0) == pytest.approx(91.0)


def test_schema_from_trade_plan() -> None:
    plan = make_plan()
    rec = build_trade_recommendation(
        plan,
        timeframe="15 Minute",
        timestamp=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
        trend_direction=TrendDirection.BULLISH,
        market_structure=TrendDirection.BULLISH,
        indicators_used=["ema_20", "ema_50", "adx"],
    )
    assert isinstance(rec, TradeRecommendation)
    assert rec.signal is SignalType.BUY
    assert rec.confidence == pytest.approx(85.0)
    assert rec.trade_id
    assert rec.timeframe == "15 Minute"


def test_buy_geometry_validation() -> None:
    engine = TradeRecommendationEngine(
        RecommendationConfig(min_risk_reward=1.0),
    )
    # Disable confidence recompute so geometry stays BUY-shaped with known conf
    rec = engine.recommend(make_plan(), recompute_confidence=False)
    assert rec.entry_price > rec.stop_loss
    assert rec.target_2 > rec.target_1 > rec.entry_price


def test_reject_invalid_buy_stop() -> None:
    plan = make_plan(stop=105.0)  # stop above entry
    validator = TradeRecommendationValidator(RecommendationConfig(min_risk_reward=0.5))
    rec = build_trade_recommendation(plan)
    with pytest.raises(TradeRecommendationValidationError, match="stop_loss"):
        validator.validate(rec)


def test_reject_low_risk_reward() -> None:
    plan = make_plan(rr=0.5)
    validator = TradeRecommendationValidator(RecommendationConfig(min_risk_reward=1.5))
    rec = build_trade_recommendation(plan)
    with pytest.raises(TradeRecommendationValidationError, match="risk_reward"):
        validator.validate(rec)


def test_reject_duplicate_trade_id() -> None:
    validator = TradeRecommendationValidator()
    plan = make_plan()
    first = build_trade_recommendation(plan, trade_id="abc123")
    validator.validate(first)
    second = build_trade_recommendation(plan, trade_id="abc123")
    with pytest.raises(TradeRecommendationValidationError, match="duplicate"):
        validator.validate(second)


def test_sell_geometry() -> None:
    plan = make_plan(
        signal=SignalType.SELL,
        entry=100.0,
        stop=105.0,
        t1=90.0,
        t2=80.0,
    )
    engine = TradeRecommendationEngine(RecommendationConfig(min_risk_reward=1.0))
    rec = engine.recommend(plan, recompute_confidence=False)
    assert rec.signal is SignalType.SELL
    assert rec.stop_loss > rec.entry_price > rec.target_1 > rec.target_2


def test_confidence_calculation() -> None:
    breakdown = combine_confidence(
        ConfidenceInputs(
            strategy_confidence=90.0,
            trend_strength=100.0,
            volume_score=80.0,
            structure_score=100.0,
            risk_reward_score=100.0,
            confluence_score=70.0,
        ),
        RecommendationConfig(),
    )
    assert 0.0 <= breakdown.total <= 100.0
    assert breakdown.total > 80.0
    assert breakdown.reasons


def test_recommendation_report() -> None:
    engine = TradeRecommendationEngine(RecommendationConfig(min_risk_reward=1.0))
    rec = engine.recommend(
        make_plan(confidence=0.91),
        timeframe="15 Minute",
        trend_direction=TrendDirection.BULLISH,
        market_structure=TrendDirection.BULLISH,
        recompute_confidence=False,
    )
    report = build_recommendation_report(rec)
    assert "Trade Recommendation" in report.body
    assert "RELIANCE" in report.body
    assert "BUY" in report.body
    assert report.confidence == "91"
