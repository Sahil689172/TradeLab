"""Pure evaluation helpers for SuperTrend trades."""

from __future__ import annotations

import pandas as pd

from app.conditions import ComparisonOperator, ConditionEngine
from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.risk_engine.stops import take_profit_from_risk
from app.services.strategy_engine.indicators.supertrend import SuperTrendSnapshot
from app.strategies.supertrend.config import (
    SuperTrendConfidenceWeights,
    SuperTrendStrategyConfig,
)
from app.strategies.supertrend.schemas import (
    SuperTrendConfidenceBreakdown,
    SuperTrendSetup,
    SuperTrendStopSource,
)
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def ema_trend_bullish(
    features: pd.DataFrame,
    *,
    config: SuperTrendStrategyConfig,
    conditions: ConditionEngine,
) -> bool:
    """True when close > slow EMA and fast EMA >= slow EMA."""
    fast_col = config.ema_fast_column
    slow_col = config.ema_slow_column
    if fast_col not in features.columns or slow_col not in features.columns:
        return False
    fast = float(features.iloc[-1][fast_col])
    slow = float(features.iloc[-1][slow_col])
    close = float(features.iloc[-1][config.close_column])
    return (
        conditions.compare(close, ComparisonOperator.GT, slow).value
        and conditions.compare(fast, ComparisonOperator.GTE, slow).value
    )


def assess_supertrend_setup(
    *,
    snapshot: SuperTrendSnapshot,
    structure: MarketStructureResult,
    ema_bullish: bool,
    volume_ok: bool,
    atr_ok: bool,
) -> SuperTrendSetup:
    """Evaluate BUY / SELL / HOLD filters on the latest SuperTrend state."""
    sideways = structure.trend is TrendDirection.SIDEWAYS
    structure_bullish = structure.trend is TrendDirection.BULLISH
    structure_bearish = structure.trend is TrendDirection.BEARISH

    reasons: list[str] = []
    signal = SignalType.HOLD
    direction: TradeDirection | None = None
    structure_ok = False

    # Filters that block new long entries
    if sideways:
        reasons.append("Sideways market — entries blocked")
    if not volume_ok:
        reasons.append("Low / insufficient relative volume")
    if not atr_ok:
        reasons.append("ATR below configured health threshold")
    if not structure_bullish and not structure_bearish:
        reasons.append("Weak market structure")

    buy_ready = (
        snapshot.flipped_to_bullish
        and snapshot.close_above
        and ema_bullish
        and volume_ok
        and structure_bullish
        and atr_ok
        and not sideways
    )
    sell_on_flip = snapshot.flipped_to_bearish
    sell_on_close = snapshot.close_below and snapshot.bearish

    if buy_ready:
        signal = SignalType.BUY
        direction = TradeDirection.LONG
        structure_ok = True
        reasons = [
            "SuperTrend flipped bearish → bullish",
            "Price closes above SuperTrend",
            "EMA trend bullish",
            "Relative volume healthy",
            f"Market structure {structure.trend.value}",
            "ATR healthy",
        ]
    elif sell_on_flip or sell_on_close:
        signal = SignalType.SELL
        direction = TradeDirection.SHORT
        structure_ok = structure_bearish
        reasons = []
        if sell_on_flip:
            reasons.append("SuperTrend flipped bullish → bearish")
        if snapshot.close_below:
            reasons.append("Price closes below SuperTrend")
        if structure_bearish:
            reasons.append(f"Market structure {structure.trend.value}")
    else:
        if snapshot.flipped_to_bullish and not buy_ready:
            reasons.insert(0, "Bullish SuperTrend flip rejected by filters (false signal)")
        elif snapshot.bullish and snapshot.close_above:
            reasons.append("Bullish SuperTrend — waiting for flip + confirmations")
        elif snapshot.bearish:
            reasons.append("Bearish SuperTrend — no fresh sell trigger")
        else:
            reasons.append("No SuperTrend trade setup")

    return SuperTrendSetup(
        signal=signal,
        direction=direction,
        trend_flip_bullish=snapshot.flipped_to_bullish,
        trend_flip_bearish=snapshot.flipped_to_bearish,
        close_above_supertrend=snapshot.close_above,
        close_below_supertrend=snapshot.close_below,
        ema_bullish=ema_bullish,
        volume_ok=volume_ok,
        structure_ok=structure_ok,
        atr_ok=atr_ok,
        sideways_blocked=sideways,
        snapshot=snapshot,
        reasons=reasons,
    )


def select_supertrend_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    supertrend_value: float,
    previous_swing: float | None,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[SuperTrendStopSource, float]:
    """Stop priority: SuperTrend line → previous swing → ATR × multiplier."""
    candidates: list[tuple[SuperTrendStopSource, float]] = []
    if direction is TradeDirection.LONG:
        if 0 < supertrend_value < entry_price:
            candidates.append((SuperTrendStopSource.SUPERTREND, supertrend_value))
        if previous_swing is not None and previous_swing < entry_price:
            candidates.append((SuperTrendStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                candidates.append((SuperTrendStopSource.ATR, atr_stop))
    else:
        if supertrend_value > entry_price:
            candidates.append((SuperTrendStopSource.SUPERTREND, supertrend_value))
        if previous_swing is not None and previous_swing > entry_price:
            candidates.append((SuperTrendStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                candidates.append((SuperTrendStopSource.ATR, atr_stop))

    if not candidates:
        raise StrategyValidationError("Unable to derive a valid SuperTrend stop")
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
    """TP1 via RR 1:2; TP2 nearest resistance/support or ATR projection."""
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
                label = f"Nearest resistance ({nearest.label})"
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
                label = f"Nearest support ({nearest.label})"
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


def build_confidence(
    setup: SuperTrendSetup,
    weights: SuperTrendConfidenceWeights,
) -> SuperTrendConfidenceBreakdown:
    """Weighted confidence scorecard (normalized to 0–100)."""
    trend = weights.trend_change if (
        setup.trend_flip_bullish or setup.trend_flip_bearish
    ) else 0.0
    ema = weights.ema_confirmation if setup.ema_bullish else 0.0
    structure = weights.market_structure if setup.structure_ok else 0.0
    volume = weights.relative_volume if setup.volume_ok else 0.0
    atr = weights.atr_health if setup.atr_ok else 0.0
    raw = trend + ema + structure + volume + atr
    total = 100.0 * raw / weights.total if weights.total > 0 else 0.0
    reasons = [
        f"Trend change: {trend:g}/{weights.trend_change:g}",
        f"EMA confirmation: {ema:g}/{weights.ema_confirmation:g}",
        f"Market structure: {structure:g}/{weights.market_structure:g}",
        f"Relative volume: {volume:g}/{weights.relative_volume:g}",
        f"ATR health: {atr:g}/{weights.atr_health:g}",
    ]
    return SuperTrendConfidenceBreakdown(
        trend_change=trend,
        ema_confirmation=ema,
        market_structure=structure,
        relative_volume=volume,
        atr_health=atr,
        total=total,
        reasons=reasons,
    )


def previous_swing_for_stop(
    structure: MarketStructureResult,
    *,
    direction: TradeDirection,
) -> float | None:
    if direction is TradeDirection.LONG and structure.last_swing_low is not None:
        return structure.last_swing_low.price
    if direction is TradeDirection.SHORT and structure.last_swing_high is not None:
        return structure.last_swing_high.price
    return None


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
    extension = abs(take_profit_1 - entry_price) * 0.5
    if direction is TradeDirection.LONG:
        return take_profit_1 + extension
    return take_profit_1 - extension
