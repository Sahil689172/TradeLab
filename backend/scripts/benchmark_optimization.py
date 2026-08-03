#!/usr/bin/env python3
"""Compare saved performance profiles (before vs after optimization).

Does NOT run universe validation. Point it at two profile JSON files produced
by ``profile_validation.py``.

Workflow:

    # 1. Capture baseline
    python backend/scripts/profile_validation.py --limit 20 --workers 1 --label before

    # 2. Apply optimizations (code changes)

    # 3. Capture after
    python backend/scripts/profile_validation.py --limit 20 --workers 1 --label after

    # 4. Compare
    python backend/scripts/benchmark_optimization.py
    python backend/scripts/benchmark_optimization.py \\
        --before backend/data/logs/performance_profile_before.json \\
        --after  backend/data/logs/performance_profile_after.json

Outputs:

    backend/data/logs/optimization_report.json
    backend/data/logs/optimization_report.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.services.profiling.compare import (
    compare_profiles,
    load_profile_report,
    write_comparison_reports,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    default_dir = Path(settings.log_directory)
    parser = argparse.ArgumentParser(
        description=(
            "Compare two saved performance_profile JSON reports "
            "(does not re-run validation)"
        ),
    )
    parser.add_argument(
        "--before",
        type=Path,
        default=default_dir / "performance_profile_before.json",
        help="Baseline profile JSON (default: .../performance_profile_before.json)",
    )
    parser.add_argument(
        "--after",
        type=Path,
        default=default_dir / "performance_profile_after.json",
        help="Optimized profile JSON (default: .../performance_profile_after.json)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for optimization_report.json (default: settings.log_directory)",
    )
    parser.add_argument(
        "--json-filename",
        default="optimization_report.json",
        help="Output JSON filename",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    output_dir = Path(args.output_dir) if args.output_dir else Path(settings.log_directory)

    before_path = Path(args.before)
    after_path = Path(args.after)

    print("=" * 72)
    print("TradeLab — Optimization Report (profile comparison)")
    print("=" * 72)
    print(f"Before: {before_path}")
    print(f"After:  {after_path}")
    print()

    if not before_path.exists():
        print(f"ERROR: before report not found: {before_path}", file=sys.stderr)
        print(
            "Run: python backend/scripts/profile_validation.py --label before ...",
            file=sys.stderr,
        )
        return 1
    if not after_path.exists():
        print(f"ERROR: after report not found: {after_path}", file=sys.stderr)
        print(
            "Run: python backend/scripts/profile_validation.py --label after ...",
            file=sys.stderr,
        )
        return 1

    before = load_profile_report(before_path)
    after = load_profile_report(after_path)
    report = compare_profiles(
        before,
        after,
        before_path=str(before_path),
        after_path=str(after_path),
    )
    json_path, console_text = write_comparison_reports(
        report,
        output_dir,
        json_filename=args.json_filename,
    )
    print(console_text)
    print()
    print(f"JSON: {json_path}")
    print(f"TXT:  {output_dir / 'optimization_report.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
