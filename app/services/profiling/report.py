"""Console / JSON / CSV writers for performance profiling reports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.services.profiling.schemas import (
    HotspotEntry,
    PerformanceProfileReport,
    TimingStats,
)
from app.services.profiling.timers import TimingCollector


def format_console_report(report: PerformanceProfileReport) -> str:
    """Human-readable performance profile."""
    lines: list[str] = [
        "=" * 72,
        "TradeLab — Performance Profile (measurement only)",
        "=" * 72,
        f"Generated:     {report.generated_at.isoformat()}",
        f"Storage:       {report.storage_dir}",
        f"Workers:       {report.workers}",
        f"Symbols:       {len(report.symbols)}",
        f"Strategies:    {len(report.strategies)}",
        f"Wall time:     {_fmt_ms(report.wall_time_ms)}",
        f"CPU time:      {_fmt_ms(report.cpu_time_ms)}",
        f"Memory now:    {_fmt_bytes(report.memory_current_bytes)}",
        f"Memory peak:   {_fmt_bytes(report.memory_peak_bytes)}",
        f"Discovery:     {_fmt_ms(report.discovery_ms)}",
        f"Report gen:    {_fmt_ms(report.report_generation_ms)}",
        "",
        "--- Pipeline Overview ---",
        f"Avg stock runtime:     {_fmt_ms(report.average_stock_ms)}",
        f"Avg strategy runtime:  {_fmt_ms(report.average_strategy_ms)}",
        "",
        "--- Parquet Loading ---",
        _stats_table(report.parquet_stats),
        "",
        "--- Strategy Context ---",
        _stats_table(report.context_stats),
        "",
        "--- Strategy Execution ---",
        _stats_table(report.strategy_stats),
        "",
        "--- Trade Recommendation ---",
        _stats_table(report.recommendation_stats),
        "",
        "--- Report Generation ---",
        _stats_table(report.report_stats) if report.report_stats else "(not timed yet)",
        "",
        "--- Per Stock (sample) ---",
        _stock_table(report),
        "",
        "--- Per Strategy ---",
        _strategy_detail(report.strategy_stats),
        "",
        "--- Top 10 Slowest Operations ---",
        _hotspot_table(report.top_slowest),
        "",
        "--- Top 10 Fastest Operations (by avg) ---",
        _hotspot_table(report.top_fastest, show_share=False),
        "",
        "--- Runtime Estimates (linear from avg stock) ---",
    ]
    for estimate in report.runtime_estimates:
        lines.append(
            f"  {estimate.stocks:>4} stocks → "
            f"{estimate.estimated_wall_minutes:,.1f} min "
            f"({_fmt_ms(estimate.estimated_wall_ms)})",
        )

    lines.extend(
        [
            "",
            "--- Performance Hotspots ---",
            _hotspot_table(report.hotspots),
            "",
        ],
    )
    if report.notes:
        lines.append("--- Notes ---")
        for note in report.notes:
            lines.append(f"  • {note}")
    return "\n".join(lines)


def write_json_report(report: PerformanceProfileReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def write_csv_report(report: PerformanceProfileReport, path: Path) -> Path:
    """Flat operation-level CSV (stats + per-stock rollups)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "section",
        "name",
        "symbol",
        "count",
        "total_ms",
        "average_ms",
        "minimum_ms",
        "maximum_ms",
        "share_pct",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for stats in (
            report.parquet_stats
            + report.context_stats
            + report.strategy_stats
            + report.recommendation_stats
            + report.report_stats
        ):
            writer.writerow(
                {
                    "section": stats.category,
                    "name": stats.name,
                    "symbol": "",
                    "count": stats.count,
                    "total_ms": f"{stats.total_ms:.6f}",
                    "average_ms": f"{stats.average_ms:.6f}",
                    "minimum_ms": f"{stats.minimum_ms:.6f}",
                    "maximum_ms": f"{stats.maximum_ms:.6f}",
                    "share_pct": f"{stats.share_of_measured_pct:.4f}",
                },
            )
        for stock in report.stock_breakdowns:
            writer.writerow(
                {
                    "section": "per_stock",
                    "name": "total",
                    "symbol": stock.symbol,
                    "count": 1,
                    "total_ms": f"{stock.total_ms:.6f}",
                    "average_ms": f"{stock.total_ms:.6f}",
                    "minimum_ms": f"{stock.total_ms:.6f}",
                    "maximum_ms": f"{stock.total_ms:.6f}",
                    "share_pct": "",
                },
            )
            writer.writerow(
                {
                    "section": "per_stock",
                    "name": "load_ohlcv",
                    "symbol": stock.symbol,
                    "count": 1,
                    "total_ms": f"{stock.load_ohlcv_ms:.6f}",
                    "average_ms": f"{stock.load_ohlcv_ms:.6f}",
                    "minimum_ms": f"{stock.load_ohlcv_ms:.6f}",
                    "maximum_ms": f"{stock.load_ohlcv_ms:.6f}",
                    "share_pct": "",
                },
            )
            writer.writerow(
                {
                    "section": "per_stock",
                    "name": "load_features",
                    "symbol": stock.symbol,
                    "count": 1,
                    "total_ms": f"{stock.load_features_ms:.6f}",
                    "average_ms": f"{stock.load_features_ms:.6f}",
                    "minimum_ms": f"{stock.load_features_ms:.6f}",
                    "maximum_ms": f"{stock.load_features_ms:.6f}",
                    "share_pct": "",
                },
            )
            writer.writerow(
                {
                    "section": "per_stock",
                    "name": "context",
                    "symbol": stock.symbol,
                    "count": 1,
                    "total_ms": f"{stock.context_ms:.6f}",
                    "average_ms": f"{stock.context_ms:.6f}",
                    "minimum_ms": f"{stock.context_ms:.6f}",
                    "maximum_ms": f"{stock.context_ms:.6f}",
                    "share_pct": "",
                },
            )
            for strategy_name, elapsed in stock.strategy_ms.items():
                writer.writerow(
                    {
                        "section": "per_stock",
                        "name": strategy_name,
                        "symbol": stock.symbol,
                        "count": 1,
                        "total_ms": f"{elapsed:.6f}",
                        "average_ms": f"{elapsed:.6f}",
                        "minimum_ms": f"{elapsed:.6f}",
                        "maximum_ms": f"{elapsed:.6f}",
                        "share_pct": "",
                    },
                )
    return path


