"""Text / Markdown report formatting for EMA evaluation."""

from __future__ import annotations

from app.backtesting.evaluation.funnel_semantics import format_semantic_funnel
from app.backtesting.evaluation.schemas import EvaluationReport


def format_console_report(report: EvaluationReport) -> str:
    raw = report.raw
    pro = report.professional
    funnel = report.signal_funnel
    meta = report.metadata or {}
    validity = meta.get("validity") or {}
    lines = [
        "=" * 48,
        "TradeLab Professional EMA Evaluation",
        "=" * 48,
        "",
        "Evaluation Resolution",
        str(meta.get("evaluation_resolution", "n/a")),
        f"stride={meta.get('stride', 'n/a')}",
        f"capital_mode={meta.get('capital_mode', 'n/a')}",
        "",
        "Universe",
        f"{len(report.symbols)} Stocks",
        "",
        "Period",
        f"{report.period_start or 'n/a'} - {report.period_end or 'n/a'}",
        "",
        "Raw",
        "Trades",
        f"{raw.total_trades}",
        "Win Rate",
        f"{raw.win_rate:.1%}",
        "Sharpe",
        f"{raw.sharpe_ratio:.2f}",
        "Max DD",
        f"{raw.max_drawdown:.1%}",
        "Net Return",
        f"{raw.return_pct:.1%}",
        "",
        "-" * 48,
        "",
        "Professional",
        "Trades",
        f"{pro.total_trades}",
        "Win Rate",
        f"{pro.win_rate:.1%}",
        "Sharpe",
        f"{pro.sharpe_ratio:.2f}",
        "Max DD",
        f"{pro.max_drawdown:.1%}",
        "Net Return",
        f"{pro.return_pct:.1%}",
        "",
        "-" * 48,
        "",
        "Validity",
        "OK" if validity.get("ok", True) else "FAILED",
        ", ".join(validity.get("reasons") or []) or "none",
        "",
        "-" * 48,
        "",
        format_semantic_funnel(funnel),
        "",
        "-" * 48,
        "",
        "Overall Improvement",
        "PASS" if report.overall_improvement else "FAIL",
        "",
        "Professional Strategy Recommended",
        "YES" if report.professional_recommended else "NO",
        "",
        "=" * 48,
        "",
        "Executive Summary",
        report.executive_summary,
    ]
    return "\n".join(lines)


