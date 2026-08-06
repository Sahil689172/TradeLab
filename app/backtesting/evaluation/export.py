"""Export evaluation artifacts to JSON / CSV / Markdown."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.backtesting.evaluation.reports import format_markdown_report
from app.backtesting.evaluation.schemas import EvaluationReport


def export_evaluation_json(report: EvaluationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_public_dict(), indent=2), encoding="utf-8")
    return path


def export_evaluation_markdown(report: EvaluationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_markdown_report(report), encoding="utf-8")
    return path


def export_trades_csv(trades: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not trades:
        path.write_text("symbol,net_profit\n", encoding="utf-8")
        return path
    fieldnames = list(trades[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)
    return path


def export_metrics_csv(report: EvaluationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["metric", "raw", "professional", "delta", "verdict"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.metric_comparisons:
            writer.writerow(
                {
                    "metric": row.metric,
                    "raw": row.raw_value,
                    "professional": row.professional_value,
                    "delta": row.delta,
                    "verdict": row.verdict.value,
                },
            )
    return path


def export_filter_csv(report: EvaluationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "filter_name",
        "signals_examined",
        "signals_rejected",
        "signals_accepted",
        "average_profit_after_filter",
        "average_loss_after_filter",
        "improvement_pct",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.filter_effectiveness:
            writer.writerow(row.model_dump())
    return path
