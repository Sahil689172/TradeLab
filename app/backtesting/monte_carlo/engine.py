"""Monte Carlo engine — resample completed trades, never generate them.

Architecture (A5.6):

    MonteCarloEngine  (facade)
        └── TradeResamplingMonteCarlo
              ├── shuffle
              ├── bootstrap
              └── block_bootstrap

    PathDependentMonteCarlo  [A5.7 PathDependentPortfolioMonteCarlo]

Trade-resampling randomizes trade *order* (shuffle) or trade *selection*
(bootstrap / block bootstrap). It does not randomize P&L values or position
sizes, and it does not re-run A5.1–A5.3.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.adapter import trades_from_sources, with_cost_perturbation
from app.backtesting.monte_carlo.exceptions import MonteCarloConfigError
from app.backtesting.monte_carlo.robustness import (
    assess_robustness,
    assess_verdict,
    classify_sample_quality,
    pick_cases,
    pick_cases_from_batch,
)
from app.backtesting.monte_carlo.schemas import (
    PERCENTILE_LEVELS,
    PERCENTILE_METHOD,
    RESAMPLING_LIMITATION,
    CapitalMode,
    CostSensitivityRow,
    EngineMode,
    HistoricalSnapshot,
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloTrade,
    MonteCarloVerdict,
    PercentileSummary,
    RiskMetrics,
    RobustnessAssessment,
    SampleQuality,
    SamplingMethod,
    SimulationSummary,
)
from app.backtesting.monte_carlo.risk_metrics import compute_risk_metrics
from app.backtesting.monte_carlo.simulation import (
    simulate_equity,
    simulate_equity_batch,
    summary_from_batch,
    trade_level_sharpe,
)
from app.backtesting.monte_carlo.validation import series_for_mode, validate_config, validate_trades
from app.backtesting.monte_carlo.warnings import collect_warnings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TradeResamplingMonteCarlo:
    """Resample completed-trade P&L or returns. Same input + same seed → same output."""

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
        validate_config(self._config)
        original = list(sources)
        trades = trades_from_sources(original)
        return self._run_trades(trades, strategy=strategy, symbol=symbol, period=period)

    def sample_indices(self, n: int, *, seed: int | None = None) -> np.ndarray:
        """Public sampler for tests: one simulation's trade indices."""
        rng = np.random.default_rng(self._config.random_seed if seed is None else seed)
        return _sample_indices(
            rng,
            n,
            self._config.sampling_method,
            block_size=self._config.block_size,
        )

    def _run_trades(
        self,
        trades: list[MonteCarloTrade],
        *,
        strategy: str,
        symbol: str,
        period: str,
        extra_warnings: list[str] | None = None,
    ) -> MonteCarloResult:
        config = self._config
        validate_config(config)
        validate_trades(trades, capital_mode=config.capital_mode)
        capital_mode, mode_warnings = series_for_mode(trades, capital_mode=config.capital_mode)
        quality = classify_sample_quality(len(trades))
        historical = _historical_snapshot(trades, config.initial_capital, capital_mode)

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
            verdict = MonteCarloVerdict.INSUFFICIENT_EVIDENCE
            warnings = collect_warnings(
                trades,
                config,
                capital_mode=capital_mode,
                sample_quality=quality,
                verdict=verdict,
            )
            warnings.extend(mode_warnings)
            if extra_warnings:
                warnings.extend(extra_warnings)
            return _result(
                config=config,
                capital_mode=capital_mode,
                quality=quality,
                verdict=verdict,
                historical=historical,
                final_p=_zero_percentiles(config.initial_capital),
                return_p=_zero_percentiles(0.0),
                dd_p=_zero_percentiles(0.0),
                dd_abs_p=_zero_percentiles(0.0),
                min_p=_zero_percentiles(config.initial_capital),
                streak_p=_zero_percentiles(0.0),
                p_loss=0.0,
                p_profit=0.0,
                p_ruin=0.0,
                thresholds={},
                worst=empty,
                median=empty,
                best=empty,
                robustness=robustness,
                cost_rows=[],
                warnings=warnings,
                strategy=strategy,
                symbol=symbol,
                period=period,
                summaries=[] if config.store_simulation_summaries else None,
            )

        batch = self._simulate_batch(trades, capital_mode)
        cost_rows: list[CostSensitivityRow] = []
        if config.include_cost_perturbation:
            cost_rows = self._cost_sensitivity(trades, capital_mode)

        final_p = _percentiles(batch["final"])
        return_p = _percentiles(batch["ret"])
        dd_p = _percentiles(batch["dd"])
        dd_abs_p = _percentiles(np.abs(batch["dd"]))
        min_p = _percentiles(batch["min_eq"])
        streak_p = _percentiles(batch["lose_streak"].astype(float))

        p_loss = float(np.mean(batch["final"] < config.initial_capital))
        p_profit = float(np.mean(batch["final"] > config.initial_capital))
        p_ruin = float(np.mean(batch["min_eq"] < config.ruin_equity))
        thresholds = _threshold_probs(batch, config)
        risk_metrics = compute_risk_metrics(
            batch["ret"],
            initial_capital=config.initial_capital,
        )

        summaries: list[SimulationSummary] | None = None
        if config.store_simulation_summaries:
            summaries = [summary_from_batch(batch, i) for i in range(batch["final"].size)]
            worst, median, best = pick_cases(summaries)
        else:
            worst, median, best = pick_cases_from_batch(batch)

        robustness = assess_robustness(
            source_trade_count=len(trades),
            probability_of_loss=p_loss,
            median_return=return_p.p50,
            p05_return=return_p.p05,
            p95_max_drawdown=-dd_abs_p.p95,
            p95_losing_streak=streak_p.p95,
            cost_rows=cost_rows,
        )
        verdict = assess_verdict(
            source_trade_count=len(trades),
            probability_of_loss=p_loss,
            median_return=return_p.p50,
            p95_max_drawdown=-dd_abs_p.p95,
            score=robustness.score,
        )
        warnings = collect_warnings(
            trades,
            config,
            capital_mode=capital_mode,
            sample_quality=quality,
            verdict=verdict,
        )
        warnings.extend(mode_warnings)
        if extra_warnings:
            warnings.extend(extra_warnings)
        if config.include_cost_perturbation and all(t.costs <= 0 for t in trades):
            warnings.append(
                "COST_SENSITIVITY_INCOMPLETE: source trades have zero stored "
                "brokerage/slippage. Sensitivity reconstructs costs from notional "
                "when possible; it never subtracts costs from already-netted P&L.",
            )

        logger.info(
            "Monte Carlo %s mode=%s sims=%s trades=%s seed=%s P(loss)=%.3f "
            "quality=%s verdict=%s band=%s",
            config.sampling_method.value,
            capital_mode.value,
            config.simulations,
            len(trades),
            config.random_seed,
            p_loss,
            quality.value,
            verdict.value,
            robustness.band.value,
        )
        return _result(
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
            cost_rows=cost_rows,
            warnings=warnings,
            strategy=strategy,
            symbol=symbol,
            period=period,
            summaries=summaries,
            risk_metrics=risk_metrics,
        )

    def _simulate_batch(
        self,
        trades: Sequence[MonteCarloTrade],
        capital_mode: CapitalMode,
    ) -> dict[str, np.ndarray]:
        values = _series(trades, capital_mode)
        n = int(values.size)
        n_sims = self._config.simulations
        rng = np.random.default_rng(self._config.random_seed)
        idx = _sample_index_matrix(
            rng,
            n,
            n_sims,
            self._config.sampling_method,
            block_size=self._config.block_size,
        )
        paths = values[idx]
        return simulate_equity_batch(
            paths,
            initial_capital=self._config.initial_capital,
            capital_mode=capital_mode,
        )

    def _cost_sensitivity(
        self,
        trades: Sequence[MonteCarloTrade],
        capital_mode: CapitalMode,
    ) -> list[CostSensitivityRow]:
        rows: list[CostSensitivityRow] = []
        base_cost = float(sum(t.costs for t in trades))
        for bps in self._config.slippage_range_bps:
            for mult in self._config.commission_range_mult:
                adjusted = with_cost_perturbation(
                    trades,
                    slippage_bps=float(bps),
                    base_slippage_bps=self._config.base_slippage_bps,
                    commission_mult=float(mult),
                )
                nested = TradeResamplingMonteCarlo(
                    self._config.model_copy(
                        update={
                            "include_cost_perturbation": False,
                            "store_simulation_summaries": False,
                            "capital_mode": capital_mode,
                        },
                    ),
                )
                result = nested._run_trades(list(adjusted), strategy="", symbol="", period="")
                scenario_cost = float(sum(t.costs for t in adjusted))
                incremental = scenario_cost - base_cost
                median_pnl = (
                    result.median_case.net_profit
                    if result.median_case is not None
                    else result.final_capital_percentiles.p50 - self._config.initial_capital
                )
                rows.append(
                    CostSensitivityRow(
                        slippage_bps=float(bps),
                        commission_mult=float(mult),
                        median_return=result.return_percentiles.p50,
                        p95_max_drawdown=-result.max_drawdown_abs_percentiles.p95,
                        probability_of_loss=result.probability_of_loss,
                        probability_of_profit=result.probability_of_profit,
                        base_cost=base_cost,
                        scenario_cost=scenario_cost,
                        incremental_cost=incremental,
                        final_simulated_pnl=median_pnl,
                    ),
                )
        return rows


