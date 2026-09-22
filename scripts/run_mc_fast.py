"""
Minimal MC test - imports ONLY numpy + simulation.py + schemas.py directly.
No FastAPI, no replay engine, no strategy code.
Run: .venv\Scripts\python.exe scripts\run_mc_fast.py
"""
import sys, time, traceback
from pathlib import Path

OUT = Path(__file__).parent / "mc_fast_output.txt"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

lines = []
def log(m=""): lines.append(str(m)); print(m)
def section(t): log(); log("="*60); log(f"  {t}"); log("="*60)
passed = failed = 0

def run_test(name, fn):
    global passed, failed
    try:
        t0 = time.perf_counter()
        fn()
        log(f"  PASS  {name}  ({(time.perf_counter()-t0)*1000:.1f}ms)")
        passed += 1
    except Exception as e:
        log(f"  FAIL  {name}  => {type(e).__name__}: {e}")
        failed += 1

section("IMPORTS (minimal)")
t0 = time.perf_counter()
import numpy as np
log(f"  numpy OK ({(time.perf_counter()-t0)*1000:.0f}ms)")

t0 = time.perf_counter()
# Import directly, bypassing __init__.py (which pulls in the whole app)
from app.backtesting.monte_carlo.simulation import _max_run, simulate_equity_batch, simulate_equity
from app.backtesting.monte_carlo.schemas import CapitalMode, MonteCarloConfig, MonteCarloTrade, MonteCarloVerdict
log(f"  simulation + schemas OK ({(time.perf_counter()-t0)*1000:.0f}ms)")

t0 = time.perf_counter()
from app.backtesting.monte_carlo.engine import TradeResamplingMonteCarlo, _sample_index_matrix, _series
from app.backtesting.monte_carlo.validation import validate_config, validate_trades
log(f"  engine + validation OK ({(time.perf_counter()-t0)*1000:.0f}ms)")

t0 = time.perf_counter()
# make_synthetic_trades lives in pipeline.py but we can reproduce it inline
# to avoid the replay_engine import
def make_trades(count, seed=1):
    rng = np.random.default_rng(int(seed))
    pnl = np.clip(rng.normal(20.0, 80.0, size=int(count)), -400.0, 400.0)
    return [MonteCarloTrade(pnl=float(p), return_pct=float(p)/1000.0) for p in pnl]
log(f"  synthetic trades helper ready")

# ── REFERENCE _max_run ────────────────────────────────────────────────────
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
run_test("all_true",    lambda: np.testing.assert_array_equal(_max_run(np.ones((4,6),bool)), [6,6,6,6]))
run_test("all_false",   lambda: np.testing.assert_array_equal(_max_run(np.zeros((4,6),bool)), [0,0,0,0]))
run_test("alternating", lambda: (lambda m: np.testing.assert_array_equal(_max_run(m),[1]))(np.array([[True,False,True,False,True,False]])))
run_test("run_at_end",  lambda: (lambda m: np.testing.assert_array_equal(_max_run(m),[3]))(np.array([[False,False,True,True,True]])))
run_test("run_at_start",lambda: (lambda m: np.testing.assert_array_equal(_max_run(m),[2]))(np.array([[True,True,False,False,False]])))
run_test("empty_steps", lambda: np.testing.assert_array_equal(_max_run(np.zeros((5,0),bool)), [0,0,0,0,0]))
run_test("single_step", lambda: np.testing.assert_array_equal(_max_run(np.array([[True],[False],[True]])), [1,0,1]))

def t_multi_row():
    m = np.array([[True,True,False,True],[False,False,False,False],[True,True,True,True],[False,True,False,True]], dtype=bool)
    np.testing.assert_array_equal(_max_run(m), _max_run_ref(m))
    np.testing.assert_array_equal(_max_run(m), [2,0,4,1])
run_test("multi_row", t_multi_row)

# ── PAIRWISE MATCH REFERENCE ──────────────────────────────────────────────
section("_max_run MATCHES REFERENCE")
for ns, nt in [(1,1),(10,20),(100,50),(1000,100),(5000,200)]:
    def mk(ns,nt):
        def fn():
            mask = np.random.default_rng(42).random((ns,nt)) > 0.5
            np.testing.assert_array_equal(_max_run(mask), _max_run_ref(mask))
        return fn
    run_test(f"n_sims={ns},n_steps={nt}", mk(ns,nt))

