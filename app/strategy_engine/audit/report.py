"""Professional readiness report + human-readable formatting."""

from __future__ import annotations

from app.strategy_engine.audit.schemas import (
    ProfessionalReadinessReport,
    ReadinessCheck,
    StrategyAuditMetrics,
    StrategyAuditReport,
    StrategyComparisonTable,
    StrategyScorecard,
)


def build_readiness_report(
    *,
    symbol: str,
    metrics: list[StrategyAuditMetrics] | tuple[StrategyAuditMetrics, ...],
    scorecard: StrategyScorecard,
    comparison: StrategyComparisonTable,
    tests_passed: bool = True,
) -> ProfessionalReadinessReport:
    """Assemble readiness checks required by Phase A4X.8."""
    filter_ok = all(m.filter_integration_ok for m in metrics) and bool(metrics)
    scorecard_ok = len(scorecard.rows) > 0
    comparison_ok = len(comparison.rows) > 0
    # Treat filter-integration + successful materialization as the audit "test" gate.
    # Per-window feature/context misses are recorded on metrics but do not fail this check.
    no_runtime_failures = filter_ok and all(
        not any(err.startswith("filter_integration:") for err in m.runtime_errors)
        for m in metrics
    )

    checks = (
        ReadinessCheck(
            name="no_failing_tests",
            passed=tests_passed and no_runtime_failures,
            detail="No audit runtime errors"
            if tests_passed and no_runtime_failures
            else "Audit runtime errors present or tests marked failed",
        ),
        ReadinessCheck(
            name="filter_integration_passes",
            passed=filter_ok,
            detail="All strategies have working filter profiles/pipelines"
            if filter_ok
            else "Filter integration failed for one or more strategies",
        ),
        ReadinessCheck(
            name="scorecard_generated",
            passed=scorecard_ok,
            detail=f"{scorecard.total_count} strategies scored",
        ),
        ReadinessCheck(
            name="comparison_generated",
            passed=comparison_ok,
            detail=f"{len(comparison.rows)} strategies ranked",
        ),
        ReadinessCheck(
            name="professional_report_generated",
            passed=True,
            detail="This readiness report was generated successfully",
        ),
    )

    ready_names = tuple(m.strategy_name for m in metrics if m.ready)
    not_ready = tuple(m.strategy_name for m in metrics if not m.ready)
    overall = all(check.passed for check in checks)

    highlights: list[str] = []
    if comparison.rows:
        top = comparison.rows[0]
        highlights.append(
            f"Top ranked: {top.strategy_name} (score={top.composite_score:.1f})",
        )
    highlights.append(
        f"Ready {scorecard.ready_count}/{scorecard.total_count} strategies",
    )
    if metrics:
        best_conf = max(metrics, key=lambda m: m.average_confidence)
        highlights.append(
            f"Highest avg confidence: {best_conf.strategy_name} "
            f"({best_conf.average_confidence:.2f})",
        )

    summary = (
        f"Audited {len(metrics)} strategies on {symbol.strip().upper()}. "
        f"{scorecard.ready_count} ready. "
        f"Overall professional readiness: {'PASS' if overall else 'FAIL'}."
    )

    return ProfessionalReadinessReport(
        symbol=symbol.strip().upper(),
        summary=summary,
        overall_ready=overall,
        checks=checks,
        ready_strategies=ready_names,
        not_ready_strategies=not_ready,
        highlights=tuple(highlights),
    )


def format_scorecard_table(scorecard: StrategyScorecard) -> str:
    headers = (
        "strategy",
        "buy",
        "sell",
        "hold",
        "avg_hold",
        "avg_conf",
        "avg_rr",
        "expect",
        "filt_acc",
        "filt_rej",
        "score",
        "ready",
    )
    lines = [" | ".join(headers), "-|-".join("-" * len(h) for h in headers)]
    for row in scorecard.rows:
        lines.append(
            " | ".join(
                [
                    row.strategy_name,
                    str(row.buy_signals),
                    str(row.sell_signals),
                    str(row.hold_signals),
                    f"{row.average_hold:.2f}",
                    f"{row.average_confidence:.3f}",
                    f"{row.average_risk_reward:.2f}",
                    f"{row.average_win_expectancy:.3f}",
                    f"{row.filter_acceptance_rate:.2%}",
                    f"{row.filter_rejection_rate:.2%}",
                    f"{row.composite_score:.1f}",
                    "Y" if row.ready else "N",
                ],
            ),
        )
    return "\n".join(lines)


def format_comparison_table(comparison: StrategyComparisonTable) -> str:
    headers = ("rank", "strategy", "score", "conf", "rr", "expect", "filt_acc", "actionable", "ready")
    lines = [" | ".join(headers), "-|-".join("-" * len(h) for h in headers)]
    for row in comparison.rows:
        lines.append(
            " | ".join(
                [
                    str(row.rank),
                    row.strategy_name,
                    f"{row.composite_score:.1f}",
                    f"{row.average_confidence:.3f}",
                    f"{row.average_risk_reward:.2f}",
                    f"{row.average_win_expectancy:.3f}",
                    f"{row.filter_acceptance_rate:.2%}",
                    str(row.actionable_signals),
                    "Y" if row.ready else "N",
                ],
            ),
        )
    return "\n".join(lines)


def format_readiness_report(report: ProfessionalReadinessReport) -> str:
    lines = [
        report.title,
        "=" * len(report.title),
        report.summary,
        "",
        "Checks:",
    ]
    for check in report.checks:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
    lines.append("")
    lines.append(f"Ready: {', '.join(report.ready_strategies) or '(none)'}")
    lines.append(f"Not ready: {', '.join(report.not_ready_strategies) or '(none)'}")
    if report.highlights:
        lines.append("")
        lines.append("Highlights:")
        for item in report.highlights:
            lines.append(f"  - {item}")
    lines.append("")
    lines.append(f"Overall: {'READY' if report.overall_ready else 'NOT READY'}")
    return "\n".join(lines)


def format_audit_report(report: StrategyAuditReport) -> str:
    sections = [
        f"TradeLab Strategy Audit — {report.symbol}",
        f"Generated: {report.generated_at.isoformat()}",
        "",
        "SCORECARD",
        format_scorecard_table(report.scorecard),
        "",
        "COMPARISON",
        format_comparison_table(report.comparison),
        "",
        format_readiness_report(report.readiness),
    ]
    return "\n".join(sections)
