"""First-time market data bootstrap service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.market_data.providers.base_provider import MarketDataProvider
from app.market_data.repositories.interfaces import (
    CompanyMetadataRepository,
    IngestionStateRepository,
    ParquetRepository,
)
from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.schemas.ingestion_state import IngestionState
from app.market_data.utils.ohlcv_normalizer import normalize_ohlcv_frame
from app.market_data.validators.ohlcv_validator import OHLCVValidator

logger = get_logger(__name__)


@dataclass(slots=True)
class BootstrapResult:
    """Outcome of a bootstrap attempt."""

    symbol: str
    status: str
    rows_downloaded: int
    metadata: CompanyMetadata | None
    ingestion_state: IngestionState | None
    message: str


class BootstrapEngine:
    """Download and persist first-time symbol history."""

    def __init__(
        self,
        provider: MarketDataProvider,
        parquet_repository: ParquetRepository,
        metadata_repository: CompanyMetadataRepository,
        ingestion_repository: IngestionStateRepository,
        validator: OHLCVValidator,
        settings: Settings | None = None,
    ) -> None:
        self._provider = provider
        self._parquet_repository = parquet_repository
        self._metadata_repository = metadata_repository
        self._ingestion_repository = ingestion_repository
        self._validator = validator
        self._settings = settings or get_settings()

    def bootstrap_symbol(self, symbol: str) -> BootstrapResult:
        """Bootstrap roughly ten years of data when symbol is not stored yet."""
        normalized_symbol = symbol.strip().upper()
        if self._parquet_repository.exists(normalized_symbol):
            logger.info("Skipping bootstrap for %s; history already exists", normalized_symbol)
            state = self._ingestion_repository.get(normalized_symbol)
            metadata = self._metadata_repository.get(normalized_symbol)
            return BootstrapResult(
                symbol=normalized_symbol,
                status="skipped",
                rows_downloaded=0,
                metadata=metadata,
                ingestion_state=state,
                message="History already exists locally",
            )

        logger.info("Bootstrap started for %s", normalized_symbol)
        start_date = date.today() - timedelta(days=365 * self._settings.bootstrap_history_years)
        end_date = date.today() + timedelta(days=1)

        history = self._provider.download_history(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
        )
        normalized_history = normalize_ohlcv_frame(history)
        self._validator.validate(normalized_history)
        self._parquet_repository.write(normalized_symbol, normalized_history)

        metadata = self._provider.download_metadata(normalized_symbol)
        existing_metadata = self._metadata_repository.get(normalized_symbol)
        stored_metadata = (
            self._metadata_repository.update(metadata)
            if existing_metadata is not None
            else self._metadata_repository.save(metadata)
        )

        state = IngestionState(
            symbol=normalized_symbol,
            first_available_date=self._frame_date_min(normalized_history),
            last_available_date=self._frame_date_max(normalized_history),
            last_fetch_timestamp=datetime.now(timezone.utc),
            last_fetch_status="success",
            row_count=len(normalized_history),
        )
        existing_state = self._ingestion_repository.get(normalized_symbol)
        stored_state = (
            self._ingestion_repository.update(state)
            if existing_state is not None
            else self._ingestion_repository.save(state)
        )
        logger.info("Bootstrap completed for %s with %d rows", normalized_symbol, len(normalized_history))
        return BootstrapResult(
            symbol=normalized_symbol,
            status="bootstrapped",
            rows_downloaded=len(normalized_history),
            metadata=stored_metadata,
            ingestion_state=stored_state,
            message="Bootstrap completed",
        )

    @staticmethod
    def _frame_date_min(frame: pd.DataFrame) -> date:
        return pd.to_datetime(frame["date"]).dt.date.min()

    @staticmethod
    def _frame_date_max(frame: pd.DataFrame) -> date:
        return pd.to_datetime(frame["date"]).dt.date.max()
