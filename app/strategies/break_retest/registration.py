"""Registration helpers for Break & Retest strategy."""

from __future__ import annotations

from app.market_structure.schemas import MarketStructureResult
from app.services.strategy_engine.break_retest import BreakRetestEngine
from app.strategies.break_retest.config import BreakRetestStrategyConfig
from app.strategies.break_retest.strategy import BreakRetestStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_break_retest_strategy(
    config: BreakRetestStrategyConfig | None = None,
    *,
    resistance: float | None = None,
    support: float | None = None,
    market_structure: MarketStructureResult | None = None,
    break_retest_engine: BreakRetestEngine | None = None,
) -> BreakRetestStrategy:
    return BreakRetestStrategy(
        config,
        resistance=resistance,
        support=support,
        market_structure=market_structure,
        break_retest_engine=break_retest_engine,
    )


def register_break_retest_strategy(
    registry: StrategyRegistry,
    config: BreakRetestStrategyConfig | None = None,
    *,
    resistance: float | None = None,
    support: float | None = None,
    market_structure: MarketStructureResult | None = None,
    break_retest_engine: BreakRetestEngine | None = None,
) -> BreakRetestStrategy:
    strategy = build_break_retest_strategy(
        config,
        resistance=resistance,
        support=support,
        market_structure=market_structure,
        break_retest_engine=break_retest_engine,
    )
    registry.register(strategy)
    return strategy
