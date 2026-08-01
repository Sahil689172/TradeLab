"""Pure evaluation helpers for the VWAP strategy."""

from __future__ import annotations

import pandas as pd

from app.conditions import ConditionEngine
from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategies.vwap.config import VWAPConfidenceWeights, VWAPStrategyConfig
from app.strategies.vwap.schemas import (
    VWAPConfidenceBreakdown,
    VWAPSetupAssessment,
    VWAPStopSource,
)
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def assess_vwap_setup(
    frame: pd.DataFrame,
    *,
    config: VWAPStrategyConfig,
    structure: MarketStructureResult,
    conditions: ConditionEngine,
) -> VWAPSetupAssessment:
    """Evaluate buy/sell VWAP conditions on the latest bar."""
    latest = frame.iloc[-1]
    close = float(latest[config.close_column])
    high = float(latest[config.high_column])
    low = float(latest[config.low_column])
    vwap = float(latest[config.vwap_column])
    slope_raw = latest[config.slope_column]
    slope = float(slope_raw) if pd.notna(slope_raw) else 0.0

    rvol_raw = latest[config.relative_volume_column]
    rvol = float(rvol_raw) if pd.notna(rvol_raw) else None
    relative_volume_ok = rvol is not None and rvol > config.relative_volume_threshold

    price_above = conditions.compare(
        close,
        ">",
        vwap,
        left_label="close",
        right_label="VWAP",
    ).value
    price_below = conditions.compare(
        close,
        "<",
        vwap,
        left_label="close",
        right_label="VWAP",
    ).value
    slope_positive = slope > 0
    slope_negative = slope < 0

    tolerance = abs(vwap) * config.retest_tolerance
    retest_ok = conditions.retest(
        side="ABOVE",
        low=low,
        high=high,
        close=close,
        level=vwap,
        tolerance=tolerance,
        level_label="VWAP",
    ).value
    rejection_ok = conditions.retest(
        side="BELOW",
        low=low,
        high=high,
        close=close,
        level=vwap,
        tolerance=tolerance,
        level_label="VWAP",
    ).value

    structure_bullish = structure.trend is TrendDirection.BULLISH
    structure_bearish = structure.trend is TrendDirection.BEARISH

    reasons: list[str] = []
    signal = SignalType.HOLD
    direction: TradeDirection | None = None
    structure_ok = False

    if price_above and slope_positive:
        structure_ok = structure_bullish
        if not relative_volume_ok:
            reasons.append(
                f"Low volume: RVOL {rvol if rvol is not None else 'n/a'} "
                f"(need > {config.relative_volume_threshold:g})",
            )
        if not structure_ok:
            reasons.append(f"Structure {structure.trend.value} is not bullish")
        if not retest_ok:
            reasons.append("VWAP retest confirmation failed")
        if relative_volume_ok and structure_ok and retest_ok:
            signal = SignalType.BUY
            direction = TradeDirection.LONG
            reasons = [
                f"Close {close:.6g} above VWAP {vwap:.6g}",
                f"VWAP slope positive ({slope:.6g})",
                f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                f"Market structure {structure.trend.value}",
                "Successful VWAP retest",
            ]
    elif price_below and slope_negative:
        structure_ok = structure_bearish
        if not relative_volume_ok:
            reasons.append(
                f"Low volume: RVOL {rvol if rvol is not None else 'n/a'} "
                f"(need > {config.relative_volume_threshold:g})",
            )
        if not structure_ok:
            reasons.append(f"Structure {structure.trend.value} is not bearish")
        if not rejection_ok:
            reasons.append("VWAP rejection confirmation failed")
        if relative_volume_ok and structure_ok and rejection_ok:
            signal = SignalType.SELL
            direction = TradeDirection.SHORT
            reasons = [
                f"Close {close:.6g} below VWAP {vwap:.6g}",
                f"VWAP slope negative ({slope:.6g})",
                f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                f"Market structure {structure.trend.value}",
                "VWAP rejection confirmed",
            ]
    else:
        if not price_above and not price_below:
            reasons.append("Price at VWAP (no clear side)")
        elif price_above and not slope_positive:
            reasons.append("Price above VWAP but slope is not positive")
        elif price_below and not slope_negative:
            reasons.append("Price below VWAP but slope is not negative")
        else:
            reasons.append("VWAP setup incomplete")

    return VWAPSetupAssessment(
        signal=signal,
        direction=direction,
        price_above_vwap=price_above,
        price_below_vwap=price_below,
        slope_positive=slope_positive,
        slope_negative=slope_negative,
        relative_volume_ok=relative_volume_ok,
        structure_ok=structure_ok,
        retest_ok=retest_ok,
        rejection_ok=rejection_ok,
        relative_volume=rvol,
        reasons=reasons,
    )


