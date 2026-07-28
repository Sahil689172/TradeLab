"""Public gateway for market data storage and ingestion operations."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.market_data.exceptions import RepositoryError, StorageError, ValidationError
from app.market_data.providers import MarketDataProvider, YFinanceProvider
from app.market_data.repositories.company_metadata_repository import (
    SQLiteCompanyMetadataRepository,
)
from app.market_data.repositories.ingestion_state_repository import (
    SQLiteIngestionStateRepository,
)
from app.market_data.repositories.parquet_repository import FileParquetRepository
from app.market_data.schemas.api import IngestionOperationResult, MarketStatusResponse
from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.schemas.ingestion_state import IngestionState
from app.market_data.services.bootstrap_engine import BootstrapEngine
from app.market_data.services.incremental_update_engine import IncrementalUpdateEngine
from app.market_data.services.metadata_sync_service import MetadataSyncService
from app.market_data.utils.ohlcv_normalizer import normalize_ohlcv_frame
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
        provider: MarketDataProvider | None = None,
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
        self._provider = provider or YFinanceProvider(cfg)
        self._bootstrap_engine = BootstrapEngine(
            self._provider,
            self._parquet_repo,
            self._metadata_repo,
            self._ingestion_repo,
            self._validator,
            cfg,
        )
        self._update_engine = IncrementalUpdateEngine(
            self._provider,
            self._parquet_repo,
            self._ingestion_repo,
            self._validator,
        )
        self._metadata_sync_service = MetadataSyncService(
            self._provider,
            self._metadata_repo,
        )

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
            normalized = normalize_ohlcv_frame(data)
            self._validator.validate(normalized)
            path = self._parquet_repo.write(symbol, normalized)
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

    def download_history(self, symbol: str, **kwargs: object) -> pd.DataFrame:
        """Download raw history from the provider without storing it."""
        return self._provider.download_history(symbol, **kwargs)

    def download_metadata(self, symbol: str) -> CompanyMetadata:
        """Download raw normalized metadata from the provider without storing it."""
        return self._provider.download_metadata(symbol)

    def bootstrap_symbol(self, symbol: str) -> IngestionOperationResult:
        """Bootstrap a symbol if it does not already exist locally."""
        result = self._bootstrap_engine.bootstrap_symbol(symbol)
        return IngestionOperationResult(**asdict(result))

    def bootstrap_all(self, symbols: list[str]) -> list[IngestionOperationResult]:
        """Bootstrap multiple symbols in order."""
        return [self.bootstrap_symbol(symbol) for symbol in symbols]

    def update_symbol(self, symbol: str) -> IngestionOperationResult:
        """Incrementally update one locally stored symbol."""
        result = self._update_engine.update_symbol(symbol)
        return IngestionOperationResult(**asdict(result))

    def update_all(self, symbols: list[str]) -> list[IngestionOperationResult]:
        """Incrementally update multiple locally stored symbols."""
        return [self.update_symbol(symbol) for symbol in symbols]

    def refresh_metadata(self, symbol: str) -> IngestionOperationResult:
        """Refresh company metadata for one symbol."""
        metadata = self._metadata_sync_service.refresh(symbol)
        state = self._ingestion_repo.get(metadata.symbol)
        return IngestionOperationResult(
            symbol=metadata.symbol,
            status="metadata_refreshed",
            rows_downloaded=0,
            rows_added=0,
            message="Metadata refreshed",
            metadata=metadata,
            ingestion_state=state,
        )

    def get_status(self, symbol: str) -> MarketStatusResponse:
        """Return current metadata, ingestion state, and history presence."""
        normalized_symbol = symbol.strip().upper()
        return MarketStatusResponse(
            symbol=normalized_symbol,
            history_exists=self.history_exists(normalized_symbol),
            metadata=self.get_metadata(normalized_symbol),
            ingestion_state=self.get_ingestion_state(normalized_symbol),
        )


def get_market_data_gateway(session: Session) -> MarketDataGateway:
    """Construct the public market data gateway."""
    return MarketDataGateway(session)
