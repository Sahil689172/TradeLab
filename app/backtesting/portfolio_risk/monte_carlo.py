"""Portfolio Monte Carlo: resample completed trades onto a shared book.

Reuses A5.6 sampling (shuffle / bootstrap / block_bootstrap) and A5.2
execution via ``replay_book``. Does not concatenate independent A5.7 runs.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.engine import _percentiles, _sample_index_matrix
from app.backtesting.monte_carlo.path_dependent import PathDependentMonteCarlo
from app.backtesting.monte_carlo.schemas import (
    CapitalMode,
    EngineMode,
    MonteCarloConfig,
    MonteCarloSizingMode,
    PercentileSummary,
)
from app.backtesting.portfolio_risk.book import replay_book
from app.backtesting.portfolio_risk.equity import drawdown_from_equity
from app.backtesting.portfolio_risk.schemas import (
    CostSensitivityRow,
    PortfolioRiskConfig,
    PortfolioTrade,
)


def run_portfolio_monte_carlo(
    trades: Sequence[PortfolioTrade],
    config: PortfolioRiskConfig,
) -> dict[str, object]:
    n = len(trades)
    if n == 0 or config.simulations < 1:
        return _empty_mc(config)
    rng = np.random.default_rng(config.random_seed)
    idx = _sample_index_matrix(
        rng,
        n,
        config.simulations,
        config.sampling_method,
        block_size=config.block_size,
    )
    finals = np.zeros(config.simulations, dtype=float)
    rets = np.zeros(config.simulations, dtype=float)
    dds = np.zeros(config.simulations, dtype=float)
    mins = np.zeros(config.simulations, dtype=float)
    costs = np.zeros(config.simulations, dtype=float)
    brokerage = np.zeros(config.simulations, dtype=float)
    slippage = np.zeros(config.simulations, dtype=float)
    util = np.zeros(config.simulations, dtype=float)
    concurrent = np.zeros(config.simulations, dtype=np.int32)
    streaks = np.zeros(config.simulations, dtype=np.int32)

    for s in range(config.simulations):
        sampled = _materialize(trades, idx[s], sim=s)
        book = replay_book(sampled, config)
        finals[s] = book.final_equity
        rets[s] = book.net_return
        dd = drawdown_from_equity(book.equity_timestamps, book.equity_values)
        dds[s] = dd.max_drawdown
        mins[s] = min(book.equity_values) if book.equity_values else book.final_equity
        costs[s] = sum(t.execution_costs for t in book.executed_trades)
        brokerage[s] = sum(t.brokerage for t in book.executed_trades)
        slippage[s] = sum(t.slippage for t in book.executed_trades)
        if book.snapshots:
            util[s] = float(np.mean([snap.utilization_pct for snap in book.snapshots]))
            concurrent[s] = max(snap.open_positions for snap in book.snapshots)
        streaks[s] = _losing_streak(book.executed_trades)

    p_loss = float(np.mean(finals < config.initial_capital))
    p_profit = float(np.mean(finals > config.initial_capital))
    p_ruin = float(np.mean(mins < config.ruin_equity))
    thresholds = {
        "P(return<0)": float(np.mean(rets < 0.0)),
        "P(final<initial)": p_loss,
    }
    for thr in config.drawdown_thresholds:
        thresholds[f"P(|maxDD|>{thr:.0%})"] = float(np.mean(np.abs(dds) > thr))

    return {
        "return_percentiles": _percentiles(rets),
        "equity_percentiles": _percentiles(finals),
        "drawdown_percentiles": _percentiles(np.abs(dds)),
        "probability_of_loss": p_loss,
        "probability_of_profit": p_profit,
        "probability_of_ruin": p_ruin,
        "threshold_probabilities": thresholds,
        "median_utilization": float(np.median(util)),
        "median_concurrent": float(np.median(concurrent)),
        "p95_losing_streak": float(np.percentile(streaks.astype(float), 95, method="linear")),
        "median_cost": float(np.median(costs)),
        "median_brokerage": float(np.median(brokerage)),
        "median_slippage": float(np.median(slippage)),
    }


def cost_sensitivity(
    trades: Sequence[PortfolioTrade],
    config: PortfolioRiskConfig,
) -> list[CostSensitivityRow]:
    rows: list[CostSensitivityRow] = []
    baseline_cost = 0.0
    for bps in config.slippage_range_bps:
        cfg = config.model_copy(update={"slippage_bps": float(bps), "include_cost_sensitivity": False})
        stats = run_portfolio_monte_carlo(trades, cfg)
        total = float(stats["median_cost"])
        if abs(float(bps)) < 1e-12:
            baseline_cost = total
        dd = stats["drawdown_percentiles"]
        p95 = float(dd.p95) if isinstance(dd, PercentileSummary) else 0.0
        rows.append(
            CostSensitivityRow(
                slippage_bps=float(bps),
                median_return=float(stats["return_percentiles"].p50) if isinstance(stats["return_percentiles"], PercentileSummary) else 0.0,
                probability_of_loss=float(stats["probability_of_loss"]),
                p95_max_drawdown=-p95,
                total_execution_cost=total,
                incremental_cost=0.0,
                brokerage_cost=float(stats["median_brokerage"]),
                slippage_cost=float(stats["median_slippage"]),
                median_ending_equity=float(stats["equity_percentiles"].p50) if isinstance(stats["equity_percentiles"], PercentileSummary) else 0.0,
            ),
        )
    if rows and abs(rows[0].slippage_bps) < 1e-12:
        baseline_cost = rows[0].total_execution_cost
    return [
        row.model_copy(update={"incremental_cost": row.total_execution_cost - baseline_cost})
        for row in rows
    ]


def compare_a57(
    trades: Sequence[PortfolioTrade],
    config: PortfolioRiskConfig,
) -> tuple[float, float, float]:
    """Run sequential A5.7 on the same trades for comparison. Not a ranking."""
    from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExitReason

    closed = []
    for trade in trades:
        closed.append(
            ClosedTradeRecord(
                symbol=trade.symbol,
                entry_timestamp=trade.entry_timestamp,
                exit_timestamp=trade.exit_timestamp,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                quantity=max(trade.quantity, 1e-9),
                gross_profit=trade.gross_pnl,
                brokerage=trade.brokerage,
                slippage=trade.slippage,
                net_profit=trade.net_pnl,
                holding_days=max(trade.holding_period, 0),
                exit_reason=ExitReason.SELL_RECOMMENDATION,
                strategy_name=trade.strategy,
            ),
        )
    mc = PathDependentMonteCarlo(
        MonteCarloConfig(
            simulations=min(config.simulations, 2_000),
            initial_capital=config.initial_capital,
            random_seed=config.random_seed,
            sampling_method=config.sampling_method,
            capital_mode=CapitalMode.PATH_DEPENDENT_EQUITY,
            engine_mode=EngineMode.PATH_DEPENDENT,
            sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
            position_percent=config.position_percent,
            slippage_range_bps=(config.slippage_bps,),
            base_slippage_bps=config.slippage_bps,
            brokerage_rate=config.brokerage_rate,
            brokerage_flat=config.brokerage_flat,
            allow_fractional_shares=config.allow_fractional_shares,
            min_quantity=config.min_quantity,
            include_cost_perturbation=False,
        ),
    )
    result = mc.run(closed)
    return (
        result.return_percentiles.p50,
        result.probability_of_loss,
        -result.max_drawdown_abs_percentiles.p95,
    )


def _materialize(
    trades: Sequence[PortfolioTrade],
    indices: np.ndarray,
    *,
    sim: int,
) -> list[PortfolioTrade]:
    out: list[PortfolioTrade] = []
    for k, index in enumerate(indices.tolist()):
        trade = trades[int(index)]
        out.append(
            trade.model_copy(
                update={"trade_id": f"{trade.trade_id}:sim{sim}:{k}"},
            ),
        )
    return out


def _losing_streak(trades: Sequence[PortfolioTrade]) -> int:
    run = 0
    best = 0
    ordered = sorted(trades, key=lambda t: (t.exit_timestamp, t.symbol))
    for trade in ordered:
        if trade.net_pnl < 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _empty_mc(config: PortfolioRiskConfig) -> dict[str, object]:
    zero = PercentileSummary()
    return {
        "return_percentiles": zero,
        "equity_percentiles": PercentileSummary(
            p01=config.initial_capital,
            p05=config.initial_capital,
            p10=config.initial_capital,
            p25=config.initial_capital,
            p50=config.initial_capital,
            p75=config.initial_capital,
            p90=config.initial_capital,
            p95=config.initial_capital,
            p99=config.initial_capital,
        ),
        "drawdown_percentiles": zero,
        "probability_of_loss": 0.0,
        "probability_of_profit": 0.0,
        "probability_of_ruin": 0.0,
        "threshold_probabilities": {},
        "median_utilization": 0.0,
        "median_concurrent": 0.0,
        "p95_losing_streak": 0.0,
        "median_cost": 0.0,
        "median_brokerage": 0.0,
        "median_slippage": 0.0,
    }