class MonteCarloEngine:
    """Facade. Default is A5.6 TradeResamplingMonteCarlo."""

    def __init__(self, config: MonteCarloConfig | None = None) -> None:
        cfg = config or MonteCarloConfig()
        if cfg.engine_mode is EngineMode.PATH_DEPENDENT:
            from app.backtesting.monte_carlo.path_dependent import PathDependentMonteCarlo

            self._impl = PathDependentMonteCarlo(cfg)
        else:
            self._impl = TradeResamplingMonteCarlo(cfg)

    @property
    def config(self) -> MonteCarloConfig:
        return self._impl.config

    def run(
        self,
        sources: Sequence[object],
        *,
        strategy: str = "",
        symbol: str = "",
        period: str = "",
    ) -> MonteCarloResult:
        return self._impl.run(sources, strategy=strategy, symbol=symbol, period=period)

    def sample_indices(self, n: int, *, seed: int | None = None) -> np.ndarray:
        return self._impl.sample_indices(n, seed=seed)


def _series(trades: Sequence[MonteCarloTrade], capital_mode: CapitalMode) -> np.ndarray:
    if capital_mode is CapitalMode.RETURN_BASED:
        return np.asarray([t.return_pct for t in trades], dtype=float)
    return np.asarray([t.pnl for t in trades], dtype=float)


