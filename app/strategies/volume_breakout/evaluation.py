"""Pure evaluation helpers for Volume Breakout."""

from __future__ import annotations

import pandas as pd

from app.conditions import ConditionEngine
from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.indicators.volume_analysis import VolumeStatistics
from app.strategies.volume_breakout.config import (
    VolumeBreakoutConfidenceWeights,
    VolumeBreakoutConfig,
)
from app.strategies.volume_breakout.schemas import (
    VolumeBreakoutConfidenceBreakdown,
    VolumeBreakoutSetupAssessment,
    VolumeBreakoutStopSource,
)
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def session_slice(frame: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    as_of_day = pd.Timestamp(frame.iloc[-1][date_column]).normalize()
    dates = pd.to_datetime(frame[date_column])
    return frame.loc[dates.dt.normalize() == as_of_day].reset_index(drop=True)


def resolve_breakout_levels(
    frame: pd.DataFrame,
    *,
    config: VolumeBreakoutConfig,
    levels: LevelsSnapshot | None,
) -> tuple[float | None, float | None]:
    """Recent resistance / support from Levels or lookback highs/lows."""
    prior = frame.iloc[:-1]
    if prior.empty:
        return None, None

    resistance: float | None = None
    support: float | None = None

    if levels is not None:
        entry = float(frame.iloc[-1][config.close_column])
        above = [level.price for level in levels.resistances if level.price > entry * 0.99]
        below = [level.price for level in levels.supports if level.price < entry * 1.01]
        # Prefer levels that the prior close was still inside of (breakout candidates)
        prior_close = float(prior.iloc[-1][config.close_column])
        resist_candidates = [
            level.price
            for level in levels.resistances
            if level.price >= prior_close
        ]
        support_candidates = [
            level.price
            for level in levels.supports
            if level.price <= prior_close
        ]
        if resist_candidates:
            resistance = min(resist_candidates)
        elif above:
            resistance = min(above)
        if support_candidates:
            support = max(support_candidates)
        elif below:
            support = max(below)

    lookback = min(config.resistance_lookback, len(prior))
    window = prior.iloc[-lookback:]
    roll_high = float(window[config.high_column].max())
    roll_low = float(window[config.low_column].min())
    if resistance is None:
        resistance = roll_high
    if support is None:
        support = roll_low
    return resistance, support


def assess_volume_breakout(
    frame: pd.DataFrame,
    *,
    config: VolumeBreakoutConfig,
    structure: MarketStructureResult,
    volume_stats: VolumeStatistics,
    conditions: ConditionEngine,
    levels: LevelsSnapshot | None = None,
) -> VolumeBreakoutSetupAssessment:
    """Evaluate volume-confirmed breakout / breakdown on the latest bar."""
    latest = frame.iloc[-1]
    prior = frame.iloc[-2] if len(frame) >= 2 else latest
    close = float(latest[config.close_column])
    open_ = float(latest[config.open_column])
    high = float(latest[config.high_column])
    low = float(latest[config.low_column])
    prior_close = float(prior[config.close_column])

    resistance, support = resolve_breakout_levels(frame, config=config, levels=levels)

    broke_resistance = False
    broke_support = False
    if resistance is not None:
        broke_resistance = conditions.breaks_above(
            prior_close,
            close,
            resistance,
            level_label="resistance",
        ).value
    if support is not None:
        broke_support = conditions.breaks_below(
            prior_close,
            close,
            support,
            level_label="support",
        ).value

    relative_volume_ok = (
        volume_stats.relative_volume_20 is not None
        and volume_stats.relative_volume_20 > config.relative_volume_threshold
    )
    above_average_volume = volume_stats.above_average_20
    structure_bullish = structure.trend is TrendDirection.BULLISH
    structure_bearish = structure.trend is TrendDirection.BEARISH

    vwap_ok_long = False
    vwap_ok_short = False
    if config.vwap_column in latest.index and pd.notna(latest[config.vwap_column]):
        vwap = float(latest[config.vwap_column])
        vwap_ok_long = close > vwap
        vwap_ok_short = close < vwap

    candle_ok = _strong_body(open_, high, low, close, config.min_body_ratio)
    session = session_slice(frame, date_column=config.date_column)
    session_index = max(0, len(session) - 1)
    late_session = session_index > config.max_session_bar_index

    volume_decreasing = volume_stats.decreasing or (
        volume_stats.contraction and not volume_stats.spike
    )
    breakout_without_volume = (broke_resistance or broke_support) and not (
        relative_volume_ok and above_average_volume
    )
    false_breakout = bool(
        breakout_without_volume
        or volume_decreasing
        or not candle_ok
        or late_session
    )

    reasons: list[str] = []
    signal = SignalType.HOLD
    direction: TradeDirection | None = None
    structure_ok = False
    vwap_ok = False

    if late_session and (broke_resistance or broke_support):
        reasons.append(f"Late session breakout (bar {session_index})")
    elif breakout_without_volume:
        reasons.append("Price breakout without sufficient volume")
    elif volume_decreasing and (broke_resistance or broke_support):
        reasons.append("Volume decreasing / contraction on breakout")
    elif not candle_ok and (broke_resistance or broke_support):
        reasons.append("Weak candle body on breakout")
    elif broke_resistance:
        structure_ok = structure_bullish
        vwap_ok = vwap_ok_long
        if not relative_volume_ok:
            reasons.append(
                f"RVOL {volume_stats.relative_volume_20} "
                f"(need > {config.relative_volume_threshold:g})",
            )
        if not above_average_volume:
            reasons.append("Volume not above 20-period average")
        if not structure_ok:
            reasons.append(f"Structure {structure.trend.value} is not bullish")
        if not vwap_ok:
            reasons.append("Close is not above VWAP")
        if (
            relative_volume_ok
            and above_average_volume
            and structure_ok
            and vwap_ok
            and candle_ok
            and not late_session
            and not volume_stats.decreasing
        ):
            signal = SignalType.BUY
            direction = TradeDirection.LONG
            reasons = [
                f"Broke resistance {resistance:.6g}",
                (
                    f"Relative volume {volume_stats.relative_volume_20:.3g} "
                    f"> {config.relative_volume_threshold:g}"
                ),
                "Volume above 20-period average",
                f"Market structure {structure.trend.value}",
                "Close above VWAP",
                "Volume expansion / spike confirmed",
            ]
    elif broke_support:
        structure_ok = structure_bearish
        vwap_ok = vwap_ok_short
        if not relative_volume_ok:
            reasons.append(
                f"RVOL {volume_stats.relative_volume_20} "
                f"(need > {config.relative_volume_threshold:g})",
            )
        if not above_average_volume:
            reasons.append("Volume not above 20-period average")
        if not structure_ok:
            reasons.append(f"Structure {structure.trend.value} is not bearish")
        if not vwap_ok:
            reasons.append("Close is not below VWAP")
        if (
            relative_volume_ok
            and above_average_volume
            and structure_ok
            and vwap_ok
            and candle_ok
            and not late_session
            and not volume_stats.decreasing
        ):
            signal = SignalType.SELL
            direction = TradeDirection.SHORT
            reasons = [
                f"Broke support {support:.6g}",
                (
                    f"Relative volume {volume_stats.relative_volume_20:.3g} "
                    f"> {config.relative_volume_threshold:g}"
                ),
                "Volume above 20-period average",
                f"Market structure {structure.trend.value}",
                "Close below VWAP",
                "Volume expansion / spike confirmed",
            ]
    else:
        reasons.append("No resistance/support breakout on latest bar")

    # Final false-breakout gate
    if signal is not SignalType.HOLD and false_breakout:
        # Recompute false_breakout excluding volume_decreasing when expansion true
        if volume_stats.decreasing or not candle_ok or late_session or breakout_without_volume:
            signal = SignalType.HOLD
            direction = None
            if "False breakout" not in " ".join(reasons):
                reasons.append("False breakout filter rejected signal")

    return VolumeBreakoutSetupAssessment(
        signal=signal,
        direction=direction,
        broke_resistance=broke_resistance,
        broke_support=broke_support,
        relative_volume_ok=relative_volume_ok,
        above_average_volume=above_average_volume,
        structure_ok=structure_ok,
        vwap_ok=vwap_ok if (broke_resistance or broke_support) else (vwap_ok_long or vwap_ok_short),
        candle_ok=candle_ok,
        late_session=late_session,
        false_breakout=false_breakout and signal is SignalType.HOLD,
        resistance_level=resistance,
        support_level=support,
        volume_stats=volume_stats,
        reasons=reasons,
    )


def build_confidence(
    setup: VolumeBreakoutSetupAssessment,
    weights: VolumeBreakoutConfidenceWeights,
) -> VolumeBreakoutConfidenceBreakdown:
    level = weights.level_break if (setup.broke_resistance or setup.broke_support) else 0.0
    volume = weights.relative_volume if setup.relative_volume_ok and setup.above_average_volume else 0.0
    structure = weights.structure if setup.structure_ok else 0.0
    vwap = weights.vwap if setup.vwap_ok else 0.0
    candle = weights.candle_quality if setup.candle_ok else 0.0
    raw = level + volume + structure + vwap + candle
    normalized = 100.0 * raw / weights.total
    reasons = [
        f"Level break: {level:g}/{weights.level_break:g}",
        f"Relative volume: {volume:g}/{weights.relative_volume:g}",
        f"Structure: {structure:g}/{weights.structure:g}",
        f"VWAP: {vwap:g}/{weights.vwap:g}",
        f"Candle quality: {candle:g}/{weights.candle_quality:g}",
        f"Total: {normalized:.2f}/100",
    ]
    return VolumeBreakoutConfidenceBreakdown(
        level_break=level,
        relative_volume=volume,
        structure=structure,
        vwap=vwap,
        candle_quality=candle,
        total=round(normalized, 4),
        reasons=reasons,
    )


def select_volume_breakout_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    previous_swing: float | None,
    atr_value: float | None,
    atr_multiplier: float,
    vwap_value: float | None,
) -> tuple[VolumeBreakoutStopSource, float]:
    """Stop priority: previous swing → ATR → VWAP."""
    candidates: list[tuple[VolumeBreakoutStopSource, float]] = []
    if direction is TradeDirection.LONG:
        if previous_swing is not None and previous_swing < entry_price:
            candidates.append((VolumeBreakoutStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                candidates.append((VolumeBreakoutStopSource.ATR, atr_stop))
        if vwap_value is not None and 0 < vwap_value < entry_price:
            candidates.append((VolumeBreakoutStopSource.VWAP, vwap_value))
    else:
        if previous_swing is not None and previous_swing > entry_price:
            candidates.append((VolumeBreakoutStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                candidates.append((VolumeBreakoutStopSource.ATR, atr_stop))
        if vwap_value is not None and vwap_value > entry_price:
            candidates.append((VolumeBreakoutStopSource.VWAP, vwap_value))

    if not candidates:
        raise StrategyValidationError("Unable to derive a valid volume-breakout stop")
    return candidates[0]


def select_targets(
    *,
    direction: TradeDirection,
    entry_price: float,
    stop_loss: float,
    risk_reward: float,
    atr_value: float | None,
    atr_multiplier: float,
    levels: LevelsSnapshot | None,
) -> tuple[float, float, float, str]:
    """TP1 via RR; TP2 nearest resistance/support or ATR projection."""
    from app.risk_engine.stops import take_profit_from_risk

    take_profit_1, realized_rr = take_profit_from_risk(
        entry_price,
        stop_loss,
        direction,
        risk_reward,
    )

    label = "ATR projection"
    if levels is not None:
        if direction is TradeDirection.LONG:
            resistances = [level for level in levels.resistances if level.price > entry_price]
            if resistances:
                nearest = min(resistances, key=lambda item: item.price)
                take_profit_2 = float(nearest.price)
                label = nearest.label
                if take_profit_2 <= take_profit_1:
                    take_profit_2 = _atr_or_extend(
                        direction, entry_price, take_profit_1, atr_value, atr_multiplier,
                    )
                    label = "ATR projection"
                return take_profit_1, take_profit_2, realized_rr, label
        else:
            supports = [level for level in levels.supports if level.price < entry_price]
            if supports:
                nearest = max(supports, key=lambda item: item.price)
                take_profit_2 = float(nearest.price)
                label = nearest.label
                if take_profit_2 >= take_profit_1:
                    take_profit_2 = _atr_or_extend(
                        direction, entry_price, take_profit_1, atr_value, atr_multiplier,
                    )
                    label = "ATR projection"
                return take_profit_1, take_profit_2, realized_rr, label

    take_profit_2 = _atr_or_extend(
        direction, entry_price, take_profit_1, atr_value, atr_multiplier,
    )
    return take_profit_1, take_profit_2, realized_rr, label


def _atr_or_extend(
    direction: TradeDirection,
    entry_price: float,
    take_profit_1: float,
    atr_value: float | None,
    atr_multiplier: float,
) -> float:
    if atr_value is not None and atr_value > 0:
        if direction is TradeDirection.LONG:
            projected = entry_price + atr_value * atr_multiplier
            return max(projected, take_profit_1 + abs(take_profit_1 - entry_price) * 0.25)
        projected = entry_price - atr_value * atr_multiplier
        return min(projected, take_profit_1 - abs(entry_price - take_profit_1) * 0.25)
    risk = abs(take_profit_1 - entry_price)
    if direction is TradeDirection.LONG:
        return take_profit_1 + risk * 0.5
    return take_profit_1 - risk * 0.5


def _strong_body(
    open_: float,
    high: float,
    low: float,
    close: float,
    min_body_ratio: float,
) -> bool:
    span = high - low
    if span <= 0:
        return False
    body = abs(close - open_)
    return (body / span) >= min_body_ratio
