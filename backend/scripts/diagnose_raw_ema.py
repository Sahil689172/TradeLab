#!/usr/bin/env python3
"""A4Y.1.7 — Diagnose why Raw EMA produces zero trades.

Does not modify strategy logic. Counts crosses / BUY / EXIT / HOLD and
attributes blocked cross-above events to ADX or close>slow gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.evaluation.integrity import diagnose_raw_signals
from app.backtesting.evaluation.runner import load_symbol_features, synthetic_features
from app.core.config import get_settings
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Raw EMA signal path")
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--min-history-bars", type=int, default=60)
    parser.add_argument("--synthetic", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)
    symbol = args.symbol.strip().upper()

    if args.synthetic:
        frame = synthetic_features(symbol=symbol, bars=260)
        source = "synthetic"
    else:
        frame = load_symbol_features(symbol, storage_dir)
        if frame is None:
            print(f"ERROR: no features for {symbol}")
            return 2
        source = "parquet"

    strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol=symbol, min_history_bars=args.min_history_bars),
    )
    diag = diagnose_raw_signals(
        strategy,
        frame,
        symbol=symbol,
        min_history_bars=args.min_history_bars,
        stride=args.stride,
    )
    payload = diag.as_dict()
    payload["source"] = source
    payload["bars_in_frame"] = len(frame)
    payload["stride"] = args.stride
    print(json.dumps(payload, indent=2))
    print()
    print("Interpretation:")
    if diag.buy_count == 0 and diag.cross_above_count == 0:
        print("  A/B: No raw ema20/ema50 cross-above events → genuine zero BUYs.")
    elif diag.buy_count == 0:
        print(
            "  A: Crosses exist but ADX/close>slow gates block BUY — "
            "evaluation is detecting signals; raw strategy produces 0 trades.",
        )
    else:
        print(f"  Raw BUY signals exist ({diag.buy_count}). Check trade conversion next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
