"""Markdown walk-forward report. Not a profitability endorsement."""

from __future__ import annotations

from app.backtesting.walk_forward.schemas import WalkForwardResult


def format_markdown_report(result: WalkForwardResult) -> str:
    cfg = result.config
    deg = result.degradation
    stab = result.parameter_stability
    leak = result.leakage
    lines = [
        "TRADELAB WALK-FORWARD VALIDATION",
        "================================",
        "",
        f"Strategy: {cfg.strategy_alias}",
        f"Requested strategy: {result.strategy_identity.requested_strategy if result.strategy_identity else cfg.strategy_alias}",
        f"Execution engine: {result.strategy_identity.execution_engine if result.strategy_identity else 'ema_trend'}",
        f"Symbol: {', '.join(result.symbols)}",
        f"Period: {_period(result)}",
        "",
        "Configuration:",
        f"Train period: {cfg.train_years} year(s)"
        + (f" / {cfg.train_days} day(s)" if cfg.train_days else ""),
        f"Test period: {cfg.test_years} year(s)"
        + (f" / {cfg.test_days} day(s)" if cfg.test_days else ""),
        f"Step: {cfg.step_years} year(s)"
        + (f" / {cfg.step_days} day(s)" if cfg.step_days else ""),
        f"Capital mode: {result.capital_mode.value}",
        f"Initial capital: ₹{result.initial_capital:,.2f}",
        f"Selection scope: {cfg.selection_scope.value}",
        "",
        "WINDOW SUMMARY",
        "---------------",
        "",
        "Window | Symbol | Train | Test | Selected Config | Train Return | OOS Return | OOS DD | OOS Trades",
        "------ | ------ | ----- | ---- | ---------------- | ------------ | ---------- | ------ | ----------",
    ]
    for row in result.windows:
        w = row.window
        lines.append(
            f"{w.window_id} | {row.symbol} | {w.train_label} | {w.test_label} | "
            f"{row.selected.config_key} | {_pct(row.train.return_pct)} | "
            f"{_pct(row.oos.return_pct)} | {_pct(row.oos.max_drawdown)} | {row.oos_trade_count}",
        )
    if not result.windows:
        lines.append("(no complete windows)")
    lines.extend(
        [
            "",
            "TRAIN SELECTION ELIGIBILITY",
            "---------------------------",
            f"Minimum training trades: {cfg.minimum_training_trades}",
            "",
            "Window | Symbol | Status | Selected train trades | Required | Eligible | Ineligible",
            "------ | ------ | ------ | --------------------- | -------- | -------- | ----------",
        ],
    )
    for row in result.windows:
        sel = row.train_selection
        if sel is None:
            lines.append(
                f"{row.window.window_id} | {row.symbol} | (n/a) | {row.train.trade_count} | "
                f"{cfg.minimum_training_trades} | n/a | n/a",
            )
            continue
        status = sel.selected_eligibility.value
        lines.append(
            f"{row.window.window_id} | {row.symbol} | {status} | "
            f"{sel.selected_training_trade_count} | {sel.minimum_training_trades} | "
            f"{sel.eligible_count} | {sel.ineligible_count}",
        )
        if sel.selected_eligibility.value == "FALLBACK_INELIGIBLE":
            lines.append(
                f"  WARNING window {row.window.window_id}: {sel.note}",
            )
    lines.extend(
        [
            "",
            "ACCOUNTING",
            "----------",
            f"Model: {result.accounting_model}",
            result.accounting_note or "(see docs/walk_forward_validation.md)",
            f"Ledger check: final equity = initial + Σ net_profit "
            f"(₹{result.initial_capital:,.2f} + ₹{result.oos_net_profit:,.2f} "
            f"= ₹{result.initial_capital + result.oos_net_profit:,.2f})",
            "",
            "COMBINED OOS",
            "------------",
            "",
            f"OOS Trades: {result.oos_trade_count}",
            f"Historical OOS trades: {result.historical_oos_trades}",
            f"Combined OOS return (ledger/compounded equity): {_pct(result.combined_oos_return)}",
            f"Mean window OOS return (arithmetic mean of per-window returns): {_pct(result.mean_window_oos_return)}",
            f"OOS return (alias of combined): {_pct(result.oos_return)}",
            f"OOS CAGR: {_pct(result.oos_cagr) if result.oos_cagr is not None else 'n/a'}",
            f"OOS Sharpe ({result.oos_sharpe_methodology}): {_metric(result.oos_sharpe, result.oos_sharpe_status)}",
            f"OOS Sharpe (raw): {_num(result.oos_sharpe_raw)}",
            f"OOS Sortino ({result.oos_sortino_methodology}): {_metric(result.oos_sortino, result.oos_sortino_status)}",
            f"OOS Max DD: {_pct(result.oos_max_drawdown)}",
            f"OOS Win Rate: {_metric(result.oos_win_rate, result.oos_win_rate_status, pct=True)}",
            f"OOS Profit Factor: {_metric(result.oos_profit_factor, result.oos_profit_factor_status)}",
            f"Gross profit: ₹{result.oos_gross_profit:,.2f}",
            f"Net profit: ₹{result.oos_net_profit:,.2f}",
            f"Total Costs: ₹{result.oos_total_costs:,.2f}",
            f"Cost % of |gross|: {_pct(result.oos_cost_pct_of_gross) if result.oos_cost_pct_of_gross is not None else 'n/a'}",
            f"Final OOS equity: ₹{result.final_oos_equity:,.2f}",
            "",
            "OOS EXECUTION ATTRIBUTION",
            "-------------------------",
            f"Signals generated (BUY/SELL): {result.oos_attribution.signals_generated}",
            f"Hold bars (no order): {result.oos_attribution.no_order_for_signal}",
            f"Orders attempted: {result.oos_attribution.orders_attempted}",
            f"Orders filled: {result.oos_attribution.orders_filled}",
            f"Orders rejected (execution constraints): {result.oos_attribution.orders_rejected}",
            f"Completed trades: {result.oos_attribution.completed_trades}",
            f"Rejected — insufficient cash: {result.oos_attribution.rejected_insufficient_cash}",
            f"Rejected — below min quantity: {result.oos_attribution.rejected_below_min_quantity}",
            f"Rejected — no open position: {result.oos_attribution.rejected_no_open_position}",
            f"Rejected — already holding: {result.oos_attribution.rejected_already_holding}",
            f"Legacy rejected-order count: {result.oos_rejected_count}",
            "",
            "OOS BY YEAR",
            "-----------",
        ],
    )
    if result.oos_by_year:
        for year, ret in result.oos_by_year.items():
            lines.append(f"{year}: {_pct(ret)}")
    else:
        lines.append("(none)")
    lines.extend(["", "OOS BY SYMBOL", "-------------"])
    if result.oos_by_symbol:
        for symbol, ret in result.oos_by_symbol.items():
            lines.append(f"{symbol}: {_pct(ret)}")
    else:
        lines.append("(none)")
    lines.extend(
        [
            "",
            "DEGRADATION (DESCRIPTIVE DIAGNOSTIC)",
            "------------------------------------",
            "",
            f"Train Return: {_pct(deg.train_return)}",
            f"Mean window OOS return: {_pct(result.mean_window_oos_return)}",
            f"Combined OOS return (not used in degradation): {_pct(result.combined_oos_return)}",
            f"OOS Return (degradation uses mean per-window): {_pct(deg.oos_return)}",
            f"Return ratio (OOS/Train): {_num(deg.return_ratio)}",
            f"Return degradation: {_pct(deg.return_degradation_pct)}",
            f"Train Sharpe: {deg.train_sharpe:.3f}",
            f"OOS Sharpe: {_metric(deg.oos_sharpe, deg.oos_sharpe_status)}",
            f"Sharpe ratio (OOS/Train): {_num(deg.sharpe_ratio)}",
            f"Sharpe degradation: {_pct(deg.sharpe_degradation_pct)}",
            f"Train win rate: {_pct(deg.train_win_rate)}",
            f"OOS win rate: {_metric(deg.oos_win_rate, deg.oos_win_rate_status, pct=True)}",
            f"Win-rate ratio: {_num(deg.win_rate_ratio)}",
            f"Win-rate degradation: {_pct(deg.win_rate_degradation_pct)}",
            f"Train profit factor: {deg.train_profit_factor:.3f}",
            f"OOS profit factor: {_metric(deg.oos_profit_factor, deg.oos_profit_factor_status)}",
            f"Profit-factor ratio: {_num(deg.profit_factor_ratio)}",
            f"Profit-factor degradation: {_pct(deg.profit_factor_degradation_pct)}",
            f"OOS trade count (degradation context): {deg.oos_trade_count}",
            f"Sample flag: {deg.sample_flag or 'n/a'}",
            deg.note,
            f"Degradation compares: {deg.compares}",
            _caution(deg.return_ratio, cfg.degradation_return_caution, "return"),
            _caution(deg.sharpe_ratio, cfg.degradation_sharpe_caution, "Sharpe"),
            "",
            "PARAMETER STABILITY",
            "-------------------",
            "",
            f"History: {', '.join(stab.history) if stab.history else '(none)'}",
            f"Changes: {stab.changes}",
            f"Most frequent: {stab.most_frequent or '(none)'}",
            f"Stability score: {stab.stability_score:.3f}",
            f"Unique configs: {stab.unique_config_count}",
            f"Windows: {stab.window_count}",
            f"OOS trades (coverage): {stab.oos_trade_count}",
            f"Coverage status: {stab.coverage_status.value}",
            f"Interpretation: {stab.interpretation}",
        ],
    )
    for key, freq in sorted(stab.frequency.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {key}: {freq}")
    lines.append(stab.note)
    lines.extend(
        [
            "",
            "LEAKAGE VALIDATION",
            "------------------",
            "",
            f"{'PASS' if leak.passed else 'FAIL'}",
            f"Train before test: {leak.train_before_test}",
            f"No overlap: {leak.no_overlap}",
            f"No duplicate boundary: {leak.no_duplicate_boundary}",
            f"Warmup capped at period end: {leak.warmup_capped_at_period_end}",
            f"Train selection ignores test: {leak.train_selection_ignores_test}",
        ],
    )
    for detail in leak.details:
        lines.append(f"- {detail}")
    lines.extend(
        [
            "",
            "MONTE CARLO",
            "-----------",
            "",
            result.monte_carlo_label,
            f"Historical OOS trades: {result.historical_oos_trades}",
            f"Simulation count: {result.simulation_count:,}",
            "Monte Carlo resamples historical OOS trades only; simulation count does not increase historical sample size.",
        ],
    )
    if result.monte_carlo_simulations:
        lines.append(f"P(loss): {_pct(result.monte_carlo_probability_of_loss)}")
        lines.append(f"Median simulated return: {_pct(result.monte_carlo_median_return)}")
    else:
        lines.append("Monte Carlo was not requested or had no OOS trades.")
    lines.extend(
        [
            "",
            "FINAL VERDICT",
            "------------",
            "",
            result.verdict.value,
            f"Sample quality: {result.sample_quality.value}",
            f"Historical OOS trades: {result.historical_oos_trades}",
            f"Monte Carlo simulations: {result.simulation_count:,} (does not increase historical sample size)",
            "Do not treat a favorable simulated distribution as ROBUST when the OOS sample is small.",
            "",
            "WARNINGS",
            "--------",
        ],
    )
    for warning in result.warnings:
        lines.append(f"- {warning}")
    lines.extend(["", result.limitation, ""])
    return "\n".join(lines)


def _period(result: WalkForwardResult) -> str:
    if not result.windows:
        return "n/a"
    first = result.windows[0].window
    last = result.windows[-1].window
    return f"{first.train_start.isoformat()} → {last.test_end.isoformat()}"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * float(value):.2f}%"


def _num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.3f}"


def _metric(value: float | None, status: object, *, pct: bool = False) -> str:
    if value is None:
        label = getattr(status, "value", str(status))
        return f"n/a ({label})"
    if pct:
        return _pct(value)
    return f"{float(value):.3f}"


def _caution(ratio: float | None, threshold: float, label: str) -> str:
    if ratio is None:
        return f"{label} caution band: not applicable (train metric near zero)."
    if ratio < threshold:
        return (
            f"{label} ratio {ratio:.3f} is below the caution threshold {threshold:g}. "
            "This is a diagnostic, not an automatic fail."
        )
    return f"{label} ratio {ratio:.3f} is at or above the caution threshold {threshold:g}."
