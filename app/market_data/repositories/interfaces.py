"""Repository interfaces for market data storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.schemas.ingestion_state import IngestionState


class CompanyMetadataRepository(ABC):
    """Persistence contract for company metadata."""

    @abstractmethod
    def save(self, metadata: CompanyMetadata) -> CompanyMetadata:
        """Insert a new company metadata record."""

    @abstractmethod
    def get(self, symbol: str) -> CompanyMetadata | None:
        """Return metadata for a symbol, or None if not found."""

    @abstractmethod
    def update(self, metadata: CompanyMetadata) -> CompanyMetadata:
        """Update an existing company metadata record."""

    @abstractmethod
    def delete(self, symbol: str) -> bool:
        """Delete metadata for a symbol. Returns True if a row was removed."""


class IngestionStateRepository(ABC):
    """Persistence contract for ingestion state."""

    @abstractmethod
    def save(self, state: IngestionState) -> IngestionState:
        """Insert a new ingestion state record."""

    @abstractmethod
    def get(self, symbol: str) -> IngestionState | None:
        """Return ingestion state for a symbol, or None if not found."""

    @abstractmethod
    def update(self, state: IngestionState) -> IngestionState:
        """Update an existing ingestion state record."""

    @abstractmethod
    def delete(self, symbol: str) -> bool:
        """Delete ingestion state for a symbol. Returns True if a row was removed."""


class ParquetRepository(ABC):
    """Persistence contract for OHLCV Parquet files."""

    @abstractmethod
    def write(self, symbol: str, data: pd.DataFrame) -> Path:
        """Write OHLCV data to a symbol Parquet file."""

    @abstractmethod
    def read(self, symbol: str) -> pd.DataFrame:
        """Read OHLCV data for a symbol."""

    @abstractmethod
    def delete(self, symbol: str) -> bool:
        """Delete the Parquet file for a symbol."""

    @abstractmethod
    def exists(self, symbol: str) -> bool:
        """Return True if a Parquet file exists for the symbol."""

    @abstractmethod
    def append(self, symbol: str, data: pd.DataFrame) -> Path:
        """Append rows to an existing symbol file without introducing duplicates."""
