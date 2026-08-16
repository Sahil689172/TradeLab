"""Walk-forward controller: train → freeze → OOS test → roll.

Does not rewrite A5.1–A5.8. Monte Carlo, if requested, runs only on combined
OOS trades and is labeled OUT-OF-SAMPLE MONTE CARLO.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone

import pandas as pd

from app.backtesting.monte_carlo import MonteCarloConfig, MonteCarloEngine
from app.backtesting.monte_carlo.robustness import assess_verdict, classify_sample_quality
from app.backtesting.monte_carlo.schemas import MonteCarloVerdict
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.portfolio_risk import PortfolioRiskEngine
from app.backtesting.walk_forward.analysis import (
    combined_metrics,
    degradation,
    mean_train_oos,
    oos_by_symbol,
    oos_by_year,
    parameter_stability,
    stitch_equity,
)
from app.backtesting.walk_forward.exceptions import WalkForwardConfigError
from app.backtesting.walk_forward.execution import PeriodRun, run_period
from app.backtesting.walk_forward.isolation import CachedFeatures, CachedMarket, frame_max_date, leakage_from_windows
from app.backtesting.walk_forward.optimizer import select_joint, select_on_train
from app.backtesting.walk_forward.schemas import (
    LIMITATION,
    CapitalMode,
    EquityPoint,
    SelectionScope,
    WalkForwardConfig,
    WalkForwardResult,
    WindowResult,
)
from app.backtesting.walk_forward.windows import generate_windows


class WalkForwardEngine:
    def __init__(
        self,
        config: WalkForwardConfig | None = None,
        *,
        selector: Callable[..., tuple] | None = None,
        runner: Callable[..., PeriodRun] | None = None,
        evaluator: object | None = None,
        strategy_factory: object | None = None,
    ) -> None:
        self._config = config or WalkForwardConfig()
        self._selector = selector
        self._runner = runner or run_period
        self._evaluator = evaluator
        self._strategy_factory = strategy_factory

    @property
    def config(self) -> WalkForwardConfig:
        return self._config

    def run(
        self,
        *,
        symbols: Sequence[str],
        market_data: object,
        features: object,
    ) -> WalkForwardResult:
        names = [s.strip().upper() for s in symbols if s.strip()]
        if not names:
            raise WalkForwardConfigError("at least one symbol is required")
        market_data = CachedMarket(market_data)
        features = CachedFeatures(features)
        data_start, data_end = _span(names, market_data, self._config)
        windows = generate_windows(data_start, data_end, self._config)
        leakage = leakage_from_windows(windows)
        window_results: list[WindowResult] = []
        oos_trades: list[ClosedTradeRecord] = []
        equity_segments: list[pd.Series] = []
        capital = float(self._config.initial_capital)
        rejected_total = 0
        extra = _runner_extras(self._evaluator, self._strategy_factory)

        for window in windows:
            frozen_joint = None
            joint_n = 0
            if self._config.selection_scope is SelectionScope.JOINT:
                frozen_joint, _joint_metrics, joint_n, train_max = (self._selector or select_joint)(
                    symbols=names,
                    wf_config=self._config,
                    train_start=window.train_start,
                    train_end=window.train_end,
                    market_data=market_data,
                    features=features,
                    initial_capital=self._config.initial_capital,
                    runner=self._runner,
                    **extra,
                )
                if train_max > window.train_end:
                    leakage = _fail_leakage(leakage, f"joint train saw {train_max}")

            for symbol in names:
                if frozen_joint is None:
                    frozen, train_metrics, n_cand, train_max = (self._selector or select_on_train)(
                        symbol=symbol,
                        wf_config=self._config,
                        train_start=window.train_start,
                        train_end=window.train_end,
                        market_data=market_data,
                        features=features,
                        initial_capital=self._config.initial_capital,
                        runner=self._runner,
                        **extra,
                    )
                else:
                    frozen = frozen_joint
                    n_cand = joint_n
                    train_period = self._runner(
                        symbol=symbol,
                        strategy_config=frozen,
                        wf_config=self._config,
                        start=window.train_start,
                        end=window.train_end,
                        market_data=market_data,
                        features=features,
                        initial_capital=self._config.initial_capital,
                        **extra,
                    )
                    train_metrics = train_period.metrics
                    train_max = train_period.used_max
                if train_max > window.train_end:
                    leakage = _fail_leakage(leakage, f"{symbol} train saw {train_max}")
                start_cap = (
                    capital
                    if self._config.capital_mode is CapitalMode.COMPOUNDED
                    else self._config.initial_capital
                )
                period = self._runner(
                    symbol=symbol,
                    strategy_config=frozen,
                    wf_config=self._config,
                    start=window.test_start,
                    end=window.test_end,
                    market_data=market_data,
                    features=features,
                    initial_capital=start_cap,
                    **extra,
                )
                if period.used_max > window.test_end:
                    leakage = _fail_leakage(
                        leakage,
                        f"{symbol} OOS saw {period.used_max}",
                        warmup=False,
                    )
                ending = float(period.equity.iloc[-1]) if len(period.equity) else start_cap
                window_results.append(
                    WindowResult(
                        window=window,
                        symbol=symbol,
                        selected=train_metrics,
                        candidates_evaluated=n_cand,
                        train=train_metrics,
                        oos=period.metrics,
                        frozen_parameters=train_metrics.parameters,
                        oos_trade_count=len(period.trades),
                        starting_capital=start_cap,
                        ending_capital=ending,
                        selection_used_max_data_date=train_max,
                        oos_used_max_data_date=period.used_max,
                        rejected_count=period.rejected_count,
                    ),
                )
                oos_trades.extend(period.trades)
                equity_segments.append(period.equity)
                rejected_total += period.rejected_count
                if self._config.capital_mode is CapitalMode.COMPOUNDED:
                    capital = ending

        oos_equity = stitch_equity(
            equity_segments,
            initial=self._config.initial_capital,
            mode=self._config.capital_mode,
        )
        stats = combined_metrics(oos_trades, oos_equity, self._config.initial_capital)
        train_mean, oos_mean = mean_train_oos(window_results)
        deg = degradation(train_mean, oos_mean)
        stability = parameter_stability(window_results)
        quality = classify_sample_quality(len(oos_trades))
        verdict = assess_verdict(
            source_trade_count=len(oos_trades),
            probability_of_loss=1.0 if float(stats["return"] or 0.0) < 0 else 0.0,
            median_return=float(stats["return"] or 0.0),
            p95_max_drawdown=-float(stats["max_drawdown"] or 0.0),
            score=50.0 if len(oos_trades) else 0.0,
        )
        warnings = [
            LIMITATION,
            f"{len(oos_trades)} OOS trades from {len(windows)} window(s). "
            "Simulation count does not increase historical sample size.",
            f"SAMPLE_QUALITY={quality.value}; VERDICT={verdict.value}.",
            "capital_mode=compounded carries ending OOS equity into the next test window. "
            "capital_mode=fixed restarts each test window at initial_capital.",
        ]
        mc_p_loss = None
        mc_med = None
        mc_sims = 0
        if self._config.include_monte_carlo and oos_trades:
            mc = MonteCarloEngine(
                MonteCarloConfig(
                    simulations=self._config.simulations,
                    initial_capital=self._config.initial_capital,
                    random_seed=self._config.random_seed,
                ),
            ).run(oos_trades, strategy=self._config.strategy_alias, symbol=",".join(names))
            mc_p_loss = mc.probability_of_loss
            mc_med = mc.return_percentiles.p50
            mc_sims = mc.simulations
            warnings.append(
                "OUT-OF-SAMPLE MONTE CARLO resamples OOS trades only. "
                f"{mc.simulations:,} simulations generated from {len(oos_trades)} OOS trades. "
                "Monte Carlo does not create new historical observations.",
            )
            verdict = mc.verdict
            quality = mc.sample_quality
        if self._config.include_portfolio_risk and oos_trades:
            PortfolioRiskEngine().run(oos_trades)
            warnings.append("A5.8 portfolio risk was run on combined OOS trades.")
        if len(oos_trades) <= 4:
            warnings.append("INSUFFICIENT_EVIDENCE: OOS trade count is too small for a robustness claim.")
            verdict = MonteCarloVerdict.INSUFFICIENT_EVIDENCE
        if not windows:
            warnings.append("No complete train/test windows fit the configured data range.")
            verdict = MonteCarloVerdict.INSUFFICIENT_EVIDENCE

        gross = float(stats["gross"] or 0.0)
        costs = float(stats["costs"] or 0.0)
        return WalkForwardResult(
            config=self._config,
            symbols=names,
            windows=window_results,
            window_count=len(windows),
            oos_trade_count=len(oos_trades),
            oos_return=float(stats["return"] or 0.0),
            oos_cagr=stats["cagr"],
            oos_sharpe=float(stats["sharpe"] or 0.0),
            oos_sortino=float(stats["sortino"] or 0.0),
            oos_max_drawdown=float(stats["max_drawdown"] or 0.0),
            oos_win_rate=float(stats["win_rate"] or 0.0),
            oos_profit_factor=float(stats["profit_factor"] or 0.0),
            oos_gross_profit=gross,
            oos_net_profit=float(stats["net"] or 0.0),
            oos_total_costs=costs,
            oos_cost_pct_of_gross=(costs / abs(gross)) if abs(gross) > 1e-12 else None,
            initial_capital=self._config.initial_capital,
            final_oos_equity=float(stats["final"] or self._config.initial_capital),
            capital_mode=self._config.capital_mode,
            degradation=deg,
            parameter_stability=stability,
            leakage=leakage,
            sample_quality=quality,
            verdict=verdict,
            monte_carlo_probability_of_loss=mc_p_loss,
            monte_carlo_median_return=mc_med,
            monte_carlo_simulations=mc_sims,
            warnings=warnings,
            oos_by_year=oos_by_year(oos_trades, self._config.initial_capital),
            oos_by_symbol=oos_by_symbol(oos_trades, self._config.initial_capital),
            oos_trades=oos_trades,
            equity_curve=_equity_points(oos_equity),
            oos_rejected_count=rejected_total,
            generated_at=datetime.now(timezone.utc),
        )


def _runner_extras(evaluator: object | None, factory: object | None) -> dict[str, object]:
    extra: dict[str, object] = {}
    if evaluator is not None:
        extra["evaluator"] = evaluator
    if factory is not None:
        extra["strategy_factory"] = factory
    return extra


def _fail_leakage(report, detail: str, *, warmup: bool = True):
    update = {
        "passed": False,
        "train_selection_ignores_test": False if warmup else report.train_selection_ignores_test,
        "details": list(report.details) + [detail],
    }
    if not warmup:
        update["warmup_capped_at_period_end"] = False
    return report.model_copy(update=update)


def _equity_points(series: pd.Series) -> list[EquityPoint]:
    points: list[EquityPoint] = []
    if series is None or series.empty:
        return points
    for ts, value in series.items():
        stamp = pd.Timestamp(ts).to_pydatetime()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        points.append(EquityPoint(timestamp=stamp, equity=float(value)))
    return points


def _span(symbols: Sequence[str], market_data: object, config: WalkForwardConfig) -> tuple:
    if config.data_start is not None and config.data_end is not None:
        return config.data_start, config.data_end
    starts = []
    ends = []
    for symbol in symbols:
        frame = market_data.get_history(symbol)
        latest = frame_max_date(frame)
        if frame is None or frame.empty or latest is None:
            continue
        stamps = pd.to_datetime(frame["date"])
        starts.append(stamps.min().date())
        ends.append(latest)
    if not starts:
        raise WalkForwardConfigError("no market data for requested symbols")
    data_start = config.data_start or min(starts)
    data_end = config.data_end or max(ends)
    return data_start, data_end
