"""Tests for universe strategy validation (Phase A4.14)."""

from __future__ import annotations

import csv
import json
import runpy
from pathlib import Path

import pandas as pd
import pytest

from app.services.universe_validation import (
    UniverseValidationConfig,
    UniverseValidationEngine,
    discover_ohlcv_symbols,
    format_console_summary,
    resolve_universe_symbols,
    synthetic_session_features,
    write_reports,
)
from app.services.universe_validation.aggregation import (
    aggregate_stock_stats,
    aggregate_strategy_stats,
)
from app.services.universe_validation.schemas import UniverseCellResult


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
    for symbol, base in (("RELIANCE", 100.0), ("TCS", 200.0), ("INFY", 150.0)):
        # Enough history for levels + RS/momentum lookbacks (≈12m trading days)
        _write_ohlcv(storage / f"{symbol}.parquet", bars=280, base=base)
        _write_features(storage / f"{symbol}_features.parquet", bars=280, base=base)
    # Noise that must be ignored by discovery
    _write_features(storage / "NOISE_features.parquet", bars=40)
    return storage


def test_discover_ohlcv_ignores_features(ohlcv_dir: Path) -> None:
    symbols = discover_ohlcv_symbols(ohlcv_dir)
    assert symbols == ["INFY", "RELIANCE", "TCS"]
    assert all(not name.endswith("_FEATURES") for name in symbols)


def test_resolve_universe_symbols_limit_and_filter(ohlcv_dir: Path) -> None:
    all_symbols = resolve_universe_symbols(ohlcv_dir, symbols=["all"])
    assert all_symbols == ["INFY", "RELIANCE", "TCS"]

    limited = resolve_universe_symbols(ohlcv_dir, symbols=["all"], limit=2)
    assert limited == ["INFY", "RELIANCE"]

    selected = resolve_universe_symbols(ohlcv_dir, symbols=["tcs", "RELIANCE", "tcs"])
    assert selected == ["RELIANCE", "TCS"]


def test_single_stock_validation(ohlcv_dir: Path, tmp_path: Path) -> None:
    engine = UniverseValidationEngine(
        UniverseValidationConfig(
            storage_dir=ohlcv_dir,
            output_dir=tmp_path / "logs",
            workers=1,
            allow_synthetic=False,
        ),
    )
    cells, elapsed_ms, load_error = engine.validate_symbol(
        "RELIANCE",
        strategy_names=["ema_trend"],
    )
    assert load_error is None
    assert elapsed_ms >= 0.0
    assert len(cells) == 1
    assert cells[0].symbol == "RELIANCE"
    assert cells[0].strategy == "ema_trend"
    assert cells[0].status == "PASS", cells[0].errors


def test_multiple_stock_validation(ohlcv_dir: Path, tmp_path: Path) -> None:
    engine = UniverseValidationEngine(
        UniverseValidationConfig(
            storage_dir=ohlcv_dir,
            output_dir=tmp_path / "logs",
            workers=2,
            limit=2,
        ),
    )
    report = engine.validate(
        symbols=["RELIANCE", "TCS"],
        strategy_names=["ema_trend", "darvas_box"],
    )
    assert report.symbols == ["RELIANCE", "TCS"]
    assert set(report.strategies) == {"ema_trend", "darvas_box"}
    assert report.total_cells == 4
    assert report.total_failed == 0, [
        (cell.symbol, cell.strategy, cell.errors)
        for cell in report.cells
        if cell.status != "PASS"
    ]
    assert len(report.strategy_stats) == 2
    assert len(report.stock_stats) == 2
    for stats in report.strategy_stats:
        assert stats.stocks_tested == 2
        assert stats.passed == 2
        assert stats.failed == 0


def test_entire_universe_validation_all_strategies(ohlcv_dir: Path, tmp_path: Path) -> None:
    engine = UniverseValidationEngine(
        UniverseValidationConfig(
            storage_dir=ohlcv_dir,
            output_dir=tmp_path / "logs",
            workers=2,
            allow_synthetic=True,
        ),
    )
    report = engine.validate(symbols=["all"], strategy_names=["all"])
    assert len(report.symbols) == 3
    assert len(report.strategies) == 12
    assert report.total_cells == 36
    failed = [cell for cell in report.cells if cell.status != "PASS"]
    assert not failed, {
        f"{cell.symbol}/{cell.strategy}": cell.errors for cell in failed
    }
    assert report.total_passed == 36
    assert report.total_failed == 0


