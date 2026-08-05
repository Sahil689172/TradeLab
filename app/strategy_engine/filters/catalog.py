"""Filter id → factory catalog for strategy pipeline assembly."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.strategy_engine.filters.adx import ADXFilter
from app.strategy_engine.filters.atr_stop import ATRStopFilter
from app.strategy_engine.filters.atr_trailing_stop import ATRTrailingStopFilter
from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.daily_confirmation import DailyConfirmationFilter
from app.strategy_engine.filters.ema200 import EMA200Filter
from app.strategy_engine.filters.fixed_stop import FixedStopFilter
from app.strategy_engine.filters.gap import GapFilter
from app.strategy_engine.filters.higher_timeframe_trend import HigherTimeframeTrendFilter
from app.strategy_engine.filters.liquidity import LiquidityFilter
from app.strategy_engine.filters.maximum_drawdown import MaximumDrawdownFilter
from app.strategy_engine.filters.maximum_portfolio_exposure import MaximumPortfolioExposureFilter
from app.strategy_engine.filters.minimum_confidence import MinimumConfidenceFilter
from app.strategy_engine.filters.minimum_position_size import MinimumPositionSizeFilter
from app.strategy_engine.filters.minimum_volume import MinimumVolumeFilter
from app.strategy_engine.filters.multi_timeframe_ema import MultiTimeframeEMAFilter
from app.strategy_engine.filters.multi_timeframe_rsi import MultiTimeframeRSIFilter
from app.strategy_engine.filters.multi_timeframe_supertrend import MultiTimeframeSuperTrendFilter
from app.strategy_engine.filters.obv_confirmation import OBVConfirmationFilter
from app.strategy_engine.filters.relative_volume import RelativeVolumeFilter
from app.strategy_engine.filters.risk_reward import RiskRewardFilter
from app.strategy_engine.filters.sma200 import SMA200Filter
from app.strategy_engine.filters.stocks_in_play import StocksInPlayFilter
from app.strategy_engine.filters.trending_market import TrendingMarketFilter
from app.strategy_engine.filters.volatility_regime import VolatilityRegimeFilter
from app.strategy_engine.filters.volume_sma import VolumeSMAFilter
from app.strategy_engine.filters.vwap_confirmation import VWAPConfirmationFilter
from app.strategy_engine.filters.weekly_confirmation import WeeklyConfirmationFilter

FilterFactory = Callable[..., FilterBase]

FILTER_CATALOG: dict[str, FilterFactory] = {
    "ema200": EMA200Filter,
    "sma200": SMA200Filter,
    "adx": ADXFilter,
    "atr_stop": ATRStopFilter,
    "atr_trailing_stop": ATRTrailingStopFilter,
    "fixed_stop": FixedStopFilter,
    "risk_reward": RiskRewardFilter,
    "maximum_drawdown": MaximumDrawdownFilter,
    "minimum_confidence": MinimumConfidenceFilter,
    "maximum_portfolio_exposure": MaximumPortfolioExposureFilter,
    "minimum_position_size": MinimumPositionSizeFilter,
    "relative_volume": RelativeVolumeFilter,
    "volume_sma": VolumeSMAFilter,
    "obv_confirmation": OBVConfirmationFilter,
    "vwap_confirmation": VWAPConfirmationFilter,
    "stocks_in_play": StocksInPlayFilter,
    "liquidity": LiquidityFilter,
    "minimum_volume": MinimumVolumeFilter,
    "gap": GapFilter,
    "trending_market": TrendingMarketFilter,
    "volatility_regime": VolatilityRegimeFilter,
    "htf_trend": HigherTimeframeTrendFilter,
    "daily_confirmation": DailyConfirmationFilter,
    "weekly_confirmation": WeeklyConfirmationFilter,
    "mtf_ema": MultiTimeframeEMAFilter,
    "mtf_rsi": MultiTimeframeRSIFilter,
    "mtf_supertrend": MultiTimeframeSuperTrendFilter,
}


def create_filter(
    filter_id: str,
    *,
    enabled: bool = True,
    priority: int = 100,
    params: dict[str, Any] | None = None,
) -> FilterBase:
    """Instantiate a catalog filter by id."""
    try:
        factory = FILTER_CATALOG[filter_id]
    except KeyError as exc:
        known = ", ".join(sorted(FILTER_CATALOG))
        raise KeyError(f"Unknown filter_id '{filter_id}'. Known: {known}") from exc
    return factory(enabled=enabled, priority=priority, **(params or {}))
