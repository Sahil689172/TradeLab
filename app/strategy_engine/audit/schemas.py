"""Strategy Audit schemas (Phase A4X.8)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrategyAuditMetrics(BaseModel):
    """Per-strategy audit aggregates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = Field(..., min_length=1)
    symbol: str = Field(default="UNKNOWN", min_length=1)
    evaluations: int = Field(default=0, ge=0)
    buy_signals: int = Field(default=0, ge=0)
    sell_signals: int = Field(default=0, ge=0)
    hold_signals: int = Field(default=0, ge=0)
    exit_signals: int = Field(default=0, ge=0)
    average_hold: float = Field(default=0.0, ge=0.0)
    average_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    average_risk_reward: float = Field(default=0.0, ge=0.0)
    average_win_expectancy: float = Field(default=0.0)
    filter_evaluations: int = Field(default=0, ge=0)
    filter_accepted: int = Field(default=0, ge=0)
    filter_rejected: int = Field(default=0, ge=0)
    filter_acceptance_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    filter_rejection_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    filter_integration_ok: bool = False
    runtime_errors: tuple[str, ...] = ()
    ready: bool = False

    @field_validator("strategy_name", "symbol")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class StrategyScorecardRow(BaseModel):
    """One row of the strategy scorecard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str
    symbol: str
    buy_signals: int
    sell_signals: int
    hold_signals: int
    average_hold: float
    average_confidence: float
    average_risk_reward: float
    average_win_expectancy: float
    filter_acceptance_rate: float
    filter_rejection_rate: float
    filter_integration_ok: bool
    composite_score: float = Field(..., ge=0.0, le=100.0)
    ready: bool
    notes: str = ""


class StrategyScorecard(BaseModel):
    """Scorecard covering every audited strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    rows: tuple[StrategyScorecardRow, ...]
    ready_count: int = Field(..., ge=0)
    total_count: int = Field(..., ge=0)

    @model_validator(mode="after")
    def counts_consistent(self) -> StrategyScorecard:
        if self.total_count != len(self.rows):
            raise ValueError("total_count must equal number of scorecard rows")
        if self.ready_count > self.total_count:
            raise ValueError("ready_count cannot exceed total_count")
        return self


class StrategyComparisonRow(BaseModel):
    """Ranked comparison entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(..., ge=1)
    strategy_name: str
    composite_score: float
    average_confidence: float
    average_risk_reward: float
    average_win_expectancy: float
    filter_acceptance_rate: float
    actionable_signals: int
    ready: bool


class StrategyComparisonTable(BaseModel):
    """Cross-strategy comparison ranked by composite score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    rows: tuple[StrategyComparisonRow, ...]


class ReadinessCheck(BaseModel):
    """Single readiness criterion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    detail: str = ""


class ProfessionalReadinessReport(BaseModel):
    """Professional readiness report for the audited universe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    title: str = "TradeLab Professional Strategy Readiness Report"
    summary: str
    overall_ready: bool
    checks: tuple[ReadinessCheck, ...]
    ready_strategies: tuple[str, ...]
    not_ready_strategies: tuple[str, ...]
    highlights: tuple[str, ...] = ()


class StrategyAuditReport(BaseModel):
    """Full audit artifact: metrics + scorecard + comparison + readiness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    metrics: tuple[StrategyAuditMetrics, ...]
    scorecard: StrategyScorecard
    comparison: StrategyComparisonTable
    readiness: ProfessionalReadinessReport
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