def build_confidence(
    setup: VWAPSetupAssessment,
    weights: VWAPConfidenceWeights,
) -> VWAPConfidenceBreakdown:
    """Award scorecard points for VWAP components."""
    position = weights.vwap_position if (setup.price_above_vwap or setup.price_below_vwap) else 0.0
    slope = weights.slope if (setup.slope_positive or setup.slope_negative) else 0.0
    volume = weights.relative_volume if setup.relative_volume_ok else 0.0
    structure = weights.structure if setup.structure_ok else 0.0
    retest = weights.retest_confirmation if (setup.retest_ok or setup.rejection_ok) else 0.0
    raw = position + slope + volume + structure + retest
    normalized = 100.0 * raw / weights.total
    reasons = [
        f"VWAP position: {position:g}/{weights.vwap_position:g}",
        f"Slope: {slope:g}/{weights.slope:g}",
        f"Relative volume: {volume:g}/{weights.relative_volume:g}",
        f"Structure: {structure:g}/{weights.structure:g}",
        f"Retest confirmation: {retest:g}/{weights.retest_confirmation:g}",
        f"Total: {normalized:.2f}/100",
    ]
    return VWAPConfidenceBreakdown(
        vwap_position=position,
        slope=slope,
        relative_volume=volume,
        structure=structure,
        retest_confirmation=retest,
        total=round(normalized, 4),
        reasons=reasons,
    )


def select_vwap_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    vwap_value: float,
    previous_swing: float | None,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[VWAPStopSource, float]:
    """Stop priority: VWAP → previous swing → ATR × multiplier."""
    candidates: list[tuple[VWAPStopSource, float]] = []
    if direction is TradeDirection.LONG:
        if 0 < vwap_value < entry_price:
            candidates.append((VWAPStopSource.VWAP, vwap_value))
        if previous_swing is not None and previous_swing < entry_price:
            candidates.append((VWAPStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                candidates.append((VWAPStopSource.ATR, atr_stop))
    else:
        if vwap_value > entry_price:
            candidates.append((VWAPStopSource.VWAP, vwap_value))
        if previous_swing is not None and previous_swing > entry_price:
            candidates.append((VWAPStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                candidates.append((VWAPStopSource.ATR, atr_stop))

    if not candidates:
        raise StrategyValidationError("Unable to derive a valid VWAP stop loss")
    return candidates[0]


def select_take_profit_2(
    *,
    direction: TradeDirection,
    entry_price: float,
    levels: LevelsSnapshot | None,
    take_profit_1: float,
) -> tuple[float, str]:
    """Nearest resistance (long) or support (short); fallback beyond TP1."""
    if levels is not None:
        if direction is TradeDirection.LONG:
            resistances = [level for level in levels.resistances if level.price > entry_price]
            if resistances:
                nearest = min(resistances, key=lambda item: item.price)
                return float(nearest.price), nearest.label
        else:
            supports = [level for level in levels.supports if level.price < entry_price]
            if supports:
                nearest = max(supports, key=lambda item: item.price)
                return float(nearest.price), nearest.label

    risk = abs(take_profit_1 - entry_price)
    if direction is TradeDirection.LONG:
        return entry_price + risk * 1.5, "Fallback extension (1.5x TP1 distance)"
    return entry_price - risk * 1.5, "Fallback extension (1.5x TP1 distance)"