def format_markdown_report(report: EvaluationReport) -> str:
    raw = report.raw
    pro = report.professional
    meta = report.metadata or {}
    validity = meta.get("validity") or {}
    lines = [
        f"# {report.title}",
        "",
        f"- Phase: `{report.phase}`",
        f"- Generated: `{report.generated_at.isoformat()}`",
        f"- Symbols ({len(report.symbols)}): {', '.join(report.symbols)}",
        f"- Period: {report.period_start or 'n/a'} → {report.period_end or 'n/a'}",
        f"- Evaluation Resolution: `{meta.get('evaluation_resolution', 'n/a')}`",
        f"- Stride: `{meta.get('stride', 'n/a')}`",
        f"- Capital Mode: `{meta.get('capital_mode', 'n/a')}`",
        f"- Cost Model: `{meta.get('cost_model', 'n/a')}`",
        f"- Validity: `{'OK' if validity.get('ok', True) else 'FAILED'}` "
        f"({', '.join(validity.get('reasons') or []) or 'none'})",
        "",
        "## Executive Summary",
        "",
        report.executive_summary,
        "",
        f"**Overall Improvement:** {'PASS' if report.overall_improvement else 'FAIL'}  ",
        f"**Professional Recommended:** {'YES' if report.professional_recommended else 'NO'}",
        "",
        "## Performance Comparison",
        "",
        "| Metric | Raw | Professional | Delta | Verdict |",
        "|---|---:|---:|---:|---|",
    ]
    for row in report.metric_comparisons:
        lines.append(
            f"| {row.metric} | {row.raw_value:.4f} | {row.professional_value:.4f} | "
            f"{row.delta:.4f} | {row.verdict.value} |",
        )
    lines.extend(
        [
            "",
            "## Raw Metrics",
            "",
            f"- Trades: {raw.total_trades}",
            f"- Win Rate: {raw.win_rate:.2%}",
            f"- Sharpe: {raw.sharpe_ratio:.3f}",
            f"- Sortino: {raw.sortino_ratio:.3f}",
            f"- Max DD: {raw.max_drawdown:.2%}",
            f"- CAGR: {raw.cagr:.2%}",
            f"- Net Profit: {raw.net_profit:.2f}",
            f"- Profit Factor: {raw.profit_factor:.3f}",
            "",
            "## Professional Metrics",
            "",
            f"- Trades: {pro.total_trades}",
            f"- Win Rate: {pro.win_rate:.2%}",
            f"- Sharpe: {pro.sharpe_ratio:.3f}",
            f"- Sortino: {pro.sortino_ratio:.3f}",
            f"- Max DD: {pro.max_drawdown:.2%}",
            f"- CAGR: {pro.cagr:.2%}",
            f"- Net Profit: {pro.net_profit:.2f}",
            f"- Profit Factor: {pro.profit_factor:.3f}",
            "",
            "## Signal Funnel (A4Y.1.7.3 layers)",
            "",
            f"- funnel_mode: `{report.signal_funnel.funnel_mode}` "
            f"(sequential first-fail; sequential_reconciles="
            f"{report.signal_funnel.sequential_funnel_reconciles})",
            f"- Technical crossovers: above={report.signal_funnel.technical_cross_above} "
            f"below={report.signal_funnel.technical_cross_below}",
            f"- Raw strategy signals: BUY={report.signal_funnel.raw_strategy_buy_signals} "
            f"EXIT={report.signal_funnel.raw_strategy_exit_signals}",
            f"- Professional BUY candidates (EMA9/21 crosses, not raw BUY): "
            f"{report.signal_funnel.professional_buy_candidates}",
            f"- Sequential BUY remaining: "
            f"EMA200→{report.signal_funnel.remaining_after_ema200} "
            f"ADX→{report.signal_funnel.remaining_after_adx} "
            f"Volume→{report.signal_funnel.remaining_after_volume} "
            f"ATR→{report.signal_funnel.remaining_after_atr}",
            f"- Rejections EMA200/ADX/Volume/ATR/Other: "
            f"{report.signal_funnel.ema200_rejections}/"
            f"{report.signal_funnel.adx_rejections}/"
            f"{report.signal_funnel.volume_rejections}/"
            f"{report.signal_funnel.atr_rejections}/"
            f"{report.signal_funnel.other_rejections}",
            f"- Professional BUY signals (final): {report.signal_funnel.professional_buy_signals}",
            f"- Professional EXIT signals: {report.signal_funnel.professional_exit_signals}",
            f"- Completed trades: raw={report.signal_funnel.raw_completed_trades} "
            f"professional={report.signal_funnel.professional_completed_trades}",
            f"- BUY candidate reduction: "
            f"{report.signal_funnel.professional_buy_candidate_reduction_pct:.1f}% "
            f"(candidates - final_buy) / candidates",
            "",
            "## Filter Effectiveness",
            "",
            "| Filter | Examined | Rejected | Accepted | Improvement % |",
            "|---|---:|---:|---:|---:|",
        ],
    )
    for row in report.filter_effectiveness:
        lines.append(
            f"| {row.filter_name} | {row.signals_examined} | {row.signals_rejected} | "
            f"{row.signals_accepted} | {row.improvement_pct:.2f} |",
        )
    lines.extend(
        [
            "",
            "## Risk Report",
            "",
            f"- Raw Ulcer Index: {raw.ulcer_index:.4f}",
            f"- Professional Ulcer Index: {pro.ulcer_index:.4f}",
            f"- Raw Volatility: {raw.volatility:.4f}",
            f"- Professional Volatility: {pro.volatility:.4f}",
            f"- Raw Recovery Factor: {raw.recovery_factor:.4f}",
            f"- Professional Recovery Factor: {pro.recovery_factor:.4f}",
            "",
            "## Statistics",
            "",
            f"- Paired mean delta: {report.statistics.paired_mean_delta:.4f}",
            f"- Bootstrap CI: [{report.statistics.bootstrap_ci_low:.4f}, {report.statistics.bootstrap_ci_high:.4f}]",
            f"- Significance: {report.statistics.significance}",
            f"- Verdict: {report.statistics.overall_verdict.value}",
            "",
        ],
    )
    for note in report.statistics.notes:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
