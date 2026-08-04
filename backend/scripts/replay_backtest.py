#!/usr/bin/env python3
"""Historical candle replay → Strategy Engine → optional Order Execution.

A5.1 Replay + A5.2 / A5.2.1 simulated market fills. No portfolio analytics.

Run from the project root:

    python backend/scripts/replay_backtest.py --symbol RELIANCE --speed fast
    python backend/scripts/replay_backtest.py --symbol RELIANCE ^
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

from app.backtesting.order_execution import (
    ExecutionConfig,
    OrderExecutionEngine,
    PositionSizingMode,
)
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
        "--position-sizing",
        choices=[m.value for m in PositionSizingMode],
        default=PositionSizingMode.PERCENT_OF_CAPITAL.value,
        help="Position sizing mode (only one active)",
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=None,
        help="Cash amount per BUY when --position-sizing fixed_amount",
    )
    parser.add_argument(
        "--quantity",
        type=float,
        default=None,
        help="Share quantity per BUY when --position-sizing fixed_quantity",
    )
    parser.add_argument(
        "--percent",
        type=float,
        default=95.0,
        help="Percent of available cash per BUY when --position-sizing percent_of_capital",
    )
    parser.add_argument(
        "--position-size-pct",
        type=float,
        default=None,
        help=argparse.SUPPRESS,  # legacy alias → percent (0–1 fraction)
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
        "--min-confidence",
        type=float,
        default=None,
        help="Reject actionable signals below this confidence (0–100)",
    )
    parser.add_argument(
        "--trade-log",
        default=None,
        help="Closed-trade log JSON path (default: logs/trade_log.json)",
    )
    parser.add_argument(
        "--rejected-orders",
        default=None,
        help="Rejected-order log JSON path (default: logs/rejected_orders.json)",
    )
    parser.add_argument(
        "--debug-orders",
        action="store_true",
        help="Print every order decision (fills and rejects)",
    )
    return parser.parse_args(argv)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _build_execution_config(args: argparse.Namespace) -> ExecutionConfig:
    mode = PositionSizingMode(args.position_sizing)
    percent = float(args.percent)
    if args.position_size_pct is not None:
        # Legacy fraction 0–1 → percent 0–100
        percent = float(args.position_size_pct) * 100.0
        mode = PositionSizingMode.PERCENT_OF_CAPITAL

    if mode is PositionSizingMode.FIXED_AMOUNT and args.amount is None:
        raise SystemExit("--position-sizing fixed_amount requires --amount")
    if mode is PositionSizingMode.FIXED_QUANTITY and args.quantity is None:
        raise SystemExit("--position-sizing fixed_quantity requires --quantity")

    return ExecutionConfig(
        initial_capital=float(args.initial_capital),
        position_sizing=mode,
        amount=float(args.amount) if args.amount is not None else None,
        quantity=float(args.quantity) if args.quantity is not None else None,
        percent=percent,
        slippage_bps=float(args.slippage_bps),
        brokerage_rate=float(args.brokerage_rate),
        allow_fractional_shares=False,
        min_confidence=float(args.min_confidence) if args.min_confidence is not None else None,
        close_open_at_replay_end=True,
    )


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
    rejected_path = (
        Path(args.rejected_orders)
        if args.rejected_orders
        else Path(settings.log_directory) / "rejected_orders.json"
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
        print("+ Order Execution Engine (A5.2.1)")
    print("=" * 72)
    print(f"Storage:    {storage_dir}")
    print(f"Symbols:    {', '.join(config.symbols)}")
    print(f"Strategies: {', '.join(config.strategy_names)}")
    print(f"Start:      {config.start_date or 'beginning'}")
    print(f"End:        {config.end_date or 'latest'}")
    print(f"Speed:      {config.speed.value}")
    if args.execute_orders:
        print(f"Capital:    ₹{float(args.initial_capital):,.2f}")
        print(f"Sizing:     {args.position_sizing}")
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
        exec_config = _build_execution_config(args)
        execution = OrderExecutionEngine(
            exec_config,
            debug=bool(args.debug_orders),
        )
        exec_result = execution.process_replay_result(result)
        summary = exec_result.summary

        print()
        print("--- Order Execution Summary ---")
        print(f"Orders Attempted:  {summary.orders_attempted}")
        print(f"Orders Filled:     {summary.orders_filled}")
        print(f"Orders Rejected:   {summary.orders_rejected}")
        print(f"Win Trades:        {summary.win_trades}")
        print(f"Loss Trades:       {summary.loss_trades}")
        print(f"Open Positions:    {summary.open_positions}")
        print(f"Closed Positions:  {summary.closed_positions}")
        print(f"Current Cash:      ₹{summary.current_cash:,.2f}")
        print(f"Current Equity:    ₹{summary.current_equity:,.2f}")
        print(f"Largest Position:  ₹{summary.largest_position:,.2f}")
        print(f"Largest Profit:    ₹{summary.largest_profit:,.2f}")
        print(f"Largest Loss:      ₹{summary.largest_loss:,.2f}")

        print()
        print("--- Closed Trades (latest) ---")
        for row in exec_result.trade_log[-10:]:
            print(
                f"  {row.entry_timestamp.date()}→{row.exit_timestamp.date()} "
                f"{row.symbol} qty={row.quantity:g} "
                f"entry={row.entry_price:.4f} exit={row.exit_price:.4f} "
                f"net={row.net_profit:,.2f} days={row.holding_days} "
                f"reason={row.exit_reason.value}",
            )

        if exec_result.rejected_orders:
            print()
            print("--- Rejected Orders (latest) ---")
            for row in exec_result.rejected_orders[-10:]:
                side = row.side.value if row.side else "N/A"
                px = f"{row.requested_price:.4f}" if row.requested_price else "n/a"
                print(
                    f"  {row.timestamp.date()} {side} {row.symbol} "
                    f"px={px} reason={row.reason}",
                )

        trade_payload = {
            "summary": exec_result.summary.model_dump(mode="json"),
            "config": exec_result.config.model_dump(mode="json"),
            "trade_log": [t.model_dump(mode="json") for t in exec_result.trade_log],
            "fill_log": [f.model_dump(mode="json") for f in exec_result.fill_log],
            "final_account": exec_result.final_account.model_dump(mode="json"),
            "orders_filled": exec_result.orders_filled,
            "orders_rejected": exec_result.orders_rejected,
            "started_at": exec_result.started_at.isoformat(),
            "completed_at": exec_result.completed_at.isoformat(),
        }
        rejected_payload = {
            "count": len(exec_result.rejected_orders),
            "rejected_orders": [
                r.model_dump(mode="json") for r in exec_result.rejected_orders
            ],
        }

        trade_log_path.parent.mkdir(parents=True, exist_ok=True)
        trade_log_path.write_text(
            json.dumps(trade_payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        rejected_path.parent.mkdir(parents=True, exist_ok=True)
        rejected_path.write_text(
            json.dumps(rejected_payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print()
        print(f"Trade log JSON:      {trade_log_path}")
        print(f"Rejected orders JSON: {rejected_path}")

    return 1 if result.errors and not result.steps else 0


if __name__ == "__main__":
    raise SystemExit(main())
