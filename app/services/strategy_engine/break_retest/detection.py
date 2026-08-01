"""Reusable Break, Retest, and Confirmation Candle detectors.

Wraps Condition Engine primitives so strategies share one implementation.
"""

from __future__ import annotations

import pandas as pd

from app.conditions import ConditionEngine
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.break_retest.schemas import (
    BreakEvent,
    ConfirmationCandle,
    RetestEvent,
)


def detect_break(
    *,
    previous_close: float,
    current_close: float,
    level: float,
    direction: TradeDirection,
    conditions: ConditionEngine,
    level_label: str = "level",
) -> bool:
    """True when price breaks above resistance (long) or below support (short)."""
    if direction is TradeDirection.LONG:
        return conditions.breaks_above(
            previous_close,
            current_close,
            level,
            level_label=level_label,
        ).value
    return conditions.breaks_below(
        previous_close,
        current_close,
        level,
        level_label=level_label,
    ).value


def detect_retest(
    *,
    low: float,
    high: float,
    close: float,
    level: float,
    direction: TradeDirection,
    conditions: ConditionEngine,
    tolerance: float = 0.0,
    level_label: str = "level",
) -> bool:
    """True when price successfully retests the broken level from the break side."""
    side = "ABOVE" if direction is TradeDirection.LONG else "BELOW"
    return conditions.retest(
        side=side,
        low=low,
        high=high,
        close=close,
        level=level,
        tolerance=tolerance,
        level_label=level_label,
    ).value


def detect_failed_retest(
    *,
    close: float,
    level: float,
    direction: TradeDirection,
) -> bool:
    """True when price closes back through the broken level (failed retest)."""
    if direction is TradeDirection.LONG:
        return close < level
    return close > level


def detect_confirmation_candle(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    previous_close: float,
    direction: TradeDirection,
    min_body_ratio: float = 0.4,
) -> ConfirmationCandle:
    """Bullish/bearish confirmation candle with minimum body strength."""
    span = max(high - low, 1e-12)
    body = abs(close - open_)
    body_ratio = body / span
    bullish = close > open_ and close >= previous_close and body_ratio >= min_body_ratio
    bearish = close < open_ and close <= previous_close and body_ratio >= min_body_ratio
    confirmed = bullish if direction is TradeDirection.LONG else bearish
    return ConfirmationCandle(
        bullish=bullish,
        bearish=bearish,
        body_ratio=body_ratio,
        open=open_,
        high=high,
        low=low,
        close=close,
        confirmed=confirmed,
    )


def make_break_event(
    *,
    direction: TradeDirection,
    level: float,
    bar_index: int,
    close: float,
) -> BreakEvent:
    return BreakEvent(
        direction=direction,
        level=level,
        bar_index=bar_index,
        close=close,
    )


def make_retest_event(
    *,
    direction: TradeDirection,
    level: float,
    bar_index: int,
    low: float,
    high: float,
    successful: bool,
) -> RetestEvent:
    return RetestEvent(
        direction=direction,
        level=level,
        bar_index=bar_index,
        retest_low=low,
        retest_high=high,
        successful=successful,
    )


def resolve_break_level(
    frame: pd.DataFrame,
    *,
    direction: TradeDirection,
    lookback: int,
    high_column: str = "high",
    low_column: str = "low",
    exclude_tail: int = 3,
) -> float | None:
    """Recent resistance (long) or support (short) from bars before the signal tail.

    ``exclude_tail`` drops the newest bars so break / retest / confirmation can form
    without contaminating the level (default 3 bars).
    """
    tail = max(1, exclude_tail)
    if len(frame) <= tail:
        return None
    body = frame.iloc[:-tail]
    if body.empty:
        return None
    prior = body.iloc[-lookback:] if len(body) >= lookback else body
    if prior.empty:
        return None
    if direction is TradeDirection.LONG:
        return float(pd.to_numeric(prior[high_column], errors="coerce").max())
    return float(pd.to_numeric(prior[low_column], errors="coerce").min())
