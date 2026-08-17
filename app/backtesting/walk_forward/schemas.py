"""A5.9 walk-forward / out-of-sample schemas.

Walk-forward does not prove future profitability. Monte Carlo on OOS trades
does not create new independent historical observations.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting.monte_carlo.schemas import MonteCarloVerdict, SampleQuality
from app.backtesting.order_execution.schemas import ClosedTradeRecord


LIMITATION = (
    "Walk-forward validation selects a configuration on each training window "
    "and evaluates it only on the subsequent test window. Combined OOS results "
    "concatenate test-period trades only. Training trades are never mixed into "
    "OOS performance. Indicator warmup may use pre-test (and pre-train) candles "
    "with timestamp <= the period end; it must not use later candles. "
    "Walk-forward does not prove future profitability."
)


class CapitalMode(str, Enum):
    COMPOUNDED = "compounded"
    FIXED = "fixed"


class MetricStatus(str, Enum):
    VALID = "VALID"
    LOW_SAMPLE = "LOW_SAMPLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NO_WINNING_TRADES = "NO_WINNING_TRADES"
    NO_TRADES = "NO_TRADES"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CoverageStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LOW_COVERAGE = "LOW_COVERAGE"
    NO_OOS_TRADES = "NO_OOS_TRADES"


class DegradationLabel(str, Enum):
    DESCRIPTIVE_DIAGNOSTIC = "DESCRIPTIVE_DIAGNOSTIC"


class SelectionEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    FALLBACK_INELIGIBLE = "FALLBACK_INELIGIBLE"


class TrainSelectionDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_training_trades: int
    candidates_evaluated: int = 0
    eligible_count: int = 0
    ineligible_count: int = 0
    zero_trade_candidates: int = 0
    selected_training_trade_count: int = 0
    fallback_count: int = 0
    selected_eligibility: SelectionEligibility = SelectionEligibility.ELIGIBLE
    note: str = ""


class SelectionScope(str, Enum):
    PER_SYMBOL = "per_symbol"
    JOINT = "joint"


class WalkForwardWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window_id: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    @property
    def train_label(self) -> str:
        return f"{self.train_start.isoformat()} → {self.train_end.isoformat()}"

    @property
    def test_label(self) -> str:
        return f"{self.test_start.isoformat()} → {self.test_end.isoformat()}"


class SearchSpace(BaseModel):
    """Declared-only search. Empty tuples mean 'do not search that axis'."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ema_pair_presets: tuple[str, ...] = ("9_21", "12_26", "20_50")
    fast_emas: tuple[int, ...] = ()
    slow_emas: tuple[int, ...] = ()
    adx_thresholds: tuple[float, ...] = (20.0,)
    ema200_filters: tuple[bool, ...] = (True,)
    max_candidates: int = Field(default=24, ge=1, le=256)


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train_years: int = Field(default=5, ge=1)
    test_years: int = Field(default=1, ge=1)
    step_years: int = Field(default=1, ge=1)
    train_days: int | None = Field(default=None, ge=2)
    test_days: int | None = Field(default=None, ge=1)
    step_days: int | None = Field(default=None, ge=1)
    data_start: date | None = None
    data_end: date | None = None
    embargo_days: int = Field(default=0, ge=0)
    initial_capital: float = Field(default=100_000.0, gt=0.0)
    capital_mode: CapitalMode = CapitalMode.COMPOUNDED
    selection_scope: SelectionScope = SelectionScope.PER_SYMBOL
    search: SearchSpace = Field(default_factory=SearchSpace)
    strategy_alias: str = "ema_professional"
    min_history_bars: int = Field(default=60, ge=3)
    percent: float = Field(default=95.0, gt=0.0, le=100.0)
    slippage_bps: float = Field(default=5.0, ge=0.0)
    brokerage_rate: float = Field(default=0.0003, ge=0.0)
    allow_fractional_shares: bool = False
    min_quantity: float = Field(default=1.0, gt=0.0)
    include_monte_carlo: bool = False
    include_portfolio_risk: bool = False
    include_charts: bool = True
    simulations: int = Field(default=1_000, ge=1, le=1_000_000)
    random_seed: int = 42
    random_seed_required: bool = True
    degradation_return_caution: float = Field(default=0.5, ge=0.0)
    degradation_sharpe_caution: float = Field(default=0.5, ge=0.0)
    minimum_training_trades: int = Field(
        default=5,
        ge=0,
        description=(
            "Training candidates with fewer completed trades are INELIGIBLE for "
            "selection. Default 5 matches walk-forward LOW_SAMPLE threshold."
        ),
    )


class CandidateMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    config_key: str
    parameters: dict[str, str | int | float | bool]
    score: float
    return_pct: float
    sharpe: float
    sortino: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    trade_count: int
    total_costs: float
    net_profit: float
    gross_profit: float


class ExecutionAttribution(BaseModel):
    """Separate no-signal periods from execution rejections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signals_generated: int = 0
    hold_bars: int = 0
    orders_attempted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    no_order_for_signal: int = 0
    completed_trades: int = 0
    rejected_insufficient_cash: int = 0
    rejected_below_min_quantity: int = 0
    rejected_no_open_position: int = 0
    rejected_already_holding: int = 0
    rejected_invalid_recommendation: int = 0
    rejected_validation_failure: int = 0
    rejected_other: int = 0
    rejected_by_reason: dict[str, int] = Field(default_factory=dict)


class WindowResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window: WalkForwardWindow
    symbol: str
    selected: CandidateMetrics
    candidates_evaluated: int
    train: CandidateMetrics
    oos: CandidateMetrics
    frozen_parameters: dict[str, str | int | float | bool]
    oos_trade_count: int
    starting_capital: float
    ending_capital: float
    selection_used_max_data_date: date
    oos_used_max_data_date: date
    rejected_count: int = 0
    attribution: ExecutionAttribution = Field(default_factory=ExecutionAttribution)
    requested_strategy: str = ""
    execution_engine: str = "ema_trend"
    train_selection: TrainSelectionDiagnostic | None = None


class SampleAwarePerformance(BaseModel):
    """Combined OOS metrics with explicit sample validity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_count: int = 0
    return_pct: float = 0.0
    return_raw: float = 0.0
    return_status: MetricStatus = MetricStatus.NO_TRADES
    sharpe: float | None = None
    sharpe_raw: float | None = None
    sharpe_status: MetricStatus = MetricStatus.INSUFFICIENT_SAMPLE
    sortino: float | None = None
    sortino_raw: float | None = None
    sortino_status: MetricStatus = MetricStatus.INSUFFICIENT_SAMPLE
    max_drawdown: float = 0.0
    max_drawdown_raw: float = 0.0
    max_drawdown_status: MetricStatus = MetricStatus.VALID
    win_rate: float | None = None
    win_rate_raw: float | None = None
    win_rate_status: MetricStatus = MetricStatus.NO_TRADES
    profit_factor: float | None = None
    profit_factor_raw: float | None = None
    profit_factor_status: MetricStatus = MetricStatus.NO_TRADES
    gross_profit: float = 0.0
    net_profit: float = 0.0
    total_costs: float = 0.0
    final_equity: float = 0.0


class StrategyIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_strategy: str
    execution_engine: str = "ema_trend"


class DegradationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: DegradationLabel = DegradationLabel.DESCRIPTIVE_DIAGNOSTIC
    train_return: float
    oos_return: float
    return_ratio: float | None = None
    return_degradation_pct: float | None = None
    train_sharpe: float
    oos_sharpe: float | None = None
    oos_sharpe_raw: float | None = None
    oos_sharpe_status: MetricStatus = MetricStatus.INSUFFICIENT_SAMPLE
    sharpe_ratio: float | None = None
    sharpe_degradation_pct: float | None = None
    train_win_rate: float
    oos_win_rate: float | None = None
    oos_win_rate_raw: float | None = None
    oos_win_rate_status: MetricStatus = MetricStatus.NO_TRADES
    win_rate_ratio: float | None = None
    win_rate_degradation_pct: float | None = None
    train_profit_factor: float
    oos_profit_factor: float | None = None
    oos_profit_factor_raw: float | None = None
    oos_profit_factor_status: MetricStatus = MetricStatus.NO_TRADES
    profit_factor_ratio: float | None = None
    profit_factor_degradation_pct: float | None = None
    oos_trade_count: int = 0
    sample_flag: str = ""
    compares: str = "mean_window_train_vs_mean_window_oos_returns"
    note: str = (
        "Degradation is a DESCRIPTIVE DIAGNOSTIC. It is not statistical proof and "
        "not an automatic fail. Ratios are OOS / Train. Degradation % is (Train − OOS) / |Train|."
    )


