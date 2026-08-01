"""Registration helpers for SuperTrend strategy."""

from __future__ import annotations

from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult
from app.services.strategy_engine.indicators.supertrend import SuperTrendService
from app.strategies.supertrend.config import SuperTrendStrategyConfig
from app.strategies.supertrend.strategy import SuperTrendStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_supertrend_strategy(
    config: SuperTrendStrategyConfig | None = None,
    *,
    supertrend_service: SuperTrendService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> SuperTrendStrategy:
    return SuperTrendStrategy(
        config,
        supertrend_service=supertrend_service,
        market_structure=market_structure,
        levels=levels,
    )


def register_supertrend_strategy(
    registry: StrategyRegistry,
    config: SuperTrendStrategyConfig | None = None,
    *,
    supertrend_service: SuperTrendService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> SuperTrendStrategy:
    strategy = build_supertrend_strategy(
        config,
        supertrend_service=supertrend_service,
        market_structure=market_structure,
        levels=levels,
    )
    registry.register(strategy)
    return strategy
