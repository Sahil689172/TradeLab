"""A5.8 portfolio-risk schemas.

This layer consumes completed A5.2 trades. It does not generate signals and
does not rewrite A5.2 / A5.3 / A5.6 / A5.7 numerical cores.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting.monte_carlo.schemas import PercentileSummary, SamplingMethod
from app.backtesting.order_execution.schemas import ExitReason


LIMITATION = (
    "Portfolio risk overlays completed historical trades onto a shared cash book. "
    "Independent per-symbol backtest quantities are not treated as a live portfolio. "
    "Each entry is re-sized from current cash using the configured allocation policy "
    "and A5.2 cost formulas. Monte Carlo resamples historical evidence; it does not "
    "create new independent historical observations or new market paths."
)


class AllocationPolicy(str, Enum):
    EQUAL_CAPITAL = "equal_capital"
    EQUAL_RISK = "equal_risk"
    FIXED_PERCENT_EQUITY = "fixed_percent_equity"


class LimitAction(str, Enum):
    """REJECT is the default. SCALE is explicit and recorded, never silent."""

    REJECT = "reject"
    SCALE = "scale"


class AllocationStatus(str, Enum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class PortfolioRejectReason(str, Enum):
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    CANNOT_AFFORD_MIN_QUANTITY = "CANNOT_AFFORD_MIN_QUANTITY"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    MAX_PORTFOLIO_EXPOSURE = "MAX_PORTFOLIO_EXPOSURE"
    MAX_POSITION_PERCENT = "MAX_POSITION_PERCENT"
    MAX_SYMBOL_CONCENTRATION = "MAX_SYMBOL_CONCENTRATION"
    MAX_STRATEGY_CONCENTRATION = "MAX_STRATEGY_CONCENTRATION"
    MAX_PORTFOLIO_DRAWDOWN = "MAX_PORTFOLIO_DRAWDOWN"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
    ALREADY_HOLDING = "ALREADY_HOLDING"
    INVALID_TRADE = "INVALID_TRADE"
    EXECUTION_REJECTED = "EXECUTION_REJECTED"


class PortfolioTrade(BaseModel):
    """Canonical portfolio trade. Keeps symbol and strategy identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str
    symbol: str
    strategy: str = ""
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    quantity: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    trade_return: float = 0.0
    brokerage: float = 0.0
    slippage: float = 0.0
    execution_costs: float = 0.0
    holding_period: int = Field(default=0, ge=0)
    requested_notional: float = 0.0
    allocated_notional: float = 0.0
    exit_reason: str = ExitReason.SELL_RECOMMENDATION.value


class AllocationDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str
    symbol: str
    strategy: str
    timestamp: datetime
    status: AllocationStatus
    reason_code: PortfolioRejectReason | None = None
    reason: str = ""
    requested_budget: float = 0.0
    allocated_budget: float = 0.0
    quantity: float = 0.0


class ExposureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    cash: float
    equity: float
    gross_exposure: float
    net_exposure: float
    invested_capital: float
    utilization_pct: float
    open_positions: int
    largest_position_pct: float
    symbol_weights: dict[str, float] = Field(default_factory=dict)
    strategy_weights: dict[str, float] = Field(default_factory=dict)
    hhi: float = 0.0
    peak_equity: float = 0.0
    drawdown: float = 0.0


class ConcentrationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    largest_symbol: str = ""
    largest_symbol_pct: float = 0.0
    top2_pct: float = 0.0
    top5_pct: float = 0.0
    largest_strategy: str = ""
    largest_strategy_pct: float = 0.0
    hhi: float = 0.0
    hhi_10000: float = 0.0
    peak_largest_symbol_pct: float = 0.0
    peak_hhi: float = 0.0
    note: str = (
        "Weights are open-notional / equity at the snapshot. "
        "A dominant name is reported; it is not auto-rejected unless a limit fires."
    )


class CorrelationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    labels: list[str] = Field(default_factory=list)
    matrix: list[list[float | None]] = Field(default_factory=list)
    average_pairwise: float | None = None
    maximum_pairwise: float | None = None
    highly_correlated_pairs: list[dict[str, float | str]] = Field(default_factory=list)
    min_observations: int = 0
    insufficient: bool = True
    insufficient_pairs: list[str] = Field(default_factory=list)
    note: str = (
        "Pairwise Pearson on timestamp-aligned returns. Missing observations "
        "are left as missing (not zero). Insufficient pairs are not filled in."
    )


class DrawdownReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    duration_events: int = 0
    recovery_events: int | None = None
    worst_period_loss: float = 0.0
    worst_historical_drawdown: float = 0.0
    note: str = (
        "Computed from the shared-book equity curve. Not the sum of per-strategy "
        "maximum drawdowns."
    )


class CostSensitivityRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slippage_bps: float
    median_return: float
    probability_of_loss: float
    p95_max_drawdown: float
    total_execution_cost: float
    incremental_cost: float
    brokerage_cost: float
    slippage_cost: float
    median_ending_equity: float


class PortfolioRiskLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_exposure_pct: float = Field(default=80.0, gt=0.0, le=100.0)
    max_position_pct: float = Field(default=25.0, gt=0.0, le=100.0)
    max_symbol_concentration_pct: float = Field(default=40.0, gt=0.0, le=100.0)
    max_strategy_concentration_pct: float = Field(default=100.0, gt=0.0, le=100.0)
    max_open_positions: int = Field(default=10, ge=1)
    max_portfolio_drawdown_pct: float | None = Field(default=None, gt=0.0, le=100.0)
    max_daily_loss_pct: float | None = Field(default=None, gt=0.0, le=100.0)
    limit_action: LimitAction = LimitAction.REJECT


class PortfolioRiskConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float = Field(default=100_000.0, gt=0.0)
    allocation_policy: AllocationPolicy = AllocationPolicy.FIXED_PERCENT_EQUITY
    position_percent: float = Field(default=20.0, gt=0.0, le=100.0)
    limits: PortfolioRiskLimits = Field(default_factory=PortfolioRiskLimits)
    slippage_bps: float = Field(default=5.0, ge=0.0)
    brokerage_rate: float = Field(default=0.0003, ge=0.0)
    brokerage_flat: float = Field(default=0.0, ge=0.0)
    allow_fractional_shares: bool = False
    min_quantity: float = Field(default=1.0, gt=0.0)
    simulations: int = Field(default=1_000, ge=1, le=1_000_000)
    random_seed: int = 42
    sampling_method: SamplingMethod = SamplingMethod.BOOTSTRAP
    block_size: int = Field(default=5, ge=1)
    include_monte_carlo: bool = True
    compare_a57: bool = False
    include_cost_sensitivity: bool = False
    slippage_range_bps: tuple[float, ...] = (0.0, 5.0, 10.0, 15.0, 20.0)
    ruin_threshold: float = Field(default=0.5, gt=0.0)
    min_correlation_observations: int = Field(default=8, ge=3)
    high_correlation_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    drawdown_thresholds: tuple[float, ...] = (0.10, 0.20, 0.30)

    @property
    def ruin_equity(self) -> float:
        if self.ruin_threshold <= 1.0:
            return self.initial_capital * self.ruin_threshold
        return self.ruin_threshold


class BookReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float
    final_equity: float
    final_cash: float
    net_return: float
    executed_trades: list[PortfolioTrade]
    rejections: list[AllocationDecision]
    snapshots: list[ExposureSnapshot]
    equity_timestamps: list[datetime]
    equity_values: list[float]


class PortfolioRiskResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_kind: str = "PortfolioRiskEngine"
    limitation: str = LIMITATION
    config: PortfolioRiskConfig
    historical_trade_count: int
    symbol_count: int
    strategy_count: int
    executed_trade_count: int
    rejected_count: int
    initial_capital: float
    final_equity: float
    net_return: float
    cagr: float | None = None
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_gross_pnl: float = 0.0
    total_net_pnl: float = 0.0
    total_brokerage: float = 0.0
    total_slippage: float = 0.0
    total_costs: float = 0.0
    cost_pct_of_gross: float | None = None
    average_exposure: float = 0.0
    maximum_exposure: float = 0.0
    average_utilization: float = 0.0
    maximum_utilization: float = 0.0
    maximum_concurrent_positions: int = 0
    concentration: ConcentrationReport
    drawdown: DrawdownReport
    symbol_correlation: CorrelationReport
    strategy_correlation: CorrelationReport
    rejections: list[AllocationDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sample_quality: str = "INVALID"
    simulation_count: int = 0
    seed: int = 42
    return_percentiles: PercentileSummary | None = None
    equity_percentiles: PercentileSummary | None = None
    drawdown_percentiles: PercentileSummary | None = None
    probability_of_loss: float | None = None
    probability_of_profit: float | None = None
    probability_of_ruin: float | None = None
    threshold_probabilities: dict[str, float] = Field(default_factory=dict)
    cost_sensitivity: list[CostSensitivityRow] = Field(default_factory=list)
    a57_median_return: float | None = None
    a57_probability_of_loss: float | None = None
    a57_p95_drawdown: float | None = None
    a57_note: str = (
        "A5.7 is sequential path-dependent sizing (one round-trip at a time). "
        "A5.8 is a shared book with concurrent positions and portfolio limits. "
        "Different numbers do not mean one engine is more profitable."
    )
