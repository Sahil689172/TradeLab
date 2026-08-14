#!/usr/bin/env python3
"""Compare RAW vs PROFESSIONAL EMA using the canonical evaluation path (A4Y.1.7.2).

Uses the same feature prep + backtester as evaluate_ema_professional.py and the
same raw diagnostic as diagnose_raw_ema.py. Does NOT use the truncated
StrategyAuditor last-N-window walk (that path disagreed with the evaluator).

Examples:

    python backend/scripts/compare_ema_modes.py --symbol RELIANCE
    python backend/scripts/compare_ema_modes.py --symbol RELIANCE --stride 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.evaluation.canonical import (
    compare_ema_modes_canonical,
    load_canonical_features,
)
from app.backtesting.evaluation.funnel_semantics import format_semantic_funnel
from app.backtesting.evaluation.runner import synthetic_features
from app.core.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare RAW vs PROFESSIONAL EMA (canonical evaluation path)",
    )
    parser.add_argument("--symbol", action="append", dest="symbols", help="Symbol(s)")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Bar stride (default 1 = FULL_BACKTEST, same as evaluate --full)",
    )
    parser.add_argument("--min-history-bars", type=int, default=60)
    parser.add_argument("--out-dir", default="backend/data/audit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = [s.strip().upper() for s in (args.symbols or ["RELIANCE"])]
    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    comparison_rows: list[dict] = []

    print("=" * 64)
    print("TradeLab — RAW vs PROFESSIONAL EMA Comparison (A4Y.1.7.2)")
    print("Canonical path: diagnose + long-only backtester (not auditor sample)")
    print("=" * 64)

    for symbol in symbols:
        if args.synthetic:
            features = synthetic_features(symbol=symbol, bars=260)
            source = "synthetic"
        else:
            features = load_canonical_features(symbol, storage_dir)
            if features is None:
                features = synthetic_features(symbol=symbol, bars=260)
                source = "synthetic (no parquet)"
            else:
                source = "parquet+ensure_strategy_indicators"

        result = compare_ema_modes_canonical(
            symbol,
            features,
            stride=args.stride,
            min_history_bars=args.min_history_bars,
        )
        diag = result.raw_diagnostic
        raw = result.raw
        pro = result.professional

        print(f"\n--- {symbol} ({source}, {result.bars_in_frame} bars) ---")
        print(
            f"Resolution: {result.evaluation_resolution} | stride={result.stride}",
        )
        if result.semantic_funnel is not None:
            print()
            print(format_semantic_funnel(result.semantic_funnel))
        else:
            print("\n[TECHNICAL CROSSOVERS]")
            print(
                f"  cross_above={diag.cross_above_count} "
                f"cross_below={diag.cross_below_count}",
            )
            print("\n[RAW STRATEGY SIGNALS]")
            print(
                f"  BUY={diag.buy_count} SELL={diag.sell_count} "
                f"HOLD={diag.hold_count} EXIT={diag.exit_count}",
            )
            print("\n[COMPLETED TRADES]")
            print(
                f"  raw={raw.trade_count} professional={pro.trade_count}",
            )

        path = out_dir / f"{symbol}_ema_canonical_comparison.json"
        path.write_text(json.dumps(result.as_dict(), indent=2), encoding="utf-8")
        print(f"  Wrote {path}")

        comparison_rows.append(
            {
                "symbol": symbol,
                "source": source,
                "evaluation_resolution": result.evaluation_resolution,
                "stride": result.stride,
                "bars_in_frame": result.bars_in_frame,
                "cross_above": diag.cross_above_count,
                "cross_below": diag.cross_below_count,
                "raw_strategy_buy_signals": diag.buy_count,
                "raw_strategy_exit_signals": diag.exit_count,
                "raw_completed_trades": raw.trade_count,
                "professional_buy_candidates": (
                    result.semantic_funnel.professional_buy_candidates
                    if result.semantic_funnel is not None
                    else None
                ),
                "professional_buy_signals": pro.buy_signals,
                "professional_completed_trades": pro.trade_count,
                "professional_buy_candidate_reduction_pct": (
                    result.semantic_funnel.professional_buy_candidate_reduction_pct
                    if result.semantic_funnel is not None
                    else None
                ),
                "funnel_mode": (
                    result.semantic_funnel.funnel_mode
                    if result.semantic_funnel is not None
                    else None
                ),
            },
        )

    summary_path = out_dir / "ema_raw_vs_professional_comparison.json"
    summary_path.write_text(json.dumps(comparison_rows, indent=2), encoding="utf-8")
    print(f"\nComparison summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
