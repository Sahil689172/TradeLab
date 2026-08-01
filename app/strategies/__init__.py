"""Concrete TradeLab trading strategies."""

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

__all__ = [
    "EMATrendConfig",
    "EMATrendStrategy",
    "OpeningRangeBreakoutConfig",
    "OpeningRangeBreakoutStrategy",
    "PreviousDayBreakoutConfig",
    "PreviousDayBreakoutStrategy",
    "register_ema_trend_strategy",
    "register_opening_range_breakout_strategy",
    "register_previous_day_breakout_strategy",
]
