"""Pure evaluation helpers for the Previous Day breakout sequence."""

from __future__ import annotations

import pandas as pd

from app.conditions import ConditionEngine
from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategies.previous_day_breakout.config import (
    ConfidenceWeights,
    PreviousDayBreakoutConfig,
)
from app.strategies.previous_day_breakout.schemas import (
    ConfidenceBreakdown,
    LevelsUsed,
    SetupAssessment,
    SetupSide,
    SetupStage,
    StopSource,
)
from app.strategy_engine.models import SignalType


def assess_long_setup(
    frame: pd.DataFrame,
    *,
    pdh: float,
    config: PreviousDayBreakoutConfig,
    structure_trend: TrendDirection,
    conditions: ConditionEngine,
) -> SetupAssessment:
    """Scan 15m bars for a completed bullish PDH Magic Box sequence."""
    return _assess_setup(
        frame,
        level=pdh,
        side=SetupSide.PREVIOUS_DAY_HIGH,
        direction=TradeDirection.LONG,
        structure_ok=structure_trend is TrendDirection.BULLISH,
        structure_trend=structure_trend,
        config=config,
        conditions=conditions,
    )


def assess_short_setup(
    frame: pd.DataFrame,
    *,
    pdl: float,
    config: PreviousDayBreakoutConfig,
    structure_trend: TrendDirection,
    conditions: ConditionEngine,
) -> SetupAssessment:
    """Scan 15m bars for a completed bearish PDL Magic Box sequence."""
    return _assess_setup(
        frame,
        level=pdl,
        side=SetupSide.PREVIOUS_DAY_LOW,
        direction=TradeDirection.SHORT,
        structure_ok=structure_trend is TrendDirection.BEARISH,
        structure_trend=structure_trend,
        config=config,
        conditions=conditions,
    )


