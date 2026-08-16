"""Portfolio equity-curve analytics. Drawdown is from the combined book."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.backtesting.evaluation.metrics import max_drawdown
from app.backtesting.portfolio_risk.schemas import DrawdownReport


def drawdown_from_equity(
    timestamps: Sequence[datetime],
    equity: Sequence[float],
) -> DrawdownReport:
    """Max drawdown of the *combined* equity path. Not a sum of sleeve DDs."""
    _ = timestamps
    values = [float(v) for v in equity]
    if len(values) < 2:
        return DrawdownReport()
    max_dd_frac, _avg, longest = max_drawdown(values)
    peak = values[0]
    peak_i = 0
    best_dd = 0.0
    trough_i = 0
    start_peak_i = 0
    for i, value in enumerate(values):
        if value >= peak - 1e-12:
            peak = value
            peak_i = i
        dd = 0.0 if peak <= 0 else (peak - value) / peak
        if dd > best_dd:
            best_dd = dd
            trough_i = i
            start_peak_i = peak_i
    recovered: int | None = None
    if best_dd > 0:
        peak_level = values[start_peak_i]
        for j in range(trough_i + 1, len(values)):
            if values[j] >= peak_level - 1e-9:
                recovered = j - trough_i
                break
    worst_step = 0.0
    for i in range(1, len(values)):
        worst_step = min(worst_step, values[i] - values[i - 1])
    signed = -float(max(best_dd, max_dd_frac))
    return DrawdownReport(
        max_drawdown=signed,
        max_drawdown_pct=signed,
        duration_events=int(longest),
        recovery_events=recovered,
        worst_period_loss=float(worst_step),
        worst_historical_drawdown=signed,
    )
