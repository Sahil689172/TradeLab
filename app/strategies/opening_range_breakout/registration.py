"""Registration helpers for the Opening Range Breakout strategy."""

from __future__ import annotations

from app.market_structure.schemas import MarketStructureResult
from app.strategies.opening_range_breakout.config import OpeningRangeBreakoutConfig
from app.strategies.opening_range_breakout.strategy import OpeningRangeBreakoutStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_opening_range_breakout_strategy(
    config: OpeningRangeBreakoutConfig | None = None,
    *,
    market_structure: MarketStructureResult | None = None,
) -> OpeningRangeBreakoutStrategy:
    return OpeningRangeBreakoutStrategy(config, market_structure=market_structure)


def register_opening_range_breakout_strategy(
    registry: StrategyRegistry,
    config: OpeningRangeBreakoutConfig | None = None,
    *,
    market_structure: MarketStructureResult | None = None,
) -> OpeningRangeBreakoutStrategy:
    strategy = build_opening_range_breakout_strategy(
        config,
        market_structure=market_structure,
    )
    registry.register(strategy)
    return strategy
