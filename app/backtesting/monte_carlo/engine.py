"""Monte Carlo engine — resample completed trades, never generate them."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.adapter import trades_from_sources, with_cost_perturbation
from app.backtesting.monte_carlo.robustness import assess_robustness, pick_cases
from app.backtesting.monte_carlo.schemas import (
    PERCENTILE_LEVELS,
    CostSensitivityRow,
    HistoricalSnapshot,
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloTrade,
    PercentileSummary,
    SamplingMethod,
    SimulationSummary,
)
from app.backtesting.monte_carlo.simulation import simulate_equity, trade_level_sharpe
from app.backtesting.monte_carlo.warnings import collect_warnings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MonteCarloEngine:
    """Resample completed-trade P&L. Same input + same seed → same output."""

    def __init__(self, config: MonteCarloConfig | None = None) -> None:
        self._config = config or MonteCarloConfig()

    @property
    def config(self) -> MonteCarloConfig:
        return self._config

    def run(
        self,
        sources: Sequence[object],
        *,
        strategy: str = "",
        symbol: str = "",
        period: str = "",
    ) -> MonteCarloResult:
        original = list(sources)
        trades = trades_from_sources(original)
        result = self._run_trades(trades, strategy=strategy, symbol=symbol, period=period)
        return result

    def sample_indices(self, n: int, *, seed: int | None = None) -> np.ndarray:
        """Public sampler for tests: one simulation's trade indices."""
        rng = np.random.default_rng(self._config.random_seed if seed is None else seed)
        return _sample_indices(rng, n, self._config.sampling_method)

    def _run_trades(
        self,
        trades: list[MonteCarloTrade],
        *,
        strategy: str,
        symbol: str,
        period: str,
    ) -> MonteCarloResult:
        config = self._config
        warnings = collect_warnings(trades, config)
        historical = _historical_snapshot(trades, config.initial_capital)
        if not trades:
            empty = _empty_summary(config.initial_capital)
            robustness = assess_robustness(
                source_trade_count=0,
                probability_of_loss=0.0,
                median_return=0.0,
                p05_return=0.0,
                p95_max_drawdown=0.0,
                p95_losing_streak=0.0,
                cost_rows=[],
            )
            return MonteCarloResult(
                simulations=config.simulations,
                seed=config.random_seed,
                sampling_method=config.sampling_method,
                initial_capital=config.initial_capital,
                source_trade_count=0,
                historical=historical,
                final_capital_percentiles=_zero_percentiles(config.initial_capital),
                return_percentiles=_zero_percentiles(0.0),
                max_drawdown_percentiles=_zero_percentiles(0.0),
                max_drawdown_abs_percentiles=_zero_percentiles(0.0),
                min_equity_percentiles=_zero_percentiles(config.initial_capital),
                longest_losing_streak_percentiles=_zero_percentiles(0.0),
                probability_of_loss=0.0,
                probability_of_profit=0.0,
                probability_of_ruin=0.0,
                ruin_equity=config.ruin_equity,
                ruin_definition=_ruin_definition(config),
                threshold_probabilities={},
                worst_case=empty,
                best_case=empty,
                median_case=empty,
                robustness=robustness,
                warnings=warnings,
                strategy=strategy,
                symbol=symbol,
                period=period,
                simulation_summaries=[] if config.store_simulation_summaries else None,
            )

        summaries = self._simulate(trades)
        cost_rows: list[CostSensitivityRow] = []
        if config.include_cost_perturbation:
            cost_rows = self._cost_sensitivity(trades)

        arrays = _stack(summaries)
        final_p = _percentiles(arrays["final"])
        return_p = _percentiles(arrays["ret"])
        dd_p = _percentiles(arrays["dd"])
        dd_abs_p = _percentiles(np.abs(arrays["dd"]))
        min_p = _percentiles(arrays["min_eq"])
        streak_p = _percentiles(arrays["lose_streak"])

        p_loss = float(np.mean(arrays["final"] < config.initial_capital))
        p_profit = float(np.mean(arrays["final"] > config.initial_capital))
        p_ruin = float(np.mean(arrays["min_eq"] < config.ruin_equity))
        thresholds = _threshold_probs(arrays, config)

        worst, median, best = pick_cases(summaries)
        robustness = assess_robustness(
            source_trade_count=len(trades),
            probability_of_loss=p_loss,
            median_return=return_p.p50,
            p05_return=return_p.p05,
            p95_max_drawdown=-dd_abs_p.p95,
            p95_losing_streak=streak_p.p95,
            cost_rows=cost_rows,
        )

        logger.info(
            "Monte Carlo %s sims=%s trades=%s seed=%s P(loss)=%.3f band=%s",
            config.sampling_method.value,
            config.simulations,
            len(trades),
            config.random_seed,
            p_loss,
            robustness.band.value,
        )
        return MonteCarloResult(
            simulations=config.simulations,
            seed=config.random_seed,
            sampling_method=config.sampling_method,
            initial_capital=config.initial_capital,
            source_trade_count=len(trades),
            historical=historical,
            final_capital_percentiles=final_p,
            return_percentiles=return_p,
            max_drawdown_percentiles=dd_p,
            max_drawdown_abs_percentiles=dd_abs_p,
            min_equity_percentiles=min_p,
            longest_losing_streak_percentiles=streak_p,
            probability_of_loss=p_loss,
            probability_of_profit=p_profit,
            probability_of_ruin=p_ruin,
            ruin_equity=config.ruin_equity,
            ruin_definition=_ruin_definition(config),
            threshold_probabilities=thresholds,
            worst_case=worst,
            best_case=best,
            median_case=median,
            robustness=robustness,
            cost_sensitivity=cost_rows,
            warnings=warnings,
            strategy=strategy,
            symbol=symbol,
            period=period,
            simulation_summaries=summaries if config.store_simulation_summaries else None,
        )

    def _simulate(self, trades: Sequence[MonteCarloTrade]) -> list[SimulationSummary]:
        pnls = np.asarray([t.pnl for t in trades], dtype=float)
        n = pnls.size
        rng = np.random.default_rng(self._config.random_seed)
        summaries: list[SimulationSummary] = []
        for _ in range(self._config.simulations):
            idx = _sample_indices(rng, n, self._config.sampling_method)
            path = pnls[idx]
            summaries.append(
                simulate_equity(path.tolist(), initial_capital=self._config.initial_capital),
            )
        return summaries

    def _cost_sensitivity(self, trades: Sequence[MonteCarloTrade]) -> list[CostSensitivityRow]:
        rows: list[CostSensitivityRow] = []
        for bps in self._config.slippage_range_bps:
            for mult in self._config.commission_range_mult:
                adjusted = with_cost_perturbation(
                    trades,
                    slippage_bps=float(bps),
                    base_slippage_bps=self._config.base_slippage_bps,
                    commission_mult=float(mult),
                )
                nested = MonteCarloEngine(
                    self._config.model_copy(
                        update={
                            "include_cost_perturbation": False,
                            "store_simulation_summaries": False,
                        },
                    ),
                )
                result = nested._run_trades(adjusted, strategy="", symbol="", period="")
                rows.append(
                    CostSensitivityRow(
                        slippage_bps=float(bps),
                        commission_mult=float(mult),
                        median_return=result.return_percentiles.p50,
                        p95_max_drawdown=-result.max_drawdown_abs_percentiles.p95,
                        probability_of_loss=result.probability_of_loss,
                        probability_of_profit=result.probability_of_profit,
                    ),
                )
        return rows


