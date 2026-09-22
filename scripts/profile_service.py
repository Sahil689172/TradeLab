"""
Profile the DashboardMonteCarloService stage-by-stage.

Instruments:
  1. Service entry / config
  2. load_trades_from_replay() broken into:
     a. HistoricalReplayEngine.run()  (the replay loop)
     b. OrderExecutionEngine.process_replay_result()
     c. trades_from_sources()
  3. MonteCarloEngine.run() / _simulate_batch()
  4. _horizon_inputs() — pd.read_parquet
  5. compute_horizon_bands()
  6. Response construction

Also checks whether load_trades_from_replay is called ONCE or multiple times.

Run: .venv\Scripts\python.exe scripts\profile_service.py
Output written to scripts\profile_service_output.txt
"""
from __future__ import annotations

import sys
import time
import functools
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).parent / "profile_service_output.txt"
lines: list[str] = []

def log(m: str = "") -> None:
    lines.append(str(m))
    print(m, flush=True)

def section(t: str) -> None:
    log(); log("=" * 64); log(f"  {t}"); log("=" * 64)

section("IMPORTS")
t0 = time.perf_counter()
from app.core.config import get_settings
from app.services.dashboard.monte_carlo_service import DashboardMonteCarloService
from app.services.dashboard.schemas import MonteCarloDashboardRequest
settings = get_settings()
log(f"  Imports complete  ({(time.perf_counter()-t0)*1000:.0f} ms)")

# ── find symbol ────────────────────────────────────────────────────────────
storage = Path(settings.parquet_storage_dir)
parquet_files = sorted(storage.glob("*.parquet"))
assert parquet_files, f"No parquet files in {storage}"
symbol = parquet_files[0].stem.upper()
log(f"  Symbol: {symbol}  storage: {storage}")

# ── choose non-WF strategy ─────────────────────────────────────────────────
from app.services.trade_recommendation.strategy_validation import STRATEGY_REGISTERARS
_OOS = {"ema_trend","ema_professional","ema_trend_professional","ema"}
non_wf = sorted(s for s in STRATEGY_REGISTERARS if s not in _OOS)
strategy = non_wf[0] if non_wf else "ema_trend"
log(f"  Strategy: {strategy}")

# ── Instrumentation patches ────────────────────────────────────────────────
call_counts: dict[str, int] = {}
timings: dict[str, list[float]] = {}

