"""Module-level confluence scorers.

Each scorer returns a raw score in ``[-1, 1]`` plus a human-readable reason.
Positive = bullish bias, negative = bearish bias, zero = neutral.
"""

from __future__ import annotations

import pandas as pd

from app.confluence.exceptions import ConfluenceValidationError
from app.confluence.schemas import ConfluenceConfig, SignalContribution
from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import (
    MarketStructureResult,
    StructureEventType,
    TrendDirection,
)


def score_ema(features: pd.DataFrame, config: ConfluenceConfig) -> tuple[float, str]:
    """Score EMA stack / price vs EMA."""
    close = _latest(features, config.close_column, required=False)
    fast = _latest(features, config.ema_fast_column)
    slow = _latest(features, config.ema_slow_column)
    trend = _latest(features, config.ema_trend_column, required=False)

    if close is None:
        # Fall back to EMA-only alignment when close is absent from feature frames.
        if trend is None:
            if fast > slow:
                return 0.6, f"{config.ema_fast_column} ({fast:.6g}) > {config.ema_slow_column} ({slow:.6g})"
            if fast < slow:
                return -0.6, f"{config.ema_fast_column} ({fast:.6g}) < {config.ema_slow_column} ({slow:.6g})"
            return 0.0, "Fast/slow EMAs are equal"

        if fast > slow > trend:
            return 0.9, f"Bullish EMA stack {config.ema_fast_column}>{config.ema_slow_column}>{config.ema_trend_column}"
        if fast < slow < trend:
            return -0.9, f"Bearish EMA stack {config.ema_fast_column}<{config.ema_slow_column}<{config.ema_trend_column}"
        if fast > slow:
            return 0.4, f"Mixed EMA: fast>slow but not fully stacked"
        if fast < slow:
            return -0.4, f"Mixed EMA: fast<slow but not fully stacked"
        return 0.0, "EMA stack neutral"

    bullish_cross = close > slow and fast >= slow
    bearish_cross = close < slow and fast <= slow
    if trend is not None and fast > slow > trend and close > slow:
        return 1.0, f"Price {close:.6g} above bullish EMA stack"
    if trend is not None and fast < slow < trend and close < slow:
        return -1.0, f"Price {close:.6g} below bearish EMA stack"
    if bullish_cross:
        return 0.55, f"Price {close:.6g} above {config.ema_slow_column} ({slow:.6g})"
    if bearish_cross:
        return -0.55, f"Price {close:.6g} below {config.ema_slow_column} ({slow:.6g})"
    return 0.0, f"Price {close:.6g} mixed vs EMAs (fast={fast:.6g}, slow={slow:.6g})"


def score_rsi(features: pd.DataFrame, config: ConfluenceConfig) -> tuple[float, str]:
    rsi = _latest(features, config.rsi_column)
    if rsi <= config.rsi_oversold:
        # Oversold can be bullish mean-reversion confluence.
        strength = min(1.0, (config.rsi_oversold - rsi) / max(config.rsi_oversold, 1.0) + 0.5)
        return strength, f"RSI oversold at {rsi:.2f} (<= {config.rsi_oversold:g})"
    if rsi >= config.rsi_overbought:
        strength = min(1.0, (rsi - config.rsi_overbought) / max(100.0 - config.rsi_overbought, 1.0) + 0.5)
        return -strength, f"RSI overbought at {rsi:.2f} (>= {config.rsi_overbought:g})"
    # Momentum tilt inside neutral band.
    mid = (config.rsi_oversold + config.rsi_overbought) / 2.0
    tilt = (rsi - mid) / max((config.rsi_overbought - config.rsi_oversold) / 2.0, 1.0)
    tilt = max(-0.35, min(0.35, tilt))
    return tilt, f"RSI neutral-momentum at {rsi:.2f}"


def score_volume(features: pd.DataFrame, config: ConfluenceConfig) -> tuple[float, str]:
    rel = _latest(features, config.volume_column)
    close = _latest(features, config.close_column, required=False)
    prev_close = _previous(features, config.close_column) if close is not None else None

    if rel >= config.volume_high:
        if prev_close is not None and close is not None:
            if close > prev_close:
                return 0.85, f"High relative volume {rel:.2f} on up bar"
            if close < prev_close:
                return -0.85, f"High relative volume {rel:.2f} on down bar"
        return 0.4, f"Elevated relative volume {rel:.2f} without price direction"
    if rel <= config.volume_low:
        return 0.0, f"Low relative volume {rel:.2f} (weak participation)"
    return 0.15 if (prev_close is None or close is None or close >= prev_close) else -0.15, (
        f"Average relative volume {rel:.2f}"
    )


def score_structure(structure: MarketStructureResult | None) -> tuple[float, str]:
    if structure is None:
        return 0.0, "Market structure unavailable"
    score = 0.0
    reasons: list[str] = [f"Trend={structure.trend.value}"]
    if structure.trend is TrendDirection.BULLISH:
        score += 0.7
    elif structure.trend is TrendDirection.BEARISH:
        score -= 0.7
    else:
        reasons.append("sideways structure")

    if structure.events:
        latest = structure.events[-1]
        if latest.event_type is StructureEventType.BREAK_OF_STRUCTURE:
            delta = 0.3 if latest.direction is TrendDirection.BULLISH else -0.3
            score += delta
            reasons.append(f"latest BOS {latest.direction.value}")
        elif latest.event_type is StructureEventType.CHANGE_OF_CHARACTER:
            delta = 0.2 if latest.direction is TrendDirection.BULLISH else -0.2
            score += delta
            reasons.append(f"latest ChoCH {latest.direction.value}")

    return _clamp(score), "; ".join(reasons)


