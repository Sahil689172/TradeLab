"""Export audit artifacts to JSON and CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.strategy_engine.audit.schemas import StrategyAuditReport


def export_audit_json(report: StrategyAuditReport, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.to_public_dict(), indent=2, sort_keys=False),
        encoding="utf-8",
    )
    return target


def export_audit_csv(report: StrategyAuditReport, path: str | Path) -> Path:
    """Export scorecard rows as a flat CSV (one row per strategy)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "strategy_name",
        "symbol",
        "buy_signals",
        "sell_signals",
        "hold_signals",
        "average_hold",
        "average_confidence",
        "average_risk_reward",
        "average_win_expectancy",
        "filter_acceptance_rate",
        "filter_rejection_rate",
        "filter_integration_ok",
        "composite_score",
        "ready",
        "notes",
        "rank",
    ]
    rank_by_name = {row.strategy_name: row.rank for row in report.comparison.rows}
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.scorecard.rows:
            writer.writerow(
                {
                    "strategy_name": row.strategy_name,
                    "symbol": row.symbol,
                    "buy_signals": row.buy_signals,
                    "sell_signals": row.sell_signals,
                    "hold_signals": row.hold_signals,
                    "average_hold": row.average_hold,
                    "average_confidence": row.average_confidence,
                    "average_risk_reward": row.average_risk_reward,
                    "average_win_expectancy": row.average_win_expectancy,
                    "filter_acceptance_rate": row.filter_acceptance_rate,
                    "filter_rejection_rate": row.filter_rejection_rate,
                    "filter_integration_ok": row.filter_integration_ok,
                    "composite_score": row.composite_score,
                    "ready": row.ready,
                    "notes": row.notes,
                    "rank": rank_by_name.get(row.strategy_name, ""),
                },
            )
    return target


def export_audit(
    report: StrategyAuditReport,
    *,
    json_path: str | Path,
    csv_path: str | Path,
) -> tuple[Path, Path]:
    return export_audit_json(report, json_path), export_audit_csv(report, csv_path)
