"""Map strategy names → required context assets."""

from __future__ import annotations

from app.services.strategy_context.schemas import ContextRequirement

# Canonical strategy_name → requirements the Context Provider must satisfy.
STRATEGY_CONTEXT_REQUIREMENTS: dict[str, tuple[ContextRequirement, ...]] = {
    "ema_trend": (ContextRequirement.FEATURES,),
    "previous_day_breakout": (
        ContextRequirement.INTRADAY_FEATURES,
        ContextRequirement.DAILY_OHLCV,
        ContextRequirement.LEVELS,
        ContextRequirement.MARKET_STRUCTURE,
    ),
    # Session/intraday bars drive opening-range resolution inside the strategy.
    "opening_range_breakout": (
        ContextRequirement.INTRADAY_FEATURES,
        ContextRequirement.MARKET_STRUCTURE,
    ),
    "vwap": (
        ContextRequirement.FEATURES,
        ContextRequirement.VWAP_READY,
        ContextRequirement.RELATIVE_VOLUME,
        ContextRequirement.MARKET_STRUCTURE,
        ContextRequirement.LEVELS,
    ),
    "cpr": (
        ContextRequirement.FEATURES,
        ContextRequirement.LEVELS,
        ContextRequirement.MARKET_STRUCTURE,
        ContextRequirement.RELATIVE_VOLUME,
        ContextRequirement.VWAP_READY,
    ),
    "volume_breakout": (
        ContextRequirement.FEATURES,
        ContextRequirement.RELATIVE_VOLUME,
        ContextRequirement.MARKET_STRUCTURE,
        ContextRequirement.LEVELS,
    ),
    "relative_strength": (
        ContextRequirement.FEATURES,
        ContextRequirement.RS_RANKING,
    ),
    "momentum": (
        ContextRequirement.FEATURES,
        ContextRequirement.MOMENTUM_RANKING,
    ),
    "darvas_box": (ContextRequirement.FEATURES,),
    "break_retest": (
        ContextRequirement.FEATURES,
        ContextRequirement.MARKET_STRUCTURE,
    ),
    "supertrend": (
        ContextRequirement.FEATURES,
        ContextRequirement.MARKET_STRUCTURE,
        ContextRequirement.LEVELS,
    ),
    "donchian": (
        ContextRequirement.FEATURES,
        ContextRequirement.MARKET_STRUCTURE,
    ),
}


def requirements_for(strategy_name: str) -> tuple[ContextRequirement, ...]:
    """Return context requirements for a registered strategy name."""
    key = strategy_name.strip().lower()
    return STRATEGY_CONTEXT_REQUIREMENTS.get(key, (ContextRequirement.FEATURES,))
