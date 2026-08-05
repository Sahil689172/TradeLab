#!/usr/bin/env python3
"""Run Phase A4X.8 Strategy Audit & Comparison.

Examples:

    python backend/scripts/audit_strategies.py --symbol RELIANCE --synthetic
    python backend/scripts/audit_strategies.py --symbol RELIANCE
    python backend/scripts/audit_strategies.py --symbol RELIANCE --out-dir backend/data/audit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.strategy_engine.audit import (
    StrategyAuditor,
    export_audit,
    format_audit_report,
)
from app.strategy_engine.configuration import list_bound_strategies
from app.strategy_engine.symbols import attach_symbol


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradeLab Strategy Audit (A4X.8)")
    parser.add_argument("--symbol", default="RELIANCE", help="Symbol to audit")
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help="Strategy name (repeatable). Default: all bound strategies",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Force synthetic feature frame",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=10,
        help="Bar stride for rolling evaluations",
    )
    parser.add_argument(
        "--max-evaluations",
        type=int,
        default=25,
        help="Cap rolling evaluations per strategy",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=60,
        help="Minimum bars before first evaluation",
    )
    parser.add_argument(
        "--out-dir",
        default="backend/data/audit",
        help="Directory for JSON/CSV exports",
    )
    parser.add_argument(
        "--no-filters",
        action="store_true",
        help="Skip filter pipeline during signal audit",
    )
    return parser.parse_args()


def synthetic_features(*, bars: int = 120, symbol: str = "RELIANCE") -> pd.DataFrame:
    sessions: list[pd.Timestamp] = []
    day = pd.Timestamp("2024-06-03 09:15")
    while len(sessions) < bars:
        for minute in range(0, 6 * 60, 15):
            sessions.append(day + pd.Timedelta(minutes=minute))
            if len(sessions) >= bars:
                break
        day = day + pd.Timedelta(days=1)
        while day.weekday() >= 5:
            day = day + pd.Timedelta(days=1)

    rows = []
    price = 100.0
    for index, ts in enumerate(sessions[:bars]):
        price = price + (0.4 if index % 7 else -0.2)
        close = price
        rows.append(
            {
                "date": ts,
                "open": close - 0.1,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 100_000 + index * 1500,
                "relative_volume_20": 1.2 + (0.5 if index == bars - 1 else 0.0),
                "volume_sma_20": 90_000,
                "atr_14": 1.5,
                "ema_9": close * 1.001,
                "ema_20": close * 1.002,
                "ema_21": close * 1.002,
                "ema_50": close * 0.998,
                "ema_200": close * 0.95,
                "sma_200": close * 0.94,
                "adx_14": 28.0,
                "rsi_14": 55.0,
                "vwap": close * 0.999,
                "gap_pct": 0.5,
                "obv": 1_000_000 + index * 1000,
                "supertrend": close * 0.97,
                "supertrend_direction": 1,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def load_features(symbol: str, storage_dir: Path) -> pd.DataFrame | None:
    from app.feature_engine.strategy_frame import (
        features_include_ohlcv,
        load_strategy_features,
    )

    frame = load_strategy_features(symbol, storage_dir)
    if frame is None:
        return None
    if not features_include_ohlcv(frame):
        print(f"WARNING: {symbol} features missing OHLCV — falling back to synthetic")
        return None
    return attach_symbol(frame, symbol)


def main() -> int:
    args = parse_args()
    symbol = args.symbol.strip().upper()
    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)

    if args.synthetic:
        features = synthetic_features(symbol=symbol)
        source = "synthetic"
    else:
        features = load_features(symbol, storage_dir)
        if features is None:
            features = synthetic_features(symbol=symbol)
            source = "synthetic (no parquet)"
        else:
            source = "parquet"

    names = args.strategies
    if names and any(n.strip().lower() == "all" for n in names):
        names = None

    auditor = StrategyAuditor(
        min_bars=args.min_bars,
        stride=args.stride,
        max_evaluations=args.max_evaluations,
        apply_filters=not args.no_filters,
        enable_filter_pipeline_config=not args.no_filters,
    )

    print("=" * 64)
    print("TradeLab — Strategy Audit & Comparison (A4X.8)")
    print("=" * 64)
    print(f"Symbol:     {symbol}")
    print(f"Source:     {source} ({len(features)} bars)")
    print(f"Strategies: {', '.join(names) if names else 'all (' + str(len(list_bound_strategies())) + ')'}")
    print()

    report = auditor.run(
        features,
        symbol=symbol,
        strategy_names=names,
        metadata={"source": source, "bars": len(features)},
    )

    print(format_audit_report(report))
    print()

    out_dir = Path(args.out_dir)
    json_path = out_dir / f"{symbol}_strategy_audit.json"
    csv_path = out_dir / f"{symbol}_strategy_audit.csv"
    export_audit(report, json_path=json_path, csv_path=csv_path)
    print(f"Exported JSON: {json_path}")
    print(f"Exported CSV:  {csv_path}")

    return 0 if report.readiness.overall_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
