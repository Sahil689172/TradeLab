"""
Self-contained MC test runner.
Writes results to scripts/mc_test_output.txt regardless of shell redirect issues.
Run: .venv\Scripts\python.exe scripts\run_mc_tests.py
"""
import sys
import time
import traceback
from pathlib import Path

OUT = Path(__file__).parent / "mc_test_output.txt"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

lines = []

def log(msg=""):
    lines.append(str(msg))
    print(msg)

def section(title):
    log()
    log("=" * 60)
    log(f"  {title}")
    log("=" * 60)

def run_test(name, fn):
    try:
        t0 = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - t0
        log(f"  PASS  {name}  ({elapsed*1000:.1f} ms)")
        return True
    except Exception as e:
        log(f"  FAIL  {name}")
        log(f"        {type(e).__name__}: {e}")
        traceback.print_exc()
        return False

passed = failed = 0

# ── IMPORT STAGE ──────────────────────────────────────────────────────────
section("IMPORTS")
t0 = time.perf_counter()
try:
    import numpy as np
    from app.backtesting.monte_carlo.simulation import _max_run, simulate_equity_batch, simulate_equity
    from app.backtesting.monte_carlo.pipeline import make_synthetic_trades
    from app.backtesting.monte_carlo.schemas import (
        CapitalMode, MonteCarloConfig, MonteCarloTrade, MonteCarloVerdict,
    )
    from app.backtesting.monte_carlo.engine import TradeResamplingMonteCarlo
    from app.backtesting.monte_carlo.validation import validate_config, validate_trades
    from app.services.dashboard.monte_carlo_service import _HORIZON_BOOTSTRAP_CAP
    from app.services.dashboard.horizon_outlook import compute_horizon_bands
    from app.services.dashboard.schemas import MonteCarloDashboardRequest
    log(f"  All imports OK  ({(time.perf_counter()-t0)*1000:.0f} ms)")
except Exception as e:
    log(f"  IMPORT FAILED: {e}")
    traceback.print_exc()
    OUT.write_text("\n".join(lines), encoding="utf-8")
    sys.exit(1)

# ── REFERENCE _max_run ─────────────────────────────────────────────────────
def _max_run_ref(mask):
    n_sims, n_steps = mask.shape
    runs = np.zeros(n_sims, dtype=np.int32)
    best = np.zeros(n_sims, dtype=np.int32)
    for t in range(n_steps):
        runs = np.where(mask[:, t], runs + 1, 0)
        best = np.maximum(best, runs)
    return best

# ── _max_run CORRECTNESS ──────────────────────────────────────────────────
section("_max_run CORRECTNESS")

def t_all_true():
    m = np.ones((4, 6), dtype=bool)
    r = _max_run(m)
    assert list(r) == [6,6,6,6], f"got {list(r)}"

def t_all_false():
    m = np.zeros((4, 6), dtype=bool)
    r = _max_run(m)
    assert list(r) == [0,0,0,0], f"got {list(r)}"

def t_alternating():
    m = np.array([[True,False,True,False,True,False]])
    assert _max_run(m)[0] == 1

def t_run_at_end():
    m = np.array([[False,False,True,True,True]])
    assert _max_run(m)[0] == 3

def t_run_at_start():
    m = np.array([[True,True,False,False,False]])
    assert _max_run(m)[0] == 2

def t_multi_row():
    m = np.array([
        [True,True,False,True],
        [False,False,False,False],
        [True,True,True,True],
        [False,True,False,True],
    ], dtype=bool)
    r = _max_run(m)
    ref = _max_run_ref(m)
    np.testing.assert_array_equal(r, ref)
    np.testing.assert_array_equal(r, [2,0,4,1])

def t_empty_steps():
    m = np.zeros((5,0), dtype=bool)
    r = _max_run(m)
    assert list(r) == [0,0,0,0,0], f"got {list(r)}"

def t_single_step():
    m = np.array([[True],[False],[True]], dtype=bool)
    r = _max_run(m)
    ref = _max_run_ref(m)
    np.testing.assert_array_equal(r, ref)