def _assess_setup(
    frame: pd.DataFrame,
    *,
    level: float,
    side: SetupSide,
    direction: TradeDirection,
    structure_ok: bool,
    structure_trend: TrendDirection,
    config: PreviousDayBreakoutConfig,
    conditions: ConditionEngine,
) -> SetupAssessment:
    tolerance = level * config.approach_tolerance_pct
    approached = False
    broken = False
    retested = False
    failed_retest = False
    break_index: int | None = None
    retest_index: int | None = None
    reasons: list[str] = []

    high_col = config.high_column
    low_col = config.low_column
    close_col = config.close_column
    open_col = config.open_column
    volume_col = config.volume_column

    for index in range(1, len(frame)):
        prev = frame.iloc[index - 1]
        curr = frame.iloc[index]
        prev_close = float(prev[close_col])
        close = float(curr[close_col])
        high = float(curr[high_col])
        low = float(curr[low_col])
        open_ = float(curr[open_col])

        if not broken:
            touch = conditions.touches(
                low,
                high,
                level,
                tolerance=tolerance,
                level_label=side.value,
            )
            if touch.value:
                approached = True

            if direction is TradeDirection.LONG:
                brk = conditions.breaks_above(
                    prev_close,
                    close,
                    level,
                    level_label=side.value,
                )
            else:
                brk = conditions.breaks_below(
                    prev_close,
                    close,
                    level,
                    level_label=side.value,
                )
            if approached and brk.value:
                broken = True
                break_index = index
            continue

        # After break: look for retest or failure.
        if broken and not retested and not failed_retest:
            if direction is TradeDirection.LONG:
                # Failed retest: close back below PDH after break.
                if close < level:
                    failed_retest = True
                    reasons.append(f"Failed retest: close {close:.6g} back below PDH {level:.6g}")
                    continue
                retest = conditions.retest(
                    side="ABOVE",
                    low=low,
                    high=high,
                    close=close,
                    level=level,
                    tolerance=tolerance,
                    level_label=side.value,
                )
            else:
                if close > level:
                    failed_retest = True
                    reasons.append(f"Failed retest: close {close:.6g} back above PDL {level:.6g}")
                    continue
                retest = conditions.retest(
                    side="BELOW",
                    low=low,
                    high=high,
                    close=close,
                    level=level,
                    tolerance=tolerance,
                    level_label=side.value,
                )
            if retest.value:
                retested = True
                retest_index = index

    latest = frame.iloc[-1]
    close = float(latest[close_col])
    open_ = float(latest[open_col])
    high = float(latest[high_col])
    low = float(latest[low_col])
    rvol = float(latest[volume_col]) if volume_col in frame.columns and pd.notna(latest[volume_col]) else None
    relative_volume_ok = rvol is not None and rvol > config.relative_volume_threshold

    if direction is TradeDirection.LONG:
        confirmation_candle = close > open_ and close >= float(frame.iloc[-2][close_col])
    else:
        confirmation_candle = close < open_ and close <= float(frame.iloc[-2][close_col])

    # Entry requires retest on or before the latest bar, with filters on the latest bar.
    entry_ready = (
        broken
        and retested
        and not failed_retest
        and confirmation_candle
        and relative_volume_ok
        and structure_ok
        and retest_index is not None
        and retest_index <= len(frame) - 1
    )
    # Confirmation should occur on the retest bar or a later bar (latest).
    if entry_ready and retest_index is not None and retest_index > len(frame) - 1:
        entry_ready = False

    if failed_retest:
        stage = SetupStage.FAILED_RETEST
        signal = SignalType.HOLD
    elif entry_ready:
        stage = SetupStage.ENTRY
        signal = SignalType.BUY if direction is TradeDirection.LONG else SignalType.SELL
    elif retested:
        stage = SetupStage.RETESTED
        signal = SignalType.HOLD
        if not confirmation_candle:
            reasons.append("Retest complete but confirmation candle missing")
        if not relative_volume_ok:
            reasons.append(
                f"Weak relative volume {rvol if rvol is not None else 'n/a'} "
                f"(need > {config.relative_volume_threshold:g})",
            )
        if not structure_ok:
            reasons.append(f"Market structure {structure_trend.value} blocks entry")
    elif broken:
        stage = SetupStage.BROKEN
        signal = SignalType.HOLD
        reasons.append(f"{side.value} broken; waiting for retest")
    elif approached:
        stage = SetupStage.APPROACHED
        signal = SignalType.HOLD
        reasons.append(f"Approached {side.value}; waiting for break")
    else:
        stage = SetupStage.IDLE
        signal = SignalType.HOLD
        reasons.append(f"No interaction with {side.value} yet")

    if entry_ready:
        reasons = [
            f"{side.value} approach confirmed",
            f"{side.value} break confirmed",
            f"{side.value} retest confirmed",
            "Confirmation candle present",
            f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
            f"Market structure {structure_trend.value}",
        ]

    return SetupAssessment(
        side=side,
        stage=stage,
        direction=direction if entry_ready else None,
        signal=signal,
        approached=approached,
        broken=broken,
        retested=retested,
        failed_retest=failed_retest,
        confirmation_candle=confirmation_candle,
        relative_volume_ok=relative_volume_ok,
        structure_ok=structure_ok,
        relative_volume=rvol,
        entry_index=len(frame) - 1 if entry_ready else None,
        break_index=break_index,
        retest_index=retest_index,
        reasons=reasons,
    )


