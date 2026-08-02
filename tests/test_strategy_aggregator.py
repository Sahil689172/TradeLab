"""Tests for multi-strategy recommendation aggregation and consensus."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation import (
    ConsensusSignal,
    RecommendationAggregator,
    RecommendationConfig,
    TradeRecommendation,
    build_aggregate_report,
)
from app.strategy_engine.models import SignalType


def _rec(
    *,
    strategy: str,
    signal: SignalType,
    confidence: float,
    trade_id: str,
    entry: float = 100.0,
) -> TradeRecommendation:
    if signal is SignalType.BUY:
        stop, t1, t2 = entry - 5, entry + 10, entry + 20
    elif signal is SignalType.SELL:
        stop, t1, t2 = entry + 5, entry - 10, entry - 20
    else:
        stop, t1, t2 = entry - 5, entry + 10, entry + 20
    return TradeRecommendation(
        strategy_name=strategy,
        symbol="RELIANCE",
        timeframe="15 Minute",
        timestamp=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
        signal=signal,
        entry_price=entry,
        stop_loss=stop,
        target_1=t1,
        target_2=t2,
        risk_reward=2.0,
        confidence=confidence,
        expected_holding_period=8,
        trend_direction=TrendDirection.BULLISH,
        market_structure=TrendDirection.BULLISH,
        reasons=[f"{strategy} reason"],
        trade_id=trade_id,
    )


def test_strong_buy_consensus() -> None:
    config = RecommendationConfig(
        strong_consensus_min_count=5,
        strong_consensus_min_confidence=95.0,
        min_agreement_ratio=0.6,
        min_risk_reward=1.0,
    )
    recs = [
        _rec(strategy="ema_trend", signal=SignalType.BUY, confidence=96.0, trade_id="1"),
        _rec(strategy="vwap", signal=SignalType.BUY, confidence=97.0, trade_id="2"),
        _rec(strategy="cpr", signal=SignalType.BUY, confidence=95.0, trade_id="3"),
        _rec(strategy="momentum", signal=SignalType.BUY, confidence=98.0, trade_id="4"),
        _rec(strategy="relative_strength", signal=SignalType.BUY, confidence=96.0, trade_id="5"),
    ]
    result = RecommendationAggregator(config).aggregate(recs)
    assert result.consensus is ConsensusSignal.STRONG_BUY
    assert result.buy_count == 5
    assert result.confidence >= 90.0
    assert result.recommendation is not None
    assert result.recommendation.signal is SignalType.BUY


def test_conflict_returns_hold() -> None:
    config = RecommendationConfig(min_risk_reward=1.0)
    recs = [
        _rec(strategy="ema_trend", signal=SignalType.BUY, confidence=80.0, trade_id="a"),
        _rec(strategy="supertrend", signal=SignalType.SELL, confidence=80.0, trade_id="b"),
    ]
    result = RecommendationAggregator(config).aggregate(recs)
    assert result.consensus is ConsensusSignal.HOLD
    assert "conflict" in result.explanation.lower()
    assert result.recommendation is None
    report = build_aggregate_report(result, config=config)
    assert "HOLD" in report.body or "conflict" in report.body.lower()


def test_buy_consensus_without_strong() -> None:
    config = RecommendationConfig(
        strong_consensus_min_count=5,
        strong_consensus_min_confidence=95.0,
        min_agreement_ratio=0.5,
        min_risk_reward=1.0,
    )
    recs = [
        _rec(strategy="ema_trend", signal=SignalType.BUY, confidence=70.0, trade_id="1"),
        _rec(strategy="vwap", signal=SignalType.BUY, confidence=72.0, trade_id="2"),
        _rec(strategy="cpr", signal=SignalType.HOLD, confidence=40.0, trade_id="3"),
    ]
    result = RecommendationAggregator(config).aggregate(recs)
    assert result.consensus is ConsensusSignal.BUY
    assert result.buy_count == 2


def test_all_hold() -> None:
    config = RecommendationConfig(min_risk_reward=0.0)
    recs = [
        _rec(strategy="a", signal=SignalType.HOLD, confidence=40.0, trade_id="1"),
        _rec(strategy="b", signal=SignalType.HOLD, confidence=45.0, trade_id="2"),
    ]
    result = RecommendationAggregator(config).aggregate(recs)
    assert result.consensus is ConsensusSignal.HOLD
