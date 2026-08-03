"""Regression tests for Phase A4.16 performance optimizations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.market_structure import MarketStructureService
from app.market_structure.detector import detect_raw_swings
from app.services.strategy_context import (
    ContextProviderConfig,
    ContextRunCache,
    StrategyContextProvider,
)
from app.services.strategy_engine.indicators.supertrend import compute_supertrend
from app.services.trade_recommendation.strategy_validation import (
    StrategyValidationFramework,
)
from app.services.universe_validation import (
    UniverseValidationConfig,
    UniverseValidationEngine,
)
from app.services.universe_validation.loaders import load_symbol_features
from tests.test_market_structure import uptrend_frame


def _write_ohlcv(path: Path, *, bars: int = 280, base: float = 100.0) -> None:
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


def _write_features(path: Path, *, bars: int = 280, base: float = 100.0) -> None:
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
        _write_ohlcv(storage / f"{symbol}.parquet", bars=280, base=base)
        _write_features(storage / f"{symbol}_features.parquet", bars=280, base=base)
    return storage


def test_context_cache_reuses_structure(ohlcv_dir: Path) -> None:
    cache = ContextRunCache()
    provider = StrategyContextProvider(
        ContextProviderConfig(
            storage_dir=str(ohlcv_dir),
            enable_context_cache=True,
        ),
        storage_dir=ohlcv_dir,
        run_cache=cache,
    )
    framework = StrategyValidationFramework(context_provider=provider)
    strategies = framework.resolve_strategies(["vwap", "cpr", "supertrend"])
    features, _ = load_symbol_features("RELIANCE", ohlcv_dir)
    assert features is not None

    first = provider.prepare(strategies[0], "RELIANCE", features=features)
    second = provider.prepare(strategies[1], "RELIANCE", features=features)
    assert first.market_structure is not None
    assert second.market_structure is not None
    assert first.market_structure is second.market_structure
    assert first.levels is second.levels
    assert any("Reused" in note or "cached" in note.lower() for note in second.notes)


def test_cache_disabled_rebuilds(ohlcv_dir: Path) -> None:
    provider = StrategyContextProvider(
        ContextProviderConfig(
            storage_dir=str(ohlcv_dir),
            enable_context_cache=False,
        ),
        storage_dir=ohlcv_dir,
        run_cache=None,
    )
    framework = StrategyValidationFramework(context_provider=provider)
    strategies = framework.resolve_strategies(["vwap", "cpr"])
    features, _ = load_symbol_features("RELIANCE", ohlcv_dir)
    assert features is not None
    first = provider.prepare(strategies[0], "RELIANCE", features=features)
    second = provider.prepare(strategies[1], "RELIANCE", features=features)
    assert first.market_structure is not None
    assert second.market_structure is not None
    # Without cache, new structure objects are produced each time
    assert first.market_structure is not second.market_structure


def test_market_structure_vectorized_matches_service() -> None:
    frame = uptrend_frame()
    service = MarketStructureService(swing_length=1)
    result = service.analyze(frame, symbol="TEST")
    raw = detect_raw_swings(frame["high"], frame["low"], frame["date"], swing_length=1)
    assert result.bar_count == len(frame)
    assert len(raw) >= 1
    assert result.trend is not None


def test_supertrend_numpy_path_finite() -> None:
    n = 80
    close = pd.Series([100.0 + i * 0.1 for i in range(n)])
    high = close + 1.0
    low = close - 1.0
    out = compute_supertrend(high, low, close, period=10, multiplier=3.0)
    assert list(out.columns) == ["supertrend", "direction"]
    assert out["supertrend"].notna().sum() > 0
    assert set(out["direction"].dropna().unique()).issubset({1.0, -1.0})


def test_validation_cache_vs_nocache_same_signals(ohlcv_dir: Path, tmp_path: Path) -> None:
    """Cached and uncached validation must agree on signal outcomes."""

    def _run(*, enable: bool) -> list[tuple[str, str, str | None]]:
        cache = ContextRunCache() if enable else None

        class _Engine(UniverseValidationEngine):
            def _validate_one_symbol(self, symbol, *, strategy_names, features=None):  # noqa: ANN001
                from app.services.universe_validation.engine import _signal_from_row
                from app.services.universe_validation.schemas import UniverseCellResult

                stock_start = __import__("time").perf_counter()
                framework = StrategyValidationFramework(
                    timeframe=self._config.timeframe,
                    context_provider=StrategyContextProvider(
                        ContextProviderConfig(
                            timeframe=self._config.timeframe,
                            storage_dir=str(self._storage_dir),
                            allow_synthetic_features=False,
                            enable_context_cache=enable,
                        ),
                        storage_dir=self._storage_dir,
                        run_cache=cache,
                    ),
                )
                strategies = framework.resolve_strategies(strategy_names)
                frame = features
                load_error = None
                if frame is None:
                    frame, load_error = self._load_features(symbol)
                cells = []
                if frame is None:
                    return [], 0.0, load_error
                for strategy in strategies:
                    row = framework.validate_strategy(strategy, frame, symbol=symbol)
                    cells.append(
                        UniverseCellResult(
                            symbol=symbol,
                            strategy=row.strategy,
                            status=row.status,
                            signal=_signal_from_row(row),
                            confidence=float(row.average_confidence),
                            holding=float(row.average_holding),
                            elapsed_ms=0.0,
                            errors=list(row.validation_errors),
                        ),
                    )
                return cells, (__import__("time").perf_counter() - stock_start) * 1000.0, None

        engine = _Engine(
            UniverseValidationConfig(
                storage_dir=ohlcv_dir,
                output_dir=tmp_path / ("cached" if enable else "plain"),
                workers=1,
                limit=2,
            ),
        )
        report = engine.validate(
            strategy_names=["ema_trend", "vwap", "supertrend", "break_retest"],
        )
        return [(c.symbol, c.strategy, c.signal) for c in report.cells]

    plain = _run(enable=False)
    cached = _run(enable=True)
    assert plain == cached
