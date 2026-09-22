"""
After-fix timing: runs DashboardMonteCarloService for 10, 100, 1000 sims
and reports per-stage timing. Writes to scripts/after_fix_output.txt.

Run: .venv\Scripts\python.exe scripts\run_after_fix.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).parent / "after_fix_output.txt"
lines: list[str] = []

def log(m=""):
    lines.append(str(m)); print(m, flush=True)

def section(t):
    log(); log("="*60); log(f"  {t}"); log("="*60)

section("IMPORTS")
t0 = time.perf_counter()
from app.core.config import get_settings
from app.services.dashboard.monte_carlo_service import DashboardMonteCarloService
from app.services.dashboard.schemas import MonteCarloDashboardRequest
from app.services.trade_recommendation.strategy_validation import STRATEGY_REGISTERARS
settings = get_settings()
log(f"  done ({(time.perf_counter()-t0)*1000:.0f}ms)")

storage = Path(settings.parquet_storage_dir)
parquet_files = sorted(storage.glob("*.parquet"))
assert parquet_files, f"No parquet in {storage}"
symbol = parquet_files[0].stem.upper()
_OOS = {"ema_trend","ema_professional","ema_trend_professional","ema"}
non_wf = sorted(s for s in STRATEGY_REGISTERARS if s not in _OOS)
strategy = non_wf[0] if non_wf else "ema_trend"
log(f"  symbol={symbol}  strategy={strategy}")

# ── patch historical_window + slice_features to count calls ──────────────
import app.backtesting.replay_engine.replay_session as _rs
_orig_hw = _rs.ReplaySession.historical_window
_hw_calls = [0]
def _hw(self):
    _hw_calls[0] += 1
    return _orig_hw(self)
_rs.ReplaySession.historical_window = _hw

_orig_sftc = _rs.ReplaySession.slice_features_to_cursor
_sftc_calls = [0]
def _sftc(self, features):
    _sftc_calls[0] += 1
    return _orig_sftc(self, features)
_rs.ReplaySession.slice_features_to_cursor = _sftc

import app.backtesting.replay_engine.engine as _re
_orig_run = _re.HistoricalReplayEngine.run
_replay_times: list[float] = []
def _run(self):
    t0 = time.perf_counter()
    r = _orig_run(self)
    _replay_times.append(time.perf_counter()-t0)
    return r
_re.HistoricalReplayEngine.run = _run

section(f"RUNS: {symbol} / {strategy}")

results = {}
for n_sims in [10, 100, 1_000]:
    _hw_calls[0] = 0; _sftc_calls[0] = 0; _replay_times.clear()
    svc = DashboardMonteCarloService()
    req = MonteCarloDashboardRequest(
        strategy=strategy, simulations=n_sims,
        random_seed=42, initial_capital=1_000_000.0, horizons=[1,2,5],
    )
    log(f"\n  n_sims={n_sims:,} ...")
    t0 = time.perf_counter()
    try:
        resp = svc.run(symbol, req)
        elapsed = time.perf_counter()-t0
        results[n_sims] = {"ok": True, "elapsed": elapsed,
                           "available": resp.available,
                           "sim_count": resp.simulation_count,
                           "hist_trades": resp.historical_oos_trade_count,
                           "replay_time": sum(_replay_times),
                           "hw_calls": _hw_calls[0],
                           "sftc_calls": _sftc_calls[0]}
        log(f"  OK  total={elapsed:.3f}s  replay={sum(_replay_times):.3f}s  "
            f"hw_calls={_hw_calls[0]}  sftc_calls={_sftc_calls[0]}")
        log(f"  available={resp.available}  sim_count={resp.simulation_count}  "
            f"hist_trades={resp.historical_oos_trade_count}")
    except Exception as e:
        elapsed = time.perf_counter()-t0
        results[n_sims] = {"ok": False, "elapsed": elapsed, "error": str(e)}
        log(f"  FAIL  {elapsed:.3f}s  {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()

section("SUMMARY")
log(f"\n{'Sims':>8}  {'Total(s)':>10}  {'Replay(s)':>10}  {'hw_calls':>10}  Status")
for n, r in sorted(results.items()):
    if r.get("ok"):
        log(f"{n:>8,}  {r['elapsed']:>10.3f}  {r.get('replay_time',0):>10.3f}  "
            f"{r.get('hw_calls',0):>10}  OK")
    else:
        log(f"{n:>8,}  {r['elapsed']:>10.3f}  {'—':>10}  {'—':>10}  FAIL")

log("\nNOTE on hw_calls:")
log("  hw_calls = number of historical_window() calls during replay.")
log("  For N candles this should equal N (one call per candle).")
log("  Before fix: each call copied [0..i] rows → O(N²) total memory.")
log("  After fix:  each call returns a view → O(1) per call, O(N) total.")

OUT.write_text("\n".join(lines), encoding="utf-8")
log(f"\nWritten to {OUT}")
