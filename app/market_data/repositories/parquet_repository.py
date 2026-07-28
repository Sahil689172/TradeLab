"""Parquet file repository for OHLCV history."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow
import pyarrow.parquet as pq

from app.core.logging import get_logger
from app.market_data.exceptions import RepositoryError
from app.market_data.repositories.interfaces import ParquetRepository
from app.market_data.validators.ohlcv_validator import OHLCV_COLUMNS

logger = get_logger(__name__)


class FileParquetRepository(ParquetRepository):
    """Read and write OHLCV Parquet files on the local filesystem."""

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, symbol: str) -> Path:
        safe_symbol = symbol.strip().upper()
        if not safe_symbol:
            raise RepositoryError("Symbol must not be empty")
        return self._storage_dir / f"{safe_symbol}.parquet"

    def write(self, symbol: str, data: pd.DataFrame) -> Path:
        path = self._file_path(symbol)
        try:
            frame = data[list(OHLCV_COLUMNS)].copy()
            frame.to_parquet(path, engine="pyarrow", index=False)
            logger.info("Wrote Parquet file for %s (%d rows) -> %s", symbol, len(frame), path)
            return path
        except Exception as exc:
            logger.exception("Failed to write Parquet file for %s", symbol)
            raise RepositoryError(f"Failed to write Parquet file for '{symbol}': {exc}") from exc

    def read(self, symbol: str) -> pd.DataFrame:
        path = self._file_path(symbol)
        if not path.exists():
            msg = f"Parquet file not found for symbol '{symbol}'"
            raise RepositoryError(msg)
        try:
            table = pq.read_table(path)
            frame = table.to_pandas()
            logger.info("Read Parquet file for %s (%d rows) from %s", symbol, len(frame), path)
            return frame
        except (pyarrow.ArrowInvalid, OSError, ValueError) as exc:
            logger.exception("Invalid or unreadable Parquet file for %s", symbol)
            raise RepositoryError(
                f"Invalid or unreadable Parquet file for '{symbol}': {exc}",
            ) from exc
        except Exception as exc:
            logger.exception("Failed to read Parquet file for %s", symbol)
            raise RepositoryError(f"Failed to read Parquet file for '{symbol}': {exc}") from exc

    def delete(self, symbol: str) -> bool:
        path = self._file_path(symbol)
        if not path.exists():
            return False
        try:
            path.unlink()
            logger.info("Deleted Parquet file for %s", symbol)
            return True
        except Exception as exc:
            logger.exception("Failed to delete Parquet file for %s", symbol)
            raise RepositoryError(f"Failed to delete Parquet file for '{symbol}': {exc}") from exc

    def exists(self, symbol: str) -> bool:
        return self._file_path(symbol).exists()
