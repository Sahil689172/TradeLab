"""Dashboard Monte Carlo — OOS walk-forward or replay trades via existing engines."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np

from app.backtesting.monte_carlo import MonteCarloConfig, MonteCarloEngine
from app.backtesting.monte_carlo.pipeline import load_trades_from_replay
from app.backtesting.monte_carlo.schemas import (
    MonteCarloResult,
    MonteCarloTrade,
    MonteCarloVerdict,
    RESAMPLING_LIMITATION,
)
from app.backtesting.replay_engine.adapters import ParquetFeatureFrameAdapter, ParquetMarketDataAdapter
from app.backtesting.walk_forward import WalkForwardConfig, WalkForwardEngine
from app.core.config import Settings, get_settings
from app.market_data.utils.symbols import parquet_basename
from app.services.dashboard.horizon_outlook import compute_horizon_bands, daily_returns_from_frame
from app.services.dashboard.oos_trade_cache import OOSTradeCache, cache_key
from app.services.dashboard.schemas import (
    HorizonOutlook,
    MonteCarloDashboardRequest,
    MonteCarloDashboardResponse,
    NextDayOutlook,
    PercentileBand,
)
from app.services.trade_recommendation.strategy_validation import STRATEGY_REGISTERARS

_OOS_STRATEGIES = frozenset({"ema_trend", "ema_professional", "ema_trend_professional", "ema"})
# Horizon bands use bootstrap on daily returns; cap keeps large MC requests responsive.
_HORIZON_BOOTSTRAP_CAP = 2_000

# Walk-forward settings used to produce the dashboard's out-of-sample trades.
#
# This deliberately uses the YEAR-based windowing rather than the day-based one.
# generate_windows()'s day path measures spans in CALENDAR days, so the previous
# dashboard setting of train_days=60 asked for ~41 trading bars -- below the EMA
# strategy's own min_history_bars=60.  Every training window was therefore
# structurally unable to evaluate the strategy, and the run still paid for 180
# windows over a 10-year history.
#
# train=2y (~504 bars) clears the warmup requirement with a wide margin while
# still leaving several independent test windows, and test/step=1y keeps the
# windows non-overlapping.  Train/test isolation and the leakage report are
# unchanged -- this only sizes the windows sanely.
_WF_TRAIN_YEARS = 2
_WF_TEST_YEARS = 1
_WF_STEP_YEARS = 1
_WF_FINGERPRINT = f"wf:y{_WF_TRAIN_YEARS}:{_WF_TEST_YEARS}:{_WF_STEP_YEARS}"


class DashboardMonteCarloService:
    """Run existing Monte Carlo on OOS or replay completed trades."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _load_trades(
        self,
        symbol: str,
        request: MonteCarloDashboardRequest,
    ) -> tuple[list[MonteCarloTrade], str, str, list[str]]:
        """Load trades for streaming or sync run. Returns (trades, source, period, warnings)."""
        base = parquet_basename(symbol).upper()
        strategy = request.strategy.strip().lower()
        if strategy not in STRATEGY_REGISTERARS:
            raise ValueError(f"Unknown strategy '{request.strategy}'")

        storage = Path(self._settings.parquet_storage_dir)
        parquet = storage / f"{base}.parquet"
        if not parquet.exists():
            raise ValueError(
                f"No OHLCV history for {base}. Bootstrap or refresh this symbol first.",
            )

        wf_alias = "ema_professional" if strategy in _OOS_STRATEGIES else strategy
        warnings: list[str] = []

        if strategy in _OOS_STRATEGIES:
            trades, trade_source, period, warnings = self._oos_trades(
                base, wf_alias, storage, request,
            )
        else:
            trades, meta = load_trades_from_replay(
                symbols=[base],
                strategy_names=[strategy],
                initial_capital=request.initial_capital,
                storage_dir=storage,
            )
            trade_source = "HISTORICAL REPLAY TRADES"
            period = str(meta.get("period", ""))
            warnings = [
                "Monte Carlo uses completed trades from A5.1 replay + A5.2 execution. "
                "These are not walk-forward OOS trades.",
                RESAMPLING_LIMITATION,
            ]
            if meta.get("replay_errors"):
                warnings.append(f"Replay warnings: {meta['replay_errors']}")

        return trades, trade_source, period, warnings

    def run(self, symbol: str, request: MonteCarloDashboardRequest) -> MonteCarloDashboardResponse:
        trades, trade_source, period, warnings = self._load_trades(symbol, request)
        base = parquet_basename(symbol).upper()
        strategy = request.strategy.strip().lower()
        storage = Path(self._settings.parquet_storage_dir)
        parquet = storage / f"{base}.parquet"

        if not trades:
            return MonteCarloDashboardResponse(
                symbol=base,
                strategy=strategy,
                trade_source=trade_source,
                historical_oos_trade_count=0,
                simulation_count=0,
                available=False,
                message="Insufficient completed trades for Monte Carlo on this symbol/strategy.",
                warnings=warnings,
            )

        mc_config = MonteCarloConfig(
            simulations=request.simulations,
            initial_capital=request.initial_capital,
            random_seed=request.random_seed,
        )
        result: MonteCarloResult = MonteCarloEngine(mc_config).run(
            trades,
            strategy=strategy,
            symbol=base,
            period=period,
        )
        all_warnings = list(warnings) + list(result.warnings)
        all_warnings.append(
            f"{result.simulations:,} simulations resampled from {result.source_trade_count} "
            "historical completed trades. Simulation count does not increase sample size.",
        )
        outlook = self._next_day_outlook(result, base, strategy, trade_source)
        current_price, daily_returns, horizons = self._horizon_inputs(
            parquet,
            request,
        )
        horizon_rows = [
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
            for band in compute_horizon_bands(
                daily_returns,
                current_price=current_price,
                horizons=horizons,
                simulations=min(request.simulations, _HORIZON_BOOTSTRAP_CAP),
                random_seed=request.random_seed,
            )
        ]
        return MonteCarloDashboardResponse(
            symbol=base,
            strategy=strategy,
            trade_source=trade_source,
            historical_oos_trade_count=result.source_trade_count,
            simulation_count=result.simulations,
            available=True,
            message="Monte Carlo complete",
            sample_quality=result.sample_quality.value,
            verdict=result.verdict.value,
            probability_of_loss=result.probability_of_loss,
            probability_of_profit=result.probability_of_profit,
            probability_of_ruin=result.probability_of_ruin,
            median_return_pct=result.return_percentiles.p50,
            return_percentiles=PercentileBand.from_summary(result.return_percentiles),
            max_drawdown_percentiles=PercentileBand.from_summary(result.max_drawdown_abs_percentiles),
            final_capital_percentiles=PercentileBand.from_summary(result.final_capital_percentiles),
            historical_return_pct=result.historical.return_pct,
            historical_trades=result.historical.trades,
            historical_win_rate=result.historical.win_rate,
            period=period or result.period,
            timeframe=request.timeframe,
            next_day_outlook=outlook,
            current_price=current_price if current_price > 0 else None,
            historical_daily_return_count=len(daily_returns),
            horizon_outlook=horizon_rows,
            warnings=all_warnings,
            resampling_limitation=RESAMPLING_LIMITATION,
        )

    def _horizon_inputs(
        self,
        parquet: Path,
        request: MonteCarloDashboardRequest,
    ) -> tuple[float, np.ndarray, list[int]]:
        horizons = sorted({int(h) for h in request.horizons if int(h) > 0}) or [1, 2, 5]
        try:
            frame = pd.read_parquet(parquet)
        except Exception:
            return 0.0, np.array([], dtype=float), horizons
        daily_returns = daily_returns_from_frame(frame)
        closes = frame.sort_values("date")["close"].astype(float)
        current_price = float(closes.iloc[-1]) if not closes.empty else 0.0
        return current_price, daily_returns, horizons

    def _oos_cache(self) -> OOSTradeCache:
        return OOSTradeCache(Path(self._settings.data_root) / "monte_carlo" / "oos_cache")

    def _oos_trades(
        self,
        symbol: str,
        wf_alias: str,
        storage: Path,
        request: MonteCarloDashboardRequest,
    ) -> tuple[list[MonteCarloTrade], str, str, list[str]]:
        """Return completed walk-forward OOS trades, memoized on disk.

        The trade set depends only on the symbol, the strategy, the walk-forward
        settings and the underlying bars -- never on ``simulations`` or
        ``initial_capital`` scaling of the request -- so repeat Monte Carlo runs
        reuse it instead of re-running a multi-minute walk-forward pass.
        """
        from app.backtesting.monte_carlo.adapter import trades_from_sources

        parquet = storage / f"{symbol}.parquet"
        cache = self._oos_cache()
        key = cache_key(
            symbol=symbol,
            strategy_alias=wf_alias,
            # initial_capital scales trade P&L, so it belongs in the identity.
            config_fingerprint=f"{_WF_FINGERPRINT}:cap{request.initial_capital:g}",
            parquet=parquet,
        )

        cached = cache.get(key)
        if cached is not None:
            return (
                list(cached.trades),
                "OUT-OF-SAMPLE MONTE CARLO",
                cached.period,
                self._oos_warnings(
                    cached.trade_count, cached.window_count, from_cache=True,
                ),
            )

        config = WalkForwardConfig(
            train_years=_WF_TRAIN_YEARS,
            test_years=_WF_TEST_YEARS,
            step_years=_WF_STEP_YEARS,
            initial_capital=request.initial_capital,
            strategy_alias=wf_alias,
            include_monte_carlo=False,
            include_charts=False,
            simulations=request.simulations,
            random_seed=request.random_seed,
        )
        market = ParquetMarketDataAdapter(storage)
        features = ParquetFeatureFrameAdapter(storage)
        try:
            wf = WalkForwardEngine(config).run(
                symbols=[symbol],
                market_data=market,
                features=features,
            )
        except Exception as exc:
            warnings = [
                f"Walk-forward OOS unavailable: {exc}",
                "Falling back to historical replay trades for Monte Carlo.",
            ]
            trades, meta = load_trades_from_replay(
                symbols=[symbol],
                strategy_names=[request.strategy.strip().lower()],
                initial_capital=request.initial_capital,
                storage_dir=storage,
            )
            period = str(meta.get("period", ""))
            return trades, "HISTORICAL REPLAY TRADES", period, warnings
        oos = list(wf.oos_trades)
        period = ""
        if oos:
            start = min(t.entry_timestamp for t in oos).date()
            end = max(t.exit_timestamp for t in oos).date()
            period = f"{start.isoformat()} → {end.isoformat()}"
        trades = trades_from_sources(oos)
        cache.put(
            key,
            trades=trades,
            period=period,
            window_count=len(wf.windows),
            strategy_alias=wf_alias,
        )
        return (
            trades,
            "OUT-OF-SAMPLE MONTE CARLO",
            period,
            self._oos_warnings(len(oos), len(wf.windows), from_cache=False),
        )

    @staticmethod
    def _oos_warnings(
        trade_count: int,
        window_count: int,
        *,
        from_cache: bool,
    ) -> list[str]:
        warnings = [
            "OUT-OF-SAMPLE MONTE CARLO: trades are walk-forward test-window completions only.",
            f"historical_oos_trades={trade_count} from {window_count} window(s).",
            RESAMPLING_LIMITATION,
        ]
        if from_cache:
            warnings.append(
                "OOS trades served from cache (invalidated automatically when "
                "this symbol's OHLCV data changes).",
            )
        if trade_count <= 4:
            warnings.append("INSUFFICIENT_EVIDENCE: OOS trade count is very small.")
        return warnings

    def _next_day_outlook(
        self,
        result: MonteCarloResult,
        symbol: str,
        strategy: str,
        trade_source: str,
    ) -> NextDayOutlook:
        """Statistical outlook from resampled trade returns — not a price forecast."""
        median_ret = result.return_percentiles.p50
        p05 = result.return_percentiles.p05
        p95 = result.return_percentiles.p95
        supported = (
            result.source_trade_count >= 1
            and result.verdict is not MonteCarloVerdict.INSUFFICIENT_EVIDENCE
        )
        disclaimer = (
            "Statistical resampling of completed historical trades. "
            "This is NOT a guaranteed next-day price forecast."
        )
        if not supported:
            return NextDayOutlook(
                supported=False,
                disclaimer=disclaimer,
                message="Insufficient OOS/replay trades for a statistical outlook.",
            )
        return NextDayOutlook(
            supported=True,
            disclaimer=disclaimer,
            expected_return_pct=median_ret,
            return_range_low_pct=p05,
            return_range_high_pct=p95,
            probability_of_loss=result.probability_of_loss,
            confidence_label="Monte Carlo resampling (not predictive probability)",
            simulation_count=result.simulations,
            historical_sample_count=result.source_trade_count,
            timeframe="completed-trade resampling",
            trade_source=trade_source,
            symbol=symbol,
            strategy=strategy,
        )


_service: DashboardMonteCarloService | None = None


def get_monte_carlo_service() -> DashboardMonteCarloService:
    global _service
    if _service is None:
        _service = DashboardMonteCarloService()
    return _service
