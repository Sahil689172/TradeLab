"""Statistical comparison helpers (paired, bootstrap, verdict)."""

from __future__ import annotations

import numpy as np

from app.backtesting.evaluation.schemas import (
    MetricComparison,
    PerformanceMetrics,
    StatisticalSummary,
    Verdict,
)


# Metrics where higher is better / lower is better
_HIGHER_BETTER = {
    "win_rate",
    "profit_factor",
    "net_profit",
    "return_pct",
    "cagr",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "expectancy",
    "risk_reward_ratio",
    "recovery_factor",
}
_LOWER_BETTER = {
    "max_drawdown",
    "average_drawdown",
    "longest_drawdown_days",
    "volatility",
    "ulcer_index",
    "loss_rate",
}


def verdict_for(metric: str, raw: float, pro: float, *, tol: float = 1e-6) -> Verdict:
    higher = metric in _HIGHER_BETTER or metric not in _LOWER_BETTER
    if abs(pro - raw) <= tol:
        return Verdict.SAME
    if higher:
        return Verdict.IMPROVED if pro > raw else Verdict.WORSE
    return Verdict.IMPROVED if pro < raw else Verdict.WORSE


def compare_metrics(
    raw: PerformanceMetrics,
    professional: PerformanceMetrics,
) -> list[MetricComparison]:
    keys = [
        "total_trades",
        "win_rate",
        "profit_factor",
        "net_profit",
        "return_pct",
        "cagr",
        "max_drawdown",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "volatility",
        "expectancy",
        "average_holding_days",
        "ulcer_index",
        "recovery_factor",
    ]
    rows: list[MetricComparison] = []
    for key in keys:
        rv = float(getattr(raw, key))
        pv = float(getattr(professional, key))
        higher = key in _HIGHER_BETTER or key not in _LOWER_BETTER
        rows.append(
            MetricComparison(
                metric=key,
                raw_value=rv,
                professional_value=pv,
                delta=pv - rv,
                verdict=verdict_for(key, rv, pv),
                higher_is_better=higher,
            ),
        )
    return rows


def bootstrap_mean_ci(
    values: list[float],
    *,
    n_boot: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Return (mean, ci_low, ci_high) for the sample mean."""
    if not values:
        return 0.0, 0.0, 0.0
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n_boot):
        sample = rng.choice(arr, size=len(arr), replace=True)
        means.append(float(np.mean(sample)))
    low = float(np.quantile(means, alpha / 2))
    high = float(np.quantile(means, 1 - alpha / 2))
    return float(np.mean(arr)), low, high


def paired_trade_delta(
    raw_pnls: list[float],
    pro_pnls: list[float],
) -> StatisticalSummary:
    """Simple unpaired/bootstrap comparison of trade PnL distributions."""
    raw_mean = float(np.mean(raw_pnls)) if raw_pnls else 0.0
    pro_mean = float(np.mean(pro_pnls)) if pro_pnls else 0.0
    delta = pro_mean - raw_mean
    # Bootstrap CI on professional minus raw means via pooled resampling of delta proxy
    if pro_pnls:
        _, lo, hi = bootstrap_mean_ci(pro_pnls)
    else:
        lo = hi = 0.0
    # Significance: CI of pro mean entirely above/below raw mean
    if not raw_pnls and not pro_pnls:
        sig = "inconclusive"
        verdict = Verdict.SAME
    elif lo > raw_mean:
        sig = "significant_improvement"
        verdict = Verdict.IMPROVED
    elif hi < raw_mean:
        sig = "significant_deterioration"
        verdict = Verdict.WORSE
    elif abs(delta) < 1e-9:
        sig = "no_difference"
        verdict = Verdict.SAME
    else:
        sig = "not_significant"
        verdict = Verdict.IMPROVED if delta > 0 else Verdict.WORSE if delta < 0 else Verdict.SAME

    notes = (
        f"Raw mean trade PnL={raw_mean:.4f}",
        f"Professional mean trade PnL={pro_mean:.4f}",
        f"Bootstrap 95% CI for professional mean=[{lo:.4f}, {hi:.4f}]",
    )
    return StatisticalSummary(
        paired_mean_delta=delta,
        bootstrap_ci_low=lo,
        bootstrap_ci_high=hi,
        significance=sig,
        overall_verdict=verdict,
        trade_count_raw=len(raw_pnls),
        trade_count_professional=len(pro_pnls),
        notes=notes,
    )


def overall_recommendation(
    comparisons: list[MetricComparison],
    statistics: StatisticalSummary,
    *,
    raw: PerformanceMetrics,
    professional: PerformanceMetrics,
) -> tuple[bool, bool, str]:
    """Return (overall_improvement, recommended, executive_summary)."""
    key_metrics = {"sharpe_ratio", "max_drawdown", "return_pct", "win_rate", "profit_factor"}
    improved = 0
    worse = 0
    for row in comparisons:
        if row.metric not in key_metrics:
            continue
        if row.verdict is Verdict.IMPROVED:
            improved += 1
        elif row.verdict is Verdict.WORSE:
            worse += 1

    # Prefer professional if sharpe improved and drawdown not worse (or improved).
    # If raw produced zero trades, do not treat its 0% drawdown as superior.
    sharpe_ok = professional.sharpe_ratio >= raw.sharpe_ratio - 1e-9
    if raw.total_trades == 0:
        dd_ok = True
    else:
        dd_ok = professional.max_drawdown <= raw.max_drawdown + 1e-9
    ret_ok = professional.return_pct >= raw.return_pct - 1e-9
    overall = improved > worse and sharpe_ok
    recommended = overall and dd_ok and (
        statistics.overall_verdict is not Verdict.WORSE
    )
    if recommended and not ret_ok and professional.sharpe_ratio > raw.sharpe_ratio:
        # Still recommend on risk-adjusted grounds
        recommended = True
    if raw.total_trades == 0 and professional.total_trades > 0 and sharpe_ok:
        recommended = True
        overall = True

    summary = (
        f"Professional EMA {'outperformed' if overall else 'did not clearly outperform'} "
        f"Raw EMA on {improved}/{improved + worse or 1} key metrics. "
        f"Sharpe {raw.sharpe_ratio:.2f}→{professional.sharpe_ratio:.2f}, "
        f"MaxDD {raw.max_drawdown:.1%}→{professional.max_drawdown:.1%}, "
        f"Return {raw.return_pct:.1%}→{professional.return_pct:.1%}. "
        f"Statistical verdict: {statistics.overall_verdict.value} ({statistics.significance}). "
        f"Recommended: {'YES' if recommended else 'NO'}."
    )
    return overall, recommended, summary
