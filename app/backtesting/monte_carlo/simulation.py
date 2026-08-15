"""Equity-path statistics for one simulation or a vectorized batch.

Drawdown (every path):

    drawdown_t = equity_t / running_peak_t - 1
    max_drawdown = min_t drawdown_t          (most negative)
    max_drawdown_pct = max_drawdown          (same fraction)

Capital modes are never mixed:

    ADDITIVE_PNL:  equity[t] = equity[t-1] + net_profit[t]
    RETURN_BASED:  equity[t] = equity[t-1] * (1 + return[t])
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.backtesting.evaluation.metrics import sharpe_ratio
from app.backtesting.monte_carlo.schemas import CapitalMode, SimulationSummary


def simulate_equity(
    values: Sequence[float],
    *,
    initial_capital: float,
    capital_mode: CapitalMode = CapitalMode.ADDITIVE_PNL,
) -> SimulationSummary:
    """Single-path helper (tests and historical snapshot)."""
    if initial_capital <= 0:
        raise ValueError("initial_capital must be > 0")
    matrix = np.asarray(values, dtype=float).reshape(1, -1)
    batch = simulate_equity_batch(
        matrix,
        initial_capital=initial_capital,
        capital_mode=capital_mode,
    )
    return summary_from_batch(batch, 0)


def simulate_equity_batch(
    values: np.ndarray,
    *,
    initial_capital: float,
    capital_mode: CapitalMode,
) -> dict[str, np.ndarray]:
    """Vectorized paths. ``values`` shape is (n_sims, n_steps)."""
    if initial_capital <= 0:
        raise ValueError("initial_capital must be > 0")
    paths = np.asarray(values, dtype=float)
    if paths.ndim == 1:
        paths = paths.reshape(1, -1)
    n_sims, n_steps = paths.shape
    if n_steps == 0:
        zeros = np.zeros(n_sims, dtype=float)
        return {
            "final": np.full(n_sims, initial_capital),
            "ret": zeros,
            "dd": zeros,
            "min_eq": np.full(n_sims, initial_capital),
            "peak": np.full(n_sims, initial_capital),
            "lose_streak": np.zeros(n_sims, dtype=np.int32),
            "win_streak": np.zeros(n_sims, dtype=np.int32),
            "losing": np.zeros(n_sims, dtype=np.int32),
            "net_profit": zeros,
            "vol": zeros,
            "sharpe": zeros,
        }

    if capital_mode is CapitalMode.ADDITIVE_PNL:
        equity = initial_capital + np.cumsum(paths, axis=1)
        step_ret = paths / initial_capital
    else:
        growth = np.cumprod(np.maximum(1.0 + paths, 0.0), axis=1)
        equity = initial_capital * growth
        step_ret = paths

    start = np.full((n_sims, 1), float(initial_capital))
    eq = np.concatenate([start, equity], axis=1)
    peak = np.maximum.accumulate(eq, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0.0, eq / peak - 1.0, np.where(eq <= 0.0, -1.0, 0.0))
        dd = np.nan_to_num(dd, nan=-1.0, posinf=0.0, neginf=-1.0)

    final = eq[:, -1]
    max_dd = dd.min(axis=1)
    min_eq = eq.min(axis=1)
    peak_eq = peak.max(axis=1)
    total_return = (final - initial_capital) / initial_capital
    net_profit = final - initial_capital

    lose_mask = paths < 0
    win_mask = paths > 0
    losing = lose_mask.sum(axis=1).astype(np.int32)
    lose_streak = _max_run(lose_mask)
    win_streak = _max_run(win_mask)

    if n_steps >= 2:
        vol = step_ret.std(axis=1, ddof=1)
        mean = step_ret.mean(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            sharpe = np.where(vol > 1e-12, mean / vol, 0.0)
        sharpe = np.nan_to_num(sharpe, nan=0.0, posinf=0.0, neginf=0.0)
    else:
        vol = np.zeros(n_sims, dtype=float)
        sharpe = np.zeros(n_sims, dtype=float)

    return {
        "final": final,
        "ret": total_return,
        "dd": max_dd,
        "min_eq": min_eq,
        "peak": peak_eq,
        "lose_streak": lose_streak,
        "win_streak": win_streak,
        "losing": losing,
        "net_profit": net_profit,
        "vol": vol,
        "sharpe": sharpe,
    }


def _max_run(mask: np.ndarray) -> np.ndarray:
    """Longest consecutive True run along axis 1. Loops over steps, not sims."""
    n_sims, n_steps = mask.shape
    runs = np.zeros(n_sims, dtype=np.int32)
    best = np.zeros(n_sims, dtype=np.int32)
    for t in range(n_steps):
        runs = np.where(mask[:, t], runs + 1, 0)
        best = np.maximum(best, runs)
    return best


def summary_from_batch(batch: dict[str, np.ndarray], index: int) -> SimulationSummary:
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
    )


def trade_level_sharpe(pnls: Sequence[float], initial_capital: float) -> float:
    if initial_capital <= 0 or len(pnls) < 2:
        return 0.0
    returns = [float(pnl) / initial_capital for pnl in pnls]
    return sharpe_ratio(returns, periods_per_year=1.0)