# ── _max_run SPEED ────────────────────────────────────────────────────────
section("_max_run SPEED: new vs reference")
timings_maxrun = {}
for ns, nt in [(1000,50),(10000,50),(100000,50),(1000,200)]:
    mask = np.random.default_rng(7).random((ns,nt)) > 0.5
    t0=time.perf_counter(); _max_run_ref(mask); t_ref=time.perf_counter()-t0
    t0=time.perf_counter(); _max_run(mask);     t_new=time.perf_counter()-t0
    speedup = t_ref/t_new if t_new>0 else float("inf")
    timings_maxrun[(ns,nt)] = (t_ref, t_new, speedup)
    log(f"  n_sims={ns:>6}  n_steps={nt:>3}  ref={t_ref*1000:7.2f}ms  new={t_new*1000:7.2f}ms  speedup={speedup:.1f}x")

# ── simulate_equity_batch STREAKS ─────────────────────────────────────────
section("simulate_equity_batch STREAK CORRECTNESS")

def t_known_streaks():
    pnls = [10.,10.,10.,10.,10.,-5.,-5.,-5.,8.,8.]
    paths = np.array([pnls,pnls], dtype=float)
    b = simulate_equity_batch(paths, initial_capital=1000., capital_mode=CapitalMode.ADDITIVE_PNL)
    assert int(b["lose_streak"][0])==3 and int(b["win_streak"][0])==5

def t_single_trade():
    paths = np.array([[100.],[-50.]], dtype=float)
    b = simulate_equity_batch(paths, initial_capital=1000., capital_mode=CapitalMode.ADDITIVE_PNL)
    assert abs(b["final"][0]-1100.) < 0.01
    assert abs(b["final"][1]-950.)  < 0.01
    assert int(b["lose_streak"][0])==0 and int(b["lose_streak"][1])==1

run_test("known_streaks", t_known_streaks)
run_test("single_trade",  t_single_trade)

# ── EDGE CASES ────────────────────────────────────────────────────────────
section("EDGE CASES")

def t_zero_trades():
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=10))
    r = mc._run_trades([], strategy="t", symbol="T", period="")
    assert r.verdict == MonteCarloVerdict.INSUFFICIENT_EVIDENCE

def t_one_trade():
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=50, random_seed=1))
    r = mc._run_trades([MonteCarloTrade(pnl=100., return_pct=0.1)], strategy="t", symbol="T", period="")
    assert r.probability_of_loss == 0.0 and r.probability_of_profit == 1.0

def t_all_winning():
    trades = [MonteCarloTrade(pnl=50., return_pct=0.05) for _ in range(20)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=100, random_seed=1))
    r = mc._run_trades(trades, strategy="t", symbol="T", period="")
    assert r.probability_of_loss == 0.0

def t_all_losing():
    trades = [MonteCarloTrade(pnl=-50., return_pct=-0.05) for _ in range(20)]
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=100, random_seed=1))
    r = mc._run_trades(trades, strategy="t", symbol="T", period="")
    assert r.probability_of_profit == 0.0

def t_nan_pnl_rejected():
    try:
        MonteCarloTrade(pnl=float("nan"), return_pct=0.0)
        raise AssertionError("Should reject NaN")
    except (ValueError, Exception) as e:
        if "AssertionError" in type(e).__name__: raise

def t_invalid_sim_zero():
    try:
        MonteCarloConfig(simulations=0)
        raise AssertionError("Should reject 0 sims")
    except (ValueError, Exception) as e:
        if "AssertionError" in type(e).__name__: raise

for name, fn in [("zero_trades",t_zero_trades),("one_trade",t_one_trade),
                  ("all_winning",t_all_winning),("all_losing",t_all_losing),
                  ("nan_pnl_rejected",t_nan_pnl_rejected),("invalid_sim_zero",t_invalid_sim_zero)]:
    run_test(f"edge/{name}", fn)

# ── FULL ENGINE TIMING ────────────────────────────────────────────────────
section("FULL ENGINE TIMING (50 synthetic trades)")
trades50 = make_trades(50, seed=1)
timings = {}

