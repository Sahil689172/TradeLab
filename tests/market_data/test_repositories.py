"""Tests for SQLite metadata repositories."""

from __future__ import annotations

import pytest

from app.market_data.exceptions import RepositoryError
from app.market_data.repositories.company_metadata_repository import (
    SQLiteCompanyMetadataRepository,
)
from app.market_data.repositories.ingestion_state_repository import (
    SQLiteIngestionStateRepository,
)
from tests.market_data.conftest import make_company_metadata, make_ingestion_state


def test_company_metadata_repository_crud(db_session) -> None:
    """Company metadata can be saved, read, updated, and deleted."""
    repo = SQLiteCompanyMetadataRepository(db_session)
    metadata = make_company_metadata("TCS")

    saved = repo.save(metadata)
    assert saved.symbol == "TCS"

    fetched = repo.get("TCS")
    assert fetched is not None
    assert fetched.company_name == metadata.company_name

    updated = repo.update(
        make_company_metadata("TCS").model_copy(
            update={"company_name": "Tata Consultancy Services Ltd"},
        )
    )
    assert updated.company_name == "Tata Consultancy Services Ltd"

    assert repo.delete("TCS") is True
    assert repo.get("TCS") is None
    assert repo.delete("TCS") is False


def test_company_metadata_duplicate_save_raises(db_session) -> None:
    """Saving duplicate company metadata raises RepositoryError."""
    repo = SQLiteCompanyMetadataRepository(db_session)
    repo.save(make_company_metadata("INFY"))

    with pytest.raises(RepositoryError, match="already exists"):
        repo.save(make_company_metadata("INFY"))


def test_company_metadata_update_missing_raises(db_session) -> None:
    """Updating missing company metadata raises RepositoryError."""
    repo = SQLiteCompanyMetadataRepository(db_session)
    with pytest.raises(RepositoryError, match="not found"):
        repo.update(make_company_metadata("WIPRO"))


def test_ingestion_state_repository_crud(db_session) -> None:
    """Ingestion state can be saved, read, updated, and deleted."""
    repo = SQLiteIngestionStateRepository(db_session)
    state = make_ingestion_state("RELIANCE")

    saved = repo.save(state)
    assert saved.symbol == "RELIANCE"
    assert saved.row_count == 1000

    fetched = repo.get("RELIANCE")
    assert fetched is not None
    assert fetched.last_fetch_status == "success"

    updated = repo.update(
        make_ingestion_state("RELIANCE").model_copy(update={"row_count": 1200}),
    )
    assert updated.row_count == 1200

    assert repo.delete("RELIANCE") is True
    assert repo.get("RELIANCE") is None


def test_ingestion_state_duplicate_save_raises(db_session) -> None:
    """Saving duplicate ingestion state raises RepositoryError."""
    repo = SQLiteIngestionStateRepository(db_session)
    repo.save(make_ingestion_state("HDFCBANK"))

    with pytest.raises(RepositoryError, match="already exists"):
        repo.save(make_ingestion_state("HDFCBANK"))
