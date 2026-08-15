"""Monte Carlo schemas (Phase A5.6).

This layer consumes completed-trade copies. It does not generate trades and
does not claim to forecast future profitability.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


PERCENTILE_LEVELS: tuple[int, ...] = (1, 5, 10, 25, 50, 75, 90, 95, 99)


class SamplingMethod(str, Enum):
    """Implemented resampling methods. Unsupported names are not advertised as live."""

    TRADE_SHUFFLE = "shuffle"
    BOOTSTRAP = "bootstrap"


class RobustnessBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MonteCarloConfig(BaseModel):
    """Knobs for a Monte Carlo run. Sampling never mutates source trades."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    simulations: int = Field(default=10_000, ge=1, le=1_000_000)
    initial_capital: float = Field(default=1_000_000.0, gt=0.0)
    random_seed: int = Field(default=42)
    sampling_method: SamplingMethod = SamplingMethod.BOOTSTRAP
    include_cost_perturbation: bool = False
    slippage_range_bps: tuple[float, ...] = (0.0, 5.0, 10.0, 15.0, 20.0)
    base_slippage_bps: float = Field(default=5.0, ge=0.0)
    commission_range_mult: tuple[float, ...] = (1.0,)
    # <= 1.0: fraction of initial capital. > 1.0: absolute rupee floor.
    ruin_threshold: float = Field(default=0.5, gt=0.0)
    return_thresholds: tuple[float, ...] = (0.10, 0.20)
    drawdown_thresholds: tuple[float, ...] = (0.10, 0.20, 0.30)
    store_simulation_summaries: bool = False

    @field_validator("slippage_range_bps", "commission_range_mult", "return_thresholds", "drawdown_thresholds")
    @classmethod
    def nonempty_tuple(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not value:
            raise ValueError("tuple must not be empty")
        return value

    @property
    def ruin_equity(self) -> float:
        """Equity level treated as ruin for this run (documented, not a universal standard)."""
        if self.ruin_threshold <= 1.0:
            return self.initial_capital * self.ruin_threshold
        return self.ruin_threshold


class MonteCarloTrade(BaseModel):
    """Simulation representation copied from a completed historical trade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pnl: float
    return_pct: float = 0.0
    costs: float = Field(default=0.0, ge=0.0)
    brokerage: float = Field(default=0.0, ge=0.0)
    slippage: float = Field(default=0.0, ge=0.0)
    gross_pnl: float = 0.0
    holding_period: int = Field(default=0, ge=0)
    win_loss: int = Field(default=0, description="-1 loss, 0 flat, +1 win")
    source_trade_id: str = ""
    symbol: str = ""
    quantity: float = Field(default=0.0, ge=0.0)
    entry_price: float = Field(default=0.0, ge=0.0)
    exit_price: float = Field(default=0.0, ge=0.0)


class PercentileSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    p01: float = 0.0
    p05: float = 0.0
    p10: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0


class SimulationSummary(BaseModel):
    """Per-simulation aggregates. Equity paths are not retained by default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    final_equity: float
    total_return: float
    max_drawdown: float
    min_equity: float
    peak_equity: float
    losing_trades: int = Field(..., ge=0)
    longest_losing_streak: int = Field(..., ge=0)
    longest_winning_streak: int = Field(..., ge=0)


class CostSensitivityRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slippage_bps: float
    commission_mult: float = 1.0
    median_return: float
    p95_max_drawdown: float
    probability_of_loss: float
    probability_of_profit: float


class RobustnessAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    band: RobustnessBand
    score: float = Field(..., ge=0.0, le=100.0)
    formula: str
    reasons: list[str] = Field(default_factory=list)


class HistoricalSnapshot(BaseModel):
    """Original-sequence stats (not a Monte Carlo forecast)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trades: int = 0
    return_pct: float = 0.0
    max_drawdown: float = 0.0
    sharpe_trade_level: float = 0.0
    net_profit: float = 0.0
    win_rate: float = 0.0


class MonteCarloResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    simulations: int
    seed: int
    sampling_method: SamplingMethod
    initial_capital: float
    source_trade_count: int
    historical: HistoricalSnapshot
    final_capital_percentiles: PercentileSummary
    return_percentiles: PercentileSummary
    max_drawdown_percentiles: PercentileSummary
    max_drawdown_abs_percentiles: PercentileSummary
    min_equity_percentiles: PercentileSummary
    longest_losing_streak_percentiles: PercentileSummary
    probability_of_loss: float = Field(..., ge=0.0, le=1.0)
    probability_of_profit: float = Field(..., ge=0.0, le=1.0)
    probability_of_ruin: float = Field(..., ge=0.0, le=1.0)
    ruin_equity: float
    ruin_definition: str
    threshold_probabilities: dict[str, float] = Field(default_factory=dict)
    worst_case: SimulationSummary | None = None
    best_case: SimulationSummary | None = None
    median_case: SimulationSummary | None = None
    robustness: RobustnessAssessment
    cost_sensitivity: list[CostSensitivityRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    strategy: str = ""
    symbol: str = ""
    period: str = ""
    simulation_summaries: list[SimulationSummary] | None = None
