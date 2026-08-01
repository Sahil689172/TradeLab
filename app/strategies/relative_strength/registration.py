"""Registration helpers for Relative Strength."""

from __future__ import annotations

from app.strategies.relative_strength.config import RelativeStrengthConfig
from app.strategies.relative_strength.schemas import UniverseRanking
from app.strategies.relative_strength.strategy import RelativeStrengthStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_relative_strength_strategy(
    config: RelativeStrengthConfig | None = None,
    *,
    ranking: UniverseRanking | None = None,
) -> RelativeStrengthStrategy:
    return RelativeStrengthStrategy(config, ranking=ranking)


def register_relative_strength_strategy(
    registry: StrategyRegistry,
    config: RelativeStrengthConfig | None = None,
    *,
    ranking: UniverseRanking | None = None,
) -> RelativeStrengthStrategy:
    strategy = build_relative_strength_strategy(config, ranking=ranking)
    registry.register(strategy)
    return strategy
