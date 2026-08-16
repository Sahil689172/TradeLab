"""A5.8 portfolio-level risk and validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.backtesting.monte_carlo import MonteCarloConfig, MonteCarloEngine, PathDependentMonteCarlo
from app.backtesting.monte_carlo.schemas import EngineMode
from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExitReason
from app.backtesting.portfolio_risk import (
    AllocationPolicy,
    LimitAction,
    PortfolioRejectReason,
    PortfolioRiskConfig,
    PortfolioRiskEngine,
    PortfolioRiskLimits,
    format_markdown_report,
    portfolio_trades_from_sources,
    write_outputs,
)
from app.backtesting.portfolio_risk.book import replay_book
from app.backtesting.portfolio_risk.correlation import correlation_report
from app.backtesting.portfolio_risk.equity import drawdown_from_equity
from app.backtesting.portfolio_risk.schemas import AllocationStatus

TS = datetime(2022, 1, 3, tzinfo=timezone.utc)
FIXTURE = Path("tests/fixtures/portfolio_risk_trades.json")


def _closed(
    symbol: str,
    *,
    strategy: str = "ema_trend",
    entry: float = 100.0,
    exit_px: float = 110.0,
    qty: float = 10.0,
    t0: datetime | None = None,
    days: int = 10,
) -> ClosedTradeRecord:
    start = t0 or TS
    gross = (exit_px - entry) * qty
    return ClosedTradeRecord(
        symbol=symbol,
        entry_timestamp=start,
        exit_timestamp=start + timedelta(days=days),
        entry_price=entry,
        exit_price=exit_px,
        quantity=qty,
        gross_profit=gross,
        brokerage=0.0,
        slippage=0.0,
        net_profit=gross,
        holding_days=days,
        exit_reason=ExitReason.SELL_RECOMMENDATION,
        strategy_name=strategy,
    )


def _cfg(**kwargs: object) -> PortfolioRiskConfig:
    limits_kwargs = kwargs.pop("limits", None)
    base: dict[str, object] = dict(
        initial_capital=100_000.0,
        allocation_policy=AllocationPolicy.FIXED_PERCENT_EQUITY,
        position_percent=20.0,
        slippage_bps=0.0,
        brokerage_rate=0.0,
        allow_fractional_shares=False,
        min_quantity=1.0,
        include_monte_carlo=False,
        include_cost_sensitivity=False,
        compare_a57=False,
        simulations=40,
        random_seed=42,
        limits=limits_kwargs
        or PortfolioRiskLimits(
            max_exposure_pct=80.0,
            max_position_pct=25.0,
            max_symbol_concentration_pct=100.0,
            max_strategy_concentration_pct=100.0,
            max_open_positions=10,
            limit_action=LimitAction.REJECT,
        ),
    )
    base.update(kwargs)
    return PortfolioRiskConfig(**base)  # type: ignore[arg-type]


def test_portfolio_capital_constraint() -> None:
    trades = [
        _closed("RELIANCE", t0=TS),
        _closed("TCS", t0=TS),
        _closed("INFY", t0=TS, strategy="vwap"),
    ]
    book = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(
            allocation_policy=AllocationPolicy.EQUAL_CAPITAL,
            limits=PortfolioRiskLimits(
                max_exposure_pct=100.0,
                max_position_pct=100.0,
                max_symbol_concentration_pct=100.0,
                max_strategy_concentration_pct=100.0,
                max_open_positions=10,
            ),
        ),
    )
    invested = max(s.gross_exposure for s in book.snapshots)
    assert invested <= 100_000.0 + 1e-6
    assert book.final_equity > 0


def test_insufficient_cash() -> None:
    trades = [_closed("RELIANCE", entry=100.0, exit_px=110.0)]
    book = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(initial_capital=50.0, position_percent=20.0),
    )
    assert book.executed_trades == []
    assert book.rejections
    assert book.rejections[0].reason_code is PortfolioRejectReason.CANNOT_AFFORD_MIN_QUANTITY
    assert book.final_equity == pytest.approx(50.0)


def test_max_position_limit() -> None:
    trades = [_closed("RELIANCE")]
    book = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(
            position_percent=50.0,
            limits=PortfolioRiskLimits(
                max_exposure_pct=100.0,
                max_position_pct=10.0,
                max_symbol_concentration_pct=100.0,
                max_strategy_concentration_pct=100.0,
                max_open_positions=10,
                limit_action=LimitAction.REJECT,
            ),
        ),
    )
    assert book.executed_trades == []
    assert book.rejections[0].reason_code is PortfolioRejectReason.MAX_POSITION_PERCENT


def test_max_exposure_limit() -> None:
    trades = [
        _closed("RELIANCE", t0=TS),
        _closed("TCS", t0=TS),
        _closed("INFY", t0=TS, strategy="vwap"),
        _closed("SBIN", t0=TS, strategy="supertrend"),
    ]
    book = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(
            position_percent=30.0,
            limits=PortfolioRiskLimits(
                max_exposure_pct=50.0,
                max_position_pct=30.0,
                max_symbol_concentration_pct=100.0,
                max_strategy_concentration_pct=100.0,
                max_open_positions=10,
                limit_action=LimitAction.REJECT,
            ),
        ),
    )
    peak = max(s.gross_exposure for s in book.snapshots)
    assert peak <= 50_000.0 + 1.0
    assert any(r.reason_code is PortfolioRejectReason.MAX_PORTFOLIO_EXPOSURE for r in book.rejections)


def test_symbol_concentration() -> None:
    trades = [
        _closed("RELIANCE", t0=TS, days=20),
        _closed("TCS", t0=TS + timedelta(days=1), days=5),
    ]
    result = PortfolioRiskEngine(
        _cfg(
            position_percent=40.0,
            limits=PortfolioRiskLimits(
                max_exposure_pct=100.0,
                max_position_pct=50.0,
                max_symbol_concentration_pct=100.0,
                max_strategy_concentration_pct=100.0,
                max_open_positions=10,
            ),
        ),
    ).run(trades)
    assert result.concentration.largest_symbol == "RELIANCE"
    assert result.concentration.hhi > 0


def test_strategy_concentration() -> None:
    trades = [
        _closed("RELIANCE", strategy="ema_trend", t0=TS),
        _closed("TCS", strategy="ema_trend", t0=TS),
        _closed("INFY", strategy="vwap", t0=TS + timedelta(days=1)),
    ]
    book = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(
            position_percent=20.0,
            limits=PortfolioRiskLimits(
                max_exposure_pct=80.0,
                max_position_pct=25.0,
                max_symbol_concentration_pct=100.0,
                max_strategy_concentration_pct=30.0,
                max_open_positions=10,
                limit_action=LimitAction.REJECT,
            ),
        ),
    )
    assert any(r.reason_code is PortfolioRejectReason.MAX_STRATEGY_CONCENTRATION for r in book.rejections)


def test_concurrent_positions() -> None:
    trades = [
        _closed("RELIANCE", t0=TS, days=20),
        _closed("TCS", t0=TS, days=20),
    ]
    book = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(
            position_percent=20.0,
            limits=PortfolioRiskLimits(
                max_exposure_pct=80.0,
                max_position_pct=25.0,
                max_symbol_concentration_pct=100.0,
                max_strategy_concentration_pct=100.0,
                max_open_positions=10,
            ),
        ),
    )
    assert max(s.open_positions for s in book.snapshots) == 2
    peak = next(s for s in book.snapshots if s.open_positions == 2)
    assert peak.gross_exposure > 0
    assert peak.utilization_pct > 0
    assert peak.cash < 100_000.0


def test_portfolio_equity_curve() -> None:
    trades = [
        _closed("RELIANCE", entry=100, exit_px=110, t0=TS, days=20),
        _closed("TCS", entry=100, exit_px=90, t0=TS + timedelta(days=5), days=10),
    ]
    book = replay_book(portfolio_trades_from_sources(trades), _cfg(position_percent=20.0))
    assert len(book.equity_values) >= 3
    # Historical sleeve qty was 10; shared book re-sizes from 20% of ₹1,00,000.
    assert all(t.quantity == pytest.approx(200.0) for t in book.executed_trades)
    # Combined path: TCS exit (-₹2,000) then RELIANCE exit (+₹2,000).
    assert min(book.equity_values) == pytest.approx(98_000.0)
    assert book.final_equity == pytest.approx(100_000.0)
    historical_qty_pnl = 100.0 + (-100.0)
    resized_pnl = 2_000.0 + (-2_000.0)
    assert resized_pnl == historical_qty_pnl
    assert sum(t.net_pnl for t in book.executed_trades) == pytest.approx(resized_pnl)


def test_portfolio_drawdown() -> None:
    trades = [
        _closed("RELIANCE", entry=100, exit_px=70, t0=TS, days=15, strategy="ema_trend"),
        _closed("TCS", entry=100, exit_px=80, t0=TS, days=15, strategy="vwap"),
    ]
    shared_cfg = _cfg(
        position_percent=20.0,
        limits=PortfolioRiskLimits(
            max_exposure_pct=80.0,
            max_position_pct=25.0,
            max_symbol_concentration_pct=100.0,
            max_strategy_concentration_pct=100.0,
            max_open_positions=10,
        ),
    )
    full_cfg = _cfg(
        position_percent=100.0,
        limits=PortfolioRiskLimits(
            max_exposure_pct=100.0,
            max_position_pct=100.0,
            max_symbol_concentration_pct=100.0,
            max_strategy_concentration_pct=100.0,
            max_open_positions=10,
        ),
    )
    shared = replay_book(portfolio_trades_from_sources(trades), shared_cfg)
    sleeve_a = replay_book(portfolio_trades_from_sources([trades[0]]), full_cfg)
    sleeve_b = replay_book(portfolio_trades_from_sources([trades[1]]), full_cfg)
    port_dd = drawdown_from_equity(shared.equity_timestamps, shared.equity_values)
    dd_a = drawdown_from_equity(sleeve_a.equity_timestamps, sleeve_a.equity_values)
    dd_b = drawdown_from_equity(sleeve_b.equity_timestamps, sleeve_b.equity_values)
    naive_sum = abs(dd_a.max_drawdown) + abs(dd_b.max_drawdown)
    # Standalone 100% sleeves: RELIANCE -30%, TCS -20% → naive 50%.
    # Shared 20% book: combined equity trough is not 50%.
    assert naive_sum == pytest.approx(0.50)
    assert abs(port_dd.max_drawdown) < naive_sum - 0.05
    assert port_dd.max_drawdown < 0
    assert min(shared.equity_values) == pytest.approx(90_000.0)


def test_correlation_alignment() -> None:
    trades = [
        _closed("RELIANCE", exit_px=110, t0=TS, days=10),
        _closed("TCS", exit_px=109, t0=TS, days=10),
        _closed("RELIANCE", exit_px=90, t0=TS + timedelta(days=20), days=10),
        _closed("TCS", exit_px=91, t0=TS + timedelta(days=20), days=10),
        _closed("RELIANCE", exit_px=120, t0=TS + timedelta(days=40), days=10),
        _closed("TCS", exit_px=118, t0=TS + timedelta(days=40), days=10),
        _closed("RELIANCE", exit_px=80, t0=TS + timedelta(days=60), days=10),
        _closed("TCS", exit_px=82, t0=TS + timedelta(days=60), days=10),
        _closed("RELIANCE", exit_px=105, t0=TS + timedelta(days=80), days=10),
        _closed("TCS", exit_px=104, t0=TS + timedelta(days=80), days=10),
        _closed("RELIANCE", exit_px=95, t0=TS + timedelta(days=100), days=10),
        _closed("TCS", exit_px=96, t0=TS + timedelta(days=100), days=10),
        _closed("RELIANCE", exit_px=115, t0=TS + timedelta(days=120), days=10),
        _closed("TCS", exit_px=114, t0=TS + timedelta(days=120), days=10),
        _closed("RELIANCE", exit_px=85, t0=TS + timedelta(days=140), days=10),
        _closed("TCS", exit_px=86, t0=TS + timedelta(days=140), days=10),
    ]
    report = correlation_report(
        portfolio_trades_from_sources(trades),
        kind="symbol",
        min_observations=8,
        high_threshold=0.8,
    )
    assert report.insufficient is False
    assert report.average_pairwise is not None
    assert report.average_pairwise > 0.8


def test_insufficient_correlation_data() -> None:
    trades = [
        _closed("RELIANCE", t0=TS),
        _closed("TCS", t0=TS + timedelta(days=30)),
    ]
    report = correlation_report(
        portfolio_trades_from_sources(trades),
        kind="symbol",
        min_observations=8,
        high_threshold=0.8,
    )
    assert report.insufficient is True
    assert report.average_pairwise is None


@pytest.mark.parametrize("capital", [200.0, 500.0, 1000.0, 5000.0, 10_000.0, 100_000.0])
def test_small_capital_ladder(capital: float) -> None:
    trades = [_closed("RELIANCE", entry=1200.0, exit_px=1300.0)]
    book = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(initial_capital=capital, position_percent=20.0, allow_fractional_shares=False),
    )
    min_share = 1200.0
    budget = min(capital, capital * 0.20)
    if budget + 1e-9 < min_share:
        assert book.executed_trades == []
        assert book.rejections
        assert book.rejections[0].reason_code is PortfolioRejectReason.CANNOT_AFFORD_MIN_QUANTITY
        assert book.final_equity == pytest.approx(capital)
    else:
        assert book.executed_trades
        assert book.final_equity > 0


def test_small_capital_200() -> None:
    test_small_capital_ladder(200.0)


def test_small_capital_500() -> None:
    test_small_capital_ladder(500.0)


def test_small_capital_1000() -> None:
    test_small_capital_ladder(1000.0)


def test_deterministic_portfolio_monte_carlo() -> None:
    trades = [_closed("RELIANCE"), _closed("TCS", t0=TS + timedelta(days=1), exit_px=90)]
    cfg = _cfg(include_monte_carlo=True, simulations=80, random_seed=7)
    first = PortfolioRiskEngine(cfg).run(trades)
    second = PortfolioRiskEngine(cfg).run(trades)
    assert first.return_percentiles is not None
    assert first.return_percentiles.p50 == second.return_percentiles.p50
    assert first.probability_of_loss == second.probability_of_loss


def test_different_seed_changes_simulation() -> None:
    trades = [
        _closed("RELIANCE", exit_px=110),
        _closed("TCS", exit_px=90, t0=TS + timedelta(days=2)),
        _closed("INFY", exit_px=105, strategy="vwap", t0=TS + timedelta(days=4)),
    ]
    a = PortfolioRiskEngine(_cfg(include_monte_carlo=True, simulations=120, random_seed=1)).run(trades)
    b = PortfolioRiskEngine(_cfg(include_monte_carlo=True, simulations=120, random_seed=2)).run(trades)
    assert a.return_percentiles is not None and b.return_percentiles is not None
    assert a.return_percentiles.model_dump() != b.return_percentiles.model_dump()


def test_cost_sensitivity() -> None:
    trades = [_closed("RELIANCE", exit_px=110), _closed("TCS", exit_px=95, t0=TS + timedelta(days=1))]
    result = PortfolioRiskEngine(
        _cfg(
            include_monte_carlo=True,
            include_cost_sensitivity=True,
            simulations=30,
            slippage_bps=5.0,
            brokerage_rate=0.0003,
            slippage_range_bps=(0.0, 5.0, 10.0, 15.0, 20.0),
        ),
    ).run(trades)
    assert [row.slippage_bps for row in result.cost_sensitivity] == [0.0, 5.0, 10.0, 15.0, 20.0]
    zero = result.cost_sensitivity[0]
    high = result.cost_sensitivity[-1]
    assert high.incremental_cost == pytest.approx(high.total_execution_cost - zero.total_execution_cost)
    assert all(row.brokerage_cost >= 0 for row in result.cost_sensitivity)


def test_no_lookahead() -> None:
    early = [
        _closed("RELIANCE", t0=TS, days=10, exit_px=110),
        _closed("TCS", t0=TS + timedelta(days=1), days=10, exit_px=90),
    ]
    late = early + [_closed("INFY", t0=TS + timedelta(days=40), days=5, exit_px=120, strategy="vwap")]
    cfg = _cfg(position_percent=20.0)
    a = replay_book(portfolio_trades_from_sources(early), cfg)
    b = replay_book(portfolio_trades_from_sources(late), cfg)
    cutoff = TS + timedelta(days=12)
    eq_a = [v for ts, v in zip(a.equity_timestamps, a.equity_values) if ts <= cutoff]
    eq_b = [v for ts, v in zip(b.equity_timestamps, b.equity_values) if ts <= cutoff]
    assert eq_a == eq_b


def test_existing_a56_regression() -> None:
    trades = [_closed("RELIANCE"), _closed("TCS", exit_px=90)]
    result = MonteCarloEngine(
        MonteCarloConfig(simulations=40, initial_capital=10_000, random_seed=3),
    ).run(trades)
    assert result.engine_kind == "TradeResamplingMonteCarlo"


def test_existing_a57_regression() -> None:
    trades = [_closed("RELIANCE"), _closed("TCS", exit_px=90)]
    result = PathDependentMonteCarlo(
        MonteCarloConfig(
            simulations=20,
            initial_capital=10_000,
            random_seed=3,
            engine_mode=EngineMode.PATH_DEPENDENT,
        ),
    ).run(trades)
    assert result.engine_kind == "PathDependentPortfolioMonteCarlo"
    assert result.source_trade_count == 2


def test_report_and_cli(tmp_path: Path) -> None:
    trades = portfolio_trades_from_sources(
        [
            _closed("RELIANCE", strategy="ema_trend"),
            _closed("TCS", strategy="ema_trend", t0=TS + timedelta(days=1)),
            _closed("INFY", strategy="vwap", t0=TS + timedelta(days=2), exit_px=95),
        ],
    )
    result = PortfolioRiskEngine(_cfg(include_monte_carlo=True, simulations=25)).run(trades)
    text = format_markdown_report(result)
    for section in ("PORTFOLIO SUMMARY", "EXPOSURE", "CONCENTRATION", "RISK", "COSTS"):
        assert section in text
    paths = write_outputs(result, output_dir=tmp_path)
    assert paths["json"].exists()
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "portfolio_risk_cli",
        Path("backend/scripts/portfolio_risk.py"),
    )
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    code = cli.main(
        [
            "--trades-json",
            str(FIXTURE),
            "--initial-capital",
            "100000",
            "--max-exposure",
            "80",
            "--max-position-percent",
            "20",
            "--simulations",
            "20",
            "--seed",
            "42",
            "--no-monte-carlo",
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert code == 0


def test_identity_preserved() -> None:
    trades = portfolio_trades_from_sources(
        [
            _closed("RELIANCE", strategy="ema_trend"),
            _closed("INFY", strategy="vwap"),
        ],
    )
    assert {t.symbol for t in trades} == {"RELIANCE", "INFY"}
    assert {t.strategy for t in trades} == {"ema_trend", "vwap"}


def test_hhi_and_scale_is_explicit() -> None:
    trades = [_closed("RELIANCE"), _closed("TCS", t0=TS)]
    scaled = replay_book(
        portfolio_trades_from_sources(trades),
        _cfg(
            position_percent=50.0,
            limits=PortfolioRiskLimits(
                max_exposure_pct=40.0,
                max_position_pct=50.0,
                max_symbol_concentration_pct=100.0,
                max_strategy_concentration_pct=100.0,
                max_open_positions=10,
                limit_action=LimitAction.SCALE,
            ),
        ),
    )
    assert scaled.executed_trades
    assert any(d.status is AllocationStatus.PARTIAL for d in scaled.rejections) or max(
        s.gross_exposure for s in scaled.snapshots
    ) <= 40_000.0 + 1.0
