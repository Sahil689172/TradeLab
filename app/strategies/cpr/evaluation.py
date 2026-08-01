"""Pure evaluation helpers for the CPR strategy."""

from __future__ import annotations

import pandas as pd

from app.conditions import ConditionEngine
from app.levels.schemas import ClassicPivotLevels, CPRLevels, LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategies.cpr.config import CPRConfidenceWeights, CPRStrategyConfig
from app.strategies.cpr.schemas import (
    CPRClassification,
    CPRConfidenceBreakdown,
    CPRPositionClass,
    CPRSetupAssessment,
    CPRStopSource,
    CPRTradeMode,
    CPRWidthClass,
)
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def session_slice(frame: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    """Return bars belonging to the latest session calendar day."""
    as_of_day = pd.Timestamp(frame.iloc[-1][date_column]).normalize()
    dates = pd.to_datetime(frame[date_column])
    return frame.loc[dates.dt.normalize() == as_of_day].reset_index(drop=True)


def classify_cpr(
    *,
    cpr: CPRLevels,
    close: float,
    session: pd.DataFrame,
    config: CPRStrategyConfig,
    conditions: ConditionEngine,
) -> CPRClassification:
    """Classify CPR width, position, virgin status, and trade mode."""
    width = (
        CPRWidthClass.NARROW
        if cpr.width_pct <= config.narrow_cpr_threshold
        else CPRWidthClass.WIDE
    )
    mode = CPRTradeMode.TREND if width is CPRWidthClass.NARROW else CPRTradeMode.REVERSAL

    inside = conditions.inside_range(
        close,
        cpr.lower,
        cpr.upper,
        value_label="close",
    ).value
    position = CPRPositionClass.INSIDE if inside else CPRPositionClass.OUTSIDE

    virgin = _is_virgin_cpr(session, cpr=cpr, config=config, conditions=conditions)
    reasons = [
        f"CPR width {cpr.width_pct:.4%} → {width.value}",
        f"Price {position.value} CPR [{cpr.lower:.6g}, {cpr.upper:.6g}]",
        f"Virgin CPR: {virgin}",
        f"Trade mode: {mode.value}",
    ]
    return CPRClassification(
        width=width,
        position=position,
        virgin=virgin,
        mode=mode,
        width_pct=cpr.width_pct,
        reasons=reasons,
    )


def assess_cpr_setup(
    frame: pd.DataFrame,
    *,
    config: CPRStrategyConfig,
    levels: LevelsSnapshot,
    structure: MarketStructureResult,
    conditions: ConditionEngine,
) -> CPRSetupAssessment:
    """Evaluate CPR trend / reversal setups with VWAP confirmation."""
    cpr = levels.cpr
    session = session_slice(frame, date_column=config.date_column)
    latest = frame.iloc[-1]
    close = float(latest[config.close_column])
    high = float(latest[config.high_column])
    low = float(latest[config.low_column])

    classification = classify_cpr(
        cpr=cpr,
        close=close,
        session=session,
        config=config,
        conditions=conditions,
    )

    rvol_raw = latest[config.relative_volume_column]
    rvol = float(rvol_raw) if pd.notna(rvol_raw) else None
    relative_volume_ok = rvol is not None and rvol > config.relative_volume_threshold

    price_above_cpr = close > cpr.upper
    price_below_cpr = close < cpr.lower

    vwap_ok, vwap_bullish, vwap_bearish = _vwap_confirmation(latest, config)
    structure_bullish = structure.trend is TrendDirection.BULLISH
    structure_bearish = structure.trend is TrendDirection.BEARISH

    tolerance = abs(cpr.pivot) * config.cpr_touch_tolerance_pct
    support_bounce = conditions.retest(
        side="ABOVE",
        low=low,
        high=high,
        close=close,
        level=cpr.lower,
        tolerance=tolerance,
        level_label="CPR BC/lower",
    ).value
    resistance_reject = conditions.retest(
        side="BELOW",
        low=low,
        high=high,
        close=close,
        level=cpr.upper,
        tolerance=tolerance,
        level_label="CPR TC/upper",
    ).value

    reasons: list[str] = []
    signal = SignalType.HOLD
    direction: TradeDirection | None = None
    structure_ok = False
    mode_aligned = False
    vwap_filter_ok = False

    if classification.mode is CPRTradeMode.TREND:
        # Narrow CPR → breakout / trend continuation
        if price_above_cpr:
            structure_ok = structure_bullish
            vwap_filter_ok = vwap_bullish
            mode_aligned = True
            if not relative_volume_ok:
                reasons.append(_low_volume_reason(rvol, config))
            if not structure_ok:
                reasons.append(f"Structure {structure.trend.value} is not bullish")
            if not vwap_filter_ok:
                reasons.append("VWAP confirmation failed for long")
            if relative_volume_ok and structure_ok and vwap_filter_ok:
                signal = SignalType.BUY
                direction = TradeDirection.LONG
                reasons = [
                    f"Narrow CPR breakout: close {close:.6g} above TC {cpr.upper:.6g}",
                    "VWAP confirmation bullish",
                    f"Market structure {structure.trend.value}",
                    f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                    "Trend / continuation mode",
                ]
        elif price_below_cpr:
            structure_ok = structure_bearish
            vwap_filter_ok = vwap_bearish
            mode_aligned = True
            if not relative_volume_ok:
                reasons.append(_low_volume_reason(rvol, config))
            if not structure_ok:
                reasons.append(f"Structure {structure.trend.value} is not bearish")
            if not vwap_filter_ok:
                reasons.append("VWAP confirmation failed for short")
            if relative_volume_ok and structure_ok and vwap_filter_ok:
                signal = SignalType.SELL
                direction = TradeDirection.SHORT
                reasons = [
                    f"Narrow CPR breakdown: close {close:.6g} below BC {cpr.lower:.6g}",
                    "VWAP confirmation bearish",
                    f"Market structure {structure.trend.value}",
                    f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                    "Trend / continuation mode",
                ]
        else:
            reasons.append("Inside narrow CPR — waiting for breakout")
    else:
        # Wide CPR → support / resistance reversal
        if support_bounce and (price_above_cpr or close >= cpr.lower):
            structure_ok = structure_bullish
            vwap_filter_ok = vwap_bullish
            mode_aligned = True
            if not relative_volume_ok:
                reasons.append(_low_volume_reason(rvol, config))
            if not structure_ok:
                reasons.append(f"Structure {structure.trend.value} is not bullish")
            if not vwap_filter_ok:
                reasons.append("VWAP confirmation failed for support reversal")
            if relative_volume_ok and structure_ok and vwap_filter_ok:
                signal = SignalType.BUY
                direction = TradeDirection.LONG
                reasons = [
                    f"Wide CPR support reversal at BC {cpr.lower:.6g}",
                    "VWAP confirmation bullish",
                    f"Market structure {structure.trend.value}",
                    f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                    "Reversal mode",
                ]
        elif resistance_reject and (price_below_cpr or close <= cpr.upper):
            structure_ok = structure_bearish
            vwap_filter_ok = vwap_bearish
            mode_aligned = True
            if not relative_volume_ok:
                reasons.append(_low_volume_reason(rvol, config))
            if not structure_ok:
                reasons.append(f"Structure {structure.trend.value} is not bearish")
            if not vwap_filter_ok:
                reasons.append("VWAP confirmation failed for resistance reversal")
            if relative_volume_ok and structure_ok and vwap_filter_ok:
                signal = SignalType.SELL
                direction = TradeDirection.SHORT
                reasons = [
                    f"Wide CPR resistance reversal at TC {cpr.upper:.6g}",
                    "VWAP confirmation bearish",
                    f"Market structure {structure.trend.value}",
                    f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                    "Reversal mode",
                ]
        else:
            reasons.append("Wide CPR — no support/resistance reversal confirmed")

    reasons = [*classification.reasons, *reasons]

    return CPRSetupAssessment(
        signal=signal,
        direction=direction,
        price_above_cpr=price_above_cpr,
        price_below_cpr=price_below_cpr,
        vwap_ok=vwap_filter_ok if mode_aligned else vwap_ok,
        structure_ok=structure_ok,
        relative_volume_ok=relative_volume_ok,
        mode_aligned=mode_aligned,
        relative_volume=rvol,
        classification=classification,
        reasons=reasons,
    )


def build_confidence(
    setup: CPRSetupAssessment,
    weights: CPRConfidenceWeights,
) -> CPRConfidenceBreakdown:
    """Award scorecard points for CPR components."""
    position = weights.cpr_position if (setup.price_above_cpr or setup.price_below_cpr or setup.signal is not SignalType.HOLD) else 0.0
    vwap = weights.vwap_confirmation if setup.vwap_ok else 0.0
    structure = weights.structure if setup.structure_ok else 0.0
    volume = weights.relative_volume if setup.relative_volume_ok else 0.0
    mode = weights.mode_alignment if setup.mode_aligned else 0.0
    raw = position + vwap + structure + volume + mode
    normalized = 100.0 * raw / weights.total
    reasons = [
        f"CPR position: {position:g}/{weights.cpr_position:g}",
        f"VWAP confirmation: {vwap:g}/{weights.vwap_confirmation:g}",
        f"Structure: {structure:g}/{weights.structure:g}",
        f"Relative volume: {volume:g}/{weights.relative_volume:g}",
        f"Mode alignment: {mode:g}/{weights.mode_alignment:g}",
        f"Total: {normalized:.2f}/100",
    ]
    return CPRConfidenceBreakdown(
        cpr_position=position,
        vwap_confirmation=vwap,
        structure=structure,
        relative_volume=volume,
        mode_alignment=mode,
        total=round(normalized, 4),
        reasons=reasons,
    )


def select_cpr_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    cpr: CPRLevels,
    previous_swing: float | None,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[CPRStopSource, float]:
    """Stop priority: nearest CPR level → previous swing → ATR."""
    candidates: list[tuple[CPRStopSource, float]] = []
    if direction is TradeDirection.LONG:
        cpr_stops = [level for level in (cpr.lower, cpr.pivot, cpr.bc, cpr.tc) if 0 < level < entry_price]
        if cpr_stops:
            nearest = max(cpr_stops)  # nearest below entry
            candidates.append((CPRStopSource.CPR_LEVEL, nearest))
        if previous_swing is not None and previous_swing < entry_price:
            candidates.append((CPRStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                candidates.append((CPRStopSource.ATR, atr_stop))
    else:
        cpr_stops = [level for level in (cpr.upper, cpr.pivot, cpr.bc, cpr.tc) if level > entry_price]
        if cpr_stops:
            nearest = min(cpr_stops)  # nearest above entry
            candidates.append((CPRStopSource.CPR_LEVEL, nearest))
        if previous_swing is not None and previous_swing > entry_price:
            candidates.append((CPRStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                candidates.append((CPRStopSource.ATR, atr_stop))

    if not candidates:
        raise StrategyValidationError("Unable to derive a valid CPR stop loss")
    return candidates[0]


def select_cpr_targets(
    *,
    direction: TradeDirection,
    entry_price: float,
    classic: ClassicPivotLevels,
    stop_loss: float,
    risk_reward_fallback: float,
) -> tuple[tuple[float, str], tuple[float, str], float]:
    """Targets R1/R2/R3 (long) or S1/S2/S3 (short); fallback to RR if needed."""
    risk = abs(entry_price - stop_loss)
    if direction is TradeDirection.LONG:
        ladder = [
            (classic.resistance_1, "Classic R1"),
            (classic.resistance_2, "Classic R2"),
            (classic.resistance_3, "Classic R3"),
        ]
        above = [(price, label) for price, label in ladder if price > entry_price]
        if len(above) >= 2:
            tp1, label1 = above[0]
            tp2, label2 = above[1]
        elif len(above) == 1:
            tp1, label1 = above[0]
            tp2, label2 = entry_price + risk * risk_reward_fallback * 1.5, "Fallback extension"
        else:
            tp1 = entry_price + risk * risk_reward_fallback
            tp2 = entry_price + risk * risk_reward_fallback * 1.5
            label1, label2 = "RR fallback TP1", "RR fallback TP2"
        rr = 0.0 if risk <= 0 else abs(tp1 - entry_price) / risk
        return (tp1, label1), (tp2, label2), rr

    ladder = [
        (classic.support_1, "Classic S1"),
        (classic.support_2, "Classic S2"),
        (classic.support_3, "Classic S3"),
    ]
    below = [(price, label) for price, label in ladder if price < entry_price]
    if len(below) >= 2:
        tp1, label1 = below[0]
        tp2, label2 = below[1]
    elif len(below) == 1:
        tp1, label1 = below[0]
        tp2, label2 = entry_price - risk * risk_reward_fallback * 1.5, "Fallback extension"
    else:
        tp1 = entry_price - risk * risk_reward_fallback
        tp2 = entry_price - risk * risk_reward_fallback * 1.5
        label1, label2 = "RR fallback TP1", "RR fallback TP2"
    rr = 0.0 if risk <= 0 else abs(entry_price - tp1) / risk
    return (tp1, label1), (tp2, label2), rr


def _is_virgin_cpr(
    session: pd.DataFrame,
    *,
    cpr: CPRLevels,
    config: CPRStrategyConfig,
    conditions: ConditionEngine,
) -> bool:
    """True when the session has not touched the CPR band yet."""
    if session.empty:
        return True
    tol = abs(cpr.pivot) * config.cpr_touch_tolerance_pct
    for _, row in session.iterrows():
        low = float(row[config.low_column])
        high = float(row[config.high_column])
        # Band touch if range intersects [lower, upper] with tolerance.
        touched_lower = conditions.touches(
            low,
            high,
            cpr.lower,
            tolerance=tol,
            level_label="CPR lower",
        ).value
        touched_upper = conditions.touches(
            low,
            high,
            cpr.upper,
            tolerance=tol,
            level_label="CPR upper",
        ).value
        overlaps = (low - tol) <= cpr.upper and (high + tol) >= cpr.lower
        if touched_lower or touched_upper or overlaps:
            return False
    return True


def _vwap_confirmation(
    latest: pd.Series,
    config: CPRStrategyConfig,
) -> tuple[bool, bool, bool]:
    """Return (any_side_ok, bullish_ok, bearish_ok) using attached VWAP columns."""
    if config.vwap_column not in latest.index or pd.isna(latest[config.vwap_column]):
        return False, False, False
    close = float(latest[config.close_column])
    vwap = float(latest[config.vwap_column])
    bullish = close > vwap
    bearish = close < vwap
    return bullish or bearish, bullish, bearish


def _low_volume_reason(rvol: float | None, config: CPRStrategyConfig) -> str:
    return (
        f"Low volume: RVOL {rvol if rvol is not None else 'n/a'} "
        f"(need > {config.relative_volume_threshold:g})"
    )
