"""Markdown / console portfolio-risk report."""

from __future__ import annotations

from app.backtesting.portfolio_risk.schemas import PortfolioRiskResult


def format_markdown_report(result: PortfolioRiskResult) -> str:
    c = result.concentration
    d = result.drawdown
    lines = [
        "------------------------------------------------",
        "TRADELAB PORTFOLIO RISK REPORT (A5.8)",
        "------------------------------------------------",
        "",
        "PORTFOLIO SUMMARY",
        "-----------------",
        f"Initial capital: ₹{result.initial_capital:,.2f}",
        f"Final equity: ₹{result.final_equity:,.2f}",
        f"Net return: {_pct(result.net_return)}",
        f"CAGR: {_pct(result.cagr) if result.cagr is not None else 'n/a'}",
        f"Max drawdown: {_pct(result.max_drawdown_pct)}",
        f"Sharpe (event returns, 252): {result.sharpe:.3f}",
        f"Sortino (event returns, 252): {result.sortino:.3f}",
        f"Win rate: {_pct(result.win_rate)}",
        f"Profit factor: {result.profit_factor:.3f}",
        f"Trades executed: {result.executed_trade_count}",
        f"Historical trades: {result.historical_trade_count}",
        f"Symbols: {result.symbol_count}",
        f"Strategies: {result.strategy_count}",
        f"Rejections: {result.rejected_count}",
        "",
        "EXPOSURE",
        "--------",
        f"Average exposure: ₹{result.average_exposure:,.2f}",
        f"Maximum exposure: ₹{result.maximum_exposure:,.2f}",
        f"Average utilization: {result.average_utilization:.2f}%",
        f"Maximum utilization: {result.maximum_utilization:.2f}%",
        f"Maximum concurrent positions: {result.maximum_concurrent_positions}",
        "",
        "CONCENTRATION",
        "-------------",
        f"Largest symbol: {c.largest_symbol or 'n/a'} {c.largest_symbol_pct:.2f}%",
        f"Top-2: {c.top2_pct:.2f}%",
        f"Top-5: {c.top5_pct:.2f}%",
        f"Largest strategy: {c.largest_strategy or 'n/a'} {c.largest_strategy_pct:.2f}%",
        f"HHI: {c.hhi:.4f} ({c.hhi_10000:.1f} / 10000)",
        f"Peak largest symbol: {c.peak_largest_symbol_pct:.2f}%",
        c.note,
        "",
        "CORRELATION",
        "-----------",
        _corr_block("Symbols", result.symbol_correlation),
        _corr_block("Strategies", result.strategy_correlation),
        "",
        "RISK",
        "----",
        f"Historical max drawdown: {_pct(d.max_drawdown_pct)}",
        f"Drawdown duration (events): {d.duration_events}",
        f"Recovery (events): {d.recovery_events if d.recovery_events is not None else 'not recovered'}",
        f"Worst period loss: ₹{d.worst_period_loss:,.2f}",
        d.note,
        f"P(loss): {_opt_pct(result.probability_of_loss)}",
        f"P(profit): {_opt_pct(result.probability_of_profit)}",
        f"P(ruin): {_opt_pct(result.probability_of_ruin)}",
    ]
    if result.drawdown_percentiles is not None:
        lines.append(f"P95 |DD|: {_pct(result.drawdown_percentiles.p95)}")
        lines.append(f"P99 |DD|: {_pct(result.drawdown_percentiles.p99)}")
    for key, value in result.threshold_probabilities.items():
        lines.append(f"  {key}: {_pct(value)}")
    if result.return_percentiles is not None:
        lines.extend(
            [
                "",
                "MONTE CARLO DISTRIBUTION",
                "------------------------",
                f"Simulations: {result.simulation_count:,}",
                f"Seed: {result.seed}",
                f"Sample quality: {result.sample_quality}",
                f"Median return: {_pct(result.return_percentiles.p50)}",
                f"P05 return: {_pct(result.return_percentiles.p05)}",
                f"P95 return: {_pct(result.return_percentiles.p95)}",
                f"{result.simulation_count:,} simulations generated from "
                f"{result.historical_trade_count} historical trades.",
            ],
        )
    if result.a57_median_return is not None:
        lines.extend(
            [
                "",
                "A5.7 vs A5.8",
                "------------",
                f"A5.7 median return: {_pct(result.a57_median_return)}  "
                f"P(loss): {_opt_pct(result.a57_probability_of_loss)}  "
                f"P95 DD: {_opt_pct(result.a57_p95_drawdown)}",
                f"A5.8 median return: "
                f"{_pct(result.return_percentiles.p50) if result.return_percentiles else 'n/a'}  "
                f"P(loss): {_opt_pct(result.probability_of_loss)}",
                result.a57_note,
            ],
        )
    lines.extend(["", "COSTS", "-----"])
    lines.append(f"Brokerage: ₹{result.total_brokerage:,.2f}")
    lines.append(f"Slippage: ₹{result.total_slippage:,.2f}")
    lines.append(f"Total costs: ₹{result.total_costs:,.2f}")
    lines.append(
        "Cost as % of |gross|: "
        + (_pct(result.cost_pct_of_gross) if result.cost_pct_of_gross is not None else "n/a"),
    )
    lines.extend(["", "COST SENSITIVITY", "----------------"])
    if result.cost_sensitivity:
        for row in result.cost_sensitivity:
            lines.append(
                f"  {row.slippage_bps:g} bps: median return {_pct(row.median_return)} "
                f"P(loss) {_pct(row.probability_of_loss)} "
                f"P95 |DD| {_pct(row.p95_max_drawdown)} "
                f"total_cost ₹{row.total_execution_cost:,.2f} "
                f"incremental_cost ₹{row.incremental_cost:,.2f} "
                f"brokerage ₹{row.brokerage_cost:,.2f} "
                f"slippage ₹{row.slippage_cost:,.2f} "
                f"median equity ₹{row.median_ending_equity:,.2f}",
            )
    else:
        lines.append("  (not requested)")
    lines.extend(["", "REJECTIONS", "----------"])
    if result.rejections:
        for item in result.rejections[:50]:
            lines.append(
                f"  {item.timestamp.date()} {item.symbol} {item.status.value} "
                f"{item.reason_code.value if item.reason_code else ''} {item.reason}",
            )
    else:
        lines.append("  none")
    lines.extend(["", "WARNINGS", "--------"])
    for warning in result.warnings:
        lines.append(f"  - {warning}")
    lines.extend(
        [
            "",
            result.limitation,
            "This report does not prove future profitability.",
        ],
    )
    return "\n".join(lines) + "\n"


def _corr_block(title: str, report) -> str:
    if report.insufficient:
        extra = "; ".join(report.insufficient_pairs[:6])
        return (
            f"{title}: insufficient aligned observations. "
            f"{report.note} {extra}"
        )
    pairs = ", ".join(
        f"{p['a']}/{p['b']}={float(p['correlation']):.2f}" for p in report.highly_correlated_pairs[:5]
    ) or "none"
    return (
        f"{title}: avg pairwise {report.average_pairwise:.3f}, "
        f"max {report.maximum_pairwise:.3f}, highly correlated: {pairs}"
    )


def _pct(value: float) -> str:
    return f"{value * 100.0:.2f}%"


def _opt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _pct(value)