def test_orb_passes_on_daily_ohlcv_via_session_expansion(
    ohlcv_dir: Path,
    tmp_path: Path,
) -> None:
    """ORB needs multi-bar sessions; Context Provider expands daily → session."""
    engine = UniverseValidationEngine(
        UniverseValidationConfig(
            storage_dir=ohlcv_dir,
            output_dir=tmp_path / "logs",
            workers=1,
        ),
    )
    cells, _, load_error = engine.validate_symbol(
        "RELIANCE",
        strategy_names=["opening_range_breakout"],
    )
    assert load_error is None
    assert len(cells) == 1
    assert cells[0].status == "PASS", cells[0].errors


def test_report_generation(ohlcv_dir: Path, tmp_path: Path) -> None:
    engine = UniverseValidationEngine(
        UniverseValidationConfig(
            storage_dir=ohlcv_dir,
            output_dir=tmp_path / "logs",
            workers=1,
        ),
    )
    report = engine.validate(symbols=["RELIANCE"], strategy_names=["ema"])
    text = format_console_summary(report)
    assert "Universe Strategy Validation" in text
    assert "ema_trend" in text
    assert "RELIANCE" in text

    out = tmp_path / "logs"
    json_path, csv_path = write_reports(report, out)
    assert json_path.exists()
    assert csv_path.exists()
    assert json_path.name == "universe_validation.json"
    assert csv_path.name == "universe_validation.csv"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total_cells"] == 1
    assert payload["symbols"] == ["RELIANCE"]

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["strategy"] == "ema_trend"
    assert rows[0]["status"] == "PASS"


def test_aggregation_helpers() -> None:
    cells = [
        UniverseCellResult(
            symbol="AAA",
            strategy="ema_trend",
            status="PASS",
            signal="BUY",
            confidence=70.0,
            holding=5.0,
            elapsed_ms=10.0,
        ),
        UniverseCellResult(
            symbol="BBB",
            strategy="ema_trend",
            status="FAIL",
            errors=["boom"],
            elapsed_ms=5.0,
        ),
        UniverseCellResult(
            symbol="AAA",
            strategy="vwap",
            status="PASS",
            signal="HOLD",
            confidence=40.0,
            holding=2.0,
            elapsed_ms=8.0,
        ),
    ]
    strategy_stats = aggregate_strategy_stats(
        cells,
        strategy_order=["ema_trend", "vwap"],
    )
    assert strategy_stats[0].stocks_tested == 2
    assert strategy_stats[0].passed == 1
    assert strategy_stats[0].failed == 1
    assert strategy_stats[0].buy_signals == 1
    assert strategy_stats[1].hold_signals == 1

    stock_stats = aggregate_stock_stats(
        cells,
        symbol_order=["AAA", "BBB"],
        stock_elapsed_ms={"AAA": 20.0, "BBB": 5.0},
    )
    assert stock_stats[0].strategies_passed == 2
    assert stock_stats[0].strategies_failed == 0
    assert stock_stats[0].execution_time_ms == 20.0
    assert stock_stats[1].strategies_failed == 1


def test_cli_arguments_and_main(ohlcv_dir: Path, tmp_path: Path) -> None:
    script = Path("backend/scripts/validate_universe.py")
    assert script.exists()
    ns = runpy.run_path(str(script), run_name="not_main")
    assert "parse_args" in ns
    assert "main" in ns

    args = ns["parse_args"](
        [
            "--symbol",
            "RELIANCE",
            "--strategy",
            "ema_trend",
            "--limit",
            "10",
            "--workers",
            "2",
            "--storage-dir",
            str(ohlcv_dir),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert args.symbols == ["RELIANCE"]
    assert args.strategies == ["ema_trend"]
    assert args.limit == 10
    assert args.workers == 2

    code = ns["main"](
        [
            "--symbol",
            "RELIANCE",
            "--strategy",
            "ema_trend",
            "--workers",
            "1",
            "--storage-dir",
            str(ohlcv_dir),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert code == 0
    assert (tmp_path / "out" / "universe_validation.json").exists()
    assert (tmp_path / "out" / "universe_validation.csv").exists()


def test_synthetic_fallback_single_stock(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    engine = UniverseValidationEngine(
        UniverseValidationConfig(
            storage_dir=empty,
            output_dir=tmp_path / "logs",
            workers=1,
            allow_synthetic=True,
        ),
    )
    features = synthetic_session_features(symbol="SYNTH", bars=100)
    cells, _, load_error = engine.validate_symbol(
        "SYNTH",
        strategy_names=["ema_trend"],
        features=features,
    )
    assert load_error is None
    assert cells[0].status == "PASS", cells[0].errors