def _sample_indices(rng: np.random.Generator, n: int, method: SamplingMethod) -> np.ndarray:
    if n <= 0:
        return np.asarray([], dtype=int)
    if method is SamplingMethod.TRADE_SHUFFLE:
        return rng.permutation(n)
    return rng.choice(n, size=n, replace=True)


def _historical_snapshot(trades: Sequence[MonteCarloTrade], initial: float) -> HistoricalSnapshot:
    pnls = [t.pnl for t in trades]
    if not pnls:
        return HistoricalSnapshot()
    summary = simulate_equity(pnls, initial_capital=initial)
    wins = sum(1 for p in pnls if p > 0)
    return HistoricalSnapshot(
        trades=len(pnls),
        return_pct=summary.total_return,
        max_drawdown=summary.max_drawdown,
        sharpe_trade_level=trade_level_sharpe(pnls, initial),
        net_profit=float(sum(pnls)),
        win_rate=wins / len(pnls),
    )


def _stack(summaries: list[SimulationSummary]) -> dict[str, np.ndarray]:
    return {
        "final": np.asarray([s.final_equity for s in summaries], dtype=float),
        "ret": np.asarray([s.total_return for s in summaries], dtype=float),
        "dd": np.asarray([s.max_drawdown for s in summaries], dtype=float),
        "min_eq": np.asarray([s.min_equity for s in summaries], dtype=float),
        "lose_streak": np.asarray([s.longest_losing_streak for s in summaries], dtype=float),
    }


def _percentiles(values: np.ndarray) -> PercentileSummary:
    if values.size == 0:
        return PercentileSummary()
    qs = np.percentile(values, PERCENTILE_LEVELS)
    return PercentileSummary(
        p01=float(qs[0]),
        p05=float(qs[1]),
        p10=float(qs[2]),
        p25=float(qs[3]),
        p50=float(qs[4]),
        p75=float(qs[5]),
        p90=float(qs[6]),
        p95=float(qs[7]),
        p99=float(qs[8]),
    )


def _zero_percentiles(fill: float) -> PercentileSummary:
    return PercentileSummary(
        p01=fill, p05=fill, p10=fill, p25=fill, p50=fill,
        p75=fill, p90=fill, p95=fill, p99=fill,
    )


def _empty_summary(initial: float) -> SimulationSummary:
    return SimulationSummary(
        final_equity=initial,
        total_return=0.0,
        max_drawdown=0.0,
        min_equity=initial,
        peak_equity=initial,
        losing_trades=0,
        longest_losing_streak=0,
        longest_winning_streak=0,
    )


def _threshold_probs(arrays: dict[str, np.ndarray], config: MonteCarloConfig) -> dict[str, float]:
    out: dict[str, float] = {
        "P(return<0)": float(np.mean(arrays["ret"] < 0.0)),
        "P(final<initial)": float(np.mean(arrays["final"] < config.initial_capital)),
    }
    for thr in config.return_thresholds:
        key = f"P(return>{thr:.0%})"
        out[key] = float(np.mean(arrays["ret"] > thr))
    for thr in config.drawdown_thresholds:
        key = f"P(|maxDD|>{thr:.0%})"
        out[key] = float(np.mean(np.abs(arrays["dd"]) > thr))
    return out


def _ruin_definition(config: MonteCarloConfig) -> str:
    return (
        f"Ruin is defined for this run as any simulated equity path falling below "
        f"₹{config.ruin_equity:,.2f} "
        f"({'{:.0%}'.format(config.ruin_threshold)} of initial capital)"
        if config.ruin_threshold <= 1.0
        else f"Ruin is defined for this run as any simulated equity path falling below ₹{config.ruin_equity:,.2f}"
    )
