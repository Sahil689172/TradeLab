"""Read-only adapter over Feature Engineering Engine outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, overload

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.feature_engine.feature_repository import FeatureRepository
from app.indicator_adapter.cache import IndicatorCache
from app.indicator_adapter.catalog import list_aliases, resolve_indicator_name
from app.indicator_adapter.exceptions import IndicatorValidationError
from app.indicator_adapter.schemas import (
    IndicatorPoint,
    IndicatorSeries,
    IndicatorValue,
    MacdIndicator,
)
from app.market_data.utils.symbols import parquet_basename

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"

# Shared point memo: (column, first-date, first-value) -> (dates, values, points).
#
# Strategies construct a fresh IndicatorAdapter per evaluated bar (see e.g.
# EMATrendStrategy._snapshot), and a replay re-binds a frame that grows by one
# row per bar.  Rebuilding every earlier IndicatorPoint on each bar made
# indicator access quadratic in bar count and dominated replay runtime, so the
# memo has to outlive the adapter instance to be reachable at all.
#
# Every hit is verified by comparing the cached date AND value prefixes against
# the incoming frame, so a coincidental key collision (NSE symbols all share a
# trading calendar) degrades to a rebuild rather than returning wrong data.
_POINTS_MEMO: dict[
    tuple[str, int, float],
    tuple[np.ndarray, np.ndarray, list[IndicatorPoint]],
] = {}
_POINTS_MEMO_MAX = 256


def clear_points_memo() -> None:
    """Drop the shared indicator-point memo (used by tests and cache resets)."""
    _POINTS_MEMO.clear()


class IndicatorAdapter:
    """Expose feature-engine columns through a clean ``indicator(name)`` API.

    This adapter never recalculates EMA/RSI/ATR/MACD. It only reads columns from
    an in-memory feature frame or ``FeatureRepository`` Parquet files.
    """

    def __init__(
        self,
        features: pd.DataFrame | None = None,
        *,
        repository: FeatureRepository | None = None,
        cache: IndicatorCache | None = None,
    ) -> None:
        self._repository = repository
        self._cache = cache or IndicatorCache()
        self._features: pd.DataFrame | None = None
        self._frame_key: str | None = None
        if features is not None:
            self.bind(features)

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    @property
    def cache(self) -> IndicatorCache:
        return self._cache

    def bind(self, features: pd.DataFrame) -> IndicatorAdapter:
        """Bind an in-memory feature DataFrame produced by the feature engine."""
        frame = self._normalize_features(features)
        self._features = frame
        self._frame_key = self._fingerprint(frame)
        return self

    def for_symbol(self, symbol: str) -> IndicatorAdapter:
        """Load and bind feature data for ``symbol`` via ``FeatureRepository``."""
        if self._repository is None:
            raise IndicatorValidationError(
                "FeatureRepository is required to load indicators by symbol",
            )

        key = parquet_basename(symbol).upper()
        cached = self._cache.frames.get(key)
        if cached is not None:
            self._features = cached
            self._frame_key = f"symbol:{key}"
            logger.debug("Feature frame cache hit for %s", key)
            return self

        frame = self._normalize_features(self._repository.read(symbol))
        self._cache.frames.set(key, frame)
        self._features = frame
        self._frame_key = f"symbol:{key}"
        logger.info("Loaded feature frame for %s (%d rows)", key, len(frame))
        return self

    def available(self) -> list[str]:
        """Return sorted feature column names excluding ``date``."""
        frame = self._require_features()
        return sorted(column for column in frame.columns if column != "date")

    def aliases(self) -> dict[str, str]:
        """Return supported friendly-name aliases."""
        return list_aliases()

    def clear_cache(self) -> None:
        """Clear frame and indicator object caches."""
        self._cache.clear()
        clear_points_memo()

    @overload
    def indicator(self, name: Literal["macd"]) -> MacdIndicator: ...

    @overload
    def indicator(self, name: str) -> IndicatorValue: ...

    def indicator(self, name: str) -> IndicatorValue:
        """Return a typed indicator object for ``name``.

        Examples:
            adapter.indicator("ema_20")
            adapter.indicator("atr")
            adapter.indicator("rsi")
            adapter.indicator("macd")
        """
        frame = self._require_features()
        cache_key = f"{self._frame_key}:{name.strip().lower()}"
        cached = self._cache.indicators.get(cache_key)
        if cached is not None:
            logger.debug("Indicator cache hit for %s", name)
            return cached

        resolved = resolve_indicator_name(name, set(frame.columns))
        if resolved.is_macd_bundle:
            assert resolved.columns is not None
            payload: IndicatorValue = MacdIndicator(
                line=self._series_from_column(frame, request="macd", column=resolved.columns[0]),
                signal=self._series_from_column(
                    frame,
                    request="macd_signal",
                    column=resolved.columns[1],
                ),
                histogram=self._series_from_column(
                    frame,
                    request="macd_histogram",
                    column=resolved.columns[2],
                ),
            )
        else:
            assert resolved.column is not None
            payload = self._series_from_column(
                frame,
                request=resolved.request,
                column=resolved.column,
            )

        self._cache.indicators.set(cache_key, payload)
        return payload

    def _series_from_column(
        self,
        frame: pd.DataFrame,
        *,
        request: str,
        column: str,
    ) -> IndicatorSeries:
        """Build the typed series for ``column``.

        Hot path: a replay re-binds a date-capped frame on every bar, so this
        runs once per bar per indicator over the whole capped frame.  Building
        it row-by-row through full Pydantic validation dominated replay runtime
        (~66% of a walk-forward window), so both axes are handled in bulk:

        - timestamps/values are converted with one vectorized pandas/NumPy call
          each instead of one ``pd.Timestamp(...)`` per row;
        - points are built with ``model_construct``, which skips per-point
          schema validation.  The inputs are already exactly typed here
          (``datetime`` and ``float | None``), so validation had nothing left
          to check -- it was pure overhead.

        Field semantics are unchanged; only the cost of producing them is.

        The frame a replay binds grows by one row per bar, so rebuilding every
        earlier point each time made this quadratic in bar count.  The memo
        below keeps the canonical point list per column and only builds rows
        that are genuinely new.  Reusing a prefix is sound because the frame is
        the same underlying series capped at a later date -- earlier rows are
        byte-identical -- and it never materializes a point past the cap, so
        the walk-forward date-capping guarantees are untouched.
        """
        dates = frame["date"]
        if not pd.api.types.is_datetime64_any_dtype(dates):
            dates = pd.to_datetime(dates)
        raw = frame[column].to_numpy(dtype="float64", copy=False)
        n_rows = len(raw)

        tz_aware = getattr(dates.dt, "tz", None) is not None
        date_key = None if tz_aware else dates.to_numpy(dtype="datetime64[ns]")

        memo_key: tuple[str, int, float] | None = None
        if date_key is not None and n_rows > 0:
            first_value = float(raw[0])
            memo_key = (
                column,
                int(date_key[0].astype("int64")),
                first_value if first_value == first_value else float("inf"),
            )

        start = 0
        canonical: list[IndicatorPoint] = []
        memo = _POINTS_MEMO.get(memo_key) if memo_key is not None else None
        if memo is not None:
            cached_dates, cached_values, cached_points = memo
            reuse = min(len(cached_points), n_rows)
            # Dates alone are not a safe identity: every NSE symbol shares the
            # same trading calendar, so a different symbol's frame would match
            # on dates while carrying different values.  Compare the values too
            # (a vectorized compare, far cheaper than rebuilding the points).
            if (
                reuse > 0
                and np.array_equal(cached_dates[:reuse], date_key[:reuse])
                and np.array_equal(cached_values[:reuse], raw[:reuse], equal_nan=True)
            ):
                canonical = cached_points
                start = reuse

        if start < n_rows:
            if tz_aware:
                new_timestamps: object = [_as_datetime(value) for value in dates[start:]]
            else:
                # datetime64[us] -> object yields real ``datetime`` objects in
                # bulk, without the .dt.to_pydatetime deprecation.
                new_timestamps = (
                    dates.to_numpy(dtype="datetime64[us]")[start:].astype(object)
                )
            new_values = raw[start:]
            new_missing = pd.isna(new_values)
            construct = IndicatorPoint.model_construct
            fresh = [
                construct(timestamp=timestamp, value=None if is_na else float(value))
                for timestamp, value, is_na in zip(
                    new_timestamps, new_values, new_missing, strict=True,
                )
            ]
            if start == 0:
                canonical = fresh
            else:
                canonical = canonical + fresh
            if memo_key is not None:
                size = len(canonical)
                if len(_POINTS_MEMO) >= _POINTS_MEMO_MAX and memo_key not in _POINTS_MEMO:
                    _POINTS_MEMO.pop(next(iter(_POINTS_MEMO)), None)
                _POINTS_MEMO[memo_key] = (
                    date_key[:size], raw[:size].copy(), canonical,
                )

        # Hand out a prefix matching this frame; never expose rows past the cap.
        points = canonical if len(canonical) == n_rows else canonical[:n_rows]
        return IndicatorSeries.model_construct(
            name=request.strip().lower(),
            column=column.strip().lower(),
            points=points,
        )

    def _require_features(self) -> pd.DataFrame:
        if self._features is None:
            raise IndicatorValidationError(
                "No feature data bound. Call bind(features) or for_symbol(symbol) first.",
            )
        return self._features

    @staticmethod
    def _normalize_features(features: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(features, pd.DataFrame):
            raise TypeError(f"Expected pandas DataFrame, got {type(features).__name__}")
        if features.empty:
            raise IndicatorValidationError("Feature DataFrame must not be empty")
        if "date" not in features.columns:
            raise IndicatorValidationError("Feature DataFrame must contain a 'date' column")

        frame = features.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return (
            frame.drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )

    @staticmethod
    def _fingerprint(frame: pd.DataFrame) -> str:
        last_date = pd.Timestamp(frame.iloc[-1]["date"]).isoformat()
        columns = ",".join(frame.columns.astype(str))
        return f"mem:{len(frame)}:{last_date}:{hash(columns)}"


def _as_datetime(value: object) -> datetime:
    return pd.Timestamp(value).to_pydatetime()
