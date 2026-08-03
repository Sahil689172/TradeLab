#!/usr/bin/env python3
"""Profile universe validation — measure where runtime is spent.

Does not optimize or change strategy / recommendation logic.

Run from the project root:

    python backend/scripts/profile_validation.py --limit 20 --workers 1
    python backend/scripts/profile_validation.py --limit 20 --workers 1 --label before
    python backend/scripts/profile_validation.py --limit 20 --workers 1 --label after

Then compare saved reports (no second automatic run):

    python backend/scripts/benchmark_optimization.py

Reports:

    backend/data/logs/performance_profile.json
    backend/data/logs/performance_profile_<label>.json  (when --label is set)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.services.profiling import ValidationProfiler, write_performance_reports
from app.services.trade_recommendation import known_strategy_aliases
from app.services.universe_validation import UniverseValidationConfig


def _safe_label(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", raw.strip())
    return cleaned.strip("_") or "run"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    aliases = ", ".join(sorted(set(known_strategy_aliases())))
    parser = argparse.ArgumentParser(
        description=(
            "Performance profile for universe strategy validation "
            "(measurement only — no optimization)"
        ),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="Symbol (repeatable) or omit for full OHLCV discovery",
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
        default=1,
        help="ThreadPoolExecutor workers (default 1 for additive timings)",
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
    parser.add_argument(
        "--label",
        default=None,
        help=(
            "Optional tag written into the JSON filename "
            "(e.g. before → performance_profile_before.json)"
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable [n/total] progress lines",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    storage_dir = (
        Path(args.storage_dir) if args.storage_dir else Path(settings.parquet_storage_dir)
    )
    output_dir = (
        Path(args.output_dir) if args.output_dir else Path(settings.log_directory)
    )

    if args.label:
        tag = _safe_label(args.label)
        json_filename = f"performance_profile_{tag}.json"
        csv_filename = f"performance_profile_{tag}.csv"
    else:
        json_filename = "performance_profile.json"
        csv_filename = "performance_profile.csv"

    config = UniverseValidationConfig(
        storage_dir=storage_dir,
        output_dir=output_dir,
        timeframe=args.timeframe,
        workers=max(1, args.workers),
        limit=args.limit,
        allow_synthetic=bool(args.allow_synthetic),
        json_filename=json_filename,
        csv_filename=csv_filename,
    )
    profiler = ValidationProfiler(config, show_progress=not args.no_progress)

    strategy_names = args.strategies or ["all"]
    symbols = args.symbols

    print("=" * 72)
    print("TradeLab — Performance Profiling (measurement only)")
    print("=" * 72)
    print(f"Storage:    {storage_dir}")
    print(f"Output:     {output_dir}")
    print(f"JSON file:  {json_filename}")
    print(f"Strategies: {', '.join(strategy_names)}")
    print(f"Symbols:    {', '.join(symbols) if symbols else 'all (OHLCV discovery)'}")
    print(f"Limit:      {args.limit if args.limit else 'none'}")
    print(f"Workers:    {config.workers}")
    print()

    report = profiler.profile(symbols=symbols, strategy_names=strategy_names)
    updated, json_path, csv_path, console_text = write_performance_reports(
        report,
        output_dir,
        json_filename=config.json_filename,
        csv_filename=config.csv_filename,
        collector=profiler.collector,
    )

    print()
    print(console_text)
    print()
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(
        f"Profiled {len(updated.symbols)} symbols × "
        f"{len(updated.strategies)} strategies in "
        f"{updated.wall_time_ms / 1000.0:,.1f}s wall",
    )
    if args.label in {"before", "after"}:
        print(
            "Next: python backend/scripts/benchmark_optimization.py "
            "(compares performance_profile_before.json vs "
            "performance_profile_after.json)",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
