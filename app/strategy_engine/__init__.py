"""Strategy engine foundation — contracts, registry, and runner."""

from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import (
    StrategyEngineError,
    StrategyNotFoundError,
    StrategyRegistrationError,
    StrategyValidationError,
)
from app.strategy_engine.models import Signal, SignalType, TradePlan
from app.strategy_engine.registry import StrategyRegistry
from app.strategy_engine.runner import StrategyRunner
from app.strategy_engine.symbols import attach_symbol, resolve_symbol_from_features

__all__ = [
    "BaseStrategy",
    "Signal",
    "SignalType",
    "StrategyEngineError",
    "StrategyNotFoundError",
    "StrategyRegistrationError",
    "StrategyRegistry",
    "StrategyRunner",
    "StrategyValidationError",
    "TradePlan",
    "attach_symbol",
    "resolve_symbol_from_features",
]
