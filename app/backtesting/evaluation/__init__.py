"""Professional EMA Evaluation & Statistical Validation (Phase A4Y.1.5)."""

from app.backtesting.evaluation.backtester import (
    BacktestResult,
    BacktestSettings,
    EvalTrade,
    run_long_only_backtest,
)
from app.backtesting.evaluation.metrics import (
    cagr,
    compute_performance,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    ulcer_index,
)
from app.backtesting.evaluation.reports import format_console_report, format_markdown_report
from app.backtesting.evaluation.runner import (
    EMAEvaluationEngine,
    EvaluationConfig,
    format_report,
    synthetic_features,
)
from app.backtesting.evaluation.schemas import (
    EvaluationReport,
    FilterEffectivenessRow,
    MetricComparison,
    PerformanceMetrics,
    SignalFunnelMetrics,
    StatisticalSummary,
    Verdict,
)
from app.backtesting.evaluation.statistics import (
    compare_metrics,
    overall_recommendation,
    paired_trade_delta,
    verdict_for,
)

__all__ = [
    "BacktestResult",
    "BacktestSettings",
    "EMAEvaluationEngine",
    "EvalTrade",
    "EvaluationConfig",
    "EvaluationReport",
    "FilterEffectivenessRow",
    "MetricComparison",
    "PerformanceMetrics",
    "SignalFunnelMetrics",
    "StatisticalSummary",
    "Verdict",
    "cagr",
    "compare_metrics",
    "compute_performance",
    "format_console_report",
    "format_markdown_report",
    "format_report",
    "max_drawdown",
    "overall_recommendation",
    "paired_trade_delta",
    "profit_factor",
    "run_long_only_backtest",
    "sharpe_ratio",
    "sortino_ratio",
    "synthetic_features",
    "ulcer_index",
    "verdict_for",
]
