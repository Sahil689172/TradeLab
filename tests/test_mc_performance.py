"""Monte Carlo performance regression + correctness tests.

Tests cover:
  - _max_run vectorised correctness vs reference implementation
  - _max_run handles edge cases: all-True, all-False, single trade, empty
  - simulate_equity_batch produces identical results before/after refactor
  - Full engine.run() completes in a reasonable time for 10 / 100 / 1000 sims
  - Progress logging fires via _simulate_batch chunked path
  - Zero trades, one trade, NaN/Inf guard, invalid sim count
  - Horizon bootstrap cap is respected (<=200 sims per call)
"""
from __future__ import annotations

import time
from unittest.mock import patch

import numpy as np
import pytest

from app.backtesting.monte_carlo.engine import TradeResamplingMonteCarlo
from app.backtesting.monte_carlo.pipeline import make_synthetic_trades
from app.backtesting.monte_carlo.schemas import (
    CapitalMode,
    MonteCarloConfig,
    MonteCarloTrade,
    MonteCarloVerdict,
)
from app.backtesting.monte_carlo.simulation import (
    _max_run,
    simulate_equity_batch,
    simulate_equity,
)
from app.backtesting.monte_carlo.validation import validate_config, validate_trades


# ── reference _max_run (original Python loop) ─────────────────────────────

def _max_run_reference(mask: np.ndarray) -> np.ndarray:
    """Original Python-loop implementation kept here for correctness check."""
    n_sims, n_steps = mask.shape
    runs = np.zeros(n_sims, dtype=np.int32)
    best = np.zeros(n_sims, dtype=np.int32)
    for t in range(n_steps):
        runs = np.where(mask[:, t], runs + 1, 0)
        best = np.maximum(best, runs)
    return best


# ── _max_run correctness ────────────────────────────────────────────────────

def test_max_run_all_true():
    mask = np.ones((4, 6), dtype=bool)
    assert list(_max_run(mask)) == [6, 6, 6, 6]
    assert list(_max_run_reference(mask)) == [6, 6, 6, 6]


def test_max_run_all_false():
    mask = np.zeros((4, 6), dtype=bool)
    assert list(_max_run(mask)) == [0, 0, 0, 0]


def test_max_run_alternating():
    # T F T F T F → longest run = 1
    row = [True, False, True, False, True, False]
    mask = np.array([row], dtype=bool)
    assert _max_run(mask)[0] == 1
    assert _max_run_reference(mask)[0] == 1


def test_max_run_single_run_at_end():
    row = [False, False, True, True, True]
    mask = np.array([row], dtype=bool)
    assert _max_run(mask)[0] == 3
    assert _max_run_reference(mask)[0] == 3


def test_max_run_single_run_at_start():
    row = [True, True, False, False, False]
    mask = np.array([row], dtype=bool)
    assert _max_run(mask)[0] == 2
    assert _max_run_reference(mask)[0] == 2


def test_max_run_multiple_rows():
    mask = np.array([
        [True, True, False, True],      # best = 2
        [False, False, False, False],    # best = 0
        [True, True, True, True],        # best = 4
        [False, True, False, True],      # best = 1
    ], dtype=bool)
    result = _max_run(mask)
    reference = _max_run_reference(mask)
    np.testing.assert_array_equal(result, reference)
    np.testing.assert_array_equal(result, [2, 0, 4, 1])


def test_max_run_single_step():
    mask = np.array([[True], [False], [True]], dtype=bool)
    result = _max_run(mask)
    reference = _max_run_reference(mask)
    np.testing.assert_array_equal(result, reference)
    np.testing.assert_array_equal(result, [1, 0, 1])


def test_max_run_empty_steps():
    mask = np.zeros((5, 0), dtype=bool)
    result = _max_run(mask)
    assert result.shape == (5,)
    assert list(result) == [0, 0, 0, 0, 0]


