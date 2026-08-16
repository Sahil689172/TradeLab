"""Monte Carlo schemas (Phase A5.6).

This layer consumes completed-trade copies. It does not generate trades and
does not claim to forecast future profitability.
"""

from __future__ import annotations

import math
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


PERCENTILE_LEVELS: tuple[int, ...] = (1, 5, 10, 25, 50, 75, 90, 95, 99)


class SamplingMethod(str, Enum):
    """Implemented resampling methods. Unsupported names are not advertised as live."""

    TRADE_SHUFFLE = "shuffle"
    BOOTSTRAP = "bootstrap"
    BLOCK_BOOTSTRAP = "block_bootstrap"


class CapitalMode(str, Enum):
    """How completed-trade P&L is applied to equity. Never mixed silently."""

    ADDITIVE_PNL = "ADDITIVE_PNL"
    RETURN_BASED = "RETURN_BASED"
    PATH_DEPENDENT_EQUITY = "PATH_DEPENDENT_EQUITY"


class EngineMode(str, Enum):
    """Which Monte Carlo engine the facade dispatches to."""

    TRADE_RESAMPLING = "trade_resampling"
    PATH_DEPENDENT = "path_dependent"


class MonteCarloSizingMode(str, Enum):
    """A5.7 allocation. percent_of_equity and fixed_fractional both use A5.2 percent-of-cash."""

    PERCENT_OF_EQUITY = "percent_of_equity"
    FIXED_FRACTIONAL = "fixed_fractional"
    FIXED_CASH = "fixed_cash"


class SampleQuality(str, Enum):
    """Reporting-quality label. Not a claim of statistical sufficiency."""

    INVALID = "INVALID"
    EXTREMELY_LOW = "EXTREMELY_LOW"
    LOW = "LOW"
    LIMITED = "LIMITED"
    MODERATE = "MODERATE"
    STRONGER = "STRONGER"


class MonteCarloVerdict(str, Enum):
    """Evidence verdict. Constrained by sample size; not PASS/FAIL."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    WEAK = "WEAK"
    LIMITED = "LIMITED"
    PROMISING = "PROMISING"
    ROBUST = "ROBUST"


class RobustnessBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


RESAMPLING_LIMITATION = (
    "Trade-resampling Monte Carlo applies historical net_profit (ADDITIVE_PNL) or "
    "trade returns (RETURN_BASED) to copies of completed trades. It does not re-run "
    "position sizing, order execution, or the position manager. Simulations resample "
    "historical evidence; they do not create new independent historical observations."
)

PATH_DEPENDENT_LIMITATION = (
    "Path-dependent portfolio Monte Carlo resamples historical completed-trade "
    "prices and reallocates capital from current cash after each round-trip using "
    "A5.2 position sizing, slippage, and brokerage. It does not replay candles, "
    "re-generate strategy signals, or create new independent historical observations."
)

PERCENTILE_METHOD = (
    "numpy.percentile method='linear' — Monte Carlo percentile interval, "
    "not a statistical confidence interval"
)


class MonteCarloConfig(BaseModel):
    """Knobs for a Monte Carlo run. Sampling never mutates source trades."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    simulations: int = Field(default=10_000, ge=1, le=1_000_000)
    initial_capital: float = Field(default=1_000_000.0, gt=0.0)
    random_seed: int = Field(default=42)
    sampling_method: SamplingMethod = SamplingMethod.BOOTSTRAP
    capital_mode: CapitalMode = CapitalMode.ADDITIVE_PNL
    block_size: int = Field(default=5, ge=1)
    include_cost_perturbation: bool = False
    slippage_range_bps: tuple[float, ...] = (0.0, 5.0, 10.0, 15.0, 20.0)
    base_slippage_bps: float = Field(default=5.0, ge=0.0)
    commission_range_mult: tuple[float, ...] = (1.0,)
    # <= 1.0: fraction of initial capital. > 1.0: absolute rupee floor.
    ruin_threshold: float = Field(default=0.5, gt=0.0)
    return_thresholds: tuple[float, ...] = (0.10, 0.20)
    drawdown_thresholds: tuple[float, ...] = (0.10, 0.20, 0.30)
    store_simulation_summaries: bool = False
    engine_mode: EngineMode = EngineMode.TRADE_RESAMPLING
    sizing_mode: MonteCarloSizingMode = MonteCarloSizingMode.PERCENT_OF_EQUITY
    position_percent: float = Field(default=10.0, gt=0.0, le=100.0)
    fixed_cash_amount: float | None = None
    brokerage_rate: float = Field(default=0.0003, ge=0.0)
    brokerage_flat: float = Field(default=0.0, ge=0.0)
    allow_fractional_shares: bool = True
    min_quantity: float = Field(default=1.0, gt=0.0)
    compare_engines: bool = False

    @property
    def slippage_bps(self) -> float:
        """CLI ``--slippage-bps`` maps here (same value as ``base_slippage_bps``)."""
        return self.base_slippage_bps

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

    @field_validator("pnl", "return_pct", "gross_pnl", "costs", "brokerage", "slippage")
    @classmethod
    def finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be a finite number (NaN/inf rejected)")
        return value


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
    net_profit: float = 0.0
    max_drawdown_pct: float = 0.0
    volatility: float = 0.0
    sharpe: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    trade_count: int = Field(default=0, ge=0)
    total_cost: float = 0.0
    total_slippage_cost: float = 0.0
    total_brokerage_cost: float = 0.0
    gross_pnl: float = 0.0


class CostSensitivityRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slippage_bps: float
    commission_mult: float = 1.0
    median_return: float
    p95_max_drawdown: float
    probability_of_loss: float
    probability_of_profit: float
    base_cost: float = 0.0
    scenario_cost: float = 0.0
    incremental_cost: float = 0.0
    final_simulated_pnl: float = 0.0
    brokerage_cost: float = 0.0
    slippage_cost: float = 0.0
    total_execution_cost: float = 0.0
    median_ending_equity: float = 0.0


class EngineComparison(BaseModel):
    """A5.6 vs A5.7 on the same trades/seed/simulations. Not a quality ranking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resampling_median_return: float = 0.0
    resampling_p95_max_drawdown: float = 0.0
    resampling_probability_of_loss: float = 0.0
    path_dependent_median_return: float = 0.0
    path_dependent_p95_max_drawdown: float = 0.0
    path_dependent_probability_of_loss: float = 0.0
    modeling_difference: str = (
        "A5.6 adds historical rupee net_profit (additive). A5.7 reallocates a "
        "fraction of current cash to each resampled trade's price path using A5.2 "
        "costs. Different numbers do not mean one engine is more profitable."
    )


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
    capital_mode: CapitalMode = CapitalMode.ADDITIVE_PNL
    capital_model: str = ""
    engine_kind: str = "TradeResamplingMonteCarlo"
    block_size: int | None = None
    initial_capital: float
    source_trade_count: int
    sample_quality: SampleQuality = SampleQuality.INVALID
    verdict: MonteCarloVerdict = MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    resampling_limitation: str = RESAMPLING_LIMITATION
    percentile_method: str = PERCENTILE_METHOD
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
    comparison: EngineComparison | None = None
    position_sizing_mode: str | None = None
    position_size_parameters: dict[str, float] = Field(default_factory=dict)
    execution_cost_parameters: dict[str, float] = Field(default_factory=dict)
