#!/usr/bin/env python3
"""Validate all TradeLab strategies across the OHLCV universe (NIFTY500).

Not a backtest — no PnL. Verifies that every strategy executes and produces a
valid TradeRecommendation for every available source OHLCV symbol.

Run from the project root:

    python backend/scripts/validate_universe.py
    python backend/scripts/validate_universe.py --symbol RELIANCE --strategy all
    python backend/scripts/validate_universe.py --symbol TCS --strategy ema_trend
    python backend/scripts/validate_universe.py --limit 10 --workers 4

Reports are written to backend/data/logs/:

    universe_validation.json
    universe_validation.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.services.trade_recommendation import known_strategy_aliases
from app.services.universe_validation import (
    UniverseValidationConfig,
    UniverseValidationEngine,
    format_console_summary,
    write_reports,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    aliases = ", ".join(sorted(set(known_strategy_aliases())))
    parser = argparse.ArgumentParser(
        description=(
            "Universe strategy validation — execute every strategy on every "
            "OHLCV symbol and validate TradeRecommendation contracts"
        ),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="Symbol (repeatable) or 'all' to use every OHLCV parquet (default: all)",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help=f"Strategy alias (repeatable) or 'all' (default: all). Known: {aliases}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of symbols after discovery / sorting",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="ThreadPoolExecutor workers for parallel per-symbol validation",
    )
    parser.add_argument(
        "--timeframe",
        default="15 Minute",
        help="Timeframe label stamped on recommendations",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Report directory (default: settings.log_directory)",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="OHLCV parquet directory (default: settings.parquet_storage_dir)",
    )
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Fall back to synthetic features when parquet is missing (tests/dev)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    storage_dir = Path(args.storage_dir) if args.storage_dir else Path(settings.parquet_storage_dir)
    output_dir = Path(args.output_dir) if args.output_dir else Path(settings.log_directory)

    config = UniverseValidationConfig(
        storage_dir=storage_dir,
        output_dir=output_dir,
        timeframe=args.timeframe,
        workers=max(1, args.workers),
        limit=args.limit,
        allow_synthetic=bool(args.allow_synthetic),
    )
    engine = UniverseValidationEngine(config)

    strategy_names = args.strategies or ["all"]
    symbols = args.symbols  # None → discover all OHLCV

    print("=" * 72)
    print("TradeLab — Universe Strategy Validation")
    print("=" * 72)
    print(f"Storage:    {storage_dir}")
    print(f"Output:     {output_dir}")
    print(f"Strategies: {', '.join(strategy_names)}")
    print(f"Symbols:    {', '.join(symbols) if symbols else 'all (OHLCV discovery)'}")
    print(f"Limit:      {args.limit or 'none'}")
    print(f"Workers:    {config.workers}")
    print()

    try:
        report = engine.validate(symbols=symbols, strategy_names=strategy_names)
    except KeyError as exc:
        print(f"ERROR: {exc}")
        return 2

    print(format_console_summary(report))
    print()

    json_path, csv_path = write_reports(
        report,
        output_dir,
        json_filename=config.json_filename,
        csv_filename=config.csv_filename,
    )
    print(f"JSON report: {json_path}")
    print(f"CSV report:  {csv_path}")

    if report.total_cells == 0:
        print("WARNING: no symbols discovered — nothing validated")
        return 2
    if report.total_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
