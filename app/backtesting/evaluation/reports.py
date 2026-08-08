"""Text / Markdown report formatting for EMA evaluation."""

from __future__ import annotations

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
        "Signal Reduction",
        f"{funnel.signal_reduction_pct:.1f}%",
        "",
        "EMA200 Filter",
        f"Rejected {funnel.rejected_ema200}",
        "",
        "ADX Filter",
        f"Rejected {funnel.rejected_adx}",
        "",
        "Volume Filter",
        f"Rejected {funnel.rejected_volume}",
        "",
        "ATR Filter",
        f"Rejected {funnel.rejected_atr}",
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
            "## Signal Funnel",
            "",
            f"- Raw BUY/SELL: {report.signal_funnel.raw_buy} / {report.signal_funnel.raw_sell}",
            f"- Professional BUY/SELL: {report.signal_funnel.professional_buy} / {report.signal_funnel.professional_sell}",
            f"- Rejected EMA200/ADX/Volume/ATR/Other: "
            f"{report.signal_funnel.rejected_ema200}/"
            f"{report.signal_funnel.rejected_adx}/"
            f"{report.signal_funnel.rejected_volume}/"
            f"{report.signal_funnel.rejected_atr}/"
            f"{report.signal_funnel.rejected_other}",
            f"- Acceptance Rate: {report.signal_funnel.acceptance_rate:.2%}",
            f"- Rejection Rate: {report.signal_funnel.rejection_rate:.2%}",
            f"- Signal Reduction: {report.signal_funnel.signal_reduction_pct:.1f}%",
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
