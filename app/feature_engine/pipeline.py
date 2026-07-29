"""Composable feature engineering pipeline."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.feature_engine.indicators import (
    compute_momentum_features,
    compute_price_features,
    compute_trend_features,
    compute_volatility_features,
    compute_volume_features,
)

logger = get_logger(__name__)

IndicatorModule = Callable[[pd.DataFrame], pd.DataFrame]
REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "adj_close", "volume")
PIPELINE_VERSION = "a3.0.0"

DEFAULT_MODULES: tuple[IndicatorModule, ...] = (
    compute_trend_features,
    compute_momentum_features,
    compute_volatility_features,
    compute_volume_features,
    compute_price_features,
)


class FeaturePipeline:
    """Normalize OHLCV and concatenate independent indicator modules."""

    def __init__(
        self,
        modules: Sequence[IndicatorModule] | None = None,
        *,
        version: str = PIPELINE_VERSION,
    ) -> None:
        self._modules = DEFAULT_MODULES if modules is None else tuple(modules)
        self.version = version

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return one date-aligned frame containing every configured feature."""
        source = self._normalize_source(data)
        blocks: list[pd.DataFrame] = []
        for module in self._modules:
            block = module(source)
            if not isinstance(block, pd.DataFrame):
                raise TypeError(f"Indicator module {module.__name__} must return a DataFrame")
            if not block.index.equals(source.index):
                raise ValueError(f"Indicator module {module.__name__} returned a misaligned index")
            blocks.append(block)

        features = pd.concat(
            [source[["date"]], *blocks],
            axis=1,
        )
        duplicate_columns = features.columns[features.columns.duplicated()].tolist()
        if duplicate_columns:
            raise ValueError(f"Duplicate feature columns: {duplicate_columns}")

        features = features.replace([np.inf, -np.inf], np.nan)
        logger.info(
            "Feature pipeline generated %d features for %d rows",
            len(features.columns) - 1,
            len(features),
        )
        return features

    @staticmethod
    def _normalize_source(data: pd.DataFrame) -> pd.DataFrame:
        if data is None or data.empty:
            raise ValueError("OHLCV source data must not be empty")
        missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
        if missing:
            raise ValueError(f"Missing OHLCV columns: {missing}")

        source = data[list(REQUIRED_COLUMNS)].copy()
        source["date"] = pd.to_datetime(source["date"])
        for column in REQUIRED_COLUMNS[1:]:
            source[column] = pd.to_numeric(source[column], errors="raise")
        return (
            source.drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
