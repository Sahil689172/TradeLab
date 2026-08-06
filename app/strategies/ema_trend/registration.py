"""Registration helpers for the EMA Trend Following strategy."""

from __future__ import annotations

from app.strategies.ema_trend.config import EMATrendConfig
from app.strategies.ema_trend.strategy import EMATrendStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_ema_trend_strategy(config: EMATrendConfig | None = None) -> EMATrendStrategy:
    """Construct a configured EMA trend strategy instance."""
    return EMATrendStrategy(config)


def register_ema_trend_strategy(
    registry: StrategyRegistry,
    config: EMATrendConfig | None = None,
) -> EMATrendStrategy:
    """Register the EMA trend strategy on ``registry`` and return it."""
    strategy = build_ema_trend_strategy(config)
    registry.register(strategy)
    return strategy


def register_ema_trend_professional_strategy(
    registry: StrategyRegistry,
    config: EMATrendConfig | None = None,
) -> EMATrendStrategy:
    """Register EMA trend in professional mode (institutional filters)."""
    professional = config or EMATrendConfig.professional()
    if professional.mode != "professional":
        professional = professional.model_copy(update={"mode": "professional"})
    return register_ema_trend_strategy(registry, professional)