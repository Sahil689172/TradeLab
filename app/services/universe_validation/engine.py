"""Universe validation engine — run all strategies across OHLCV symbols."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.strategy_context import ContextProviderConfig, StrategyContextProvider
from app.services.trade_recommendation.strategy_validation import (
    StrategyValidationFramework,
)
from app.services.universe_validation.aggregation import (
    aggregate_stock_stats,
    aggregate_strategy_stats,
)
from app.services.universe_validation.config import UniverseValidationConfig
from app.services.universe_validation.discovery import resolve_universe_symbols
from app.services.universe_validation.loaders import (
    load_symbol_features,
    synthetic_session_features,
)
from app.services.universe_validation.schemas import (
    UniverseCellResult,
    UniverseValidationReport,
)

logger = get_logger(__name__)


class UniverseValidationEngine:
    """Validate every strategy against every discovered OHLCV symbol.

    Not a backtester — no PnL. Verifies execution + TradeRecommendation contract.
    Parallelism is at the **symbol** grain so each worker owns fresh strategy
    instances (strategies mutate internal state). Aggregation sorts by symbol /
    strategy for deterministic reports regardless of completion order.
    """

    def __init__(
        self,
        config: UniverseValidationConfig | None = None,
        *,
        framework_factory: type[StrategyValidationFramework] | None = None,
    ) -> None:
        settings = get_settings()
        self._config = config or UniverseValidationConfig()
        storage = self._config.storage_dir or Path(settings.parquet_storage_dir)
        output = self._config.output_dir or Path(settings.log_directory)
        self._storage_dir = Path(storage)
        self._output_dir = Path(output)
        self._framework_factory = framework_factory or StrategyValidationFramework

    @property
    def config(self) -> UniverseValidationConfig:
        return self._config

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def validate(
        self,
        *,
        symbols: list[str] | None = None,
        strategy_names: list[str] | None = None,
    ) -> UniverseValidationReport:
        """Run universe validation and return a structured report."""
        wall_start = time.perf_counter()
        resolved_symbols = resolve_universe_symbols(
            self._storage_dir,
            symbols=symbols,
            limit=self._config.limit,
        )
        framework = self._framework_factory(timeframe=self._config.timeframe)
        strategy_instances = framework.resolve_strategies(strategy_names)
        strategy_order = [strategy.name for strategy in strategy_instances]
        if not resolved_symbols:
            return self._empty_report(strategy_order=strategy_order)

        logger.info(
            "Universe validation: %d symbols × %d strategies (workers=%d)",
            len(resolved_symbols),
            len(strategy_order),
            self._config.workers,
        )

        stock_results = self._run_parallel(
            resolved_symbols,
            strategy_names=strategy_names or ["all"],
        )

        cells: list[UniverseCellResult] = []
        stock_elapsed: dict[str, float] = {}
        load_errors: dict[str, str] = {}
        for symbol in resolved_symbols:
            result = stock_results[symbol]
            cells.extend(result["cells"])  # type: ignore[arg-type]
            stock_elapsed[symbol] = float(result["elapsed_ms"])
            if result.get("load_error"):
                load_errors[symbol] = str(result["load_error"])

        cells.sort(key=lambda cell: (cell.symbol, cell.strategy))
        strategy_stats = aggregate_strategy_stats(cells, strategy_order=strategy_order)
        stock_stats = aggregate_stock_stats(
            cells,
            symbol_order=resolved_symbols,
            stock_elapsed_ms=stock_elapsed,
            load_errors=load_errors,
        )
        total_passed = sum(1 for cell in cells if cell.status == "PASS")
        total_failed = len(cells) - total_passed
        wall_ms = (time.perf_counter() - wall_start) * 1000.0

        return UniverseValidationReport(
            generated_at=datetime.now(timezone.utc),
            timeframe=self._config.timeframe,
            storage_dir=str(self._storage_dir),
            workers=self._config.workers,
            symbols=list(resolved_symbols),
            strategies=list(strategy_order),
            total_cells=len(cells),
            total_passed=total_passed,
            total_failed=total_failed,
            total_execution_time_ms=wall_ms,
            strategy_stats=strategy_stats,
            stock_stats=stock_stats,
            cells=cells,
        )

    def validate_symbol(
        self,
        symbol: str,
        *,
        strategy_names: list[str] | None = None,
        features: pd.DataFrame | None = None,
    ) -> tuple[list[UniverseCellResult], float, str | None]:
        """Validate all strategies for a single symbol (sequential, timed)."""
        return self._validate_one_symbol(
            symbol.strip().upper(),
            strategy_names=strategy_names or ["all"],
            features=features,
        )

    def _run_parallel(
        self,
        symbols: list[str],
        *,
        strategy_names: list[str],
    ) -> dict[str, dict[str, object]]:
        workers = min(self._config.workers, max(1, len(symbols)))
        results: dict[str, dict[str, object]] = {}

        if workers == 1 or len(symbols) == 1:
            for symbol in symbols:
                cells, elapsed, load_error = self._validate_one_symbol(
                    symbol,
                    strategy_names=strategy_names,
                )
                results[symbol] = {
                    "cells": cells,
                    "elapsed_ms": elapsed,
                    "load_error": load_error,
                }
            return results

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    self._validate_one_symbol,
                    symbol,
                    strategy_names=strategy_names,
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                cells, elapsed, load_error = future.result()
                results[symbol] = {
                    "cells": cells,
                    "elapsed_ms": elapsed,
                    "load_error": load_error,
                }
        return results

    def _validate_one_symbol(
        self,
        symbol: str,
        *,
        strategy_names: list[str],
        features: pd.DataFrame | None = None,
    ) -> tuple[list[UniverseCellResult], float, str | None]:
        """Worker body: fresh framework + strategies per symbol (thread-safe)."""
        stock_start = time.perf_counter()
        framework = self._framework_factory(
            timeframe=self._config.timeframe,
            context_provider=StrategyContextProvider(
                ContextProviderConfig(
                    timeframe=self._config.timeframe,
                    storage_dir=str(self._storage_dir),
                    allow_synthetic_features=self._config.allow_synthetic,
                ),
                storage_dir=self._storage_dir,
            ),
        )
        strategies = framework.resolve_strategies(strategy_names)

        load_error: str | None = None
        frame = features
        if frame is None:
            frame, load_error = self._load_features(symbol)

        cells: list[UniverseCellResult] = []
        if frame is None:
            message = load_error or f"Unable to load OHLCV/features for {symbol}"
            for strategy in strategies:
                cells.append(
                    UniverseCellResult(
                        symbol=symbol,
                        strategy=strategy.name,
                        status="FAIL",
                        errors=[message],
                    ),
                )
            elapsed = (time.perf_counter() - stock_start) * 1000.0
            return cells, elapsed, message

        for strategy in strategies:
            cell_start = time.perf_counter()
            row = framework.validate_strategy(strategy, frame, symbol=symbol)
            elapsed_ms = (time.perf_counter() - cell_start) * 1000.0
            cells.append(
                UniverseCellResult(
                    symbol=symbol,
                    strategy=row.strategy,
                    status=row.status,
                    signal=_signal_from_row(row),
                    confidence=float(row.average_confidence),
                    holding=float(row.average_holding),
                    elapsed_ms=elapsed_ms,
                    errors=list(row.validation_errors),
                ),
            )

        elapsed = (time.perf_counter() - stock_start) * 1000.0
        return cells, elapsed, load_error

    def _load_features(self, symbol: str) -> tuple[pd.DataFrame | None, str | None]:
        frame, error = load_symbol_features(symbol, self._storage_dir)
        if frame is not None:
            return frame, None
        if self._config.allow_synthetic:
            return synthetic_session_features(symbol=symbol), None
        return None, error

    def _empty_report(self, *, strategy_order: list[str]) -> UniverseValidationReport:
        return UniverseValidationReport(
            generated_at=datetime.now(timezone.utc),
            timeframe=self._config.timeframe,
            storage_dir=str(self._storage_dir),
            workers=self._config.workers,
            symbols=[],
            strategies=list(strategy_order),
            total_cells=0,
            total_passed=0,
            total_failed=0,
            total_execution_time_ms=0.0,
            strategy_stats=aggregate_strategy_stats([], strategy_order=strategy_order),
            stock_stats=[],
            cells=[],
        )


def _signal_from_row(row: object) -> str | None:
    buy = int(getattr(row, "buy_count", 0) or 0)
    sell = int(getattr(row, "sell_count", 0) or 0)
    hold = int(getattr(row, "hold_count", 0) or 0)
    exit_ = int(getattr(row, "exit_count", 0) or 0)
    if buy:
        return "BUY"
    if sell:
        return "SELL"
    if exit_:
        return "EXIT"
    if hold:
        return "HOLD"
    if getattr(row, "status", None) == "PASS":
        return "HOLD"
    return None
