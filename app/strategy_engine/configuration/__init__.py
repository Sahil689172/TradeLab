"""Strategy Configuration System (Phase A4X.7).

Load validated JSON/YAML documents that expose parameters, filters, thresholds,
risk, position, and enable/disable for every strategy — without rewriting
strategy logic.
"""

from app.strategy_engine.configuration.exceptions import (
    StrategyConfigLoadError,
    StrategyConfigNotFoundError,
    StrategyConfigValidationError,
    StrategyConfigurationError,
)
from app.strategy_engine.configuration.loader import (
    build_strategy_from_config,
    build_strategy_from_dict,
    export_default_config,
    load_strategy_config,
    load_strategy_config_bundle,
    load_strategy_config_dict,
    save_strategy_config,
)
from app.strategy_engine.configuration.registry import (
    default_system_config,
    ensure_default_bindings,
    get_binding,
    list_bound_strategies,
    materialize_native_config,
    materialize_strategy,
)
from app.strategy_engine.configuration.schemas import (
    FilterConfiguration,
    PositionConfiguration,
    RiskConfiguration,
    StrategyConfigBundle,
    StrategySystemConfig,
    ThresholdConfiguration,
)

__all__ = [
    "FilterConfiguration",
    "PositionConfiguration",
    "RiskConfiguration",
    "StrategyConfigBundle",
    "StrategyConfigLoadError",
    "StrategyConfigNotFoundError",
    "StrategyConfigValidationError",
    "StrategyConfigurationError",
    "StrategySystemConfig",
    "ThresholdConfiguration",
    "build_strategy_from_config",
    "build_strategy_from_dict",
    "default_system_config",
    "ensure_default_bindings",
    "export_default_config",
    "get_binding",
    "list_bound_strategies",
    "load_strategy_config",
    "load_strategy_config_bundle",
    "load_strategy_config_dict",
    "materialize_native_config",
    "materialize_strategy",
    "save_strategy_config",
]