class ParameterStability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    history: list[str] = Field(default_factory=list)
    frequency: dict[str, int] = Field(default_factory=dict)
    changes: int = 0
    most_frequent: str = ""
    stability_score: float = 0.0
    unique_config_count: int = 0
    window_count: int = 0
    oos_trade_count: int = 0
    coverage_status: CoverageStatus = CoverageStatus.NO_OOS_TRADES
    interpretation: str = ""
    note: str = (
        "Stability score is 1 − changes/(windows−1). It is descriptive only and "
        "does not imply OOS robustness when trade coverage is absent."
    )


class EquityPoint(BaseModel):
    """One canonical equity observation after a market/backtest event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    equity: float


class LeakageReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool = True
    train_before_test: bool = True
    no_overlap: bool = True
    no_duplicate_boundary: bool = True
    warmup_capped_at_period_end: bool = True
    train_selection_ignores_test: bool = True
    details: list[str] = Field(default_factory=list)


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_kind: str = "WalkForwardEngine"
    limitation: str = LIMITATION
    config: WalkForwardConfig
    symbols: list[str]
    windows: list[WindowResult]
    window_count: int
    oos_trade_count: int
    historical_oos_trades: int = 0
    accounting_model: str = "trade_ledger_net_profit"
    accounting_note: str = ""
    combined_oos_return: float = 0.0
    mean_window_oos_return: float = 0.0
    combined_train_return: float | None = None
    mean_window_train_return: float = 0.0
    oos_return: float
    oos_cagr: float | None = None
    oos_sharpe: float | None = None
    oos_sharpe_raw: float | None = None
    oos_sharpe_status: MetricStatus = MetricStatus.INSUFFICIENT_SAMPLE
    oos_sharpe_methodology: str = "canonical_equity_step_returns"
    oos_sortino: float | None = None
    oos_sortino_raw: float | None = None
    oos_sortino_status: MetricStatus = MetricStatus.INSUFFICIENT_SAMPLE
    oos_sortino_methodology: str = "canonical_equity_step_returns"
    oos_max_drawdown: float = 0.0
    oos_win_rate: float | None = None
    oos_win_rate_raw: float | None = None
    oos_win_rate_status: MetricStatus = MetricStatus.NO_TRADES
    oos_profit_factor: float | None = None
    oos_profit_factor_raw: float | None = None
    oos_profit_factor_status: MetricStatus = MetricStatus.NO_TRADES
    oos_gross_profit: float = 0.0
    oos_net_profit: float = 0.0
    oos_total_costs: float = 0.0
    oos_cost_pct_of_gross: float | None = None
    oos_performance: SampleAwarePerformance | None = None
    initial_capital: float
    final_oos_equity: float
    capital_mode: CapitalMode
    strategy_identity: StrategyIdentity | None = None
    degradation: DegradationReport
    parameter_stability: ParameterStability
    leakage: LeakageReport
    sample_quality: SampleQuality = SampleQuality.INVALID
    verdict: MonteCarloVerdict = MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    monte_carlo_label: str = "OUT-OF-SAMPLE MONTE CARLO"
    monte_carlo_probability_of_loss: float | None = None
    monte_carlo_median_return: float | None = None
    monte_carlo_simulations: int = 0
    simulation_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    oos_by_year: dict[str, float] = Field(default_factory=dict)
    oos_by_symbol: dict[str, float] = Field(default_factory=dict)
    oos_trades: list[ClosedTradeRecord] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    oos_rejected_count: int = 0
    oos_attribution: ExecutionAttribution = Field(default_factory=ExecutionAttribution)
    oos_attribution_by_symbol: dict[str, ExecutionAttribution] = Field(default_factory=dict)
    generated_at: datetime | None = None
