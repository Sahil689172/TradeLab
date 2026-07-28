"""Metadata synchronization service."""

from __future__ import annotations

from app.core.logging import get_logger
from app.market_data.providers.base_provider import MarketDataProvider
from app.market_data.repositories.interfaces import CompanyMetadataRepository
from app.market_data.schemas.company_metadata import CompanyMetadata

logger = get_logger(__name__)


class MetadataSyncService:
    """Download and upsert company metadata."""

    def __init__(
        self,
        provider: MarketDataProvider,
        metadata_repository: CompanyMetadataRepository,
    ) -> None:
        self._provider = provider
        self._metadata_repository = metadata_repository

    def refresh(self, symbol: str) -> CompanyMetadata:
        """Download provider metadata and save or update the SQLite record."""
        metadata = self._provider.download_metadata(symbol)
        existing = self._metadata_repository.get(metadata.symbol)
        if existing is None:
            logger.info("Saving fresh metadata for %s", metadata.symbol)
            return self._metadata_repository.save(metadata)

        logger.info("Updating metadata for %s", metadata.symbol)
        return self._metadata_repository.update(metadata)
