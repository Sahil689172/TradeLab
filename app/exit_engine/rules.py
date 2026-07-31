"""Individual exit rule evaluators."""

from __future__ import annotations

import pandas as pd

from app.exit_engine.exceptions import ExitValidationError
from app.exit_engine.schemas import (
    ExitConfig,
    ExitMethod,
    ExitSignal,
    TradeExitState,
)
from app.exit_engine.supertrend import compute_supertrend
from app.risk_engine.schemas import TradeDirection


def evaluate_fixed_target(
    state: TradeExitState,
    *,
    close: float,
    high: float,
    low: float,
    config: ExitConfig,
) -> ExitSignal:
    """Exit when the fixed take-profit level is reached."""
    target = config.take_profit
    if target is None:
        return _idle(ExitMethod.FIXED_TARGET, "Fixed target not configured")

    if state.direction is TradeDirection.LONG:
        hit = high >= target or close >= target
    else:
        hit = low <= target or close <= target

    return ExitSignal(
        method=ExitMethod.FIXED_TARGET,
        triggered=hit,
        exit_price=target if hit else None,
        exit_fraction=1.0 if hit else 0.0,
        reason=(
            f"Fixed target {target:.6g} hit (close={close:.6g})"
            if hit
            else f"Fixed target {target:.6g} not reached (close={close:.6g})"
        ),
    )


def evaluate_partial_exit(
    state: TradeExitState,
    *,
    close: float,
    high: float,
    low: float,
    config: ExitConfig,
) -> ExitSignal:
    """Scale out a fraction once partial R-multiple is reached."""
    if state.remaining_fraction < 1.0:
        return _idle(ExitMethod.PARTIAL_EXIT, "Partial exit already taken")
    if config.initial_stop is None:
        return _idle(ExitMethod.PARTIAL_EXIT, "Partial exit requires initial_stop")

    risk = abs(state.entry_price - config.initial_stop)
    if risk <= 0:
        raise ExitValidationError("initial_stop must differ from entry_price")

    if state.direction is TradeDirection.LONG:
        trigger = state.entry_price + risk * config.partial_trigger_r
        hit = high >= trigger or close >= trigger
        exit_price = trigger
    else:
        trigger = state.entry_price - risk * config.partial_trigger_r
        hit = low <= trigger or close <= trigger
        exit_price = trigger

    return ExitSignal(
        method=ExitMethod.PARTIAL_EXIT,
        triggered=hit,
        exit_price=exit_price if hit else None,
        exit_fraction=config.partial_fraction if hit else 0.0,
        reason=(
            f"Partial exit {config.partial_fraction:.0%} at {exit_price:.6g} "
            f"({config.partial_trigger_r:g}R)"
            if hit
            else f"Partial trigger {trigger:.6g} not reached"
        ),
    )


def evaluate_break_even(
    state: TradeExitState,
    *,
    close: float,
    high: float,
    low: float,
    config: ExitConfig,
) -> ExitSignal:
    """Exit at entry once break-even is armed and price revisits entry."""
    if config.initial_stop is None:
        return _idle(ExitMethod.BREAK_EVEN, "Break-even requires initial_stop")

    risk = abs(state.entry_price - config.initial_stop)
    if risk <= 0:
        raise ExitValidationError("initial_stop must differ from entry_price")

    if state.direction is TradeDirection.LONG:
        arm_level = state.entry_price + risk * config.break_even_trigger_r
        armed = state.break_even_armed or high >= arm_level or close >= arm_level
        hit = armed and (low <= state.entry_price or close <= state.entry_price)
    else:
        arm_level = state.entry_price - risk * config.break_even_trigger_r
        armed = state.break_even_armed or low <= arm_level or close <= arm_level
        hit = armed and (high >= state.entry_price or close >= state.entry_price)

    return ExitSignal(
        method=ExitMethod.BREAK_EVEN,
        triggered=hit,
        exit_price=state.entry_price if hit else None,
        exit_fraction=1.0 if hit else 0.0,
        reason=(
            f"Break-even exit at entry {state.entry_price:.6g}"
            if hit
            else (
                f"Break-even armed={armed} arm_level={arm_level:.6g}; "
                f"waiting for revisit of entry"
            )
        ),
    )


