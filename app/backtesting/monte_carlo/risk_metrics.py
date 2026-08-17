"""A6 tail-risk metrics: empirical VaR and CVaR / Expected Shortfall.

These reuse the simulated return distribution already produced by the Monte
Carlo engines. They add tail summaries that were previously missing; they do
not change resampling, sizing, or execution logic.

Definitions (empirical, non-parametric):

- ``VaR(c)`` = -quantile(returns, 1 - c). Reported as a positive loss fraction.
  A negative value means even the (1-c) tail outcome was a gain.
- ``CVaR(c)`` / Expected Shortfall = -mean(returns <= quantile(returns, 1 - c)).
  The average loss in the tail at or beyond VaR.

Capital figures scale the return-based estimate by initial capital.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.schemas import RiskMetrics


def _var_cvar(returns: np.ndarray, confidence: float) -> tuple[float, float]:
    """Return (VaR, CVaR) as positive loss fractions for one confidence level."""
    if returns.size == 0:
        return 0.0, 0.0
    tail_pct = (1.0 - confidence) * 100.0
    quantile = float(np.percentile(returns, tail_pct, method="linear"))
    var = -quantile
    tail = returns[returns <= quantile]
    if tail.size == 0:
        cvar = var
    else:
        cvar = -float(np.mean(tail))
    return var, cvar


def compute_risk_metrics(
    returns: Sequence[float] | np.ndarray,
    *,
    initial_capital: float,
    confidence: tuple[float, float] = (0.95, 0.99),
) -> RiskMetrics:
    """Compute empirical VaR/CVaR at the 95% and 99% confidence levels."""
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    c95, c99 = confidence
    var95, cvar95 = _var_cvar(arr, c95)
    var99, cvar99 = _var_cvar(arr, c99)
    cap = float(initial_capital)
    return RiskMetrics(
        confidence_levels=(c95, c99),
        var_return_95=var95,
        var_return_99=var99,
        cvar_return_95=cvar95,
        cvar_return_99=cvar99,
        var_capital_95=var95 * cap,
        var_capital_99=var99 * cap,
        cvar_capital_95=cvar95 * cap,
        cvar_capital_99=cvar99 * cap,
    )
