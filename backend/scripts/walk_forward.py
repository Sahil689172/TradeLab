#!/usr/bin/env python3
"""A5.9 / A5.10 walk-forward / out-of-sample validation.

Windows CMD examples (run from the repo root):

    .venv\\Scripts\\python.exe backend\\scripts\\walk_forward.py --symbol RELIANCE --train-years 5 --test-years 1 --step-years 1 --initial-capital 100000 --strategy ema_professional --seed 42 --no-monte-carlo --output backend\\data\\walk_forward\\reliance

    .venv\\Scripts\\python.exe backend\\scripts\\walk_forward.py --symbols RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK --train-years 5 --test-years 1 --step-years 1 --initial-capital 1000000 --strategy ema_professional --seed 42 --no-monte-carlo --output backend\\data\\walk_forward\\multi_symbol

Walk-forward does not prove future profitability.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.replay_engine.adapters import ParquetFeatureFrameAdapter, ParquetMarketDataAdapter
from app.backtesting.walk_forward import (
    CapitalMode,
    SearchSpace,
    SelectionScope,
    WalkForwardConfig,
    WalkForwardEngine,
    format_markdown_report,
    write_outputs,
)
from app.core.config import get_settings
from app.services.trade_recommendation import known_strategy_aliases
from app.services.universe_validation.discovery import resolve_universe_symbols


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    aliases = ", ".join(sorted(set(known_strategy_aliases())))
    parser = argparse.ArgumentParser(
        description="Walk-forward / out-of-sample validation (not a forecast)",
    )
    parser.add_argument("--symbol", action="append", dest="symbol_flags", help="Symbol (repeatable)")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols, e.g. RELIANCE,TCS,HDFCBANK",
    )
    parser.add_argument(
        "--symbols-file",
        default=None,
        help="Path to a file with one symbol per line or comma-separated symbols",
    )
    parser.add_argument(
        "--universe",
        action="store_true",
        help="Use every OHLCV parquet in --storage-dir",
    )
    parser.add_argument(
        "--strategy",
        default="ema_professional",
        help=f"Strategy alias (default: ema_professional). Known: {aliases}",
    )
    parser.add_argument("--train-years", type=int, default=5)
    parser.add_argument("--test-years", type=int, default=1)
    parser.add_argument("--step-years", type=int, default=1)
    parser.add_argument("--train-days", type=int, default=None)
    parser.add_argument("--test-days", type=int, default=None)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--embargo-days", type=int, default=0)
    parser.add_argument("--start-date", type=_parse_date, default=None)
    parser.add_argument("--end-date", type=_parse_date, default=None)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument(
        "--capital-mode",
        choices=[m.value for m in CapitalMode],
        default=CapitalMode.COMPOUNDED.value,
        help="compounded (default): next OOS window starts at previous OOS equity. "
        "fixed: each OOS window restarts at --initial-capital.",
    )
    parser.add_argument(
        "--selection-scope",
        choices=[s.value for s in SelectionScope],
        default=SelectionScope.PER_SYMBOL.value,
    )
    parser.add_argument("--percent", type=float, default=95.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--brokerage-rate", type=float, default=0.0003)
    parser.add_argument("--min-history", type=int, default=60)
    parser.add_argument("--min-quantity", type=float, default=1.0)
    parser.add_argument("--allow-fractional-shares", action="store_true")
    parser.add_argument("--fast", default=None, help="Comma-separated fast EMA periods, e.g. 9,12,20")
    parser.add_argument("--slow", default=None, help="Comma-separated slow EMA periods, e.g. 21,26,50")
    parser.add_argument("--adx", default="20", help="Comma-separated ADX thresholds (default: 20)")
    parser.add_argument(
        "--ema200",
        choices=["on", "off", "both"],
        default="on",
        help="Search ema200 filter: on (default), off, or both. "
        "both doubles the candidate count and runtime.",
    )
    parser.add_argument("--presets", default="9_21,12_26,20_50", help="EMA pair presets when --fast/--slow omitted")
    parser.add_argument("--max-candidates", type=int, default=24)
    parser.add_argument("--monte-carlo", action="store_true", help="Run OUT-OF-SAMPLE Monte Carlo on OOS trades")
    parser.add_argument("--no-monte-carlo", action="store_true", help="Skip Monte Carlo (default)")
    parser.add_argument("--portfolio-risk", action="store_true", help="Run A5.8 on combined OOS trades")
    parser.add_argument("--simulations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-charts", action="store_true")
    parser.add_argument("--storage-dir", default=None)
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: backend/data/walk_forward/<symbol>)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    def emit(message: str) -> None:
        print(message, flush=True)

    args = parse_args(argv)
    emit("TradeLab walk-forward (A5.9/A5.10) — progress prints per window. Not a forecast.")
    settings = get_settings()
    storage_dir = Path(args.storage_dir) if args.storage_dir else Path(settings.parquet_storage_dir)
    symbols = _resolve_symbols(args, storage_dir)
    if not symbols:
        print("No symbols resolved.", file=sys.stderr)
        return 2
    search = _search_space(args)
    include_mc = bool(args.monte_carlo) and not bool(args.no_monte_carlo)
    config = WalkForwardConfig(
        train_years=int(args.train_years),
        test_years=int(args.test_years),
        step_years=int(args.step_years),
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        data_start=args.start_date,
        data_end=args.end_date,
        embargo_days=int(args.embargo_days),
        initial_capital=float(args.initial_capital),
        capital_mode=CapitalMode(args.capital_mode),
        selection_scope=SelectionScope(args.selection_scope),
        search=search,
        strategy_alias=str(args.strategy),
        min_history_bars=int(args.min_history),
        percent=float(args.percent),
        slippage_bps=float(args.slippage_bps),
        brokerage_rate=float(args.brokerage_rate),
        allow_fractional_shares=bool(args.allow_fractional_shares),
        min_quantity=float(args.min_quantity),
        include_monte_carlo=include_mc,
        include_portfolio_risk=bool(args.portfolio_risk),
        include_charts=not bool(args.no_charts),
        simulations=int(args.simulations),
        random_seed=int(args.seed),
    )
    emit(f"Symbols: {', '.join(symbols)}")
    emit(f"Storage: {storage_dir}")
    emit(
        f"Windows: train={config.train_years}y test={config.test_years}y step={config.step_years}y | "
        f"ema200={args.ema200} | capital=₹{config.initial_capital:,.0f}",
    )
    emit("Loading parquet once, then one A5.1 train replay per window (all candidates)...")
    market = ParquetMarketDataAdapter(storage_dir)
    features = ParquetFeatureFrameAdapter(storage_dir)
    result = WalkForwardEngine(config, progress=emit).run(
        symbols=symbols,
        market_data=market,
        features=features,
    )
    emit("")
    print(format_markdown_report(result), flush=True)
    stem = "_".join(symbols[:3]).lower()
    if len(symbols) > 3:
        stem += "_plus"
    out_dir = Path(args.output) if args.output else Path("backend/data/walk_forward") / stem
    paths = write_outputs(result, output_dir=out_dir)
    emit("Wrote:")
    for label, dest in paths.items():
        emit(f"  {label}: {dest}")
    return 0


def _resolve_symbols(args: argparse.Namespace, storage_dir: Path) -> list[str]:
    collected: list[str] = []
    if args.symbol_flags:
        collected.extend(args.symbol_flags)
    if args.symbols:
        collected.extend(part.strip() for part in str(args.symbols).split(",") if part.strip())
    if args.symbols_file:
        path = Path(args.symbols_file)
        if not path.is_file():
            raise FileNotFoundError(f"symbols file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        for line in raw.replace(",", "\n").splitlines():
            token = line.strip()
            if token and not token.startswith("#"):
                collected.append(token)
    if args.universe:
        return resolve_universe_symbols(storage_dir, symbols=["all"])
    if collected:
        return resolve_universe_symbols(storage_dir, symbols=collected)
    return []


def _search_space(args: argparse.Namespace) -> SearchSpace:
    ema200 = {
        "on": (True,),
        "off": (False,),
        "both": (True, False),
    }[str(args.ema200)]
    fast = _ints(args.fast)
    slow = _ints(args.slow)
    presets = tuple(p.strip() for p in str(args.presets).split(",") if p.strip())
    return SearchSpace(
        ema_pair_presets=presets or ("9_21",),
        fast_emas=tuple(fast),
        slow_emas=tuple(slow),
        adx_thresholds=tuple(_floats(args.adx) or [20.0]),
        ema200_filters=ema200,
        max_candidates=int(args.max_candidates),
    )


def _ints(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _floats(raw: str | None) -> list[float]:
    if not raw:
        return []
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
