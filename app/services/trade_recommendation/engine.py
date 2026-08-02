"""Trade Recommendation Engine — validate + standardize TradePlan outputs."""

from __future__ import annotations

from datetime import datetime

from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.confidence import (
    build_confidence_inputs,
    combine_confidence,
)
from app.services.trade_recommendation.schemas import (
    ConfidenceBreakdown,
    RecommendationConfig,
    TradeRecommendation,
)
from app.services.trade_recommendation.trade_recommendation import (
    enrich_from_detailed_plan,
    build_trade_recommendation,
)
from app.services.trade_recommendation.validator import (
    TradeRecommendationValidationError,
    TradeRecommendationValidator,
)
from app.strategy_engine.models import TradePlan


class TradeRecommendationEngine:
    """Final output layer: TradePlan → validated TradeRecommendation.

    Backtesting / Monte Carlo / Paper / Live / Frontend / AI must consume
    ``TradeRecommendation`` objects produced here — never raw strategy plans.
    """

    def __init__(
        self,
        config: RecommendationConfig | None = None,
        *,
        validator: TradeRecommendationValidator | None = None,
    ) -> None:
        self._config = config or RecommendationConfig()
        self._validator = validator or TradeRecommendationValidator(self._config)

    @property
    def config(self) -> RecommendationConfig:
        return self._config

    @property
    def validator(self) -> TradeRecommendationValidator:
        return self._validator

    def recommend(
        self,
        plan: TradePlan,
        *,
        timeframe: str | None = None,
        timestamp: datetime | None = None,
        trend_direction: TrendDirection | None = None,
        market_structure: TrendDirection | None = None,
        indicators_used: list[str] | None = None,
        warnings: list[str] | None = None,
        holding_note: str = "",
        detailed_plan: object | None = None,
        volume_score: float = 50.0,
        confluence_score: float = 50.0,
        recompute_confidence: bool = True,
    ) -> TradeRecommendation:
        """Standardize → optional confidence blend → validate → return."""
        if detailed_plan is not None:
            recommendation = enrich_from_detailed_plan(
                plan,
                detailed_plan,
                timeframe=timeframe,
                config=self._config,
            )
            # Allow explicit overrides to win
            updates: dict[str, object] = {}
            if trend_direction is not None:
                updates["trend_direction"] = trend_direction
            if market_structure is not None:
                updates["market_structure"] = market_structure
            if indicators_used is not None:
                updates["indicators_used"] = indicators_used
            if warnings is not None:
                updates["warnings"] = warnings
            if holding_note:
                updates["holding_note"] = holding_note
            if timestamp is not None:
                updates["timestamp"] = timestamp
            if updates:
                recommendation = recommendation.model_copy(update=updates)
        else:
            recommendation = build_trade_recommendation(
                plan,
                timeframe=timeframe,
                timestamp=timestamp,
                trend_direction=trend_direction,
                market_structure=market_structure,
                indicators_used=indicators_used,
                warnings=warnings,
                holding_note=holding_note,
                config=self._config,
            )

        if recompute_confidence:
            breakdown = self.score_confidence(
                recommendation,
                volume_score=volume_score,
                confluence_score=confluence_score,
            )
            recommendation = recommendation.model_copy(
                update={"confidence": breakdown.total},
            )

        return self._validator.validate(recommendation)

    def from_recommendation(
        self,
        recommendation: TradeRecommendation,
        *,
        recompute_confidence: bool = False,
        volume_score: float = 50.0,
        confluence_score: float = 50.0,
    ) -> TradeRecommendation:
        """Validate an already-built recommendation (optional re-score)."""
        current = recommendation
        if recompute_confidence:
            breakdown = self.score_confidence(
                current,
                volume_score=volume_score,
                confluence_score=confluence_score,
            )
            current = current.model_copy(update={"confidence": breakdown.total})
        return self._validator.validate(current)

    def score_confidence(
        self,
        recommendation: TradeRecommendation,
        *,
        volume_score: float = 50.0,
        confluence_score: float = 50.0,
    ) -> ConfidenceBreakdown:
        inputs = build_confidence_inputs(
            recommendation,
            volume_score=volume_score,
            confluence_score=confluence_score,
            rr_target=max(self._config.min_risk_reward, 1.0) * 2.0
            if self._config.min_risk_reward > 0
            else 2.0,
        )
        return combine_confidence(inputs, self._config)

    def try_recommend(
        self,
        plan: TradePlan,
        **kwargs: object,
    ) -> tuple[TradeRecommendation | None, str | None]:
        """Like ``recommend`` but returns ``(result, error)`` instead of raising."""
        try:
            return self.recommend(plan, **kwargs), None  # type: ignore[arg-type]
        except TradeRecommendationValidationError as exc:
            return None, str(exc)
