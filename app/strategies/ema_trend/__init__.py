"""EMA Trend Following strategy package."""

from app.strategies.ema_trend.config import EMATrendConfig
from app.strategies.ema_trend.diagnostics import (
    FilterRejection,
    RejectionFilter,
    SignalFunnel,
)
from app.strategies.ema_trend.presets import EMA_PAIR_PRESETS
from app.strategies.ema_trend.professional import (
    atr_stop_price,
    atr_trailing_stop_price,
)
from app.strategies.ema_trend.registration import (
    build_ema_trend_strategy,
    register_ema_trend_professional_strategy,
    register_ema_trend_strategy,
)
from app.strategies.ema_trend.strategy import EMATrendStrategy

__all__ = [
    "EMA_PAIR_PRESETS",
    "EMATrendConfig",
    "EMATrendStrategy",
    "FilterRejection",
    "RejectionFilter",
    "SignalFunnel",
    "atr_stop_price",
    "atr_trailing_stop_price",
    "build_ema_trend_strategy",
    "register_ema_trend_professional_strategy",
    "register_ema_trend_strategy",
]
