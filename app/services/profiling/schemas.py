"""Schemas for performance profiling reports."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TimingStats(BaseModel):
    """Aggregate timing statistics for one operation family."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    category: str
    count: int = Field(..., ge=0)
    total_ms: float = Field(..., ge=0.0)
    average_ms: float = Field(..., ge=0.0)
    minimum_ms: float = Field(..., ge=0.0)
    maximum_ms: float = Field(..., ge=0.0)
    share_of_measured_pct: float = Field(default=0.0, ge=0.0)


class StockTimingBreakdown(BaseModel):
    """Per-stock timing rollup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    load_ohlcv_ms: float = 0.0
    load_features_ms: float = 0.0
    context_ms: float = 0.0
    strategy_ms: dict[str, float] = Field(default_factory=dict)
    recommendation_ms: float = 0.0
    total_ms: float = 0.0


class HotspotEntry(BaseModel):
    """One contributor to overall measured runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    category: str
    total_ms: float
    share_pct: float


class RuntimeEstimate(BaseModel):
    """Linear extrapolation from observed average stock runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stocks: int
    estimated_wall_ms: float
    estimated_wall_minutes: float


class PerformanceProfileReport(BaseModel):
    """Full performance profile payload (JSON contract)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    storage_dir: str
    workers: int
    symbols: list[str]
    strategies: list[str]
    wall_time_ms: float
    cpu_time_ms: float
    memory_current_bytes: int
    memory_peak_bytes: int
    discovery_ms: float
    report_generation_ms: float
    parquet_stats: list[TimingStats] = Field(default_factory=list)
    context_stats: list[TimingStats] = Field(default_factory=list)
    strategy_stats: list[TimingStats] = Field(default_factory=list)
    recommendation_stats: list[TimingStats] = Field(default_factory=list)
    report_stats: list[TimingStats] = Field(default_factory=list)
    stock_breakdowns: list[StockTimingBreakdown] = Field(default_factory=list)
    hotspots: list[HotspotEntry] = Field(default_factory=list)
    top_slowest: list[HotspotEntry] = Field(default_factory=list)
    top_fastest: list[HotspotEntry] = Field(default_factory=list)
    average_stock_ms: float = 0.0
    average_strategy_ms: float = 0.0
    runtime_estimates: list[RuntimeEstimate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
