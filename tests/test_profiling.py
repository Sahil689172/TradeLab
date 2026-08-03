"""Tests for performance profiling (Phase A4.15) — measurement only."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from app.services.profiling import (
    TimingCollector,
    ValidationProfiler,
    format_console_report,
    write_performance_reports,
)
from app.services.profiling.timers import ResourceMonitor
from app.services.universe_validation import UniverseValidationConfig


def _write_ohlcv(path: Path, *, bars: int = 80, base: float = 100.0) -> None:
    dates = pd.bdate_range("2023-01-02", periods=bars)
    rows = []
    for index, date in enumerate(dates):
        close = base + index * 0.2
        rows.append(
            {
                "date": date,
                "open": close - 0.3,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000 + index * 1000,
            },
        )
    pd.DataFrame(rows).to_parquet(path, engine="pyarrow", index=False)


def _write_features(path: Path, *, bars: int = 80, base: float = 100.0) -> None:
    dates = pd.bdate_range("2023-01-02", periods=bars)
    rows = []
    for index, date in enumerate(dates):
        close = base + index * 0.2
        rows.append(
            {
                "date": date,
                "ema_9": close,
                "ema_20": close + 0.5,
                "ema_21": close + 0.5,
                "ema_50": close - 0.5,
                "adx_14": 28.0,
                "rsi_14": 55.0,
                "atr_14": 1.5,
                "relative_volume_20": 1.8,
                "vwap": close * 0.999,
            },
        )
    pd.DataFrame(rows).to_parquet(path, engine="pyarrow", index=False)


@pytest.fixture
def ohlcv_dir(tmp_path: Path) -> Path:
    storage = tmp_path / "ohlcv"
    storage.mkdir()
    for symbol, base in (("RELIANCE", 100.0), ("TCS", 200.0)):
        _write_ohlcv(storage / f"{symbol}.parquet", bars=280, base=base)
        _write_features(storage / f"{symbol}_features.parquet", bars=280, base=base)
    return storage


def test_timing_collector_measure() -> None:
    collector = TimingCollector()
    with collector.measure("parquet_load", "ohlcv", symbol="RELIANCE"):
        pass
    records = collector.snapshot()
    assert len(records) == 1
    assert records[0].category == "parquet_load"
    assert records[0].elapsed_ms >= 0.0


def test_resource_monitor_snapshot() -> None:
    monitor = ResourceMonitor()
    monitor.start()
    snap = monitor.stop()
    assert snap.wall_ms >= 0.0
    assert snap.cpu_ms >= 0.0
    assert snap.memory_peak_bytes >= 0


def test_profile_single_symbol(ohlcv_dir: Path, tmp_path: Path) -> None:
    config = UniverseValidationConfig(
        storage_dir=ohlcv_dir,
        output_dir=tmp_path / "logs",
        workers=1,
        limit=1,
        allow_synthetic=False,
    )
    profiler = ValidationProfiler(config, show_progress=False)
    report = profiler.profile(symbols=["RELIANCE"], strategy_names=["ema_trend", "vwap"])

    assert report.symbols == ["RELIANCE"]
    assert len(report.strategies) == 2
    assert report.wall_time_ms > 0
    assert report.discovery_ms >= 0
    assert any(row.name == "ohlcv" for row in report.parquet_stats)
    assert any(row.name == "features" for row in report.parquet_stats)
    assert report.stock_breakdowns
    assert report.stock_breakdowns[0].symbol == "RELIANCE"
    assert report.stock_breakdowns[0].load_ohlcv_ms >= 0
    assert report.hotspots
    assert report.runtime_estimates
    assert {e.stocks for e in report.runtime_estimates} == {100, 449, 1000}

    updated, json_path, csv_path, console = write_performance_reports(
        report,
        tmp_path / "logs",
        collector=TimingCollector(),
    )
    assert json_path.exists()
    assert csv_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "strategy_stats" in payload
    assert "hotspots" in payload
    assert updated.report_stats
    assert {row.name for row in updated.report_stats} == {"json", "csv", "console"}
    assert "Performance Profile" in console
    assert "Hotspots" in console

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert any(row["section"] == "strategy_execution" for row in rows)
    assert any(row["symbol"] == "RELIANCE" for row in rows)


def test_profile_limit_and_workers(ohlcv_dir: Path, tmp_path: Path) -> None:
    config = UniverseValidationConfig(
        storage_dir=ohlcv_dir,
        output_dir=tmp_path / "logs",
        workers=2,
        limit=2,
    )
    profiler = ValidationProfiler(config, show_progress=False)
    report = profiler.profile(strategy_names=["ema_trend"])
    assert len(report.symbols) == 2
    assert len(report.stock_breakdowns) == 2
    text = format_console_report(report)
    assert "Parquet Loading" in text or "parquet" in text.lower()
