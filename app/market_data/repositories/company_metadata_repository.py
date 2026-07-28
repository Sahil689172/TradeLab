"""SQLite repository for company metadata."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.market_data.exceptions import RepositoryError
from app.market_data.models.company_metadata import CompanyMetadataModel
from app.market_data.repositories.interfaces import CompanyMetadataRepository
from app.market_data.schemas.company_metadata import CompanyMetadata

logger = get_logger(__name__)


class SQLiteCompanyMetadataRepository(CompanyMetadataRepository):
    """SQLite-backed company metadata repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, metadata: CompanyMetadata) -> CompanyMetadata:
        try:
            if self.get(metadata.symbol) is not None:
                msg = f"Company metadata already exists for symbol '{metadata.symbol}'"
                raise RepositoryError(msg)
            row = CompanyMetadataModel(**metadata.model_dump())
            self._session.add(row)
            self._session.commit()
            self._session.refresh(row)
            logger.info("Saved company metadata for %s", metadata.symbol)
            return CompanyMetadata.model_validate(row)
        except RepositoryError:
            raise
        except Exception as exc:
            self._session.rollback()
            logger.exception("Failed to save company metadata for %s", metadata.symbol)
            raise RepositoryError(f"Failed to save company metadata: {exc}") from exc

    def get(self, symbol: str) -> CompanyMetadata | None:
        try:
            row = self._session.get(CompanyMetadataModel, symbol)
            if row is None:
                return None
            return CompanyMetadata.model_validate(row)
        except Exception as exc:
            logger.exception("Failed to read company metadata for %s", symbol)
            raise RepositoryError(f"Failed to read company metadata: {exc}") from exc

    def update(self, metadata: CompanyMetadata) -> CompanyMetadata:
        try:
            row = self._session.get(CompanyMetadataModel, metadata.symbol)
            if row is None:
                msg = f"Company metadata not found for symbol '{metadata.symbol}'"
                raise RepositoryError(msg)
            for key, value in metadata.model_dump().items():
                setattr(row, key, value)
            self._session.commit()
            self._session.refresh(row)
            logger.info("Updated company metadata for %s", metadata.symbol)
            return CompanyMetadata.model_validate(row)
        except RepositoryError:
            raise
        except Exception as exc:
            self._session.rollback()
            logger.exception("Failed to update company metadata for %s", metadata.symbol)
            raise RepositoryError(f"Failed to update company metadata: {exc}") from exc

    def delete(self, symbol: str) -> bool:
        try:
            row = self._session.get(CompanyMetadataModel, symbol)
            if row is None:
                return False
            self._session.delete(row)
            self._session.commit()
            logger.info("Deleted company metadata for %s", symbol)
            return True
        except Exception as exc:
            self._session.rollback()
            logger.exception("Failed to delete company metadata for %s", symbol)
            raise RepositoryError(f"Failed to delete company metadata: {exc}") from exc
