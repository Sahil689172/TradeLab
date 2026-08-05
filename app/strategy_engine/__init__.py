"""Strategy engine foundation — contracts, registry, runner, and filters."""

from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import (
    StrategyEngineError,
    StrategyNotFoundError,
    StrategyRegistrationError,
    StrategyValidationError,
)
from app.strategy_engine.audit import (
    StrategyAuditReport,
    StrategyAuditor,
    export_audit,
    format_audit_report,
)
from app.strategy_engine.configuration import (
    StrategySystemConfig,
    load_strategy_config,
    build_strategy_from_config,
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
    "StrategyAuditReport",
    "StrategyAuditor",
    "StrategyEngineError",
    "StrategyNotFoundError",
    "StrategyRecommendation",
    "StrategyRegistrationError",
    "StrategyRegistry",
    "StrategyRunner",
    "StrategySystemConfig",
    "StrategyValidationError",
    "TradePlan",
    "attach_symbol",
    "build_strategy_from_config",
    "export_audit",
    "format_audit_report",
    "load_strategy_config",
    "resolve_symbol_from_features",
]
