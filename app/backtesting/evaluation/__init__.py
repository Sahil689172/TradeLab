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
from app.backtesting.evaluation.canonical import (
    CanonicalEMAComparison,
    compare_ema_modes_canonical,
    load_canonical_features,
)
from app.backtesting.evaluation.integrity import (
    CapitalAllocationMode,
    RawSignalDiagnostic,
    diagnose_raw_signals,
    merge_equal_weight_equity,
    periods_per_year_for_stride,
    resolution_for_stride,
    validate_evaluation_metrics,
)
from app.backtesting.evaluation.funnel_semantics import (
    buy_candidate_reduction_pct,
    build_signal_funnel,
)
from app.feature_engine.strategy_frame import ensure_strategy_indicators
from app.backtesting.evaluation.reports import format_console_report, format_markdown_report
from app.backtesting.evaluation.runner import (
    EMAEvaluationEngine,
    EvaluationConfig,
    format_report,
    load_symbol_features,
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
    "CanonicalEMAComparison",
    "CapitalAllocationMode",
    "EMAEvaluationEngine",
    "EvalTrade",
    "EvaluationConfig",
    "EvaluationReport",
    "FilterEffectivenessRow",
    "MetricComparison",
    "PerformanceMetrics",
    "RawSignalDiagnostic",
    "SignalFunnelMetrics",
    "StatisticalSummary",
    "Verdict",
    "build_signal_funnel",
    "buy_candidate_reduction_pct",
    "cagr",
    "compare_ema_modes_canonical",
    "compare_metrics",
    "compute_performance",
    "diagnose_raw_signals",
    "ensure_strategy_indicators",
    "format_console_report",
    "format_markdown_report",
    "format_report",
    "load_canonical_features",
    "load_symbol_features",
    "max_drawdown",
    "merge_equal_weight_equity",
    "overall_recommendation",
    "paired_trade_delta",
    "periods_per_year_for_stride",
    "profit_factor",
    "resolution_for_stride",
    "run_long_only_backtest",
    "sharpe_ratio",
    "sortino_ratio",
    "synthetic_features",
    "ulcer_index",
    "validate_evaluation_metrics",
    "verdict_for",
]
