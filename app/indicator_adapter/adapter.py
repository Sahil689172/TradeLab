"""Read-only adapter over Feature Engineering Engine outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, overload

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
        points = [
            IndicatorPoint(
                timestamp=_as_datetime(timestamp),
                value=None if pd.isna(value) else float(value),
            )
            for timestamp, value in zip(frame["date"], frame[column], strict=True)
        ]
        return IndicatorSeries(name=request, column=column, points=points)

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
