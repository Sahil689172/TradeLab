"""Load completed trades from A5.1/A5.2 replay or an existing trade_log JSON."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from app.backtesting.monte_carlo.adapter import trades_from_sources
from app.backtesting.monte_carlo.exceptions import MonteCarloConfigError
from app.backtesting.monte_carlo.schemas import MonteCarloTrade
from app.backtesting.order_execution import ExecutionConfig, OrderExecutionEngine, PositionSizingMode
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.replay_engine import HistoricalReplayEngine, ReplayConfig, ReplaySpeed
from app.core.logging import get_logger

logger = get_logger(__name__)


def load_trades_from_json(path: Path) -> list[MonteCarloTrade]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = _extract_trade_rows(raw)
    return trades_from_sources(rows)


def load_trades_from_replay(
    *,
    symbols: list[str],
    strategy_names: list[str],
    initial_capital: float,
    storage_dir: Path | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    max_steps: int | None = None,
    slippage_bps: float = 5.0,
    brokerage_rate: float = 0.0003,
    percent: float = 95.0,
    min_history_bars: int = 60,
) -> tuple[list[MonteCarloTrade], dict[str, Any]]:
    """Run A5.1 replay + A5.2 execution and return completed-trade copies."""
    replay = HistoricalReplayEngine(
        ReplayConfig(
            symbols=symbols,
            strategy_names=strategy_names,
            start_date=start_date,
            end_date=end_date,
            speed=ReplaySpeed.FAST,
            storage_dir=storage_dir,
            min_history_bars=min_history_bars,
            max_steps=max_steps,
        ),
    ).run()
    execution = OrderExecutionEngine(
        ExecutionConfig(
            initial_capital=initial_capital,
            position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
            percent=percent,
            slippage_bps=slippage_bps,
            brokerage_rate=brokerage_rate,
            close_open_at_replay_end=True,
        ),
    )
    exec_result = execution.process_replay_result(replay)
    trades = trades_from_sources(exec_result.trade_log)
    meta = {
        "candles_replayed": replay.candles_replayed,
        "recommendations": replay.recommendations_generated,
        "orders_filled": exec_result.orders_filled,
        "orders_rejected": exec_result.orders_rejected,
        "closed_trades": len(exec_result.trade_log),
        "replay_errors": list(replay.errors),
        "period": _period(exec_result.trade_log),
    }
    logger.info(
        "Monte Carlo source trades=%s filled=%s rejected=%s",
        len(trades),
        exec_result.orders_filled,
        exec_result.orders_rejected,
    )
    return trades, meta


def _extract_trade_rows(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        raise ValueError("trade JSON must be a list or an object with trade_log")
    if "trade_log" in raw:
        return list(raw["trade_log"])
    if "trades" in raw:
        return list(raw["trades"])
    if "closed_positions" in raw:
        return list(raw["closed_positions"])
    raise ValueError("JSON must contain trade_log, trades, closed_positions, or a list")


def _period(trades: list[ClosedTradeRecord]) -> str:
    if not trades:
        return ""
    start = min(t.entry_timestamp for t in trades).date()
    end = max(t.exit_timestamp for t in trades).date()
    return f"{start.isoformat()} → {end.isoformat()}"


def make_synthetic_trades(
    count: int,
    *,
    seed: int = 1,
    quantity: float = 10.0,
    entry_price: float = 100.0,
) -> list[MonteCarloTrade]:
    """Deterministic synthetic completed trades for benchmarks and tests."""
    if count < 1:
        raise MonteCarloConfigError("synthetic trade count must be >= 1")

    rng = np.random.default_rng(int(seed))
    pnl = np.clip(rng.normal(20.0, 80.0, size=int(count)), -400.0, 400.0)
    trades: list[MonteCarloTrade] = []
    notional = quantity * entry_price
    for index, value in enumerate(pnl):
        net = float(value)
        brokerage = 0.50
        slippage = 0.50
        costs = brokerage + slippage
        trades.append(
            MonteCarloTrade(
                pnl=net,
                return_pct=net / notional,
                costs=costs,
                brokerage=brokerage,
                slippage=slippage,
                gross_pnl=net + costs,
                holding_period=1,
                win_loss=1 if net > 0 else (-1 if net < 0 else 0),
                source_trade_id=f"SYNTHETIC:{index}",
                symbol="SYNTHETIC",
                quantity=quantity,
                entry_price=entry_price,
                exit_price=entry_price + net / quantity,
            ),
        )
    return trades
