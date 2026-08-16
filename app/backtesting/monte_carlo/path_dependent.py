"""A5.7 Path-dependent portfolio Monte Carlo.

Resamples historical completed-trade *prices* and reallocates capital from
current cash after every round-trip. Does not replay A5.1 candles or re-run
the strategy. Full market-path Monte Carlo (signal → execution → PM) remains
out of scope.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.adapter import trades_from_sources
from app.backtesting.monte_carlo.engine import (
    _historical_snapshot,
    _percentiles,
    _result,
    _sample_index_matrix,
    _sample_indices,
    _threshold_probs,
    _zero_percentiles,
)
from app.backtesting.monte_carlo.exceptions import MonteCarloConfigError
from app.backtesting.monte_carlo.portfolio import (
    execution_config_from_mc,
    price_arrays,
    simulate_portfolio_batch,
    summary_from_portfolio_batch,
)
from app.backtesting.monte_carlo.robustness import (
    assess_robustness,
    assess_verdict,
    classify_sample_quality,
    pick_cases,
)
from app.backtesting.monte_carlo.schemas import (
    PATH_DEPENDENT_LIMITATION,
    CapitalMode,
    CostSensitivityRow,
    EngineComparison,
    EngineMode,
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloSizingMode,
    MonteCarloTrade,
    MonteCarloVerdict,
    SimulationSummary,
)
from app.backtesting.monte_carlo.simulation import simulate_equity
from app.backtesting.monte_carlo.validation import validate_config, validate_trades
from app.backtesting.monte_carlo.warnings import collect_warnings
from app.backtesting.order_execution.schemas import ExecutionConfig
from app.core.logging import get_logger

logger = get_logger(__name__)

ENGINE_KIND = "PathDependentPortfolioMonteCarlo"


class PathDependentMonteCarlo:
    """A5.7 portfolio Monte Carlo on resampled completed-trade prices."""

    def __init__(self, config: MonteCarloConfig | None = None) -> None:
        self._config = config or MonteCarloConfig(engine_mode=EngineMode.PATH_DEPENDENT)

    @property
    def config(self) -> MonteCarloConfig:
        return self._config

    def run(
        self,
        sources: Sequence[object] | None = None,
        *,
        strategy: str = "",
        symbol: str = "",
        period: str = "",
    ) -> MonteCarloResult:
        config = self._config
        validate_config(config)
        if (
            config.sizing_mode is MonteCarloSizingMode.FIXED_CASH
            and (config.fixed_cash_amount is None or config.fixed_cash_amount <= 0)
        ):
            raise MonteCarloConfigError("fixed_cash sizing requires fixed_cash_amount > 0")
        trades = trades_from_sources(list(sources or []))
        validate_trades(trades, capital_mode=CapitalMode.PATH_DEPENDENT_EQUITY)
        return self._run_trades(trades, strategy=strategy, symbol=symbol, period=period)

    def sample_indices(self, n: int, *, seed: int | None = None) -> np.ndarray:
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
    ) -> MonteCarloResult:
        config = self._config
        quality = classify_sample_quality(len(trades))
        historical = _historical_snapshot(
            trades,
            config.initial_capital,
            CapitalMode.ADDITIVE_PNL,
        )
        exec_cfg = self._execution_config(config.base_slippage_bps, config.brokerage_rate)
        capital_mode = CapitalMode.PATH_DEPENDENT_EQUITY

        if not trades:
            empty = simulate_equity([], initial_capital=config.initial_capital)
            robustness = assess_robustness(
                source_trade_count=0,
                probability_of_loss=0.0,
                median_return=0.0,
                p05_return=0.0,
                p95_max_drawdown=0.0,
                p95_losing_streak=0.0,
                cost_rows=[],
            )
            warnings = collect_warnings(
                trades,
                config,
                capital_mode=capital_mode,
                sample_quality=quality,
                verdict=MonteCarloVerdict.INSUFFICIENT_EVIDENCE,
            )
            return self._pack(
                config=config,
                quality=quality,
                verdict=MonteCarloVerdict.INSUFFICIENT_EVIDENCE,
                historical=historical,
                batch=None,
                cost_rows=[],
                warnings=warnings,
                strategy=strategy,
                symbol=symbol,
                period=period,
                empty=empty,
                comparison=None,
                robustness=robustness,
            )

        entries, exits = price_arrays(trades)
        rng = np.random.default_rng(config.random_seed)
        idx = _sample_index_matrix(
            rng,
            len(trades),
            config.simulations,
            config.sampling_method,
            block_size=config.block_size,
        )
        batch = simulate_portfolio_batch(
            entries,
            exits,
            idx,
            initial_capital=config.initial_capital,
            config=exec_cfg,
            ruin_equity=config.ruin_equity,
        )
        cost_rows: list[CostSensitivityRow] = []
        if config.include_cost_perturbation:
            cost_rows = self._cost_sensitivity(entries, exits, idx)

        return_p = _percentiles(batch["ret"])
        dd_abs = np.abs(batch["dd"])
        robustness = assess_robustness(
            source_trade_count=len(trades),
            probability_of_loss=float(np.mean(batch["final"] < config.initial_capital)),
            median_return=return_p.p50,
            p05_return=return_p.p05,
            p95_max_drawdown=-float(np.percentile(dd_abs, 95, method="linear")),
            p95_losing_streak=float(np.percentile(batch["lose_streak"].astype(float), 95, method="linear")),
            cost_rows=cost_rows,
        )
        p_loss = float(np.mean(batch["final"] < config.initial_capital))
        verdict = assess_verdict(
            source_trade_count=len(trades),
            probability_of_loss=p_loss,
            median_return=return_p.p50,
            p95_max_drawdown=-float(np.percentile(dd_abs, 95, method="linear")),
            score=robustness.score,
        )
        warnings = collect_warnings(
            trades,
            config,
            capital_mode=capital_mode,
            sample_quality=quality,
            verdict=verdict,
        )
        comparison = None
        if config.compare_engines:
            comparison = self._compare_a56(trades, strategy=strategy, symbol=symbol, period=period)

        logger.info(
            "Path-dependent MC sims=%s trades=%s seed=%s sizing=%s P(loss)=%.3f verdict=%s",
            config.simulations,
            len(trades),
            config.random_seed,
            config.sizing_mode.value,
            p_loss,
            verdict.value,
        )
        return self._pack(
            config=config,
            quality=quality,
            verdict=verdict,
            historical=historical,
            batch=batch,
            cost_rows=cost_rows,
            warnings=warnings,
            strategy=strategy,
            symbol=symbol,
            period=period,
            empty=None,
            comparison=comparison,
            robustness=robustness,
        )

    def _execution_config(self, slippage_bps: float, brokerage_rate: float) -> ExecutionConfig:
        cfg = self._config
        return execution_config_from_mc(
            initial_capital=cfg.initial_capital,
            sizing_mode=cfg.sizing_mode,
            position_percent=cfg.position_percent,
            fixed_cash_amount=cfg.fixed_cash_amount,
            slippage_bps=slippage_bps,
            brokerage_rate=brokerage_rate,
            brokerage_flat=cfg.brokerage_flat,
            allow_fractional_shares=cfg.allow_fractional_shares,
            min_quantity=cfg.min_quantity,
        )

    def _cost_sensitivity(
        self,
        entries: np.ndarray,
        exits: np.ndarray,
        idx: np.ndarray,
    ) -> list[CostSensitivityRow]:
        config = self._config
        rows: list[CostSensitivityRow] = []
        for bps in config.slippage_range_bps:
            for mult in config.commission_range_mult:
                rate = config.brokerage_rate * float(mult)
                exec_cfg = self._execution_config(float(bps), rate)
                batch = simulate_portfolio_batch(
                    entries,
                    exits,
                    idx,
                    initial_capital=config.initial_capital,
                    config=exec_cfg,
                    ruin_equity=config.ruin_equity,
                )
                broker = float(np.median(batch["total_brokerage_cost"]))
                slip = float(np.median(batch["total_slippage_cost"]))
                total = float(np.median(batch["total_cost"]))
                rows.append(
                    CostSensitivityRow(
                        slippage_bps=float(bps),
                        commission_mult=float(mult),
                        median_return=float(np.median(batch["ret"])),
                        p95_max_drawdown=-float(np.percentile(np.abs(batch["dd"]), 95, method="linear")),
                        probability_of_loss=float(np.mean(batch["final"] < config.initial_capital)),
                        probability_of_profit=float(np.mean(batch["final"] > config.initial_capital)),
                        base_cost=0.0,
                        scenario_cost=total,
                        incremental_cost=0.0,
                        final_simulated_pnl=float(np.median(batch["net_profit"])),
                        brokerage_cost=broker,
                        slippage_cost=slip,
                        total_execution_cost=total,
                        median_ending_equity=float(np.median(batch["final"])),
                    ),
                )
        baseline = _baseline_cost(rows, config.base_slippage_bps)
        out: list[CostSensitivityRow] = []
        for row in rows:
            out.append(
                row.model_copy(
                    update={
                        "base_cost": baseline,
                        "incremental_cost": row.total_execution_cost - baseline,
                    },
                ),
            )
        return out

    def _compare_a56(
        self,
        trades: list[MonteCarloTrade],
        *,
        strategy: str,
        symbol: str,
        period: str,
    ) -> EngineComparison:
        from app.backtesting.monte_carlo.engine import TradeResamplingMonteCarlo

        a56 = TradeResamplingMonteCarlo(
            self._config.model_copy(
                update={
                    "engine_mode": EngineMode.TRADE_RESAMPLING,
                    "compare_engines": False,
                    "include_cost_perturbation": False,
                    "capital_mode": CapitalMode.ADDITIVE_PNL,
                    "store_simulation_summaries": False,
                },
            ),
        )
        other = a56.run(trades, strategy=strategy, symbol=symbol, period=period)
        return EngineComparison(
            resampling_median_return=other.return_percentiles.p50,
            resampling_p95_max_drawdown=-other.max_drawdown_abs_percentiles.p95,
            resampling_probability_of_loss=other.probability_of_loss,
        )

    def _pack(
        self,
        *,
        config: MonteCarloConfig,
        quality,
        verdict: MonteCarloVerdict,
        historical,
        batch: dict[str, np.ndarray] | None,
        cost_rows: list[CostSensitivityRow],
        warnings: list[str],
        strategy: str,
        symbol: str,
        period: str,
        empty: SimulationSummary | None,
        comparison: EngineComparison | None,
        robustness=None,
    ) -> MonteCarloResult:
        if batch is None:
            initial = config.initial_capital
            result = _result(
                config=config,
                capital_mode=CapitalMode.PATH_DEPENDENT_EQUITY,
                quality=quality,
                verdict=verdict,
                historical=historical,
                final_p=_zero_percentiles(initial),
                return_p=_zero_percentiles(0.0),
                dd_p=_zero_percentiles(0.0),
                dd_abs_p=_zero_percentiles(0.0),
                min_p=_zero_percentiles(initial),
                streak_p=_zero_percentiles(0.0),
                p_loss=0.0,
                p_profit=0.0,
                p_ruin=0.0,
                thresholds={},
                worst=empty,
                median=empty,
                best=empty,
                robustness=robustness,
                cost_rows=cost_rows,
                warnings=warnings,
                strategy=strategy,
                symbol=symbol,
                period=period,
                summaries=[] if config.store_simulation_summaries else None,
            )
            return _with_a57_fields(result, config, comparison, PATH_DEPENDENT_LIMITATION)

        p_loss = float(np.mean(batch["final"] < config.initial_capital))
        p_profit = float(np.mean(batch["final"] > config.initial_capital))
        p_ruin = float(np.mean(batch["min_eq"] < config.ruin_equity))
        summaries: list[SimulationSummary] | None = None
        n = batch["final"].size
        if config.store_simulation_summaries:
            summaries = [summary_from_portfolio_batch(batch, i) for i in range(n)]
            worst, median, best = pick_cases(summaries)
        else:
            order = np.argsort(batch["final"], kind="mergesort")
            worst = summary_from_portfolio_batch(batch, int(order[0]))
            best = summary_from_portfolio_batch(batch, int(order[-1]))
            median = summary_from_portfolio_batch(batch, int(order[n // 2]))

        if robustness is None:
            robustness = assess_robustness(
                source_trade_count=historical.trades,
                probability_of_loss=p_loss,
                median_return=_percentiles(batch["ret"]).p50,
                p05_return=_percentiles(batch["ret"]).p05,
                p95_max_drawdown=-_percentiles(np.abs(batch["dd"])).p95,
                p95_losing_streak=_percentiles(batch["lose_streak"].astype(float)).p95,
                cost_rows=cost_rows,
            )
        result = _result(
            config=config,
            capital_mode=CapitalMode.PATH_DEPENDENT_EQUITY,
            quality=quality,
            verdict=verdict,
            historical=historical,
            final_p=_percentiles(batch["final"]),
            return_p=_percentiles(batch["ret"]),
            dd_p=_percentiles(batch["dd"]),
            dd_abs_p=_percentiles(np.abs(batch["dd"])),
            min_p=_percentiles(batch["min_eq"]),
            streak_p=_percentiles(batch["lose_streak"].astype(float)),
            p_loss=p_loss,
            p_profit=p_profit,
            p_ruin=p_ruin,
            thresholds=_threshold_probs(batch, config),
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
        )
        if comparison is not None:
            comparison = comparison.model_copy(
                update={
                    "path_dependent_median_return": result.return_percentiles.p50,
                    "path_dependent_p95_max_drawdown": -result.max_drawdown_abs_percentiles.p95,
                    "path_dependent_probability_of_loss": result.probability_of_loss,
                },
            )
        return _with_a57_fields(result, config, comparison, PATH_DEPENDENT_LIMITATION)


def _baseline_cost(rows: list[CostSensitivityRow], base_slippage_bps: float) -> float:
    if not rows:
        return 0.0
    for row in rows:
        if abs(row.slippage_bps) < 1e-12 and abs(row.commission_mult - 1.0) < 1e-12:
            return row.total_execution_cost
    for row in rows:
        if abs(row.slippage_bps - base_slippage_bps) < 1e-12 and abs(row.commission_mult - 1.0) < 1e-12:
            return row.total_execution_cost
    return rows[0].total_execution_cost


def _with_a57_fields(
    result: MonteCarloResult,
    config: MonteCarloConfig,
    comparison: EngineComparison | None,
    limitation: str,
) -> MonteCarloResult:
    params: dict[str, float] = {"position_percent": float(config.position_percent)}
    if config.fixed_cash_amount is not None:
        params["fixed_cash_amount"] = float(config.fixed_cash_amount)
    return result.model_copy(
        update={
            "engine_kind": ENGINE_KIND,
            "capital_model": CapitalMode.PATH_DEPENDENT_EQUITY.value,
            "resampling_limitation": limitation,
            "comparison": comparison,
            "position_sizing_mode": config.sizing_mode.value,
            "position_size_parameters": params,
            "execution_cost_parameters": {
                "slippage_bps": float(config.base_slippage_bps),
                "brokerage_rate": float(config.brokerage_rate),
                "brokerage_flat": float(config.brokerage_flat),
            },
        },
    )


PathDependentPortfolioMonteCarlo = PathDependentMonteCarlo