@pytest.mark.parametrize("n_sims,n_steps", [
    (1, 1), (10, 20), (100, 50), (1_000, 100), (5_000, 200),
])
def test_max_run_matches_reference(n_sims: int, n_steps: int):
    """New implementation must match original for random masks of every size."""
    rng = np.random.default_rng(42)
    mask = rng.random((n_sims, n_steps)) > 0.5
    result = _max_run(mask)
    reference = _max_run_reference(mask)
    np.testing.assert_array_equal(result, reference,
        err_msg=f"Mismatch at n_sims={n_sims}, n_steps={n_steps}")


# ── simulate_equity_batch correctness (streak fields) ─────────────────────

def test_equity_batch_streak_correctness():
    """Batch streak result must match single-path reference for known trades."""
    # 5 winning then 3 losing then 2 winning
    pnls = [10.0, 10.0, 10.0, 10.0, 10.0, -5.0, -5.0, -5.0, 8.0, 8.0]
    paths = np.array([pnls, pnls], dtype=float)
    batch = simulate_equity_batch(paths, initial_capital=1_000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    # Both rows are identical so both should produce the same streaks.
    assert int(batch["lose_streak"][0]) == 3
    assert int(batch["win_streak"][0]) == 5
    assert int(batch["lose_streak"][1]) == 3
    assert int(batch["win_streak"][1]) == 5


def test_equity_batch_single_trade():
    paths = np.array([[100.0], [-50.0]], dtype=float)
    batch = simulate_equity_batch(paths, initial_capital=1_000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    assert batch["final"][0] == pytest.approx(1_100.0)
    assert batch["final"][1] == pytest.approx(950.0)
    assert int(batch["lose_streak"][0]) == 0
    assert int(batch["lose_streak"][1]) == 1
    assert int(batch["win_streak"][0]) == 1
    assert int(batch["win_streak"][1]) == 0


# ── simulate_equity single-path ────────────────────────────────────────────

def test_simulate_equity_zero_pnl():
    result = simulate_equity([0.0] * 10, initial_capital=1_000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    assert result.final_equity == pytest.approx(1_000.0)
    assert result.max_drawdown == pytest.approx(0.0)
    assert result.longest_losing_streak == 0


def test_simulate_equity_all_wins():
    result = simulate_equity([50.0] * 10, initial_capital=1_000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    assert result.final_equity == pytest.approx(1_500.0)
    assert result.longest_losing_streak == 0
    assert result.longest_winning_streak == 10


def test_simulate_equity_all_losses():
    result = simulate_equity([-10.0] * 5, initial_capital=1_000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    assert result.final_equity == pytest.approx(950.0)
    assert result.longest_winning_streak == 0
    assert result.longest_losing_streak == 5


# ── validate_config / validate_trades ──────────────────────────────────────

def test_validate_config_rejects_zero_sims():
    from app.backtesting.monte_carlo.exceptions import MonteCarloConfigError
    with pytest.raises(MonteCarloConfigError):
        validate_config(MonteCarloConfig(simulations=0))


def test_validate_config_rejects_negative_capital():
    with pytest.raises(Exception):
        MonteCarloConfig(initial_capital=-1.0)


def test_validate_trades_rejects_nan_pnl():
    from app.backtesting.monte_carlo.exceptions import MonteCarloDataError
    bad = MonteCarloTrade(pnl=float("nan"), return_pct=0.0)
    with pytest.raises((MonteCarloDataError, ValueError)):
        validate_trades([bad], capital_mode=CapitalMode.ADDITIVE_PNL)


def test_validate_trades_rejects_inf_return():
    bad = MonteCarloTrade(pnl=100.0, return_pct=float("inf"))
    with pytest.raises((Exception,)):
        validate_trades([bad], capital_mode=CapitalMode.ADDITIVE_PNL)


# ── MC schema limits ────────────────────────────────────────────────────────

def test_mc_config_min_sims():
    cfg = MonteCarloConfig(simulations=1)
    assert cfg.simulations == 1


def test_mc_config_max_sims():
    cfg = MonteCarloConfig(simulations=1_000_000)
    assert cfg.simulations == 1_000_000


def test_mc_config_invalid_high():
    with pytest.raises(Exception):
        MonteCarloConfig(simulations=1_000_001)


def test_mc_dashboard_request_default():
    from app.services.dashboard.schemas import MonteCarloDashboardRequest
    req = MonteCarloDashboardRequest(strategy="ema_trend")
    assert req.simulations == 1_000
    assert req.simulations >= 1
    assert req.simulations <= 100_000


def test_mc_dashboard_request_invalid_low():
    from app.services.dashboard.schemas import MonteCarloDashboardRequest
    with pytest.raises(Exception):
        MonteCarloDashboardRequest(strategy="ema_trend", simulations=0)


def test_mc_dashboard_request_invalid_high():
    from app.services.dashboard.schemas import MonteCarloDashboardRequest
    with pytest.raises(Exception):
        MonteCarloDashboardRequest(strategy="ema_trend", simulations=200_000)


# ── zero / one trade edge cases ────────────────────────────────────────────

def test_mc_zero_trades_returns_unavailable():
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=10))
    result = mc._run_trades([], strategy="test", symbol="TEST", period="")
    assert result.verdict == MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    assert result.source_trade_count == 0


def test_mc_one_trade():
    trades = [MonteCarloTrade(pnl=100.0, return_pct=0.1)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=50, random_seed=1))
    result = mc._run_trades(trades, strategy="test", symbol="TEST", period="")
    # With one trade all sims are identical — P(loss)=0 if pnl>0.
    assert result.probability_of_loss == pytest.approx(0.0)
    assert result.probability_of_profit == pytest.approx(1.0)


def test_mc_all_winning_trades():
    trades = [MonteCarloTrade(pnl=50.0, return_pct=0.05) for _ in range(20)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=100, random_seed=1))
    result = mc._run_trades(trades, strategy="test", symbol="TEST", period="")
    assert result.probability_of_loss == pytest.approx(0.0)
    assert result.probability_of_profit == pytest.approx(1.0)


def test_mc_all_losing_trades():
    trades = [MonteCarloTrade(pnl=-50.0, return_pct=-0.05) for _ in range(20)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=100, random_seed=1))
    result = mc._run_trades(trades, strategy="test", symbol="TEST", period="")
    assert result.probability_of_loss == pytest.approx(1.0)
    assert result.probability_of_profit == pytest.approx(0.0)