def _sample_indices(
    rng: np.random.Generator,
    n: int,
    method: SamplingMethod,
    block_size: int = 5,
) -> np.ndarray:
    if n <= 0:
        return np.asarray([], dtype=int)
    if method is SamplingMethod.TRADE_SHUFFLE:
        return rng.permutation(n)
    if method is SamplingMethod.BOOTSTRAP:
        return rng.choice(n, size=n, replace=True)
    if method is SamplingMethod.BLOCK_BOOTSTRAP:
        return _block_bootstrap_matrix(rng, n, 1, block_size)[0]
    raise MonteCarloConfigError(f"unsupported sampling method: {method}")


def _sample_index_matrix(
    rng: np.random.Generator,
    n: int,
    n_sims: int,
    method: SamplingMethod,
    block_size: int = 5,
) -> np.ndarray:
    if n <= 0:
        return np.zeros((n_sims, 0), dtype=np.int64)
    if method is SamplingMethod.TRADE_SHUFFLE:
        base = np.broadcast_to(np.arange(n, dtype=np.int64), (n_sims, n)).copy()
        return rng.permuted(base, axis=1)
    if method is SamplingMethod.BOOTSTRAP:
        return rng.choice(n, size=(n_sims, n), replace=True)
    if method is SamplingMethod.BLOCK_BOOTSTRAP:
        return _block_bootstrap_matrix(rng, n, n_sims, block_size)
    raise MonteCarloConfigError(f"unsupported sampling method: {method}")


def _block_bootstrap_matrix(
    rng: np.random.Generator,
    n: int,
    n_sims: int,
    block_size: int,
) -> np.ndarray:
    """Overlapping circular blocks, concatenated and truncated to n trades."""
    block = max(1, min(int(block_size), n))
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_sims, n_blocks), dtype=np.int64)
    offsets = np.arange(block, dtype=np.int64)
    idx = (starts[..., None] + offsets) % n
    flat = idx.reshape(n_sims, n_blocks * block)
    return flat[:, :n]


