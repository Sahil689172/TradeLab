"""Schemas for universe-wide strategy validation reports."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UniverseCellResult(BaseModel):
    """One strategy × symbol validation outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    strategy: str
    status: str
    signal: str | None = None
    confidence: float = Field(default=0.0, ge=0.0)
    holding: float = Field(default=0.0, ge=0.0)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    errors: list[str] = Field(default_factory=list)


class StrategyUniverseStats(BaseModel):
    """Aggregated stats for one strategy across the universe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str
    stocks_tested: int = Field(..., ge=0)
    passed: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    buy_signals: int = Field(..., ge=0)
    sell_signals: int = Field(..., ge=0)
    hold_signals: int = Field(..., ge=0)
    exit_signals: int = Field(..., ge=0)
    average_confidence: float = Field(..., ge=0.0)
    average_holding: float = Field(..., ge=0.0)
    execution_time_ms: float = Field(..., ge=0.0)


class StockUniverseStats(BaseModel):
    """Aggregated stats for one stock across strategies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    strategies_passed: int = Field(..., ge=0)
    strategies_failed: int = Field(..., ge=0)
    execution_time_ms: float = Field(..., ge=0.0)
    load_error: str | None = None


class UniverseValidationReport(BaseModel):
    """Full universe validation report (JSON contract)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    timeframe: str
    storage_dir: str
    workers: int = Field(..., ge=1)
    symbols: list[str]
    strategies: list[str]
    total_cells: int = Field(..., ge=0)
    total_passed: int = Field(..., ge=0)
    total_failed: int = Field(..., ge=0)
    total_execution_time_ms: float = Field(..., ge=0.0)
    strategy_stats: list[StrategyUniverseStats]
    stock_stats: list[StockUniverseStats]
    cells: list[UniverseCellResult]
