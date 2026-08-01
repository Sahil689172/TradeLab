"""Registration helpers for the CPR strategy."""

from __future__ import annotations

from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult
from app.services.strategy_engine.indicators.vwap import VWAPService
from app.strategies.cpr.config import CPRStrategyConfig
from app.strategies.cpr.strategy import CPRStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_cpr_strategy(
    config: CPRStrategyConfig | None = None,
    *,
    vwap_service: VWAPService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> CPRStrategy:
    return CPRStrategy(
        config,
        vwap_service=vwap_service,
        market_structure=market_structure,
        levels=levels,
    )


def register_cpr_strategy(
    registry: StrategyRegistry,
    config: CPRStrategyConfig | None = None,
    *,
    vwap_service: VWAPService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> CPRStrategy:
    strategy = build_cpr_strategy(
        config,
        vwap_service=vwap_service,
        market_structure=market_structure,
        levels=levels,
    )
    registry.register(strategy)
    return strategy