def _historical_snapshot(
    trades: Sequence[MonteCarloTrade],
    initial: float,
    capital_mode: CapitalMode,
) -> HistoricalSnapshot:
    values = _series(trades, capital_mode).tolist()
    if not values:
        return HistoricalSnapshot()
    summary = simulate_equity(values, initial_capital=initial, capital_mode=capital_mode)
    pnls = [t.pnl for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    return HistoricalSnapshot(
        trades=len(pnls),
        return_pct=summary.total_return,
        max_drawdown=summary.max_drawdown,
        sharpe_trade_level=trade_level_sharpe(pnls, initial),
        net_profit=float(sum(pnls)),
        win_rate=wins / len(pnls),
    )


def _percentiles(values: np.ndarray) -> PercentileSummary:
    if values.size == 0:
        return PercentileSummary()
    qs = np.percentile(values, PERCENTILE_LEVELS, method="linear")
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
        net_profit=0.0,
        max_drawdown_pct=0.0,
        volatility=0.0,
        sharpe=0.0,
    )


def _threshold_probs(batch: dict[str, np.ndarray], config: MonteCarloConfig) -> dict[str, float]:
    out: dict[str, float] = {
        "P(return<0)": float(np.mean(batch["ret"] < 0.0)),
        "P(final<initial)": float(np.mean(batch["final"] < config.initial_capital)),
    }
    for thr in config.return_thresholds:
        key = f"P(return>{thr:.0%})"
        out[key] = float(np.mean(batch["ret"] > thr))
    for thr in config.drawdown_thresholds:
        key = f"P(|maxDD|>{thr:.0%})"
        out[key] = float(np.mean(np.abs(batch["dd"]) > thr))
    return out


def _ruin_definition(config: MonteCarloConfig) -> str:
    if config.ruin_threshold <= 1.0:
        return (
            f"Ruin is defined for this run as any simulated equity path falling below "
            f"₹{config.ruin_equity:,.2f} "
            f"({'{:.0%}'.format(config.ruin_threshold)} of initial capital). "
            "This is a configured floor, not a universal industry constant."
        )
    return (
        f"Ruin is defined for this run as any simulated equity path falling below "
        f"₹{config.ruin_equity:,.2f}. This is a configured floor, not a universal industry constant."
    )


def _result(
    *,
    config: MonteCarloConfig,
    capital_mode: CapitalMode,
    quality: SampleQuality,
    verdict: MonteCarloVerdict,
    historical: HistoricalSnapshot,
    final_p: PercentileSummary,
    return_p: PercentileSummary,
    dd_p: PercentileSummary,
    dd_abs_p: PercentileSummary,
    min_p: PercentileSummary,
    streak_p: PercentileSummary,
    p_loss: float,
    p_profit: float,
    p_ruin: float,
    thresholds: dict[str, float],
    worst: SimulationSummary | None,
    median: SimulationSummary | None,
    best: SimulationSummary | None,
    robustness: RobustnessAssessment,
    cost_rows: list[CostSensitivityRow],
    warnings: list[str],
    strategy: str,
    symbol: str,
    period: str,
    summaries: list[SimulationSummary] | None,
    risk_metrics: RiskMetrics | None = None,
) -> MonteCarloResult:
    block_size = (
        config.block_size
        if config.sampling_method is SamplingMethod.BLOCK_BOOTSTRAP
        else None
    )
    return MonteCarloResult(
        simulations=config.simulations,
        seed=config.random_seed,
        sampling_method=config.sampling_method,
        capital_mode=capital_mode,
        capital_model=capital_mode.value,
        engine_kind="TradeResamplingMonteCarlo",
        block_size=block_size,
        initial_capital=config.initial_capital,
        source_trade_count=historical.trades,
        sample_quality=quality,
        verdict=verdict,
        resampling_limitation=RESAMPLING_LIMITATION,
        percentile_method=PERCENTILE_METHOD,
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
        simulation_summaries=summaries,
        risk_metrics=risk_metrics,
    )


# Imported by tests and by PathDependentMonteCarlo consumers.
__all__ = [
    "MonteCarloEngine",
    "TradeResamplingMonteCarlo",
    "_percentiles",
    "_sample_index_matrix",
    "_sample_indices",
]
