"""Phase A5.6 Monte Carlo — resampling of completed trades only."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from app.backtesting.monte_carlo import (
    MonteCarloConfig,
    MonteCarloEngine,
    SamplingMethod,
    format_markdown_report,
    load_trades_from_json,
    simulate_equity,
    trades_from_sources,
    with_cost_perturbation,
    write_outputs,
)
from app.backtesting.monte_carlo.engine import _sample_indices
from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExitReason
from app.backtesting.position_manager.schemas import Position, PositionStatus

TS0 = datetime(2022, 6, 1, tzinfo=timezone.utc)
TS1 = datetime(2022, 6, 10, tzinfo=timezone.utc)
FIXTURE = Path("tests/fixtures/monte_carlo_trades.json")


def _trade(
    pnl: float,
    *,
    qty: float = 10.0,
    entry: float = 100.0,
    slip: float = 0.0,
    broker: float = 0.0,
) -> ClosedTradeRecord:
    gross = pnl + slip + broker
    exit_px = entry + pnl / qty if qty else entry
    return ClosedTradeRecord(
        symbol="RELIANCE",
        entry_timestamp=TS0,
        exit_timestamp=TS1,
        entry_price=entry,
        exit_price=exit_px,
        quantity=qty,
        gross_profit=gross,
        brokerage=broker,
        slippage=slip,
        net_profit=pnl,
        holding_days=9,
        exit_reason=ExitReason.SELL_RECOMMENDATION,
        strategy_name="ema_trend",
    )


def test_deterministic_seed() -> None:
    trades = [_trade(100), _trade(-40), _trade(80)]
    cfg = MonteCarloConfig(
        simulations=50,
        initial_capital=10_000,
        random_seed=42,
        sampling_method=SamplingMethod.BOOTSTRAP,
    )
    first = MonteCarloEngine(cfg).run(trades)
    second = MonteCarloEngine(cfg).run(trades)
    assert first.final_capital_percentiles.p50 == second.final_capital_percentiles.p50
    assert first.probability_of_loss == second.probability_of_loss
    rng = np.random.default_rng(42)
    a = _sample_indices(rng, 3, SamplingMethod.BOOTSTRAP)
    rng2 = np.random.default_rng(42)
    b = _sample_indices(rng2, 3, SamplingMethod.BOOTSTRAP)
    assert np.array_equal(a, b)


def test_different_seed_produces_different_simulations() -> None:
    idx_a = _sample_indices(np.random.default_rng(1), 8, SamplingMethod.BOOTSTRAP)
    idx_b = _sample_indices(np.random.default_rng(2), 8, SamplingMethod.BOOTSTRAP)
    assert not np.array_equal(idx_a, idx_b)


def test_shuffle_preserves_pnl_distribution() -> None:
    pnls = np.array([100.0, -40.0, 80.0, -10.0])
    idx = _sample_indices(np.random.default_rng(7), 4, SamplingMethod.TRADE_SHUFFLE)
    assert sorted(pnls[idx].tolist()) == sorted(pnls.tolist())
    assert len(np.unique(idx)) == 4


def test_bootstrap_preserves_simulation_trade_count() -> None:
    idx = _sample_indices(np.random.default_rng(3), 5, SamplingMethod.BOOTSTRAP)
    assert idx.shape == (5,)


def test_initial_capital_and_final_capital_and_return() -> None:
    summary = simulate_equity([100.0, -40.0], initial_capital=1_000.0)
    assert summary.final_equity == pytest.approx(1_060.0)
    assert summary.total_return == pytest.approx(0.06)


def test_drawdown_and_maximum_drawdown() -> None:
    summary = simulate_equity([100.0, -300.0], initial_capital=1_000.0)
    assert summary.peak_equity == pytest.approx(1_100.0)
    assert summary.max_drawdown == pytest.approx(800.0 / 1_100.0 - 1.0)
    assert summary.min_equity == pytest.approx(800.0)


def test_losing_streak() -> None:
    summary = simulate_equity([-10.0, -10.0, 5.0, -10.0], initial_capital=1_000.0)
    assert summary.longest_losing_streak == 2
    assert summary.longest_winning_streak == 1
    assert summary.losing_trades == 3


def test_probability_of_loss_and_thresholds() -> None:
    cfg = MonteCarloConfig(
        simulations=200,
        initial_capital=1_000.0,
        random_seed=1,
        sampling_method=SamplingMethod.BOOTSTRAP,
        return_thresholds=(0.10, 0.20),
        drawdown_thresholds=(0.10, 0.20, 0.30),
    )
    result = MonteCarloEngine(cfg).run([_trade(50) for _ in range(6)])
    assert result.probability_of_loss == pytest.approx(0.0)
    assert result.probability_of_profit == pytest.approx(1.0)
    assert result.threshold_probabilities["P(return<0)"] == pytest.approx(0.0)
    assert "P(return>10%)" in result.threshold_probabilities
    assert "P(|maxDD|>20%)" in result.threshold_probabilities

    lost = MonteCarloEngine(cfg).run([_trade(-50) for _ in range(6)])
    assert lost.probability_of_loss == pytest.approx(1.0)
    assert lost.probability_of_profit == pytest.approx(0.0)


def test_ruin_threshold() -> None:
    cfg = MonteCarloConfig(
        simulations=20,
        initial_capital=1_000.0,
        random_seed=0,
        sampling_method=SamplingMethod.TRADE_SHUFFLE,
        ruin_threshold=0.5,
    )
    result = MonteCarloEngine(cfg).run([_trade(-600.0)])
    assert result.ruin_equity == pytest.approx(500.0)
    assert result.probability_of_ruin == pytest.approx(1.0)
    assert "500" in result.ruin_definition


def test_insufficient_trade_warning_and_zero_trades() -> None:
    cfg = MonteCarloConfig(simulations=10_000, initial_capital=10_000, random_seed=42)
    few = MonteCarloEngine(cfg).run([_trade(10), _trade(-5), _trade(8), _trade(-3)])
    assert any("Only 4 historical trades" in w for w in few.warnings)
    assert few.robustness.band.value in {"LOW", "MEDIUM"}

    empty = MonteCarloEngine(cfg).run([])
    assert empty.source_trade_count == 0
    assert any("ZERO_TRADES" in w for w in empty.warnings)
    assert empty.probability_of_loss == 0.0
    assert empty.final_capital_percentiles.p50 == pytest.approx(10_000.0)


def test_all_winning_all_losing_mixed() -> None:
    cfg = MonteCarloConfig(
        simulations=100,
        initial_capital=5_000,
        random_seed=9,
        sampling_method=SamplingMethod.TRADE_SHUFFLE,
    )
    result = MonteCarloEngine(cfg).run(
        [_trade(100), _trade(-50), _trade(80), _trade(-30), _trade(40)],
    )
    assert result.worst_case is not None
    assert result.best_case is not None
    assert result.worst_case.final_equity == pytest.approx(result.best_case.final_equity)
    assert result.historical.net_profit == pytest.approx(140.0)
    assert result.historical.return_pct == pytest.approx(140.0 / 5_000.0)


def test_negative_final_equity_handling() -> None:
    summary = simulate_equity([-150.0], initial_capital=100.0)
    assert summary.final_equity == pytest.approx(-50.0)
    assert summary.total_return == pytest.approx(-1.5)


def test_original_trade_list_is_not_mutated() -> None:
    trades = [_trade(10), _trade(-4)]
    snapshot = [t.model_dump() for t in trades]
    MonteCarloEngine(MonteCarloConfig(simulations=30, initial_capital=1_000, random_seed=4)).run(trades)
    assert [t.model_dump() for t in trades] == snapshot
    assert len(trades) == 2


def test_lookahead_only_completed_trades() -> None:
    open_pos = Position(
        symbol="RELIANCE",
        quantity=10,
        entry_price=100,
        current_price=105,
        entry_timestamp=TS0,
        last_updated_timestamp=TS0,
        stop_loss=90,
        target_1=110,
        target_2=120,
        status=PositionStatus.OPEN,
    )
    converted = trades_from_sources([open_pos, _trade(25)])
    assert len(converted) == 1
    assert converted[0].pnl == pytest.approx(25.0)
    rng_indices = _sample_indices(np.random.default_rng(1), 1, SamplingMethod.TRADE_SHUFFLE)
    assert rng_indices.tolist() == [0]


def test_cost_sensitivity_uses_copy() -> None:
    trade = _trade(100.0, slip=10.0, broker=5.0)
    original_pnl = trade.net_profit
    adjusted = with_cost_perturbation(
        trades_from_sources([trade]),
        slippage_bps=20.0,
        base_slippage_bps=5.0,
        commission_mult=1.0,
    )
    assert trade.net_profit == pytest.approx(original_pnl)
    assert adjusted[0].slippage == pytest.approx(40.0)
    assert adjusted[0].pnl == pytest.approx(trade.gross_profit - 5.0 - 40.0)

    cfg = MonteCarloConfig(
        simulations=40,
        initial_capital=10_000,
        random_seed=42,
        sampling_method=SamplingMethod.BOOTSTRAP,
        include_cost_perturbation=True,
        slippage_range_bps=(0.0, 5.0, 20.0),
        base_slippage_bps=5.0,
    )
    result = MonteCarloEngine(cfg).run([trade, _trade(-20.0, slip=2.0)])
    assert len(result.cost_sensitivity) == 3
    assert result.cost_sensitivity[0].slippage_bps == 0.0


def test_report_generation_and_outputs(tmp_path: Path) -> None:
    trades = load_trades_from_json(FIXTURE)
    assert len(trades) == 5
    cfg = MonteCarloConfig(
        simulations=80,
        initial_capital=10_000,
        random_seed=42,
        sampling_method=SamplingMethod.BOOTSTRAP,
    )
    result = MonteCarloEngine(cfg).run(trades, strategy="ema_trend", symbol="RELIANCE")
    text = format_markdown_report(result)
    assert "TRADELAB MONTE CARLO REPORT" in text
    assert "Overall Robustness" in text
    paths = write_outputs(result, output_dir=tmp_path, stem="RELIANCE_ema_trend")
    assert paths["json"].exists()
    assert paths["md"].exists()
    assert paths["csv"].exists()
    csv = paths["csv"].read_text(encoding="utf-8")
    assert "final_capital" in csv


def test_cli_deterministic_fixture(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "monte_carlo_cli",
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
            "--method",
            "shuffle",
            "--simulations",
            "100",
            "--seed",
            "42",
            "--initial-capital",
            "10000",
            "--output",
            str(out),
        ],
    )
    assert code == 0
    assert list(out.glob("*_monte_carlo.json"))


def test_shuffle_does_not_change_final_capital() -> None:
    trades = [_trade(x) for x in (50, -20, 30, -10, 15)]
    cfg = MonteCarloConfig(
        simulations=60,
        initial_capital=2_000,
        random_seed=11,
        sampling_method=SamplingMethod.TRADE_SHUFFLE,
        store_simulation_summaries=True,
    )
    result = MonteCarloEngine(cfg).run(trades)
    finals = {round(s.final_equity, 8) for s in (result.simulation_summaries or [])}
    assert len(finals) == 1
    assert next(iter(finals)) == pytest.approx(2_065.0)


def test_shuffle_preserves_trade_multiset_vectorized() -> None:
    from app.backtesting.monte_carlo.engine import _sample_index_matrix

    mat = _sample_index_matrix(
        np.random.default_rng(9),
        5,
        40,
        SamplingMethod.TRADE_SHUFFLE,
    )
    assert mat.shape == (40, 5)
    for row in mat:
        assert sorted(row.tolist()) == [0, 1, 2, 3, 4]


def test_bootstrap_samples_with_replacement() -> None:
    from app.backtesting.monte_carlo.engine import _sample_index_matrix

    mat = _sample_index_matrix(
        np.random.default_rng(0),
        4,
        300,
        SamplingMethod.BOOTSTRAP,
    )
    assert mat.shape == (300, 4)
    assert any(len(set(row.tolist())) < 4 for row in mat)


def test_block_bootstrap_preserves_length_and_seed() -> None:
    from app.backtesting.monte_carlo.engine import _sample_index_matrix

    a = _sample_index_matrix(
        np.random.default_rng(12),
        9,
        15,
        SamplingMethod.BLOCK_BOOTSTRAP,
        block_size=3,
    )
    b = _sample_index_matrix(
        np.random.default_rng(12),
        9,
        15,
        SamplingMethod.BLOCK_BOOTSTRAP,
        block_size=3,
    )
    assert a.shape == (15, 9)
    assert np.array_equal(a, b)
    cfg = MonteCarloConfig(
        simulations=30,
        initial_capital=10_000,
        random_seed=12,
        sampling_method=SamplingMethod.BLOCK_BOOTSTRAP,
        block_size=3,
    )
    trades = [_trade(x) for x in (10, -4, 8, -3, 6, -2, 5, -1, 4)]
    first = MonteCarloEngine(cfg).run(trades)
    second = MonteCarloEngine(cfg).run(trades)
    assert first.return_percentiles.p50 == second.return_percentiles.p50
    assert first.block_size == 3


def test_nan_and_infinite_pnl_rejected() -> None:
    from pydantic import ValidationError

    from app.backtesting.monte_carlo.exceptions import MonteCarloDataError
    from app.backtesting.monte_carlo.schemas import MonteCarloTrade

    with pytest.raises(ValidationError):
        MonteCarloTrade(pnl=float("nan"))
    with pytest.raises(ValidationError):
        MonteCarloTrade(pnl=float("inf"))
    cfg = MonteCarloConfig(simulations=5, initial_capital=1_000, random_seed=1)
    constructed = MonteCarloTrade.model_construct(pnl=float("nan"), return_pct=0.0, gross_pnl=0.0)
    with pytest.raises(MonteCarloDataError):
        MonteCarloEngine(cfg).run([constructed])
    infinite = MonteCarloTrade.model_construct(pnl=float("inf"), return_pct=0.0, gross_pnl=0.0)
    with pytest.raises(MonteCarloDataError):
        MonteCarloEngine(cfg).run([infinite])


def test_one_trade_and_tiny_sample_warning() -> None:
    from app.backtesting.monte_carlo.schemas import MonteCarloVerdict, SampleQuality

    cfg = MonteCarloConfig(simulations=10_000, initial_capital=10_000, random_seed=42)
    one = MonteCarloEngine(cfg).run([_trade(25)])
    assert one.source_trade_count == 1
    assert one.sample_quality is SampleQuality.EXTREMELY_LOW
    assert one.verdict is MonteCarloVerdict.INSUFFICIENT_EVIDENCE

    tiny = MonteCarloEngine(cfg).run([_trade(10), _trade(-5)])
    assert tiny.sample_quality is SampleQuality.EXTREMELY_LOW
    assert tiny.verdict is MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    assert any("10,000 simulations generated from 2 historical trades" in w for w in tiny.warnings)
    text = format_markdown_report(tiny)
    assert "INSUFFICIENT_EVIDENCE" in text
    assert "SAMPLE QUALITY" in text


def test_additive_versus_return_based_capital() -> None:
    from app.backtesting.monte_carlo.schemas import CapitalMode
    from app.backtesting.monte_carlo.simulation import simulate_equity as sim

    additive = sim([100.0, -50.0], initial_capital=1_000.0, capital_mode=CapitalMode.ADDITIVE_PNL)
    ret = sim([0.10, -0.05], initial_capital=1_000.0, capital_mode=CapitalMode.RETURN_BASED)
    assert additive.final_equity == pytest.approx(1_050.0)
    assert ret.final_equity == pytest.approx(1_000.0 * 1.10 * 0.95)
    assert additive.final_equity != pytest.approx(ret.final_equity)

    cfg = MonteCarloConfig(
        simulations=20,
        initial_capital=1_000.0,
        random_seed=3,
        sampling_method=SamplingMethod.TRADE_SHUFFLE,
        capital_mode=CapitalMode.RETURN_BASED,
        store_simulation_summaries=True,
    )
    result = MonteCarloEngine(cfg).run([_trade(100.0), _trade(-50.0)])
    assert result.capital_mode is CapitalMode.RETURN_BASED
    finals = {round(s.final_equity, 8) for s in (result.simulation_summaries or [])}
    assert len(finals) == 1
    assert next(iter(finals)) == pytest.approx(1_000.0 * 1.10 * 0.95)


def test_return_based_falls_back_without_notional() -> None:
    from app.backtesting.monte_carlo.schemas import CapitalMode, MonteCarloTrade

    cfg = MonteCarloConfig(
        simulations=10,
        initial_capital=1_000.0,
        random_seed=1,
        capital_mode=CapitalMode.RETURN_BASED,
    )
    trade = MonteCarloTrade(pnl=40.0, return_pct=0.0, quantity=0.0, entry_price=0.0)
    result = MonteCarloEngine(cfg).run([trade])
    assert result.capital_mode is CapitalMode.ADDITIVE_PNL
    assert any("remaining in ADDITIVE_PNL" in w for w in result.warnings)


def test_percentile_linear_definition() -> None:
    from app.backtesting.monte_carlo.engine import _percentiles
    from app.backtesting.monte_carlo.schemas import PERCENTILE_LEVELS

    values = np.arange(1.0, 101.0)
    got = _percentiles(values)
    expected = np.percentile(values, PERCENTILE_LEVELS, method="linear")
    assert got.p01 == pytest.approx(float(expected[0]))
    assert got.p50 == pytest.approx(float(expected[4]))
    assert got.p99 == pytest.approx(float(expected[8]))


def test_no_double_counted_costs() -> None:
    trade = _trade(100.0, slip=10.0, broker=5.0)
    cfg = MonteCarloConfig(
        simulations=40,
        initial_capital=10_000,
        random_seed=42,
        sampling_method=SamplingMethod.BOOTSTRAP,
        include_cost_perturbation=True,
        slippage_range_bps=(5.0,),
        base_slippage_bps=5.0,
        commission_range_mult=(1.0,),
    )
    result = MonteCarloEngine(cfg).run([trade, _trade(-20.0, slip=2.0, broker=1.0)])
    assert len(result.cost_sensitivity) == 1
    row = result.cost_sensitivity[0]
    assert row.incremental_cost == pytest.approx(0.0)
    assert row.base_cost == pytest.approx(row.scenario_cost)
    assert row.median_return == pytest.approx(result.return_percentiles.p50)
    assert row.probability_of_loss == pytest.approx(result.probability_of_loss)


def test_invalid_configuration_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MonteCarloConfig(simulations=0)
    with pytest.raises(ValidationError):
        MonteCarloConfig(initial_capital=0)
    with pytest.raises(ValidationError):
        MonteCarloConfig(ruin_threshold=0)
    with pytest.raises(ValidationError):
        MonteCarloConfig(block_size=0)


def test_extremely_large_pnl_remains_finite() -> None:
    summary = simulate_equity([1e12], initial_capital=1_000_000.0)
    assert np.isfinite(summary.final_equity)
    assert summary.final_equity == pytest.approx(1_000_000.0 + 1e12)


def test_reproducible_json_output(tmp_path: Path) -> None:
    import json

    trades = [_trade(40), _trade(-15), _trade(25), _trade(-10), _trade(8)]
    cfg = MonteCarloConfig(
        simulations=80,
        initial_capital=5_000,
        random_seed=42,
        sampling_method=SamplingMethod.BOOTSTRAP,
    )
    first = MonteCarloEngine(cfg).run(trades, strategy="ema_trend", symbol="RELIANCE")
    second = MonteCarloEngine(cfg).run(trades, strategy="ema_trend", symbol="RELIANCE")
    dump_a = json.dumps(first.model_dump(mode="json", exclude={"simulation_summaries"}), sort_keys=True)
    dump_b = json.dumps(second.model_dump(mode="json", exclude={"simulation_summaries"}), sort_keys=True)
    assert dump_a == dump_b
    paths = write_outputs(first, output_dir=tmp_path, stem="json_repro")
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["seed"] == 42
    assert payload["capital_mode"] == "ADDITIVE_PNL"
    assert payload["engine_kind"] == "TradeResamplingMonteCarlo"
    assert "resampling_limitation" in payload
    other = MonteCarloEngine(cfg.model_copy(update={"random_seed": 99})).run(trades)
    assert first.final_capital_percentiles.model_dump() != other.final_capital_percentiles.model_dump()


def test_report_schema_sections() -> None:
    from app.backtesting.monte_carlo.schemas import MonteCarloVerdict

    result = MonteCarloEngine(
        MonteCarloConfig(simulations=30, initial_capital=10_000, random_seed=2),
    ).run([_trade(10), _trade(-4), _trade(8)])
    text = format_markdown_report(result)
    for section in (
        "HISTORICAL OBSERVATION",
        "MONTE CARLO",
        "DISTRIBUTION",
        "RISK",
        "SAMPLE QUALITY",
        "VERDICT",
        "Monte Carlo percentile interval",
        "Overall Robustness",
    ):
        assert section in text
    dumped = result.model_dump()
    assert result.verdict is MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    assert "sample_quality" in dumped
    assert "capital_mode" in dumped


def test_path_dependent_not_implemented() -> None:
    from app.backtesting.monte_carlo import PathDependentMonteCarlo, PathDependentNotImplementedError

    with pytest.raises(PathDependentNotImplementedError):
        PathDependentMonteCarlo().run([])


def test_synthetic_hundred_trades_sample_quality() -> None:
    from app.backtesting.monte_carlo import make_synthetic_trades
    from app.backtesting.monte_carlo.schemas import SampleQuality

    trades = make_synthetic_trades(100, seed=1)
    assert len(trades) == 100
    result = MonteCarloEngine(
        MonteCarloConfig(
            simulations=200,
            initial_capital=1_000_000,
            random_seed=42,
            sampling_method=SamplingMethod.BOOTSTRAP,
        ),
    ).run(trades)
    assert result.source_trade_count == 100
    assert result.sample_quality is SampleQuality.STRONGER
    assert result.engine_kind == "TradeResamplingMonteCarlo"
    assert result.capital_mode.value == "ADDITIVE_PNL"

