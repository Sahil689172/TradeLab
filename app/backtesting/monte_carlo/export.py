"""Write Monte Carlo summary JSON / Markdown / CSV (not 10k equity curves)."""

from __future__ import annotations

import json
from pathlib import Path

from app.backtesting.monte_carlo.report import format_markdown_report
from app.backtesting.monte_carlo.schemas import MonteCarloResult, PercentileSummary


def write_outputs(
    result: MonteCarloResult,
    *,
    output_dir: Path,
    stem: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}_monte_carlo.json"
    md_path = output_dir / f"{stem}_monte_carlo.md"
    csv_path = output_dir / f"{stem}_monte_carlo.csv"

    payload = result.model_dump(mode="json", exclude={"simulation_summaries"})
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(format_markdown_report(result), encoding="utf-8")
    csv_path.write_text(_csv(result), encoding="utf-8")
    return {"json": json_path, "md": md_path, "csv": csv_path}


def _csv(result: MonteCarloResult) -> str:
    lines = [
        f"capital_mode,{result.capital_mode.value}",
        f"capital_model,{result.capital_model or result.capital_mode.value}",
        f"engine_kind,{result.engine_kind}",
        f"method,{result.sampling_method.value}",
        f"seed,{result.seed}",
        f"simulations,{result.simulations}",
        f"historical_trade_count,{result.source_trade_count}",
        f"sample_quality,{result.sample_quality.value}",
        f"verdict,{result.verdict.value}",
        "",
        "metric,p01,p05,p10,p25,p50,p75,p90,p95,p99",
        _csv_row("final_capital", result.final_capital_percentiles),
        _csv_row("return", result.return_percentiles),
        _csv_row("max_drawdown_signed", result.max_drawdown_percentiles),
        _csv_row("max_drawdown_abs", result.max_drawdown_abs_percentiles),
        _csv_row("min_equity", result.min_equity_percentiles),
        _csv_row("longest_losing_streak", result.longest_losing_streak_percentiles),
        "",
        "probability,value",
        f"loss,{result.probability_of_loss}",
        f"profit,{result.probability_of_profit}",
        f"ruin,{result.probability_of_ruin}",
    ]
    for key, value in result.threshold_probabilities.items():
        lines.append(f"{key},{value}")
    return "\n".join(lines) + "\n"


def _csv_row(name: str, summary: PercentileSummary) -> str:
    return (
        f"{name},{summary.p01},{summary.p05},{summary.p10},{summary.p25},"
        f"{summary.p50},{summary.p75},{summary.p90},{summary.p95},{summary.p99}"
    )
