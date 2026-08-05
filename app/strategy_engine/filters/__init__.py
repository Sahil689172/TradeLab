"""Strategy Filter Framework — A4X.1 framework + A4X.2/A4X.3 filters.

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
from app.strategy_engine.filters.gap import GapFilter, GapFilterConfig
from app.strategy_engine.filters.liquidity import LiquidityFilter, LiquidityFilterConfig
from app.strategy_engine.filters.minimum_volume import (
    MinimumVolumeFilter,
    MinimumVolumeFilterConfig,
)
from app.strategy_engine.filters.obv_confirmation import (
    OBVConfirmationFilter,
    OBVConfirmationFilterConfig,
)
from app.strategy_engine.filters.pipeline import FilterPipeline
from app.strategy_engine.filters.protocols import (
    FilterPipelinePort,
    FilterRegistryPort,
    StrategyFilterPort,
)
from app.strategy_engine.filters.registry import FilterRegistry
from app.strategy_engine.filters.relative_volume import (
    RelativeVolumeFilter,
    RelativeVolumeFilterConfig,
)
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
from app.strategy_engine.filters.stocks_in_play import (
    StocksInPlayFilter,
    StocksInPlayFilterConfig,
)
from app.strategy_engine.filters.trending_market import (
    TrendingMarketFilter,
    TrendingMarketFilterConfig,
)
from app.strategy_engine.filters.volatility_regime import (
    VolatilityRegime,
    VolatilityRegimeFilter,
    VolatilityRegimeFilterConfig,
)
from app.strategy_engine.filters.volume_sma import VolumeSMAFilter, VolumeSMAFilterConfig
from app.strategy_engine.filters.vwap_confirmation import (
    VWAPConfirmationFilter,
    VWAPConfirmationFilterConfig,
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
    "GapFilter",
    "GapFilterConfig",
    "LiquidityFilter",
    "LiquidityFilterConfig",
    "MinimumVolumeFilter",
    "MinimumVolumeFilterConfig",
    "OBVConfirmationFilter",
    "OBVConfirmationFilterConfig",
    "PipelineResult",
    "RelativeVolumeFilter",
    "RelativeVolumeFilterConfig",
    "SMA200Filter",
    "SMA200FilterConfig",
    "SidewaysMarketFilter",
    "SidewaysMarketFilterConfig",
    "StocksInPlayFilter",
    "StocksInPlayFilterConfig",
    "StrategyFilterError",
    "StrategyFilterPort",
    "StrategyRecommendation",
    "TrendingMarketFilter",
    "TrendingMarketFilterConfig",
    "VWAPConfirmationFilter",
    "VWAPConfirmationFilterConfig",
    "VolatilityRegime",
    "VolatilityRegimeFilter",
    "VolatilityRegimeFilterConfig",
    "VolumeSMAFilter",
    "VolumeSMAFilterConfig",
]
