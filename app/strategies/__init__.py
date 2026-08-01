"""Concrete TradeLab trading strategies."""

from app.strategies.cpr import CPRStrategy, CPRStrategyConfig, register_cpr_strategy
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy, register_ema_trend_strategy
from app.strategies.opening_range_breakout import (
    OpeningRangeBreakoutConfig,
    OpeningRangeBreakoutStrategy,
    register_opening_range_breakout_strategy,
)
from app.strategies.previous_day_breakout import (
    PreviousDayBreakoutConfig,
    PreviousDayBreakoutStrategy,
    register_previous_day_breakout_strategy,
)
from app.strategies.relative_strength import (
    RelativeStrengthConfig,
    RelativeStrengthScreener,
    RelativeStrengthStrategy,
    register_relative_strength_strategy,
)
from app.strategies.volume_breakout import (
    VolumeBreakoutConfig,
    VolumeBreakoutStrategy,
    register_volume_breakout_strategy,
)
from app.strategies.vwap import VWAPStrategy, VWAPStrategyConfig, register_vwap_strategy

__all__ = [
    "CPRStrategy",
    "CPRStrategyConfig",
    "EMATrendConfig",
    "EMATrendStrategy",
    "OpeningRangeBreakoutConfig",
    "OpeningRangeBreakoutStrategy",
    "PreviousDayBreakoutConfig",
    "PreviousDayBreakoutStrategy",
    "RelativeStrengthConfig",
    "RelativeStrengthScreener",
    "RelativeStrengthStrategy",
    "VolumeBreakoutConfig",
    "VolumeBreakoutStrategy",
    "VWAPStrategy",
    "VWAPStrategyConfig",
    "register_cpr_strategy",
    "register_ema_trend_strategy",
    "register_opening_range_breakout_strategy",
    "register_previous_day_breakout_strategy",
    "register_relative_strength_strategy",
    "register_volume_breakout_strategy",
    "register_vwap_strategy",
]