def build_confidence(
    setup: SetupAssessment,
    weights: ConfidenceWeights,
) -> ConfidenceBreakdown:
    """Award scorecard points for completed Magic Box components."""
    level_break = weights.level_break if setup.broken else 0.0
    retest = weights.retest if setup.retested and not setup.failed_retest else 0.0
    relative_volume = weights.relative_volume if setup.relative_volume_ok else 0.0
    confirmation_candle = weights.confirmation_candle if setup.confirmation_candle else 0.0
    market_structure = weights.market_structure if setup.structure_ok else 0.0
    total = level_break + retest + relative_volume + confirmation_candle + market_structure
    # Normalize to 0–100 against configured weight total.
    normalized = 100.0 * total / weights.total
    reasons = [
        f"Level break: {level_break:g}/{weights.level_break:g}",
        f"Retest: {retest:g}/{weights.retest:g}",
        f"Relative volume: {relative_volume:g}/{weights.relative_volume:g}",
        f"Confirmation candle: {confirmation_candle:g}/{weights.confirmation_candle:g}",
        f"Market structure: {market_structure:g}/{weights.market_structure:g}",
        f"Total: {normalized:.2f}/100",
    ]
    return ConfidenceBreakdown(
        level_break=level_break,
        retest=retest,
        relative_volume=relative_volume,
        confirmation_candle=confirmation_candle,
        market_structure=market_structure,
        total=round(normalized, 4),
        reasons=reasons,
    )


def select_stop_loss(
    *,
    direction: TradeDirection,
    entry_price: float,
    previous_candle_low: float,
    previous_candle_high: float,
    previous_day_high: float,
    previous_day_low: float,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[float, StopSource]:
    """Choose stop by priority: previous candle → PD level → ATR × multiplier."""
    candidates: list[tuple[StopSource, float]] = []

    if direction is TradeDirection.LONG:
        if previous_candle_low < entry_price:
            candidates.append((StopSource.PREVIOUS_CANDLE, previous_candle_low))
        if previous_day_low < entry_price:
            candidates.append((StopSource.PREVIOUS_DAY_LEVEL, previous_day_low))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if atr_stop > 0 and atr_stop < entry_price:
                candidates.append((StopSource.ATR, atr_stop))
        # Prefer first valid in priority order (already appended in priority order).
        if not candidates:
            raise ValueError("Unable to derive a valid long stop loss")
        return candidates[0]

    if previous_candle_high > entry_price:
        candidates.append((StopSource.PREVIOUS_CANDLE, previous_candle_high))
    if previous_day_high > entry_price:
        candidates.append((StopSource.PREVIOUS_DAY_LEVEL, previous_day_high))
    if atr_value is not None and atr_value > 0:
        atr_stop = entry_price + atr_value * atr_multiplier
        if atr_stop > entry_price:
            candidates.append((StopSource.ATR, atr_stop))
    if not candidates:
        raise ValueError("Unable to derive a valid short stop loss")
    return candidates[0]


def select_take_profit_2(
    *,
    direction: TradeDirection,
    entry_price: float,
    levels: LevelsSnapshot,
    take_profit_1: float,
) -> tuple[float, str]:
    """Nearest resistance (long) or support (short); fallback to 1.5× TP1 distance."""
    if direction is TradeDirection.LONG:
        resistances = [level for level in levels.resistances if level.price > entry_price]
        if resistances:
            nearest = min(resistances, key=lambda item: item.price)
            return float(nearest.price), nearest.label
        fallback = entry_price + abs(take_profit_1 - entry_price) * 1.5
        return fallback, "Fallback extension (1.5x TP1 distance)"

    supports = [level for level in levels.supports if level.price < entry_price]
    if supports:
        nearest = max(supports, key=lambda item: item.price)
        return float(nearest.price), nearest.label
    fallback = entry_price - abs(entry_price - take_profit_1) * 1.5
    return fallback, "Fallback extension (1.5x TP1 distance)"


def levels_used_from_snapshot(
    levels: LevelsSnapshot,
    *,
    entry_level: float,
    target_2: float,
    target_2_label: str,
) -> LevelsUsed:
    return LevelsUsed(
        previous_day_high=levels.previous_day_high,
        previous_day_low=levels.previous_day_low,
        entry_level=entry_level,
        target_2_level=target_2,
        target_2_label=target_2_label,
    )
