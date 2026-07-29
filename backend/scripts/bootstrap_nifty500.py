#!/usr/bin/env python3
"""Bootstrap the full NIFTY 500 universe from Yahoo Finance.

Run from the project root:

    python backend/scripts/bootstrap_nifty500.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.database import get_session_factory, init_db
from app.core.storage_paths import ensure_storage_directories
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.market_data.services.universe_bootstrap_engine import format_progress, format_summary
from app.market_data.universe import Nifty500Universe


def main() -> int:
    """Bootstrap all NIFTY 500 symbols using the real YFinanceProvider."""
    settings = get_settings()

    print("=" * 60)
    print("TradeLab — NIFTY 500 Universe Bootstrap")
    print("=" * 60)
    print(f"Metadata DB:         {settings.metadata_db_path}")
    print(f"Parquet directory:   {settings.parquet_storage_dir}")
    print(f"Rate limit delay:    {settings.bootstrap_rate_limit_seconds}s")
    print(f"Max retries:         {settings.bootstrap_max_retries}")
    print(f"Validation report:   {Path(settings.log_directory) / 'universe_validation_report.json'}")
    print()

    ensure_storage_directories(settings)
    init_db(settings)

    universe = Nifty500Universe()
    print(f"Local CSV:           {universe._symbols_file}")
    print(f"Universe size:       {universe.get_count()} symbols")
    print()
    print("Validating Yahoo Finance tickers...")
    print()

    session = get_session_factory()()
    try:
        gateway = MarketDataGateway(session, settings=settings)

        def on_progress(progress) -> None:
            print(format_progress(progress), flush=True)

        summary = gateway.bootstrap_universe(universe, progress_callback=on_progress)
        report = universe.get_validation_report()

        print()
        print(format_summary(summary))
        if report is not None:
            print("Validation Statistics")
            print("-" * 60)
            print(f"Universe size:       {report.universe_size}")
            print(f"Mapped symbols:      {len(report.renamed_symbols)}")
            print(f"Valid symbols:       {len(report.valid_symbols)}")
            print(f"Downloaded:          {summary.downloaded}")
            print(f"Skipped:             {summary.skipped}")
            print(f"Delisted:            {len(report.delisted_symbols)}")
            print(f"Network failures:    {len(report.network_errors)}")
            print(f"Invalid format:      {len(report.invalid_format_symbols)}")
            print()

        if summary.failed > 0:
            print("Bootstrap completed with failures.")
            return 1

        print("NIFTY 500 bootstrap completed successfully.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
