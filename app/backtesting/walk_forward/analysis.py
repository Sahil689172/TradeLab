"""Degradation, parameter stability, combined OOS metrics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import pandas as pd

from app.backtesting.evaluation.metrics import cagr, compute_performance, max_drawdown, sharpe_ratio, sortino_ratio
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.walk_forward.schemas import (
    CandidateMetrics,
    CapitalMode,
    CoverageStatus,
    DegradationLabel,
    DegradationReport,
    MetricStatus,
    ParameterStability,
    WindowResult,
)


def mean_window_return(windows: Sequence[WindowResult], *, train: bool = False) -> float:
    if not windows:
        return 0.0
    values = [row.train.return_pct if train else row.oos.return_pct for row in windows]
    return float(sum(values) / len(values))


def degradation(
    train: CandidateMetrics,
    oos: CandidateMetrics,
    *,
    oos_trade_count: int = 0,
) -> DegradationReport:
    sample_flag = "INSUFFICIENT_OOS_SAMPLE" if oos_trade_count < 5 else ""
    oos_sharpe_status = (
        MetricStatus.NO_TRADES
        if oos_trade_count == 0
        else MetricStatus.INSUFFICIENT_SAMPLE
        if oos_trade_count < 2
        else MetricStatus.LOW_SAMPLE
        if oos_trade_count < 5
        else MetricStatus.VALID
    )
    oos_sharpe = oos.sharpe if oos_sharpe_status in (MetricStatus.VALID, MetricStatus.LOW_SAMPLE) else None
    oos_win_rate_status = MetricStatus.NO_TRADES if oos_trade_count == 0 else MetricStatus.LOW_SAMPLE if oos_trade_count < 5 else MetricStatus.VALID
    oos_win_rate = oos.win_rate if oos_trade_count > 0 else None
    has_wins = oos_trade_count > 0 and oos.gross_profit > 0
    pf_status = (
        MetricStatus.NO_TRADES
        if oos_trade_count == 0
        else MetricStatus.NO_WINNING_TRADES
        if not has_wins
        else MetricStatus.LOW_SAMPLE
        if oos_trade_count < 5
        else MetricStatus.VALID
    )
    oos_pf = oos.profit_factor if pf_status in (MetricStatus.VALID, MetricStatus.LOW_SAMPLE) else None
    return DegradationReport(
        label=DegradationLabel.DESCRIPTIVE_DIAGNOSTIC,
        train_return=train.return_pct,
        oos_return=oos.return_pct,
        return_ratio=_ratio(oos.return_pct, train.return_pct),
        return_degradation_pct=_degrade(train.return_pct, oos.return_pct),
        train_sharpe=train.sharpe,
        oos_sharpe=oos_sharpe,
        oos_sharpe_raw=oos.sharpe,
        oos_sharpe_status=oos_sharpe_status,
        sharpe_ratio=_ratio(oos.sharpe, train.sharpe) if oos_sharpe is not None else None,
        sharpe_degradation_pct=_degrade(train.sharpe, oos.sharpe) if oos_sharpe is not None else None,
        train_win_rate=train.win_rate,
        oos_win_rate=oos_win_rate,
        oos_win_rate_raw=oos.win_rate if oos_trade_count > 0 else None,
        oos_win_rate_status=oos_win_rate_status,
        win_rate_ratio=_ratio(oos.win_rate, train.win_rate) if oos_win_rate is not None else None,
        win_rate_degradation_pct=_degrade(train.win_rate, oos.win_rate) if oos_win_rate is not None else None,
        train_profit_factor=train.profit_factor,
        oos_profit_factor=oos_pf,
        oos_profit_factor_raw=oos.profit_factor if oos_trade_count > 0 else None,
        oos_profit_factor_status=pf_status,
        profit_factor_ratio=_ratio(oos.profit_factor, train.profit_factor) if oos_pf is not None else None,
        profit_factor_degradation_pct=_degrade(train.profit_factor, oos.profit_factor) if oos_pf is not None else None,
        oos_trade_count=oos_trade_count,
        sample_flag=sample_flag,
    )


def mean_train_oos(windows: Sequence[WindowResult]) -> tuple[CandidateMetrics, CandidateMetrics]:
    if not windows:
        empty = CandidateMetrics(
            config_key="",
            parameters={},
            score=0.0,
            return_pct=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            trade_count=0,
            total_costs=0.0,
            net_profit=0.0,
            gross_profit=0.0,
        )
        return empty, empty
    return _mean([w.train for w in windows]), _mean([w.oos for w in windows])


def parameter_stability(windows: Sequence[WindowResult]) -> ParameterStability:
    history = [w.selected.config_key for w in windows]
    freq = dict(Counter(history))
    changes = sum(1 for i in range(1, len(history)) if history[i] != history[i - 1])
    most = max(freq, key=freq.get) if freq else ""
    denom = max(len(history) - 1, 1)
    score = 1.0 - (changes / denom) if history else 0.0
    oos_trades = sum(w.oos_trade_count for w in windows)
    unique = len(freq)
    if oos_trades == 0:
        coverage = CoverageStatus.NO_OOS_TRADES
        interpretation = "STABLE CONFIGURATION, BUT NO OOS TRADE EVIDENCE" if score >= 0.999 else (
            "PARAMETER CHANGES OBSERVED WITH NO OOS TRADE EVIDENCE"
        )
    elif oos_trades < 5:
        coverage = CoverageStatus.LOW_COVERAGE
        interpretation = (
            f"Stability score {score:.3f} with only {oos_trades} OOS trade(s); "
            "not evidence of OOS robustness."
        )
    else:
        coverage = CoverageStatus.SUFFICIENT
        interpretation = (
            f"Stability score {score:.3f} across {len(windows)} window(s) with {oos_trades} OOS trade(s)."
        )
    return ParameterStability(
        history=history,
        frequency=freq,
        changes=changes,
        most_frequent=most,
        stability_score=float(score),
        unique_config_count=unique,
        window_count=len(windows),
        oos_trade_count=oos_trades,
        coverage_status=coverage,
        interpretation=interpretation,
    )


def stitch_equity(
    segments: Sequence[pd.Series],
    *,
    initial: float,
    mode: CapitalMode,
) -> pd.Series:
    if not segments:
        return pd.Series([initial], index=pd.DatetimeIndex([pd.Timestamp(0, tz="UTC")]))
    parts: list[pd.Series] = []
    last = float(initial)
    for i, segment in enumerate(segments):
        if segment is None or segment.empty:
            continue
        series = segment.astype(float).copy()
        if mode is CapitalMode.FIXED and i > 0:
            start = float(series.iloc[0])
            if start != 0:
                series = series - start + float(initial)
        if parts and not series.empty:
            series = series.iloc[1:] if len(series) > 1 and abs(float(series.iloc[0]) - last) < 1e-6 else series
        if not series.empty:
            last = float(series.iloc[-1])
            parts.append(series)
    if not parts:
        return pd.Series([initial], index=pd.DatetimeIndex([pd.Timestamp(0, tz="UTC")]))
    return pd.concat(parts).sort_index()


def combined_metrics(
    trades: Sequence[ClosedTradeRecord],
    equity: pd.Series,
    initial: float,
) -> dict[str, float | None]:
    dumped = [t.model_dump() for t in trades]
    final = float(equity.iloc[-1]) if len(equity) else initial
    perf = compute_performance(
        mode="oos",
        trades=dumped,
        equity_curve=equity if len(equity) >= 2 else None,
        initial_capital=initial,
    )
    years = 0.0
    if len(equity) >= 2:
        delta = equity.index[-1] - equity.index[0]
        years = max(pd.Timedelta(delta).total_seconds() / (365.25 * 24 * 3600), 0.0)
    pf = float(perf.profit_factor)
    if pf == float("inf"):
        pf = 1_000_000.0
    dd, _avg, _long = max_drawdown(equity.tolist()) if len(equity) else (0.0, 0.0, 0)
    rets = equity.pct_change().dropna().tolist() if len(equity) >= 3 else []
    return {
        "return": (final - initial) / initial if initial else 0.0,
        "cagr": cagr(initial, final, years) if years > 0 else None,
        "sharpe": sharpe_ratio(rets) if len(rets) >= 2 else float(perf.sharpe_ratio),
        "sortino": sortino_ratio(rets) if len(rets) >= 2 else float(perf.sortino_ratio),
        "max_drawdown": float(dd),
        "win_rate": float(perf.win_rate),
        "profit_factor": pf,
        "gross": float(perf.gross_profit),
        "net": float(perf.net_profit),
        "costs": float(perf.commission_paid) + float(perf.slippage_paid),
        "final": final,
    }


def oos_by_year(trades: Sequence[ClosedTradeRecord], initial: float) -> dict[str, float]:
    buckets: dict[int, float] = {}
    for trade in trades:
        year = trade.entry_timestamp.year
        buckets[year] = buckets.get(year, 0.0) + float(trade.net_profit)
    if not buckets or initial <= 0:
        return {}
    return {str(year): pnl / initial for year, pnl in sorted(buckets.items())}


def oos_by_symbol(trades: Sequence[ClosedTradeRecord], initial: float) -> dict[str, float]:
    buckets: dict[str, float] = {}
    for trade in trades:
        key = trade.symbol.strip().upper()
        buckets[key] = buckets.get(key, 0.0) + float(trade.net_profit)
    if not buckets or initial <= 0:
        return {}
    return {symbol: pnl / initial for symbol, pnl in sorted(buckets.items())}


def _ratio(oos: float, train: float) -> float | None:
    if abs(train) <= 1e-12:
        return None
    return float(oos / train)


def _degrade(train: float, oos: float) -> float | None:
    if abs(train) <= 1e-12:
        return None
    return float((train - oos) / abs(train))


def _mean(rows: Sequence[CandidateMetrics]) -> CandidateMetrics:
    n = max(len(rows), 1)
    return CandidateMetrics(
        config_key="mean",
        parameters={},
        score=sum(r.score for r in rows) / n,
        return_pct=sum(r.return_pct for r in rows) / n,
        sharpe=sum(r.sharpe for r in rows) / n,
        sortino=sum(r.sortino for r in rows) / n,
        max_drawdown=sum(r.max_drawdown for r in rows) / n,
        win_rate=sum(r.win_rate for r in rows) / n,
        profit_factor=sum(r.profit_factor for r in rows) / n,
        trade_count=int(sum(r.trade_count for r in rows)),
        total_costs=sum(r.total_costs for r in rows),
        net_profit=sum(r.net_profit for r in rows),
        gross_profit=sum(r.gross_profit for r in rows),
    )
