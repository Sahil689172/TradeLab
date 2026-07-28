"""Shared fixtures for market data storage and ingestion tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, clear_settings_cache
from app.core.database import get_session_factory, init_db, reset_db_state
from app.core.storage_paths import ensure_storage_directories
from app.market_data.providers.base_provider import MarketDataProvider
from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.schemas.ingestion_state import IngestionState
from app.market_data.services.market_data_gateway import MarketDataGateway


@pytest.fixture()
def storage_settings(tmp_path: Path) -> Settings:
    """Isolated storage paths and metadata database for market data tests."""
    clear_settings_cache()
    reset_db_state()

    data_root = tmp_path / "backend" / "data"
    metadata_db = data_root / "metadata.db"
    settings = Settings(
        app_name="TradeLab",
        app_version="0.1.0",
        app_env="test",
        debug=True,
        metadata_database_url=f"sqlite:///{metadata_db.as_posix()}",
        database_url=f"sqlite:///{metadata_db.as_posix()}",
        parquet_storage_dir=data_root / "ohlcv",
        log_directory=data_root / "logs",
        log_level="WARNING",
        log_format="console",
    )
    yield settings
    reset_db_state()
    clear_settings_cache()


@pytest.fixture()
def db_session(storage_settings: Settings) -> Session:
    """SQLAlchemy session with initialized metadata tables."""
    ensure_storage_directories(storage_settings)
    init_db(storage_settings)
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def gateway(db_session: Session, storage_settings: Settings) -> MarketDataGateway:
    """Market data gateway wired to the test session and storage paths."""
    return MarketDataGateway(
        db_session,
        settings=storage_settings,
        provider=FakeProvider(),
    )


def make_ohlcv_dataframe(rows: int = 3) -> pd.DataFrame:
    """Build a valid OHLCV DataFrame for tests."""
    base = date(2024, 1, 1)
    records = []
    for index in range(rows):
        bar_date = base + timedelta(days=index)
        records.append(
            {
                "date": bar_date,
                "open": 100.0 + index,
                "high": 105.0 + index,
                "low": 95.0 + index,
                "close": 102.0 + index,
                "adj_close": 102.0 + index,
                "volume": 1000.0 + index,
            }
        )
    return pd.DataFrame(records)


def make_company_metadata(symbol: str = "RELIANCE") -> CompanyMetadata:
    """Build sample company metadata."""
    return CompanyMetadata(
        symbol=symbol,
        company_name="Reliance Industries Ltd",
        sector="Energy",
        industry="Oil & Gas",
        exchange="NSE",
        currency="INR",
        market_cap=1_500_000.0,
        market_cap_date=date(2024, 6, 30),
        last_updated=datetime(2024, 7, 1, tzinfo=timezone.utc),
    )


def make_ingestion_state(symbol: str = "RELIANCE") -> IngestionState:
    """Build sample ingestion state."""
    return IngestionState(
        symbol=symbol,
        first_available_date=date(2020, 1, 1),
        last_available_date=date(2024, 6, 30),
        last_fetch_timestamp=datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc),
        last_fetch_status="success",
        row_count=1000,
    )


class FakeProvider(MarketDataProvider):
    """Deterministic provider used by tests to avoid network access."""

    def download_history(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        frame = make_ohlcv_dataframe(rows=5)
        if start_date is not None:
            frame = frame[frame["date"] >= start_date]
        if end_date is not None:
            frame = frame[frame["date"] < end_date]
        return frame.reset_index(drop=True)

    def download_metadata(self, symbol: str) -> CompanyMetadata:
        return make_company_metadata(symbol.strip().upper())

    def download_company_info(self, symbol: str) -> dict[str, object]:
        metadata = self.download_metadata(symbol)
        return {
            "longName": metadata.company_name,
            "sector": metadata.sector,
            "industry": metadata.industry,
            "exchange": metadata.exchange,
            "currency": metadata.currency,
            "marketCap": metadata.market_cap,
        }
