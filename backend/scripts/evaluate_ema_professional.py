#!/usr/bin/env python3
"""Phase A4Y.1.5 — Professional EMA Evaluation & Statistical Validation.

Examples:

    python backend/scripts/evaluate_ema_professional.py --symbol RELIANCE --synthetic
    python backend/scripts/evaluate_ema_professional.py --symbol RELIANCE --symbol TCS --symbol HDFCBANK --symbol ADANIPORTS --synthetic
    python backend/scripts/evaluate_ema_professional.py --limit 50 --synthetic
    python backend/scripts/evaluate_ema_professional.py --limit 100 --synthetic
    python backend/scripts/evaluate_ema_professional.py --all --synthetic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.evaluation import (
    EMAEvaluationEngine,
    EvaluationConfig,
    format_report,
    synthetic_features,
)
from app.backtesting.evaluation.integrity import CapitalAllocationMode
from app.core.config import get_settings
from app.services.universe_validation.discovery import (
    discover_ohlcv_symbols,
    resolve_universe_symbols,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Raw vs Professional EMA (A4Y.1.5)",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="Symbol(s) to evaluate (repeatable)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate first N symbols from universe",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate complete OHLCV universe",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic feature frames (no parquet required)",
    )
    parser.add_argument(
        "--out-dir",
        default="backend/data/evaluation",
        help="Output directory for reports/charts",
    )
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--percent", type=float, default=95.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--brokerage-rate", type=float, default=0.0003)
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Bar stride. stride>1 is FAST_SAMPLED_EVALUATION (not a full backtest).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force FULL_BACKTEST (stride=1). Overrides auto-throttle.",
    )
    parser.add_argument(
        "--capital-mode",
        choices=["equal_weight", "per_symbol_full"],
        default="equal_weight",
        help="Multi-stock capital allocation (default equal_weight sleeves).",
    )
    parser.add_argument("--min-history-bars", type=int, default=60)
    parser.add_argument("--no-charts", action="store_true")
    return parser.parse_args()


def resolve_symbols(args: argparse.Namespace, storage_dir: Path) -> list[str]:
    if args.all:
        symbols = resolve_universe_symbols(storage_dir, symbols=["all"], limit=None)
        if not symbols and args.synthetic:
            # Deterministic synthetic universe labels
            symbols = [f"SYN{i:03d}" for i in range(1, 101)]
        return symbols
    if args.limit is not None and not args.symbols:
        discovered = discover_ohlcv_symbols(storage_dir)
        if not discovered and args.synthetic:
            discovered = [f"SYN{i:03d}" for i in range(1, max(args.limit, 1) + 1)]
        return discovered[: args.limit]
    if args.symbols:
        return resolve_universe_symbols(
            storage_dir,
            symbols=args.symbols,
            limit=args.limit,
        )
    return ["RELIANCE"]


def main() -> int:
    args = parse_args()
    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)
    symbols = resolve_symbols(args, storage_dir)
    if not symbols:
        print("ERROR: No symbols resolved. Use --synthetic or provide parquet data.")
        return 2

    stride = 1 if args.full else args.stride
    config = EvaluationConfig(
        initial_capital=args.initial_capital,
        percent=args.percent,
        slippage_bps=args.slippage_bps,
        brokerage_rate=args.brokerage_rate,
        min_history_bars=args.min_history_bars,
        stride=stride,
        out_dir=Path(args.out_dir),
        generate_charts=not args.no_charts,
        capital_mode=CapitalAllocationMode(args.capital_mode),
    )
    # Auto-throttle large universes unless --full or explicit --stride was set.
    # Sampled runs are labeled FAST_SAMPLED_EVALUATION and cannot recommend YES.
    if not args.full and args.stride == 1:
        if len(symbols) > 50:
            config.stride = 20
        elif len(symbols) > 10:
            config.stride = 10
        if config.stride != 1:
            print(
                f"Note: universe size {len(symbols)} — using stride={config.stride} "
                f"(FAST_SAMPLED_EVALUATION). Use --full for FULL_BACKTEST.",
                flush=True,
            )

    engine = EMAEvaluationEngine(config)

    frames: dict = {}
    sources: list[str] = []
    bars = 260 if len(symbols) <= 10 else 160
    print(f"Loading {len(symbols)} symbols ...", flush=True)
    for index, symbol in enumerate(symbols, start=1):
        if args.synthetic:
            frames[symbol] = synthetic_features(symbol=symbol, bars=bars)
            sources.append("synthetic")
        else:
            from app.backtesting.evaluation.canonical import load_canonical_features

            frame = load_canonical_features(symbol, storage_dir)
            if frame is None:
                frames[symbol] = synthetic_features(symbol=symbol, bars=bars)
                sources.append("synthetic-fallback")
            else:
                frames[symbol] = frame
                sources.append("parquet")
        if index == 1 or index == len(symbols) or index % 10 == 0:
            print(f"  loaded {index}/{len(symbols)}", flush=True)

    print(
        f"Evaluating {len(frames)} symbols "
        f"({', '.join(sorted(set(sources)))}, stride={config.stride})",
        flush=True,
    )
    report = engine.evaluate_universe(frames)
    print(format_report(report), flush=True)
    paths = engine.export_all(report)
    print("\nGenerated files:", flush=True)
    for key, path in sorted(paths.items()):
        print(f"  [{key}] {path}", flush=True)
    return 0 if report.professional_recommended or report.overall_improvement else 0


if __name__ == "__main__":
    raise SystemExit(main())
