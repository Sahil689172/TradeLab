"""Concrete TradeLab trading strategies."""

from app.strategies.break_retest import (
    BreakRetestStrategy,
    BreakRetestStrategyConfig,
    register_break_retest_strategy,
)
from app.strategies.cpr import CPRStrategy, CPRStrategyConfig, register_cpr_strategy
from app.strategies.darvas_box import (
    DarvasBoxStrategy,
    DarvasBoxStrategyConfig,
    register_darvas_box_strategy,
)
from app.strategies.donchian import (
    DonchianStrategy,
    DonchianStrategyConfig,
    register_donchian_strategy,
)
from app.strategies.ema_trend import (
    EMATrendConfig,
    EMATrendStrategy,
    register_ema_trend_professional_strategy,
    register_ema_trend_strategy,
)
from app.strategies.momentum import (
    MomentumConfig,
    MomentumEngine,
    MomentumStrategy,
    register_momentum_strategy,
)
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
    RelativeStrengthStrategy,
    register_relative_strength_strategy,
)
from app.strategies.supertrend import (
    SuperTrendStrategy,
    SuperTrendStrategyConfig,
    register_supertrend_strategy,
)
from app.strategies.volume_breakout import (
    VolumeBreakoutConfig,
    VolumeBreakoutStrategy,
    register_volume_breakout_strategy,
)
from app.strategies.vwap import VWAPStrategy, VWAPStrategyConfig, register_vwap_strategy

__all__ = [
    "BreakRetestStrategy",
    "BreakRetestStrategyConfig",
    "CPRStrategy",
    "CPRStrategyConfig",
    "DarvasBoxStrategy",
    "DarvasBoxStrategyConfig",
    "DonchianStrategy",
    "DonchianStrategyConfig",
    "EMATrendConfig",
    "EMATrendStrategy",
    "MomentumConfig",
    "MomentumEngine",
    "MomentumStrategy",
    "OpeningRangeBreakoutConfig",
    "OpeningRangeBreakoutStrategy",
    "PreviousDayBreakoutConfig",
    "PreviousDayBreakoutStrategy",
    "RelativeStrengthConfig",
    "RelativeStrengthStrategy",
    "SuperTrendStrategy",
    "SuperTrendStrategyConfig",
    "VolumeBreakoutConfig",
    "VolumeBreakoutStrategy",
    "VWAPStrategy",
    "VWAPStrategyConfig",
    "register_break_retest_strategy",
    "register_cpr_strategy",
    "register_darvas_box_strategy",
    "register_donchian_strategy",
    "register_ema_trend_professional_strategy",
    "register_ema_trend_strategy",
    "register_momentum_strategy",
    "register_opening_range_breakout_strategy",
    "register_previous_day_breakout_strategy",
    "register_relative_strength_strategy",
    "register_supertrend_strategy",
    "register_volume_breakout_strategy",
    "register_vwap_strategy",
]


def __getattr__(name: str):
    """Lazily expose optional heavy helpers without import-time side effects."""
    if name == "RelativeStrengthScreener":
        from app.strategies.relative_strength import RelativeStrengthScreener

        return RelativeStrengthScreener
    raise AttributeError(name)
