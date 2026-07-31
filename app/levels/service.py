"""Service facade for reusable price-level computation."""

from __future__ import annotations

import pandas as pd

from app.core.logging import get_logger
from app.levels.calculator import (
    build_support_resistance,
    camarilla_pivot_levels,
    classic_pivot_levels,
    collect_named_levels,
    normalize_ohlcv,
    opening_range,
    previous_day_range,
    previous_month_range,
    previous_week_range,
    to_datetime,
)
from app.levels.exceptions import LevelsValidationError
from app.levels.schemas import LevelsSnapshot

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"


class LevelsService:
    """Compute session, period, pivot, support, and resistance levels from OHLCV.

    Deterministic: identical inputs and ``opening_range_bars`` always yield the
    same ``LevelsSnapshot``. No strategy or indicator logic is included.
    """

    def __init__(self, *, opening_range_bars: int = 1) -> None:
        if opening_range_bars < 1:
            raise ValueError("opening_range_bars must be >= 1")
        self._opening_range_bars = opening_range_bars

    @property
    def opening_range_bars(self) -> int:
        return self._opening_range_bars

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    def compute(
        self,
        ohlcv: pd.DataFrame,
        *,
        symbol: str | None = None,
        as_of: pd.Timestamp | None = None,
    ) -> LevelsSnapshot:
        """Return a levels snapshot as-of the latest bar (or ``as_of``).

        Args:
            ohlcv: Canonical OHLCV frame with ``date/open/high/low/close/volume``.
            symbol: Optional symbol tag for downstream consumers.
            as_of: Optional timestamp; defaults to the last bar in ``ohlcv``.
                The frame is truncated to bars at or before ``as_of``.
        """
        frame = normalize_ohlcv(ohlcv)
        as_of_ts = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(frame.iloc[-1]["date"])
        frame = frame[frame["date"] <= as_of_ts].copy()
        if frame.empty:
            raise LevelsValidationError("No OHLCV bars available at or before as_of")

        as_of_ts = pd.Timestamp(frame.iloc[-1]["date"])
        reference_price = float(frame.iloc[-1]["close"])

        previous_day = previous_day_range(frame, as_of_ts)
        previous_week = previous_week_range(frame, as_of_ts)
        previous_month = previous_month_range(frame, as_of_ts)
        or_high, or_low = opening_range(
            frame,
            as_of_ts,
            opening_range_bars=self._opening_range_bars,
        )

        classic = classic_pivot_levels(
            previous_day.high,
            previous_day.low,
            previous_day.close,
        )
        weekly = classic_pivot_levels(
            previous_week.high,
            previous_week.low,
            previous_week.close,
        )
        camarilla = camarilla_pivot_levels(
            previous_day.high,
            previous_day.low,
            previous_day.close,
        )

        named = collect_named_levels(
            previous_day_high=previous_day.high,
            previous_day_low=previous_day.low,
            previous_week_high=previous_week.high,
            previous_week_low=previous_week.low,
            previous_month_high=previous_month.high,
            previous_month_low=previous_month.low,
            opening_range_high=or_high,
            opening_range_low=or_low,
            daily_pivot=classic.pivot,
            weekly_pivot=weekly.pivot,
            classic=classic,
            camarilla=camarilla,
        )
        supports, resistances = build_support_resistance(
            named,
            reference_price=reference_price,
        )

        snapshot = LevelsSnapshot(
            symbol=symbol,
            as_of=to_datetime(as_of_ts),
            reference_price=reference_price,
            opening_range_bars=self._opening_range_bars,
            previous_day_high=previous_day.high,
            previous_day_low=previous_day.low,
            previous_week_high=previous_week.high,
            previous_week_low=previous_week.low,
            previous_month_high=previous_month.high,
            previous_month_low=previous_month.low,
            opening_range_high=or_high,
            opening_range_low=or_low,
            daily_pivot=classic.pivot,
            weekly_pivot=weekly.pivot,
            classic_pivot=classic,
            camarilla_pivot=camarilla,
            supports=supports,
            resistances=resistances,
            previous_day=previous_day,
            previous_week=previous_week,
            previous_month=previous_month,
        )
        logger.info(
            "Levels computed%s: as_of=%s supports=%d resistances=%d",
            f" for {snapshot.symbol}" if snapshot.symbol else "",
            snapshot.as_of.isoformat(),
            len(snapshot.supports),
            len(snapshot.resistances),
        )
        return snapshot
