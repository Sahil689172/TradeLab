"""Write walk-forward JSON / Markdown / CSV artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from app.backtesting.walk_forward.charts import write_charts
from app.backtesting.walk_forward.report import format_markdown_report
from app.backtesting.walk_forward.schemas import WalkForwardResult, MetricStatus


def write_outputs(
    result: WalkForwardResult,
    *,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "walk_forward_report.json"
    md_path = output_dir / "walk_forward_report.md"
    leakage_path = output_dir / "leakage_report.json"
    windows_path = output_dir / "windows.csv"
    train_path = output_dir / "train_metrics.csv"
    oos_path = output_dir / "oos_metrics.csv"
    trades_path = output_dir / "oos_trades.csv"
    params_path = output_dir / "parameter_history.csv"
    equity_path = output_dir / "equity_curve.csv"

    payload = result.model_dump(mode="json")
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(format_markdown_report(result), encoding="utf-8")
    leakage_path.write_text(
        json.dumps(result.leakage.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    windows_path.write_text(_windows_csv(result), encoding="utf-8")
    train_path.write_text(_metrics_csv(result, train=True), encoding="utf-8")
    oos_path.write_text(_metrics_csv(result, train=False), encoding="utf-8")
    trades_path.write_text(_trades_csv(result), encoding="utf-8")
    params_path.write_text(_params_csv(result), encoding="utf-8")
    equity_path.write_text(_equity_csv(result), encoding="utf-8")
    paths = {
        "json": json_path,
        "md": md_path,
        "leakage": leakage_path,
        "windows": windows_path,
        "train_metrics": train_path,
        "oos_metrics": oos_path,
        "oos_trades": trades_path,
        "parameter_history": params_path,
        "equity_curve": equity_path,
    }
    if result.config.include_charts:
        paths.update(write_charts(result, output_dir=output_dir))
    return paths


def _windows_csv(result: WalkForwardResult) -> str:
    lines = [
        "window_id,symbol,train_start,train_end,test_start,test_end,"
        "selected,train_return,oos_return,oos_dd,oos_trades,start_capital,end_capital,rejected,"
        "train_selection_status,selected_train_trades,min_train_trades,eligible_candidates,ineligible_candidates",
    ]
    for row in result.windows:
        w = row.window
        sel = row.train_selection
        status = sel.selected_eligibility.value if sel else ""
        sel_trades = sel.selected_training_trade_count if sel else row.train.trade_count
        min_trades = sel.minimum_training_trades if sel else result.config.minimum_training_trades
        eligible = sel.eligible_count if sel else ""
        ineligible = sel.ineligible_count if sel else ""
        lines.append(
            f"{w.window_id},{row.symbol},{w.train_start.isoformat()},{w.train_end.isoformat()},"
            f"{w.test_start.isoformat()},{w.test_end.isoformat()},{_csv(row.selected.config_key)},"
            f"{row.train.return_pct},{row.oos.return_pct},{row.oos.max_drawdown},"
            f"{row.oos_trade_count},{row.starting_capital},{row.ending_capital},{row.rejected_count},"
            f"{_csv(status)},{sel_trades},{min_trades},{eligible},{ineligible}",
        )
    return "\n".join(lines) + "\n"


def _metrics_csv(result: WalkForwardResult, *, train: bool) -> str:
    lines = [
        "window_id,symbol,config_key,return_pct,sharpe,sortino,max_drawdown,"
        "win_rate,profit_factor,trade_count,total_costs,net_profit,gross_profit,score,"
        "sharpe_status,win_rate_status,profit_factor_status",
    ]
    for row in result.windows:
        m = row.train if train else row.oos
        tc = row.oos_trade_count if not train else m.trade_count
        sharpe_status = (
            MetricStatus.NO_TRADES
            if tc == 0
            else MetricStatus.INSUFFICIENT_SAMPLE
            if tc < 2
            else MetricStatus.LOW_SAMPLE
            if tc < 5
            else MetricStatus.VALID
        )
        win_status = MetricStatus.NO_TRADES if tc == 0 else MetricStatus.LOW_SAMPLE if tc < 5 else MetricStatus.VALID
        pf_status = (
            MetricStatus.NO_TRADES
            if tc == 0
            else MetricStatus.NO_WINNING_TRADES
            if m.gross_profit <= 0
            else MetricStatus.LOW_SAMPLE
            if tc < 5
            else MetricStatus.VALID
        )
        lines.append(
            f"{row.window.window_id},{row.symbol},{_csv(m.config_key)},{m.return_pct},"
            f"{m.sharpe},{m.sortino},{m.max_drawdown},{m.win_rate},{m.profit_factor},"
            f"{m.trade_count},{m.total_costs},{m.net_profit},{m.gross_profit},{m.score},"
            f"{sharpe_status.value},{win_status.value},{pf_status.value}",
        )
    return "\n".join(lines) + "\n"


def _trades_csv(result: WalkForwardResult) -> str:
    lines = [
        "symbol,requested_strategy,execution_engine,strategy_name,entry_timestamp,exit_timestamp,entry_price,exit_price,"
        "quantity,gross_profit,brokerage,slippage,net_profit,holding_days,exit_reason",
    ]
    identity = result.strategy_identity
    requested = identity.requested_strategy if identity else result.config.strategy_alias
    engine_name = identity.execution_engine if identity else "ema_trend"
    for trade in result.oos_trades:
        lines.append(
            f"{trade.symbol},{_csv(requested)},{_csv(engine_name)},{_csv(trade.strategy_name)},{trade.entry_timestamp.isoformat()},"
            f"{trade.exit_timestamp.isoformat()},{trade.entry_price},{trade.exit_price},"
            f"{trade.quantity},{trade.gross_profit},{trade.brokerage},{trade.slippage},"
            f"{trade.net_profit},{trade.holding_days},{_csv(trade.exit_reason.value)}",
        )
    return "\n".join(lines) + "\n"


def _params_csv(result: WalkForwardResult) -> str:
    lines = ["window_id,symbol,config_key,fast_ema,slow_ema,adx_threshold,ema200_filter"]
    for row in result.windows:
        params = row.frozen_parameters
        lines.append(
            f"{row.window.window_id},{row.symbol},{_csv(row.selected.config_key)},"
            f"{params.get('fast_ema','')},{params.get('slow_ema','')},"
            f"{params.get('adx_threshold','')},{params.get('ema200_filter','')}",
        )
    return "\n".join(lines) + "\n"


def _equity_csv(result: WalkForwardResult) -> str:
    lines = ["timestamp,equity"]
    for point in result.equity_curve:
        lines.append(f"{point.timestamp.isoformat()},{point.equity}")
    return "\n".join(lines) + "\n"


def _csv(value: object) -> str:
    text = str(value).replace(",", ";")
    return text
