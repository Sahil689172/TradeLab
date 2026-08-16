#!/usr/bin/env python3
"""A5.8 portfolio-level risk on completed historical trades.

    python backend/scripts/portfolio_risk.py --trades-json tests\\fixtures\\portfolio_risk_trades.json ^
        --initial-capital 100000 --max-exposure 80 --max-position-percent 20 --simulations 200 --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backtesting.monte_carlo.schemas import SamplingMethod
from app.backtesting.portfolio_risk import (
    AllocationPolicy,
    LimitAction,
    PortfolioRiskConfig,
    PortfolioRiskEngine,
    PortfolioRiskLimits,
    format_markdown_report,
    portfolio_trades_from_sources,
    write_outputs,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Portfolio risk on completed A5.2 trades (shared book, not a forecast)",
    )
    parser.add_argument("--trades-json", required=True, help="trade_log.json or a list of closed trades")
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument(
        "--allocation",
        choices=[p.value for p in AllocationPolicy],
        default=AllocationPolicy.FIXED_PERCENT_EQUITY.value,
    )
    parser.add_argument("--position-percent", type=float, default=20.0)
    parser.add_argument("--max-exposure", type=float, default=80.0)
    parser.add_argument("--max-position-percent", type=float, default=25.0)
    parser.add_argument("--max-symbol-concentration", type=float, default=40.0)
    parser.add_argument("--max-strategy-concentration", type=float, default=100.0)
    parser.add_argument("--max-open-positions", type=int, default=10)
    parser.add_argument("--max-drawdown-pct", type=float, default=None)
    parser.add_argument("--max-daily-loss-pct", type=float, default=None)
    parser.add_argument(
        "--limit-action",
        choices=[a.value for a in LimitAction],
        default=LimitAction.REJECT.value,
        help="reject (default) or scale. Scale is recorded; never silent.",
    )
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--brokerage-rate", type=float, default=0.0003)
    parser.add_argument("--allow-fractional-shares", action="store_true")
    parser.add_argument("--simulations", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--method",
        choices=[m.value for m in SamplingMethod],
        default=SamplingMethod.BOOTSTRAP.value,
    )
    parser.add_argument("--no-monte-carlo", action="store_true")
    parser.add_argument("--cost-sensitivity", action="store_true")
    parser.add_argument("--compare-a57", action="store_true")
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: backend/data/portfolio_risk)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.trades_json)
    if not path.exists():
        print(f"trades JSON not found: {path}", file=sys.stderr)
        return 2
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw["trade_log"] if isinstance(raw, dict) and "trade_log" in raw else raw
    trades = portfolio_trades_from_sources(rows if isinstance(rows, list) else [])
    config = PortfolioRiskConfig(
        initial_capital=float(args.initial_capital),
        allocation_policy=AllocationPolicy(args.allocation),
        position_percent=float(args.position_percent),
        limits=PortfolioRiskLimits(
            max_exposure_pct=float(args.max_exposure),
            max_position_pct=float(args.max_position_percent),
            max_symbol_concentration_pct=float(args.max_symbol_concentration),
            max_strategy_concentration_pct=float(args.max_strategy_concentration),
            max_open_positions=int(args.max_open_positions),
            max_portfolio_drawdown_pct=args.max_drawdown_pct,
            max_daily_loss_pct=args.max_daily_loss_pct,
            limit_action=LimitAction(args.limit_action),
        ),
        slippage_bps=float(args.slippage_bps),
        brokerage_rate=float(args.brokerage_rate),
        allow_fractional_shares=bool(args.allow_fractional_shares),
        simulations=int(args.simulations),
        random_seed=int(args.seed),
        sampling_method=SamplingMethod(args.method),
        include_monte_carlo=not bool(args.no_monte_carlo),
        include_cost_sensitivity=bool(args.cost_sensitivity),
        compare_a57=bool(args.compare_a57),
    )
    result = PortfolioRiskEngine(config).run(trades)
    print(format_markdown_report(result))
    out_dir = Path(args.output) if args.output else Path("backend/data/portfolio_risk")
    paths = write_outputs(result, output_dir=out_dir, stem="portfolio_report")
    print("Wrote:")
    for label, dest in paths.items():
        print(f"  {label}: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
