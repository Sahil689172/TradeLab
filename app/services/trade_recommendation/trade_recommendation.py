"""Standardize ``TradePlan`` (+ optional context) into ``TradeRecommendation``."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import (
    RecommendationConfig,
    TradeRecommendation,
)
from app.strategy_engine.models import TradePlan


def confidence_to_percent(confidence: float) -> float:
    """Normalize strategy confidence to a 0–100 scale.

    Accepts legacy 0–1 scores and already-percent 0–100 scores.
    """
    if confidence < 0:
        return 0.0
    if confidence <= 1.0:
        return round(confidence * 100.0, 6)
    return float(min(confidence, 100.0))


def build_trade_recommendation(
    plan: TradePlan,
    *,
    timeframe: str | None = None,
    timestamp: datetime | None = None,
    trend_direction: TrendDirection | None = None,
    market_structure: TrendDirection | None = None,
    indicators_used: list[str] | None = None,
    warnings: list[str] | None = None,
    holding_note: str = "",
    trade_id: str | None = None,
    config: RecommendationConfig | None = None,
    confidence_override: float | None = None,
) -> TradeRecommendation:
    """Map a foundation ``TradePlan`` into the canonical recommendation object.

    Does not validate — callers should pass the result through
    ``TradeRecommendationValidator`` / ``TradeRecommendationEngine``.
    """
    cfg = config or RecommendationConfig()
    confidence = (
        float(confidence_override)
        if confidence_override is not None
        else confidence_to_percent(plan.confidence)
    )
    return TradeRecommendation(
        strategy_name=plan.strategy_name,
        symbol=plan.symbol,
        timeframe=(timeframe or cfg.default_timeframe).strip(),
        timestamp=timestamp or datetime.now(timezone.utc),
        signal=plan.signal,
        entry_price=plan.entry_price,
        stop_loss=plan.stop_loss,
        target_1=plan.take_profit_1,
        target_2=plan.take_profit_2,
        risk_reward=plan.risk_reward,
        confidence=confidence,
        expected_holding_period=plan.holding_period,
        holding_note=holding_note,
        trend_direction=trend_direction or TrendDirection.SIDEWAYS,
        market_structure=market_structure or TrendDirection.SIDEWAYS,
        indicators_used=list(indicators_used or []),
        reasons=list(plan.reasons),
        warnings=list(warnings or []),
        trade_id=trade_id or uuid4().hex,
    )


def enrich_from_detailed_plan(
    plan: TradePlan,
    detailed: object | None,
    *,
    timeframe: str | None = None,
    config: RecommendationConfig | None = None,
) -> TradeRecommendation:
    """Build a recommendation, pulling trend/structure/warnings from rich plans."""
    trend = TrendDirection.SIDEWAYS
    structure = TrendDirection.SIDEWAYS
    warnings: list[str] = []
    holding_note = ""
    indicators: list[str] = []
    timestamp: datetime | None = None

    if detailed is not None:
        trend_attr = getattr(detailed, "trend_direction", None) or getattr(
            detailed, "market_structure", None,
        )
        if isinstance(trend_attr, TrendDirection):
            trend = trend_attr
        structure_attr = getattr(detailed, "market_structure", None)
        if isinstance(structure_attr, TrendDirection):
            structure = structure_attr
        note = getattr(detailed, "holding_note", None)
        if isinstance(note, str):
            holding_note = note
        ts = getattr(detailed, "timestamp", None)
        if isinstance(ts, datetime):
            timestamp = ts
        setup = getattr(detailed, "setup", None)
        if setup is not None:
            for flag, warning in (
                (getattr(setup, "false_breakout", False), "False breakout risk"),
                (getattr(setup, "sideways_blocked", False), "Sideways market filter"),
                (getattr(setup, "late_session", False), "Late session entry"),
            ):
                if flag:
                    warnings.append(warning)

        for attr in (
            "strategy_name",
            "current_box",
            "vwap",
            "cpr",
            "opening_range",
            "snapshot",
        ):
            if getattr(detailed, attr, None) is not None and attr != "strategy_name":
                indicators.append(attr)

    return build_trade_recommendation(
        plan,
        timeframe=timeframe,
        timestamp=timestamp,
        trend_direction=trend,
        market_structure=structure,
        indicators_used=indicators,
        warnings=warnings,
        holding_note=holding_note,
        config=config,
    )