for n_sims in [10, 100, 500, 1_000]:
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=n_sims, random_seed=42))
    t0 = time.perf_counter()
    result = mc._run_trades(list(trades50), strategy="bench", symbol="TEST", period="")
    elapsed = time.perf_counter() - t0
    rate = n_sims / elapsed if elapsed > 0 else float("inf")
    timings[n_sims] = elapsed
    log(f"  n_sims={n_sims:>6,}  elapsed={elapsed*1000:8.1f}ms  rate={rate:,.0f} sims/s")
    assert 0.0 <= result.probability_of_loss <= 1.0, "invalid probability"
    assert result.source_trade_count == 50, f"wrong trade count: {result.source_trade_count}"

def t_10_sims():   assert timings[10]    < 1.0, f"10 sims took {timings[10]:.2f}s"
def t_100_sims():  assert timings[100]   < 1.0, f"100 sims took {timings[100]:.2f}s"
def t_1000_sims(): assert timings[1_000] < 5.0, f"1000 sims took {timings[1_000]:.2f}s"
def t_rate():
    rate = 1000 / timings[1_000]
    assert rate >= 200, f"Only {rate:.0f} sims/s"
    log(f"    => final rate: {rate:,.0f} sims/s")

for name, fn in [("<1s for 10",t_10_sims),("<1s for 100",t_100_sims),
                  ("<5s for 1000",t_1000_sims),(">=200 sims/s",t_rate)]:
    run_test(f"timing/{name}", fn)

# ── DETERMINISM ──────────────────────────────────────────────────────────
section("DETERMINISM")
def t_deterministic():
    trades = make_trades(30, seed=5)
    cfg = MonteCarloConfig(simulations=500, random_seed=42)
    r1 = TradeResamplingMonteCarlo(cfg)._run_trades(list(trades), strategy="t", symbol="T", period="")
    r2 = TradeResamplingMonteCarlo(cfg)._run_trades(list(trades), strategy="t", symbol="T", period="")
    assert abs(r1.probability_of_loss - r2.probability_of_loss) < 1e-9
    assert abs(r1.return_percentiles.p50 - r2.return_percentiles.p50) < 1e-9

run_test("determinism/same_seed", t_deterministic)

# ── PROGRESS LOGGING ─────────────────────────────────────────────────────
section("PROGRESS LOGGING")
def t_progress_logs():
    import logging
    trades = make_trades(20, seed=3)
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=500, random_seed=1))
    records = []
    class Cap(logging.Handler):
        def emit(self, r):
            if "Monte Carlo" in r.getMessage(): records.append(r.getMessage())
    h = Cap()
    logging.getLogger("app.backtesting.monte_carlo.engine").addHandler(h)
    mc._simulate_batch(list(trades), CapitalMode.ADDITIVE_PNL)
    logging.getLogger("app.backtesting.monte_carlo.engine").removeHandler(h)
    assert records, "No progress logs emitted"
    log(f"    {len(records)} log entries. First: {records[0][:70]}")
run_test("progress/logs_emitted", t_progress_logs)

# ── SPEEDUP SUMMARY ───────────────────────────────────────────────────────
section("SPEEDUP SUMMARY")
log("_max_run speedup (new vectorised vs old Python loop):")
log(f"  {'Shape':>20}  {'Before (ms)':>12}  {'After (ms)':>12}  {'Speedup':>8}")
for (ns,nt),(t_ref,t_new,sp) in timings_maxrun.items():
    log(f"  ({ns:>6},{nt:>3})        {t_ref*1000:>12.2f}  {t_new*1000:>12.2f}  {sp:>7.1f}x")

section("FINAL RESULT")
log(f"  Passed: {passed}")
log(f"  Failed: {failed}")
log(f"  Total:  {passed+failed}")
log()
log("BENCHMARK (50 trades, full engine._run_trades):")
log(f"  {'Sims':>8}  {'ms':>8}  {'sims/s':>10}")
for n in [10,100,500,1000]:
    if n in timings:
        log(f"  {n:>8,}  {timings[n]*1000:>8.1f}  {n/timings[n]:>10,.0f}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\nWritten to {OUT}")
sys.exit(0 if failed==0 else 1)
