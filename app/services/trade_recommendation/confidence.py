"""Confidence engine — blend strategy + context scores into a 0–100 total."""

from __future__ import annotations

from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import (
    ConfidenceBreakdown,
    ConfidenceInputs,
    RecommendationConfig,
    TradeRecommendation,
)
from app.strategy_engine.models import SignalType


def risk_reward_to_score(risk_reward: float, *, target: float = 2.0) -> float:
    """Map RR to 0–100 (target RR → 100, clipped)."""
    if risk_reward <= 0 or target <= 0:
        return 0.0
    return float(min(100.0, (risk_reward / target) * 100.0))


def structure_to_score(
    structure: TrendDirection,
    *,
    signal: SignalType,
) -> float:
    """Reward structure aligned with the trade direction."""
    if signal is SignalType.BUY:
        if structure is TrendDirection.BULLISH:
            return 100.0
        if structure is TrendDirection.SIDEWAYS:
            return 40.0
        return 10.0
    if signal is SignalType.SELL:
        if structure is TrendDirection.BEARISH:
            return 100.0
        if structure is TrendDirection.SIDEWAYS:
            return 40.0
        return 10.0
    return 50.0


def trend_to_score(
    trend: TrendDirection,
    *,
    signal: SignalType,
) -> float:
    return structure_to_score(trend, signal=signal)


def build_confidence_inputs(
    recommendation: TradeRecommendation,
    *,
    volume_score: float = 50.0,
    confluence_score: float = 50.0,
    rr_target: float = 2.0,
) -> ConfidenceInputs:
    return ConfidenceInputs(
        strategy_confidence=recommendation.confidence,
        trend_strength=trend_to_score(
            recommendation.trend_direction,
            signal=recommendation.signal,
        ),
        volume_score=volume_score,
        structure_score=structure_to_score(
            recommendation.market_structure,
            signal=recommendation.signal,
        ),
        risk_reward_score=risk_reward_to_score(
            recommendation.risk_reward,
            target=rr_target,
        ),
        confluence_score=confluence_score,
    )


def combine_confidence(
    inputs: ConfidenceInputs,
    config: RecommendationConfig | None = None,
) -> ConfidenceBreakdown:
    """Weighted blend of confidence inputs → final 0–100 score."""
    cfg = config or RecommendationConfig()
    weights = {
        "strategy": cfg.weight_strategy,
        "trend": cfg.weight_trend,
        "volume": cfg.weight_volume,
        "structure": cfg.weight_structure,
        "risk_reward": cfg.weight_risk_reward,
        "confluence": cfg.weight_confluence,
    }
    total_weight = sum(weights.values())
    raw = {
        "strategy": inputs.strategy_confidence * weights["strategy"],
        "trend": inputs.trend_strength * weights["trend"],
        "volume": inputs.volume_score * weights["volume"],
        "structure": inputs.structure_score * weights["structure"],
        "risk_reward": inputs.risk_reward_score * weights["risk_reward"],
        "confluence": inputs.confluence_score * weights["confluence"],
    }
    total = sum(raw.values()) / total_weight if total_weight else 0.0
    total = float(max(0.0, min(100.0, total)))
    # Normalize component display to contribution share of final (optional clarity)
    reasons = [
        f"Strategy: {inputs.strategy_confidence:.1f} (w={weights['strategy']:g})",
        f"Trend: {inputs.trend_strength:.1f} (w={weights['trend']:g})",
        f"Volume: {inputs.volume_score:.1f} (w={weights['volume']:g})",
        f"Structure: {inputs.structure_score:.1f} (w={weights['structure']:g})",
        f"Risk/Reward: {inputs.risk_reward_score:.1f} (w={weights['risk_reward']:g})",
        f"Confluence: {inputs.confluence_score:.1f} (w={weights['confluence']:g})",
    ]
    return ConfidenceBreakdown(
        strategy=inputs.strategy_confidence,
        trend=inputs.trend_strength,
        volume=inputs.volume_score,
        structure=inputs.structure_score,
        risk_reward=inputs.risk_reward_score,
        confluence=inputs.confluence_score,
        total=total,
        reasons=reasons,
    )
