"""Incremental market data synchronization service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from app.core.logging import get_logger
from app.market_data.exceptions import RepositoryError
from app.market_data.providers.base_provider import MarketDataProvider
from app.market_data.repositories.interfaces import IngestionStateRepository, ParquetRepository
from app.market_data.schemas.ingestion_state import IngestionState
from app.market_data.validators.ohlcv_validator import OHLCVValidator

logger = get_logger(__name__)


@dataclass(slots=True)
class UpdateResult:
    """Outcome of an incremental update attempt."""

    symbol: str
    status: str
    rows_downloaded: int
    rows_added: int
    ingestion_state: IngestionState
    message: str


class IncrementalUpdateEngine:
    """Download only missing OHLCV rows and append them safely."""

    def __init__(
        self,
        provider: MarketDataProvider,
        parquet_repository: ParquetRepository,
        ingestion_repository: IngestionStateRepository,
        validator: OHLCVValidator,
    ) -> None:
        self._provider = provider
        self._parquet_repository = parquet_repository
        self._ingestion_repository = ingestion_repository
        self._validator = validator

    def update_symbol(self, symbol: str) -> UpdateResult:
        """Update a stored symbol using its current ingestion state."""
        normalized_symbol = symbol.strip().upper()
        state = self._ingestion_repository.get(normalized_symbol)
        if state is None or state.last_available_date is None:
            raise RepositoryError(
                f"Ingestion state not found for '{normalized_symbol}'; bootstrap first",
            )

        start_date = state.last_available_date + timedelta(days=1)
        end_date = date.today() + timedelta(days=1)
        logger.info(
            "Incremental update started for %s from %s to %s",
            normalized_symbol,
            start_date,
            end_date,
        )

        if start_date >= end_date:
            state = state.model_copy(
                update={"last_fetch_timestamp": datetime.now(timezone.utc)},
            )
            stored = self._ingestion_repository.update(state)
            return UpdateResult(
                symbol=normalized_symbol,
                status="up_to_date",
                rows_downloaded=0,
                rows_added=0,
                ingestion_state=stored,
                message="No missing trading days",
            )

        history = self._provider.download_history(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
        )
        if history.empty:
            stored = self._ingestion_repository.update(
                state.model_copy(
                    update={
                        "last_fetch_timestamp": datetime.now(timezone.utc),
                        "last_fetch_status": "up_to_date",
                    },
                ),
            )
            return UpdateResult(
                symbol=normalized_symbol,
                status="up_to_date",
                rows_downloaded=0,
                rows_added=0,
                ingestion_state=stored,
                message="No new rows returned by provider",
            )
        self._validator.validate(history)

        existing = self._parquet_repository.read(normalized_symbol)
        before_rows = len(existing)
        self._parquet_repository.append(normalized_symbol, history)
        combined = self._parquet_repository.read(normalized_symbol)
        after_rows = len(combined)
        rows_added = after_rows - before_rows

        stored_state = self._ingestion_repository.update(
            IngestionState(
                symbol=normalized_symbol,
                first_available_date=state.first_available_date
                or pd.to_datetime(combined["date"]).dt.date.min(),
                last_available_date=pd.to_datetime(combined["date"]).dt.date.max(),
                last_fetch_timestamp=datetime.now(timezone.utc),
                last_fetch_status="success",
                row_count=after_rows,
            ),
        )
        logger.info(
            "Incremental update completed for %s (%d downloaded, %d added)",
            normalized_symbol,
            len(history),
            rows_added,
        )
        return UpdateResult(
            symbol=normalized_symbol,
            status="updated",
            rows_downloaded=len(history),
            rows_added=rows_added,
            ingestion_state=stored_state,
            message="Incremental update completed",
        )