def write_performance_reports(
    report: PerformanceProfileReport,
    output_dir: Path,
    *,
    json_filename: str = "performance_profile.json",
    csv_filename: str = "performance_profile.csv",
    collector: TimingCollector | None = None,
) -> tuple[PerformanceProfileReport, Path, Path, str]:
    """Time JSON / CSV / console generation and attach report_stats.

    ``collector`` is accepted for API compatibility; report writers always use a
    fresh local timer so prior profile samples are not mixed in.
    """
    del collector  # unused — keep signature stable for callers
    sink = TimingCollector()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / json_filename
    csv_path = output_dir / csv_filename

    # Time each writer on a throwaway draft, then persist the final payload once.
    with sink.measure("report", "json"):
        write_json_report(report, json_path)

    with sink.measure("report", "csv"):
        write_csv_report(report, csv_path)

    with sink.measure("report", "console"):
        _ = format_console_report(report)

    report_records = [r for r in sink.snapshot() if r.category == "report"]
    report_total = sum(r.elapsed_ms for r in report_records)
    by_name: dict[str, list[float]] = {}
    for record in report_records:
        by_name.setdefault(record.name, []).append(record.elapsed_ms)

    report_stats: list[TimingStats] = []
    for name in ("json", "csv", "console"):
        samples = by_name.get(name, [])
        if not samples:
            report_stats.append(
                TimingStats(
                    name=name,
                    category="report",
                    count=0,
                    total_ms=0.0,
                    average_ms=0.0,
                    minimum_ms=0.0,
                    maximum_ms=0.0,
                ),
            )
            continue
        total = sum(samples)
        report_stats.append(
            TimingStats(
                name=name,
                category="report",
                count=len(samples),
                total_ms=total,
                average_ms=total / len(samples),
                minimum_ms=min(samples),
                maximum_ms=max(samples),
                share_of_measured_pct=0.0,
            ),
        )

    measured_base = max(report.wall_time_ms, 1.0)
    report_hotspot = HotspotEntry(
        name="Report Generation",
        category="report",
        total_ms=report_total,
        share_pct=(report_total / (measured_base + report_total)) * 100.0,
    )
    hotspots = list(report.hotspots) + [report_hotspot]
    hotspots.sort(key=lambda item: item.total_ms, reverse=True)

    updated = report.model_copy(
        update={
            "report_generation_ms": report_total,
            "report_stats": report_stats,
            "hotspots": hotspots[:15],
            "top_slowest": hotspots[:10],
        },
    )
    write_json_report(updated, json_path)
    write_csv_report(updated, csv_path)
    console_text = format_console_report(updated)
    return updated, json_path, csv_path, console_text


