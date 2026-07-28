"""SQLite repository for ingestion state."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.market_data.exceptions import RepositoryError
from app.market_data.models.ingestion_state import IngestionStateModel
from app.market_data.repositories.interfaces import IngestionStateRepository
from app.market_data.schemas.ingestion_state import IngestionState

logger = get_logger(__name__)


class SQLiteIngestionStateRepository(IngestionStateRepository):
    """SQLite-backed ingestion state repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, state: IngestionState) -> IngestionState:
        try:
            if self.get(state.symbol) is not None:
                msg = f"Ingestion state already exists for symbol '{state.symbol}'"
                raise RepositoryError(msg)
            row = IngestionStateModel(**state.model_dump())
            self._session.add(row)
            self._session.commit()
            self._session.refresh(row)
            logger.info("Saved ingestion state for %s", state.symbol)
            return IngestionState.model_validate(row)
        except RepositoryError:
            raise
        except Exception as exc:
            self._session.rollback()
            logger.exception("Failed to save ingestion state for %s", state.symbol)
            raise RepositoryError(f"Failed to save ingestion state: {exc}") from exc

    def get(self, symbol: str) -> IngestionState | None:
        try:
            row = self._session.get(IngestionStateModel, symbol)
            if row is None:
                return None
            return IngestionState.model_validate(row)
        except Exception as exc:
            logger.exception("Failed to read ingestion state for %s", symbol)
            raise RepositoryError(f"Failed to read ingestion state: {exc}") from exc

    def update(self, state: IngestionState) -> IngestionState:
        try:
            row = self._session.get(IngestionStateModel, state.symbol)
            if row is None:
                msg = f"Ingestion state not found for symbol '{state.symbol}'"
                raise RepositoryError(msg)
            for key, value in state.model_dump().items():
                setattr(row, key, value)
            self._session.commit()
            self._session.refresh(row)
            logger.info("Updated ingestion state for %s", state.symbol)
            return IngestionState.model_validate(row)
        except RepositoryError:
            raise
        except Exception as exc:
            self._session.rollback()
            logger.exception("Failed to update ingestion state for %s", state.symbol)
            raise RepositoryError(f"Failed to update ingestion state: {exc}") from exc

    def delete(self, symbol: str) -> bool:
        try:
            row = self._session.get(IngestionStateModel, symbol)
            if row is None:
                return False
            self._session.delete(row)
            self._session.commit()
            logger.info("Deleted ingestion state for %s", symbol)
            return True
        except Exception as exc:
            self._session.rollback()
            logger.exception("Failed to delete ingestion state for %s", symbol)
            raise RepositoryError(f"Failed to delete ingestion state: {exc}") from exc
