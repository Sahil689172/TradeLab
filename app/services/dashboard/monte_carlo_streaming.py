"""Monte Carlo SSE streaming service.

Runs the simulation in batches and yields JSON-encoded Server-Sent Events:

  event: progress
  data: {"completed": 4000, "total": 10000, "pct": 40.0, "elapsed": 3.2,
          "status": "running", "sample_paths": [...], "partial_stats": {...}}

  event: result
  data: <MonteCarloDashboardResponse JSON>

  event: error
  data: {"message": "..."}

Design:
- Trades are loaded once, then the simulation matrix is built in batches so
  the event loop has a yield point between batches.
- ALL simulations contribute to final statistics (nothing is dropped).
- Only a representative sample of equity paths (SAMPLE_PATH_COUNT) is sent
  to the browser for rendering.
- Each batch also recomputes running percentile snapshots so the partial_stats
  card updates progressively.
- Cancellation is cooperative: the generator checks a threading.Event and
  yields an error event when cancelled.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from collections.abc import AsyncGenerator

import numpy as np

from app.backtesting.monte_carlo.engine import (
    _percentiles,
    _result,
    _historical_snapshot,
    _threshold_probs,
    _series,
    _sample_index_matrix,
)
from app.backtesting.monte_carlo.robustness import (
    assess_robustness,
    assess_verdict,
    classify_sample_quality,
)
from app.backtesting.monte_carlo.schemas import (
    CapitalMode,
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloTrade,
    MonteCarloVerdict,
    RESAMPLING_LIMITATION,
)
from app.backtesting.monte_carlo.risk_metrics import compute_risk_metrics
from app.backtesting.monte_carlo.simulation import simulate_equity_batch
from app.backtesting.monte_carlo.validation import series_for_mode, validate_config, validate_trades
from app.backtesting.monte_carlo.warnings import collect_warnings
from app.services.dashboard.monte_carlo_service import DashboardMonteCarloService
from app.services.dashboard.schemas import (
    MonteCarloDashboardRequest,
    MonteCarloDashboardResponse,
    PercentileBand,
)

# How many representative equity paths to send to the browser.
#
# These are illustrative only -- the chart's real content is the percentile fan
# below.  Rendering thousands of individual polylines is what made the old view
# unusable, so this stays small and, once filled, stops growing: every progress
# event then carries a constant-size payload instead of re-sending an
# ever-larger list.
SAMPLE_PATH_COUNT = 40

# Percentile fan levels sent to the browser for the equity-band chart.
BAND_LEVELS = (10, 25, 50, 75, 90)

# Upper bound on equity cells (paths x steps) retained for computing the fan.
# Scalar statistics (returns, drawdowns, probabilities) are always exact over
# every simulation; only the *drawn* band is derived from a bounded, uniformly
# drawn subset, which keeps memory flat for 100k-simulation runs.
_BAND_CELL_BUDGET = 4_000_000

# Batch size for streaming progress updates (sims processed per yield).
# Smaller = more responsive UI but more CPU overhead.  For 100k sims,
# 5 000 gives 20 updates; for 1 000 sims, minimum clamp gives 5 updates.
_BATCH_TARGET = 5_000
_MIN_BATCHES = 5


def _batch_size(total: int) -> int:
    return max(1, min(_BATCH_TARGET, math.ceil(total / _MIN_BATCHES)))


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _equity_matrix(
    paths: np.ndarray,
    initial_capital: float,
    capital_mode: CapitalMode,
) -> np.ndarray:
    """Equity curves for a batch of resampled trade sequences."""
    if capital_mode is CapitalMode.ADDITIVE_PNL:
        equity = initial_capital + np.cumsum(paths, axis=1)
    else:
        equity = initial_capital * np.cumprod(np.maximum(1.0 + paths, 0.0), axis=1)
    start = np.full((equity.shape[0], 1), float(initial_capital))
    return np.concatenate([start, equity], axis=1)


def _percentile_bands(equity: np.ndarray) -> dict:
    """Percentile fan across simulations, one value per step.

    Returns a compact payload (len(BAND_LEVELS) arrays of n_steps floats)
    instead of the full path set, so the browser draws a handful of polygons
    rather than one polyline per simulation.
    """
    if equity.size == 0:
        return {}
    levels = np.percentile(equity, BAND_LEVELS, axis=0)
    return {
        "steps": list(range(equity.shape[1])),
        "paths_used": int(equity.shape[0]),
        **{
            f"p{level}": [round(float(v), 2) for v in levels[i]]
            for i, level in enumerate(BAND_LEVELS)
        },
    }


def _partial_stats(
    ret: np.ndarray,
    dd_abs: np.ndarray,
    initial: float,
) -> dict:
    """Compact stats from the completed-so-far portion of the batch."""
    if ret.size == 0:
        return {}
    p_loss = float(np.mean(ret < 0))
    p_profit = float(np.mean(ret > 0))
    median_ret = float(np.median(ret))
    p05 = float(np.percentile(ret, 5))
    p95 = float(np.percentile(ret, 95))
    med_dd = float(np.median(dd_abs))
    return {
        "probability_of_loss": round(p_loss, 4),
        "probability_of_profit": round(p_profit, 4),
        "median_return_pct": round(median_ret, 6),
        "return_p05": round(p05, 6),
        "return_p95": round(p95, 6),
        "median_drawdown": round(med_dd, 6),
    }


def _sample_equity_paths(
    trades_values: np.ndarray,
    initial_capital: float,
    capital_mode: CapitalMode,
    rng: np.random.Generator,
    n_sim: int,
    n_sample: int,
) -> list[list[float]]:
    """Draw n_sample equity paths from n_sim simulations (deterministic subset).
    Not used in the main loop — kept as a utility for external callers.
    """
    from app.backtesting.monte_carlo.schemas import SamplingMethod

    sample = min(n_sample, n_sim)
    if sample <= 0 or trades_values.size == 0:
        return []
    idx = _sample_index_matrix(
        rng,
        int(trades_values.size),
        sample,
        SamplingMethod.BOOTSTRAP,
    )
    if idx.size == 0:
        return []
    paths_matrix = trades_values[idx]
    if capital_mode is CapitalMode.ADDITIVE_PNL:
        equity = initial_capital + np.cumsum(paths_matrix, axis=1)
    else:
        growth = np.cumprod(np.maximum(1.0 + paths_matrix, 0.0), axis=1)
        equity = initial_capital * growth
    return [[round(float(v), 2) for v in equity[i]] for i in range(sample)]


class MonteCarloStreamingService:
    """Streaming facade over the existing Monte Carlo engine.

    Usage::

        service = MonteCarloStreamingService()
        cancel_event = threading.Event()
        async for chunk in service.stream(symbol, request, cancel_event):
            yield chunk          # forward as SSE to the browser
    """

    def __init__(self, base: DashboardMonteCarloService | None = None) -> None:
        self._base = base or DashboardMonteCarloService()

    async def stream(
        self,
        symbol: str,
        request: MonteCarloDashboardRequest,
        cancel_event: threading.Event,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE text chunks.  Never raises; errors are emitted as events."""
        started = time.monotonic()

        # ── Phase 1: load trades (blocking, done once) ───────────────────────
        try:
            trades, trade_source, period, extra_warnings = await asyncio.to_thread(
                self._base._load_trades, symbol, request
            )
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})
            return

        if cancel_event.is_set():
            yield _sse("error", {"message": "Cancelled"})
            return

        n_total = request.simulations
        # ── Phase 2: validate + prepare ──────────────────────────────────────
        try:
            config = MonteCarloConfig(
                simulations=n_total,
                initial_capital=request.initial_capital,
                random_seed=request.random_seed,
            )
            validate_config(config)
            validate_trades(trades, capital_mode=config.capital_mode)
            capital_mode, mode_warnings = series_for_mode(
                trades, capital_mode=config.capital_mode
            )
            quality = classify_sample_quality(len(trades))
            historical = _historical_snapshot(
                trades, config.initial_capital, capital_mode
            )
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"Setup error: {exc}"})
            return

        if not trades:
            # No trades — stream the unavailable response directly.
            resp = MonteCarloDashboardResponse(
                symbol=symbol.upper(),
                strategy=request.strategy,
                trade_source=trade_source,
                historical_oos_trade_count=0,
                simulation_count=0,
                available=False,
                message="Insufficient completed trades for Monte Carlo.",
                warnings=extra_warnings,
            )
            yield _sse("result", resp.model_dump(mode="json"))
            return

        values = _series(trades, capital_mode)
        n_trades = int(values.size)
        batch_sz = _batch_size(n_total)
        rng = np.random.default_rng(config.random_seed)

        # Pre-allocate accumulators for the full run.
        all_final = np.empty(n_total, dtype=np.float64)
        all_ret = np.empty(n_total, dtype=np.float64)
        all_dd = np.empty(n_total, dtype=np.float64)
        all_dd_abs = np.empty(n_total, dtype=np.float64)
        all_min_eq = np.empty(n_total, dtype=np.float64)
        all_peak = np.empty(n_total, dtype=np.float64)
        all_lose_streak = np.empty(n_total, dtype=np.int32)
        all_win_streak = np.empty(n_total, dtype=np.int32)
        all_losing = np.empty(n_total, dtype=np.int32)
        all_net_profit = np.empty(n_total, dtype=np.float64)
        all_vol = np.empty(n_total, dtype=np.float64)
        all_sharpe = np.empty(n_total, dtype=np.float64)

        # Sample paths buffer: gather a few representative paths per batch.
        paths_per_batch = max(1, SAMPLE_PATH_COUNT // max(1, (n_total // batch_sz)))
        sample_paths_acc: list[list[float]] = []

        # Bounded reservoir of equity curves backing the percentile fan.
        n_steps = n_trades + 1
        band_capacity = max(1, min(n_total, _BAND_CELL_BUDGET // max(1, n_steps)))
        band_reservoir = np.empty((band_capacity, n_steps), dtype=np.float64)
        band_filled = 0

        completed = 0
        while completed < n_total:
            if cancel_event.is_set():
                yield _sse("error", {"message": "Cancelled"})
                return

            this_batch = min(batch_sz, n_total - completed)

            # The simulation itself is pure CPU work.  Running it inline on the
            # event loop stalled every other request for the duration of the
            # batch (`await asyncio.sleep(0)` between batches only yields once
            # the batch has already finished), so it goes to a worker thread --
            # NumPy releases the GIL for these bulk operations.
            def _run_batch(size: int = this_batch) -> tuple[np.ndarray, dict]:
                idx = _sample_index_matrix(
                    rng, n_trades, size, config.sampling_method,
                    block_size=config.block_size,
                )
                batch_paths = values[idx]  # (size, n_trades)
                return batch_paths, simulate_equity_batch(
                    batch_paths,
                    initial_capital=config.initial_capital,
                    capital_mode=capital_mode,
                )

            batch_paths, batch = await asyncio.to_thread(_run_batch)

            sl = slice(completed, completed + this_batch)
            all_final[sl] = batch["final"]
            all_ret[sl] = batch["ret"]
            all_dd[sl] = batch["dd"]
            all_dd_abs[sl] = np.abs(batch["dd"])
            all_min_eq[sl] = batch["min_eq"]
            all_peak[sl] = batch["peak"]
            all_lose_streak[sl] = batch["lose_streak"]
            all_win_streak[sl] = batch["win_streak"]
            all_losing[sl] = batch["losing"]
            all_net_profit[sl] = batch["net_profit"]
            all_vol[sl] = batch["vol"]
            all_sharpe[sl] = batch["sharpe"]

            # Equity curves for this batch, used for both the fan reservoir and
            # the small illustrative sample.
            batch_equity = _equity_matrix(
                batch_paths, config.initial_capital, capital_mode,
            )

            # Fill the bounded reservoir backing the percentile fan.
            if band_filled < band_capacity:
                take = min(band_capacity - band_filled, batch_equity.shape[0])
                band_reservoir[band_filled:band_filled + take] = batch_equity[:take]
                band_filled += take

            # Collect sample equity paths until full, then stop growing so the
            # per-event payload stays constant instead of compounding.
            to_take = min(paths_per_batch, this_batch)
            if to_take > 0 and len(sample_paths_acc) < SAMPLE_PATH_COUNT:
                room = SAMPLE_PATH_COUNT - len(sample_paths_acc)
                # Column 0 is the seeded initial capital, which the fan needs as
                # a common origin but sample paths have never included.
                for row in batch_equity[:min(to_take, room), 1:]:
                    sample_paths_acc.append([round(float(v), 2) for v in row])

            completed += this_batch
            elapsed = round(time.monotonic() - started, 2)
            pct = round(completed / n_total * 100, 1)
            # Real remaining-time estimate from observed throughput so far.
            rate = completed / elapsed if elapsed > 0 else 0.0
            eta = round((n_total - completed) / rate, 2) if rate > 0 else None

            partial = _partial_stats(
                all_ret[:completed], all_dd_abs[:completed], config.initial_capital
            )
            progress_payload: dict = {
                "completed": completed,
                "total": n_total,
                "pct": pct,
                "elapsed": elapsed,
                "eta_seconds": eta,
                "status": "running",
                "partial_stats": partial,
                # Primary visualization: a handful of percentile curves rather
                # than one polyline per simulation.
                "bands": _percentile_bands(band_reservoir[:band_filled]),
                "sample_paths": sample_paths_acc,
            }
            yield _sse("progress", progress_payload)
            # Yield control to the event loop between batches.
            await asyncio.sleep(0)

        # ── Phase 3: finalise results from accumulated arrays ─────────────────
        if cancel_event.is_set():
            yield _sse("error", {"message": "Cancelled"})
            return

        full_batch = {
            "final": all_final,
            "ret": all_ret,
            "dd": all_dd,
            "min_eq": all_min_eq,
            "peak": all_peak,
            "lose_streak": all_lose_streak,
            "win_streak": all_win_streak,
            "losing": all_losing,
            "net_profit": all_net_profit,
            "vol": all_vol,
            "sharpe": all_sharpe,
        }
        try:
            final_response = await asyncio.to_thread(
                self._finalise,
                symbol,
                request,
                config,
                capital_mode,
                quality,
                historical,
                trades,
                full_batch,
                all_dd_abs,
                extra_warnings,
                mode_warnings,
                trade_source,
                period,
                sample_paths_acc,
            )
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"Finalisation error: {exc}"})
            return

        elapsed_total = round(time.monotonic() - started, 2)
        final_bands = _percentile_bands(band_reservoir[:band_filled])
        # Final progress event (100%).
        yield _sse("progress", {
            "completed": n_total,
            "total": n_total,
            "pct": 100.0,
            "elapsed": elapsed_total,
            "eta_seconds": 0.0,
            "status": "complete",
            "partial_stats": _partial_stats(all_ret, all_dd_abs, config.initial_capital),
            "bands": final_bands,
            "sample_paths": sample_paths_acc,
        })
        await asyncio.sleep(0)

        payload = final_response.model_dump(mode="json")
        payload["_sample_paths"] = sample_paths_acc
        payload["_bands"] = final_bands
        payload["_elapsed"] = elapsed_total
        yield _sse("result", payload)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _finalise(
        self,
        symbol: str,
        request: MonteCarloDashboardRequest,
        config: MonteCarloConfig,
        capital_mode: CapitalMode,
        quality,
        historical,
        trades: list[MonteCarloTrade],
        batch: dict,
        dd_abs: np.ndarray,
        extra_warnings: list[str],
        mode_warnings: list[str],
        trade_source: str,
        period: str,
        sample_paths: list[list[float]],
    ) -> MonteCarloDashboardResponse:
        from app.backtesting.monte_carlo.robustness import (
            assess_robustness,
            assess_verdict,
            pick_cases_from_batch,
        )

        final_p = _percentiles(batch["final"])
        return_p = _percentiles(batch["ret"])
        dd_p = _percentiles(batch["dd"])
        dd_abs_p = _percentiles(dd_abs)
        min_p = _percentiles(batch["min_eq"])
        streak_p = _percentiles(batch["lose_streak"].astype(float))

        p_loss = float(np.mean(batch["final"] < config.initial_capital))
        p_profit = float(np.mean(batch["final"] > config.initial_capital))
        p_ruin = float(np.mean(batch["min_eq"] < config.ruin_equity))
        thresholds = _threshold_probs(batch, config)
        risk_metrics = compute_risk_metrics(batch["ret"], initial_capital=config.initial_capital)

        worst, median, best = pick_cases_from_batch(batch)
        robustness = assess_robustness(
            source_trade_count=len(trades),
            probability_of_loss=p_loss,
            median_return=return_p.p50,
            p05_return=return_p.p05,
            p95_max_drawdown=-dd_abs_p.p95,
            p95_losing_streak=streak_p.p95,
            cost_rows=[],
        )
        verdict = assess_verdict(
            source_trade_count=len(trades),
            probability_of_loss=p_loss,
            median_return=return_p.p50,
            p95_max_drawdown=-dd_abs_p.p95,
            score=robustness.score,
        )
        warnings = collect_warnings(
            trades, config, capital_mode=capital_mode,
            sample_quality=quality, verdict=verdict,
        )
        warnings.extend(mode_warnings)
        warnings.extend(extra_warnings)
        warnings.append(
            f"{config.simulations:,} simulations resampled from "
            f"{historical.trades} historical completed trades. "
            "Simulation count does not increase sample size.",
        )

        mc_result = _result(
            config=config,
            capital_mode=capital_mode,
            quality=quality,
            verdict=verdict,
            historical=historical,
            final_p=final_p,
            return_p=return_p,
            dd_p=dd_p,
            dd_abs_p=dd_abs_p,
            min_p=min_p,
            streak_p=streak_p,
            p_loss=p_loss,
            p_profit=p_profit,
            p_ruin=p_ruin,
            thresholds=thresholds,
            worst=worst,
            median=median,
            best=best,
            robustness=robustness,
            cost_rows=[],
            warnings=warnings,
            strategy=request.strategy,
            symbol=symbol.upper(),
            period=period,
            summaries=None,
            risk_metrics=risk_metrics,
        )

        # Horizon bands (bootstrapped from daily returns).
        from pathlib import Path
        import pandas as pd
        from app.services.dashboard.horizon_outlook import (
            compute_horizon_bands, daily_returns_from_frame,
        )
        from app.services.dashboard.schemas import HorizonOutlook
        from app.market_data.utils.symbols import parquet_basename
        from app.core.config import get_settings

        settings = get_settings()
        base = parquet_basename(symbol).upper()
        parquet = Path(settings.parquet_storage_dir) / f"{base}.parquet"
        current_price = 0.0
        daily_return_count = 0
        horizon_rows: list[HorizonOutlook] = []
        if parquet.exists():
            try:
                frame = pd.read_parquet(parquet)
                daily_returns = daily_returns_from_frame(frame)
                daily_return_count = len(daily_returns)
                closes = frame.sort_values("date")["close"].astype(float)
                current_price = float(closes.iloc[-1]) if not closes.empty else 0.0
                horizons = sorted({int(h) for h in request.horizons if int(h) > 0}) or [1, 2, 5]
                for band in compute_horizon_bands(
                    daily_returns,
                    current_price=current_price,
                    horizons=horizons,
                    simulations=min(request.simulations, 2_000),
                    random_seed=request.random_seed,
                ):
                    horizon_rows.append(
                        HorizonOutlook(
                            trading_days=band.trading_days,
                            label=band.label,
                            supported=band.supported,
                            message=band.message,
                            mean_price=band.mean_price,
                            median_price=band.median_price,
                            lower_price=band.lower_price,
                            upper_price=band.upper_price,
                            expected_return_pct=band.expected_return_pct,
                            lower_return_pct=band.lower_return_pct,
                            upper_return_pct=band.upper_return_pct,
                            probability_negative_return=band.probability_negative_return,
                            method=band.method,
                        )
                    )
            except Exception:  # noqa: BLE001
                pass

        # Build next-day outlook.
        outlook = self._base._next_day_outlook(
            mc_result, symbol.upper(), request.strategy, trade_source
        )

        return MonteCarloDashboardResponse(
            symbol=symbol.upper(),
            strategy=request.strategy,
            trade_source=trade_source,
            historical_oos_trade_count=mc_result.source_trade_count,
            simulation_count=mc_result.simulations,
            available=True,
            message="Monte Carlo complete",
            sample_quality=mc_result.sample_quality.value,
            verdict=mc_result.verdict.value,
            probability_of_loss=mc_result.probability_of_loss,
            probability_of_profit=mc_result.probability_of_profit,
            probability_of_ruin=mc_result.probability_of_ruin,
            median_return_pct=mc_result.return_percentiles.p50,
            return_percentiles=PercentileBand.from_summary(mc_result.return_percentiles),
            max_drawdown_percentiles=PercentileBand.from_summary(
                mc_result.max_drawdown_abs_percentiles
            ),
            final_capital_percentiles=PercentileBand.from_summary(
                mc_result.final_capital_percentiles
            ),
            historical_return_pct=mc_result.historical.return_pct,
            historical_trades=mc_result.historical.trades,
            historical_win_rate=mc_result.historical.win_rate,
            period=period or mc_result.period,
            timeframe=request.timeframe,
            next_day_outlook=outlook,
            current_price=current_price if current_price > 0 else None,
            historical_daily_return_count=daily_return_count,
            horizon_outlook=horizon_rows,
            warnings=warnings,
            resampling_limitation=RESAMPLING_LIMITATION,
        )


# ── cancellation registry ─────────────────────────────────────────────────────

_cancel_registry: dict[str, threading.Event] = {}
_registry_lock = threading.Lock()


def register_cancel_token(run_id: str) -> threading.Event:
    event = threading.Event()
    with _registry_lock:
        _cancel_registry[run_id] = event
    return event


def cancel_run(run_id: str) -> bool:
    with _registry_lock:
        ev = _cancel_registry.get(run_id)
    if ev is not None:
        ev.set()
        return True
    return False


def unregister_cancel_token(run_id: str) -> None:
    with _registry_lock:
        _cancel_registry.pop(run_id, None)


# Singleton.
_streaming_service: MonteCarloStreamingService | None = None


def get_streaming_service() -> MonteCarloStreamingService:
    global _streaming_service
    if _streaming_service is None:
        _streaming_service = MonteCarloStreamingService()
    return _streaming_service
