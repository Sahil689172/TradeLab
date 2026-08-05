"""Unit tests for Phase A4X.8 Strategy Audit & Comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.strategy_engine.audit import (
    StrategyAuditor,
    aggregate_metrics,
    audit_from_plans,
    build_comparison,
    build_readiness_report,
    build_scorecard,
    export_audit,
    format_audit_report,
    format_comparison_table,
    format_scorecard_table,
    verify_filter_integration,
    win_expectancy,
)
from app.strategy_engine.configuration import (
    default_system_config,
    list_bound_strategies,
    materialize_strategy,
)
from app.strategy_engine.models import SignalType, TradePlan
from app.strategy_engine.symbols import attach_symbol


def _plan(
    *,
    signal: SignalType = SignalType.BUY,
    confidence: float = 0.8,
    risk_reward: float = 2.0,
    holding: int = 10,
    strategy_name: str = "ema_trend",
) -> TradePlan:
    return TradePlan(
        symbol="RELIANCE",
        entry_price=100.0,
        signal=signal,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=115.0,
        holding_period=holding,
        risk_reward=risk_reward,
        confidence=confidence,
        reasons=["unit"],
        strategy_name=strategy_name,
    )


def _synthetic_features(*, bars: int = 90, symbol: str = "RELIANCE") -> pd.DataFrame:
    rows = []
    price = 100.0
    day = pd.Timestamp("2024-06-03 09:15")
    for index in range(bars):
        price = price + (0.3 if index % 5 else -0.1)
        close = price
        ts = day + pd.Timedelta(minutes=15 * (index % 24))
        if index % 24 == 0 and index:
            day = day + pd.Timedelta(days=1)
        rows.append(
            {
                "date": ts,
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100_000 + index * 1000,
                "relative_volume_20": 1.4,
                "volume_sma_20": 90_000,
                "atr_14": 1.5,
                "ema_9": close * 1.001,
                "ema_20": close * 1.002,
                "ema_21": close * 1.002,
                "ema_50": close * 0.998,
                "ema_200": close * 0.95,
                "sma_200": close * 0.94,
                "adx_14": 28.0,
                "rsi_14": 55.0,
                "vwap": close * 0.999,
                "gap_pct": 0.4,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def test_win_expectancy_formula() -> None:
    # 80% win @ 2R → 0.8*2 - 0.2 = 1.4
    assert win_expectancy(0.8, 2.0) == pytest.approx(1.4)


def test_aggregate_metrics_counts_signals() -> None:
    plans = [
        _plan(signal=SignalType.BUY),
        _plan(signal=SignalType.BUY, confidence=0.6),
        _plan(signal=SignalType.SELL, confidence=0.7, risk_reward=1.5),
        _plan(signal=SignalType.HOLD, confidence=0.2, risk_reward=0.0, holding=0),
    ]
    metrics = aggregate_metrics(
        strategy_name="ema_trend",
        symbol="RELIANCE",
        plans=plans,
        filter_accepted=2,
        filter_rejected=1,
        filter_integration_ok=True,
    )
    assert metrics.buy_signals == 2
    assert metrics.sell_signals == 1
    assert metrics.hold_signals == 1
    assert metrics.evaluations == 4
    assert metrics.filter_acceptance_rate == pytest.approx(2 / 3)
    assert metrics.filter_rejection_rate == pytest.approx(1 / 3)
    assert metrics.average_confidence > 0
    assert metrics.average_hold >= 0
    assert metrics.ready is True


def test_scorecard_and_comparison() -> None:
    m1 = audit_from_plans(
        strategy_name="ema_trend",
        symbol="RELIANCE",
        plans=[_plan(), _plan(signal=SignalType.HOLD, confidence=0.1)],
        filter_accepted=1,
        filter_rejected=0,
        filter_integration_ok=True,
    )
    m2 = audit_from_plans(
        strategy_name="vwap",
        symbol="RELIANCE",
        plans=[_plan(strategy_name="vwap", confidence=0.5, risk_reward=1.2)],
        filter_accepted=0,
        filter_rejected=1,
        filter_integration_ok=True,
    )
    scorecard = build_scorecard([m1, m2], symbol="RELIANCE")
    assert scorecard.total_count == 2
    assert scorecard.ready_count == 2
    comparison = build_comparison(scorecard)
    assert len(comparison.rows) == 2
    assert comparison.rows[0].rank == 1
    assert comparison.rows[0].composite_score >= comparison.rows[1].composite_score
    text = format_scorecard_table(scorecard)
    assert "ema_trend" in text
    assert "vwap" in text
    assert "rank" in format_comparison_table(comparison)


def test_readiness_report_checks() -> None:
    metrics = [
        audit_from_plans(
            strategy_name="ema_trend",
            symbol="RELIANCE",
            plans=[_plan()],
            filter_accepted=1,
            filter_integration_ok=True,
        ),
    ]
    scorecard = build_scorecard(metrics, symbol="RELIANCE")
    comparison = build_comparison(scorecard)
    report = build_readiness_report(
        symbol="RELIANCE",
        metrics=metrics,
        scorecard=scorecard,
        comparison=comparison,
        tests_passed=True,
    )
    names = {c.name for c in report.checks}
    assert names == {
        "no_failing_tests",
        "filter_integration_passes",
        "scorecard_generated",
        "comparison_generated",
        "professional_report_generated",
    }
    assert all(c.passed for c in report.checks)
    assert report.overall_ready is True


def test_export_json_and_csv(tmp_path: Path) -> None:
    metrics = [
        audit_from_plans(
            strategy_name="ema_trend",
            symbol="RELIANCE",
            plans=[_plan(), _plan(signal=SignalType.SELL)],
            filter_accepted=2,
            filter_rejected=0,
            filter_integration_ok=True,
        ),
    ]
    auditor = StrategyAuditor()
    report = auditor.build_report(metrics, symbol="RELIANCE")
    json_path = tmp_path / "audit.json"
    csv_path = tmp_path / "audit.csv"
    export_audit(report, json_path=json_path, csv_path=csv_path)
    assert json_path.is_file()
    assert csv_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["symbol"] == "RELIANCE"
    assert "scorecard" in payload
    assert "comparison" in payload
    assert "readiness" in payload
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "strategy_name" in csv_text
    assert "ema_trend" in csv_text
    assert "SCORECARD" in format_audit_report(report)


def test_filter_integration_for_ema() -> None:
    cfg = default_system_config(
        "ema_trend",
        parameters={"symbol": "RELIANCE"},
        filters={"enable_pipeline": True},
    )
    strategy = materialize_strategy(cfg)
    ok, detail = verify_filter_integration(
        strategy,
        features=_synthetic_features().tail(1),
    )
    assert ok is True, detail


def test_auditor_runs_ema_on_synthetic() -> None:
    features = _synthetic_features(bars=90)
    auditor = StrategyAuditor(
        min_bars=60,
        stride=15,
        max_evaluations=5,
        apply_filters=True,
    )
    strategy = auditor.materialize("ema_trend", symbol="RELIANCE")
    metrics = auditor.audit_one(strategy, features, symbol="RELIANCE")
    assert metrics.strategy_name == "ema_trend"
    assert metrics.filter_integration_ok is True
    assert metrics.evaluations >= 1
    assert (
        metrics.buy_signals
        + metrics.sell_signals
        + metrics.hold_signals
        + metrics.exit_signals
        == metrics.evaluations
    )


def test_auditor_all_twelve_produce_scorecard() -> None:
    features = _synthetic_features(bars=100)
    auditor = StrategyAuditor(
        min_bars=70,
        stride=20,
        max_evaluations=3,
        apply_filters=True,
    )
    report = auditor.run(features, symbol="RELIANCE")
    assert len(report.metrics) == 12
    assert {m.strategy_name for m in report.metrics} == set(list_bound_strategies())
    assert report.scorecard.total_count == 12
    assert len(report.comparison.rows) == 12
    assert report.readiness.checks
    assert all(m.filter_integration_ok for m in report.metrics)
    assert any(c.name == "scorecard_generated" and c.passed for c in report.readiness.checks)
    assert any(c.name == "comparison_generated" and c.passed for c in report.readiness.checks)
    assert any(
        c.name == "professional_report_generated" and c.passed
        for c in report.readiness.checks
    )
