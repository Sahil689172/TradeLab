"""Schemas for Professional EMA evaluation (Phase A4Y.1.5)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Verdict(str, Enum):
    IMPROVED = "Improved"
    SAME = "Same"
    WORSE = "Worse"


class PerformanceMetrics(BaseModel):
    """Full performance suite for one mode (raw or professional)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    average_profit: float = 0.0
    average_loss: float = 0.0
    largest_profit: float = 0.0
    largest_loss: float = 0.0
    profit_factor: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    return_pct: float = 0.0
    cagr: float = 0.0
    max_drawdown: float = 0.0
    average_drawdown: float = 0.0
    longest_drawdown_days: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    volatility: float = 0.0
    expectancy: float = 0.0
    average_holding_days: float = 0.0
    median_holding_days: float = 0.0
    exposure_pct: float = 0.0
    average_position_size: float = 0.0
    capital_utilization: float = 0.0
    commission_paid: float = 0.0
    slippage_paid: float = 0.0
    risk_reward_ratio: float = 0.0
    recovery_factor: float = 0.0
    ulcer_index: float = 0.0
    initial_capital: float = 0.0
    final_equity: float = 0.0
    symbols_evaluated: int = 0


class SignalFunnelMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_buy: int = 0
    raw_sell: int = 0
    professional_buy: int = 0
    professional_sell: int = 0
    rejected_ema200: int = 0
    rejected_adx: int = 0
    rejected_volume: int = 0
    rejected_atr: int = 0
    rejected_other: int = 0
    acceptance_rate: float = 0.0
    rejection_rate: float = 0.0
    signal_reduction_pct: float = 0.0


class FilterEffectivenessRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filter_name: str
    signals_examined: int = 0
    signals_rejected: int = 0
    signals_accepted: int = 0
    average_profit_after_filter: float = 0.0
    average_loss_after_filter: float = 0.0
    improvement_pct: float = 0.0


class MetricComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    raw_value: float
    professional_value: float
    delta: float
    verdict: Verdict
    higher_is_better: bool = True


class StatisticalSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    paired_mean_delta: float = 0.0
    bootstrap_ci_low: float = 0.0
    bootstrap_ci_high: float = 0.0
    significance: str = "inconclusive"
    overall_verdict: Verdict = Verdict.SAME
    trade_count_raw: int = 0
    trade_count_professional: int = 0
    notes: tuple[str, ...] = ()


class EvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    phase: str = "A4Y.1.5"
    title: str = "TradeLab Professional EMA Evaluation"
    symbols: tuple[str, ...]
    period_start: str | None = None
    period_end: str | None = None
    raw: PerformanceMetrics
    professional: PerformanceMetrics
    signal_funnel: SignalFunnelMetrics
    filter_effectiveness: tuple[FilterEffectivenessRow, ...]
    metric_comparisons: tuple[MetricComparison, ...]
    statistics: StatisticalSummary
    overall_improvement: bool = False
    professional_recommended: bool = False
    executive_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
