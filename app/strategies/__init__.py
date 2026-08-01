"""Concrete TradeLab trading strategies."""

from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy, register_ema_trend_strategy

__all__ = [
    "EMATrendConfig",
    "EMATrendStrategy",
    "register_ema_trend_strategy",
]
