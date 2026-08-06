#!/usr/bin/env python3
"""Validate Professional EMA on a universe (Phase A4Y.1).

Default symbols: RELIANCE, TCS, HDFCBANK, ADANIPORTS
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.audit import StrategyAuditor, export_audit, format_audit_report
from app.strategy_engine.symbols import attach_symbol


DEFAULT_SYMBOLS = ("RELIANCE", "TCS", "HDFCBANK", "ADANIPORTS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Professional EMA universe")
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="Override symbols (repeatable)",
    )
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--mode", choices=("raw", "professional", "both"), default="both")
    parser.add_argument("--out-dir", default="backend/data/audit")
    parser.add_argument("--stride", type=int, default=12)
    parser.add_argument("--max-evaluations", type=int, default=25)
    return parser.parse_args()


def synthetic_features(*, bars: int = 160, symbol: str = "RELIANCE") -> pd.DataFrame:
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
        price = price + (0.45 if index % 8 else -0.25)
        close = price
        ema9 = close * (0.998 if index < bars - 2 else (0.997 if index == bars - 2 else 1.001))
        ema21 = close * 0.999
        if index == bars - 1:
            ema9 = close * 1.002
            ema21 = close * 0.999
        rows.append(
            {
                "date": ts,
                "open": close - 0.1,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 120_000 + index * 800,
                "volume_sma_20": 100_000,
                "relative_volume_20": 1.4,
                "atr_14": 1.5,
                "ema_9": ema9,
                "ema_20": close * 1.001,
                "ema_21": ema21,
                "ema_50": close * 0.997,
                "ema_200": close * 0.95,
                "adx_14": 28.0,
                "rsi_14": 55.0,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def load_features(symbol: str, storage_dir: Path) -> pd.DataFrame | None:
    from app.feature_engine.strategy_frame import (
        features_include_ohlcv,
        load_strategy_features,
    )

    frame = load_strategy_features(symbol, storage_dir)
    if frame is None or not features_include_ohlcv(frame):
        return None
    return attach_symbol(frame, symbol)


def run_one(mode: str, features: pd.DataFrame, symbol: str, args: argparse.Namespace):
    if mode == "professional":
        strategy = EMATrendStrategy(EMATrendConfig.professional(symbol=symbol))
    else:
        strategy = EMATrendStrategy(EMATrendConfig(mode="raw", symbol=symbol))
    auditor = StrategyAuditor(
        min_bars=60,
        stride=args.stride,
        max_evaluations=args.max_evaluations,
        apply_filters=False,
    )
    metrics = auditor.audit_one(strategy, features, symbol=symbol)
    report = auditor.build_report(
        [metrics],
        symbol=symbol,
        metadata={"mode": mode, "phase": "A4Y.1"},
    )
    return metrics, report


def main() -> int:
    args = parse_args()
    symbols = [s.strip().upper() for s in (args.symbols or list(DEFAULT_SYMBOLS))]
    modes = ("raw", "professional") if args.mode == "both" else (args.mode,)
    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("TradeLab — Professional EMA Validation (A4Y.1)")
    print("=" * 64)
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Modes:   {', '.join(modes)}")

    universe: list[dict] = []
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
        print(f"\n=== {symbol} ({source}, {len(features)} bars) ===")
        for mode in modes:
            metrics, report = run_one(mode, features, symbol, args)
            print(f"\n-- {mode.upper()} --")
            print(format_audit_report(report))
            json_path = out_dir / f"{symbol}_ema_{mode}_validation.json"
            csv_path = out_dir / f"{symbol}_ema_{mode}_validation.csv"
            export_audit(report, json_path=json_path, csv_path=csv_path)
            print(f"Exported {json_path}")
            universe.append(
                {
                    "symbol": symbol,
                    "mode": mode,
                    "source": source,
                    "evaluations": metrics.evaluations,
                    "buy": metrics.buy_signals,
                    "sell": metrics.sell_signals,
                    "hold": metrics.hold_signals,
                    "ready": metrics.ready,
                    "funnel_acceptance_rate": metrics.funnel_acceptance_rate,
                    "funnel_rejection_rate": metrics.funnel_rejection_rate,
                },
            )

    summary = out_dir / "ema_professional_universe_report.json"
    summary.write_text(json.dumps({"phase": "A4Y.1", "rows": universe}, indent=2), encoding="utf-8")
    print(f"\nUniverse report: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