def _fmt_ms(value: float) -> str:
    if value >= 60_000:
        return f"{value / 60_000:.2f} min ({value:,.1f} ms)"
    if value >= 1_000:
        return f"{value / 1_000:.2f} s ({value:,.1f} ms)"
    return f"{value:,.2f} ms"


def _fmt_bytes(value: int) -> str:
    if value >= 1_073_741_824:
        return f"{value / 1_073_741_824:.2f} GiB"
    if value >= 1_048_576:
        return f"{value / 1_048_576:.2f} MiB"
    if value >= 1024:
        return f"{value / 1024:.2f} KiB"
    return f"{value} B"


def _stats_table(rows: list[TimingStats]) -> str:
    if not rows:
        return "  (none)"
    header = (
        f"  {'name':<28} {'n':>6} {'avg':>12} {'min':>12} "
        f"{'max':>12} {'total':>14} {'share':>8}"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]
    for row in rows:
        lines.append(
            f"  {row.name:<28} {row.count:>6} "
            f"{row.average_ms:>10.2f}ms {row.minimum_ms:>10.2f}ms "
            f"{row.maximum_ms:>10.2f}ms {row.total_ms:>12.1f}ms "
            f"{row.share_of_measured_pct:>6.1f}%",
        )
    return "\n".join(lines)


def _strategy_detail(rows: list[TimingStats]) -> str:
    if not rows:
        return "  (none)"
    lines: list[str] = []
    for row in rows:
        lines.append(f"  {row.name}")
        lines.append(f"    Average  {_fmt_ms(row.average_ms)}")
        lines.append(f"    Maximum  {_fmt_ms(row.maximum_ms)}")
        lines.append(f"    Minimum  {_fmt_ms(row.minimum_ms)}")
        lines.append(f"    Total    {_fmt_ms(row.total_ms)}")
    return "\n".join(lines)


def _stock_table(report: PerformanceProfileReport, *, limit: int = 25) -> str:
    rows = report.stock_breakdowns
    if not rows:
        return "  (none)"
    lines: list[str] = []
    for stock in rows[:limit]:
        lines.append(f"  {stock.symbol}")
        lines.append(f"    Load OHLCV      {_fmt_ms(stock.load_ohlcv_ms)}")
        lines.append(f"    Load Features   {_fmt_ms(stock.load_features_ms)}")
        lines.append(f"    Context         {_fmt_ms(stock.context_ms)}")
        for name, elapsed in stock.strategy_ms.items():
            lines.append(f"    {name:<16} {_fmt_ms(elapsed)}")
        lines.append(f"    Recommendation  {_fmt_ms(stock.recommendation_ms)}")
        lines.append(f"    Total           {_fmt_ms(stock.total_ms)}")
        lines.append("")
    if len(rows) > limit:
        lines.append(f"  … and {len(rows) - limit} more stocks (see JSON/CSV)")
    return "\n".join(lines).rstrip()


def _hotspot_table(entries: list[HotspotEntry], *, show_share: bool = True) -> str:
    if not entries:
        return "  (none)"
    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if show_share:
            lines.append(
                f"  {index:>2}. {entry.name:<28} "
                f"{entry.share_pct:>6.1f}%  {_fmt_ms(entry.total_ms)}",
            )
        else:
            lines.append(
                f"  {index:>2}. {entry.category}/{entry.name:<24} "
                f"avg {_fmt_ms(entry.total_ms)}",
            )
    return "\n".join(lines)
