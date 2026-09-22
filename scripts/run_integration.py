"""
Integration test: exercises the full DashboardMonteCarloService.run() path
with a real symbol from the local Parquet store.

Run from project root:
    .venv\Scripts\python.exe scripts\run_integration.py

Tests: 10, 100, 1000 simulations.
Writes results to scripts\integration_output.txt
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Configure logging BEFORE any app imports so that every logger
#    created by get_logger() already has a handler attached.
#    Without this, all logger.info() calls in the service and replay
#    engine are silently discarded (Python's "last resort" handler
#    only fires for WARNING+ and only if no handler is configured).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,          # override any handler that a transitive import added first
)

OUT = Path(__file__).parent / "integration_output.txt"
lines: list[str] = []


def log(m: str = "") -> None:
    lines.append(str(m))
    print(m, flush=True)


def section(t: str) -> None:
    log(); log("=" * 60); log(f"  {t}"); log("=" * 60)


section("INTEGRATION TEST — full service path")

# ── find a symbol that actually has Parquet data ──────────────────────────
section("Finding available symbol")
try:
    from app.core.config import get_settings
    settings = get_settings()
    storage = Path(settings.parquet_storage_dir)
    parquet_files = sorted(storage.glob("*.parquet"))
    if not parquet_files:
        log(f"  ERROR: No Parquet files found in {storage}")
        log("  Cannot run integration test without local market data.")
        log("  Run the data bootstrap first, then re-run this script.")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        sys.exit(1)
    # Pick the first available symbol
    symbol = parquet_files[0].stem.upper()
    log(f"  Using symbol: {symbol}")
    log(f"  Parquet store: {storage}")
    log(f"  Available symbols: {[f.stem for f in parquet_files[:5]]} ...")
except Exception as e:
    log(f"  ERROR loading settings: {e}")
    import traceback; traceback.print_exc()
    OUT.write_text("\n".join(lines), encoding="utf-8")
    sys.exit(1)

# ── find a strategy that is registered ────────────────────────────────────
section("Choosing strategy")
try:
    from app.services.trade_recommendation.strategy_validation import STRATEGY_REGISTERARS
    # Prefer a non-WF strategy (faster, no walk-forward cold start)
    # so the integration test focuses on the MC engine, not the WF engine.
    non_wf = [s for s in STRATEGY_REGISTERARS
               if s not in {"ema_trend", "ema_professional", "ema_trend_professional", "ema"}]
    if non_wf:
        strategy = sorted(non_wf)[0]
        log(f"  Strategy: {strategy}  (non-WF — uses historical replay trades)")
    else:
        strategy = "ema_trend"
        log(f"  Strategy: {strategy}  (WF — cold start may be slow)")
    log(f"  All registered strategies: {sorted(STRATEGY_REGISTERARS)[:8]} ...")
except Exception as e:
    strategy = "ema_trend"
    log(f"  WARNING: could not load STRATEGY_REGISTERARS ({e}), defaulting to {strategy}")

# ── imports ────────────────────────────────────────────────────────────────
section("Importing service layer")
t0 = time.perf_counter()
try:
    from app.services.dashboard.monte_carlo_service import DashboardMonteCarloService
    from app.services.dashboard.schemas import MonteCarloDashboardRequest, MonteCarloDashboardResponse
    log(f"  Imports OK  ({(time.perf_counter()-t0)*1000:.0f} ms)")
except Exception as e:
    log(f"  IMPORT FAILED: {e}")
    import traceback; traceback.print_exc()
    OUT.write_text("\n".join(lines), encoding="utf-8")
    sys.exit(1)

svc = DashboardMonteCarloService()

# ── run at each sim count ──────────────────────────────────────────────────
section(f"Running MC via DashboardMonteCarloService  ({symbol} / {strategy})")

results: dict[int, dict] = {}
DISCLAIMER = "SIMULATED ESTIMATE — NOT GUARANTEED FUTURE PRICE"

for n_sims in [10, 100, 1_000]:
    log(f"\n  --- n_sims={n_sims:,} ---")
    req = MonteCarloDashboardRequest(
        strategy=strategy,
        simulations=n_sims,
        random_seed=42,
        initial_capital=1_000_000.0,
        horizons=[1, 2, 5],
    )
    t0 = time.perf_counter()
    try:
        resp: MonteCarloDashboardResponse = svc.run(symbol, req)
        elapsed = time.perf_counter() - t0
        rate = n_sims / elapsed if elapsed > 0 else float("inf")
        results[n_sims] = {
            "ok": True,
            "elapsed": elapsed,
            "rate": rate,
            "available": resp.available,
            "simulation_count": resp.simulation_count,
            "historical_oos_trade_count": resp.historical_oos_trade_count,
            "p_loss": resp.probability_of_loss,
            "p_profit": resp.probability_of_profit,
            "verdict": resp.verdict,
            "sample_quality": resp.sample_quality,
            "trade_source": resp.trade_source,
            "horizon_count": len(resp.horizon_outlook) if resp.horizon_outlook else 0,
            "warnings_count": len(resp.warnings) if resp.warnings else 0,
        }
        log(f"  OK  elapsed={elapsed:.3f}s  rate={rate:,.0f} sims/s")
        log(f"  available={resp.available}  sim_count={resp.simulation_count}  "
            f"hist_trades={resp.historical_oos_trade_count}")
        if resp.available:
            log(f"  verdict={resp.verdict}  quality={resp.sample_quality}")
            log(f"  P(loss)={resp.probability_of_loss:.3f}  "
                f"P(profit)={resp.probability_of_profit:.3f}")
            log(f"  trade_source={resp.trade_source}")
            log(f"  horizon_bands={len(resp.horizon_outlook) if resp.horizon_outlook else 0}")
            log(f"  warnings={len(resp.warnings) if resp.warnings else 0}")
            # Confirm simulation count is SEPARATE from historical trade count
            if resp.simulation_count != resp.historical_oos_trade_count:
                log(f"  [OK] simulation_count({resp.simulation_count}) != "
                    f"historical_oos_trade_count({resp.historical_oos_trade_count})")
            # Confirm disclaimer text in warnings
            if resp.resampling_limitation:
                log(f"  [OK] resampling_limitation present")
        else:
            log(f"  message={resp.message}")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        results[n_sims] = {"ok": False, "elapsed": elapsed, "error": str(e)}
        log(f"  FAIL  elapsed={elapsed:.3f}s  error={type(e).__name__}: {e}")
        import traceback; traceback.print_exc()

# ── summary ────────────────────────────────────────────────────────────────
section("SUMMARY")

all_ok = all(r.get("ok", False) for r in results.values())

log("\nBENCHMARK TABLE:")
log(f"  {'Sims':>8}  {'Time (s)':>10}  {'sims/s':>10}  {'Status':>10}")
for n, r in sorted(results.items()):
    if r.get("ok"):
        log(f"  {n:>8,}  {r['elapsed']:>10.3f}  {r['rate']:>10,.0f}  {'OK' if r.get('available') else 'unavailable':>10}")
    else:
        log(f"  {n:>8,}  {r['elapsed']:>10.3f}  {'—':>10}  {'FAIL':>10}")

log()
log(f"  Integration tests: {'ALL PASSED' if all_ok else 'SOME FAILED'}")

# Validation checks
log()
log("VALIDATION CHECKS:")
for n, r in sorted(results.items()):
    if not r.get("ok"):
        log(f"  [FAIL] n={n}: {r.get('error','unknown error')}")
        continue
    ok_markers = []
    # Simulation count must equal what was requested
    if r.get("simulation_count") == n:
        ok_markers.append("sim_count_correct")
    else:
        ok_markers.append(f"WRONG sim_count={r.get('simulation_count')} expected {n}")
    # Historical trade count must be independent of simulation count
    if r.get("historical_oos_trade_count", -1) != n or not r.get("available"):
        ok_markers.append("hist_trades_independent")
    else:
        ok_markers.append("WARN hist_trades==sim_count (coincidence or unavailable)")
    # Probabilities in [0,1]
    p_loss = r.get("p_loss")
    p_profit = r.get("p_profit")
    if p_loss is not None and p_profit is not None:
        if 0.0 <= p_loss <= 1.0 and 0.0 <= p_profit <= 1.0:
            ok_markers.append("probabilities_valid")
        else:
            ok_markers.append(f"INVALID p_loss={p_loss} p_profit={p_profit}")
    log(f"  [n={n}] " + "  ".join(ok_markers))

OUT.write_text("\n".join(lines), encoding="utf-8")
log(f"\nResults written to {OUT}")
sys.exit(0 if all_ok else 1)
