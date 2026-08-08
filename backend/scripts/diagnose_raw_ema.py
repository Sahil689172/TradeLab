#!/usr/bin/env python3
"""A4Y.1.7.1 — Diagnose Raw EMA after canonical Feature Engine preparation.

Does not modify strategy logic. Loads OHLCV, attaches missing indicators via
``ensure_strategy_indicators`` (compute_trend_features / volume / ATR / RSI),
then runs the existing RAW EMA strategy.
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
from app.backtesting.evaluation.canonical import load_canonical_features
from app.backtesting.evaluation.runner import synthetic_features
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
        frame = load_canonical_features(symbol, storage_dir)
        if frame is None:
            print(f"ERROR: no OHLCV/features for {symbol} under {storage_dir}")
            return 2
        source = "parquet+ensure_strategy_indicators"

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
    payload["stride"] = args.stride
    payload["crossover_definition"] = {
        "cross_above": "prev ema20<=ema50 AND curr ema20>ema50",
        "cross_below": "prev ema20>=ema50 AND curr ema20<ema50",
        "source": "app.conditions.operators (existing strategy semantics)",
    }
    print(json.dumps(payload, indent=2))
    print()
    print("Interpretation:")
    if diag.bars_examined <= 0:
        print("  FAIL: bars_examined=0 — feature preparation still broken.")
        return 1
    if diag.buy_count == 0 and diag.cross_above_count == 0:
        print(
            "  REAL ZERO BUYs: no ema20/ema50 cross-above events after warmup "
            "(pipeline OK; strategy genuinely idle on entries).",
        )
    elif diag.buy_count == 0:
        print(
            "  REAL ZERO BUYs: crosses exist but ADX/close>slow gates block BUY "
            f"(blocked_adx={diag.blocked_adx}, "
            f"blocked_close={diag.blocked_close_above_slow}, "
            f"blocked_both={diag.blocked_both}).",
        )
    else:
        print(
            f"  Raw BUY signals exist ({diag.buy_count}); "
            f"reconstructed trades={diag.trade_count}.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
