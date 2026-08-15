"""Per-simulation equity path statistics.

Drawdown uses only the equity path of the current simulation:

    drawdown_t = equity_t / running_peak_t - 1
    max_drawdown = minimum drawdown_t   (most negative)

P&L is applied additively (canonical rupee ``net_profit``). Shuffle therefore
changes path risk, not the sum of historical P&L.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.backtesting.monte_carlo.schemas import SimulationSummary
from app.backtesting.evaluation.metrics import sharpe_ratio


def simulate_equity(
    pnls: Sequence[float],
    *,
    initial_capital: float,
) -> SimulationSummary:
    if initial_capital <= 0:
        raise ValueError("initial_capital must be > 0")

    equity = float(initial_capital)
    peak = equity
    min_equity = equity
    max_dd = 0.0
    lose_streak = 0
    win_streak = 0
    longest_lose = 0
    longest_win = 0
    losing = 0

    for pnl in pnls:
        equity += float(pnl)
        if equity > peak:
            peak = equity
        if equity < min_equity:
            min_equity = equity
        if peak > 0:
            dd = equity / peak - 1.0
            if dd < max_dd:
                max_dd = dd
        elif equity <= 0:
            max_dd = min(max_dd, -1.0)

        if pnl < 0:
            losing += 1
            lose_streak += 1
            win_streak = 0
            longest_lose = max(longest_lose, lose_streak)
        elif pnl > 0:
            win_streak += 1
            lose_streak = 0
            longest_win = max(longest_win, win_streak)
        else:
            lose_streak = 0
            win_streak = 0

    total_return = (equity - initial_capital) / initial_capital
    return SimulationSummary(
        final_equity=equity,
        total_return=total_return,
        max_drawdown=max_dd,
        min_equity=min_equity,
        peak_equity=peak,
        losing_trades=losing,
        longest_losing_streak=longest_lose,
        longest_winning_streak=longest_win,
    )


def trade_level_sharpe(pnls: Sequence[float], initial_capital: float) -> float:
    if initial_capital <= 0 or len(pnls) < 2:
        return 0.0
    returns = [float(pnl) / initial_capital for pnl in pnls]
    return sharpe_ratio(returns, periods_per_year=1.0)
