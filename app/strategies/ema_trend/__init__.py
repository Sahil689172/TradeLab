"""EMA Trend Following strategy package."""

from app.strategies.ema_trend.config import EMATrendConfig
from app.strategies.ema_trend.registration import (
    build_ema_trend_strategy,
    register_ema_trend_strategy,
)
from app.strategies.ema_trend.strategy import EMATrendStrategy

__all__ = [
    "EMATrendConfig",
    "EMATrendStrategy",
    "build_ema_trend_strategy",
    "register_ema_trend_strategy",
]