# ── performance / timing benchmarks ────────────────────────────────────────
# These are "speed smoke tests": they assert the run finishes in a reasonable
# wall-clock time on commodity hardware.  They do NOT assert microsecond
# precision — they catch regressions where something becomes 100× slower.

@pytest.mark.parametrize("n_sims,max_seconds", [
    (10,    0.5),
    (100,   0.5),
    (1_000, 2.0),
])
def test_mc_timing(n_sims: int, max_seconds: float):
    """Full engine._run_trades must complete within max_seconds."""
    trades = make_synthetic_trades(50, seed=1)
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=n_sims, random_seed=42))
    t0 = time.perf_counter()
    result = mc._run_trades(list(trades), strategy="bench", symbol="TEST", period="")
    elapsed = time.perf_counter() - t0
    rate = n_sims / elapsed if elapsed > 0 else float("inf")
    print(f"\n  n_sims={n_sims}  elapsed={elapsed*1000:.1f}ms  rate={rate:,.0f} sims/s")
    assert elapsed < max_seconds, (
        f"n_sims={n_sims} took {elapsed:.2f}s > {max_seconds}s limit. "
        f"Possible performance regression in _max_run or simulate_equity_batch."
    )
    # Basic sanity on result.
    assert 0.0 <= result.probability_of_loss <= 1.0
    assert result.source_trade_count == 50


@pytest.mark.parametrize("n_sims", [10, 100, 1_000])
def test_mc_timing_small_trade_count(n_sims: int):
    """Also bench with a very small trade count (5 trades) — worst case for _max_run."""
    trades = make_synthetic_trades(5, seed=2)
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=n_sims, random_seed=7))
    t0 = time.perf_counter()
    result = mc._run_trades(list(trades), strategy="bench", symbol="TEST", period="")
    elapsed = time.perf_counter() - t0
    print(f"\n  n_sims={n_sims}  n_trades=5  elapsed={elapsed*1000:.1f}ms")
    assert elapsed < 2.0
    assert result.source_trade_count == 5


