"""Strategy Filter Framework — A4X.1–A4X.4 filters.

Package path: ``app/strategy_engine/filters/`` (TradeLab convention).
Strategies never import concrete filters — inject them via ``FilterRegistry``.
"""

from app.strategy_engine.filters.adx import ADXFilter, ADXFilterConfig
from app.strategy_engine.filters.atr_stop import ATRStopFilter, ATRStopFilterConfig
from app.strategy_engine.filters.atr_trailing_stop import (
    ATRTrailingStopFilter,
    ATRTrailingStopFilterConfig,
)
from app.strategy_engine.filters.base import BaseStrategyFilter, FilterBase
from app.strategy_engine.filters.ema200 import EMA200Filter, EMA200FilterConfig
from app.strategy_engine.filters.exceptions import (
    FilterNotFoundError,
    FilterPipelineError,
    FilterRegistrationError,
    FilterValidationError,
    StrategyFilterError,
)
from app.strategy_engine.filters.fixed_stop import FixedStopFilter, FixedStopFilterConfig
from app.strategy_engine.filters.gap import GapFilter, GapFilterConfig
from app.strategy_engine.filters.liquidity import LiquidityFilter, LiquidityFilterConfig
from app.strategy_engine.filters.maximum_drawdown import (
    MaximumDrawdownFilter,
    MaximumDrawdownFilterConfig,
)
from app.strategy_engine.filters.maximum_portfolio_exposure import (
    MaximumPortfolioExposureFilter,
    MaximumPortfolioExposureFilterConfig,
)
from app.strategy_engine.filters.minimum_confidence import (
    MinimumConfidenceFilter,
    MinimumConfidenceFilterConfig,
)
from app.strategy_engine.filters.minimum_position_size import (
    MinimumPositionSizeFilter,
    MinimumPositionSizeFilterConfig,
)
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
from app.strategy_engine.filters.risk_reward import RiskRewardFilter, RiskRewardFilterConfig
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
    "ATRStopFilter",
    "ATRStopFilterConfig",
    "ATRTrailingStopFilter",
    "ATRTrailingStopFilterConfig",
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
    "FixedStopFilter",
    "FixedStopFilterConfig",
    "GapFilter",
    "GapFilterConfig",
    "LiquidityFilter",
    "LiquidityFilterConfig",
    "MaximumDrawdownFilter",
    "MaximumDrawdownFilterConfig",
    "MaximumPortfolioExposureFilter",
    "MaximumPortfolioExposureFilterConfig",
    "MinimumConfidenceFilter",
    "MinimumConfidenceFilterConfig",
    "MinimumPositionSizeFilter",
    "MinimumPositionSizeFilterConfig",
    "MinimumVolumeFilter",
    "MinimumVolumeFilterConfig",
    "OBVConfirmationFilter",
    "OBVConfirmationFilterConfig",
    "PipelineResult",
    "RelativeVolumeFilter",
    "RelativeVolumeFilterConfig",
    "RiskRewardFilter",
    "RiskRewardFilterConfig",
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
