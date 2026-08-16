"""Timestamp-aligned correlation. Missing observations stay missing."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

import numpy as np

from app.backtesting.portfolio_risk.schemas import CorrelationReport, PortfolioTrade


def trade_return_series(
    trades: Sequence[PortfolioTrade],
    *,
    key: str,
) -> dict[str, list[tuple[datetime, float]]]:
    """Exit-timestamp returns by symbol or strategy. No zero-fill."""
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for trade in trades:
        label = trade.symbol if key == "symbol" else (trade.strategy or "unknown")
        if not label:
            continue
        series[label].append((trade.exit_timestamp, float(trade.trade_return)))
    for label in series:
        series[label].sort(key=lambda row: row[0])
    return dict(series)


def correlation_report(
    trades: Sequence[PortfolioTrade],
    *,
    kind: str,
    min_observations: int,
    high_threshold: float,
) -> CorrelationReport:
    series = trade_return_series(trades, key="symbol" if kind == "symbol" else "strategy")
    labels = sorted(series)
    n = len(labels)
    if n < 2:
        return CorrelationReport(
            kind=kind,
            labels=labels,
            matrix=[],
            min_observations=min_observations,
            insufficient=True,
            note=(
                "Fewer than two series. Diversification cannot be inferred. "
                "Missing observations are not treated as zero returns."
            ),
        )

    matrix: list[list[float | None]] = [[None] * n for _ in range(n)]
    pairwise: list[float] = []
    insufficient: list[str] = []
    pairs: list[dict[str, float | str]] = []

    for i, a in enumerate(labels):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            b = labels[j]
            corr, count = _aligned_corr(series[a], series[b])
            if count < min_observations or corr is None:
                insufficient.append(f"{a}|{b} (n={count})")
                continue
            matrix[i][j] = corr
            matrix[j][i] = corr
            pairwise.append(corr)
            if abs(corr) >= high_threshold:
                pairs.append({"a": a, "b": b, "correlation": corr})

    insufficient_flag = len(pairwise) == 0
    avg = float(np.mean(pairwise)) if pairwise else None
    mx = float(max(pairwise, key=abs)) if pairwise else None
    note = (
        "Pairwise Pearson on exit-timestamp returns aligned by exact timestamp. "
        "Unmatched timestamps are dropped, not filled with zeros. "
    )
    if insufficient_flag:
        note += "Insufficient aligned observations: do not claim diversification."
    return CorrelationReport(
        kind=kind,
        labels=labels,
        matrix=matrix,
        average_pairwise=avg,
        maximum_pairwise=mx,
        highly_correlated_pairs=sorted(pairs, key=lambda p: abs(float(p["correlation"])), reverse=True),
        min_observations=min_observations,
        insufficient=insufficient_flag,
        insufficient_pairs=insufficient,
        note=note,
    )


def _aligned_corr(
    left: Sequence[tuple[datetime, float]],
    right: Sequence[tuple[datetime, float]],
) -> tuple[float | None, int]:
    right_map: dict[datetime, list[float]] = defaultdict(list)
    for ts, value in right:
        right_map[ts].append(value)
    xs: list[float] = []
    ys: list[float] = []
    used: dict[datetime, int] = defaultdict(int)
    for ts, value in left:
        bucket = right_map.get(ts)
        if not bucket:
            continue
        idx = used[ts]
        if idx >= len(bucket):
            continue
        xs.append(value)
        ys.append(bucket[idx])
        used[ts] += 1
    if len(xs) < 2:
        return None, len(xs)
    arr_x = np.asarray(xs, dtype=float)
    arr_y = np.asarray(ys, dtype=float)
    if float(arr_x.std(ddof=1)) <= 1e-12 or float(arr_y.std(ddof=1)) <= 1e-12:
        return None, len(xs)
    corr = float(np.corrcoef(arr_x, arr_y)[0, 1])
    if not np.isfinite(corr):
        return None, len(xs)
    return corr, len(xs)
