"""Aggregate cell results into per-strategy and per-stock statistics."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from app.services.universe_validation.schemas import (
    StockUniverseStats,
    StrategyUniverseStats,
    UniverseCellResult,
)


def aggregate_strategy_stats(
    cells: list[UniverseCellResult],
    *,
    strategy_order: list[str],
) -> list[StrategyUniverseStats]:
    """Build deterministic per-strategy aggregates in ``strategy_order``."""
    by_strategy: dict[str, list[UniverseCellResult]] = defaultdict(list)
    for cell in cells:
        by_strategy[cell.strategy].append(cell)

    rows: list[StrategyUniverseStats] = []
    for name in strategy_order:
        group = by_strategy.get(name, [])
        passed = sum(1 for cell in group if cell.status == "PASS")
        failed = len(group) - passed
        confidences = [cell.confidence for cell in group if cell.status == "PASS"]
        holdings = [cell.holding for cell in group if cell.status == "PASS"]
        rows.append(
            StrategyUniverseStats(
                strategy=name,
                stocks_tested=len(group),
                passed=passed,
                failed=failed,
                buy_signals=sum(1 for cell in group if cell.signal == "BUY"),
                sell_signals=sum(1 for cell in group if cell.signal == "SELL"),
                hold_signals=sum(1 for cell in group if cell.signal == "HOLD"),
                exit_signals=sum(1 for cell in group if cell.signal == "EXIT"),
                average_confidence=mean(confidences) if confidences else 0.0,
                average_holding=mean(holdings) if holdings else 0.0,
                execution_time_ms=sum(cell.elapsed_ms for cell in group),
            ),
        )
    return rows


def aggregate_stock_stats(
    cells: list[UniverseCellResult],
    *,
    symbol_order: list[str],
    stock_elapsed_ms: dict[str, float] | None = None,
    load_errors: dict[str, str] | None = None,
) -> list[StockUniverseStats]:
    """Build deterministic per-stock aggregates in ``symbol_order``."""
    by_symbol: dict[str, list[UniverseCellResult]] = defaultdict(list)
    for cell in cells:
        by_symbol[cell.symbol].append(cell)

    elapsed = stock_elapsed_ms or {}
    errors = load_errors or {}
    rows: list[StockUniverseStats] = []
    for symbol in symbol_order:
        group = by_symbol.get(symbol, [])
        passed = sum(1 for cell in group if cell.status == "PASS")
        failed = len(group) - passed
        # Prefer wall-clock stock time; fall back to sum of cell times
        stock_time = elapsed.get(symbol)
        if stock_time is None:
            stock_time = sum(cell.elapsed_ms for cell in group)
        rows.append(
            StockUniverseStats(
                symbol=symbol,
                strategies_passed=passed,
                strategies_failed=failed,
                execution_time_ms=stock_time,
                load_error=errors.get(symbol),
            ),
        )
    return rows
