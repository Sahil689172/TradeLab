"""Public gateway for market data storage operations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.market_data.exceptions import RepositoryError, StorageError, ValidationError
from app.market_data.repositories.company_metadata_repository import (
    SQLiteCompanyMetadataRepository,
)
from app.market_data.repositories.ingestion_state_repository import (
    SQLiteIngestionStateRepository,
)
from app.market_data.repositories.parquet_repository import FileParquetRepository
from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.schemas.ingestion_state import IngestionState
from app.market_data.validators.ohlcv_validator import OHLCVValidator

logger = get_logger(__name__)


class MarketDataGateway:
    """Single public interface for market data storage.

    Future modules must interact with market data storage only through this
    gateway. Repositories remain internal implementation details.
    """

    def __init__(
        self,
        session: Session,
        *,
        parquet_repository: FileParquetRepository | None = None,
        metadata_repository: SQLiteCompanyMetadataRepository | None = None,
        ingestion_repository: SQLiteIngestionStateRepository | None = None,
        validator: OHLCVValidator | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._settings = cfg
        self._session = session
        self._metadata_repo = metadata_repository or SQLiteCompanyMetadataRepository(session)
        self._ingestion_repo = ingestion_repository or SQLiteIngestionStateRepository(session)
        self._parquet_repo = parquet_repository or FileParquetRepository(cfg.parquet_storage_dir)
        self._validator = validator or OHLCVValidator()

    def save_history(self, symbol: str, data: pd.DataFrame) -> Path:
        """Validate and persist OHLCV history to Parquet.

        Args:
            symbol: Trading symbol (e.g. ``RELIANCE``).
            data: OHLCV DataFrame.

        Returns:
            Path to the written Parquet file.

        Raises:
            ValidationError: When OHLCV validation fails.
            RepositoryError: When Parquet write fails.
        """
        try:
            self._validator.validate(data)
            path = self._parquet_repo.write(symbol, data)
            logger.info("Saved OHLCV history for %s", symbol)
            return path
        except (ValidationError, RepositoryError):
            raise
        except Exception as exc:
            logger.exception("Unexpected error saving history for %s", symbol)
            raise StorageError(f"Failed to save history for '{symbol}': {exc}") from exc

    def get_history(self, symbol: str) -> pd.DataFrame:
        """Load OHLCV history from Parquet.

        Raises:
            RepositoryError: When the file is missing or unreadable.
        """
        try:
            return self._parquet_repo.read(symbol)
        except RepositoryError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error reading history for %s", symbol)
            raise StorageError(f"Failed to read history for '{symbol}': {exc}") from exc

    def save_metadata(self, metadata: CompanyMetadata) -> CompanyMetadata:
        """Persist new company metadata."""
        return self._metadata_repo.save(metadata)

    def get_metadata(self, symbol: str) -> CompanyMetadata | None:
        """Retrieve company metadata for a symbol."""
        return self._metadata_repo.get(symbol)

    def update_metadata(self, metadata: CompanyMetadata) -> CompanyMetadata:
        """Update existing company metadata."""
        return self._metadata_repo.update(metadata)

    def delete_metadata(self, symbol: str) -> bool:
        """Delete company metadata for a symbol."""
        return self._metadata_repo.delete(symbol)

    def get_ingestion_state(self, symbol: str) -> IngestionState | None:
        """Retrieve ingestion state for a symbol."""
        return self._ingestion_repo.get(symbol)

    def save_ingestion_state(self, state: IngestionState) -> IngestionState:
        """Persist new ingestion state."""
        return self._ingestion_repo.save(state)

    def update_ingestion_state(self, state: IngestionState) -> IngestionState:
        """Update existing ingestion state."""
        return self._ingestion_repo.update(state)

    def delete_ingestion_state(self, symbol: str) -> bool:
        """Delete ingestion state for a symbol."""
        return self._ingestion_repo.delete(symbol)

    def delete_history(self, symbol: str) -> bool:
        """Delete OHLCV Parquet file for a symbol."""
        return self._parquet_repo.delete(symbol)

    def history_exists(self, symbol: str) -> bool:
        """Return True when a Parquet file exists for the symbol."""
        return self._parquet_repo.exists(symbol)


def get_market_data_gateway(session: Session) -> MarketDataGateway:
    """FastAPI-compatible factory for dependency injection."""
    return MarketDataGateway(session)