def test_mc_1000_sims_sims_per_second():
    """1000 sims on 50 trades should run at >= 500 sims/sec on any modern machine."""
    trades = make_synthetic_trades(50, seed=1)
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=1_000, random_seed=42))
    t0 = time.perf_counter()
    mc._run_trades(list(trades), strategy="bench", symbol="TEST", period="")
    elapsed = time.perf_counter() - t0
    rate = 1_000 / elapsed if elapsed > 0 else float("inf")
    print(f"\n  rate={rate:,.0f} sims/s  elapsed={elapsed*1000:.1f}ms")
    assert rate >= 500, f"Only {rate:.0f} sims/s — expected >= 500. Possible regression."


# ── progress logging fires ─────────────────────────────────────────────────

def test_simulate_batch_logs_progress(caplog):
    """_simulate_batch should emit at least one INFO log during large runs."""
    import logging
    trades = make_synthetic_trades(20, seed=3)
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=200, random_seed=1))
    with caplog.at_level(logging.INFO, logger="app.backtesting.monte_carlo.engine"):
        mc._simulate_batch(list(trades), CapitalMode.ADDITIVE_PNL)
    mc_logs = [r for r in caplog.records if "Monte Carlo" in r.getMessage()]
    assert mc_logs, "Expected at least one Monte Carlo progress log entry"


# ── horizon bootstrap cap ──────────────────────────────────────────────────

def test_horizon_bootstrap_cap_is_200():
    """_HORIZON_BOOTSTRAP_CAP must be <= 200 to avoid unnecessary extra sims."""
    from app.services.dashboard.monte_carlo_service import _HORIZON_BOOTSTRAP_CAP
    assert _HORIZON_BOOTSTRAP_CAP <= 200, (
        f"_HORIZON_BOOTSTRAP_CAP={_HORIZON_BOOTSTRAP_CAP} is too high. "
        "Horizon bands need only ~200 samples for stable percentiles."
    )


def test_compute_horizon_bands_respects_cap():
    """compute_horizon_bands called with n=200 must run in < 0.5s."""
    from app.services.dashboard.horizon_outlook import compute_horizon_bands
    daily_returns = np.random.default_rng(99).normal(0.001, 0.015, 500)
    t0 = time.perf_counter()
    bands = compute_horizon_bands(
        daily_returns,
        current_price=2500.0,
        horizons=[1, 2, 5],
        simulations=200,
        random_seed=42,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"compute_horizon_bands(200) took {elapsed:.2f}s — too slow"
    assert len(bands) == 3
    for b in bands:
        assert b.supported


# ── determinism preserved ──────────────────────────────────────────────────

def test_deterministic_seed_unchanged():
    """Same seed must produce identical results after refactor."""
    trades = make_synthetic_trades(30, seed=5)
    cfg = MonteCarloConfig(simulations=500, random_seed=42)
    mc = TradeResamplingMonteCarlo(cfg)
    r1 = mc._run_trades(list(trades), strategy="t", symbol="T", period="")
    r2 = mc._run_trades(list(trades), strategy="t", symbol="T", period="")
    assert r1.probability_of_loss == pytest.approx(r2.probability_of_loss)
    assert r1.return_percentiles.p50 == pytest.approx(r2.return_percentiles.p50)
    assert r1.return_percentiles.p95 == pytest.approx(r2.return_percentiles.p95)


# ── invalid symbol / strategy (service level) ─────────────────────────────

def test_service_unknown_strategy_raises():
    from app.services.dashboard.monte_carlo_service import DashboardMonteCarloService
    from app.services.dashboard.schemas import MonteCarloDashboardRequest
    svc = DashboardMonteCarloService()
    req = MonteCarloDashboardRequest(strategy="nonexistent_xyz", simulations=10)
    with pytest.raises(ValueError, match="Unknown strategy"):
        svc._load_trades("RELIANCE", req)