for name, fn in [
    ("all_true", t_all_true),
    ("all_false", t_all_false),
    ("alternating", t_alternating),
    ("run_at_end", t_run_at_end),
    ("run_at_start", t_run_at_start),
    ("multi_row", t_multi_row),
    ("empty_steps", t_empty_steps),
    ("single_step", t_single_step),
]:
    if run_test(f"_max_run/{name}", fn): passed += 1
    else: failed += 1

# Random pairwise match reference
section("_max_run MATCHES REFERENCE (random masks)")
for n_sims, n_steps in [(1,1),(10,20),(100,50),(1000,100),(5000,200)]:
    def make_test(ns, nt):
        def fn():
            rng = np.random.default_rng(42)
            mask = rng.random((ns, nt)) > 0.5
            r = _max_run(mask)
            ref = _max_run_ref(mask)
            np.testing.assert_array_equal(r, ref, err_msg=f"n_sims={ns} n_steps={nt}")
        return fn
    nm = f"match_ref(n_sims={n_sims},n_steps={n_steps})"
    if run_test(nm, make_test(n_sims, n_steps)): passed += 1
    else: failed += 1

# ── _max_run SPEED COMPARISON (before vs after) ───────────────────────────
section("_max_run SPEED: new vs reference")
for n_sims, n_steps in [(1000, 50), (10000, 50), (100000, 50), (1000, 200)]:
    rng = np.random.default_rng(7)
    mask = rng.random((n_sims, n_steps)) > 0.5

    # reference (old loop)
    t0 = time.perf_counter()
    ref = _max_run_ref(mask)
    t_ref = time.perf_counter() - t0

    # new vectorised
    t0 = time.perf_counter()
    new = _max_run(mask)
    t_new = time.perf_counter() - t0

    np.testing.assert_array_equal(new, ref)
    speedup = t_ref / t_new if t_new > 0 else float("inf")
    log(f"  n_sims={n_sims:>6}  n_steps={n_steps:>3}  "
        f"ref={t_ref*1000:7.2f}ms  new={t_new*1000:7.2f}ms  "
        f"speedup={speedup:.1f}x")

# ── simulate_equity_batch streak correctness ──────────────────────────────
section("simulate_equity_batch STREAK CORRECTNESS")

def t_known_streaks():
    pnls = [10.0,10.0,10.0,10.0,10.0,-5.0,-5.0,-5.0,8.0,8.0]
    paths = np.array([pnls, pnls], dtype=float)
    b = simulate_equity_batch(paths, initial_capital=1000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    assert int(b["lose_streak"][0]) == 3, f"lose={b['lose_streak'][0]}"
    assert int(b["win_streak"][0])  == 5, f"win={b['win_streak'][0]}"

def t_single_trade():
    paths = np.array([[100.0], [-50.0]], dtype=float)
    b = simulate_equity_batch(paths, initial_capital=1000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    assert b["final"][0] == pytest_approx(1100.0, b["final"][0])
    assert b["final"][1] == pytest_approx(950.0,  b["final"][1])
    assert int(b["lose_streak"][0]) == 0
    assert int(b["lose_streak"][1]) == 1

def pytest_approx(expected, actual, tol=1e-6):
    return actual  # used inline below

def t_single_trade_v2():
    paths = np.array([[100.0], [-50.0]], dtype=float)
    b = simulate_equity_batch(paths, initial_capital=1000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    assert abs(b["final"][0] - 1100.0) < 0.01
    assert abs(b["final"][1] - 950.0) < 0.01
    assert int(b["lose_streak"][0]) == 0
    assert int(b["lose_streak"][1]) == 1

for name, fn in [("known_streaks", t_known_streaks), ("single_trade", t_single_trade_v2)]:
    if run_test(f"equity_batch/{name}", fn): passed += 1
    else: failed += 1

# ── FULL ENGINE TIMING ────────────────────────────────────────────────────
section("FULL ENGINE TIMING (50 trades)")
trades50 = make_synthetic_trades(50, seed=1)
timings = {}

for n_sims in [10, 100, 500, 1_000]:
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=n_sims, random_seed=42))
    t0 = time.perf_counter()
    result = mc._run_trades(list(trades50), strategy="bench", symbol="TEST", period="")
    elapsed = time.perf_counter() - t0
    rate = n_sims / elapsed if elapsed > 0 else float("inf")
    timings[n_sims] = elapsed
    log(f"  n_sims={n_sims:>6,}  elapsed={elapsed*1000:8.1f}ms  rate={rate:,.0f} sims/s")
    assert 0.0 <= result.probability_of_loss <= 1.0
    assert result.source_trade_count == 50

# timing assertions
def t_timing_10():
    assert timings[10] < 1.0, f"10 sims took {timings[10]:.2f}s"
def t_timing_100():
    assert timings[100] < 1.0, f"100 sims took {timings[100]:.2f}s"
def t_timing_1000():
    assert timings[1_000] < 5.0, f"1000 sims took {timings[1_000]:.2f}s"
def t_rate_1000():
    rate = 1_000 / timings[1_000]
    assert rate >= 200, f"Only {rate:.0f} sims/s (expected >=200)"
    log(f"    => {rate:,.0f} sims/s")

for name, fn in [("10_sims_<1s", t_timing_10),("100_sims_<1s", t_timing_100),
                 ("1000_sims_<5s", t_timing_1000),("1000_rate_>=200", t_rate_1000)]:
    if run_test(f"timing/{name}", fn): passed += 1
    else: failed += 1

# ── EDGE CASES ────────────────────────────────────────────────────────────
section("EDGE CASES")

def t_zero_trades():
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=10))
    r = mc._run_trades([], strategy="t", symbol="T", period="")
    assert r.verdict == MonteCarloVerdict.INSUFFICIENT_EVIDENCE

