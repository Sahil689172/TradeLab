"""Strategy Audit & Comparison (Phase A4X.8).

Compute per-strategy signal/filter metrics, scorecards, comparison tables,
and a professional readiness report — with JSON/CSV export.
"""

from app.strategy_engine.audit.auditor import (
    StrategyAuditor,
    audit_from_plans,
    audit_strategy,
    verify_filter_integration,
)
from app.strategy_engine.audit.comparison import build_comparison
from app.strategy_engine.audit.export import (
    export_audit,
    export_audit_csv,
    export_audit_json,
)
from app.strategy_engine.audit.metrics import aggregate_metrics, win_expectancy
from app.strategy_engine.audit.report import (
    build_readiness_report,
    format_audit_report,
    format_comparison_table,
    format_readiness_report,
    format_scorecard_table,
)
from app.strategy_engine.audit.schemas import (
    ProfessionalReadinessReport,
    ReadinessCheck,
    StrategyAuditMetrics,
    StrategyAuditReport,
    StrategyComparisonRow,
    StrategyComparisonTable,
    StrategyScorecard,
    StrategyScorecardRow,
)
from app.strategy_engine.audit.scorecard import build_scorecard, composite_score

__all__ = [
    "ProfessionalReadinessReport",
    "ReadinessCheck",
    "StrategyAuditMetrics",
    "StrategyAuditReport",
    "StrategyAuditor",
    "StrategyComparisonRow",
    "StrategyComparisonTable",
    "StrategyScorecard",
    "StrategyScorecardRow",
    "aggregate_metrics",
    "audit_from_plans",
    "audit_strategy",
    "build_comparison",
    "build_readiness_report",
    "build_scorecard",
    "composite_score",
    "export_audit",
    "export_audit_csv",
    "export_audit_json",
    "format_audit_report",
    "format_comparison_table",
    "format_readiness_report",
    "format_scorecard_table",
    "verify_filter_integration",
    "win_expectancy",
]
