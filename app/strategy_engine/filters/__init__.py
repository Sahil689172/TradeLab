"""Strategy Filter Framework (Phase A4X.1) — framework only, no concrete filters.

Package path: ``app/strategy_engine/filters/`` (TradeLab convention).
There is no ``backend/app/`` package in this repository.

Strategies never import filters. Callers inject a ``FilterRegistry`` into
``FilterPipeline`` and pass a ``StrategyRecommendation``.
"""

from app.strategy_engine.filters.base import BaseStrategyFilter
from app.strategy_engine.filters.exceptions import (
    FilterNotFoundError,
    FilterPipelineError,
    FilterRegistrationError,
    FilterValidationError,
    StrategyFilterError,
)
from app.strategy_engine.filters.pipeline import FilterPipeline
from app.strategy_engine.filters.protocols import (
    FilterPipelinePort,
    FilterRegistryPort,
    StrategyFilterPort,
)
from app.strategy_engine.filters.registry import FilterRegistry
from app.strategy_engine.filters.schemas import (
    FilterConfig,
    FilterStepResult,
    PipelineResult,
    StrategyRecommendation,
)

__all__ = [
    "BaseStrategyFilter",
    "FilterConfig",
    "FilterNotFoundError",
    "FilterPipeline",
    "FilterPipelineError",
    "FilterPipelinePort",
    "FilterRegistrationError",
    "FilterRegistry",
    "FilterRegistryPort",
    "FilterStepResult",
    "FilterValidationError",
    "PipelineResult",
    "StrategyFilterError",
    "StrategyFilterPort",
    "StrategyRecommendation",
]
