"""Deterministic stop, target, and position-risk calculators."""

from __future__ import annotations

import math

import pandas as pd

from app.market_structure.schemas import (
    MarketStructureResult,
    StructureLabel,
    SwingPoint,
    SwingType,
    TrendDirection,
)
from app.risk_engine.exceptions import RiskValidationError
from app.risk_engine.schemas import (
    PositionRisk,
    RiskConfig,
    StopLevel,
    StopMethod,
    TradeDirection,
)


def atr_stop(
    entry_price: float,
    direction: TradeDirection,
    features: pd.DataFrame,
    config: RiskConfig,
) -> StopLevel:
    """Stop at entry ± ATR * multiplier."""
    atr_value = _latest_atr(features, config.atr_column)
    distance = atr_value * config.atr_multiplier
    price = _price_stop(entry_price, direction, distance)
    return StopLevel(
        method=StopMethod.ATR,
        price=price,
        reason=(
            f"ATR stop using {config.atr_column}={atr_value:.6g} "
            f"x {config.atr_multiplier:g} -> {price:.6g}"
        ),
    )


def percentage_stop(
    entry_price: float,
    direction: TradeDirection,
    config: RiskConfig,
) -> StopLevel:
    """Stop at a fixed fraction of entry price."""
    distance = entry_price * config.percentage_stop
    price = _price_stop(entry_price, direction, distance)
    return StopLevel(
        method=StopMethod.PERCENTAGE,
        price=price,
        reason=(
            f"Percentage stop {config.percentage_stop:.2%} of entry "
            f"{entry_price:.6g} -> {price:.6g}"
        ),
    )


def swing_stop(
    entry_price: float,
    direction: TradeDirection,
    structure: MarketStructureResult,
    config: RiskConfig,
) -> StopLevel:
    """Stop beyond the most recent opposing swing point."""
    swing = _opposing_swing(structure, direction)
    if swing is None:
        raise RiskValidationError("Swing stop requires a confirmed opposing swing")

    price = _buffered_structure_price(swing.price, direction, config.swing_buffer)
    if direction is TradeDirection.LONG and price >= entry_price:
        raise RiskValidationError(
            f"Swing stop {price:.6g} is not below long entry {entry_price:.6g}",
        )
    if direction is TradeDirection.SHORT and price <= entry_price:
        raise RiskValidationError(
            f"Swing stop {price:.6g} is not above short entry {entry_price:.6g}",
        )

    return StopLevel(
        method=StopMethod.SWING,
        price=price,
        reason=(
            f"Swing stop beyond {swing.swing_type.value} at {swing.price:.6g} "
            f"(buffer={config.swing_buffer:g}) -> {price:.6g}"
        ),
    )


def structure_stop(
    entry_price: float,
    direction: TradeDirection,
    structure: MarketStructureResult,
    config: RiskConfig,
) -> StopLevel:
    """Stop beyond the structure-invalidating swing for the trade direction."""
    swing = _structure_invalidation_swing(structure, direction)
    if swing is None:
        raise RiskValidationError("Structure stop requires an invalidation swing")

    price = _buffered_structure_price(swing.price, direction, config.swing_buffer)
    if direction is TradeDirection.LONG and price >= entry_price:
        raise RiskValidationError(
            f"Structure stop {price:.6g} is not below long entry {entry_price:.6g}",
        )
    if direction is TradeDirection.SHORT and price <= entry_price:
        raise RiskValidationError(
            f"Structure stop {price:.6g} is not above short entry {entry_price:.6g}",
        )

    label = swing.structure_label.value if swing.structure_label else "UNLABELED"
    return StopLevel(
        method=StopMethod.STRUCTURE,
        price=price,
        reason=(
            f"Structure stop beyond {swing.swing_type.value}/{label} at "
            f"{swing.price:.6g} (trend={structure.trend.value}) -> {price:.6g}"
        ),
    )


def time_stop(config: RiskConfig) -> StopLevel:
    """Holding-period stop expressed in bars (no price level)."""
    return StopLevel(
        method=StopMethod.TIME,
        bars=config.time_stop_bars,
        reason=f"Time stop after {config.time_stop_bars} bars",
    )


