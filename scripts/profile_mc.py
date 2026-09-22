"""Profile Monte Carlo end-to-end with timestamps at every stage.

Run from project root:
    .venv\Scripts\python.exe scripts\profile_mc.py

Tests 10 / 100 / 500 / 1000 simulations on synthetic trades.
Also times compute_horizon_bands separately.
Reports per-stage timings and sims/sec.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make sure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

# ── helpers ────────────────────────────────────────────────────────────────

class Timer:
    def __init__(self, label: str):
        self.label = label
        self._start = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed = time.perf_counter() - self._start
        print(f"  [{self.label}] {self.elapsed*1000:.1f} ms")


def sep(title=""):
    print("\n" + "="*60)
    if title:
        print(f"  {title}")
        print("="*60)


# ── stage 1: imports ───────────────────────────────────────────────────────
sep("IMPORTS")
with Timer("import numpy"):
    import numpy as _np

with Timer("import MC engine"):
    from app.backtesting.monte_carlo.engine import TradeResamplingMonteCarlo, _sample_index_matrix, _series
    from app.backtesting.monte_carlo.schemas import MonteCarloConfig, SamplingMethod, CapitalMode

with Timer("import MC simulation"):
    from app.backtesting.monte_carlo.simulation import simulate_equity_batch

with Timer("import MC pipeline / make_synthetic_trades"):
    from app.backtesting.monte_carlo.pipeline import make_synthetic_trades

with Timer("import validation"):
    from app.backtesting.monte_carlo.validation import validate_config, validate_trades, series_for_mode

with Timer("import horizon_outlook"):
    from app.services.dashboard.horizon_outlook import compute_horizon_bands

# ── stage 2: synthetic trades ──────────────────────────────────────────────
sep("SYNTHETIC TRADE GENERATION")
TRADE_COUNTS = [20, 50, 100]
SIM_COUNTS   = [10, 100, 500, 1_000]

for n_trades in TRADE_COUNTS:
    with Timer(f"make_synthetic_trades(n={n_trades})"):
        trades = make_synthetic_trades(n_trades, seed=1)
    print(f"    => {len(trades)} trades, first pnl={trades[0].pnl:.2f}")

# Use 50 trades for all timing runs
trades = make_synthetic_trades(50, seed=1)

# ── stage 3: per-stage breakdown ───────────────────────────────────────────
sep("PER-STAGE BREAKDOWN  (50 trades, 1,000 sims)")
config = MonteCarloConfig(simulations=1_000, random_seed=42)

with Timer("validate_config"):
    validate_config(config)

with Timer("validate_trades"):
    validate_trades(trades, capital_mode=config.capital_mode)

with Timer("series_for_mode (extract values array)"):
    capital_mode, _warns = series_for_mode(trades, capital_mode=config.capital_mode)

with Timer("_series (build numpy array)"):
    values = _series(trades, capital_mode)

rng = np.random.default_rng(config.random_seed)
with Timer("_sample_index_matrix (1000 sims)"):
    idx = _sample_index_matrix(rng, values.size, 1_000, config.sampling_method)

with Timer("values[idx]  (build paths matrix)"):
    paths = values[idx]

with Timer("simulate_equity_batch (1000 sims)"):
    batch = simulate_equity_batch(paths, initial_capital=config.initial_capital, capital_mode=capital_mode)

with Timer("percentile calculations"):
    from app.backtesting.monte_carlo.engine import _percentiles
    final_p  = _percentiles(batch["final"])
    return_p = _percentiles(batch["ret"])
    dd_p     = _percentiles(batch["dd"])
    dd_abs_p = _percentiles(np.abs(batch["dd"]))
    min_p    = _percentiles(batch["min_eq"])
    streak_p = _percentiles(batch["lose_streak"].astype(float))

with Timer("p_loss / p_profit / p_ruin scalars"):
    p_loss   = float(np.mean(batch["final"] < config.initial_capital))
    p_profit = float(np.mean(batch["final"] > config.initial_capital))
    p_ruin   = float(np.mean(batch["min_eq"] < config.ruin_equity))

with Timer("robustness + verdict"):
    from app.backtesting.monte_carlo.robustness import assess_robustness, assess_verdict
    robustness = assess_robustness(
        source_trade_count=len(trades),
        probability_of_loss=p_loss,
        median_return=return_p.p50,
        p05_return=return_p.p05,
        p95_max_drawdown=-float(np.percentile(np.abs(batch["dd"]), 95)),
        p95_losing_streak=float(np.percentile(batch["lose_streak"], 95)),
        cost_rows=[],
    )
    verdict = assess_verdict(
        source_trade_count=len(trades),
        probability_of_loss=p_loss,
        median_return=return_p.p50,
        p95_max_drawdown=-float(np.percentile(np.abs(batch["dd"]), 95)),
        score=robustness.score,
    )

with Timer("risk_metrics"):
    from app.backtesting.monte_carlo.risk_metrics import compute_risk_metrics
    risk_metrics = compute_risk_metrics(batch["ret"], initial_capital=config.initial_capital)

# ── stage 4: full engine.run() timing ─────────────────────────────────────
sep("FULL TradeResamplingMonteCarlo.run()  (50 trades)")
results = {}
for n_sims in SIM_COUNTS:
    mc = TradeResamplingMonteCarlo(MonteCarloConfig(simulations=n_sims, random_seed=42))
    t0 = time.perf_counter()
    result = mc._run_trades(list(trades), strategy="test", symbol="TEST", period="")
    elapsed = time.perf_counter() - t0
    rate = n_sims / elapsed if elapsed > 0 else float("inf")
    results[n_sims] = elapsed
    print(f"  n_sims={n_sims:>6,}  elapsed={elapsed*1000:8.1f} ms  rate={rate:,.0f} sims/s")

# ── stage 5: horizon_bands separate timing ────────────────────────────────
sep("compute_horizon_bands()  (simulations=2000, horizons=[1,2,5])")
daily_returns = np.random.default_rng(42).normal(0.001, 0.015, 500)
for n_sims in [100, 500, 2_000]:
    t0 = time.perf_counter()
    bands = compute_horizon_bands(
        daily_returns,
        current_price=2500.0,
        horizons=[1, 2, 5],
        simulations=n_sims,
        random_seed=42,
    )
    elapsed = time.perf_counter() - t0
    print(f"  n_sims={n_sims:>6,}  elapsed={elapsed*1000:8.1f} ms  bands={len(bands)}")

# ── stage 6: _max_run bottleneck check ────────────────────────────────────
sep("_max_run loop (streak calc)  — suspected bottleneck at large N")
from app.backtesting.monte_carlo.simulation import _max_run
for n_steps in [20, 50, 200]:
    for n_sims in [100, 1_000, 10_000]:
        rng2 = np.random.default_rng(1)
        mask = rng2.random((n_sims, n_steps)) > 0.5
        t0 = time.perf_counter()
        streaks = _max_run(mask)
        elapsed = time.perf_counter() - t0
        print(f"  n_sims={n_sims:>6,}  n_steps={n_steps:>3}  elapsed={elapsed*1000:7.2f} ms")

# ── stage 7: walk-forward check (does not run WF, just checks cache) ─────
sep("OOS cache lookup speed")
from app.services.dashboard.oos_trade_cache import OOSTradeCache, cache_key
import tempfile, os
with tempfile.TemporaryDirectory() as tmpdir:
    cache = OOSTradeCache(Path(tmpdir))
    # Fake parquet path for fingerprint
    fake_parquet = Path(tmpdir) / "RELIANCE.parquet"
    fake_parquet.write_bytes(b"x" * 1000)
    key = cache_key(symbol="RELIANCE", strategy_alias="ema_professional",
                    config_fingerprint="wf:y2:1:1:cap1000000", parquet=fake_parquet)
    t0 = time.perf_counter()
    hit = cache.get(key)
    elapsed = time.perf_counter() - t0
    print(f"  cache miss lookup: {elapsed*1000:.2f} ms  result={hit}")

    # Write then read
    from app.backtesting.monte_carlo.pipeline import make_synthetic_trades as _mst
    trades_c = _mst(30, seed=2)
    t0 = time.perf_counter()
    cache.put(key, trades=trades_c, period="2022", window_count=3, strategy_alias="ema_professional")
    elapsed = time.perf_counter() - t0
    print(f"  cache write (30 trades): {elapsed*1000:.2f} ms")

    t0 = time.perf_counter()
    hit2 = cache.get(key)
    elapsed = time.perf_counter() - t0
    print(f"  cache hit read  (30 trades): {elapsed*1000:.2f} ms  trades={hit2.trade_count if hit2 else 'NONE'}")

# ── SUMMARY ───────────────────────────────────────────────────────────────
sep("SUMMARY — full engine.run() on 50 trades")
baseline_10   = results[10]
baseline_1000 = results[1_000]
print(f"  10   sims: {baseline_10*1000:8.1f} ms")
print(f"  100  sims: {results[100]*1000:8.1f} ms")
print(f"  500  sims: {results[500]*1000:8.1f} ms")
print(f"  1000 sims: {baseline_1000*1000:8.1f} ms")
print(f"\n  Scaling 10→1000:  {baseline_1000/baseline_10:.1f}x  (expected ~100x for linear)")
print()
