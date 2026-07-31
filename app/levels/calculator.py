"""Pure, deterministic price-level and pivot calculations from OHLCV."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.levels.exceptions import LevelsValidationError
from app.levels.schemas import (
    CamarillaPivotLevels,
    ClassicPivotLevels,
    LevelKind,
    PeriodRange,
    PriceLevel,
)

REQUIRED_OHLCV_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")


def classic_pivot_levels(high: float, low: float, close: float) -> ClassicPivotLevels:
    """Classic floor-trader pivots from a prior period high/low/close."""
    _validate_hlc(high, low, close)
    pivot = (high + low + close) / 3.0
    return ClassicPivotLevels(
        pivot=pivot,
        resistance_1=(2.0 * pivot) - low,
        support_1=(2.0 * pivot) - high,
        resistance_2=pivot + (high - low),
        support_2=pivot - (high - low),
        resistance_3=high + 2.0 * (pivot - low),
        support_3=low - 2.0 * (high - pivot),
    )


def camarilla_pivot_levels(high: float, low: float, close: float) -> CamarillaPivotLevels:
    """Camarilla pivots from a prior period high/low/close."""
    _validate_hlc(high, low, close)
    span = high - low
    return CamarillaPivotLevels(
        reference_close=close,
        resistance_1=close + span * 1.1 / 12.0,
        resistance_2=close + span * 1.1 / 6.0,
        resistance_3=close + span * 1.1 / 4.0,
        resistance_4=close + span * 1.1 / 2.0,
        support_1=close - span * 1.1 / 12.0,
        support_2=close - span * 1.1 / 6.0,
        support_3=close - span * 1.1 / 4.0,
        support_4=close - span * 1.1 / 2.0,
    )


def aggregate_period(frame: pd.DataFrame) -> PeriodRange:
    """Aggregate OHLC bars into a single period high/low/close range."""
    if frame.empty:
        raise LevelsValidationError("Cannot aggregate an empty period")
    ordered = frame.sort_values("date")
    return PeriodRange(
        high=float(ordered["high"].max()),
        low=float(ordered["low"].min()),
        close=float(ordered.iloc[-1]["close"]),
        start=pd.Timestamp(ordered.iloc[0]["date"]).to_pydatetime(),
        end=pd.Timestamp(ordered.iloc[-1]["date"]).to_pydatetime(),
    )


def previous_day_range(frame: pd.DataFrame, as_of: pd.Timestamp) -> PeriodRange:
    """Return the completed calendar day before ``as_of``'s date."""
    days = _daily_groups(frame)
    as_of_day = pd.Timestamp(as_of).normalize()
    prior_days = [day for day in days if day < as_of_day]
    if not prior_days:
        raise LevelsValidationError("Need at least one completed prior day")
    return aggregate_period(days[prior_days[-1]])


def previous_week_range(frame: pd.DataFrame, as_of: pd.Timestamp) -> PeriodRange:
    """Return the completed ISO week before ``as_of``'s ISO week."""
    weeks = _iso_week_groups(frame)
    as_of_week = _iso_week_key(pd.Timestamp(as_of))
    prior_weeks = [week for week in weeks if week < as_of_week]
    if not prior_weeks:
        raise LevelsValidationError("Need at least one completed prior ISO week")
    return aggregate_period(weeks[prior_weeks[-1]])


def previous_month_range(frame: pd.DataFrame, as_of: pd.Timestamp) -> PeriodRange:
    """Return the completed calendar month before ``as_of``'s month."""
    months = _month_groups(frame)
    as_of_month = _month_key(pd.Timestamp(as_of))
    prior_months = [month for month in months if month < as_of_month]
    if not prior_months:
        raise LevelsValidationError("Need at least one completed prior calendar month")
    return aggregate_period(months[prior_months[-1]])


