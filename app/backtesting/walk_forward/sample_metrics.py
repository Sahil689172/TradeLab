"""Sample-aware performance metrics for walk-forward reporting."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from app.backtesting.evaluation.metrics import compute_performance, max_drawdown, sharpe_ratio, sortino_ratio
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.walk_forward.accounting import ledger_final_equity
from app.backtesting.walk_forward.schemas import MetricStatus, SampleAwarePerformance


def _status_for_trades(trade_count: int) -> MetricStatus:
    if trade_count == 0:
        return MetricStatus.NO_TRADES
    if trade_count < 2:
        return MetricStatus.INSUFFICIENT_SAMPLE
    if trade_count < 5:
        return MetricStatus.LOW_SAMPLE
    return MetricStatus.VALID


def _wrap_ratio(
    raw: float,
    *,
    trade_count: int,
    min_trades: int = 2,
    low_trades: int = 5,
) -> tuple[float | None, float, MetricStatus]:
    status = _status_for_trades(trade_count)
    if trade_count < min_trades:
        return None, raw, MetricStatus.INSUFFICIENT_SAMPLE
    if trade_count < low_trades:
        return raw, raw, MetricStatus.LOW_SAMPLE
    return raw, raw, status


def _wrap_win_rate(raw: float, trade_count: int) -> tuple[float | None, float | None, MetricStatus]:
    if trade_count == 0:
        return None, None, MetricStatus.NO_TRADES
    if trade_count < 5:
        return raw, raw, MetricStatus.LOW_SAMPLE
    return raw, raw, MetricStatus.VALID


def _wrap_profit_factor(raw: float, trade_count: int, wins: int) -> tuple[float | None, float, MetricStatus]:
    if trade_count == 0:
        return None, raw, MetricStatus.NO_TRADES
    if wins == 0:
        return None, raw, MetricStatus.NO_WINNING_TRADES
    if trade_count < 5:
        return raw, raw, MetricStatus.LOW_SAMPLE
    return raw, raw, MetricStatus.VALID


def build_sample_aware_performance(
    trades: Sequence[ClosedTradeRecord],
    equity: pd.Series,
    initial: float,
) -> SampleAwarePerformance:
    dumped = [t.model_dump() for t in trades]
    trade_count = len(trades)
    wins = sum(1 for t in trades if float(t.net_profit) > 0)
    perf = compute_performance(
        mode="oos",
        trades=dumped,
        equity_curve=equity if len(equity) >= 2 else None,
        initial_capital=initial,
    )
    final = ledger_final_equity(initial, trades) if trades else (float(equity.iloc[-1]) if len(equity) else initial)
    return_pct = (final - initial) / initial if initial else 0.0
    dd, _, _ = max_drawdown(equity.tolist()) if len(equity) else (0.0, 0.0, 0)
    rets = equity.pct_change().dropna().tolist() if len(equity) >= 3 else []
    sharpe_raw = sharpe_ratio(rets) if len(rets) >= 2 else float(perf.sharpe_ratio)
    sortino_raw = sortino_ratio(rets) if len(rets) >= 2 else float(perf.sortino_ratio)
    pf_raw = float(perf.profit_factor)
    if pf_raw == float("inf"):
        pf_raw = 1_000_000.0

    sharpe, sharpe_raw_out, sharpe_status = _wrap_ratio(sharpe_raw, trade_count=trade_count)
    sortino, sortino_raw_out, sortino_status = _wrap_ratio(sortino_raw, trade_count=trade_count)
    win_rate, win_rate_raw, win_rate_status = _wrap_win_rate(float(perf.win_rate), trade_count)
    profit_factor, pf_raw_out, pf_status = _wrap_profit_factor(pf_raw, trade_count, wins)

    return SampleAwarePerformance(
        trade_count=trade_count,
        return_pct=float(return_pct),
        return_raw=float(return_pct),
        return_status=MetricStatus.NO_TRADES if trade_count == 0 else MetricStatus.VALID,
        sharpe=sharpe,
        sharpe_raw=sharpe_raw_out,
        sharpe_status=sharpe_status,
        sortino=sortino,
        sortino_raw=sortino_raw_out,
        sortino_status=sortino_status,
        max_drawdown=float(dd),
        max_drawdown_raw=float(dd),
        max_drawdown_status=MetricStatus.VALID if len(equity) >= 2 else MetricStatus.NO_TRADES,
        win_rate=win_rate,
        win_rate_raw=win_rate_raw,
        win_rate_status=win_rate_status,
        profit_factor=profit_factor,
        profit_factor_raw=pf_raw_out,
        profit_factor_status=pf_status,
        gross_profit=float(perf.gross_profit),
        net_profit=float(perf.net_profit),
        total_costs=float(perf.commission_paid) + float(perf.slippage_paid),
        final_equity=final,
    )
