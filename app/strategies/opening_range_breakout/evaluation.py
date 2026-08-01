"""Pure evaluation helpers for Opening Range Breakout."""

from __future__ import annotations

import pandas as pd

from app.conditions import ConditionEngine
from app.levels.exceptions import LevelsValidationError
from app.levels.calculator import opening_range
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategies.opening_range_breakout.config import (
    OpeningRangeBreakoutConfig,
    ORBConfidenceWeights,
)
from app.strategies.opening_range_breakout.schemas import (
    OpeningRangeLevels,
    ORBConfidenceBreakdown,
    ORBSetupAssessment,
    ORBStopSource,
)
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import SignalType


def resolve_opening_range(
    frame: pd.DataFrame,
    *,
    config: OpeningRangeBreakoutConfig,
) -> OpeningRangeLevels:
    """Compute ORH / ORL / ORM via the Levels Engine calculator."""
    as_of = pd.Timestamp(frame.iloc[-1][config.date_column])
    try:
        high, low = opening_range(
            frame,
            as_of,
            opening_range_bars=config.opening_range_bars,
        )
    except LevelsValidationError as exc:
        raise StrategyValidationError(f"Unable to resolve opening range: {exc}") from exc

    mid = (high + low) / 2.0
    range_pct = 0.0 if mid <= 0 else (high - low) / mid
    return OpeningRangeLevels(
        high=high,
        low=low,
        mid=mid,
        bars=config.opening_range_bars,
        minutes=config.opening_range_minutes,
        range_pct=range_pct,
    )