def opening_range(
    frame: pd.DataFrame,
    as_of: pd.Timestamp,
    *,
    opening_range_bars: int,
) -> tuple[float, float]:
    """High/low of the first ``opening_range_bars`` bars of the current session day."""
    if opening_range_bars < 1:
        raise LevelsValidationError("opening_range_bars must be >= 1")

    as_of_day = pd.Timestamp(as_of).normalize()
    session = frame[frame["date"].dt.normalize() == as_of_day].sort_values("date")
    if session.empty:
        raise LevelsValidationError("No bars found for the current session day")
    if len(session) < opening_range_bars:
        raise LevelsValidationError(
            f"Need at least {opening_range_bars} bars in the current session for opening range, "
            f"got {len(session)}",
        )

    window = session.iloc[:opening_range_bars]
    return float(window["high"].max()), float(window["low"].min())


def build_support_resistance(
    levels: list[PriceLevel],
    *,
    reference_price: float,
) -> tuple[list[PriceLevel], list[PriceLevel]]:
    """Split named levels into supports (below) and resistances (above).

    Supports are nearest-first (descending price).
    Resistances are nearest-first (ascending price).
    Levels equal to the reference price are excluded.
    """
    supports = sorted(
        [level for level in levels if level.price < reference_price],
        key=lambda level: level.price,
        reverse=True,
    )
    resistances = sorted(
        [level for level in levels if level.price > reference_price],
        key=lambda level: level.price,
    )
    return supports, resistances


def collect_named_levels(
    *,
    previous_day_high: float,
    previous_day_low: float,
    previous_week_high: float,
    previous_week_low: float,
    previous_month_high: float,
    previous_month_low: float,
    opening_range_high: float,
    opening_range_low: float,
    daily_pivot: float,
    weekly_pivot: float,
    classic: ClassicPivotLevels,
    camarilla: CamarillaPivotLevels,
) -> list[PriceLevel]:
    """Flatten all computed levels into reusable ``PriceLevel`` objects."""
    return [
        PriceLevel(kind=LevelKind.PREVIOUS_DAY_HIGH, price=previous_day_high, label="Previous Day High"),
        PriceLevel(kind=LevelKind.PREVIOUS_DAY_LOW, price=previous_day_low, label="Previous Day Low"),
        PriceLevel(kind=LevelKind.PREVIOUS_WEEK_HIGH, price=previous_week_high, label="Previous Week High"),
        PriceLevel(kind=LevelKind.PREVIOUS_WEEK_LOW, price=previous_week_low, label="Previous Week Low"),
        PriceLevel(kind=LevelKind.PREVIOUS_MONTH_HIGH, price=previous_month_high, label="Previous Month High"),
        PriceLevel(kind=LevelKind.PREVIOUS_MONTH_LOW, price=previous_month_low, label="Previous Month Low"),
        PriceLevel(kind=LevelKind.OPENING_RANGE_HIGH, price=opening_range_high, label="Opening Range High"),
        PriceLevel(kind=LevelKind.OPENING_RANGE_LOW, price=opening_range_low, label="Opening Range Low"),
        PriceLevel(kind=LevelKind.DAILY_PIVOT, price=daily_pivot, label="Daily Pivot"),
        PriceLevel(kind=LevelKind.WEEKLY_PIVOT, price=weekly_pivot, label="Weekly Pivot"),
        PriceLevel(kind=LevelKind.CLASSIC_RESISTANCE_1, price=classic.resistance_1, label="Classic R1"),
        PriceLevel(kind=LevelKind.CLASSIC_RESISTANCE_2, price=classic.resistance_2, label="Classic R2"),
        PriceLevel(kind=LevelKind.CLASSIC_RESISTANCE_3, price=classic.resistance_3, label="Classic R3"),
        PriceLevel(kind=LevelKind.CLASSIC_SUPPORT_1, price=classic.support_1, label="Classic S1"),
        PriceLevel(kind=LevelKind.CLASSIC_SUPPORT_2, price=classic.support_2, label="Classic S2"),
        PriceLevel(kind=LevelKind.CLASSIC_SUPPORT_3, price=classic.support_3, label="Classic S3"),
        PriceLevel(kind=LevelKind.CAMARILLA_RESISTANCE_1, price=camarilla.resistance_1, label="Camarilla R1"),
        PriceLevel(kind=LevelKind.CAMARILLA_RESISTANCE_2, price=camarilla.resistance_2, label="Camarilla R2"),
        PriceLevel(kind=LevelKind.CAMARILLA_RESISTANCE_3, price=camarilla.resistance_3, label="Camarilla R3"),
        PriceLevel(kind=LevelKind.CAMARILLA_RESISTANCE_4, price=camarilla.resistance_4, label="Camarilla R4"),
        PriceLevel(kind=LevelKind.CAMARILLA_SUPPORT_1, price=camarilla.support_1, label="Camarilla S1"),
        PriceLevel(kind=LevelKind.CAMARILLA_SUPPORT_2, price=camarilla.support_2, label="Camarilla S2"),
        PriceLevel(kind=LevelKind.CAMARILLA_SUPPORT_3, price=camarilla.support_3, label="Camarilla S3"),
        PriceLevel(kind=LevelKind.CAMARILLA_SUPPORT_4, price=camarilla.support_4, label="Camarilla S4"),
    ]