def evaluate_trailing_stop(
    state: TradeExitState,
    *,
    close: float,
    atr_value: float | None,
    config: ExitConfig,
) -> ExitSignal:
    """Trail stop from favorable extreme using ATR and/or percent distance."""
    distance: float | None = None
    parts: list[str] = []
    if config.trailing_percent is not None:
        distance = state.entry_price * config.trailing_percent
        parts.append(f"pct={config.trailing_percent:.2%}")
    if atr_value is not None:
        atr_distance = atr_value * config.trailing_atr_multiplier
        distance = atr_distance if distance is None else max(distance, atr_distance)
        parts.append(f"atr={atr_value:.6g}x{config.trailing_atr_multiplier:g}")
    if distance is None:
        return _idle(ExitMethod.TRAILING_STOP, "Trailing stop requires ATR or trailing_percent")

    if state.direction is TradeDirection.LONG:
        stop = state.extreme_high - distance
        hit = close <= stop
    else:
        stop = state.extreme_low + distance
        hit = close >= stop

    return ExitSignal(
        method=ExitMethod.TRAILING_STOP,
        triggered=hit,
        exit_price=stop if hit else None,
        exit_fraction=1.0 if hit else 0.0,
        reason=(
            f"Trailing stop hit at {stop:.6g} ({', '.join(parts)})"
            if hit
            else f"Trailing stop at {stop:.6g} not hit (close={close:.6g})"
        ),
    )


def evaluate_atr_exit(
    state: TradeExitState,
    *,
    close: float,
    atr_value: float,
    config: ExitConfig,
) -> ExitSignal:
    """Exit when adverse move from entry exceeds ATR * multiplier."""
    distance = atr_value * config.atr_multiplier
    if state.direction is TradeDirection.LONG:
        level = state.entry_price - distance
        hit = close <= level
    else:
        level = state.entry_price + distance
        hit = close >= level

    return ExitSignal(
        method=ExitMethod.ATR_EXIT,
        triggered=hit,
        exit_price=level if hit else None,
        exit_fraction=1.0 if hit else 0.0,
        reason=(
            f"ATR exit at {level:.6g} (ATR={atr_value:.6g} x {config.atr_multiplier:g})"
            if hit
            else f"ATR exit level {level:.6g} not reached"
        ),
    )


def evaluate_ema_exit(
    state: TradeExitState,
    *,
    close: float,
    ema_value: float,
    config: ExitConfig,
) -> ExitSignal:
    """Exit when close crosses adversely through the configured EMA."""
    if state.direction is TradeDirection.LONG:
        hit = close < ema_value
    else:
        hit = close > ema_value

    return ExitSignal(
        method=ExitMethod.EMA_EXIT,
        triggered=hit,
        exit_price=close if hit else None,
        exit_fraction=1.0 if hit else 0.0,
        reason=(
            f"EMA exit: close {close:.6g} vs {config.ema_column}={ema_value:.6g}"
            if hit
            else f"EMA hold: close {close:.6g} vs {config.ema_column}={ema_value:.6g}"
        ),
    )


def evaluate_supertrend_exit(
    state: TradeExitState,
    market: pd.DataFrame,
    *,
    config: ExitConfig,
    atr: pd.Series | None = None,
) -> ExitSignal:
    """Exit when SuperTrend flips against the trade direction."""
    required = {"high", "low", "close"}
    missing = required - set(market.columns)
    if missing:
        return _idle(
            ExitMethod.SUPERTREND_EXIT,
            f"SuperTrend requires columns {sorted(required)}; missing {sorted(missing)}",
        )
    if len(market) < config.supertrend_period + 1:
        return _idle(
            ExitMethod.SUPERTREND_EXIT,
            f"Need at least {config.supertrend_period + 1} bars for SuperTrend",
        )

    st = compute_supertrend(
        market["high"],
        market["low"],
        market["close"],
        period=config.supertrend_period,
        multiplier=config.supertrend_multiplier,
        atr=atr,
    )
    direction = float(st["direction"].iloc[-1])
    level = float(st["supertrend"].iloc[-1])
    close = float(market["close"].iloc[-1])

    if state.direction is TradeDirection.LONG:
        hit = direction < 0
    else:
        hit = direction > 0

    return ExitSignal(
        method=ExitMethod.SUPERTREND_EXIT,
        triggered=hit,
        exit_price=close if hit else None,
        exit_fraction=1.0 if hit else 0.0,
        reason=(
            f"SuperTrend flipped against trade (dir={direction:g}, line={level:.6g})"
            if hit
            else f"SuperTrend supports trade (dir={direction:g}, line={level:.6g})"
        ),
    )


def evaluate_time_exit(
    state: TradeExitState,
    *,
    close: float,
    config: ExitConfig,
) -> ExitSignal:
    """Force exit after max holding bars."""
    hit = state.bars_held >= config.max_bars
    return ExitSignal(
        method=ExitMethod.TIME_EXIT,
        triggered=hit,
        exit_price=close if hit else None,
        exit_fraction=1.0 if hit else 0.0,
        reason=(
            f"Time exit after {state.bars_held} bars (max={config.max_bars})"
            if hit
            else f"Time exit not reached ({state.bars_held}/{config.max_bars} bars)"
        ),
    )


def _idle(method: ExitMethod, reason: str) -> ExitSignal:
    return ExitSignal(
        method=method,
        triggered=False,
        exit_price=None,
        exit_fraction=0.0,
        reason=reason,
    )
