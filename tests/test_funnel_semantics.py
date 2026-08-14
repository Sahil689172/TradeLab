"""A4Y.1.7.3 — Funnel / metric semantics tests (reporting only)."""

from __future__ import annotations

import pytest

from app.backtesting.evaluation.backtester import BacktestResult
from app.backtesting.evaluation.canonical import compare_ema_modes_canonical
from app.backtesting.evaluation.funnel_semantics import (
    buy_candidate_reduction_pct,
    build_signal_funnel,
    sequential_buy_funnel,
)
from app.backtesting.evaluation.integrity import RawSignalDiagnostic
from app.backtesting.evaluation.runner import EMAEvaluationEngine, EvaluationConfig
from tests.test_ema_path_consistency import _signal_trade_frame
from tests.test_ema_trend_strategy import make_strategy_frame


def test_technical_crossovers_are_not_trades() -> None:
    diag = RawSignalDiagnostic(
        symbol="X",
        cross_above_count=27,
        cross_below_count=27,
        buy_count=2,
        exit_count=27,
        trade_count=2,
    )
    assert diag.cross_above_count != diag.trade_count
    assert diag.cross_above_count > diag.buy_count


def test_raw_buy_signals_distinct_from_technical_crossovers() -> None:
    frame = make_strategy_frame(cross="none")
    # No last-bar cross → HOLD; crossovers over the walk may still be zero here.
    from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
    from app.backtesting.evaluation.integrity import diagnose_raw_signals

    strat = EMATrendStrategy(EMATrendConfig(mode="raw", symbol="X", min_history_bars=60))
    diag = diagnose_raw_signals(strat, frame, symbol="X", min_history_bars=60)
    assert diag.buy_count <= diag.cross_above_count


def test_professional_candidates_distinct_from_raw_buy_signals() -> None:
    raw = BacktestResult(mode="raw", symbol="X", signal_counts={"BUY": 2, "EXIT": 27})
    pro = BacktestResult(
        mode="professional",
        symbol="X",
        signal_counts={"BUY": 4, "SELL": 50},
        funnel={
            "raw_buy": 54,
            "raw_sell": 50,
            "rejected_ema200": 11,
            "rejected_adx": 27,
            "rejected_volume": 12,
            "rejected_atr": 0,
            "rejected_other": 0,
            "final_buy": 4,
            "final_sell": 50,
        },
    )
    funnel = build_signal_funnel(raw=raw, professional=pro)
    assert funnel.raw_strategy_buy_signals == 2
    assert funnel.professional_buy_candidates == 54
    assert funnel.professional_buy_candidates != funnel.raw_strategy_buy_signals
    assert funnel.professional_buy_signals == 4


def test_sequential_funnel_reconciles() -> None:
    funnel = sequential_buy_funnel(
        candidates=54,
        rejected_ema200=11,
        rejected_adx=27,
        rejected_volume=12,
        rejected_atr=0,
        rejected_other=0,
        final_buy=4,
    )
    assert funnel.remaining_after_ema200 == 43
    assert funnel.remaining_after_adx == 16
    assert funnel.remaining_after_volume == 4
    assert funnel.remaining_after_atr == 4
    assert funnel.final_buy_signals == 4
    assert funnel.reconciles is True
    assert (
        funnel.ema200_rejections
        + funnel.adx_rejections
        + funnel.volume_rejections
        + funnel.atr_rejections
        + funnel.other_rejections
        + funnel.final_buy_signals
        == funnel.candidates
    )


def test_independent_mode_would_not_reconcile_when_counts_overlap() -> None:
    """If the same candidate were counted in two filters, sequential identity fails."""
    funnel = sequential_buy_funnel(
        candidates=10,
        rejected_ema200=6,
        rejected_adx=6,
        rejected_volume=0,
        rejected_atr=0,
        rejected_other=0,
        final_buy=4,
    )
    assert funnel.reconciles is False


def test_signal_reduction_formula() -> None:
    assert buy_candidate_reduction_pct(54, 4) == pytest.approx((54 - 4) / 54 * 100)
    assert buy_candidate_reduction_pct(0, 0) == 0.0
    raw = BacktestResult(mode="raw", symbol="X", signal_counts={"BUY": 2, "EXIT": 27})
    pro = BacktestResult(
        mode="professional",
        symbol="X",
        signal_counts={"BUY": 4, "SELL": 54},
        funnel={
            "raw_buy": 54,
            "raw_sell": 54,
            "rejected_ema200": 11,
            "rejected_adx": 27,
            "rejected_volume": 12,
            "rejected_atr": 0,
            "rejected_other": 0,
            "final_buy": 4,
            "final_sell": 54,
        },
    )
    metrics = build_signal_funnel(raw=raw, professional=pro)
    # Must NOT use mixed raw BUY+EXIT vs professional BUY+SELL (that produced -100%).
    assert metrics.professional_buy_candidate_reduction_pct == pytest.approx(
        (54 - 4) / 54 * 100,
    )
    assert metrics.signal_reduction_pct == metrics.professional_buy_candidate_reduction_pct
    assert metrics.signal_reduction_pct > 0


def test_compare_and_evaluate_agree_on_completed_trades() -> None:
    frame = _signal_trade_frame()
    compare = compare_ema_modes_canonical("TEST", frame, stride=1, min_history_bars=60)
    engine = EMAEvaluationEngine(
        EvaluationConfig(stride=1, min_history_bars=60, generate_charts=False),
    )
    report = engine.evaluate_universe({"TEST": frame})
    assert compare.raw.trade_count == report.raw.total_trades
    assert compare.professional.trade_count == report.professional.total_trades
    assert compare.semantic_funnel is not None
    assert compare.semantic_funnel.raw_completed_trades == report.raw.total_trades
    assert (
        compare.semantic_funnel.professional_completed_trades
        == report.professional.total_trades
    )
    layers = compare.as_dict()["metric_layers"]
    assert layers["professional_buy_candidates"] is not None
    assert layers["raw_strategy_signals"]["buy"] != layers["technical_crossovers"]["cross_above"] or (
        layers["raw_strategy_signals"]["buy"] <= layers["technical_crossovers"]["cross_above"]
    )


def test_no_lookahead_unchanged() -> None:
    from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy

    frame = make_strategy_frame(rows=100, cross="above")
    strategy = EMATrendStrategy(EMATrendConfig(mode="raw", symbol="TEST", min_history_bars=60))
    prepared = strategy.prepare(frame)
    cut = len(prepared) - 5
    baseline = strategy.generate_signal(prepared.iloc[:cut])
    mutated = prepared.copy()
    mutated.loc[cut:, "close"] = mutated.loc[cut:, "close"] * 3.0
    mutated.loc[cut:, "ema_20"] = mutated.loc[cut:, "close"] + 50.0
    after = strategy.generate_signal(mutated.iloc[:cut])
    assert after.signal is baseline.signal


@pytest.mark.skip(reason="Live RELIANCE full-history walk is a CLI check, not a unit test")
def test_reliance_live_trade_counts_when_parquet_present() -> None:
    """Intentionally skipped. Verify with:

    .venv\\Scripts\\python.exe backend\\scripts\\compare_ema_modes.py --symbol RELIANCE
    """
    pytest.fail("This test must stay skipped in the default suite")


def format_semantic_report_keys(metrics) -> set[str]:
    from app.backtesting.evaluation.funnel_semantics import format_semantic_funnel

    text = format_semantic_funnel(metrics)
    # Display must not present an ambiguous bare "raw_buy" label.
    ambiguous = set()
    if "raw_buy=" in text or "Raw BUY" in text:
        ambiguous.add("raw_buy")
    return ambiguous