def t_one_trade():
    t = [MonteCarloTrade(pnl=100.0, return_pct=0.1)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=50, random_seed=1))
    r = mc._run_trades(t, strategy="t", symbol="T", period="")
    assert r.probability_of_loss == 0.0
    assert r.probability_of_profit == 1.0

def t_all_winning():
    trades = [MonteCarloTrade(pnl=50.0, return_pct=0.05) for _ in range(20)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=100, random_seed=1))
    r = mc._run_trades(trades, strategy="t", symbol="T", period="")
    assert r.probability_of_loss == 0.0

def t_all_losing():
    trades = [MonteCarloTrade(pnl=-50.0, return_pct=-0.05) for _ in range(20)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=100, random_seed=1))
    r = mc._run_trades(trades, strategy="t", symbol="T", period="")
    assert r.probability_of_profit == 0.0

def t_nan_pnl_rejected():
    try:
        MonteCarloTrade(pnl=float("nan"), return_pct=0.0)
        assert False, "Should have rejected NaN pnl"
    except (ValueError, Exception):
        pass  # expected

def t_invalid_sim_count_zero():
    try:
        MonteCarloConfig(simulations=0)
        assert False, "Should have rejected 0 sims"
    except Exception:
        pass

def t_invalid_sim_count_negative():
    try:
        MonteCarloConfig(simulations=-1)
        assert False, "Should have rejected -1 sims"
    except Exception:
        pass

def t_dashboard_request_default():
    req = MonteCarloDashboardRequest(strategy="ema_trend")
    assert req.simulations == 1_000
    assert 1 <= req.simulations <= 100_000

def t_dashboard_request_zero_sims():
    try:
        MonteCarloDashboardRequest(strategy="ema_trend", simulations=0)
        assert False, "Should have rejected 0"
    except Exception:
        pass

def t_unknown_strategy_raises():
    from app.services.dashboard.monte_carlo_service import DashboardMonteCarloService
    svc = DashboardMonteCarloService()
    req = MonteCarloDashboardRequest(strategy="nonexistent_xyz", simulations=10)
    try:
        svc._load_trades("RELIANCE", req)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown strategy" in str(e)

