#!/usr/bin/env python3
"""A5.6 Monte Carlo robustness analysis on completed historical trades.

    python backend/scripts/monte_carlo.py --symbol RELIANCE --strategy ema_trend ^
        --simulations 10000 --method bootstrap --initial-capital 1000000 --seed 42

    python backend/scripts/monte_carlo.py --trades-json logs\\trade_log.json --method shuffle --seed 42

    python backend/scripts/monte_carlo.py --synthetic-trades 100 --simulations 10000 --seed 42 --benchmark
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from app.backtesting.monte_carlo import (
    CapitalMode,
    MonteCarloConfig,
    MonteCarloEngine,
    SamplingMethod,
    format_console_report,
    load_trades_from_json,
    load_trades_from_replay,
    make_synthetic_trades,
    write_outputs,
)
from app.core.config import get_settings
from app.services.trade_recommendation import known_strategy_aliases


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    aliases = ", ".join(sorted(set(known_strategy_aliases())))
    parser = argparse.ArgumentParser(
        description="Monte Carlo robustness on completed A5.2 trades (not a forecast)",
    )
    parser.add_argument("--symbol", action="append", dest="symbols", help="Symbol (repeatable)")
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help=f"Strategy alias (repeatable). Default: ema_trend. Known: {aliases}",
    )
    parser.add_argument("--trades-json", default=None, help="Existing trade_log.json (skip replay)")
    parser.add_argument(
        "--synthetic-trades",
        type=int,
        default=None,
        help="Generate N deterministic synthetic completed trades (skip replay)",
    )
    parser.add_argument("--synthetic-seed", type=int, default=1)
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument(
        "--method",
        choices=[m.value for m in SamplingMethod],
        default=SamplingMethod.BOOTSTRAP.value,
    )
    parser.add_argument(
        "--capital-mode",
        choices=[m.value for m in CapitalMode],
        default=CapitalMode.ADDITIVE_PNL.value,
    )
    parser.add_argument("--block-size", type=int, default=5)
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ruin-threshold", type=float, default=0.5)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--brokerage-rate", type=float, default=0.0003)
    parser.add_argument("--percent", type=float, default=95.0)
    parser.add_argument(
        "--cost-sensitivity",
        action="store_true",
        help="Re-run on copies with alternate slippage (does not change the historical backtest)",
    )
    parser.add_argument("--start-date", type=_parse_date, default=None)
    parser.add_argument("--end-date", type=_parse_date, default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--min-history", type=int, default=60)
    parser.add_argument("--storage-dir", default=None)
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Print elapsed seconds (and RSS if psutil is installed)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: backend/data/monte_carlo)",
    )
    return parser.parse_args(argv)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _rss_mb() -> float | None:
    try:
        import psutil

        return float(psutil.Process().memory_info().rss) / 1_000_000.0
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.symbols and not args.trades_json and not args.synthetic_trades:
        print("Provide --symbol, --trades-json, or --synthetic-trades", file=sys.stderr)
        return 2

    settings = get_settings()
    strategies = args.strategies or ["ema_trend"]
    symbols = [s.strip().upper() for s in (args.symbols or [])]
    storage = Path(args.storage_dir) if args.storage_dir else Path(settings.parquet_storage_dir)
    out_dir = Path(args.output) if args.output else Path("backend/data/monte_carlo")

    meta: dict = {}
    period = ""
    if args.synthetic_trades:
        trades = make_synthetic_trades(int(args.synthetic_trades), seed=int(args.synthetic_seed))
        symbols = symbols or ["SYNTHETIC"]
        period = f"synthetic:{args.synthetic_trades}"
    elif args.trades_json:
        trades = load_trades_from_json(Path(args.trades_json))
        if trades:
            symbols = symbols or sorted({t.symbol for t in trades if t.symbol})
    else:
        trades, meta = load_trades_from_replay(
            symbols=symbols,
            strategy_names=strategies,
            initial_capital=float(args.initial_capital),
            storage_dir=storage,
            start_date=args.start_date,
            end_date=args.end_date,
            max_steps=args.max_steps,
            slippage_bps=float(args.slippage_bps),
            brokerage_rate=float(args.brokerage_rate),
            percent=float(args.percent),
            min_history_bars=max(1, int(args.min_history)),
        )
        period = str(meta.get("period") or "")

    try:
        config = MonteCarloConfig(
            simulations=int(args.simulations),
            initial_capital=float(args.initial_capital),
            random_seed=int(args.seed),
            sampling_method=SamplingMethod(args.method),
            capital_mode=CapitalMode(args.capital_mode),
            block_size=int(args.block_size),
            include_cost_perturbation=bool(args.cost_sensitivity),
            base_slippage_bps=float(args.slippage_bps),
            ruin_threshold=float(args.ruin_threshold),
        )
    except (ValidationError, ValueError) as exc:
        print(f"Invalid Monte Carlo configuration: {exc}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    rss_before = _rss_mb() if args.benchmark else None
    engine = MonteCarloEngine(config)
    result = engine.run(
        trades,
        strategy=",".join(strategies),
        symbol=",".join(symbols) if symbols else "n/a",
        period=period,
    )
    elapsed = time.perf_counter() - started

    print(format_console_report(result))
    if args.benchmark:
        rss_after = _rss_mb()
        print("------------------------------------------------")
        print("BENCHMARK")
        print(f"elapsed_seconds: {elapsed:.4f}")
        print(f"simulations: {result.simulations}")
        print(f"historical_trades: {result.source_trade_count}")
        if rss_before is not None and rss_after is not None:
            print(f"rss_mb_before: {rss_before:.1f}")
            print(f"rss_mb_after: {rss_after:.1f}")
        else:
            print("rss_mb: n/a (install psutil for process RSS)")
    stem = f"{(symbols[0] if symbols else 'TRADES')}_{strategies[0]}"
    paths = write_outputs(result, output_dir=out_dir, stem=stem)
    print("Wrote:")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    if meta.get("replay_errors"):
        print(f"Replay errors: {meta['replay_errors'][:5]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
