"""Pure evaluation helpers for Donchian / Turtle trades."""

from __future__ import annotations

import pandas as pd

from app.conditions import ComparisonOperator, ConditionEngine
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.exit_engine.schemas import ExitAction
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.risk_engine.stops import take_profit_from_risk
from app.services.strategy_engine.indicators.donchian import DonchianSnapshot
from app.strategies.donchian.config import (
    DonchianConfidenceWeights,
    DonchianStrategyConfig,
)
from app.strategies.donchian.schemas import (
    DonchianConfidenceBreakdown,
    DonchianExitAssessment,
    DonchianExitReason,
    DonchianSetup,
    DonchianStopSource,
)
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def ema_trend_bullish(
    features: pd.DataFrame,
    *,
    config: DonchianStrategyConfig,
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


def assess_donchian_setup(
    *,
    snapshot: DonchianSnapshot,
    structure: MarketStructureResult,
    ema_bullish: bool,
    volume_ok: bool,
    atr_ok: bool,
    cooldown_bars: int,
) -> DonchianSetup:
    """Evaluate BUY / SELL / HOLD with Turtle-style filters."""
    sideways = structure.trend is TrendDirection.SIDEWAYS
    structure_bullish = structure.trend is TrendDirection.BULLISH
    structure_bearish = structure.trend is TrendDirection.BEARISH

    prior_upper = snapshot.bars_since_upper_breakout
    prior_lower = snapshot.bars_since_lower_breakout
    cooldown_ok_long = (
        cooldown_bars <= 0
        or prior_upper is None
        or prior_upper >= cooldown_bars
    )
    cooldown_ok_short = (
        cooldown_bars <= 0
        or prior_lower is None
        or prior_lower >= cooldown_bars
    )

    false_breakout = snapshot.false_breakout_above or snapshot.false_breakout_below
    reasons: list[str] = []
    signal = SignalType.HOLD
    direction: TradeDirection | None = None
    structure_ok = False
    cooldown_ok = True

    if sideways:
        reasons.append("Sideways market — entries blocked")
    if not volume_ok:
        reasons.append("Weak / low relative volume")
    if not atr_ok:
        reasons.append("ATR below configured health threshold")
    if false_breakout and not snapshot.breakout_above and not snapshot.breakout_below:
        reasons.append("False breakout (wick beyond channel, close inside)")

    buy_ready = (
        snapshot.breakout_above
        and ema_bullish
        and volume_ok
        and structure_bullish
        and atr_ok
        and not sideways
        and cooldown_ok_long
        and not snapshot.false_breakout_above
    )
    sell_ready = snapshot.breakout_below and cooldown_ok_short

    if buy_ready:
        signal = SignalType.BUY
        direction = TradeDirection.LONG
        structure_ok = True
        cooldown_ok = True
        reasons = [
            f"Close above upper Donchian ({snapshot.entry_lookback}-period entry channel)",
            "EMA trend bullish",
            "Relative volume healthy",
            f"Market structure {structure.trend.value}",
            "ATR healthy",
            "Breakout cooldown clear",
        ]
    elif snapshot.breakout_above and not buy_ready:
        cooldown_ok = cooldown_ok_long
        structure_ok = structure_bullish
        if not cooldown_ok_long:
            reasons.insert(0, "Recent upper breakout within cooldown window")
        reasons.insert(0, "Upper breakout rejected by filters")
    elif sell_ready:
        signal = SignalType.SELL
        direction = TradeDirection.SHORT
        structure_ok = structure_bearish
        cooldown_ok = True
        reasons = [
            f"Close below lower Donchian ({snapshot.entry_lookback}-period entry channel)",
        ]
        if structure_bearish:
            reasons.append(f"Market structure {structure.trend.value}")
    elif snapshot.breakout_below and not cooldown_ok_short:
        cooldown_ok = False
        reasons.insert(0, "Recent lower breakout within cooldown window")
    elif not reasons:
        reasons.append("No Donchian breakout setup")

    return DonchianSetup(
        signal=signal,
        direction=direction,
        breakout_above=snapshot.breakout_above,
        breakout_below=snapshot.breakout_below,
        false_breakout=false_breakout,
        ema_bullish=ema_bullish,
        volume_ok=volume_ok,
        structure_ok=structure_ok,
        atr_ok=atr_ok,
        cooldown_ok=cooldown_ok,
        sideways_blocked=sideways,
        snapshot=snapshot,
        reasons=reasons,
    )


def evaluate_donchian_exit(
    *,
    direction: TradeDirection,
    snapshot: DonchianSnapshot,
    structure: MarketStructureResult,
    entry_price: float,
    atr_value: float | None,
    config: DonchianStrategyConfig,
    features: pd.DataFrame,
    exit_engine: ExitEngine,
    bars_held: int,
    extreme_high: float,
    extreme_low: float,
) -> DonchianExitAssessment:
    """Exit: exit-channel close · ATR trailing · ATR exit · adverse trend."""
    close = snapshot.close

    if direction is TradeDirection.LONG:
        if snapshot.close_below_exit_channel:
            return DonchianExitAssessment(
                should_exit=True,
                reason=DonchianExitReason.EXIT_CHANNEL,
                detail=(
                    f"Close {close:.6g} below exit channel low "
                    f"{snapshot.exit_lower:.6g} ({snapshot.exit_lookback}-period)"
                ),
                exit_price=close,
            )
        if structure.trend is TrendDirection.BEARISH:
            return DonchianExitAssessment(
                should_exit=True,
                reason=DonchianExitReason.TREND_BEARISH,
                detail="Market structure turned bearish",
                exit_price=close,
            )
    else:
        if snapshot.close_above_exit_channel:
            return DonchianExitAssessment(
                should_exit=True,
                reason=DonchianExitReason.EXIT_CHANNEL,
                detail=(
                    f"Close {close:.6g} above exit channel high "
                    f"{snapshot.exit_upper:.6g} ({snapshot.exit_lookback}-period)"
                ),
                exit_price=close,
            )
        if structure.trend is TrendDirection.BULLISH:
            return DonchianExitAssessment(
                should_exit=True,
                reason=DonchianExitReason.TREND_BULLISH,
                detail="Market structure turned bullish against short",
                exit_price=close,
            )

    if atr_value is not None and atr_value > 0:
        state = make_state(
            entry_price=entry_price,
            direction=direction,
            bars_held=bars_held,
            extreme_high=extreme_high,
            extreme_low=extreme_low,
        )
        trail = exit_engine.evaluate(
            state=state,
            market=features,
            config=ExitConfig(
                atr_column=config.atr_column,
                atr_multiplier=config.atr_exit_multiplier,
                trailing_atr_multiplier=config.atr_trail_multiplier,
                max_bars=config.max_holding_bars,
                enabled_methods=(ExitMethod.TRAILING_STOP, ExitMethod.ATR_EXIT),
            ),
        )
        if trail.decision is ExitAction.FULL_EXIT:
            method = trail.method
            if method is ExitMethod.TRAILING_STOP:
                reason = DonchianExitReason.ATR_TRAILING
            elif method is ExitMethod.ATR_EXIT:
                reason = DonchianExitReason.ATR_EXIT
            else:
                reason = DonchianExitReason.ATR_EXIT
            return DonchianExitAssessment(
                should_exit=True,
                reason=reason,
                detail=trail.reason,
                exit_price=trail.exit_price or close,
            )

    return DonchianExitAssessment(
        should_exit=False,
        reason=DonchianExitReason.NONE,
        detail="No Donchian exit trigger",
        exit_price=None,
    )


def select_donchian_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    middle: float,
    previous_swing: float | None,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[DonchianStopSource, float]:
    """Stop priority: Middle Channel → ATR × m → previous swing."""
    candidates: list[tuple[DonchianStopSource, float]] = []
    if direction is TradeDirection.LONG:
        if 0 < middle < entry_price:
            candidates.append((DonchianStopSource.MIDDLE_CHANNEL, middle))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                candidates.append((DonchianStopSource.ATR, atr_stop))
        if previous_swing is not None and previous_swing < entry_price:
            candidates.append((DonchianStopSource.PREVIOUS_SWING, previous_swing))
    else:
        if middle > entry_price:
            candidates.append((DonchianStopSource.MIDDLE_CHANNEL, middle))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                candidates.append((DonchianStopSource.ATR, atr_stop))
        if previous_swing is not None and previous_swing > entry_price:
            candidates.append((DonchianStopSource.PREVIOUS_SWING, previous_swing))

    if not candidates:
        raise StrategyValidationError("Unable to derive a valid Donchian stop")
    return candidates[0]


def select_targets(
    *,
    direction: TradeDirection,
    entry_price: float,
    stop_loss: float,
    risk_reward: float,
    use_fixed_rr: bool,
    snapshot: DonchianSnapshot,
) -> tuple[float | None, float | None, float, str]:
    """Open trend-following targets: optional fixed RR + trailing Donchian exit."""
    if use_fixed_rr:
        take_profit_1, realized_rr = take_profit_from_risk(
            entry_price,
            stop_loss,
            direction,
            risk_reward,
        )
    else:
        take_profit_1 = None
        realized_rr = 0.0

    # Soft TP2 reference: opposite exit-channel extreme (trailing Donchian path)
    if direction is TradeDirection.LONG:
        take_profit_2 = snapshot.exit_upper if snapshot.exit_upper > entry_price else None
    else:
        take_profit_2 = snapshot.exit_lower if snapshot.exit_lower < entry_price else None

    note = (
        "Open trend-following · fixed RR + trailing Donchian / ATR exit"
        if use_fixed_rr
        else "Open trend-following · trailing Donchian exit / ATR exit (no fixed RR)"
    )
    return take_profit_1, take_profit_2, realized_rr, note


def build_confidence(
    setup: DonchianSetup,
    weights: DonchianConfidenceWeights,
) -> DonchianConfidenceBreakdown:
    breakout = weights.channel_breakout if (
        setup.breakout_above or setup.breakout_below
    ) else 0.0
    trend = weights.trend if setup.ema_bullish else 0.0
    volume = weights.volume if setup.volume_ok else 0.0
    structure = weights.market_structure if setup.structure_ok else 0.0
    atr = weights.atr if setup.atr_ok else 0.0
    raw = breakout + trend + volume + structure + atr
    total = 100.0 * raw / weights.total if weights.total > 0 else 0.0
    reasons = [
        f"Channel breakout: {breakout:g}/{weights.channel_breakout:g}",
        f"Trend: {trend:g}/{weights.trend:g}",
        f"Volume: {volume:g}/{weights.volume:g}",
        f"Market structure: {structure:g}/{weights.market_structure:g}",
        f"ATR: {atr:g}/{weights.atr:g}",
    ]
    return DonchianConfidenceBreakdown(
        channel_breakout=breakout,
        trend=trend,
        volume=volume,
        market_structure=structure,
        atr=atr,
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
