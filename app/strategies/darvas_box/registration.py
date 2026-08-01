"""Registration helpers for Darvas Box strategy."""

from __future__ import annotations

from app.services.strategy_engine.darvas import DarvasBoxEngine
from app.strategies.darvas_box.config import DarvasBoxStrategyConfig
from app.strategies.darvas_box.strategy import DarvasBoxStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_darvas_box_strategy(
    config: DarvasBoxStrategyConfig | None = None,
    *,
    box_engine: DarvasBoxEngine | None = None,
) -> DarvasBoxStrategy:
    return DarvasBoxStrategy(config, box_engine=box_engine)


def register_darvas_box_strategy(
    registry: StrategyRegistry,
    config: DarvasBoxStrategyConfig | None = None,
    *,
    box_engine: DarvasBoxEngine | None = None,
) -> DarvasBoxStrategy:
    strategy = build_darvas_box_strategy(config, box_engine=box_engine)
    registry.register(strategy)
    return strategy
