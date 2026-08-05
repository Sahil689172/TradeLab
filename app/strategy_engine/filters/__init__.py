"""Strategy Filter Framework — A4X.1–A4X.6.

Package path: ``app/strategy_engine/filters/`` (TradeLab convention).
Strategies declare ``FILTER_PROFILE`` (mandatory/optional/default/configurable)
and keep raw signal logic unchanged. Enable via ``enable_filter_pipeline=True``.
"""

from app.strategy_engine.filters.adx import ADXFilter, ADXFilterConfig
from app.strategy_engine.filters.atr_stop import ATRStopFilter, ATRStopFilterConfig
from app.strategy_engine.filters.atr_trailing_stop import (
    ATRTrailingStopFilter,
    ATRTrailingStopFilterConfig,
)
from app.strategy_engine.filters.base import BaseStrategyFilter, FilterBase
from app.strategy_engine.filters.catalog import FILTER_CATALOG, create_filter
from app.strategy_engine.filters.confirmation import (
    ALL_HTF_CONFIRMATIONS,
    DAILY,
    HTF_TREND,
    HTFConfirmationRequest,
    MTF_EMA,
    MTF_RSI,
    MTF_SUPERTREND,
    WEEKLY,
    request_confirmations,
    requested_confirmations,
)
from app.strategy_engine.filters.integration import (
    apply_strategy_filter_pipeline,
    build_pipeline_from_profile,
    enrich_metadata_from_features,
)
from app.strategy_engine.filters.profiles import FilterRole, FilterSpec, StrategyFilterProfile
from app.strategy_engine.filters.strategy_profiles import (
    STRATEGY_FILTER_PROFILES,
    get_strategy_filter_profile,
    list_strategy_filter_profiles,
)
from app.strategy_engine.filters.daily_confirmation import (
    DailyConfirmationFilter,
    DailyConfirmationFilterConfig,
)
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
from app.strategy_engine.filters.higher_timeframe_trend import (
    HigherTimeframeTrendFilter,
    HigherTimeframeTrendFilterConfig,
)
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
from app.strategy_engine.filters.multi_timeframe_ema import (
    MultiTimeframeEMAFilter,
    MultiTimeframeEMAFilterConfig,
)
from app.strategy_engine.filters.multi_timeframe_rsi import (
    MultiTimeframeRSIFilter,
    MultiTimeframeRSIFilterConfig,
)
from app.strategy_engine.filters.multi_timeframe_supertrend import (
    MultiTimeframeSuperTrendFilter,
    MultiTimeframeSuperTrendFilterConfig,
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
from app.strategy_engine.filters.weekly_confirmation import (
    WeeklyConfirmationFilter,
    WeeklyConfirmationFilterConfig,
)

__all__ = [
    "ADXFilter",
    "ADXFilterConfig",
    "ALL_HTF_CONFIRMATIONS",
    "ATRStopFilter",
    "ATRStopFilterConfig",
    "ATRTrailingStopFilter",
    "ATRTrailingStopFilterConfig",
    "BaseStrategyFilter",
    "DAILY",
    "DailyConfirmationFilter",
    "DailyConfirmationFilterConfig",
    "EMA200Filter",
    "EMA200FilterConfig",
    "FILTER_CATALOG",
    "FilterBase",
    "FilterConfig",
    "FilterNotFoundError",
    "FilterPipeline",
    "FilterPipelineError",
    "FilterPipelinePort",
    "FilterRegistrationError",
    "FilterRegistry",
    "FilterRegistryPort",
    "FilterRole",
    "FilterSpec",
    "FilterStepResult",
    "FilterValidationError",
    "FixedStopFilter",
    "FixedStopFilterConfig",
    "GapFilter",
    "GapFilterConfig",
    "HTFConfirmationRequest",
    "HTF_TREND",
    "HigherTimeframeTrendFilter",
    "HigherTimeframeTrendFilterConfig",
    "LiquidityFilter",
    "LiquidityFilterConfig",
    "MTF_EMA",
    "MTF_RSI",
    "MTF_SUPERTREND",
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
    "MultiTimeframeEMAFilter",
    "MultiTimeframeEMAFilterConfig",
    "MultiTimeframeRSIFilter",
    "MultiTimeframeRSIFilterConfig",
    "MultiTimeframeSuperTrendFilter",
    "MultiTimeframeSuperTrendFilterConfig",
    "OBVConfirmationFilter",
    "OBVConfirmationFilterConfig",
    "PipelineResult",
    "RelativeVolumeFilter",
    "RelativeVolumeFilterConfig",
    "RiskRewardFilter",
    "RiskRewardFilterConfig",
    "SMA200Filter",
    "SMA200FilterConfig",
    "STRATEGY_FILTER_PROFILES",
    "SidewaysMarketFilter",
    "SidewaysMarketFilterConfig",
    "StocksInPlayFilter",
    "StocksInPlayFilterConfig",
    "StrategyFilterError",
    "StrategyFilterPort",
    "StrategyFilterProfile",
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
    "WEEKLY",
    "WeeklyConfirmationFilter",
    "WeeklyConfirmationFilterConfig",
    "apply_strategy_filter_pipeline",
    "build_pipeline_from_profile",
    "create_filter",
    "enrich_metadata_from_features",
    "get_strategy_filter_profile",
    "list_strategy_filter_profiles",
    "request_confirmations",
    "requested_confirmations",
]