def session_slice(frame: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    """Return bars belonging to the latest session calendar day."""
    as_of_day = pd.Timestamp(frame.iloc[-1][date_column]).normalize()
    dates = pd.to_datetime(frame[date_column])
    return frame.loc[dates.dt.normalize() == as_of_day].reset_index(drop=True)


def assess_orb_setup(
    frame: pd.DataFrame,
    *,
    opening: OpeningRangeLevels,
    config: OpeningRangeBreakoutConfig,
    structure: MarketStructureResult,
    trend_bullish: bool,
    trend_bearish: bool,
    conditions: ConditionEngine,
) -> ORBSetupAssessment:
    """Evaluate buy/sell ORB conditions and filters on the latest bar."""
    session = session_slice(frame, date_column=config.date_column)
    if len(session) <= config.opening_range_bars:
        return ORBSetupAssessment(
            signal=SignalType.HOLD,
            breakout=False,
            relative_volume_ok=False,
            structure_ok=False,
            trend_ok=False,
            momentum_ok=False,
            already_traded=False,
            range_ok=False,
            late_breakout=False,
            gap_blocked=False,
            reasons=["Opening range not yet complete"],
        )

    latest = session.iloc[-1]
    close = float(latest[config.close_column])
    open_ = float(latest[config.open_column])
    rvol_raw = latest[config.volume_column]
    rvol = float(rvol_raw) if pd.notna(rvol_raw) else None
    relative_volume_ok = rvol is not None and rvol > config.relative_volume_threshold

    bars_after_or = len(session) - config.opening_range_bars
    late_breakout = bars_after_or > config.max_breakout_bars_after_or
    range_ok = config.min_range_pct <= opening.range_pct <= config.max_range_pct
    gap_blocked = _gap_exceeds_limit(session, frame, config)

    already_traded = _prior_breakout_today(
        session,
        opening=opening,
        config=config,
    )

    long_break = conditions.compare(
        close,
        ">",
        opening.high,
        left_label="close",
        right_label="ORH",
    ).value
    short_break = conditions.compare(
        close,
        "<",
        opening.low,
        left_label="close",
        right_label="ORL",
    ).value
    breakout = long_break or short_break

    structure_bullish = structure.trend is TrendDirection.BULLISH
    structure_bearish = structure.trend is TrendDirection.BEARISH
    momentum_long = close > open_
    momentum_short = close < open_

    reasons: list[str] = []
    signal = SignalType.HOLD
    direction: TradeDirection | None = None

    if gap_blocked:
        reasons.append(
            f"News/gap filter: open gap exceeds {config.max_gap_pct:.2%}",
        )
    elif not range_ok:
        reasons.append(
            f"OR width {opening.range_pct:.4%} outside "
            f"[{config.min_range_pct:.4%}, {config.max_range_pct:.4%}]",
        )
    elif already_traded:
        reasons.append("Already traded / prior OR breakout today")
    elif late_breakout and breakout:
        reasons.append(
            f"Late breakout after {bars_after_or} bars "
            f"(max {config.max_breakout_bars_after_or})",
        )
    elif long_break:
        structure_ok = structure_bullish
        trend_ok = trend_bullish
        momentum_ok = momentum_long
        if not relative_volume_ok:
            reasons.append(
                f"Low volume: RVOL {rvol if rvol is not None else 'n/a'} "
                f"(need > {config.relative_volume_threshold:g})",
            )
        if not structure_ok:
            reasons.append(f"Structure {structure.trend.value} is not bullish")
        if not trend_ok:
            reasons.append("Trend filter is not bullish")
        if not momentum_ok:
            reasons.append("Momentum filter failed (bearish candle)")
        if relative_volume_ok and structure_ok and trend_ok and momentum_ok:
            signal = SignalType.BUY
            direction = TradeDirection.LONG
            reasons = [
                f"Close {close:.6g} above ORH {opening.high:.6g}",
                f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                f"Market structure {structure.trend.value}",
                "Trend filter bullish",
                "No prior breakout today",
            ]
    elif short_break:
        structure_ok = structure_bearish
        # User SELL conditions: structure bearish; trend filter listed only on BUY.
        # Keep trend optional for shorts: require bearish trend when available.
        trend_ok = trend_bearish or not trend_bullish
        momentum_ok = momentum_short
        if not relative_volume_ok:
            reasons.append(
                f"Low volume: RVOL {rvol if rvol is not None else 'n/a'} "
                f"(need > {config.relative_volume_threshold:g})",
            )
        if not structure_ok:
            reasons.append(f"Structure {structure.trend.value} is not bearish")
        if not momentum_ok:
            reasons.append("Momentum filter failed (bullish candle)")
        if relative_volume_ok and structure_ok and momentum_ok:
            signal = SignalType.SELL
            direction = TradeDirection.SHORT
            reasons = [
                f"Close {close:.6g} below ORL {opening.low:.6g}",
                f"Relative volume {rvol:.3g} > {config.relative_volume_threshold:g}",
                f"Market structure {structure.trend.value}",
                "No prior breakout today",
            ]
    else:
        reasons.append("Price still inside opening range")

    # Recompute flags for response (may be unset on early returns)
    if long_break:
        structure_ok = structure_bullish
        trend_ok = trend_bullish
        momentum_ok = momentum_long
    elif short_break:
        structure_ok = structure_bearish
        trend_ok = trend_bearish or not trend_bullish
        momentum_ok = momentum_short
    else:
        structure_ok = False
        trend_ok = False
        momentum_ok = False

    # Suppress breakout when blocked by session filters even if close crossed.
    if signal is not SignalType.HOLD and (gap_blocked or not range_ok or already_traded or late_breakout):
        signal = SignalType.HOLD
        direction = None

    return ORBSetupAssessment(
        signal=signal,
        direction=direction,
        breakout=breakout,
        relative_volume_ok=relative_volume_ok,
        structure_ok=structure_ok if breakout else structure_bullish or structure_bearish,
        trend_ok=trend_ok if breakout else trend_bullish or trend_bearish,
        momentum_ok=momentum_ok if breakout else False,
        already_traded=already_traded,
        range_ok=range_ok,
        late_breakout=late_breakout,
        gap_blocked=gap_blocked,
        relative_volume=rvol,
        reasons=reasons,
    )


def build_confidence(
    setup: ORBSetupAssessment,
    weights: ORBConfidenceWeights,
) -> ORBConfidenceBreakdown:
    """Award scorecard points for ORB components."""
    opening_range_break = weights.opening_range_break if setup.breakout else 0.0
    volume = weights.volume if setup.relative_volume_ok else 0.0
    trend = weights.trend if setup.trend_ok else 0.0
    structure = weights.structure if setup.structure_ok else 0.0
    momentum = weights.momentum if setup.momentum_ok else 0.0
    raw = opening_range_break + volume + trend + structure + momentum
    normalized = 100.0 * raw / weights.total
    reasons = [
        f"Opening range break: {opening_range_break:g}/{weights.opening_range_break:g}",
        f"Volume: {volume:g}/{weights.volume:g}",
        f"Trend: {trend:g}/{weights.trend:g}",
        f"Structure: {structure:g}/{weights.structure:g}",
        f"Momentum: {momentum:g}/{weights.momentum:g}",
        f"Total: {normalized:.2f}/100",
    ]
    return ORBConfidenceBreakdown(
        opening_range_break=opening_range_break,
        volume=volume,
        trend=trend,
        structure=structure,
        momentum=momentum,
        total=round(normalized, 4),
        reasons=reasons,
    )


def select_orb_stop(
    *,
    direction: TradeDirection,
    entry_price: float,
    opening: OpeningRangeLevels,
    previous_swing: float | None,
    atr_value: float | None,
    atr_multiplier: float,
) -> tuple[ORBStopSource, float]:
    """Stop priority: Opening Range → previous swing → ATR."""
    candidates: list[tuple[ORBStopSource, float]] = []
    if direction is TradeDirection.LONG:
        if opening.low < entry_price:
            candidates.append((ORBStopSource.OPENING_RANGE, opening.low))
        if previous_swing is not None and previous_swing < entry_price:
            candidates.append((ORBStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price - atr_value * atr_multiplier
            if 0 < atr_stop < entry_price:
                candidates.append((ORBStopSource.ATR, atr_stop))
    else:
        if opening.high > entry_price:
            candidates.append((ORBStopSource.OPENING_RANGE, opening.high))
        if previous_swing is not None and previous_swing > entry_price:
            candidates.append((ORBStopSource.PREVIOUS_SWING, previous_swing))
        if atr_value is not None and atr_value > 0:
            atr_stop = entry_price + atr_value * atr_multiplier
            if atr_stop > entry_price:
                candidates.append((ORBStopSource.ATR, atr_stop))

    if not candidates:
        raise StrategyValidationError("Unable to derive a valid ORB stop loss")
    return candidates[0]


def atr_projection_target(
    *,
    direction: TradeDirection,
    entry_price: float,
    atr_value: float | None,
    atr_multiplier: float,
    take_profit_1: float,
) -> float:
    """Target 2 via ATR projection; fallback beyond TP1 when ATR missing."""
    if atr_value is None or atr_value <= 0:
        risk = abs(take_profit_1 - entry_price)
        return entry_price + risk * 1.5 if direction is TradeDirection.LONG else entry_price - risk * 1.5
    if direction is TradeDirection.LONG:
        return entry_price + atr_value * atr_multiplier
    return entry_price - atr_value * atr_multiplier


def _prior_breakout_today(
    session: pd.DataFrame,
    *,
    opening: OpeningRangeLevels,
    config: OpeningRangeBreakoutConfig,
) -> bool:
    """True when a completed OR breakout already occurred before the latest bar."""
    if len(session) <= config.opening_range_bars + 1:
        return False
    body = session.iloc[config.opening_range_bars : -1]
    closes = pd.to_numeric(body[config.close_column], errors="coerce")
    return bool(((closes > opening.high) | (closes < opening.low)).any())


def _gap_exceeds_limit(
    session: pd.DataFrame,
    full_frame: pd.DataFrame,
    config: OpeningRangeBreakoutConfig,
) -> bool:
    """Detect oversized open gap vs the prior session close."""
    session_open = float(session.iloc[0][config.open_column])
    session_day = pd.Timestamp(session.iloc[0][config.date_column]).normalize()
    dates = pd.to_datetime(full_frame[config.date_column])
    prior = full_frame.loc[dates.dt.normalize() < session_day]
    if prior.empty:
        return False
    prior_close = float(prior.iloc[-1][config.close_column])
    if prior_close <= 0:
        return False
    gap = abs(session_open - prior_close) / prior_close
    return gap > config.max_gap_pct
