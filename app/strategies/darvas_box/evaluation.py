"""Pure evaluation helpers for Darvas Box strategy."""

from __future__ import annotations

import pandas as pd

from app.conditions import ConditionEngine, ComparisonOperator
from app.risk_engine.schemas import TradeDirection
from app.risk_engine.stops import take_profit_from_risk
from app.services.strategy_engine.darvas.schemas import DarvasBox, DarvasBoxSnapshot
from app.services.strategy_engine.indicators.volume_analysis import VolumeStatistics
from app.strategies.darvas_box.config import DarvasBoxStrategyConfig
from app.strategies.darvas_box.schemas import DarvasSetup, DarvasStopSource
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def assess_darvas_setup(
    *,
    snapshot: DarvasBoxSnapshot,
    volume_stats: VolumeStatistics,
    ema_trend_bullish: bool,
) -> DarvasSetup:
    """BUY on upside breakout with volume + EMA; SELL on breakdown."""
    reasons: list[str] = list(snapshot.reasons)
    volume_expansion = volume_stats.expansion or volume_stats.spike
    signal = SignalType.HOLD
    direction: TradeDirection | None = None

    if snapshot.breakout and snapshot.box is not None:
        if not volume_expansion:
            reasons.append("Breakout without volume expansion")
        if not ema_trend_bullish:
            reasons.append("EMA trend is not bullish")
        if volume_expansion and ema_trend_bullish:
            signal = SignalType.BUY
            direction = TradeDirection.LONG
            reasons = [
                f"Close above upper box {snapshot.box.upper:.6g}",
                "Volume expansion confirmed",
                "EMA trend bullish",
            ]
    elif snapshot.breakdown and snapshot.box is not None:
        signal = SignalType.SELL
        direction = TradeDirection.SHORT
        reasons = [
            f"Close below lower box {snapshot.box.lower:.6g}",
        ]
    elif not snapshot.breakout and not snapshot.breakdown:
        if "Consolidation" not in " ".join(reasons) and snapshot.consolidating:
            reasons.append("Price consolidating inside Darvas box")

    return DarvasSetup(
        signal=signal,
        direction=direction,
        breakout=snapshot.breakout,
        breakdown=snapshot.breakdown,
        volume_expansion=volume_expansion,
        ema_trend_bullish=ema_trend_bullish,
        snapshot=snapshot,
        reasons=reasons,
    )


def select_darvas_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    box: DarvasBox,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[DarvasStopSource, float]:
    """Stop priority: Lower Box (long) / Upper Box (short) → ATR."""
    if direction is TradeDirection.LONG:
        if 0 < box.lower < entry_price:
            return DarvasStopSource.LOWER_BOX, box.lower
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                return DarvasStopSource.ATR, atr_stop
    else:
        if box.upper > entry_price:
            return DarvasStopSource.UPPER_BOX, box.upper
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                return DarvasStopSource.ATR, atr_stop
    raise StrategyValidationError("Unable to derive Darvas stop loss")


def select_darvas_targets(
    *,
    direction: TradeDirection,
    entry_price: float,
    stop_loss: float,
    risk_reward: float,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[float, float, float]:
    """TP1 via RR; TP2 via ATR projection."""
    take_profit_1, realized_rr = take_profit_from_risk(
        entry_price,
        stop_loss,
        direction,
        risk_reward,
    )
    if atr_value is not None and atr_value > 0:
        if direction is TradeDirection.LONG:
            take_profit_2 = entry_price + atr_value * atr_multiplier
            if take_profit_2 <= take_profit_1:
                take_profit_2 = take_profit_1 + abs(take_profit_1 - entry_price) * 0.5
        else:
            take_profit_2 = entry_price - atr_value * atr_multiplier
            if take_profit_2 >= take_profit_1:
                take_profit_2 = take_profit_1 - abs(entry_price - take_profit_1) * 0.5
    else:
        extension = abs(take_profit_1 - entry_price) * 0.5
        take_profit_2 = (
            take_profit_1 + extension
            if direction is TradeDirection.LONG
            else take_profit_1 - extension
        )
    return take_profit_1, take_profit_2, realized_rr


def ema_trend_bullish(
    features: pd.DataFrame,
    *,
    config: DarvasBoxStrategyConfig,
    conditions: ConditionEngine,
) -> bool:
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


def build_confidence(setup: DarvasSetup) -> float:
    points = 0.0
    if setup.breakout or setup.breakdown:
        points += 40.0
    if setup.volume_expansion:
        points += 30.0
    if setup.ema_trend_bullish:
        points += 30.0
    return points / 100.0
