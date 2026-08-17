"""A7 portfolio-level performance metrics.

Reuses the shared metric primitives in ``evaluation.metrics`` (max drawdown,
Sharpe, Sortino) rather than re-implementing them. Computes portfolio return,
volatility, drawdown, risk-adjusted ratios, exposure, concentration (HHI), and
per-symbol P&L contribution from an already-combined portfolio equity curve plus
per-symbol P&L.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from app.backtesting.evaluation.metrics import max_drawdown, sharpe_ratio, sortino_ratio
from app.backtesting.portfolio_allocation.schemas import PortfolioMetrics


def _period_returns(equity: Sequence[float]) -> list[float]:
    arr = np.asarray(list(equity), dtype=float)
    if arr.size < 2:
        return []
    prev = arr[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.where(prev != 0.0, (arr[1:] - prev) / prev, 0.0)
    rets = rets[np.isfinite(rets)]
    return rets.tolist()


def herfindahl_index(weights: Mapping[str, float]) -> float:
    """Concentration HHI = sum of squared normalized weights (1/n..1)."""
    values = [abs(float(v)) for v in weights.values()]
    total = sum(values)
    if total <= 0:
        return 0.0
    shares = [v / total for v in values]
    return float(sum(s * s for s in shares))


def portfolio_metrics(
    *,
    portfolio_equity: Sequence[float],
    initial_capital: float,
    per_symbol_pnl: Mapping[str, float],
    per_symbol_capital: Mapping[str, float] | None = None,
    average_exposure: float = 0.0,
    periods_per_year: float = 252.0,
) -> PortfolioMetrics:
    """Compute portfolio metrics from a combined equity curve and per-symbol P&L."""
    equity = [float(v) for v in portfolio_equity]
    net_pnl = float(sum(per_symbol_pnl.values()))
    final_equity = equity[-1] if equity else initial_capital + net_pnl
    total_return = (
        (final_equity - initial_capital) / initial_capital if initial_capital else 0.0
    )

    rets = _period_returns(equity)
    if len(rets) > 1:
        volatility = float(np.std(rets, ddof=1) * np.sqrt(periods_per_year))
    else:
        volatility = 0.0
    max_dd, _avg_dd, _longest = max_drawdown(equity) if len(equity) >= 2 else (0.0, 0.0, 0)
    sharpe = sharpe_ratio(rets, periods_per_year=periods_per_year)
    sortino = sortino_ratio(rets, periods_per_year=periods_per_year)

    concentration_source = (
        per_symbol_capital if per_symbol_capital else {k: abs(v) for k, v in per_symbol_pnl.items()}
    )
    hhi = herfindahl_index(concentration_source)

    per_symbol_contribution: dict[str, float] = {}
    if abs(net_pnl) > 1e-12:
        per_symbol_contribution = {s: v / net_pnl for s, v in per_symbol_pnl.items()}

    per_symbol_return: dict[str, float] = {}
    if per_symbol_capital:
        for s, pnl in per_symbol_pnl.items():
            cap = per_symbol_capital.get(s, 0.0)
            per_symbol_return[s] = pnl / cap if cap else 0.0

    return PortfolioMetrics(
        initial_capital=float(initial_capital),
        final_equity=float(final_equity),
        total_return=float(total_return),
        volatility=float(volatility),
        max_drawdown=float(max_dd),
        sharpe=float(sharpe),
        sortino=float(sortino),
        average_exposure=float(average_exposure),
        concentration_hhi=float(hhi),
        per_symbol_pnl={s: float(v) for s, v in per_symbol_pnl.items()},
        per_symbol_contribution={s: float(v) for s, v in per_symbol_contribution.items()},
        per_symbol_return={s: float(v) for s, v in per_symbol_return.items()},
        symbol_count=len(per_symbol_pnl),
    )