def timed(label: str, fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    timings.setdefault(label, []).append(elapsed)
    call_counts[label] = call_counts.get(label, 0) + 1
    return result, elapsed

# Patch replay engine run()
import app.backtesting.replay_engine.engine as _re_mod
_orig_replay_run = _re_mod.HistoricalReplayEngine.run

def _patched_replay_run(self):
    t0 = time.perf_counter()
    result = _orig_replay_run(self)
    elapsed = time.perf_counter() - t0
    timings.setdefault("replay_engine.run", []).append(elapsed)
    call_counts["replay_engine.run"] = call_counts.get("replay_engine.run", 0) + 1
    log(f"  [INSTRUMENT] replay_engine.run(): {elapsed:.3f}s  "
        f"candles={result.candles_replayed}  recs={result.recommendations_generated}")
    return result
_re_mod.HistoricalReplayEngine.run = _patched_replay_run

# Patch OrderExecutionEngine.process_replay_result
import app.backtesting.order_execution.engine as _oe_mod
_orig_exec = _oe_mod.OrderExecutionEngine.process_replay_result

def _patched_exec(self, replay_result):
    t0 = time.perf_counter()
    result = _orig_exec(self, replay_result)
    elapsed = time.perf_counter() - t0
    timings.setdefault("order_execution.process_replay", []).append(elapsed)
    call_counts["order_execution.process_replay"] = call_counts.get("order_execution.process_replay", 0) + 1
    log(f"  [INSTRUMENT] order_execution.process_replay_result(): {elapsed:.3f}s  "
        f"trades={len(result.trade_log)}")
    return result
_oe_mod.OrderExecutionEngine.process_replay_result = _patched_exec

# Patch historical_window() to count calls (O(N²) suspect)
import app.backtesting.replay_engine.replay_session as _rs_mod
_orig_hw = _rs_mod.ReplaySession.historical_window
_hw_call_count = [0]
def _patched_hw(self):
    _hw_call_count[0] += 1
    return _orig_hw(self)
_rs_mod.ReplaySession.historical_window = _patched_hw

# Patch slice_features_to_cursor() to count calls
_orig_sftc = _rs_mod.ReplaySession.slice_features_to_cursor
_sftc_call_count = [0]
def _patched_sftc(self, features):
    _sftc_call_count[0] += 1
    return _orig_sftc(self, features)
_rs_mod.ReplaySession.slice_features_to_cursor = _patched_sftc

# Patch ContextStrategyEvaluator.evaluate() to count calls
import app.backtesting.replay_engine.adapters as _ad_mod
_orig_eval = _ad_mod.ContextStrategyEvaluator.evaluate
_eval_call_count = [0]
_eval_total = [0.0]
def _patched_eval(self, **kwargs):
    _eval_call_count[0] += 1
    t0 = time.perf_counter()
    result = _orig_eval(self, **kwargs)
    _eval_total[0] += time.perf_counter() - t0
    return result
_ad_mod.ContextStrategyEvaluator.evaluate = _patched_eval

# Patch compute_horizon_bands
import app.services.dashboard.horizon_outlook as _ho_mod
_orig_chb = _ho_mod.compute_horizon_bands
def _patched_chb(*args, **kwargs):
    t0 = time.perf_counter()
    result = _orig_chb(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    timings.setdefault("compute_horizon_bands", []).append(elapsed)
    call_counts["compute_horizon_bands"] = call_counts.get("compute_horizon_bands", 0) + 1
    log(f"  [INSTRUMENT] compute_horizon_bands(): {elapsed:.3f}s  "
        f"sims={kwargs.get('simulations','?')}  bands={len(result)}")
    return result
_ho_mod.compute_horizon_bands = _patched_chb
# Also patch in monte_carlo_service module (already imported)
import app.services.dashboard.monte_carlo_service as _mc_svc_mod
_mc_svc_mod.compute_horizon_bands = _patched_chb

# Patch pd.read_parquet to count and time calls
import pandas as _pd
_orig_read_parquet = _pd.read_parquet
_rp_calls: list[tuple[str, float]] = []
def _patched_read_parquet(path, *args, **kwargs):
    t0 = time.perf_counter()
    result = _orig_read_parquet(path, *args, **kwargs)
    elapsed = time.perf_counter() - t0
    _rp_calls.append((str(path), elapsed))
    return result
_pd.read_parquet = _patched_read_parquet

# ── RUN PROFILING ──────────────────────────────────────────────────────────

def run_once(n_sims: int, label: str) -> None:
    section(f"RUN: {label}  n_sims={n_sims}")

    # Reset counters
    _hw_call_count[0] = 0
    _sftc_call_count[0] = 0
    _eval_call_count[0] = 0
    _eval_total[0] = 0.0
    _rp_calls.clear()
    timings.clear()
    call_counts.clear()

    svc = DashboardMonteCarloService()
    req = MonteCarloDashboardRequest(
        strategy=strategy,
        simulations=n_sims,
        random_seed=42,
        initial_capital=1_000_000.0,
        horizons=[1, 2, 5],
    )

    # Stage 1: _load_trades
    log(f"\n  Stage 1: _load_trades ...")
    t_load = time.perf_counter()
    trades, trade_source, period, warnings = svc._load_trades(symbol, req)
    t_load = time.perf_counter() - t_load

    log(f"\n  ── Stage timing after _load_trades ──")
    log(f"  _load_trades total:           {t_load:.3f}s")
    log(f"  replay_engine.run calls:      {call_counts.get('replay_engine.run', 0)}")
    if "replay_engine.run" in timings:
        log(f"  replay_engine.run time:       {sum(timings['replay_engine.run']):.3f}s")
    log(f"  order_execution.process:      {sum(timings.get('order_execution.process_replay', [0])):.3f}s")
    log(f"  historical_window() calls:    {_hw_call_count[0]}")
    log(f"  slice_features_to_cursor():   {_sftc_call_count[0]}")
    log(f"  evaluator.evaluate() calls:   {_eval_call_count[0]}")
    log(f"  evaluator.evaluate() total:   {_eval_total[0]:.3f}s")
    log(f"  trades extracted:             {len(trades)}")
    log(f"  trade_source:                 {trade_source}")

    log(f"\n  pd.read_parquet calls during _load_trades:")
    for path, elapsed in _rp_calls:
        log(f"    {Path(path).name:<40} {elapsed*1000:.1f}ms")
    _rp_calls.clear()

    if not trades:
        log(f"  No trades — skipping MC stages")
        return

    # Stage 2: MC engine
    from app.backtesting.monte_carlo import MonteCarloConfig, MonteCarloEngine
    mc_config = MonteCarloConfig(
        simulations=n_sims,
        initial_capital=req.initial_capital,
        random_seed=req.random_seed,
    )
    log(f"\n  Stage 2: MonteCarloEngine.run ...")
    t_mc = time.perf_counter()
    mc_result = MonteCarloEngine(mc_config).run(
        trades, strategy=strategy, symbol=symbol, period=period
    )
    t_mc = time.perf_counter() - t_mc
    log(f"  MonteCarloEngine.run:         {t_mc:.3f}s  ({n_sims/t_mc:,.0f} sims/s)")

    # Stage 3: horizon inputs
    parquet_path = storage / f"{symbol}.parquet"
    log(f"\n  Stage 3: _horizon_inputs (pd.read_parquet) ...")
    t_hi = time.perf_counter()
    current_price, daily_returns, horizons = svc._horizon_inputs(parquet_path, req)
    t_hi = time.perf_counter() - t_hi
    log(f"  _horizon_inputs:              {t_hi:.3f}s  price={current_price:.2f}  returns={len(daily_returns)}")

    # Stage 4: compute_horizon_bands
    log(f"\n  Stage 4: compute_horizon_bands ...")
    from app.services.dashboard.monte_carlo_service import _HORIZON_BOOTSTRAP_CAP
    t_hb = time.perf_counter()
    from app.services.dashboard.horizon_outlook import compute_horizon_bands
    bands = compute_horizon_bands(
        daily_returns,
        current_price=current_price,
        horizons=horizons,
        simulations=min(n_sims, _HORIZON_BOOTSTRAP_CAP),
        random_seed=req.random_seed,
    )
    t_hb = time.perf_counter() - t_hb
    log(f"  compute_horizon_bands:        {t_hb:.3f}s  bands={len(bands)}")

    # Stage 5: response construction
    log(f"\n  Stage 5: response construction ...")
    t_resp = time.perf_counter()
    resp = svc.run(symbol, req)
    t_resp = time.perf_counter() - t_resp
    # run() re-runs everything, so subtract the already-measured stages
    log(f"  svc.run() TOTAL (all stages): {t_resp:.3f}s")

    log(f"\n  pd.read_parquet calls during MC+horizon stages:")
    for path, elapsed in _rp_calls:
        log(f"    {Path(path).name:<40} {elapsed*1000:.1f}ms")

    total = t_load + t_mc + t_hi + t_hb
    log(f"\n  ── TIMING BREAKDOWN ──────────────────────────────────────")
    log(f"  {'Stage':<35} {'Time':>8}")
    log(f"  {'-'*35} {'------':>8}")
    log(f"  {'1. _load_trades (total)':<35} {t_load:>8.3f}s")
    if "replay_engine.run" in timings:
        rt = sum(timings['replay_engine.run'])
        log(f"  {'   └─ replay_engine.run':<35} {rt:>8.3f}s")
    et = sum(timings.get('order_execution.process_replay', [0]))
    if et > 0:
        log(f"  {'   └─ order_execution':<35} {et:>8.3f}s")
    log(f"  {'   └─ evaluator.evaluate() ×'+str(_eval_call_count[0]):<35} {_eval_total[0]:>8.3f}s")
    log(f"  {'   └─ historical_window() ×'+str(_hw_call_count[0]):<35} {'(included above)':>16}")
    log(f"  {'2. MonteCarloEngine.run':<35} {t_mc:>8.3f}s")
    log(f"  {'3. _horizon_inputs':<35} {t_hi:>8.3f}s")
    log(f"  {'4. compute_horizon_bands':<35} {t_hb:>8.3f}s")
    log(f"  {'-'*35} {'------':>8}")
    log(f"  {'Stages 1-4 (excl. response)':<35} {total:>8.3f}s")
    log(f"  {'svc.run() TOTAL':<35} {t_resp:>8.3f}s")
    log()
    log(f"  BOTTLENECK SHARE: load_trades={t_load/t_resp*100:.1f}%  "
        f"mc={t_mc/t_resp*100:.1f}%  horizon={t_hb/t_resp*100:.1f}%")
    log(f"  evaluator.evaluate() per call: "
        f"{_eval_total[0]/_eval_call_count[0]*1000:.1f}ms avg  "
        f"(×{_eval_call_count[0]} calls)")


# Run for n=10 and n=1000
run_once(10, "FIRST RUN (cold)")
run_once(1000, "SECOND RUN (same process — cache warm)")

section("DIAGNOSIS")
log("""
Key questions answered:
  Q1: Is load_trades_from_replay re-run for each simulation count?
      => Check replay_engine.run call count above. Should be 1 per run_once().

  Q2: Is the replay loop O(N^2) in number of candles?
      => historical_window() call count shows whether a growing copy is made per candle.
         If historical_window calls == N candles, each call copies an increasing window.
         Total copy work = O(N^2).

  Q3: Is ContextStrategyEvaluator.evaluate() expensive per call?
      => evaluator.evaluate() total / call_count shows per-call cost.

  Q4: Does n=1000 cost more than n=10 in the replay stage?
      => Compare _load_trades time across both runs.
         If identical: bottleneck is fixed overhead (replay), not simulation count.
         If n=1000 is slower: bottleneck scales with simulations (horizon or MC).
""")

OUT.write_text("\n".join(lines), encoding="utf-8")
log(f"Written to {OUT}")
