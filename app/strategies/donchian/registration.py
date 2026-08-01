"""Registration helpers for Donchian Channel strategy."""

from __future__ import annotations

from app.market_structure.schemas import MarketStructureResult
from app.services.strategy_engine.indicators.donchian import DonchianChannelService
from app.strategies.donchian.config import DonchianStrategyConfig
from app.strategies.donchian.strategy import DonchianStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_donchian_strategy(
    config: DonchianStrategyConfig | None = None,
    *,
    donchian_service: DonchianChannelService | None = None,
    market_structure: MarketStructureResult | None = None,
) -> DonchianStrategy:
    return DonchianStrategy(
        config,
        donchian_service=donchian_service,
        market_structure=market_structure,
    )


def register_donchian_strategy(
    registry: StrategyRegistry,
    config: DonchianStrategyConfig | None = None,
    *,
    donchian_service: DonchianChannelService | None = None,
    market_structure: MarketStructureResult | None = None,
) -> DonchianStrategy:
    strategy = build_donchian_strategy(
        config,
        donchian_service=donchian_service,
        market_structure=market_structure,
    )
    registry.register(strategy)
    return strategy
