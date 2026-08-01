"""Registration helpers for the Previous Day breakout strategy."""

from __future__ import annotations

import pandas as pd

from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult
from app.strategies.previous_day_breakout.config import PreviousDayBreakoutConfig
from app.strategies.previous_day_breakout.strategy import PreviousDayBreakoutStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_previous_day_breakout_strategy(
    config: PreviousDayBreakoutConfig | None = None,
    *,
    daily_ohlcv: pd.DataFrame | None = None,
    levels: LevelsSnapshot | None = None,
    market_structure: MarketStructureResult | None = None,
) -> PreviousDayBreakoutStrategy:
    """Construct a configured Magic Box strategy instance."""
    return PreviousDayBreakoutStrategy(
        config,
        daily_ohlcv=daily_ohlcv,
        levels=levels,
        market_structure=market_structure,
    )


def register_previous_day_breakout_strategy(
    registry: StrategyRegistry,
    config: PreviousDayBreakoutConfig | None = None,
    *,
    daily_ohlcv: pd.DataFrame | None = None,
    levels: LevelsSnapshot | None = None,
    market_structure: MarketStructureResult | None = None,
) -> PreviousDayBreakoutStrategy:
    """Register the Magic Box strategy and return the instance."""
    strategy = build_previous_day_breakout_strategy(
        config,
        daily_ohlcv=daily_ohlcv,
        levels=levels,
        market_structure=market_structure,
    )
    registry.register(strategy)
    return strategy
