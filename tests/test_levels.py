"""Unit tests for the levels engine."""

from __future__ import annotations

import pandas as pd
import pytest

from app.levels import (
    LevelKind,
    LevelsService,
    LevelsValidationError,
)
from app.levels.calculator import (
    build_support_resistance,
    camarilla_pivot_levels,
    classic_pivot_levels,
    cpr_levels,
    opening_range,
    previous_day_range,
    previous_month_range,
    previous_week_range,
)
from app.levels.schemas import PriceLevel


def make_daily_ohlcv(
    start: str = "2024-01-02",
    periods: int = 70,
    *,
    base: float = 100.0,
) -> pd.DataFrame:
    """Build a long enough daily series for day/week/month level computation."""
    dates = pd.bdate_range(start=start, periods=periods)
    rows: list[dict[str, object]] = []
    price = base
    for offset, date in enumerate(dates):
        # Gentle deterministic drift with a fixed intraday range.
        price = base + offset * 0.25
        high = price + 2.0
        low = price - 2.0
        close = price + 0.5
        open_ = price - 0.5
        rows.append(
            {
                "date": date,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000 + offset,
            },
        )
    return pd.DataFrame(rows)


def make_intraday_session() -> pd.DataFrame:
    """Prior completed days plus a multi-bar current session for opening-range tests."""
    history = make_daily_ohlcv(start="2024-01-02", periods=40, base=90.0)
    history = history[history["date"] < pd.Timestamp("2024-03-01")].copy()
    prior = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-03-01 09:15", "2024-03-01 09:30", "2024-03-01 15:30"]),
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 102.0, 103.0],
            "volume": [100, 110, 120],
        },
    )
    current = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2024-03-04 09:15",
                    "2024-03-04 09:30",
                    "2024-03-04 09:45",
                    "2024-03-04 10:00",
                ],
            ),
            "open": [103.0, 104.0, 105.0, 106.0],
            "high": [104.5, 106.0, 107.0, 108.0],
            "low": [102.5, 103.5, 104.0, 105.0],
            "close": [104.0, 105.0, 106.0, 107.0],
            "volume": [130, 140, 150, 160],
        },
    )
    return pd.concat([history, prior, current], ignore_index=True)


# ---------------------------------------------------------------------------
# Pivot formulas
# ---------------------------------------------------------------------------


def test_classic_pivot_formula() -> None:
    levels = classic_pivot_levels(high=120.0, low=100.0, close=110.0)
    pivot = (120.0 + 100.0 + 110.0) / 3.0

    assert levels.pivot == pytest.approx(pivot)
    assert levels.resistance_1 == pytest.approx((2.0 * pivot) - 100.0)
    assert levels.support_1 == pytest.approx((2.0 * pivot) - 120.0)
    assert levels.resistance_2 == pytest.approx(pivot + 20.0)
    assert levels.support_2 == pytest.approx(pivot - 20.0)
    assert levels.resistance_3 == pytest.approx(120.0 + 2.0 * (pivot - 100.0))
    assert levels.support_3 == pytest.approx(100.0 - 2.0 * (120.0 - pivot))


def test_camarilla_pivot_formula() -> None:
    levels = camarilla_pivot_levels(high=120.0, low=100.0, close=110.0)
    span = 20.0

    assert levels.reference_close == 110.0
    assert levels.resistance_1 == pytest.approx(110.0 + span * 1.1 / 12.0)
    assert levels.resistance_4 == pytest.approx(110.0 + span * 1.1 / 2.0)
    assert levels.support_1 == pytest.approx(110.0 - span * 1.1 / 12.0)
    assert levels.support_4 == pytest.approx(110.0 - span * 1.1 / 2.0)


def test_cpr_levels_formula() -> None:
    levels = cpr_levels(high=120.0, low=100.0, close=110.0)
    pivot = (120.0 + 100.0 + 110.0) / 3.0
    bc = (120.0 + 100.0) / 2.0
    tc = (2.0 * pivot) - bc

    assert levels.pivot == pytest.approx(pivot)
    assert levels.bc == pytest.approx(bc)
    assert levels.tc == pytest.approx(tc)
    assert levels.lower == pytest.approx(min(bc, tc))
    assert levels.upper == pytest.approx(max(bc, tc))
    assert levels.width == pytest.approx(abs(tc - bc))
    assert levels.width_pct == pytest.approx(abs(tc - bc) / pivot)


# ---------------------------------------------------------------------------
# Period levels
# ---------------------------------------------------------------------------


def test_previous_day_week_month_ranges() -> None:
    frame = make_daily_ohlcv(periods=70)
    as_of = pd.Timestamp(frame.iloc[-1]["date"])

    day = previous_day_range(frame, as_of)
    week = previous_week_range(frame, as_of)
    month = previous_month_range(frame, as_of)

    assert day.high >= day.low
    assert week.high >= week.low
    assert month.high >= month.low
    assert pd.Timestamp(day.end).normalize() < as_of.normalize()
    assert _iso_week(pd.Timestamp(week.end)) < _iso_week(as_of)
    assert (pd.Timestamp(month.end).year, pd.Timestamp(month.end).month) < (
        as_of.year,
        as_of.month,
    )


