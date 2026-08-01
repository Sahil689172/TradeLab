"""Pure evaluation helpers for Break & Retest trades."""

from __future__ import annotations

from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.risk_engine.stops import take_profit_from_risk
from app.services.strategy_engine.break_retest.schemas import (
    BreakRetestSequence,
    BreakRetestStage,
)
from app.strategies.break_retest.schemas import BreakRetestSetup, BreakRetestStopSource
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def assess_break_retest_setup(
    *,
    long_sequence: BreakRetestSequence,
    short_sequence: BreakRetestSequence,
    volume_ok: bool,
    structure: TrendDirection,
) -> BreakRetestSetup:
    """Prefer confirmed long, else confirmed short, with filters."""
    structure_bullish = structure is TrendDirection.BULLISH
    structure_bearish = structure is TrendDirection.BEARISH
    reasons: list[str] = []
    signal = SignalType.HOLD
    direction: TradeDirection | None = None
    structure_ok = False

    if long_sequence.stage is BreakRetestStage.FAILED_RETEST:
        reasons.extend(long_sequence.reasons)
    if short_sequence.stage is BreakRetestStage.FAILED_RETEST:
        reasons.extend(short_sequence.reasons)

    if long_sequence.stage is BreakRetestStage.CONFIRMED:
        structure_ok = structure_bullish
        if not volume_ok:
            reasons.append("Relative volume not healthy")
        if not structure_ok:
            reasons.append(f"Market structure {structure.value} is not bullish")
        if volume_ok and structure_ok:
            signal = SignalType.BUY
            direction = TradeDirection.LONG
            reasons = [
                *long_sequence.reasons,
                "Relative volume healthy",
                f"Market structure {structure.value}",
            ]
        else:
            reasons = [*long_sequence.reasons, *reasons]
    elif short_sequence.stage is BreakRetestStage.CONFIRMED:
        structure_ok = structure_bearish
        if not structure_ok:
            reasons.append(f"Market structure {structure.value} is not bearish")
        if structure_ok:
            signal = SignalType.SELL
            direction = TradeDirection.SHORT
            reasons = [
                *short_sequence.reasons,
                f"Market structure {structure.value}",
            ]
        else:
            reasons = [*short_sequence.reasons, *reasons]
    elif long_sequence.false_breakout or short_sequence.false_breakout:
        reasons.append("False breakout — break without completed retest/confirmation")
    else:
        reasons.extend(long_sequence.reasons[:1])
        reasons.extend(short_sequence.reasons[:1])

    return BreakRetestSetup(
        signal=signal,
        direction=direction,
        volume_ok=volume_ok,
        structure_ok=structure_ok,
        long_sequence=long_sequence,
        short_sequence=short_sequence,
        reasons=reasons,
    )


def select_break_retest_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    sequence: BreakRetestSequence,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[BreakRetestStopSource, float]:
    """Stop priority: retest extreme → ATR."""
    retest = sequence.retest_event
    if direction is TradeDirection.LONG:
        if retest is not None and 0 < retest.retest_low < entry_price:
            return BreakRetestStopSource.RETEST_LOW, retest.retest_low
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                return BreakRetestStopSource.ATR, atr_stop
    else:
        if retest is not None and retest.retest_high > entry_price:
            return BreakRetestStopSource.RETEST_HIGH, retest.retest_high
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                return BreakRetestStopSource.ATR, atr_stop
    raise StrategyValidationError("Unable to derive break/retest stop")


def select_targets(
    *,
    direction: TradeDirection,
    entry_price: float,
    stop_loss: float,
    risk_reward: float,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[float, float, float]:
    take_profit_1, realized_rr = take_profit_from_risk(
        entry_price,
        stop_loss,
        direction,
        risk_reward,
    )
    if atr_value is not None and atr_value > 0:
        if direction is TradeDirection.LONG:
            take_profit_2 = max(
                entry_price + atr_value * atr_multiplier,
                take_profit_1 + abs(take_profit_1 - entry_price) * 0.25,
            )
        else:
            take_profit_2 = min(
                entry_price - atr_value * atr_multiplier,
                take_profit_1 - abs(entry_price - take_profit_1) * 0.25,
            )
    else:
        extension = abs(take_profit_1 - entry_price) * 0.5
        take_profit_2 = (
            take_profit_1 + extension
            if direction is TradeDirection.LONG
            else take_profit_1 - extension
        )
    return take_profit_1, take_profit_2, realized_rr


def build_confidence(setup: BreakRetestSetup) -> float:
    points = 0.0
    active = (
        setup.long_sequence
        if setup.direction is TradeDirection.LONG
        else setup.short_sequence
        if setup.direction is TradeDirection.SHORT
        else setup.long_sequence
    )
    if active.stage is BreakRetestStage.CONFIRMED:
        points += 40.0
    elif active.stage is BreakRetestStage.RETESTED:
        points += 25.0
    elif active.stage is BreakRetestStage.BROKEN:
        points += 15.0
    if setup.volume_ok:
        points += 30.0
    if setup.structure_ok:
        points += 30.0
    return points / 100.0
