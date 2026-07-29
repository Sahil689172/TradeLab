#!/usr/bin/env python3
"""Generate cached technical features from locally stored OHLCV data.

Run from the project root:

    python backend/scripts/generate_features.py --symbol RELIANCE
    python backend/scripts/generate_features.py --all
    python backend/scripts/generate_features.py --symbol RELIANCE.NS --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.database import get_session_factory, init_db
from app.core.storage_paths import ensure_storage_directories
from app.feature_engine import FeatureEngine, FeatureRepository
from app.feature_engine.cache import FeatureCache
from app.market_data.services.market_data_gateway import MarketDataGateway


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate OHLCV technical features")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--symbol", help="NSE symbol, e.g. RELIANCE or RELIANCE.NS")
    selection.add_argument("--all", action="store_true", help="Process all raw Parquet files")
    parser.add_argument("--force", action="store_true", help="Ignore cache and rebuild")
    return parser.parse_args()


def discover_symbols(storage_dir: Path) -> list[str]:
    """Return symbols represented by raw Parquet files."""
    return sorted(
        path.stem
        for path in storage_dir.glob("*.parquet")
        if not path.stem.endswith("_features")
    )


def main() -> int:
    args = parse_args()
    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)

    print("=" * 60)
    print("TradeLab — Feature Generation")
    print("=" * 60)
    print(f"Metadata DB:       {settings.metadata_db_path}")
    print(f"OHLCV directory:   {storage_dir}")
    print()

    ensure_storage_directories(settings)
    init_db(settings)

    symbols = discover_symbols(storage_dir) if args.all else [args.symbol.strip().upper()]
    if not symbols:
        print(f"No raw Parquet files found in {storage_dir}")
        return 1

    session = get_session_factory()()
    failed = 0
    try:
        gateway = MarketDataGateway(session, settings=settings)
        engine = FeatureEngine(
            gateway,
            FeatureRepository(storage_dir),
            FeatureCache(storage_dir),
        )
        for index, symbol in enumerate(symbols, start=1):
            try:
                result = engine.generate(symbol, force=args.force)
                print(
                    f"[{index}/{len(symbols)}] {result.symbol}: {result.status} "
                    f"rows={result.feature_rows} added={result.rows_added} "
                    f"path={result.feature_path}",
                    flush=True,
                )
            except Exception as exc:
                failed += 1
                print(f"[{index}/{len(symbols)}] {symbol}: FAILED — {exc}", flush=True)
    finally:
        session.close()

    print(
        f"Completed: total={len(symbols)} succeeded={len(symbols) - failed} failed={failed}",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
