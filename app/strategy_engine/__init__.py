"""Strategy engine foundation — contracts, registry, runner, and filters."""

from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import (
    StrategyEngineError,
    StrategyNotFoundError,
    StrategyRegistrationError,
    StrategyValidationError,
)
from app.strategy_engine.filters import (
    BaseStrategyFilter,
    FilterBase,
    FilterPipeline,
    FilterRegistry,
    StrategyRecommendation,
)
from app.strategy_engine.models import Signal, SignalType, TradePlan
from app.strategy_engine.registry import StrategyRegistry
from app.strategy_engine.runner import StrategyRunner
from app.strategy_engine.symbols import attach_symbol, resolve_symbol_from_features

__all__ = [
    "BaseStrategy",
    "BaseStrategyFilter",
    "FilterBase",
    "FilterPipeline",
    "FilterRegistry",
    "Signal",
    "SignalType",
    "StrategyEngineError",
    "StrategyNotFoundError",
    "StrategyRecommendation",
    "StrategyRegistrationError",
    "StrategyRegistry",
    "StrategyRunner",
    "StrategyValidationError",
    "TradePlan",
    "attach_symbol",
    "resolve_symbol_from_features",
]
