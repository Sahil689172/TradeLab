"""Unit tests for deterministic market structure detection."""

from __future__ import annotations

import pandas as pd
import pytest

from app.market_structure import (
    MarketStructureService,
    MarketStructureValidationError,
    StructureEventType,
    StructureLabel,
    SwingType,
    TrendDirection,
)
from app.market_structure.detector import (
    alternate_swings,
    classify_trend,
    detect_raw_swings,
    label_swings,
)


def make_ohlcv(
    highs: list[float],
    lows: list[float],
    closes: list[float] | None = None,
) -> pd.DataFrame:
    """Build a valid OHLCV frame from explicit high/low/(close) series.

    High/low are preserved for swing detection. Open/close are clamped into
    each bar's range so OHLC relationships always hold.
    """
    n = len(highs)
    if len(lows) != n:
        raise ValueError("highs and lows must have equal length")
    if any(h < l for h, l in zip(highs, lows, strict=True)):
        raise ValueError("each high must be >= corresponding low")

    if closes is None:
        closes = [(high + low) / 2.0 for high, low in zip(highs, lows, strict=True)]
    elif len(closes) != n:
        raise ValueError("closes must match highs/lows length")

    # Keep swing highs/lows intact; force open/close inside [low, high].
    closes = [
        min(high, max(low, close))
        for high, low, close in zip(highs, lows, closes, strict=True)
    ]
    opens: list[float] = []
    for index, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True)):
        if index == 0:
            opens.append(close)
        else:
            opens.append(min(high, max(low, closes[index - 1])))

    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1_000] * n,
        },
    )


def uptrend_frame() -> pd.DataFrame:
    """Zigzag with SL → SH → HL → HH (swing_length=1)."""
    # indexes:           0    1    2    3    4    5    6    7    8    9
    highs = [10.0, 11.0, 12.0, 15.0, 14.0, 13.0, 16.0, 18.0, 17.0, 19.5]
    lows = [8.0, 7.0, 9.0, 12.0, 11.0, 10.0, 13.0, 15.0, 14.0, 16.0]
    closes = [9.0, 8.0, 11.0, 14.0, 12.0, 11.0, 15.0, 17.0, 16.0, 19.0]
    return make_ohlcv(highs, lows, closes)


def downtrend_frame() -> pd.DataFrame:
    """Zigzag with SH → SL → LH → LL (swing_length=1)."""
    # indexes:            0     1     2     3     4     5     6     7     8     9    10
    highs = [16.0, 20.0, 18.0, 17.0, 19.0, 17.0, 15.0, 16.0, 14.0, 13.0, 12.0]
    lows = [14.0, 15.0, 13.0, 11.0, 14.0, 12.0, 10.0, 12.0, 11.0, 9.0, 8.0]
    closes = [15.0, 19.0, 14.0, 12.0, 18.0, 13.0, 11.0, 15.0, 12.0, 10.0, 9.0]
    return make_ohlcv(highs, lows, closes)


# ---------------------------------------------------------------------------
# Validation / service contract
# ---------------------------------------------------------------------------


def test_service_requires_ohlcv_columns() -> None:
    service = MarketStructureService(swing_length=1)
    frame = uptrend_frame().drop(columns=["volume"])

    with pytest.raises(MarketStructureValidationError, match="Missing required"):
        service.analyze(frame)


def test_service_rejects_short_history() -> None:
    service = MarketStructureService(swing_length=2)
    frame = uptrend_frame().iloc[:4]

    with pytest.raises(MarketStructureValidationError, match="Need at least"):
        service.analyze(frame)


def test_service_rejects_invalid_ohlc_relationship() -> None:
    service = MarketStructureService(swing_length=1)
    frame = uptrend_frame()
    frame.loc[0, "high"] = 1.0
    frame.loc[0, "low"] = 5.0

    with pytest.raises(MarketStructureValidationError, match="Invalid OHLC"):
        service.analyze(frame)


def test_analyze_is_deterministic() -> None:
    service = MarketStructureService(swing_length=1)
    frame = uptrend_frame()

    first = service.analyze(frame, symbol="RELIANCE")
    second = service.analyze(frame.copy(), symbol="reliance")

    assert first.model_dump() == second.model_dump()
    assert first.symbol == "RELIANCE"


# ---------------------------------------------------------------------------
# Swing detection
# ---------------------------------------------------------------------------


def test_detect_swing_high_and_swing_low() -> None:
    frame = uptrend_frame()
    raw = detect_raw_swings(
        frame["high"],
        frame["low"],
        frame["date"],
        swing_length=1,
    )
    swings = label_swings(alternate_swings(raw))

    assert any(s.swing_type is SwingType.SWING_LOW and s.index == 1 for s in swings)
    assert any(s.swing_type is SwingType.SWING_HIGH and s.index == 3 for s in swings)
    assert any(s.swing_type is SwingType.SWING_LOW and s.index == 5 for s in swings)
    assert any(s.swing_type is SwingType.SWING_HIGH and s.index == 7 for s in swings)


