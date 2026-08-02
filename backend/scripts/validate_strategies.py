#!/usr/bin/env python3
"""Validate TradeLab strategies against the Trade Recommendation contract.

Run from the project root:

    python backend/scripts/validate_strategies.py --strategy ema --symbol RELIANCE
    python backend/scripts/validate_strategies.py --strategy all --symbol RELIANCE
    python backend/scripts/validate_strategies.py --strategy all --symbol all

When no Parquet features are available, a synthetic feature frame is used so
the recommendation/validation pipeline can still be exercised.
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
from app.services.trade_recommendation import (
    StrategyValidationFramework,
    known_strategy_aliases,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate strategies → TradeRecommendation contract",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help="Strategy alias (repeatable) or 'all'. Known: "
        + ", ".join(sorted(set(known_strategy_aliases()))),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="Symbol (repeatable) or 'all' to scan feature Parquet files",
    )
    parser.add_argument(
        "--timeframe",
        default="15 Minute",
        help="Timeframe label stamped on recommendations",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Force synthetic OHLCV/features (skip Parquet load)",
    )
    return parser.parse_args()


def discover_feature_symbols(storage_dir: Path) -> list[str]:
    return sorted(
        path.stem.replace("_features", "")
        for path in storage_dir.glob("*_features.parquet")
    )


def load_features(symbol: str, storage_dir: Path) -> pd.DataFrame | None:
    path = storage_dir / f"{symbol}_features.parquet"
    if not path.exists():
        # try without suffix naming
        alt = storage_dir / f"{symbol}.parquet"
        if alt.exists():
            return pd.read_parquet(alt)
        return None
    return pd.read_parquet(path)


def synthetic_features(*, bars: int = 80, symbol: str = "RELIANCE") -> pd.DataFrame:
    """Minimal feature frame sufficient for most strategy validators."""
    start = pd.Timestamp("2024-01-02 09:15")
    rows = []
    price = 100.0
    for index in range(bars):
        price = price + (0.4 if index % 7 else -0.2)
        close = price
        rows.append(
            {
                "date": start + pd.Timedelta(minutes=15 * index),
                "open": close - 0.1,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 1000 + index * 15,
                "relative_volume_20": 1.2 + (0.5 if index == bars - 1 else 0.0),
                "atr_14": 1.5,
                "ema_9": close * 1.001,
                "ema_20": close * 1.002,
                "ema_21": close * 1.002,
                "ema_50": close * 0.998,
                "adx_14": 28.0,
                "rsi_14": 55.0,
                "vwap": close * 0.999,
            },
        )
    frame = pd.DataFrame(rows)
    frame.attrs["symbol"] = symbol
    return frame


def main() -> int:
    args = parse_args()
    strategy_names = args.strategies or ["all"]
    symbol_args = args.symbols or ["RELIANCE"]

    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)

    if any(s.strip().lower() == "all" for s in symbol_args):
        symbols = discover_feature_symbols(storage_dir) or ["RELIANCE"]
    else:
        symbols = [s.strip().upper() for s in symbol_args]

    framework = StrategyValidationFramework(timeframe=args.timeframe)
    exit_code = 0

    print("=" * 60)
    print("TradeLab — Strategy Validation")
    print("=" * 60)
    print(f"Strategies: {', '.join(strategy_names)}")
    print(f"Symbols:    {', '.join(symbols)}")
    print()

    for symbol in symbols:
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

        print(f"--- {symbol} ({source}, {len(features)} bars) ---")
        try:
            report = framework.validate_many(
                features,
                strategy_names=strategy_names,
                symbol=symbol,
            )
        except KeyError as exc:
            print(f"ERROR: {exc}")
            return 2

        print(framework.format_report(report))
        print()
        if report.failed:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