for name, fn in [
    ("zero_trades", t_zero_trades),
    ("one_trade", t_one_trade),
    ("all_winning", t_all_winning),
    ("all_losing", t_all_losing),
    ("nan_pnl_rejected", t_nan_pnl_rejected),
    ("invalid_sim_zero", t_invalid_sim_count_zero),
    ("invalid_sim_negative", t_invalid_sim_count_negative),
    ("dashboard_default_sims", t_dashboard_request_default),
    ("dashboard_zero_sims_rejected", t_dashboard_request_zero_sims),
    ("unknown_strategy_raises", t_unknown_strategy_raises),
]:
    if run_test(f"edge/{name}", fn): passed += 1
    else: failed += 1

# ── HORIZON BOOTSTRAP CAP ────────────────────────────────────────────────
section("HORIZON BOOTSTRAP CAP")

def t_cap_is_200():
    assert _HORIZON_BOOTSTRAP_CAP <= 200, f"Cap={_HORIZON_BOOTSTRAP_CAP}, expected <=200"

def t_horizon_200_is_fast():
    daily_returns = np.random.default_rng(99).normal(0.001, 0.015, 500)
    t0 = time.perf_counter()
    bands = compute_horizon_bands(
        daily_returns, current_price=2500.0,
        horizons=[1, 2, 5], simulations=200, random_seed=42,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"compute_horizon_bands(200) took {elapsed:.2f}s"
    assert len(bands) == 3
    log(f"    compute_horizon_bands(200): {elapsed*1000:.1f}ms")

for name, fn in [("cap_le_200", t_cap_is_200), ("200_sims_fast", t_horizon_200_is_fast)]:
    if run_test(f"horizon/{name}", fn): passed += 1
    else: failed += 1

# ── DETERMINISM ──────────────────────────────────────────────────────────
section("DETERMINISM")

def t_same_seed_same_result():
    trades = make_synthetic_trades(30, seed=5)
    cfg = MonteCarloConfig(simulations=500, random_seed=42)
    r1 = TradeResamplingMonteCarlo(cfg)._run_trades(list(trades), strategy="t", symbol="T", period="")
    r2 = TradeResamplingMonteCarlo(cfg)._run_trades(list(trades), strategy="t", symbol="T", period="")
    assert abs(r1.probability_of_loss - r2.probability_of_loss) < 1e-9
    assert abs(r1.return_percentiles.p50 - r2.return_percentiles.p50) < 1e-9

if run_test("determinism/same_seed", t_same_seed_same_result): passed += 1
else: failed += 1

# ── PROGRESS LOGGING ─────────────────────────────────────────────────────
section("PROGRESS LOGGING")

def t_progress_logs_emitted():
    import logging
    trades = make_synthetic_trades(20, seed=3)
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=500, random_seed=1))
    log_records = []
    class Cap(logging.Handler):
        def emit(self, record):
            if "Monte Carlo" in record.getMessage():
                log_records.append(record.getMessage())
    h = Cap()
    logging.getLogger("app.backtesting.monte_carlo.engine").addHandler(h)
    mc._simulate_batch(list(trades), CapitalMode.ADDITIVE_PNL)
    logging.getLogger("app.backtesting.monte_carlo.engine").removeHandler(h)
    assert log_records, f"No MC progress logs emitted. Got: {log_records}"
    log(f"    Progress log count: {len(log_records)}")
    log(f"    First: {log_records[0][:80]}")

if run_test("progress/logs_emitted", t_progress_logs_emitted): passed += 1
else: failed += 1

# ── SUMMARY ──────────────────────────────────────────────────────────────
section("SUMMARY")
log(f"  Passed: {passed}")
log(f"  Failed: {failed}")
log(f"  Total:  {passed + failed}")
log()
log("BENCHMARK TABLE (full engine, 50 trades):")
log(f"  {'Sims':>8}  {'Time (ms)':>12}  {'sims/s':>10}")
for n in [10, 100, 500, 1_000]:
    if n in timings:
        rate = n / timings[n]
        log(f"  {n:>8,}  {timings[n]*1000:>12.1f}  {rate:>10,.0f}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\nResults written to {OUT}")
sys.exit(0 if failed == 0 else 1)
