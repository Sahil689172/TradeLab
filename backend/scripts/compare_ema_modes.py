#!/usr/bin/env python3
"""Compare RAW vs PROFESSIONAL EMA Trend (Phase A4Y.1).

Examples:

    python backend/scripts/compare_ema_modes.py --symbol RELIANCE --synthetic
    python backend/scripts/compare_ema_modes.py --symbol RELIANCE --symbol TCS
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
from app.strategy_engine.audit import StrategyAuditor, export_audit_json, format_signal_funnel
from app.strategy_engine.symbols import attach_symbol


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare RAW vs PROFESSIONAL EMA")
    parser.add_argument("--symbol", action="append", dest="symbols", help="Symbol(s)")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--stride", type=int, default=10)
    parser.add_argument("--max-evaluations", type=int, default=30)
    parser.add_argument("--min-bars", type=int, default=60)
    parser.add_argument("--out-dir", default="backend/data/audit")
    return parser.parse_args()


def synthetic_features(*, bars: int = 150, symbol: str = "RELIANCE") -> pd.DataFrame:
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
        # Inject occasional true crosses near the end
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


def audit_mode(
    *,
    mode: str,
    features: pd.DataFrame,
    symbol: str,
    stride: int,
    max_evaluations: int,
    min_bars: int,
):
    if mode == "professional":
        strategy = EMATrendStrategy(
            EMATrendConfig.professional(symbol=symbol, min_history_bars=min(min_bars, 60)),
        )
    else:
        strategy = EMATrendStrategy(
            EMATrendConfig(mode="raw", symbol=symbol, min_history_bars=min(min_bars, 60)),
        )
    auditor = StrategyAuditor(
        min_bars=min_bars,
        stride=stride,
        max_evaluations=max_evaluations,
        apply_filters=False,
        enable_filter_pipeline_config=False,
    )
    metrics = auditor.audit_one(strategy, features, symbol=symbol)
    report = auditor.build_report([metrics], symbol=symbol, metadata={"mode": mode})
    return strategy, metrics, report


def main() -> int:
    args = parse_args()
    symbols = [s.strip().upper() for s in (args.symbols or ["RELIANCE"])]
    settings = get_settings()
    storage_dir = Path(settings.parquet_storage_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    comparison_rows: list[dict] = []

    print("=" * 64)
    print("TradeLab — RAW vs PROFESSIONAL EMA Comparison (A4Y.1)")
    print("=" * 64)

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

        print(f"\n--- {symbol} ({source}, {len(features)} bars) ---")
        for mode in ("raw", "professional"):
            _strategy, metrics, report = audit_mode(
                mode=mode,
                features=features,
                symbol=symbol,
                stride=args.stride,
                max_evaluations=args.max_evaluations,
                min_bars=args.min_bars,
            )
            print(f"\n[{mode.upper()}]")
            print(
                f"  BUY={metrics.buy_signals} SELL={metrics.sell_signals} "
                f"HOLD={metrics.hold_signals} EXIT={metrics.exit_signals}",
            )
            print(
                f"  avg_conf={metrics.average_confidence:.3f} "
                f"avg_rr={metrics.average_risk_reward:.2f} "
                f"avg_hold={metrics.average_hold:.1f}",
            )
            if mode == "professional":
                print(format_signal_funnel(metrics))
            path = out_dir / f"{symbol}_ema_{mode}_audit.json"
            export_audit_json(report, path)
            print(f"  Wrote {path}")
            comparison_rows.append(
                {
                    "symbol": symbol,
                    "mode": mode,
                    "buy": metrics.buy_signals,
                    "sell": metrics.sell_signals,
                    "hold": metrics.hold_signals,
                    "exit": metrics.exit_signals,
                    "average_confidence": metrics.average_confidence,
                    "average_risk_reward": metrics.average_risk_reward,
                    "average_hold": metrics.average_hold,
                    "raw_buy": metrics.raw_buy_signals,
                    "raw_sell": metrics.raw_sell_signals,
                    "rejected_ema200": metrics.rejected_ema200,
                    "rejected_adx": metrics.rejected_adx,
                    "rejected_volume": metrics.rejected_volume,
                    "final_buy": metrics.final_buy_signals,
                    "final_sell": metrics.final_sell_signals,
                    "funnel_acceptance_rate": metrics.funnel_acceptance_rate,
                    "funnel_rejection_rate": metrics.funnel_rejection_rate,
                },
            )

    summary_path = out_dir / "ema_raw_vs_professional_comparison.json"
    summary_path.write_text(json.dumps(comparison_rows, indent=2), encoding="utf-8")
    print(f"\nComparison summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
