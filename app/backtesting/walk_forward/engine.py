"""Walk-forward controller: train → freeze → OOS test → roll.

Does not rewrite A5.1–A5.8. Monte Carlo, if requested, runs only on combined
OOS trades and is labeled OUT-OF-SAMPLE MONTE CARLO.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, time, timezone

import pandas as pd

from app.backtesting.monte_carlo import MonteCarloConfig, MonteCarloEngine
from app.backtesting.monte_carlo.robustness import assess_verdict, classify_sample_quality
from app.backtesting.monte_carlo.schemas import MonteCarloVerdict
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.portfolio_risk import PortfolioRiskEngine
from app.backtesting.walk_forward.accounting import (
    ACCOUNTING_MODEL,
    ACCOUNTING_NOTE,
    SHARPE_METHODOLOGY,
    assert_costs_not_double_counted,
    assert_ledger_invariant,
)
from app.backtesting.walk_forward.analysis import (
    degradation,
    mean_train_oos,
    mean_window_return,
    oos_by_symbol,
    oos_by_year,
    parameter_stability,
    stitch_equity,
)
from app.backtesting.walk_forward.attribution import merge_attribution
from app.backtesting.walk_forward.equity import (
    assert_ledger_equity_matches_trades,
    assert_market_timestamps_only,
    combined_oos_end,
    sanitize_equity_series,
)
from app.backtesting.walk_forward.sample_metrics import build_sample_aware_performance
from app.backtesting.walk_forward.exceptions import WalkForwardConfigError
from app.backtesting.walk_forward.execution import PeriodRun, run_period
from app.backtesting.walk_forward.isolation import CachedFeatures, CachedMarket, frame_max_date, leakage_from_windows
from app.backtesting.walk_forward.optimizer import select_joint, select_on_train
from app.backtesting.walk_forward.schemas import (
    LIMITATION,
    CapitalMode,
    EquityPoint,
    ExecutionAttribution,
    SelectionEligibility,
    SelectionScope,
    StrategyIdentity,
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
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config or WalkForwardConfig()
        self._selector = selector
        self._runner = runner or run_period
        self._evaluator = evaluator
        self._strategy_factory = strategy_factory
        self._progress = progress or (lambda _message: None)

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
        attributions: list[ExecutionAttribution] = []
        attribution_by_symbol: dict[str, list[ExecutionAttribution]] = {}
        extra = _runner_extras(self._evaluator, self._strategy_factory)
        extra["frame_cache"] = {}
        n_cand_hint = _candidate_count(self._config, names[0])
        self._progress(
            f"Data {data_start.isoformat()} → {data_end.isoformat()} | "
            f"{len(windows)} window(s) | {n_cand_hint} train candidate(s) | "
            f"{len(names)} symbol(s)",
        )
        if not windows:
            self._progress("No complete train/test windows fit this date range.")

        for window in windows:
            frozen_joint = None
            joint_n = 0
            joint_selection = None
            train_max = window.train_end
            if self._config.selection_scope is SelectionScope.JOINT:
                frozen_joint, _joint_metrics, joint_n, train_max, joint_selection = (self._selector or select_joint)(
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
                self._progress(
                    f"Window {window.window_id}/{len(windows)} {symbol} "
                    f"TRAIN {window.train_label} ({n_cand_hint} candidate(s), one replay)...",
                )
                train_selection = joint_selection
                if frozen_joint is None:
                    frozen, train_metrics, n_cand, train_max, train_selection = (self._selector or select_on_train)(
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
                self._progress(
                    f"Window {window.window_id}/{len(windows)} {symbol} "
                    f"TEST {window.test_label} frozen={train_metrics.config_key}...",
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
                        attribution=period.attribution or ExecutionAttribution(),
                        requested_strategy=period.requested_strategy or self._config.strategy_alias,
                        execution_engine=period.execution_engine or "ema_trend",
                        train_selection=train_selection,
                    ),
                )
                oos_trades.extend(period.trades)
                equity_segments.append(period.equity)
                rejected_total += period.rejected_count
                if period.attribution is not None:
                    attributions.append(period.attribution)
                    attribution_by_symbol.setdefault(symbol, []).append(period.attribution)
                if self._config.capital_mode is CapitalMode.COMPOUNDED:
                    capital = ending
                self._progress(
                    f"Window {window.window_id}/{len(windows)} {symbol} done | "
                    f"OOS trades={len(period.trades)} return={period.metrics.return_pct:.2%}",
                )

        oos_equity = stitch_equity(
            equity_segments,
            initial=self._config.initial_capital,
            mode=self._config.capital_mode,
        )
        oos_end = combined_oos_end(window_results)
        if oos_end is not None:
            cap = pd.Timestamp(datetime.combine(oos_end, time.max, tzinfo=timezone.utc))
            oos_equity = sanitize_equity_series(oos_equity, max_timestamp=cap)
        perf = build_sample_aware_performance(oos_trades, oos_equity, self._config.initial_capital)
        assert_costs_not_double_counted(oos_trades)
        assert_ledger_equity_matches_trades(
            oos_equity,
            oos_trades,
            initial=self._config.initial_capital,
        )
        assert_ledger_invariant(
            initial=self._config.initial_capital,
            trades=oos_trades,
            final_equity=float(perf.final_equity),
        )
        train_mean, oos_mean = mean_train_oos(window_results)
        mean_oos_ret = mean_window_return(window_results, train=False)
        mean_train_ret = mean_window_return(window_results, train=True)
        combined_oos_ret = float(perf.return_pct)
        deg = degradation(train_mean, oos_mean, oos_trade_count=len(oos_trades))
        stability = parameter_stability(window_results)
        quality = classify_sample_quality(len(oos_trades))
        oos_attribution = merge_attribution(attributions)
        oos_attribution_by_symbol = {
            symbol: merge_attribution(rows) for symbol, rows in sorted(attribution_by_symbol.items())
        }
        generated_at = datetime.now(timezone.utc)
        assert_market_timestamps_only(oos_equity, max_date=oos_end, generated_at=generated_at)
        verdict = assess_verdict(
            source_trade_count=len(oos_trades),
            probability_of_loss=1.0 if float(perf.return_pct) < 0 else 0.0,
            median_return=float(perf.return_pct),
            p95_max_drawdown=-float(perf.max_drawdown),
            score=50.0 if len(oos_trades) else 0.0,
        )
        mc_p_loss = None
        mc_med = None
        mc_sims = 0
        warnings = [
            LIMITATION,
            f"historical_oos_trades={len(oos_trades)} from {len(windows)} window(s). "
            "simulation_count does not increase historical sample size.",
            f"SAMPLE_QUALITY={quality.value}; VERDICT={verdict.value}.",
            "capital_mode=compounded carries ending OOS equity into the next test window. "
            "capital_mode=fixed restarts each test window at initial_capital.",
        ]
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
        fallback_windows = [
            row
            for row in window_results
            if row.train_selection is not None
            and row.train_selection.selected_eligibility is SelectionEligibility.FALLBACK_INELIGIBLE
        ]
        if fallback_windows:
            warnings.append(
                f"TRAIN_SELECTION_FALLBACK: {len(fallback_windows)}/{len(window_results)} window(s) "
                f"selected a candidate below minimum_training_trades="
                f"{self._config.minimum_training_trades}. "
                "Minimum was NOT satisfied; train selection is diagnostic only."
            )

        gross = float(perf.gross_profit)
        costs = float(perf.total_costs)
        years = 0.0
        if len(oos_equity) >= 2:
            delta = oos_equity.index[-1] - oos_equity.index[0]
            years = max(pd.Timedelta(delta).total_seconds() / (365.25 * 24 * 3600), 0.0)
        from app.backtesting.evaluation.metrics import cagr

        oos_cagr = cagr(self._config.initial_capital, perf.final_equity, years) if years > 0 else None
        return WalkForwardResult(
            config=self._config,
            symbols=names,
            windows=window_results,
            window_count=len(windows),
            oos_trade_count=len(oos_trades),
            historical_oos_trades=len(oos_trades),
            accounting_model=ACCOUNTING_MODEL,
            accounting_note=ACCOUNTING_NOTE,
            combined_oos_return=combined_oos_ret,
            mean_window_oos_return=mean_oos_ret,
            combined_train_return=None,
            mean_window_train_return=mean_train_ret,
            oos_return=combined_oos_ret,
            oos_cagr=oos_cagr,
            oos_sharpe=perf.sharpe,
            oos_sharpe_raw=perf.sharpe_raw,
            oos_sharpe_status=perf.sharpe_status,
            oos_sharpe_methodology=SHARPE_METHODOLOGY,
            oos_sortino=perf.sortino,
            oos_sortino_raw=perf.sortino_raw,
            oos_sortino_status=perf.sortino_status,
            oos_sortino_methodology=SHARPE_METHODOLOGY,
            oos_max_drawdown=float(perf.max_drawdown),
            oos_win_rate=perf.win_rate,
            oos_win_rate_raw=perf.win_rate_raw,
            oos_win_rate_status=perf.win_rate_status,
            oos_profit_factor=perf.profit_factor,
            oos_profit_factor_raw=perf.profit_factor_raw,
            oos_profit_factor_status=perf.profit_factor_status,
            oos_gross_profit=gross,
            oos_net_profit=float(perf.net_profit),
            oos_total_costs=costs,
            oos_cost_pct_of_gross=(costs / abs(gross)) if abs(gross) > 1e-12 else None,
            oos_performance=perf,
            initial_capital=self._config.initial_capital,
            final_oos_equity=float(perf.final_equity),
            capital_mode=self._config.capital_mode,
            strategy_identity=StrategyIdentity(
                requested_strategy=self._config.strategy_alias,
                execution_engine="ema_trend",
            ),
            degradation=deg,
            parameter_stability=stability,
            leakage=leakage,
            sample_quality=quality,
            verdict=verdict,
            monte_carlo_probability_of_loss=mc_p_loss,
            monte_carlo_median_return=mc_med,
            monte_carlo_simulations=mc_sims,
            simulation_count=mc_sims,
            warnings=warnings,
            oos_by_year=oos_by_year(oos_trades, self._config.initial_capital),
            oos_by_symbol=oos_by_symbol(oos_trades, self._config.initial_capital),
            oos_trades=oos_trades,
            equity_curve=_equity_points(oos_equity),
            oos_rejected_count=rejected_total,
            oos_attribution=oos_attribution,
            oos_attribution_by_symbol=oos_attribution_by_symbol,
            generated_at=generated_at,
        )


def _candidate_count(config: WalkForwardConfig, symbol: str) -> int:
    from app.backtesting.walk_forward.search import iter_candidates

    return sum(1 for _ in iter_candidates(config.search, symbol=symbol, min_history_bars=config.min_history_bars))


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
