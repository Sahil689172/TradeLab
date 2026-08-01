"""Concrete TradeLab trading strategies."""

from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy, register_ema_trend_strategy
from app.strategies.previous_day_breakout import (
    PreviousDayBreakoutConfig,
    PreviousDayBreakoutStrategy,
    register_previous_day_breakout_strategy,
)

__all__ = [
    "EMATrendConfig",
    "EMATrendStrategy",
    "PreviousDayBreakoutConfig",
    "PreviousDayBreakoutStrategy",
    "register_ema_trend_strategy",
    "register_previous_day_breakout_strategy",
]
