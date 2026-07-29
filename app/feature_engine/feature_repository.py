"""Parquet persistence for generated feature datasets."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.core.logging import get_logger
from app.market_data.exceptions import RepositoryError
from app.market_data.utils.symbols import parquet_basename

logger = get_logger(__name__)


class FeatureRepository:
    """Store one ``SYMBOL_features.parquet`` file beside raw OHLCV data."""

    def __init__(self, storage_dir: Path | str) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, symbol: str) -> Path:
        """Return the feature Parquet path for a symbol."""
        basename = parquet_basename(symbol)
        if not basename:
            raise RepositoryError("Symbol must not be empty")
        return self._storage_dir / f"{basename}_features.parquet"

    def exists(self, symbol: str) -> bool:
        return self.path_for(symbol).exists()

    def write(self, symbol: str, features: pd.DataFrame) -> Path:
        """Normalize dates and atomically replace a feature dataset."""
        path = self.path_for(symbol)
        temporary_path = path.with_suffix(".parquet.tmp")
        try:
            frame = self._normalize(features)
            frame.to_parquet(temporary_path, engine="pyarrow", index=False)
            temporary_path.replace(path)
            logger.info("Wrote %d feature rows for %s to %s", len(frame), symbol, path)
            return path
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            raise RepositoryError(f"Failed to write features for '{symbol}': {exc}") from exc

    def read(self, symbol: str) -> pd.DataFrame:
        """Read a generated feature dataset."""
        path = self.path_for(symbol)
        if not path.exists():
            raise RepositoryError(f"Feature file not found for symbol '{symbol}'")
        try:
            return pd.read_parquet(path, engine="pyarrow")
        except Exception as exc:
            raise RepositoryError(f"Failed to read features for '{symbol}': {exc}") from exc

    def append(self, symbol: str, features: pd.DataFrame) -> Path:
        """Append new dates and rewrite a deduplicated feature dataset."""
        existing = self.read(symbol) if self.exists(symbol) else pd.DataFrame()
        combined = pd.concat([existing, features], ignore_index=True)
        return self.write(symbol, combined)

    def delete(self, symbol: str) -> bool:
        path = self.path_for(symbol)
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def _normalize(features: pd.DataFrame) -> pd.DataFrame:
        if features is None or features.empty:
            raise ValueError("Feature data must not be empty")
        if "date" not in features.columns:
            raise ValueError("Feature data must contain a date column")
        frame = features.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return (
            frame.drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