def test_opening_range_uses_first_n_bars_of_session() -> None:
    frame = make_intraday_session()
    as_of = pd.Timestamp("2024-03-04 10:00")
    high, low = opening_range(frame, as_of, opening_range_bars=2)

    assert high == pytest.approx(106.0)
    assert low == pytest.approx(102.5)


# ---------------------------------------------------------------------------
# Service snapshot
# ---------------------------------------------------------------------------


def test_levels_service_computes_all_requested_fields() -> None:
    service = LevelsService(opening_range_bars=1)
    snapshot = service.compute(make_daily_ohlcv(), symbol="RELIANCE")

    assert snapshot.symbol == "RELIANCE"
    assert snapshot.previous_day_high > 0
    assert snapshot.previous_day_low > 0
    assert snapshot.previous_week_high > 0
    assert snapshot.previous_week_low > 0
    assert snapshot.previous_month_high > 0
    assert snapshot.previous_month_low > 0
    assert snapshot.opening_range_high > 0
    assert snapshot.opening_range_low > 0
    assert snapshot.daily_pivot == pytest.approx(snapshot.classic_pivot.pivot)
    assert snapshot.weekly_pivot == pytest.approx(
        classic_pivot_levels(
            snapshot.previous_week.high,
            snapshot.previous_week.low,
            snapshot.previous_week.close,
        ).pivot,
    )
    assert snapshot.classic_pivot.resistance_1 > snapshot.classic_pivot.pivot
    assert snapshot.classic_pivot.support_1 < snapshot.classic_pivot.pivot
    assert snapshot.camarilla_pivot.resistance_4 > snapshot.camarilla_pivot.resistance_1
    assert snapshot.camarilla_pivot.support_4 < snapshot.camarilla_pivot.support_1
    assert snapshot.cpr.pivot == pytest.approx(snapshot.classic_pivot.pivot)
    assert snapshot.cpr.upper >= snapshot.cpr.lower
    assert snapshot.cpr.width_pct >= 0.0
    assert snapshot.supports
    assert snapshot.resistances


def test_supports_are_below_reference_and_nearest_first() -> None:
    service = LevelsService()
    snapshot = service.compute(make_daily_ohlcv())

    assert all(level.price < snapshot.reference_price for level in snapshot.supports)
    assert all(level.price > snapshot.reference_price for level in snapshot.resistances)
    assert snapshot.supports == sorted(snapshot.supports, key=lambda item: item.price, reverse=True)
    assert snapshot.resistances == sorted(snapshot.resistances, key=lambda item: item.price)


def test_compute_is_deterministic() -> None:
    service = LevelsService(opening_range_bars=1)
    frame = make_daily_ohlcv()

    first = service.compute(frame, symbol="reliance")
    second = service.compute(frame.copy(), symbol="RELIANCE")

    assert first.model_dump() == second.model_dump()


def test_as_of_truncates_future_bars() -> None:
    frame = make_daily_ohlcv(periods=70)
    mid = pd.Timestamp(frame.iloc[50]["date"])
    service = LevelsService()

    snapshot = service.compute(frame, as_of=mid)

    assert pd.Timestamp(snapshot.as_of) == mid
    assert snapshot.reference_price == pytest.approx(float(frame.iloc[50]["close"]))


def test_missing_prior_month_raises() -> None:
    frame = make_daily_ohlcv(start="2024-03-01", periods=5)
    service = LevelsService()

    with pytest.raises(LevelsValidationError, match="prior calendar month"):
        service.compute(frame)


def test_missing_columns_raises() -> None:
    frame = make_daily_ohlcv().drop(columns=["volume"])
    service = LevelsService()

    with pytest.raises(LevelsValidationError, match="Missing required"):
        service.compute(frame)


def test_build_support_resistance_excludes_equal_reference() -> None:
    levels = [
        PriceLevel(kind=LevelKind.PREVIOUS_DAY_HIGH, price=110.0, label="PDH"),
        PriceLevel(kind=LevelKind.PREVIOUS_DAY_LOW, price=90.0, label="PDL"),
        PriceLevel(kind=LevelKind.DAILY_PIVOT, price=100.0, label="Pivot"),
    ]
    supports, resistances = build_support_resistance(levels, reference_price=100.0)

    assert [level.kind for level in supports] == [LevelKind.PREVIOUS_DAY_LOW]
    assert [level.kind for level in resistances] == [LevelKind.PREVIOUS_DAY_HIGH]


def test_intraday_opening_range_via_service() -> None:
    service = LevelsService(opening_range_bars=2)
    snapshot = service.compute(make_intraday_session())

    assert snapshot.opening_range_high == pytest.approx(106.0)
    assert snapshot.opening_range_low == pytest.approx(102.5)
    assert any(level.kind is LevelKind.OPENING_RANGE_HIGH for level in snapshot.resistances + snapshot.supports)


def _iso_week(ts: pd.Timestamp) -> tuple[int, int]:
    iso = ts.isocalendar()
    return int(iso.year), int(iso.week)
