"""Registration helpers for the Momentum strategy."""

from __future__ import annotations

from app.strategies.momentum.config import MomentumConfig
from app.strategies.momentum.schemas import MomentumUniverseRanking
from app.strategies.momentum.strategy import MomentumStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_momentum_strategy(
    config: MomentumConfig | None = None,
    *,
    ranking: MomentumUniverseRanking | None = None,
) -> MomentumStrategy:
    return MomentumStrategy(config, ranking=ranking)


def register_momentum_strategy(
    registry: StrategyRegistry,
    config: MomentumConfig | None = None,
    *,
    ranking: MomentumUniverseRanking | None = None,
) -> MomentumStrategy:
    strategy = build_momentum_strategy(config, ranking=ranking)
    registry.register(strategy)
    return strategy
