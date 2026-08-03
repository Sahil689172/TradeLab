"""Tests for profile comparison and progress reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.services.profiling.compare import (
    compare_profiles,
    format_comparison_console,
    load_profile_report,
    write_comparison_reports,
)
from app.services.profiling.progress import ProgressReporter
from app.services.profiling.schemas import (
    PerformanceProfileReport,
    TimingStats,
)


def _report(
    *,
    wall: float,
    context: float,
    strategy: float,
    avg_stock: float,
    peak_mem: int = 1_000_000,
    strategy_name: str = "ema_trend",
    strategy_total: float = 100.0,
) -> PerformanceProfileReport:
    return PerformanceProfileReport(
        generated_at=datetime.now(timezone.utc),
        storage_dir="/tmp",
        workers=1,
        symbols=["A", "B"],
        strategies=[strategy_name],
        wall_time_ms=wall,
        cpu_time_ms=wall * 0.8,
        memory_current_bytes=peak_mem // 2,
        memory_peak_bytes=peak_mem,
        discovery_ms=1.0,
        report_generation_ms=1.0,
        context_stats=[
            TimingStats(
                name="market_structure",
                category="context",
                count=2,
                total_ms=context,
                average_ms=context / 2,
                minimum_ms=1.0,
                maximum_ms=context,
            ),
        ],
        strategy_stats=[
            TimingStats(
                name=strategy_name,
                category="strategy_execution",
                count=2,
                total_ms=strategy_total,
                average_ms=strategy_total / 2,
                minimum_ms=1.0,
                maximum_ms=strategy_total,
                share_of_measured_pct=10.0,
            ),
        ],
        average_stock_ms=avg_stock,
        average_strategy_ms=strategy,
    )


def test_compare_profiles_improvement() -> None:
    before = _report(
        wall=10_000,
        context=6_000,
        strategy=3_000,
        avg_stock=5_000,
        strategy_total=3_000,
        peak_mem=2_000_000,
    )
    after = _report(
        wall=4_000,
        context=1_500,
        strategy=2_000,
        avg_stock=2_000,
        strategy_total=2_000,
        peak_mem=1_500_000,
    )
    report = compare_profiles(before, after, before_path="b.json", after_path="a.json")
    by_name = {m.name: m for m in report.metrics}
    assert by_name["Total Runtime (wall)"].improvement_pct == 60.0
    assert by_name["Context Runtime"].improvement_pct == 75.0
    text = format_comparison_console(report)
    assert "Optimization Report" in text
    assert "Total Runtime" in text


def test_write_comparison_roundtrip(tmp_path: Path) -> None:
    before = _report(wall=1000, context=400, strategy=500, avg_stock=500, strategy_total=500)
    after = _report(wall=500, context=100, strategy=300, avg_stock=250, strategy_total=300)
    # Persist fake profile JSONs then load
    before_path = tmp_path / "performance_profile_before.json"
    after_path = tmp_path / "performance_profile_after.json"
    before_path.write_text(before.model_dump_json(indent=2) + "\n", encoding="utf-8")
    after_path.write_text(after.model_dump_json(indent=2) + "\n", encoding="utf-8")

    loaded_before = load_profile_report(before_path)
    loaded_after = load_profile_report(after_path)
    report = compare_profiles(
        loaded_before,
        loaded_after,
        before_path=str(before_path),
        after_path=str(after_path),
    )
    json_path, text = write_comparison_reports(report, tmp_path)
    assert json_path.exists()
    assert "Improvement" in text or "Impr" in text
    assert (tmp_path / "optimization_report.txt").exists()


def test_progress_reporter_eta() -> None:
    lines: list[str] = []
    reporter = ProgressReporter(4, sink=lines.append, every_symbol=True)
    reporter.start()
    reporter.tick("A")
    reporter.tick("B")
    assert any("[1/4]" in line for line in lines)
    assert any("[2/4]" in line for line in lines)
    assert any("ETA" in line for line in lines)


def test_compare_strategy_improvement_exact() -> None:
    before = _report(
        wall=10_000,
        context=6_000,
        strategy=3_000,
        avg_stock=5_000,
        strategy_total=3_000,
    )
    after = _report(
        wall=4_000,
        context=1_500,
        strategy=2_000,
        avg_stock=2_000,
        strategy_total=2_000,
    )
    report = compare_profiles(before, after)
    assert abs(report.strategy_deltas[0].improvement_pct - (1000 / 3000 * 100)) < 1e-9
