"""Markdown / console Monte Carlo report. Not a profitability endorsement."""

from __future__ import annotations

from app.backtesting.monte_carlo.schemas import MonteCarloResult, PercentileSummary


def format_console_report(result: MonteCarloResult) -> str:
    return format_markdown_report(result)


def format_markdown_report(result: MonteCarloResult) -> str:
    h = result.historical
    r = result.return_percentiles
    dd = result.max_drawdown_abs_percentiles
    streak = result.longest_losing_streak_percentiles
    cap = result.final_capital_percentiles
    lines = [
        "------------------------------------------------",
        "TRADELAB MONTE CARLO REPORT",
        "------------------------------------------------",
        "",
        f"Strategy: {result.strategy or 'n/a'}",
        f"Symbol: {result.symbol or 'n/a'}",
        f"Period: {result.period or 'n/a'}",
        f"Initial Capital: ₹{result.initial_capital:,.2f}",
        f"Historical Trades: {result.source_trade_count}",
        f"Simulations: {result.simulations:,}",
        f"Seed: {result.seed}",
        f"Method: {result.sampling_method.value}",
        "",
        "Historical Backtest (original trade order, additive net_profit):",
        f"Return: {_pct(h.return_pct)}",
        f"Max Drawdown: {_pct(h.max_drawdown)}",
        f"Sharpe (trade-level, not annualized): {h.sharpe_trade_level:.3f}",
        f"Trades: {h.trades}",
        f"Win rate: {_pct(h.win_rate)}",
        f"Net profit: ₹{h.net_profit:,.2f}",
        "",
        "Monte Carlo:",
        f"Median Return: {_pct(r.p50)}",
        f"P05 Return: {_pct(r.p05)}",
        f"P95 Return: {_pct(r.p95)}",
        "",
        f"Median |Max DD|: {_pct(-dd.p50)}",
        f"P95 |Max DD|: {_pct(-dd.p95)}",
        f"P99 |Max DD|: {_pct(-dd.p99)}",
        "",
        f"Probability of Loss: {_pct(result.probability_of_loss)}",
        f"Probability of Profit: {_pct(result.probability_of_profit)}",
        f"Probability of Ruin: {_pct(result.probability_of_ruin)}",
        f"Ruin definition: {result.ruin_definition}",
        "",
        f"Longest Losing Streak P50: {streak.p50:.0f}",
        f"P95 Losing Streak: {streak.p95:.0f}",
        "",
        "Final Capital",
        *_percentile_block(cap, money=True),
        "",
        "Total Return",
        *_percentile_block(r, pct=True),
        "",
        "Max Drawdown magnitude (P99 = more severe)",
        *_percentile_block(dd, pct=True, negate=True),
        "",
        "Threshold probabilities:",
    ]
    for key, value in result.threshold_probabilities.items():
        lines.append(f"  {key}: {_pct(value)}")
    lines.extend(["", "Execution Cost Sensitivity:"])
    if result.cost_sensitivity:
        for row in result.cost_sensitivity:
            lines.append(
                f"  slippage={row.slippage_bps:g} bps comm×{row.commission_mult:g}: "
                f"median return {_pct(row.median_return)} "
                f"P95 |DD| {_pct(row.p95_max_drawdown)} "
                f"P(loss) {_pct(row.probability_of_loss)} "
                f"P(profit) {_pct(row.probability_of_profit)}",
            )
    else:
        lines.append("  (not requested)")
    lines.extend(
        [
            "",
            f"Overall Robustness: {result.robustness.band.value} (score {result.robustness.score:.1f}/100)",
            f"Formula: {result.robustness.formula}",
            "Reasons:",
        ],
    )
    for reason in result.robustness.reasons:
        lines.append(f"  - {reason}")
    lines.extend(["", "Warnings:"])
    if result.warnings:
        for warning in result.warnings:
            lines.append(f"  - {warning}")
    else:
        lines.append("  - none")
    lines.extend(
        [
            "",
            "This report does not prove future profitability. "
            "Simulations resample completed historical trades only.",
        ],
    )
    return "\n".join(lines) + "\n"


def _percentile_block(
    summary: PercentileSummary,
    *,
    money: bool = False,
    pct: bool = False,
    negate: bool = False,
) -> list[str]:
    rows = []
    for label, value in (
        ("P01", summary.p01),
        ("P05", summary.p05),
        ("P10", summary.p10),
        ("P25", summary.p25),
        ("P50", summary.p50),
        ("P75", summary.p75),
        ("P90", summary.p90),
        ("P95", summary.p95),
        ("P99", summary.p99),
    ):
        number = -value if negate else value
        if money:
            rendered = f"₹{number:,.2f}"
        elif pct:
            rendered = _pct(number)
        else:
            rendered = f"{number:.4f}"
        rows.append(f"  {label}: {rendered}")
    return rows


def _pct(value: float) -> str:
    return f"{value * 100.0:.2f}%"
