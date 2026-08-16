"""Write portfolio-risk JSON / Markdown / CSV."""

from __future__ import annotations

import json
from pathlib import Path

from app.backtesting.portfolio_risk.report import format_markdown_report
from app.backtesting.portfolio_risk.schemas import PortfolioRiskResult


def write_outputs(
    result: PortfolioRiskResult,
    *,
    output_dir: Path,
    stem: str = "portfolio_report",
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    exposure_path = output_dir / "portfolio_exposure.csv"
    corr_path = output_dir / "portfolio_correlation.csv"
    trades_path = output_dir / "portfolio_trades.csv"

    payload = result.model_dump(mode="json")
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(format_markdown_report(result), encoding="utf-8")
    exposure_path.write_text(_exposure_csv(result), encoding="utf-8")
    corr_path.write_text(_correlation_csv(result), encoding="utf-8")
    trades_path.write_text(_rejections_csv(result), encoding="utf-8")
    return {
        "json": json_path,
        "md": md_path,
        "exposure": exposure_path,
        "correlation": corr_path,
        "trades": trades_path,
    }


def _exposure_csv(result: PortfolioRiskResult) -> str:
    lines = [
        "metric,value",
        f"average_exposure,{result.average_exposure}",
        f"maximum_exposure,{result.maximum_exposure}",
        f"average_utilization,{result.average_utilization}",
        f"maximum_utilization,{result.maximum_utilization}",
        f"maximum_concurrent_positions,{result.maximum_concurrent_positions}",
        f"largest_symbol,{result.concentration.largest_symbol}",
        f"largest_symbol_pct,{result.concentration.largest_symbol_pct}",
        f"hhi,{result.concentration.hhi}",
    ]
    return "\n".join(lines) + "\n"


def _correlation_csv(result: PortfolioRiskResult) -> str:
    report = result.symbol_correlation
    lines = ["kind,a,b,correlation"]
    if report.labels and report.matrix:
        for i, a in enumerate(report.labels):
            for j, b in enumerate(report.labels):
                value = report.matrix[i][j]
                if value is None:
                    continue
                lines.append(f"{report.kind},{a},{b},{value}")
    else:
        lines.append("symbol,n/a,n/a,insufficient")
    return "\n".join(lines) + "\n"


def _rejections_csv(result: PortfolioRiskResult) -> str:
    lines = ["timestamp,symbol,strategy,status,reason_code,reason,requested_budget,allocated_budget,quantity"]
    for item in result.rejections:
        lines.append(
            f"{item.timestamp.isoformat()},{item.symbol},{item.strategy},{item.status.value},"
            f"{item.reason_code.value if item.reason_code else ''},"
            f"{item.reason.replace(',', ';')},{item.requested_budget},{item.allocated_budget},{item.quantity}",
        )
    if len(lines) == 1:
        lines.append(",,,,,,,,")
    return "\n".join(lines) + "\n"
