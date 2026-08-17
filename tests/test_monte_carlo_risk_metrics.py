"""A6 Monte Carlo risk-engine completion: VaR / CVaR (Expected Shortfall).

Focused tests for the newly added tail-risk metrics. Existing Monte Carlo
behaviour (percentiles, probability of ruin, losing streaks, drawdown
distribution, deterministic seeds, sample quality) is covered elsewhere.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from app.backtesting.monte_carlo import (
    MonteCarloConfig,
    MonteCarloEngine,
    RiskMetrics,
    SamplingMethod,
    compute_risk_metrics,
    format_markdown_report,
)
from app.backtesting.monte_carlo.schemas import CapitalMode, EngineMode
from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExitReason

TS0 = datetime(2022, 6, 1, tzinfo=timezone.utc)
TS1 = datetime(2022, 6, 10, tzinfo=timezone.utc)


def _trade(pnl: float, *, qty: float = 10.0, entry: float = 100.0) -> ClosedTradeRecord:
    exit_px = entry + pnl / qty if qty else entry
    return ClosedTradeRecord(
        symbol="RELIANCE",
        entry_timestamp=TS0,
        exit_timestamp=TS1,
        entry_price=entry,
        exit_price=exit_px,
        quantity=qty,
        gross_profit=pnl,
        brokerage=0.0,
        slippage=0.0,
        net_profit=pnl,
        holding_days=9,
        exit_reason=ExitReason.SELL_RECOMMENDATION,
        strategy_name="ema_trend",
    )


def test_compute_risk_metrics_matches_manual_definition() -> None:
    returns = [-0.10, -0.05, 0.0, 0.05, 0.10]
    rm = compute_risk_metrics(returns, initial_capital=100_000.0)
    # VaR95 = -percentile(returns, 5) via linear interpolation.
    q95 = float(np.percentile(returns, 5, method="linear"))
    q99 = float(np.percentile(returns, 1, method="linear"))
    assert rm.var_return_95 == pytest.approx(-q95)
    assert rm.var_return_99 == pytest.approx(-q99)
    # CVaR = -mean(tail at or below the quantile).
    tail95 = [r for r in returns if r <= q95]
    assert rm.cvar_return_95 == pytest.approx(-np.mean(tail95))
    # Capital figures scale by initial capital.
    assert rm.var_capital_95 == pytest.approx(rm.var_return_95 * 100_000.0)
    assert rm.cvar_capital_99 == pytest.approx(rm.cvar_return_99 * 100_000.0)


def test_cvar_at_least_var() -> None:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.01, 0.05, size=5000)
    rm = compute_risk_metrics(returns, initial_capital=1_000_000.0)
    # Expected shortfall is never a smaller loss than VaR.
    assert rm.cvar_return_95 >= rm.var_return_95 - 1e-12
    assert rm.cvar_return_99 >= rm.var_return_99 - 1e-12


def test_empty_returns_are_zero_not_error() -> None:
    rm = compute_risk_metrics([], initial_capital=500_000.0)
    assert isinstance(rm, RiskMetrics)
    assert rm.var_return_95 == 0.0
    assert rm.cvar_capital_99 == 0.0


def test_engine_populates_risk_metrics() -> None:
    trades = [_trade(200), _trade(-80), _trade(150), _trade(-60), _trade(90)]
    cfg = MonteCarloConfig(simulations=500, initial_capital=100_000, random_seed=11)
    result = MonteCarloEngine(cfg).run(trades)
    assert result.risk_metrics is not None
    # Non-trivial tail from a mixed win/loss distribution.
    assert result.risk_metrics.cvar_return_95 >= result.risk_metrics.var_return_95 - 1e-9


def test_risk_metrics_deterministic_with_seed() -> None:
    trades = [_trade(120), _trade(-70), _trade(50), _trade(-40)]
    cfg = MonteCarloConfig(simulations=400, initial_capital=100_000, random_seed=99)
    a = MonteCarloEngine(cfg).run(trades).risk_metrics
    b = MonteCarloEngine(cfg).run(trades).risk_metrics
    assert a is not None and b is not None
    assert a.var_return_95 == b.var_return_95
    assert a.cvar_return_99 == b.cvar_return_99
    assert a.var_capital_95 == b.var_capital_95


def test_simulation_count_not_treated_as_historical_observations() -> None:
    trades = [_trade(100), _trade(-50), _trade(60)]
    small = MonteCarloConfig(simulations=200, initial_capital=100_000, random_seed=3)
    large = MonteCarloConfig(simulations=20_000, initial_capital=100_000, random_seed=3)
    r_small = MonteCarloEngine(small).run(trades)
    r_large = MonteCarloEngine(large).run(trades)
    # More simulations must NOT inflate the historical sample size or quality.
    assert r_small.source_trade_count == 3
    assert r_large.source_trade_count == 3
    assert r_small.sample_quality == r_large.sample_quality


def test_risk_metrics_reflect_only_supplied_trades() -> None:
    losers_only = [_trade(-100), _trade(-120), _trade(-80), _trade(-60)]
    winners_only = [_trade(100), _trade(120), _trade(80), _trade(60)]
    cfg = MonteCarloConfig(simulations=1000, initial_capital=100_000, random_seed=5)
    loss_rm = MonteCarloEngine(cfg).run(losers_only).risk_metrics
    win_rm = MonteCarloEngine(cfg).run(winners_only).risk_metrics
    assert loss_rm is not None and win_rm is not None
    # An all-loss OOS book has strictly worse tail risk than an all-win book.
    assert loss_rm.var_return_95 > win_rm.var_return_95


def test_report_includes_var_cvar_section() -> None:
    trades = [_trade(100), _trade(-50), _trade(70), _trade(-30)]
    cfg = MonteCarloConfig(simulations=300, initial_capital=100_000, random_seed=1)
    result = MonteCarloEngine(cfg).run(trades)
    report = format_markdown_report(result)
    assert "TAIL RISK (VaR / CVaR)" in report
    assert "CVaR/ES 95%" in report


def test_path_dependent_engine_has_risk_metrics() -> None:
    trades = [_trade(150), _trade(-90), _trade(70), _trade(-40), _trade(110)]
    cfg = MonteCarloConfig(
        simulations=300,
        initial_capital=100_000,
        random_seed=13,
        engine_mode=EngineMode.PATH_DEPENDENT,
        capital_mode=CapitalMode.PATH_DEPENDENT_EQUITY,
    )
    result = MonteCarloEngine(cfg).run(trades)
    assert result.risk_metrics is not None
    assert result.risk_metrics.cvar_return_99 >= result.risk_metrics.var_return_99 - 1e-9
