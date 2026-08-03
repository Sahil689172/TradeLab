"""Compare two saved performance profile reports (before vs after).

Does not run validation — only reads existing JSON profile artifacts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.services.profiling.schemas import PerformanceProfileReport


class MetricDelta(BaseModel):
    """One scalar metric: before / after / absolute + percentage change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    before: float
    after: float
    difference: float
    improvement_pct: float
    unit: str = "ms"


class StrategyTimingDelta(BaseModel):
    """Per-strategy total-time comparison."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str
    before_total_ms: float
    after_total_ms: float
    before_average_ms: float
    after_average_ms: float
    difference_ms: float
    improvement_pct: float


class OptimizationComparisonReport(BaseModel):
    """Permanent optimization report contract for TradeLab."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    before_path: str
    after_path: str
    before_generated_at: datetime | None = None
    after_generated_at: datetime | None = None
    before_symbols: int = 0
    after_symbols: int = 0
    before_strategies: int = 0
    after_strategies: int = 0
    metrics: list[MetricDelta] = Field(default_factory=list)
    strategy_deltas: list[StrategyTimingDelta] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def load_profile_report(path: Path | str) -> PerformanceProfileReport:
    """Load a ``performance_profile.json`` (or labeled variant) from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PerformanceProfileReport.model_validate(payload)


def _improvement_pct(before: float, after: float) -> float:
    """Positive means after is faster / smaller (improvement)."""
    if before == 0:
        return 0.0 if after == 0 else (-100.0 if after > 0 else 100.0)
    return ((before - after) / before) * 100.0


def _metric(name: str, before: float, after: float, *, unit: str = "ms") -> MetricDelta:
    return MetricDelta(
        name=name,
        before=before,
        after=after,
        difference=after - before,
        improvement_pct=_improvement_pct(before, after),
        unit=unit,
    )


def compare_profiles(
    before: PerformanceProfileReport,
    after: PerformanceProfileReport,
    *,
    before_path: str = "",
    after_path: str = "",
) -> OptimizationComparisonReport:
    """Build an optimization comparison from two profile reports."""
    notes: list[str] = [
        "Comparison of saved profiling reports only — no validation was re-run.",
        "Positive improvement % means the after report is faster / lower.",
    ]
    if len(before.symbols) != len(after.symbols):
        notes.append(
            f"Symbol count differs: before={len(before.symbols)} after={len(after.symbols)}",
        )
    if before.strategies != after.strategies:
        notes.append(
            "Strategy sets differ between reports; per-strategy rows use name intersection.",
        )

    before_context = sum(row.total_ms for row in before.context_stats)
    after_context = sum(row.total_ms for row in after.context_stats)
    before_strategy = sum(row.total_ms for row in before.strategy_stats)
    after_strategy = sum(row.total_ms for row in after.strategy_stats)

    metrics = [
        _metric("Total Runtime (wall)", before.wall_time_ms, after.wall_time_ms),
        _metric("Context Runtime", before_context, after_context),
        _metric("Strategy Runtime", before_strategy, after_strategy),
        _metric("Average Stock Runtime", before.average_stock_ms, after.average_stock_ms),
        _metric("Average Strategy Runtime", before.average_strategy_ms, after.average_strategy_ms),
        _metric("CPU Time", before.cpu_time_ms, after.cpu_time_ms),
        _metric(
            "Peak Memory",
            float(before.memory_peak_bytes),
            float(after.memory_peak_bytes),
            unit="bytes",
        ),
    ]

    before_by_name = {row.name: row for row in before.strategy_stats}
    after_by_name = {row.name: row for row in after.strategy_stats}
    names = sorted(set(before_by_name) | set(after_by_name))
    strategy_deltas: list[StrategyTimingDelta] = []
    for name in names:
        b = before_by_name.get(name)
        a = after_by_name.get(name)
        b_total = b.total_ms if b else 0.0
        a_total = a.total_ms if a else 0.0
        b_avg = b.average_ms if b else 0.0
        a_avg = a.average_ms if a else 0.0
        strategy_deltas.append(
            StrategyTimingDelta(
                strategy=name,
                before_total_ms=b_total,
                after_total_ms=a_total,
                before_average_ms=b_avg,
                after_average_ms=a_avg,
                difference_ms=a_total - b_total,
                improvement_pct=_improvement_pct(b_total, a_total),
            ),
        )
    strategy_deltas.sort(key=lambda row: row.before_total_ms, reverse=True)

    return OptimizationComparisonReport(
        generated_at=datetime.now(timezone.utc),
        before_path=before_path,
        after_path=after_path,
        before_generated_at=before.generated_at,
        after_generated_at=after.generated_at,
        before_symbols=len(before.symbols),
        after_symbols=len(after.symbols),
        before_strategies=len(before.strategies),
        after_strategies=len(after.strategies),
        metrics=metrics,
        strategy_deltas=strategy_deltas,
        notes=notes,
    )


def format_comparison_console(report: OptimizationComparisonReport) -> str:
    """Human-readable optimization report."""
    lines: list[str] = [
        "=" * 72,
        "TradeLab — Optimization Report",
        "=" * 72,
        f"Generated:  {report.generated_at.isoformat()}",
        f"Before:     {report.before_path}",
        f"After:      {report.after_path}",
        f"Symbols:    {report.before_symbols} → {report.after_symbols}",
        f"Strategies: {report.before_strategies} → {report.after_strategies}",
        "",
        f"{'Metric':<28} {'Before':>14} {'After':>14} {'Diff':>14} {'Impr %':>10}",
        "-" * 72,
    ]
    for metric in report.metrics:
        if metric.unit == "bytes":
            before_s = _fmt_bytes(int(metric.before))
            after_s = _fmt_bytes(int(metric.after))
            diff_s = _fmt_bytes(int(abs(metric.difference)))
            if metric.difference < 0:
                diff_s = f"-{diff_s}"
            elif metric.difference > 0:
                diff_s = f"+{diff_s}"
        else:
            before_s = _fmt_ms(metric.before)
            after_s = _fmt_ms(metric.after)
            diff_s = _fmt_ms(abs(metric.difference))
            if metric.difference < 0:
                diff_s = f"-{diff_s}"
            elif metric.difference > 0:
                diff_s = f"+{diff_s}"
        lines.append(
            f"{metric.name:<28} {before_s:>14} {after_s:>14} {diff_s:>14} "
            f"{metric.improvement_pct:>9.1f}%",
        )

    lines.extend(
        [
            "",
            "--- Per Strategy Timing ---",
            f"{'Strategy':<24} {'Before tot':>12} {'After tot':>12} "
            f"{'Diff':>12} {'Impr %':>10}",
            "-" * 72,
        ],
    )
    for row in report.strategy_deltas:
        sign = ""
        if row.difference_ms < 0:
            sign = "-"
        elif row.difference_ms > 0:
            sign = "+"
        lines.append(
            f"{row.strategy:<24} {_fmt_ms(row.before_total_ms):>12} "
            f"{_fmt_ms(row.after_total_ms):>12} "
            f"{sign}{_fmt_ms(abs(row.difference_ms)):>11} "
            f"{row.improvement_pct:>9.1f}%",
        )

    if report.notes:
        lines.append("")
        lines.append("--- Notes ---")
        for note in report.notes:
            lines.append(f"  • {note}")
    return "\n".join(lines)


def write_comparison_reports(
    report: OptimizationComparisonReport,
    output_dir: Path,
    *,
    json_filename: str = "optimization_report.json",
    console: bool = True,
) -> tuple[Path, str]:
    """Persist JSON and return (path, console text)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / json_filename
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    text = format_comparison_console(report)
    if console:
        (output_dir / "optimization_report.txt").write_text(text + "\n", encoding="utf-8")
    return path, text


def _fmt_ms(value: float) -> str:
    if abs(value) >= 60_000:
        return f"{value / 60_000:.2f} min"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.2f} s"
    return f"{value:.1f} ms"


def _fmt_bytes(value: int) -> str:
    value = abs(value)
    if value >= 1_073_741_824:
        return f"{value / 1_073_741_824:.2f} GiB"
    if value >= 1_048_576:
        return f"{value / 1_048_576:.2f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"
