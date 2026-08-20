"""Tests for market data storage paths and database initialization."""

from __future__ import annotations

from sqlalchemy import inspect

from app.core.database import Base, check_database_connection, init_db, reset_db_state
from app.core.storage_paths import ensure_storage_directories
from app.market_data.models import CompanyMetadataModel, IngestionStateModel


def test_storage_directories_created(storage_settings) -> None:
    """Required backend/data directories are created automatically."""
    paths = ensure_storage_directories(storage_settings)
    assert paths["data_root"].exists()
    assert paths["ohlcv"].exists()
    assert paths["logs"].exists()
    # ohlcv must remain empty until ingestion is implemented.
    assert not any(paths["ohlcv"].glob("*.parquet"))


def test_metadata_database_initializes(storage_settings) -> None:
    """SQLite metadata database is created and accepts connections."""
    ensure_storage_directories(storage_settings)
    reset_db_state()
    engine = init_db(storage_settings)

    assert storage_settings.metadata_db_path.exists()
    assert check_database_connection(engine) is True


def test_required_tables_exist(storage_settings) -> None:
    """Market data tables are created on init (alongside collab tables)."""
    ensure_storage_directories(storage_settings)
    reset_db_state()
    engine = init_db(storage_settings)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert {"company_metadata", "ingestion_state"} <= table_names
    assert CompanyMetadataModel.__tablename__ in table_names
    assert IngestionStateModel.__tablename__ in table_names
    # Market data owns 2 tables; the collaboration module registers 3 more
    # on the same metadata database.
    assert len(Base.metadata.tables) == 5
