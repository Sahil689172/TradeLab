"""Path-dependent portfolio simulation using A5.2 cost and sizing formulas.

Each completed historical trade contributes its *price path* (entry → exit).
Allocated notional is computed from *current cash* after the previous round-trip.
Equity follows A5.2 cash after BUY then SELL (execution prices already include
slippage). Brokerage is charged on both legs.

This does not replay candles or re-run the strategy.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.schemas import (
    MonteCarloSizingMode,
    MonteCarloTrade,
    SimulationSummary,
)
from app.backtesting.order_execution.costs import (
    brokerage_charge,
    execution_price,
    quantity_from_budget,
)
from app.backtesting.order_execution.orders import OrderSide
from app.backtesting.order_execution.schemas import ExecutionConfig, PositionSizingMode


def reference_prices(trade: MonteCarloTrade) -> tuple[float, float]:
    """Canonical entry/exit prices for a completed trade."""
    entry = float(trade.entry_price)
    exit_px = float(trade.exit_price)
    if entry > 0.0 and exit_px > 0.0:
        return entry, exit_px
    if entry > 0.0 and trade.quantity > 0.0:
        # Reconstruct a consistent exit from gross P&L when exit_price is missing.
        exit_px = entry + float(trade.gross_pnl) / float(trade.quantity)
        if exit_px > 0.0:
            return entry, exit_px
    return 0.0, 0.0


def price_return(trade: MonteCarloTrade) -> float:
    entry, exit_px = reference_prices(trade)
    if entry <= 0.0:
        return float(trade.return_pct)
    return exit_px / entry - 1.0


def execution_config_from_mc(
    *,
    initial_capital: float,
    sizing_mode: MonteCarloSizingMode,
    position_percent: float,
    fixed_cash_amount: float | None,
    slippage_bps: float,
    brokerage_rate: float,
    brokerage_flat: float,
    allow_fractional_shares: bool,
    min_quantity: float,
) -> ExecutionConfig:
    """Map A5.7 knobs onto A5.2 ExecutionConfig (cash ≈ equity when flat)."""
    if sizing_mode is MonteCarloSizingMode.FIXED_CASH:
        amount = float(fixed_cash_amount or 0.0)
        return ExecutionConfig(
            initial_capital=initial_capital,
            position_sizing=PositionSizingMode.FIXED_AMOUNT,
            amount=amount,
            slippage_bps=slippage_bps,
            brokerage_rate=brokerage_rate,
            brokerage_flat=brokerage_flat,
            allow_fractional_shares=allow_fractional_shares,
            min_quantity=min_quantity,
        )
    return ExecutionConfig(
        initial_capital=initial_capital,
        position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
        percent=float(position_percent),
        slippage_bps=slippage_bps,
        brokerage_rate=brokerage_rate,
        brokerage_flat=brokerage_flat,
        allow_fractional_shares=allow_fractional_shares,
        min_quantity=min_quantity,
    )


def round_trip_cash_pnl(
    *,
    cash: float,
    entry_price: float,
    exit_price: float,
    config: ExecutionConfig,
) -> dict[str, float]:
    """One sequential long round-trip. Matches A5.2 cash after BUY then SELL."""
    if cash <= 0.0 or entry_price <= 0.0 or exit_price <= 0.0:
        return _idle(cash)

    buy_px = execution_price(OrderSide.BUY, entry_price, config.slippage_bps)
    sell_px = execution_price(OrderSide.SELL, exit_price, config.slippage_bps)
    if config.position_sizing is PositionSizingMode.FIXED_AMOUNT:
        budget = min(float(config.amount or 0.0), cash)
    elif config.position_sizing is PositionSizingMode.FIXED_QUANTITY:
        qty_fixed = float(config.quantity or 0.0)
        budget = qty_fixed * buy_px * (1.0 + config.brokerage_rate) + config.brokerage_flat
        budget = min(budget, cash)
    else:
        budget = cash * config.position_size_pct

    qty = quantity_from_budget(budget, buy_px, config.brokerage_rate, config.brokerage_flat)
    if not config.allow_fractional_shares:
        qty = float(int(qty))
    if qty < config.min_quantity:
        return _idle(cash)

    entry_notional = buy_px * qty
    entry_broker = brokerage_charge(entry_notional, config.brokerage_rate, config.brokerage_flat)
    open_cost = entry_notional + entry_broker
    if open_cost > cash + 1e-9:
        return _idle(cash)

    exit_notional = sell_px * qty
    exit_broker = brokerage_charge(exit_notional, config.brokerage_rate, config.brokerage_flat)
    entry_slip = abs(buy_px - entry_price) * qty
    exit_slip = abs(exit_price - sell_px) * qty
    gross_exec = (sell_px - buy_px) * qty
    gross_ref = (exit_price - entry_price) * qty
    brokerage = entry_broker + exit_broker
    slippage = entry_slip + exit_slip
    net_cash = gross_exec - brokerage
    return {
        "qty": qty,
        "allocated": budget,
        "gross_pnl": gross_ref,
        "gross_exec": gross_exec,
        "brokerage": brokerage,
        "slippage": slippage,
        "net_pnl": net_cash,
        "cash": cash + net_cash,
        "executed": 1.0,
    }


def _idle(cash: float) -> dict[str, float]:
    return {
        "qty": 0.0,
        "allocated": 0.0,
        "gross_pnl": 0.0,
        "gross_exec": 0.0,
        "brokerage": 0.0,
        "slippage": 0.0,
        "net_pnl": 0.0,
        "cash": cash,
        "executed": 0.0,
    }


def simulate_portfolio_batch(
    entries: np.ndarray,
    exits: np.ndarray,
    index_matrix: np.ndarray,
    *,
    initial_capital: float,
    config: ExecutionConfig,
    ruin_equity: float,
) -> dict[str, np.ndarray]:
    """Vectorized across simulations; sequential across trades (path-dependent)."""
    n_sims, n_steps = index_matrix.shape
    if n_steps == 0:
        return _empty_batch(n_sims, initial_capital)

    entry = np.asarray(entries, dtype=float)[index_matrix]
    exit_px = np.asarray(exits, dtype=float)[index_matrix]
    slip = float(config.slippage_bps) / 10_000.0
    rate = float(config.brokerage_rate)
    flat = float(config.brokerage_flat)
    min_qty = float(config.min_quantity)
    pct = config.position_size_pct
    fixed = float(config.amount or 0.0)
    percent_mode = config.position_sizing is PositionSizingMode.PERCENT_OF_CAPITAL

    equity = np.full(n_sims, float(initial_capital), dtype=float)
    peak = equity.copy()
    min_eq = equity.copy()
    max_dd = np.zeros(n_sims, dtype=float)
    lose_run = np.zeros(n_sims, dtype=np.int32)
    win_run = np.zeros(n_sims, dtype=np.int32)
    lose_best = np.zeros(n_sims, dtype=np.int32)
    win_best = np.zeros(n_sims, dtype=np.int32)
    losing = np.zeros(n_sims, dtype=np.int32)
    executed = np.zeros(n_sims, dtype=np.int32)
    wins = np.zeros(n_sims, dtype=np.int32)
    gross_sum = np.zeros(n_sims, dtype=float)
    net_pos = np.zeros(n_sims, dtype=float)
    net_neg = np.zeros(n_sims, dtype=float)
    broker_sum = np.zeros(n_sims, dtype=float)
    slip_sum = np.zeros(n_sims, dtype=float)
    last_alloc = np.zeros(n_sims, dtype=float)
    active = np.ones(n_sims, dtype=bool)

    for t in range(n_steps):
        e = entry[:, t]
        x = exit_px[:, t]
        valid = active & (equity > 0.0) & (e > 0.0) & (x > 0.0)

        buy = e * (1.0 + slip)
        sell = np.maximum(x * (1.0 - slip), 1e-12)
        if percent_mode:
            budget = equity * pct
        else:
            budget = np.minimum(fixed, equity)

        effective = budget / (1.0 + rate) - flat
        qty = np.where((effective > 0.0) & (buy > 0.0), effective / buy, 0.0)
        if not config.allow_fractional_shares:
            qty = np.floor(qty)
        qty = np.where(valid & (qty >= min_qty), qty, 0.0)

        entry_notional = buy * qty
        entry_broker = entry_notional * rate + flat * (qty > 0)
        open_cost = entry_notional + entry_broker
        qty = np.where(open_cost <= equity + 1e-9, qty, 0.0)
        did = qty > 0.0

        entry_notional = buy * qty
        exit_notional = sell * qty
        entry_broker = entry_notional * rate + flat * did
        exit_broker = exit_notional * rate + flat * did
        brokerage = entry_broker + exit_broker
        slippage = (buy - e) * qty + (x - sell) * qty
        gross_exec = (sell - buy) * qty
        gross_ref = (x - e) * qty
        net = gross_exec - brokerage

        equity = np.where(did, equity + net, equity)
        equity = np.maximum(equity, 0.0)

        peak = np.maximum(peak, equity)
        min_eq = np.minimum(min_eq, equity)
        with np.errstate(divide="ignore", invalid="ignore"):
            dd = np.where(peak > 0.0, equity / peak - 1.0, 0.0)
        dd = np.nan_to_num(dd, nan=0.0)
        max_dd = np.minimum(max_dd, dd)

        loss = did & (net < 0.0)
        win = did & (net > 0.0)
        lose_run = np.where(loss, lose_run + 1, np.where(did, 0, lose_run))
        win_run = np.where(win, win_run + 1, np.where(did, 0, win_run))
        lose_best = np.maximum(lose_best, lose_run)
        win_best = np.maximum(win_best, win_run)
        losing += loss.astype(np.int32)
        executed += did.astype(np.int32)
        wins += win.astype(np.int32)
        gross_sum += gross_ref
        net_pos += np.where(net > 0.0, net, 0.0)
        net_neg += np.where(net < 0.0, net, 0.0)
        broker_sum += brokerage
        slip_sum += np.abs(slippage)
        last_alloc = np.where(did, budget, last_alloc)
        # After ruin, remaining trades are skipped (cash is not reused).
        active = active & (equity >= ruin_equity)

    total_return = (equity - initial_capital) / initial_capital
    net_profit = equity - initial_capital
    with np.errstate(divide="ignore", invalid="ignore"):
        win_rate = np.where(executed > 0, wins / executed, 0.0)
        pf = np.where(
            np.abs(net_neg) > 1e-12,
            net_pos / np.abs(net_neg),
            np.where(net_pos > 0.0, 1_000_000.0, 0.0),
        )
    pf = np.nan_to_num(pf, nan=0.0, posinf=1_000_000.0, neginf=0.0)
    vol = np.zeros(n_sims, dtype=float)
    sharpe = np.zeros(n_sims, dtype=float)
    return {
        "final": equity,
        "ret": total_return,
        "dd": max_dd,
        "min_eq": min_eq,
        "peak": peak,
        "lose_streak": lose_best,
        "win_streak": win_best,
        "losing": losing,
        "net_profit": net_profit,
        "vol": vol,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "profit_factor": pf,
        "trade_count": executed,
        "total_cost": broker_sum + slip_sum,
        "total_slippage_cost": slip_sum,
        "total_brokerage_cost": broker_sum,
        "gross_pnl": gross_sum,
        "last_alloc": last_alloc,
    }


def _empty_batch(n_sims: int, initial_capital: float) -> dict[str, np.ndarray]:
    zeros = np.zeros(n_sims, dtype=float)
    zint = np.zeros(n_sims, dtype=np.int32)
    return {
        "final": np.full(n_sims, initial_capital),
        "ret": zeros,
        "dd": zeros,
        "min_eq": np.full(n_sims, initial_capital),
        "peak": np.full(n_sims, initial_capital),
        "lose_streak": zint,
        "win_streak": zint,
        "losing": zint,
        "net_profit": zeros,
        "vol": zeros,
        "sharpe": zeros,
        "win_rate": zeros,
        "profit_factor": zeros,
        "trade_count": zint,
        "total_cost": zeros,
        "total_slippage_cost": zeros,
        "total_brokerage_cost": zeros,
        "gross_pnl": zeros,
        "last_alloc": zeros,
    }


def summary_from_portfolio_batch(batch: dict[str, np.ndarray], index: int) -> SimulationSummary:
    executed = int(batch["trade_count"][index])
    return SimulationSummary(
        final_equity=float(batch["final"][index]),
        total_return=float(batch["ret"][index]),
        max_drawdown=float(batch["dd"][index]),
        min_equity=float(batch["min_eq"][index]),
        peak_equity=float(batch["peak"][index]),
        losing_trades=int(batch["losing"][index]),
        longest_losing_streak=int(batch["lose_streak"][index]),
        longest_winning_streak=int(batch["win_streak"][index]),
        net_profit=float(batch["net_profit"][index]),
        max_drawdown_pct=float(batch["dd"][index]),
        volatility=float(batch["vol"][index]),
        sharpe=float(batch["sharpe"][index]),
        win_rate=float(batch["win_rate"][index]),
        profit_factor=float(batch["profit_factor"][index]),
        trade_count=executed,
        total_cost=float(batch["total_cost"][index]),
        total_slippage_cost=float(batch["total_slippage_cost"][index]),
        total_brokerage_cost=float(batch["total_brokerage_cost"][index]),
        gross_pnl=float(batch["gross_pnl"][index]),
    )


def price_arrays(trades: Sequence[MonteCarloTrade]) -> tuple[np.ndarray, np.ndarray]:
    entries = np.zeros(len(trades), dtype=float)
    exits = np.zeros(len(trades), dtype=float)
    for i, trade in enumerate(trades):
        entries[i], exits[i] = reference_prices(trade)
    return entries, exits
