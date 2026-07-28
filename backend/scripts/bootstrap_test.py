#!/usr/bin/env python3
"""Real Yahoo Finance bootstrap integration test (no mocks).

Run from the project root:

    python backend/scripts/bootstrap_test.py

Optional symbol override:

    python backend/scripts/bootstrap_test.py TCS.NS

Force re-bootstrap (delete existing local data first):

    python backend/scripts/bootstrap_test.py --force
    python backend/scripts/bootstrap_test.py RELIANCE.NS --force
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.database import get_session_factory, init_db
from app.core.storage_paths import ensure_storage_directories
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.market_data.utils.ohlcv_normalizer import assert_ohlcv_schema
from app.market_data.utils.symbols import parquet_basename

DEFAULT_SYMBOL = "RELIANCE.NS"


def _parse_args(argv: list[str]) -> tuple[str, bool]:
    force = "--force" in argv
    positional = [arg for arg in argv if arg != "--force"]
    symbol = positional[0].strip().upper() if positional else DEFAULT_SYMBOL
    return symbol, force


def main() -> int:
    """Bootstrap one symbol using the real YFinanceProvider."""
    symbol, force = _parse_args(sys.argv[1:])
    settings = get_settings()

    print("=" * 60)
    print("TradeLab — Real Yahoo Finance Bootstrap Test")
    print("=" * 60)
    print(f"Symbol:              {symbol}")
    print(f"Metadata DB:         {settings.metadata_db_path}")
    print(f"Parquet directory:   {settings.parquet_storage_dir}")
    print()

    ensure_storage_directories(settings)
    init_db(settings)

    session = get_session_factory()()
    try:
        gateway = MarketDataGateway(session, settings=settings)
        if force:
            gateway.delete_history(symbol)
            gateway.delete_metadata(symbol)
            gateway.delete_ingestion_state(symbol)
            print("Force mode: removed existing local history and SQLite rows.")
            print()

        result = gateway.bootstrap_symbol(symbol)

        metadata = gateway.get_metadata(symbol)
        state = gateway.get_ingestion_state(symbol)
        parquet_path = settings.parquet_storage_dir / f"{parquet_basename(symbol)}.parquet"

        print(f"Bootstrap status:    {result.status}")
        print(f"Message:             {result.message}")
        print(f"Downloaded rows:     {result.rows_downloaded}")
        print()

        if state:
            print(f"First available date: {state.first_available_date}")
            print(f"Last available date:  {state.last_available_date}")
            print(f"Ingestion status:     {state.last_fetch_status}")
            print(f"SQLite row_count:     {state.row_count}")
        else:
            print("Ingestion state:       NOT FOUND")
        print()

        if metadata:
            print("Metadata:")
            print(f"  Company:   {metadata.company_name}")
            print(f"  Sector:    {metadata.sector}")
            print(f"  Industry:  {metadata.industry}")
            print(f"  Exchange:  {metadata.exchange}")
            print(f"  Currency:  {metadata.currency}")
            print(f"  Market cap: {metadata.market_cap}")
        else:
            print("Metadata:              NOT FOUND")
        print()

        print(f"Parquet location:    {parquet_path.resolve()}")
        print(f"Parquet exists:      {parquet_path.exists()}")
        if parquet_path.exists():
            frame = pd.read_parquet(parquet_path)
            print()
            print("Parquet schema:")
            print(frame.dtypes)
            assert_ohlcv_schema(frame)
            print("Parquet schema:      OK")
        print()

        sqlite_ok = metadata is not None and state is not None
        print(f"SQLite status:       {'OK' if sqlite_ok else 'INCOMPLETE'}")
        print("=" * 60)

        if result.status not in {"bootstrapped", "skipped"}:
            return 1
        if not parquet_path.exists():
            print("ERROR: Parquet file was not created.")
            return 1
        if not sqlite_ok:
            print("ERROR: SQLite metadata or ingestion_state missing.")
            return 1
        if result.status == "bootstrapped" and result.rows_downloaded <= 0:
            print("ERROR: Bootstrap reported zero downloaded rows.")
            return 1

        print("Bootstrap integration test PASSED.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
