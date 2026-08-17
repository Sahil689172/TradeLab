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
        f"Engine: {result.engine_kind}",
        "",
        "HISTORICAL OBSERVATION",
        "----------------------",
        f"Historical trades: {result.source_trade_count}",
        f"Historical return: {_pct(h.return_pct)}",
        f"Historical drawdown: {_pct(h.max_drawdown)}",
        f"Historical win rate: {_pct(h.win_rate)}",
        f"Historical net profit: ₹{h.net_profit:,.2f}",
        f"Sharpe (trade-level, not annualized): {h.sharpe_trade_level:.3f}",
        f"Initial capital: ₹{result.initial_capital:,.2f}",
        "",
        "MONTE CARLO CONFIGURATION",
        "-------------------------",
        f"Method: {result.sampling_method.value}",
        f"Simulations: {result.simulations:,}",
        f"Seed: {result.seed}",
        f"Capital model: {result.capital_model or result.capital_mode.value}",
        f"Block size: {result.block_size if result.block_size is not None else 'n/a'}",
        f"{result.simulations:,} simulations generated from {result.source_trade_count} historical trades.",
        result.resampling_limitation,
        "",
    ]
    if result.engine_kind == "PathDependentPortfolioMonteCarlo":
        lines.extend(
            [
                "PATH-DEPENDENT CAPITAL MODEL",
                "----------------------------",
                f"Position sizing: {result.position_sizing_mode or 'n/a'}",
                f"Position size parameters: {result.position_size_parameters}",
                f"Execution cost parameters: {result.execution_cost_parameters}",
                "Each trade is sized from current cash after the previous round-trip.",
                "Historical rupee net_profit is not added.",
                "",
            ],
        )
    if result.comparison is not None:
        c = result.comparison
        lines.extend(
            [
                "A5.6 vs A5.7",
                "------------",
                f"A5.6 median return: {_pct(c.resampling_median_return)}  "
                f"P95 |DD|: {_pct(c.resampling_p95_max_drawdown)}  "
                f"P(loss): {_pct(c.resampling_probability_of_loss)}",
                f"A5.7 median return: {_pct(c.path_dependent_median_return)}  "
                f"P95 |DD|: {_pct(c.path_dependent_p95_max_drawdown)}  "
                f"P(loss): {_pct(c.path_dependent_probability_of_loss)}",
                c.modeling_difference,
                "A5.7 is not 'better' merely because a number is larger or smaller.",
                "",
            ],
        )
    lines.extend(
        [
        "DISTRIBUTION",
        "------------",
        "Monte Carlo percentile interval (numpy.percentile method='linear'; "
        "not a statistical confidence interval).",
        f"Percentile method: {result.percentile_method}",
        "",
        f"Median return: {_pct(r.p50)}",
        f"P05 return: {_pct(r.p05)}",
        f"P95 return: {_pct(r.p95)}",
        f"Median |max DD|: {_pct(-dd.p50)}",
        f"P95 |max DD|: {_pct(-dd.p95)}",
        f"P99 |max DD|: {_pct(-dd.p99)}",
        "",
        "Ending equity (Monte Carlo percentile interval)",
        *_percentile_block(cap, money=True),
        "",
        "Ending return (Monte Carlo percentile interval)",
        *_percentile_block(r, pct=True),
        "",
        "Max drawdown magnitude (P99 = more severe)",
        *_percentile_block(dd, pct=True, negate=True),
        "",
        "Losing streak (Monte Carlo percentile interval)",
        *_percentile_block(streak, pct=False),
        "",
        "RISK",
        "----",
        f"P(loss) / P(ending below initial capital): {_pct(result.probability_of_loss)}",
        f"P(profit): {_pct(result.probability_of_profit)}",
        f"P(ruin): {_pct(result.probability_of_ruin)}",
        f"Ruin definition: {result.ruin_definition}",
        f"Worst losing streak (worst-case path): "
        f"{result.worst_case.longest_losing_streak if result.worst_case else 0}",
        f"P95 losing streak: {streak.p95:.0f}",
        "",
        "Threshold probabilities:",
        ]
    )
    for key, value in result.threshold_probabilities.items():
        lines.append(f"  {key}: {_pct(value)}")
    rm = result.risk_metrics
    if rm is not None:
        lines.extend(
            [
                "",
                "TAIL RISK (VaR / CVaR)",
                "----------------------",
                "Positive = loss. Empirical Monte Carlo tail of the simulated return "
                "distribution (not parametric VaR, not a maximum-loss guarantee).",
                f"VaR 95%: {_pct(rm.var_return_95)}  (₹{rm.var_capital_95:,.2f})",
                f"CVaR/ES 95%: {_pct(rm.cvar_return_95)}  (₹{rm.cvar_capital_95:,.2f})",
                f"VaR 99%: {_pct(rm.var_return_99)}  (₹{rm.var_capital_99:,.2f})",
                f"CVaR/ES 99%: {_pct(rm.cvar_return_99)}  (₹{rm.cvar_capital_99:,.2f})",
            ]
        )
    lines.extend(["", "COST SENSITIVITY", "----------------"])
    if result.cost_sensitivity:
        for row in result.cost_sensitivity:
            lines.append(
                f"  slippage={row.slippage_bps:g} bps comm×{row.commission_mult:g}: "
                f"median return {_pct(row.median_return)} "
                f"P95 |DD| {_pct(row.p95_max_drawdown)} "
                f"P(loss) {_pct(row.probability_of_loss)} "
                f"P(profit) {_pct(row.probability_of_profit)} "
                f"base_cost ₹{row.base_cost:,.2f} "
                f"scenario_cost ₹{row.scenario_cost:,.2f} "
                f"incremental_cost ₹{row.incremental_cost:,.2f} "
                f"brokerage_cost ₹{row.brokerage_cost:,.2f} "
                f"slippage_cost ₹{row.slippage_cost:,.2f} "
                f"total_execution_cost ₹{row.total_execution_cost:,.2f} "
                f"median equity ₹{row.median_ending_equity:,.2f} "
                f"final_simulated_pnl ₹{row.final_simulated_pnl:,.2f}",
            )
    else:
        lines.append("  (not requested)")
    lines.extend(
        [
            "",
            "SAMPLE QUALITY",
            "--------------",
            f"Historical trade count: {result.source_trade_count}",
            f"Simulation count: {result.simulations:,}",
            f"Sample quality: {result.sample_quality.value}",
            "Sample-quality labels are reporting quality, not statistical sufficiency.",
            "",
            "Warnings:",
        ],
    )
    if result.warnings:
        for warning in result.warnings:
            lines.append(f"  - {warning}")
    else:
        lines.append("  - none")
    lines.extend(
        [
            "",
            "VERDICT",
            "-------",
            result.verdict.value,
            f"Overall Robustness: {result.robustness.band.value} (score {result.robustness.score:.1f}/100)",
            "The robustness band is a diagnostic score. The verdict is capped by "
            "historical sample size. A favorable simulated distribution cannot "
            "upgrade INSUFFICIENT_EVIDENCE.",
            f"Formula: {result.robustness.formula}",
            "Reasons:",
        ],
    )
    for reason in result.robustness.reasons:
        lines.append(f"  - {reason}")
    lines.extend(
        [
            "",
            "This report does not prove future profitability. "
            "Monte Carlo simulations resample historical evidence; they do not "
            "create new independent historical observations.",
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
