"""Strategy Filter Framework (A4X.1) + Trend & Regime Filters (A4X.2).

Package path: ``app/strategy_engine/filters/`` (TradeLab convention).
Strategies never import concrete filters — inject them via ``FilterRegistry``.
"""

from app.strategy_engine.filters.adx import ADXFilter, ADXFilterConfig
from app.strategy_engine.filters.base import BaseStrategyFilter, FilterBase
from app.strategy_engine.filters.ema200 import EMA200Filter, EMA200FilterConfig
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
from app.strategy_engine.filters.sideways_market import (
    SidewaysMarketFilter,
    SidewaysMarketFilterConfig,
)
from app.strategy_engine.filters.sma200 import SMA200Filter, SMA200FilterConfig
from app.strategy_engine.filters.trending_market import (
    TrendingMarketFilter,
    TrendingMarketFilterConfig,
)
from app.strategy_engine.filters.volatility_regime import (
    VolatilityRegime,
    VolatilityRegimeFilter,
    VolatilityRegimeFilterConfig,
)

__all__ = [
    "ADXFilter",
    "ADXFilterConfig",
    "BaseStrategyFilter",
    "EMA200Filter",
    "EMA200FilterConfig",
    "FilterBase",
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
    "SMA200Filter",
    "SMA200FilterConfig",
    "SidewaysMarketFilter",
    "SidewaysMarketFilterConfig",
    "StrategyFilterError",
    "StrategyFilterPort",
    "StrategyRecommendation",
    "TrendingMarketFilter",
    "TrendingMarketFilterConfig",
    "VolatilityRegime",
    "VolatilityRegimeFilter",
    "VolatilityRegimeFilterConfig",
]
