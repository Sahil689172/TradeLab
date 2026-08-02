"""Console / JSON / CSV report writers for universe validation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.services.universe_validation.schemas import UniverseValidationReport


def format_console_summary(report: UniverseValidationReport) -> str:
    """Human-readable summary with strategy and stock tables."""
    lines: list[str] = [
        "=" * 72,
        "TradeLab — Universe Strategy Validation",
        "=" * 72,
        f"Generated:   {report.generated_at.isoformat()}",
        f"Timeframe:   {report.timeframe}",
        f"Storage:     {report.storage_dir}",
        f"Workers:     {report.workers}",
        f"Symbols:     {len(report.symbols)}",
        f"Strategies:  {len(report.strategies)}",
        f"Cells:       {report.total_cells}  "
        f"(passed={report.total_passed}  failed={report.total_failed})",
        f"Wall time:   {report.total_execution_time_ms:,.1f} ms",
        "",
        "--- Per Strategy ---",
        _strategy_table(report),
        "",
        "--- Per Stock ---",
        _stock_table(report),
    ]

    failures = [cell for cell in report.cells if cell.status != "PASS"]
    if failures:
        lines.append("")
        lines.append(f"--- Failures ({len(failures)}) ---")
        # Cap console noise; full detail lives in JSON
        for cell in failures[:50]:
            err = "; ".join(cell.errors) if cell.errors else "unknown"
            lines.append(f"  {cell.symbol} / {cell.strategy}: {err}")
        if len(failures) > 50:
            lines.append(f"  … and {len(failures) - 50} more (see JSON report)")
    return "\n".join(lines)


def write_json_report(report: UniverseValidationReport, path: Path) -> Path:
    """Persist the full report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def write_csv_report(report: UniverseValidationReport, path: Path) -> Path:
    """Persist cell-level results as CSV (pivotable into strategy/stock views)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "strategy",
        "status",
        "signal",
        "confidence",
        "holding",
        "elapsed_ms",
        "errors",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for cell in report.cells:
            writer.writerow(
                {
                    "symbol": cell.symbol,
                    "strategy": cell.strategy,
                    "status": cell.status,
                    "signal": cell.signal or "",
                    "confidence": f"{cell.confidence:.4f}",
                    "holding": f"{cell.holding:.4f}",
                    "elapsed_ms": f"{cell.elapsed_ms:.3f}",
                    "errors": " | ".join(cell.errors),
                },
            )
    return path


def write_reports(
    report: UniverseValidationReport,
    output_dir: Path,
    *,
    json_filename: str = "universe_validation.json",
    csv_filename: str = "universe_validation.csv",
) -> tuple[Path, Path]:
    """Write JSON + CSV under ``output_dir``."""
    json_path = write_json_report(report, output_dir / json_filename)
    csv_path = write_csv_report(report, output_dir / csv_filename)
    return json_path, csv_path


def _strategy_table(report: UniverseValidationReport) -> str:
    headers = (
        "strategy",
        "tested",
        "pass",
        "fail",
        "BUY",
        "SELL",
        "HOLD",
        "avg_conf",
        "avg_hold",
        "ms",
    )
    rows: list[tuple[str, ...]] = [headers]
    for stats in report.strategy_stats:
        rows.append(
            (
                stats.strategy,
                str(stats.stocks_tested),
                str(stats.passed),
                str(stats.failed),
                str(stats.buy_signals),
                str(stats.sell_signals),
                str(stats.hold_signals),
                f"{stats.average_confidence:.1f}",
                f"{stats.average_holding:.1f}",
                f"{stats.execution_time_ms:.0f}",
            ),
        )
    return _format_table(rows)


def _stock_table(report: UniverseValidationReport) -> str:
    headers = ("symbol", "passed", "failed", "ms", "load_error")
    rows: list[tuple[str, ...]] = [headers]
    for stats in report.stock_stats:
        rows.append(
            (
                stats.symbol,
                str(stats.strategies_passed),
                str(stats.strategies_failed),
                f"{stats.execution_time_ms:.0f}",
                stats.load_error or "",
            ),
        )
    # Keep console readable for large universes
    if len(rows) > 31:
        head = rows[:21]
        tail_note = (f"… {len(rows) - 21} more stocks (see JSON/CSV)", "", "", "", "")
        return _format_table(head + [tail_note])
    return _format_table(rows)


def _format_table(rows: list[tuple[str, ...]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines: list[str] = []
    for row_index, row in enumerate(rows):
        line = "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))
        lines.append(line)
        if row_index == 0:
            lines.append("  ".join("-" * width for width in widths))
    return "\n".join(lines)