def score_atr(features: pd.DataFrame, config: ConfluenceConfig) -> tuple[float, str]:
    """ATR as volatility regime + directional follow-through proxy."""
    column = config.atr_column
    if column not in features.columns:
        raise ConfluenceValidationError(f"Missing ATR column '{column}'")
    series = pd.to_numeric(features[column], errors="coerce").dropna()
    if series.empty:
        raise ConfluenceValidationError(f"ATR column '{column}' has no values")

    latest = float(series.iloc[-1])
    lookback = min(config.atr_lookback, len(series))
    baseline = float(series.iloc[-lookback:].mean())
    expanding = latest >= baseline * config.atr_expand_ratio

    close = _latest(features, config.close_column, required=False)
    prev_close = _previous(features, config.close_column) if close is not None else None
    if not expanding:
        return 0.0, f"ATR contracting/stable ({latest:.6g} vs mean {baseline:.6g})"

    if prev_close is not None and close is not None:
        if close > prev_close:
            return 0.55, f"Expanding ATR {latest:.6g} with rising price"
        if close < prev_close:
            return -0.55, f"Expanding ATR {latest:.6g} with falling price"
    return 0.2, f"Expanding ATR {latest:.6g} without clear price direction"


def score_levels(
    levels: LevelsSnapshot | None,
    *,
    price: float | None,
    config: ConfluenceConfig,
) -> tuple[float, str]:
    if levels is None:
        return 0.0, "Levels unavailable"
    reference = price if price is not None else levels.reference_price
    proximity = reference * config.levels_proximity_pct

    near_support = [
        level for level in levels.supports if abs(level.price - reference) <= proximity
    ]
    near_resistance = [
        level for level in levels.resistances if abs(level.price - reference) <= proximity
    ]

    if near_support and not near_resistance:
        level = near_support[0]
        return 0.8, f"Price near support {level.label} ({level.price:.6g})"
    if near_resistance and not near_support:
        level = near_resistance[0]
        return -0.8, f"Price near resistance {level.label} ({level.price:.6g})"
    if near_support and near_resistance:
        return 0.0, "Price compressed between nearby support and resistance"

    # Bias from which side of daily pivot price sits.
    if reference > levels.daily_pivot:
        return 0.35, f"Price {reference:.6g} above daily pivot {levels.daily_pivot:.6g}"
    if reference < levels.daily_pivot:
        return -0.35, f"Price {reference:.6g} below daily pivot {levels.daily_pivot:.6g}"
    return 0.0, f"Price at daily pivot {levels.daily_pivot:.6g}"


def score_trend(features: pd.DataFrame, config: ConfluenceConfig) -> tuple[float, str]:
    """Trend module from ADX strength + EMA directional alignment."""
    adx = _latest(features, config.adx_column, required=False)
    fast = _latest(features, config.ema_fast_column, required=False)
    slow = _latest(features, config.ema_slow_column, required=False)

    direction = 0.0
    parts: list[str] = []
    if fast is not None and slow is not None:
        if fast > slow:
            direction = 1.0
            parts.append("EMA fast>slow")
        elif fast < slow:
            direction = -1.0
            parts.append("EMA fast<slow")
        else:
            parts.append("EMA flat")

    strength = 0.5
    if adx is not None:
        if adx >= config.adx_trend_threshold:
            strength = min(1.0, adx / 50.0)
            parts.append(f"ADX {adx:.2f} trending")
        else:
            strength = 0.25
            parts.append(f"ADX {adx:.2f} weak")
    else:
        parts.append("ADX unavailable")

    score = direction * strength
    return _clamp(score), "; ".join(parts) if parts else "Trend neutral"


def score_signal_list(signals: list[SignalContribution] | None, *, label: str) -> tuple[float, str]:
    if not signals:
        return 0.0, f"No {label} provided"
    average = sum(signal.score for signal in signals) / len(signals)
    details = ", ".join(f"{signal.name}={signal.score:+.2f}" for signal in signals[:5])
    more = "" if len(signals) <= 5 else f" (+{len(signals) - 5} more)"
    return _clamp(average), f"{label} avg {average:+.2f} [{details}{more}]"


def _latest(frame: pd.DataFrame, column: str, *, required: bool = True) -> float | None:
    if column not in frame.columns:
        if required:
            raise ConfluenceValidationError(f"Missing required column '{column}'")
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        if required:
            raise ConfluenceValidationError(f"Column '{column}' has no usable values")
        return None
    return float(series.iloc[-1])


def _previous(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if len(series) < 2:
        return None
    return float(series.iloc[-2])


def _clamp(value: float) -> float:
    return float(max(-1.0, min(1.0, value)))
