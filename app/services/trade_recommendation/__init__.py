"""Trade Recommendation & Strategy Validation Engine."""

from app.services.trade_recommendation.aggregator import RecommendationAggregator
from app.services.trade_recommendation.confidence import (
    combine_confidence,
    build_confidence_inputs,
)
from app.services.trade_recommendation.engine import TradeRecommendationEngine
from app.services.trade_recommendation.report import (
    build_aggregate_report,
    build_recommendation_report,
    format_price,
)
from app.services.trade_recommendation.schemas import (
    AggregatedRecommendation,
    ConfidenceBreakdown,
    ConfidenceInputs,
    ConsensusSignal,
    RecommendationConfig,
    RecommendationReport,
    StrategyValidationReport,
    StrategyValidationRow,
    TradeRecommendation,
)
from app.services.trade_recommendation.strategy_validation import (
    StrategyValidationFramework,
    known_strategy_aliases,
)
from app.services.trade_recommendation.trade_recommendation import (
    build_trade_recommendation,
    confidence_to_percent,
    enrich_from_detailed_plan,
)
from app.services.trade_recommendation.validator import (
    TradeRecommendationValidationError,
    TradeRecommendationValidator,
)

__all__ = [
    "AggregatedRecommendation",
    "ConfidenceBreakdown",
    "ConfidenceInputs",
    "ConsensusSignal",
    "RecommendationAggregator",
    "RecommendationConfig",
    "RecommendationReport",
    "StrategyValidationFramework",
    "StrategyValidationReport",
    "StrategyValidationRow",
    "TradeRecommendation",
    "TradeRecommendationEngine",
    "TradeRecommendationValidationError",
    "TradeRecommendationValidator",
    "build_aggregate_report",
    "build_confidence_inputs",
    "build_recommendation_report",
    "build_trade_recommendation",
    "combine_confidence",
    "confidence_to_percent",
    "enrich_from_detailed_plan",
    "format_price",
    "known_strategy_aliases",
]
