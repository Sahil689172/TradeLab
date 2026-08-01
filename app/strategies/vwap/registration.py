"""Registration helpers for the VWAP strategy."""

from __future__ import annotations

from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult
from app.services.strategy_engine.indicators.vwap import VWAPService
from app.strategies.vwap.config import VWAPStrategyConfig
from app.strategies.vwap.strategy import VWAPStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_vwap_strategy(
    config: VWAPStrategyConfig | None = None,
    *,
    vwap_service: VWAPService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> VWAPStrategy:
    return VWAPStrategy(
        config,
        vwap_service=vwap_service,
        market_structure=market_structure,
        levels=levels,
    )


def register_vwap_strategy(
    registry: StrategyRegistry,
    config: VWAPStrategyConfig | None = None,
    *,
    vwap_service: VWAPService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> VWAPStrategy:
    strategy = build_vwap_strategy(
        config,
        vwap_service=vwap_service,
        market_structure=market_structure,
        levels=levels,
    )
    registry.register(strategy)
    return strategy
