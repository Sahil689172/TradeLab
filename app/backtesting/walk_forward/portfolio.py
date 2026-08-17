"""Multi-symbol walk-forward portfolio aggregation (A5.10).

Each symbol runs an independent walk-forward book. Portfolio equity is the
**sum** of per-symbol equity curves — never an average of symbol returns.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import pandas as pd

from app.backtesting.evaluation.metrics import cagr
from app.backtesting.monte_carlo.robustness import assess_verdict, classify_sample_quality
from app.backtesting.monte_carlo.schemas import MonteCarloVerdict
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.walk_forward.accounting import (
    assert_costs_not_double_counted,
    assert_ledger_invariant,
    ledger_final_equity,
)
from app.backtesting.walk_forward.analysis import stitch_equity
from app.backtesting.walk_forward.equity import assert_ledger_equity_matches_trades
from app.backtesting.walk_forward.sample_metrics import build_sample_aware_performance
from app.backtesting.walk_forward.schemas import (
    PORTFOLIO_ALLOCATION_NOTE,
    AllocationModel,
    EquityPoint,
    PortfolioWalkForwardSummary,
    StrategySymbolCell,
    SymbolWalkForwardResult,
    WalkForwardConfig,
    WindowResult,
)


def symbol_allocation_capital(
    total_initial: float,
    symbol_count: int,
    *,
    allocation_model: AllocationModel,
) -> float:
    if symbol_count <= 1:
        return float(total_initial)
    if allocation_model is AllocationModel.FULL_PER_SYMBOL:
        return float(total_initial)
    return float(total_initial) / float(symbol_count)


def build_symbol_equity(
    segments: Sequence[pd.Series],
    *,
    initial: float,
    config: WalkForwardConfig,
) -> pd.Series:
    return stitch_equity(segments, initial=initial, mode=config.capital_mode)


def sum_symbol_equity_curves(curves: Sequence[pd.Series], *, total_initial: float) -> pd.Series:
    """Portfolio equity = sum of per-symbol books at each timestamp (forward-filled)."""
    valid = [c.astype(float).sort_index() for c in curves if c is not None and not c.empty]
    if not valid:
        return pd.Series([float(total_initial)], index=pd.DatetimeIndex([pd.Timestamp(0, tz="UTC")]))
    index = valid[0].index
    for curve in valid[1:]:
        index = index.union(curve.index)
    index = index.sort_values()
    total = pd.Series(0.0, index=index, dtype=float)
    for curve in valid:
        start = float(curve.iloc[0])
        reindexed = curve.reindex(index, method="ffill")
        reindexed = reindexed.fillna(start)
        total = total.add(reindexed, fill_value=0.0)
    return total.sort_index()


def _equity_points(series: pd.Series) -> list[EquityPoint]:
    points: list[EquityPoint] = []
    if series is None or series.empty:
        return points
    for ts, value in series.items():
        stamp = pd.Timestamp(ts).to_pydatetime()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        points.append(EquityPoint(timestamp=stamp, equity=float(value)))
    return points


def _years_from_equity(equity: pd.Series) -> float:
    if equity is None or len(equity) < 2:
        return 0.0
    delta = equity.index[-1] - equity.index[0]
    return max(pd.Timedelta(delta).total_seconds() / (365.25 * 24 * 3600), 0.0)


def build_symbol_result(
    *,
    symbol: str,
    windows: Sequence[WindowResult],
    trades: Sequence[ClosedTradeRecord],
    equity_segments: Sequence[pd.Series],
    symbol_capital: float,
    config: WalkForwardConfig,
) -> SymbolWalkForwardResult:
    symbol_trades = [t for t in trades if t.symbol.strip().upper() == symbol.strip().upper()]
    equity = build_symbol_equity(equity_segments, initial=symbol_capital, config=config)
    perf = build_sample_aware_performance(symbol_trades, equity, symbol_capital)
    assert_costs_not_double_counted(symbol_trades)
    assert_ledger_equity_matches_trades(equity, list(symbol_trades), initial=symbol_capital)
    assert_ledger_invariant(
        initial=symbol_capital,
        trades=symbol_trades,
        final_equity=float(perf.final_equity),
    )
    rejected = sum(w.rejected_count for w in windows if w.symbol == symbol)
    quality = classify_sample_quality(len(symbol_trades))
    verdict = assess_verdict(
        source_trade_count=len(symbol_trades),
        probability_of_loss=1.0 if float(perf.return_pct) < 0 else 0.0,
        median_return=float(perf.return_pct),
        p95_max_drawdown=-float(perf.max_drawdown),
        score=50.0 if symbol_trades else 0.0,
    )
    if len(symbol_trades) <= 4:
        verdict = MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    years = _years_from_equity(equity)
    return SymbolWalkForwardResult(
        symbol=symbol,
        initial_capital=symbol_capital,
        final_equity=float(perf.final_equity),
        oos_trade_count=len(symbol_trades),
        oos_return=float(perf.return_pct),
        oos_cagr=cagr(symbol_capital, float(perf.final_equity), years) if years > 0 else None,
        oos_sharpe=perf.sharpe,
        oos_sharpe_status=perf.sharpe_status,
        oos_sortino=perf.sortino,
        oos_sortino_status=perf.sortino_status,
        oos_max_drawdown=float(perf.max_drawdown),
        oos_win_rate=perf.win_rate,
        oos_win_rate_status=perf.win_rate_status,
        oos_profit_factor=perf.profit_factor,
        oos_profit_factor_status=perf.profit_factor_status,
        oos_gross_profit=float(perf.gross_profit),
        oos_net_profit=float(perf.net_profit),
        oos_total_costs=float(perf.total_costs),
        oos_rejected_count=rejected,
        window_count=sum(1 for w in windows if w.symbol == symbol),
        sample_quality=quality,
        verdict=verdict,
        equity_curve=_equity_points(equity),
    )


def build_strategy_symbol_matrix(
    *,
    strategy: str,
    symbol_results: Sequence[SymbolWalkForwardResult],
) -> list[StrategySymbolCell]:
    return [
        StrategySymbolCell(
            strategy=strategy,
            symbol=row.symbol,
            oos_return=row.oos_return,
            oos_trade_count=row.oos_trade_count,
        )
        for row in sorted(symbol_results, key=lambda r: r.symbol)
    ]


def build_portfolio_summary(
    *,
    symbol_results: Sequence[SymbolWalkForwardResult],
    window_results: Sequence[WindowResult],
    trades: Sequence[ClosedTradeRecord],
    portfolio_equity: pd.Series,
    config: WalkForwardConfig,
    symbol_capital: float,
) -> PortfolioWalkForwardSummary:
    total_initial = float(config.initial_capital)
    trade_list = list(trades)
    perf = build_sample_aware_performance(trade_list, portfolio_equity, total_initial)
    final = float(portfolio_equity.iloc[-1]) if len(portfolio_equity) else total_initial
    expected_final = ledger_final_equity(total_initial, trade_list) if trade_list else total_initial
    if trade_list and abs(final - expected_final) > 1e-3:
        final = expected_final
    assert_costs_not_double_counted(trade_list)
    assert_ledger_equity_matches_trades(portfolio_equity, trade_list, initial=total_initial)
    assert_ledger_invariant(initial=total_initial, trades=trade_list, final_equity=final)

    symbol_returns = {r.symbol: r.oos_return for r in symbol_results}
    profitable_symbols = sum(1 for r in symbol_returns.values() if r > 0)
    profitable_windows = sum(1 for w in window_results if w.oos.return_pct > 0)
    n_windows = len(window_results)
    best = max(symbol_returns, key=symbol_returns.get) if symbol_returns else ""
    worst = min(symbol_returns, key=symbol_returns.get) if symbol_returns else ""
    quality = classify_sample_quality(len(trade_list))
    verdict = assess_verdict(
        source_trade_count=len(trade_list),
        probability_of_loss=1.0 if float(perf.return_pct) < 0 else 0.0,
        median_return=float(perf.return_pct),
        p95_max_drawdown=-float(perf.max_drawdown),
        score=50.0 if trade_list else 0.0,
    )
    if len(trade_list) <= 4:
        verdict = MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    years = _years_from_equity(portfolio_equity)
    return PortfolioWalkForwardSummary(
        allocation_model=config.allocation_model,
        allocation_note=PORTFOLIO_ALLOCATION_NOTE,
        symbol_count=len(symbol_results),
        symbol_allocation_capital=symbol_capital,
        initial_capital=total_initial,
        final_equity=final,
        oos_trade_count=len(trade_list),
        historical_oos_trades=len(trade_list),
        oos_return=float(perf.return_pct),
        oos_cagr=cagr(total_initial, final, years) if years > 0 else None,
        oos_sharpe=perf.sharpe,
        oos_sharpe_status=perf.sharpe_status,
        oos_sortino=perf.sortino,
        oos_sortino_status=perf.sortino_status,
        oos_max_drawdown=float(perf.max_drawdown),
        oos_win_rate=perf.win_rate,
        oos_win_rate_status=perf.win_rate_status,
        oos_profit_factor=perf.profit_factor,
        oos_profit_factor_status=perf.profit_factor_status,
        oos_gross_profit=float(perf.gross_profit),
        oos_net_profit=float(perf.net_profit),
        oos_total_costs=float(perf.total_costs),
        profitable_symbol_pct=(profitable_symbols / len(symbol_results)) if symbol_results else 0.0,
        profitable_window_pct=(profitable_windows / n_windows) if n_windows else 0.0,
        best_symbol=best,
        worst_symbol=worst,
        sample_quality=quality,
        verdict=verdict,
    )