def test_structure_labels_higher_high_and_higher_low() -> None:
    frame = uptrend_frame()
    raw = detect_raw_swings(
        frame["high"],
        frame["low"],
        frame["date"],
        swing_length=1,
    )
    swings = label_swings(alternate_swings(raw))

    lows = [s for s in swings if s.swing_type is SwingType.SWING_LOW]
    highs = [s for s in swings if s.swing_type is SwingType.SWING_HIGH]

    assert lows[0].structure_label is None
    assert highs[0].structure_label is None
    assert lows[1].structure_label is StructureLabel.HIGHER_LOW
    assert highs[1].structure_label is StructureLabel.HIGHER_HIGH


def test_uptrend_classifies_as_bullish() -> None:
    service = MarketStructureService(swing_length=1)
    result = service.analyze(uptrend_frame())

    assert result.trend is TrendDirection.BULLISH
    assert result.last_swing_high is not None
    assert result.last_swing_low is not None
    assert result.last_swing_high.structure_label is StructureLabel.HIGHER_HIGH
    assert result.last_swing_low.structure_label is StructureLabel.HIGHER_LOW


def test_downtrend_classifies_as_bearish() -> None:
    service = MarketStructureService(swing_length=1)
    result = service.analyze(downtrend_frame())

    assert result.trend is TrendDirection.BEARISH
    labels = {s.structure_label for s in result.swings if s.structure_label is not None}
    assert StructureLabel.LOWER_HIGH in labels
    assert StructureLabel.LOWER_LOW in labels


def test_range_classifies_as_sideways() -> None:
    # Oscillating equal-ish range without progressive HH/HL or LH/LL pair.
    highs = [12.0, 15.0, 14.0, 13.0, 15.0, 14.0, 13.0, 15.0, 14.0]
    lows = [10.0, 11.0, 10.0, 9.0, 11.0, 10.0, 9.0, 11.0, 10.0]
    closes = [11.0, 14.0, 12.0, 10.0, 14.0, 12.0, 10.0, 14.0, 12.0]
    service = MarketStructureService(swing_length=1)
    result = service.analyze(make_ohlcv(highs, lows, closes))

    assert result.trend is TrendDirection.SIDEWAYS


def test_alternate_swings_keeps_extreme_of_duplicates() -> None:
    frame = make_ohlcv(
        highs=[10, 12, 11, 13, 12, 11, 10],
        lows=[8, 9, 8, 10, 9, 8, 7],
        closes=[9, 11, 10, 12, 11, 9, 8],
    )
    raw = detect_raw_swings(
        frame["high"],
        frame["low"],
        frame["date"],
        swing_length=1,
    )
    # Force two consecutive highs into alternation input.
    consecutive_highs = [s for s in raw if s.swing_type is SwingType.SWING_HIGH][:2]
    if len(consecutive_highs) == 2:
        alternating = alternate_swings(consecutive_highs)
        assert len(alternating) == 1
        assert alternating[0].price == max(s.price for s in consecutive_highs)


# ---------------------------------------------------------------------------
# BOS / ChoCH
# ---------------------------------------------------------------------------


def test_bullish_break_of_structure() -> None:
    """Close above prior swing high during bullish structure → BOS."""
    service = MarketStructureService(swing_length=1)
    result = service.analyze(uptrend_frame())

    bos = [
        event
        for event in result.events
        if event.event_type is StructureEventType.BREAK_OF_STRUCTURE
        and event.direction is TrendDirection.BULLISH
    ]
    assert bos, "expected at least one bullish BOS"
    assert bos[-1].confirmation_price > bos[-1].broken_level


def test_bearish_change_of_character() -> None:
    """In a bullish structure, close below last swing low → bearish ChoCH."""
    highs = [10.0, 11.0, 12.0, 15.0, 14.0, 13.0, 16.0, 18.0, 17.0, 12.0, 11.0]
    lows = [8.0, 7.0, 9.0, 12.0, 11.0, 10.0, 13.0, 15.0, 14.0, 9.0, 8.0]
    closes = [9.0, 8.0, 11.0, 14.0, 12.0, 11.0, 15.0, 17.0, 16.0, 9.5, 9.0]
    service = MarketStructureService(swing_length=1)
    result = service.analyze(make_ohlcv(highs, lows, closes))

    choch = [
        event
        for event in result.events
        if event.event_type is StructureEventType.CHANGE_OF_CHARACTER
        and event.direction is TrendDirection.BEARISH
    ]
    assert choch, "expected bearish ChoCH after breaking last higher low"
    assert choch[0].confirmation_price < choch[0].broken_level


def test_classify_trend_requires_both_legs() -> None:
    assert classify_trend([]) is TrendDirection.SIDEWAYS


def test_result_exposes_reusable_objects() -> None:
    result = MarketStructureService(swing_length=1).analyze(
        uptrend_frame(),
        symbol="RELIANCE.NS",
    )

    assert result.symbol == "RELIANCE.NS"
    assert result.swing_length == 1
    assert result.bar_count == 10
    assert isinstance(result.swings, list)
    assert isinstance(result.events, list)
    assert result.last_swing_high is not None
    assert result.last_swing_low is not None
