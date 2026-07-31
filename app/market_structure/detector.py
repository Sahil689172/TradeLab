"""Deterministic OHLCV-only market structure detection.

Rules are pure functions of price and a fixed ``swing_length``. No indicators,
moving averages, or stochastic components are used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from app.market_structure.schemas import (
    StructureEvent,
    StructureEventType,
    StructureLabel,
    SwingPoint,
    SwingType,
    TrendDirection,
)

REQUIRED_OHLCV_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class _RawSwing:
    index: int
    price: float
    swing_type: SwingType
    timestamp: datetime
    confirmation_index: int


def detect_raw_swings(
    highs: pd.Series,
    lows: pd.Series,
    timestamps: pd.Series,
    *,
    swing_length: int,
) -> list[_RawSwing]:
    """Detect fractal swing highs/lows with ``swing_length`` bars on each side.

    A bar ``i`` is a swing high when ``high[i]`` is strictly greater than every
    high in ``[i - L, i + L] \\ {i}``. Swing lows use the symmetric rule on lows.
    Swings are only emit-able once bar ``i + L`` exists (confirmation).
    """
    if swing_length < 1:
        raise ValueError("swing_length must be >= 1")

    n = len(highs)
    swings: list[_RawSwing] = []
    for i in range(swing_length, n - swing_length):
        left_highs = highs.iloc[i - swing_length : i]
        right_highs = highs.iloc[i + 1 : i + swing_length + 1]
        left_lows = lows.iloc[i - swing_length : i]
        right_lows = lows.iloc[i + 1 : i + swing_length + 1]

        high_i = float(highs.iloc[i])
        low_i = float(lows.iloc[i])
        ts = pd.Timestamp(timestamps.iloc[i]).to_pydatetime()
        confirmation = i + swing_length

        if high_i > float(left_highs.max()) and high_i > float(right_highs.max()):
            swings.append(
                _RawSwing(
                    index=i,
                    price=high_i,
                    swing_type=SwingType.SWING_HIGH,
                    timestamp=ts,
                    confirmation_index=confirmation,
                ),
            )

        if low_i < float(left_lows.min()) and low_i < float(right_lows.min()):
            swings.append(
                _RawSwing(
                    index=i,
                    price=low_i,
                    swing_type=SwingType.SWING_LOW,
                    timestamp=ts,
                    confirmation_index=confirmation,
                ),
            )

    swings.sort(key=lambda swing: (swing.index, 0 if swing.swing_type is SwingType.SWING_HIGH else 1))
    return swings


def alternate_swings(swings: list[_RawSwing]) -> list[_RawSwing]:
    """Collapse consecutive same-type swings into a single extreme.

    Two swing highs in a row keep the higher price (earlier index on ties).
    Two swing lows in a row keep the lower price (earlier index on ties).
    """
    if not swings:
        return []

    alternating: list[_RawSwing] = [swings[0]]
    for swing in swings[1:]:
        previous = alternating[-1]
        if swing.swing_type is previous.swing_type:
            if swing.swing_type is SwingType.SWING_HIGH:
                if swing.price > previous.price or (
                    swing.price == previous.price and swing.index < previous.index
                ):
                    alternating[-1] = swing
            else:
                if swing.price < previous.price or (
                    swing.price == previous.price and swing.index < previous.index
                ):
                    alternating[-1] = swing
        else:
            alternating.append(swing)
    return alternating


def label_swings(swings: list[_RawSwing]) -> list[SwingPoint]:
    """Attach HH/HL/LH/LL (or equal) labels relative to the prior same-type swing."""
    labeled: list[SwingPoint] = []
    last_high: _RawSwing | None = None
    last_low: _RawSwing | None = None

    for swing in swings:
        label: StructureLabel | None = None
        if swing.swing_type is SwingType.SWING_HIGH:
            if last_high is not None:
                if swing.price > last_high.price:
                    label = StructureLabel.HIGHER_HIGH
                elif swing.price < last_high.price:
                    label = StructureLabel.LOWER_HIGH
                else:
                    label = StructureLabel.EQUAL_HIGH
            last_high = swing
        else:
            if last_low is not None:
                if swing.price > last_low.price:
                    label = StructureLabel.HIGHER_LOW
                elif swing.price < last_low.price:
                    label = StructureLabel.LOWER_LOW
                else:
                    label = StructureLabel.EQUAL_LOW
            last_low = swing

        labeled.append(
            SwingPoint(
                index=swing.index,
                timestamp=swing.timestamp,
                price=swing.price,
                swing_type=swing.swing_type,
                structure_label=label,
                confirmation_index=swing.confirmation_index,
            ),
        )
    return labeled


def classify_trend(swings: list[SwingPoint]) -> TrendDirection:
    """Classify trend from the most recent labeled swing high and swing low.

    - BULLISH: last high is HH and last low is HL
    - BEARISH: last high is LH and last low is LL
    - SIDEWAYS: anything else (including insufficient history)
    """
    last_high = _last_of_type(swings, SwingType.SWING_HIGH)
    last_low = _last_of_type(swings, SwingType.SWING_LOW)

    if last_high is None or last_low is None:
        return TrendDirection.SIDEWAYS
    if last_high.structure_label is None or last_low.structure_label is None:
        return TrendDirection.SIDEWAYS

    if (
        last_high.structure_label is StructureLabel.HIGHER_HIGH
        and last_low.structure_label is StructureLabel.HIGHER_LOW
    ):
        return TrendDirection.BULLISH
    if (
        last_high.structure_label is StructureLabel.LOWER_HIGH
        and last_low.structure_label is StructureLabel.LOWER_LOW
    ):
        return TrendDirection.BEARISH
    return TrendDirection.SIDEWAYS


def detect_structure_events(
    frame: pd.DataFrame,
    swings: list[SwingPoint],
) -> list[StructureEvent]:
    """Detect Break of Structure and Change of Character from confirmed swings.

    Confirmation uses the bar **close** strictly beyond the reference swing price.
    Each swing level emits at most one break event.
    """
    if not swings:
        return []

    events: list[StructureEvent] = []
    active_high: SwingPoint | None = None
    active_low: SwingPoint | None = None
    broken_high_indexes: set[int] = set()
    broken_low_indexes: set[int] = set()
    confirmed: list[SwingPoint] = []

    swings_by_confirmation: dict[int, list[SwingPoint]] = {}
    for swing in swings:
        swings_by_confirmation.setdefault(swing.confirmation_index, []).append(swing)

    for i in range(len(frame)):
        if i in swings_by_confirmation:
            for swing in swings_by_confirmation[i]:
                confirmed.append(swing)
                if swing.swing_type is SwingType.SWING_HIGH:
                    active_high = swing
                else:
                    active_low = swing

        if active_high is None and active_low is None:
            continue

        trend = classify_trend(confirmed)
        close = float(frame.iloc[i]["close"])
        timestamp = pd.Timestamp(frame.iloc[i]["date"]).to_pydatetime()

        if (
            active_high is not None
            and active_high.index not in broken_high_indexes
            and i > active_high.confirmation_index
            and close > active_high.price
        ):
            event_type, direction = _classify_break(
                trend=trend,
                broke_high=True,
            )
            events.append(
                StructureEvent(
                    index=i,
                    timestamp=timestamp,
                    event_type=event_type,
                    direction=direction,
                    broken_level=active_high.price,
                    reference_swing_index=active_high.index,
                    confirmation_price=close,
                ),
            )
            broken_high_indexes.add(active_high.index)

        if (
            active_low is not None
            and active_low.index not in broken_low_indexes
            and i > active_low.confirmation_index
            and close < active_low.price
        ):
            event_type, direction = _classify_break(
                trend=trend,
                broke_high=False,
            )
            events.append(
                StructureEvent(
                    index=i,
                    timestamp=timestamp,
                    event_type=event_type,
                    direction=direction,
                    broken_level=active_low.price,
                    reference_swing_index=active_low.index,
                    confirmation_price=close,
                ),
            )
            broken_low_indexes.add(active_low.index)

    return events


def _classify_break(
    *,
    trend: TrendDirection,
    broke_high: bool,
) -> tuple[StructureEventType, TrendDirection]:
    """Map a level break to BOS/ChoCH given the prevailing trend."""
    if broke_high:
        direction = TrendDirection.BULLISH
        if trend is TrendDirection.BEARISH:
            return StructureEventType.CHANGE_OF_CHARACTER, direction
        return StructureEventType.BREAK_OF_STRUCTURE, direction

    direction = TrendDirection.BEARISH
    if trend is TrendDirection.BULLISH:
        return StructureEventType.CHANGE_OF_CHARACTER, direction
    return StructureEventType.BREAK_OF_STRUCTURE, direction


def _last_of_type(swings: list[SwingPoint], swing_type: SwingType) -> SwingPoint | None:
    for swing in reversed(swings):
        if swing.swing_type is swing_type:
            return swing
    return None