def normalize_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize an OHLCV frame for level computation."""
    if not isinstance(ohlcv, pd.DataFrame):
        raise TypeError(f"Expected pandas DataFrame, got {type(ohlcv).__name__}")
    if ohlcv.empty:
        raise LevelsValidationError("OHLCV DataFrame must not be empty")

    missing = [column for column in REQUIRED_OHLCV_COLUMNS if column not in ohlcv.columns]
    if missing:
        raise LevelsValidationError(f"Missing required OHLCV columns: {', '.join(missing)}")

    frame = ohlcv.loc[:, list(REQUIRED_OHLCV_COLUMNS)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).astype("int64")

    if frame[["open", "high", "low", "close"]].isna().any().any():
        raise LevelsValidationError("OHLC columns must be numeric and non-null")

    invalid_range = (
        (frame["high"] < frame["low"])
        | (frame["high"] < frame["open"])
        | (frame["high"] < frame["close"])
        | (frame["low"] > frame["open"])
        | (frame["low"] > frame["close"])
    )
    if bool(invalid_range.any()):
        raise LevelsValidationError(
            "Invalid OHLC relationship: high must be >= open/close/low and low <= open/close",
        )

    return (
        frame.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def _validate_hlc(high: float, low: float, close: float) -> None:
    if high < low:
        raise LevelsValidationError("Period high must be >= period low")
    if close <= 0 or high <= 0 or low <= 0:
        raise LevelsValidationError("Period high/low/close must be positive")


def _daily_groups(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    grouped: dict[pd.Timestamp, pd.DataFrame] = {}
    for day, group in frame.groupby(frame["date"].dt.normalize(), sort=True):
        grouped[pd.Timestamp(day)] = group
    return grouped


def _iso_week_key(ts: pd.Timestamp) -> tuple[int, int]:
    iso = ts.isocalendar()
    return int(iso.year), int(iso.week)


def _iso_week_groups(frame: pd.DataFrame) -> dict[tuple[int, int], pd.DataFrame]:
    keys = frame["date"].map(_iso_week_key)
    grouped: dict[tuple[int, int], pd.DataFrame] = {}
    for key, group in frame.groupby(keys, sort=True):
        grouped[key] = group
    return grouped


def _month_key(ts: pd.Timestamp) -> tuple[int, int]:
    return int(ts.year), int(ts.month)


def _month_groups(frame: pd.DataFrame) -> dict[tuple[int, int], pd.DataFrame]:
    keys = frame["date"].map(_month_key)
    grouped: dict[tuple[int, int], pd.DataFrame] = {}
    for key, group in frame.groupby(keys, sort=True):
        grouped[key] = group
    return grouped


def to_datetime(value: datetime | pd.Timestamp) -> datetime:
    return pd.Timestamp(value).to_pydatetime()
