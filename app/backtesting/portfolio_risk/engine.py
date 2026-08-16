"""A5.8 portfolio-level risk engine.

Consumes completed A5.2 trades. Re-sizes them on a shared cash book.
Does not modify EMA logic, A5.2 fills, A5.3, A5.6, or A5.7 numerical cores.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.backtesting.evaluation.metrics import cagr, profit_factor, sharpe_ratio, sortino_ratio
from app.backtesting.monte_carlo.robustness import classify_sample_quality
from app.backtesting.monte_carlo.schemas import PercentileSummary
from app.backtesting.portfolio_risk.aggregation import portfolio_trades_from_sources
from app.backtesting.portfolio_risk.book import replay_book
from app.backtesting.portfolio_risk.concentration import concentration_from_snapshots
from app.backtesting.portfolio_risk.correlation import correlation_report
from app.backtesting.portfolio_risk.equity import drawdown_from_equity
from app.backtesting.portfolio_risk.exceptions import PortfolioConfigError
from app.backtesting.portfolio_risk.monte_carlo import compare_a57, cost_sensitivity, run_portfolio_monte_carlo
from app.backtesting.portfolio_risk.schemas import (
    AllocationPolicy,
    LIMITATION,
    PortfolioRiskConfig,
    PortfolioRiskResult,
    PortfolioTrade,
)


class PortfolioRiskEngine:
    """Historical shared-book overlay plus optional portfolio Monte Carlo."""

    def __init__(self, config: PortfolioRiskConfig | None = None) -> None:
        self._config = config or PortfolioRiskConfig()
        if self._config.initial_capital <= 0:
            raise PortfolioConfigError("initial_capital must be > 0")

    @property
    def config(self) -> PortfolioRiskConfig:
        return self._config

    def run(self, sources: Sequence[object]) -> PortfolioRiskResult:
        config = self._config
        trades = portfolio_trades_from_sources(sources)
        book = replay_book(trades, config)
        executed = book.executed_trades
        dd = drawdown_from_equity(book.equity_timestamps, book.equity_values)
        concentration = concentration_from_snapshots(book.snapshots)
        symbol_corr = correlation_report(
            executed or trades,
            kind="symbol",
            min_observations=config.min_correlation_observations,
            high_threshold=config.high_correlation_threshold,
        )
        strategy_corr = correlation_report(
            executed or trades,
            kind="strategy",
            min_observations=config.min_correlation_observations,
            high_threshold=config.high_correlation_threshold,
        )
        warnings = _warnings(config, trades, book, symbol_corr, strategy_corr)
        nets = [t.net_pnl for t in executed]
        wins = [n for n in nets if n > 0]
        gross_pos = sum(t.gross_pnl for t in executed if t.gross_pnl > 0)
        gross_neg = sum(t.gross_pnl for t in executed if t.gross_pnl < 0)
        pf = profit_factor(gross_pos, gross_neg)
        if pf == float("inf"):
            pf = 1_000_000.0
        rets = _equity_returns(book.equity_values)
        years = _years(book)
        sharpe = sharpe_ratio(rets, periods_per_year=252.0) if len(rets) >= 2 else 0.0
        sortino = sortino_ratio(rets, periods_per_year=252.0) if len(rets) >= 2 else 0.0
        invested = [s for s in book.snapshots if s.open_positions > 0]
        avg_exp = float(sum(s.gross_exposure for s in invested) / len(invested)) if invested else 0.0
        max_exp = max((s.gross_exposure for s in book.snapshots), default=0.0)
        avg_util = float(sum(s.utilization_pct for s in invested) / len(invested)) if invested else 0.0
        max_util = max((s.utilization_pct for s in book.snapshots), default=0.0)
        max_conc = max((s.open_positions for s in book.snapshots), default=0)
        total_broker = sum(t.brokerage for t in executed)
        total_slip = sum(t.slippage for t in executed)
        total_cost = total_broker + total_slip
        total_gross = sum(t.gross_pnl for t in executed)
        cost_pct = (total_cost / abs(total_gross)) if abs(total_gross) > 1e-12 else None
        quality = classify_sample_quality(len(trades))

        mc: dict[str, object] = {}
        cost_rows = []
        a57 = (None, None, None)
        if config.include_monte_carlo and trades:
            mc = run_portfolio_monte_carlo(trades, config)
            if config.include_cost_sensitivity:
                cost_rows = cost_sensitivity(trades, config)
            if config.compare_a57:
                a57 = compare_a57(trades, config)

        symbols = {t.symbol for t in trades}
        strategies = {t.strategy for t in trades if t.strategy}
        return PortfolioRiskResult(
            limitation=LIMITATION,
            config=config,
            historical_trade_count=len(trades),
            symbol_count=len(symbols),
            strategy_count=len(strategies),
            executed_trade_count=len(executed),
            rejected_count=len(book.rejections),
            initial_capital=config.initial_capital,
            final_equity=book.final_equity,
            net_return=book.net_return,
            cagr=cagr(config.initial_capital, book.final_equity, years) if years else None,
            max_drawdown=dd.max_drawdown,
            max_drawdown_pct=dd.max_drawdown_pct,
            sharpe=sharpe,
            sortino=sortino,
            win_rate=(len(wins) / len(nets)) if nets else 0.0,
            profit_factor=float(pf),
            total_gross_pnl=total_gross,
            total_net_pnl=sum(nets),
            total_brokerage=total_broker,
            total_slippage=total_slip,
            total_costs=total_cost,
            cost_pct_of_gross=cost_pct,
            average_exposure=avg_exp,
            maximum_exposure=max_exp,
            average_utilization=avg_util,
            maximum_utilization=max_util,
            maximum_concurrent_positions=max_conc,
            concentration=concentration,
            drawdown=dd,
            symbol_correlation=symbol_corr,
            strategy_correlation=strategy_corr,
            rejections=book.rejections,
            warnings=warnings,
            sample_quality=quality.value,
            simulation_count=config.simulations if config.include_monte_carlo else 0,
            seed=config.random_seed,
            return_percentiles=_as_pct(mc.get("return_percentiles")),
            equity_percentiles=_as_pct(mc.get("equity_percentiles")),
            drawdown_percentiles=_as_pct(mc.get("drawdown_percentiles")),
            probability_of_loss=_as_float(mc.get("probability_of_loss")),
            probability_of_profit=_as_float(mc.get("probability_of_profit")),
            probability_of_ruin=_as_float(mc.get("probability_of_ruin")),
            threshold_probabilities=dict(mc.get("threshold_probabilities") or {}),
            cost_sensitivity=cost_rows,
            a57_median_return=a57[0],
            a57_probability_of_loss=a57[1],
            a57_p95_drawdown=a57[2],
        )


def _as_pct(value: object) -> PercentileSummary | None:
    return value if isinstance(value, PercentileSummary) else None


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _equity_returns(equity: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(equity)):
        prev = float(equity[i - 1])
        if prev <= 0:
            continue
        out.append(float(equity[i]) / prev - 1.0)
    return out


def _years(book) -> float:
    if len(book.equity_timestamps) < 2:
        return 0.0
    delta = book.equity_timestamps[-1] - book.equity_timestamps[0]
    return max(delta.total_seconds() / (365.25 * 24 * 3600), 0.0)


def _warnings(config, trades, book, symbol_corr, strategy_corr) -> list[str]:
    warnings = [
        LIMITATION,
        f"{len(trades)} historical trades overlaid on a shared book. "
        f"{config.simulations} simulations do not increase historical sample size.",
        f"SAMPLE_QUALITY={classify_sample_quality(len(trades)).value}.",
    ]
    if config.allocation_policy is AllocationPolicy.EQUAL_RISK:
        warnings.append(
            "EQUAL_RISK falls back to equal notional because completed trades do not "
            "include stop distance. True risk-parity is not fabricated.",
        )
    unaffordable = [
        r for r in book.rejections if r.reason_code and r.reason_code.value == "CANNOT_AFFORD_MIN_QUANTITY"
    ]
    if unaffordable:
        warnings.append(
            f"{len(unaffordable)} entries were not executed because cash could not buy "
            "the minimum quantity. The book does not invent fractional fills unless "
            "allow_fractional_shares is enabled.",
        )
    if symbol_corr.insufficient:
        warnings.append(
            "Symbol correlation is insufficient. Do not claim diversification.",
        )
    if strategy_corr.insufficient:
        warnings.append(
            "Strategy correlation is insufficient. Independent edge is not demonstrated.",
        )
    elif strategy_corr.average_pairwise is not None and strategy_corr.average_pairwise >= config.high_correlation_threshold:
        warnings.append(
            "Average strategy pairwise correlation is high. Multiple strategies may not "
            "be adding independent edge.",
        )
    return warnings
