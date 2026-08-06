"""Performance metric calculations from trades and equity curves."""

from __future__ import annotations

from statistics import mean, median
from typing import Sequence

import numpy as np
import pandas as pd

from app.backtesting.evaluation.schemas import PerformanceMetrics


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0 or den != den:
        return default
    return float(num) / float(den)


def max_drawdown(equity: Sequence[float]) -> tuple[float, float, int]:
    """Return (max_dd_pct, average_dd_pct, longest_dd_bars).

    Drawdown pct is expressed as a positive fraction (0.21 = 21%).
    """
    if not equity:
        return 0.0, 0.0, 0
    series = np.asarray(equity, dtype=float)
    peak = series[0]
    max_dd = 0.0
    dd_values: list[float] = []
    longest = 0
    current = 0
    for value in series:
        peak = max(peak, value)
        dd = 0.0 if peak <= 0 else (peak - value) / peak
        dd_values.append(dd)
        max_dd = max(max_dd, dd)
        if dd > 1e-12:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    avg_dd = float(mean(dd_values)) if dd_values else 0.0
    return float(max_dd), avg_dd, int(longest)


def ulcer_index(equity: Sequence[float]) -> float:
    if len(equity) < 2:
        return 0.0
    series = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(series)
    dd = np.where(peak > 0, (peak - series) / peak, 0.0)
    return float(np.sqrt(np.mean(np.square(dd))))


def sharpe_ratio(returns: Sequence[float], *, periods_per_year: float = 252.0) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.asarray(returns, dtype=float)
    std = float(np.std(arr, ddof=1))
    if std <= 1e-12:
        return 0.0
    return float(np.mean(arr) / std * np.sqrt(periods_per_year))


def sortino_ratio(returns: Sequence[float], *, periods_per_year: float = 252.0) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.asarray(returns, dtype=float)
    downside = arr[arr < 0.0]
    if len(downside) == 0:
        return 0.0 if float(np.mean(arr)) <= 0 else 10.0
    dstd = float(np.std(downside, ddof=1)) if len(downside) > 1 else abs(float(downside[0]))
    if dstd <= 1e-12:
        return 0.0
    return float(np.mean(arr) / dstd * np.sqrt(periods_per_year))


def cagr(initial: float, final: float, years: float) -> float:
    if initial <= 0 or years <= 0:
        return 0.0
    if final <= 0:
        return -1.0
    return float((final / initial) ** (1.0 / years) - 1.0)


def profit_factor(gross_profit: float, gross_loss: float) -> float:
    """gross_loss should be negative or zero; uses absolute loss."""
    loss = abs(gross_loss)
    if loss <= 1e-12:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / loss)


def compute_performance(
    *,
    mode: str,
    trades: list[dict],
    equity_curve: pd.Series | None,
    initial_capital: float,
    symbols_evaluated: int = 1,
    periods_per_year: float = 252.0,
) -> PerformanceMetrics:
    """Compute the A4Y.1.5 performance suite.

    ``trades`` dict keys: net_profit, gross_profit, brokerage, slippage,
    holding_days, quantity, entry_price (optional).
    """
    nets = [float(t["net_profit"]) for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    holdings = [float(t.get("holding_days", 0)) for t in trades]
    commissions = sum(float(t.get("brokerage", 0.0)) for t in trades)
    slippages = sum(float(t.get("slippage", 0.0)) for t in trades)
    notional = [
        abs(float(t.get("quantity", 0.0)) * float(t.get("entry_price", 0.0)))
        for t in trades
    ]

    gross_profit = sum(n for n in nets if n > 0)
    gross_loss = sum(n for n in nets if n < 0)  # negative
    net_profit = sum(nets)
    final_equity = (
        float(equity_curve.iloc[-1])
        if equity_curve is not None and len(equity_curve)
        else initial_capital + net_profit
    )
    return_pct = _safe_div(final_equity - initial_capital, initial_capital)

    if equity_curve is not None and len(equity_curve) >= 2:
        rets = equity_curve.pct_change().dropna().tolist()
        years = max(len(equity_curve) / periods_per_year, 1e-9)
        max_dd, avg_dd, longest_dd = max_drawdown(equity_curve.tolist())
        vol = float(np.std(rets, ddof=1) * np.sqrt(periods_per_year)) if len(rets) > 1 else 0.0
        sharpe = sharpe_ratio(rets, periods_per_year=periods_per_year)
        sortino = sortino_ratio(rets, periods_per_year=periods_per_year)
        ulcer = ulcer_index(equity_curve.tolist())
        # Exposure: fraction of bars with open risk approximated via holding sum / span
        total_hold = sum(holdings)
        span_days = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1) if hasattr(equity_curve.index[0], "day") else max(len(equity_curve), 1)
        exposure = min(_safe_div(total_hold, float(span_days)), 1.0)
    else:
        years = max(sum(holdings) / 252.0, 1e-9) if holdings else 1e-9
        max_dd, avg_dd, longest_dd = 0.0, 0.0, 0
        vol = 0.0
        sharpe = 0.0
        sortino = 0.0
        ulcer = 0.0
        exposure = 0.0

    ann = cagr(initial_capital, final_equity, years)
    pf = profit_factor(gross_profit, gross_loss)
    if pf == float("inf"):
        pf = 99.0  # cap for JSON/schema friendliness

    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 0.0
    win_rate = _safe_div(len(wins), len(nets)) if nets else 0.0
    loss_rate = _safe_div(len(losses), len(nets)) if nets else 0.0
    expectancy = win_rate * avg_win + loss_rate * avg_loss
    rr = _safe_div(abs(avg_win), abs(avg_loss)) if avg_loss else (0.0 if avg_win == 0 else 99.0)
    calmar = _safe_div(ann, max_dd) if max_dd > 0 else 0.0
    recovery = _safe_div(net_profit, max_dd * initial_capital) if max_dd > 0 else 0.0
    avg_pos = mean(notional) if notional else 0.0
    util = _safe_div(avg_pos, initial_capital)

    return PerformanceMetrics(
        mode=mode,
        total_trades=len(nets),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate=win_rate,
        loss_rate=loss_rate,
        average_profit=float(avg_win),
        average_loss=float(avg_loss),
        largest_profit=max(wins) if wins else 0.0,
        largest_loss=min(losses) if losses else 0.0,
        profit_factor=float(pf),
        gross_profit=float(gross_profit),
        gross_loss=float(gross_loss),
        net_profit=float(net_profit),
        return_pct=float(return_pct),
        cagr=float(ann),
        max_drawdown=float(max_dd),
        average_drawdown=float(avg_dd),
        longest_drawdown_days=int(longest_dd),
        sharpe_ratio=float(sharpe),
        sortino_ratio=float(sortino),
        calmar_ratio=float(calmar),
        volatility=float(vol),
        expectancy=float(expectancy),
        average_holding_days=float(mean(holdings)) if holdings else 0.0,
        median_holding_days=float(median(holdings)) if holdings else 0.0,
        exposure_pct=float(exposure * 100.0),
        average_position_size=float(avg_pos),
        capital_utilization=float(util),
        commission_paid=float(commissions),
        slippage_paid=float(slippages),
        risk_reward_ratio=float(rr),
        recovery_factor=float(recovery),
        ulcer_index=float(ulcer),
        initial_capital=float(initial_capital),
        final_equity=float(final_equity),
        symbols_evaluated=int(symbols_evaluated),
    )