def take_profit_from_risk(
    entry_price: float,
    stop_loss: float,
    direction: TradeDirection,
    risk_reward: float,
) -> tuple[float, float]:
    """Return (take_profit, realized_risk_reward) from stop distance."""
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        raise RiskValidationError("Stop loss must differ from entry price")
    if direction is TradeDirection.LONG:
        take_profit = entry_price + risk * risk_reward
    else:
        take_profit = entry_price - risk * risk_reward
    if take_profit <= 0:
        raise RiskValidationError("Take profit must be positive")
    return take_profit, risk_reward


def position_risk(
    entry_price: float,
    stop_loss: float,
    config: RiskConfig,
) -> PositionRisk:
    """Compute per-unit and optional equity-based position risk."""
    risk_per_unit = abs(entry_price - stop_loss)
    position_size: float | None = None
    capital_at_risk: float | None = None
    if config.account_equity is not None and risk_per_unit > 0:
        capital_at_risk = config.account_equity * config.risk_fraction
        position_size = capital_at_risk / risk_per_unit
    return PositionRisk(
        risk_per_unit=risk_per_unit,
        risk_fraction=config.risk_fraction,
        account_equity=config.account_equity,
        position_size=position_size,
        capital_at_risk=capital_at_risk,
    )


def estimate_confidence(
    *,
    direction: TradeDirection,
    structure: MarketStructureResult,
    stop_method: StopMethod,
    stops: list[StopLevel],
    risk_reward: float,
    requested_risk_reward: float,
) -> float:
    """Deterministic confidence score in [0, 1] from plan quality signals."""
    score = 0.45
    aligned = (
        (direction is TradeDirection.LONG and structure.trend is TrendDirection.BULLISH)
        or (direction is TradeDirection.SHORT and structure.trend is TrendDirection.BEARISH)
    )
    if aligned:
        score += 0.20
    elif structure.trend is TrendDirection.SIDEWAYS:
        score += 0.05
    else:
        score -= 0.15

    methods = {stop.method for stop in stops if stop.price is not None or stop.bars is not None}
    if StopMethod.ATR in methods:
        score += 0.10
    if StopMethod.SWING in methods:
        score += 0.08
    if StopMethod.STRUCTURE in methods:
        score += 0.10
    if stop_method in methods:
        score += 0.05
    if risk_reward + 1e-12 >= requested_risk_reward:
        score += 0.07

    return float(min(1.0, max(0.0, round(score, 4))))


def _latest_atr(features: pd.DataFrame, column: str) -> float:
    if column not in features.columns:
        raise RiskValidationError(f"Feature data missing ATR column '{column}'")
    series = pd.to_numeric(features[column], errors="coerce").dropna()
    if series.empty:
        raise RiskValidationError(f"ATR column '{column}' has no usable values")
    value = float(series.iloc[-1])
    if value <= 0 or math.isnan(value):
        raise RiskValidationError(f"ATR value must be positive, got {value}")
    return value


def _price_stop(entry_price: float, direction: TradeDirection, distance: float) -> float:
    if distance <= 0:
        raise RiskValidationError("Stop distance must be positive")
    if direction is TradeDirection.LONG:
        price = entry_price - distance
    else:
        price = entry_price + distance
    if price <= 0:
        raise RiskValidationError(f"Computed stop price must be positive, got {price}")
    return price


def _buffered_structure_price(
    level: float,
    direction: TradeDirection,
    buffer: float,
) -> float:
    if direction is TradeDirection.LONG:
        return level - buffer
    return level + buffer


def _opposing_swing(
    structure: MarketStructureResult,
    direction: TradeDirection,
) -> SwingPoint | None:
    if direction is TradeDirection.LONG:
        return structure.last_swing_low
    return structure.last_swing_high


def _structure_invalidation_swing(
    structure: MarketStructureResult,
    direction: TradeDirection,
) -> SwingPoint | None:
    """Prefer labeled structure swings; fall back to last opposing swing."""
    if direction is TradeDirection.LONG:
        preferred_labels = {
            StructureLabel.HIGHER_LOW,
            StructureLabel.LOWER_LOW,
            StructureLabel.EQUAL_LOW,
        }
        swing_type = SwingType.SWING_LOW
    else:
        preferred_labels = {
            StructureLabel.LOWER_HIGH,
            StructureLabel.HIGHER_HIGH,
            StructureLabel.EQUAL_HIGH,
        }
        swing_type = SwingType.SWING_HIGH

    for swing in reversed(structure.swings):
        if swing.swing_type is swing_type and swing.structure_label in preferred_labels:
            return swing
    return _opposing_swing(structure, direction)
