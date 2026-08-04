#!/usr/bin/env python3
"""Historical candle replay → Strategy Engine → optional Order Execution.

A5.1 Replay + A5.2 simulated market fills. No portfolio analytics.

Run from the project root:

    python backend/scripts/replay_backtest.py --symbol RELIANCE --speed fast
    python backend/scripts/replay_backtest.py --symbol RELIANCE \\
        --start-date 2022-01-01 --end-date 2022-12-31 --speed fast --execute-orders
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.order_execution import ExecutionConfig, OrderExecutionEngine
from app.backtesting.replay_engine import (
    HistoricalReplayEngine,
    ReplayConfig,
    ReplaySpeed,
)
from app.core.config import get_settings
from app.services.trade_recommendation import known_strategy_aliases


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    aliases = ", ".join(sorted(set(known_strategy_aliases())))
    parser = argparse.ArgumentParser(
        description=(
            "Replay historical OHLCV into the Strategy Engine "
            "(optional simulated order execution)"
        ),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        required=True,
        help="Symbol to replay (repeatable)",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help=f"Strategy alias (repeatable). Default: ema_trend. Known: {aliases}",
    )
    parser.add_argument("--start-date", type=_parse_date, default=None)
    parser.add_argument("--end-date", type=_parse_date, default=None)
    parser.add_argument(
        "--speed",
        choices=["realtime", "fast"],
        default="fast",
        help="Replay pacing (default: fast)",
    )
    parser.add_argument(
        "--realtime-sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between candles when --speed realtime",
    )
    parser.add_argument(
        "--timeframe",
        default="1 Day",
        help="Timeframe label stamped on recommendations",
    )
    parser.add_argument(
        "--min-history",
        type=int,
        default=60,
        help="Minimum bars before strategy evaluation (raised to strategy requirements)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Optional cap on candles advanced per symbol (smoke tests)",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="OHLCV parquet directory (default: settings.parquet_storage_dir)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON path for ReplayResult (default: logs/replay_result.json)",
    )
    parser.add_argument(
        "--execute-orders",
        action="store_true",
        help="Run A5.2 Order Execution Engine on replay recommendations",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=1_000_000.0,
        help="Simulated starting cash (with --execute-orders)",
    )
    parser.add_argument(
        "--position-size-pct",
        type=float,
        default=0.95,
        help="Fraction of cash used per BUY (with --execute-orders)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=5.0,
        help="Slippage in basis points (with --execute-orders)",
    )
    parser.add_argument(
        "--brokerage-rate",
        type=float,
        default=0.0003,
        help="Brokerage as fraction of notional (with --execute-orders)",
    )
    parser.add_argument(
        "--trade-log",
        default=None,
        help="Trade log JSON path (default: logs/trade_log.json)",
    )
    return parser.parse_args(argv)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    storage_dir = (
        Path(args.storage_dir) if args.storage_dir else Path(settings.parquet_storage_dir)
    )
    output_path = (
        Path(args.output)
        if args.output
        else Path(settings.log_directory) / "replay_result.json"
    )
    trade_log_path = (
        Path(args.trade_log)
        if args.trade_log
        else Path(settings.log_directory) / "trade_log.json"
    )

    config = ReplayConfig(
        symbols=args.symbols,
        strategy_names=args.strategies or ["ema_trend"],
        start_date=args.start_date,
        end_date=args.end_date,
        speed=ReplaySpeed(args.speed),
        timeframe=args.timeframe,
        storage_dir=storage_dir,
        realtime_sleep_seconds=max(0.0, float(args.realtime_sleep)),
        min_history_bars=max(1, int(args.min_history)),
        max_steps=args.max_steps,
    )

    print("=" * 72)
    print("TradeLab — Historical Replay Engine (A5.1)")
    if args.execute_orders:
        print("+ Order Execution Engine (A5.2)")
    print("=" * 72)
    print(f"Storage:    {storage_dir}")
    print(f"Symbols:    {', '.join(config.symbols)}")
    print(f"Strategies: {', '.join(config.strategy_names)}")
    print(f"Start:      {config.start_date or 'beginning'}")
    print(f"End:        {config.end_date or 'latest'}")
    print(f"Speed:      {config.speed.value}")
    print()

    engine = HistoricalReplayEngine(config)
    result = engine.run()

    print(
        f"Candles advanced: {result.candles_replayed}  "
        f"Recommendations: {result.recommendations_generated}",
    )
    if result.errors:
        print(f"Errors ({len(result.errors)}):")
        for err in result.errors[:20]:
            print(f"  - {err}")

    print()
    print("--- Latest steps ---")
    for step in result.steps[-10:]:
        print(
            f"  {step.timestamp.date()} {step.symbol} {step.strategy_name}: "
            f"{step.signal.value} close={step.current_close:.4f} "
            f"conf={step.confidence:.1f} stop={step.stop_loss:.4f} "
            f"t1={step.target_1:.4f} t2={step.target_2:.4f} "
            f"hold={step.expected_holding_period}",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print()
    print(f"Replay JSON: {output_path}")

    if args.execute_orders:
        exec_config = ExecutionConfig(
            initial_capital=float(args.initial_capital),
            position_size_pct=float(args.position_size_pct),
            slippage_bps=float(args.slippage_bps),
            brokerage_rate=float(args.brokerage_rate),
        )
        execution = OrderExecutionEngine(exec_config)
        exec_result = execution.process_replay_result(result)
        account = exec_result.final_account

        print()
        print("--- Order Execution ---")
        print(f"Filled:   {exec_result.orders_filled}")
        print(f"Rejected: {exec_result.orders_rejected}")
        print(f"Cash:     {account.cash:,.2f}")
        print(f"Equity:   {account.equity:,.2f}")
        print(f"Realized: {account.realized_pnl:,.2f}")
        print(f"Unrealzd: {account.unrealized_pnl:,.2f}")
        print()
        print("--- Trade Log (latest) ---")
        for row in exec_result.trade_log[-10:]:
            print(
                f"  {row.timestamp.date()} {row.side.value} {row.symbol} "
                f"qty={row.quantity:.4f} px={row.execution_price:.4f} "
                f"brokerage={row.brokerage:.2f} slip={row.slippage:.2f} "
                f"pnl={row.pnl:.2f} cash={row.remaining_cash:,.2f}",
            )

        trade_log_path.parent.mkdir(parents=True, exist_ok=True)
        trade_log_path.write_text(
            json.dumps(exec_result.model_dump(mode="json"), indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print()
        print(f"Trade log JSON: {trade_log_path}")

    return 1 if result.errors and not result.steps else 0


if __name__ == "__main__":
    raise SystemExit(main())
