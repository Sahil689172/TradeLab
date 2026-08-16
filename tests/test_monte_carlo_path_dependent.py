"""A5.7 path-dependent portfolio Monte Carlo."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from app.backtesting.monte_carlo import (
    EngineMode,
    MonteCarloConfig,
    MonteCarloEngine,
    MonteCarloSizingMode,
    PathDependentMonteCarlo,
    PathDependentPortfolioMonteCarlo,
    SamplingMethod,
    format_markdown_report,
    make_synthetic_trades,
    write_outputs,
)
from app.backtesting.monte_carlo.adapter import trades_from_sources
from app.backtesting.monte_carlo.exceptions import MonteCarloConfigError
from app.backtesting.monte_carlo.portfolio import (
    execution_config_from_mc,
    price_arrays,
    round_trip_cash_pnl,
    simulate_portfolio_batch,
)
from app.backtesting.monte_carlo.schemas import (
    CapitalMode,
    MonteCarloVerdict,
    SampleQuality,
)
from app.backtesting.order_execution import (
    ExecutionConfig,
    MarketOrder,
    OrderSide,
    PositionSizingMode,
    SimulatedBroker,
)
from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExitReason

TS0 = datetime(2022, 6, 1, tzinfo=timezone.utc)
TS1 = datetime(2022, 6, 10, tzinfo=timezone.utc)
FIXTURE = Path("tests/fixtures/monte_carlo_trades.json")


def _trade(
    *,
    entry: float,
    exit_px: float,
    qty: float = 10.0,
    symbol: str = "RELIANCE",
) -> ClosedTradeRecord:
    gross = (exit_px - entry) * qty
    return ClosedTradeRecord(
        symbol=symbol,
        entry_timestamp=TS0,
        exit_timestamp=TS1,
        entry_price=entry,
        exit_price=exit_px,
        quantity=qty,
        gross_profit=gross,
        brokerage=0.0,
        slippage=0.0,
        net_profit=gross,
        holding_days=9,
        exit_reason=ExitReason.SELL_RECOMMENDATION,
        strategy_name="ema_trend",
    )


def _cfg(**kwargs: object) -> MonteCarloConfig:
    base: dict[str, object] = dict(
        simulations=40,
        initial_capital=100_000.0,
        random_seed=42,
        sampling_method=SamplingMethod.BOOTSTRAP,
        engine_mode=EngineMode.PATH_DEPENDENT,
        sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
        position_percent=10.0,
        slippage_range_bps=(0.0, 5.0, 10.0, 20.0),
        base_slippage_bps=5.0,
        brokerage_rate=0.0003,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )
    base.update(kwargs)
    return MonteCarloConfig(**base)  # type: ignore[arg-type]


def test_alias_and_basic_simulation() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=95)]
    result = PathDependentPortfolioMonteCarlo(_cfg()).run(trades)
    assert result.engine_kind == "PathDependentPortfolioMonteCarlo"
    assert result.capital_mode is CapitalMode.PATH_DEPENDENT_EQUITY
    assert result.source_trade_count == 2
    assert result.simulations == 40
    assert result.median_case is not None
    assert result.median_case.final_equity > 0


def test_deterministic_seed() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=90), _trade(entry=50, exit_px=55)]
    cfg = _cfg(random_seed=7, simulations=80)
    first = PathDependentMonteCarlo(cfg).run(trades)
    second = PathDependentMonteCarlo(cfg).run(trades)
    assert first.final_capital_percentiles.p50 == second.final_capital_percentiles.p50
    assert first.probability_of_loss == second.probability_of_loss
    assert first.return_percentiles.model_dump() == second.return_percentiles.model_dump()


def test_different_seed_differs() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=90), _trade(entry=80, exit_px=88)]
    first = PathDependentMonteCarlo(_cfg(random_seed=1, simulations=120)).run(trades)
    second = PathDependentMonteCarlo(_cfg(random_seed=2, simulations=120)).run(trades)
    assert first.final_capital_percentiles.model_dump() != second.final_capital_percentiles.model_dump()


def test_empty_and_single_trade() -> None:
    empty = PathDependentMonteCarlo(_cfg()).run([])
    assert empty.verdict is MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    assert empty.sample_quality is SampleQuality.INVALID
    assert empty.final_capital_percentiles.p50 == pytest.approx(100_000.0)

    one = PathDependentMonteCarlo(_cfg(simulations=10)).run([_trade(entry=100, exit_px=110)])
    assert one.source_trade_count == 1
    assert one.sample_quality is SampleQuality.EXTREMELY_LOW
    assert one.verdict is MonteCarloVerdict.INSUFFICIENT_EVIDENCE


def test_small_capital_does_not_crash() -> None:
    cfg = _cfg(
        initial_capital=50.0,
        position_percent=10.0,
        min_quantity=1.0,
        allow_fractional_shares=False,
    )
    result = PathDependentMonteCarlo(cfg).run([_trade(entry=1000, exit_px=1100)])
    assert result.median_case is not None
    assert result.median_case.final_equity == pytest.approx(50.0)
    assert result.median_case.trade_count == 0


def test_percent_of_equity_increases_size_after_win() -> None:
    exec_cfg = execution_config_from_mc(
        initial_capital=100_000.0,
        sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
        position_percent=50.0,
        fixed_cash_amount=None,
        slippage_bps=0.0,
        brokerage_rate=0.0,
        brokerage_flat=0.0,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )
    first = round_trip_cash_pnl(cash=100_000.0, entry_price=100.0, exit_price=110.0, config=exec_cfg)
    second = round_trip_cash_pnl(cash=first["cash"], entry_price=100.0, exit_price=95.0, config=exec_cfg)
    assert first["allocated"] == pytest.approx(50_000.0)
    assert first["cash"] == pytest.approx(105_000.0)
    assert second["allocated"] == pytest.approx(52_500.0)
    assert second["allocated"] > first["allocated"]


def test_percent_of_equity_decreases_size_after_loss() -> None:
    exec_cfg = execution_config_from_mc(
        initial_capital=100_000.0,
        sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
        position_percent=50.0,
        fixed_cash_amount=None,
        slippage_bps=0.0,
        brokerage_rate=0.0,
        brokerage_flat=0.0,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )
    first = round_trip_cash_pnl(cash=100_000.0, entry_price=100.0, exit_price=95.0, config=exec_cfg)
    second = round_trip_cash_pnl(cash=first["cash"], entry_price=100.0, exit_price=110.0, config=exec_cfg)
    assert first["cash"] == pytest.approx(97_500.0)
    assert second["allocated"] == pytest.approx(48_750.0)
    assert second["allocated"] < first["allocated"]


def test_path_dependency_final_equity_differs_with_costs() -> None:
    exec_cfg = execution_config_from_mc(
        initial_capital=100_000.0,
        sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
        position_percent=50.0,
        fixed_cash_amount=None,
        slippage_bps=0.0,
        brokerage_rate=0.0,
        brokerage_flat=250.0,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )

    def run(seq: list[tuple[float, float]]) -> float:
        cash = 100_000.0
        for entry, exit_px in seq:
            cash = round_trip_cash_pnl(
                cash=cash,
                entry_price=entry,
                exit_price=exit_px,
                config=exec_cfg,
            )["cash"]
        return cash

    first = run([(100.0, 110.0), (100.0, 95.0)])
    second = run([(100.0, 95.0), (100.0, 110.0)])
    assert first != pytest.approx(second)


def test_shuffle_engine_is_path_dependent() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=95)]
    cfg = _cfg(
        simulations=40,
        sampling_method=SamplingMethod.TRADE_SHUFFLE,
        position_percent=50.0,
        brokerage_flat=200.0,
        brokerage_rate=0.0,
        store_simulation_summaries=True,
        min_quantity=1e-9,
    )
    result = PathDependentMonteCarlo(cfg).run(trades)
    finals = {round(s.final_equity, 6) for s in (result.simulation_summaries or [])}
    assert len(finals) >= 2


def test_fixed_cash_sizing() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=90)]
    cfg = _cfg(
        sizing_mode=MonteCarloSizingMode.FIXED_CASH,
        fixed_cash_amount=20_000.0,
        simulations=15,
        sampling_method=SamplingMethod.TRADE_SHUFFLE,
        brokerage_rate=0.0,
        store_simulation_summaries=True,
    )
    result = PathDependentMonteCarlo(cfg).run(trades)
    assert result.position_sizing_mode == "fixed_cash"
    assert result.median_case is not None
    assert result.median_case.trade_count == 2


def test_fixed_cash_requires_amount() -> None:
    with pytest.raises(MonteCarloConfigError):
        PathDependentMonteCarlo(
            _cfg(sizing_mode=MonteCarloSizingMode.FIXED_CASH, fixed_cash_amount=None),
        ).run([_trade(entry=100, exit_px=110)])


def test_matches_a52_broker_equity() -> None:
    exec_cfg = ExecutionConfig(
        initial_capital=100_000.0,
        position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
        percent=50.0,
        slippage_bps=5.0,
        brokerage_rate=0.0003,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )
    ours = round_trip_cash_pnl(
        cash=100_000.0,
        entry_price=100.0,
        exit_price=110.0,
        config=exec_cfg,
    )
    broker = SimulatedBroker(exec_cfg)
    qty = broker.size_buy_quantity(reference_price=100.0)
    broker.submit_market_order(
        MarketOrder(
            symbol="RELIANCE",
            side=OrderSide.BUY,
            quantity=qty,
            submitted_at=TS0,
            reference_price=100.0,
        ),
    )
    broker.submit_market_order(
        MarketOrder(
            symbol="RELIANCE",
            side=OrderSide.SELL,
            quantity=qty,
            submitted_at=TS1,
            reference_price=110.0,
        ),
    )
    assert ours["cash"] == pytest.approx(broker.snapshot().equity)
    assert ours["qty"] == pytest.approx(qty)


def test_slippage_and_brokerage_reduce_equity() -> None:
    zero = execution_config_from_mc(
        initial_capital=100_000.0,
        sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
        position_percent=50.0,
        fixed_cash_amount=None,
        slippage_bps=0.0,
        brokerage_rate=0.0,
        brokerage_flat=0.0,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )
    costly = execution_config_from_mc(
        initial_capital=100_000.0,
        sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
        position_percent=50.0,
        fixed_cash_amount=None,
        slippage_bps=20.0,
        brokerage_rate=0.001,
        brokerage_flat=0.0,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )
    cheap = round_trip_cash_pnl(cash=100_000.0, entry_price=100.0, exit_price=110.0, config=zero)
    expensive = round_trip_cash_pnl(cash=100_000.0, entry_price=100.0, exit_price=110.0, config=costly)
    assert expensive["cash"] < cheap["cash"]
    assert expensive["brokerage"] > 0
    assert expensive["slippage"] > 0


def test_drawdown_losing_streak_ruin() -> None:
    trades = [_trade(entry=100, exit_px=70), _trade(entry=100, exit_px=70)]
    cfg = _cfg(
        simulations=20,
        sampling_method=SamplingMethod.TRADE_SHUFFLE,
        position_percent=80.0,
        ruin_threshold=0.9,
        brokerage_rate=0.0,
        store_simulation_summaries=True,
    )
    result = PathDependentMonteCarlo(cfg).run(trades)
    assert result.median_case is not None
    assert result.median_case.max_drawdown < 0
    assert result.median_case.longest_losing_streak >= 1
    assert result.probability_of_ruin >= 0.0
    assert result.ruin_equity == pytest.approx(90_000.0)


def test_cost_sensitivity_separates_brokerage_and_slippage() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=95)]
    cfg = _cfg(
        include_cost_perturbation=True,
        slippage_range_bps=(0.0, 5.0, 20.0),
        commission_range_mult=(1.0,),
        simulations=30,
    )
    result = PathDependentMonteCarlo(cfg).run(trades)
    assert len(result.cost_sensitivity) == 3
    zero, _base, high = result.cost_sensitivity
    assert zero.slippage_bps == 0.0
    assert high.slippage_cost >= zero.slippage_cost
    assert high.incremental_cost == pytest.approx(high.total_execution_cost - zero.total_execution_cost)
    assert all(row.brokerage_cost >= 0 for row in result.cost_sensitivity)
    assert all(row.median_ending_equity > 0 for row in result.cost_sensitivity)


def test_a56_compatibility_default_engine() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=90)]
    resampling = MonteCarloEngine(
        MonteCarloConfig(simulations=20, initial_capital=10_000, random_seed=3),
    ).run(trades)
    assert resampling.engine_kind == "TradeResamplingMonteCarlo"
    path = MonteCarloEngine(
        _cfg(simulations=20, initial_capital=10_000, random_seed=3, compare_engines=True),
    ).run(trades)
    assert path.engine_kind == "PathDependentPortfolioMonteCarlo"
    assert path.comparison is not None
    assert path.comparison.resampling_median_return == pytest.approx(resampling.return_percentiles.p50)


def test_no_state_leakage() -> None:
    trades = [_trade(entry=100, exit_px=108) for _ in range(6)]
    engine = PathDependentMonteCarlo(_cfg(simulations=25, random_seed=11))
    first = engine.run(trades)
    second = engine.run(trades)
    assert first.final_capital_percentiles.p50 == second.final_capital_percentiles.p50
    other = PathDependentMonteCarlo(_cfg(simulations=25, random_seed=11)).run(trades)
    assert other.probability_of_loss == first.probability_of_loss


def test_sample_quality_gating() -> None:
    tiny = PathDependentMonteCarlo(_cfg(simulations=5_000)).run(
        [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=90)],
    )
    assert tiny.sample_quality is SampleQuality.EXTREMELY_LOW
    assert tiny.verdict is MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    assert any("5,000 simulations generated from 2 historical trades" in w for w in tiny.warnings)

    strong = PathDependentMonteCarlo(_cfg(simulations=50)).run(make_synthetic_trades(100, seed=1))
    assert strong.sample_quality is SampleQuality.STRONGER


def test_report_and_output_schema(tmp_path: Path) -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=95), _trade(entry=80, exit_px=84)]
    result = PathDependentMonteCarlo(_cfg(simulations=25, include_cost_perturbation=True)).run(
        trades,
        strategy="ema_trend",
        symbol="RELIANCE",
    )
    text = format_markdown_report(result)
    for section in (
        "HISTORICAL OBSERVATION",
        "MONTE CARLO CONFIGURATION",
        "PATH-DEPENDENT CAPITAL MODEL",
        "DISTRIBUTION",
        "RISK",
        "COST SENSITIVITY",
        "SAMPLE QUALITY",
        "VERDICT",
    ):
        assert section in text
    dumped = result.model_dump(mode="json")
    assert dumped["engine_kind"] == "PathDependentPortfolioMonteCarlo"
    assert dumped["capital_model"] == "PATH_DEPENDENT_EQUITY"
    assert dumped["position_sizing_mode"] == "percent_of_equity"
    assert "slippage_bps" in dumped["execution_cost_parameters"]
    paths = write_outputs(result, output_dir=tmp_path, stem="A57")
    assert paths["json"].exists()


def test_cli_path_dependent(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "monte_carlo_cli_a57",
        Path("backend/scripts/monte_carlo.py"),
    )
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = tmp_path / "mc"
    code = cli.main(
        [
            "--trades-json",
            str(FIXTURE),
            "--mode",
            "path_dependent",
            "--method",
            "bootstrap",
            "--simulations",
            "40",
            "--seed",
            "42",
            "--initial-capital",
            "100000",
            "--position-percent",
            "10",
            "--output",
            str(out),
        ],
    )
    assert code == 0
    assert list(out.glob("*_monte_carlo.json"))


def test_costs_appear_on_simulation_summary() -> None:
    trades = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=95)]
    result = PathDependentMonteCarlo(
        _cfg(simulations=12, brokerage_rate=0.001, store_simulation_summaries=True),
    ).run(trades)
    assert result.median_case is not None
    assert result.median_case.total_brokerage_cost > 0
    assert result.median_case.total_cost >= result.median_case.total_brokerage_cost
    assert result.median_case.gross_pnl != result.median_case.net_profit


def test_batch_matches_sequential_round_trip() -> None:
    records = [_trade(entry=100, exit_px=110), _trade(entry=100, exit_px=95)]
    trades = trades_from_sources(records)
    exec_cfg = execution_config_from_mc(
        initial_capital=100_000.0,
        sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY,
        position_percent=50.0,
        fixed_cash_amount=None,
        slippage_bps=5.0,
        brokerage_rate=0.0003,
        brokerage_flat=0.0,
        allow_fractional_shares=True,
        min_quantity=1e-9,
    )
    cash = 100_000.0
    for trade in trades:
        cash = round_trip_cash_pnl(
            cash=cash,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            config=exec_cfg,
        )["cash"]
    entries, exits = price_arrays(trades)
    batch = simulate_portfolio_batch(
        entries,
        exits,
        np.array([[0, 1]], dtype=int),
        initial_capital=100_000.0,
        config=exec_cfg,
        ruin_equity=1.0,
    )
    assert float(batch["final"][0]) == pytest.approx(cash)


def test_fixed_fractional_is_percent_of_equity() -> None:
    trades = [_trade(entry=100, exit_px=110)]
    percent = PathDependentMonteCarlo(
        _cfg(sizing_mode=MonteCarloSizingMode.PERCENT_OF_EQUITY, simulations=8),
    ).run(trades)
    fractional = PathDependentMonteCarlo(
        _cfg(sizing_mode=MonteCarloSizingMode.FIXED_FRACTIONAL, simulations=8),
    ).run(trades)
    assert percent.final_capital_percentiles.p50 == fractional.final_capital_percentiles.p50


def test_benchmark_10k_by_100_trades() -> None:
    trades = make_synthetic_trades(100, seed=1)
    cfg = _cfg(simulations=10_000, random_seed=42, include_cost_perturbation=False)
    started = time.perf_counter()
    result = PathDependentMonteCarlo(cfg).run(trades)
    elapsed = time.perf_counter() - started
    assert result.source_trade_count == 100
    assert result.simulations == 10_000
    assert elapsed < 30.0
    print(f"\nA5.7 benchmark 10000 sims x 100 trades: {elapsed:.4f}s")
