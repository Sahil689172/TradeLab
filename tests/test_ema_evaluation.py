"""Unit tests for Phase A4Y.1.5 Professional EMA Evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.backtesting.evaluation import (
    EMAEvaluationEngine,
    EvaluationConfig,
    Verdict,
    cagr,
    compare_metrics,
    compute_performance,
    max_drawdown,
    paired_trade_delta,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    synthetic_features,
)
from app.backtesting.evaluation.charts import generate_all_charts, plot_equity_curve
from app.backtesting.evaluation.export import (
    export_evaluation_json,
    export_metrics_csv,
)
from app.backtesting.evaluation.signals import build_filter_effectiveness, build_signal_funnel
from app.backtesting.evaluation.backtester import BacktestResult


def test_profit_factor() -> None:
    assert profit_factor(200.0, -100.0) == pytest.approx(2.0)
    assert profit_factor(100.0, 0.0) == float("inf")


def test_max_drawdown() -> None:
    equity = [100, 110, 105, 90, 95, 120]
    max_dd, avg_dd, longest = max_drawdown(equity)
    assert max_dd == pytest.approx((110 - 90) / 110)
    assert avg_dd >= 0
    assert longest >= 1


def test_sharpe_and_sortino() -> None:
    rets = [0.01, -0.005, 0.012, 0.004, -0.002, 0.008]
    s = sharpe_ratio(rets)
    so = sortino_ratio(rets)
    assert s != 0.0
    assert so != 0.0


def test_cagr() -> None:
    assert cagr(100_000, 121_000, 2.0) == pytest.approx(0.1, rel=1e-3)


def test_compute_performance_from_trades() -> None:
    trades = [
        {"net_profit": 100.0, "brokerage": 1.0, "slippage": 0.5, "holding_days": 3, "quantity": 10, "entry_price": 100},
        {"net_profit": -40.0, "brokerage": 1.0, "slippage": 0.5, "holding_days": 2, "quantity": 10, "entry_price": 100},
        {"net_profit": 50.0, "brokerage": 1.0, "slippage": 0.2, "holding_days": 5, "quantity": 8, "entry_price": 100},
    ]
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    equity = pd.Series([100000, 100050, 100020, 100080, 100060, 100100, 100090, 100120, 100110, 100150], index=idx)
    metrics = compute_performance(
        mode="raw",
        trades=trades,
        equity_curve=equity,
        initial_capital=100_000,
    )
    assert metrics.total_trades == 3
    assert metrics.winning_trades == 2
    assert metrics.losing_trades == 1
    assert metrics.win_rate == pytest.approx(2 / 3)
    assert metrics.profit_factor > 1
    assert metrics.net_profit == pytest.approx(110.0)
    assert metrics.max_drawdown >= 0
    assert metrics.commission_paid == pytest.approx(3.0)


def test_signal_and_filter_funnel() -> None:
    raw = BacktestResult(mode="raw", symbol="X", signal_counts={"BUY": 10, "SELL": 4, "HOLD": 50})
    pro = BacktestResult(
        mode="professional",
        symbol="X",
        signal_counts={"BUY": 4, "SELL": 2, "HOLD": 58},
        funnel={
            "raw_buy": 10,
            "raw_sell": 4,
            "rejected_ema200": 3,
            "rejected_adx": 2,
            "rejected_volume": 1,
            "rejected_atr": 0,
            "rejected_other": 2,
            "final_buy": 4,
            "final_sell": 2,
        },
    )
    funnel = build_signal_funnel(raw=raw, professional=pro)
    assert funnel.raw_buy == 10
    assert funnel.rejected_ema200 == 3
    assert funnel.professional_buy == 4
    assert funnel.acceptance_rate == pytest.approx(6 / 14)
    assert funnel.signal_reduction_pct == pytest.approx((14 - 6) / 14 * 100)

    raw_perf = compute_performance(mode="raw", trades=[{"net_profit": 10, "brokerage": 0, "slippage": 0, "holding_days": 1, "quantity": 1, "entry_price": 1}], equity_curve=None, initial_capital=1000)
    pro_perf = compute_performance(mode="professional", trades=[{"net_profit": 20, "brokerage": 0, "slippage": 0, "holding_days": 1, "quantity": 1, "entry_price": 1}], equity_curve=None, initial_capital=1000)
    rows = build_filter_effectiveness(funnel, raw_perf=raw_perf, pro_perf=pro_perf)
    assert any(r.filter_name == "EMA200" for r in rows)
    assert any(r.filter_name == "ALL_FILTERS" for r in rows)


def test_comparison_engine_verdicts() -> None:
    raw = compute_performance(
        mode="raw",
        trades=[{"net_profit": n, "brokerage": 0, "slippage": 0, "holding_days": 2, "quantity": 1, "entry_price": 100} for n in [10, -5, 8, -3]],
        equity_curve=pd.Series([100, 101, 100.5, 102, 101, 103], index=pd.date_range("2024-01-01", periods=6, freq="B")),
        initial_capital=100,
    )
    pro = compute_performance(
        mode="professional",
        trades=[{"net_profit": n, "brokerage": 0, "slippage": 0, "holding_days": 2, "quantity": 1, "entry_price": 100} for n in [12, -2, 15]],
        equity_curve=pd.Series([100, 101, 101.5, 103, 104, 106], index=pd.date_range("2024-01-01", periods=6, freq="B")),
        initial_capital=100,
    )
    rows = compare_metrics(raw, pro)
    assert any(r.metric == "sharpe_ratio" for r in rows)
    assert all(isinstance(r.verdict, Verdict) for r in rows)
    stats = paired_trade_delta([10, -5, 8, -3], [12, -2, 15])
    assert stats.trade_count_raw == 4
    assert stats.trade_count_professional == 3


def test_json_and_csv_export(tmp_path: Path) -> None:
    engine = EMAEvaluationEngine(
        EvaluationConfig(out_dir=tmp_path, generate_charts=False, stride=5, min_history_bars=60),
    )
    frames = {"RELIANCE": synthetic_features(symbol="RELIANCE", bars=120)}
    report = engine.evaluate_universe(frames)
    json_path = export_evaluation_json(report, tmp_path / "report.json")
    csv_path = export_metrics_csv(report, tmp_path / "metrics.csv")
    assert json_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["phase"] == "A4Y.1.5"
    assert "raw" in payload and "professional" in payload
    assert "signal_funnel" in payload
    assert csv_path.is_file()
    assert "sharpe_ratio" in csv_path.read_text(encoding="utf-8")


def test_charts_generation(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    idx = pd.date_range("2024-01-01", periods=80, freq="B")
    raw = pd.Series(100000 + pd.Series(range(80)).cumsum().values, index=idx, dtype=float)
    pro = pd.Series(100000 + pd.Series(range(80)).cumsum().values * 1.2, index=idx, dtype=float)
    paths = generate_all_charts(
        out_dir=tmp_path / "charts",
        raw_equity=raw,
        pro_equity=pro,
        raw_pnls=[10, -5, 8],
        pro_pnls=[12, -2, 15, 4],
        funnel_labels=["Raw BUY", "Final BUY"],
        funnel_values=[10, 4],
        filter_labels=["EMA200", "ADX"],
        filter_values=[3, 2],
    )
    assert paths["equity_curve"].is_file()
    assert paths["signal_funnel"].is_file()
    assert paths["filter_funnel"].is_file()
    assert plot_equity_curve(raw, pro, tmp_path / "eq2.png").is_file()


def test_charts_skip_without_matplotlib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.backtesting.evaluation.charts as charts_mod

    monkeypatch.setattr(charts_mod, "matplotlib_available", lambda: False)
    paths = generate_all_charts(
        out_dir=tmp_path / "charts",
        raw_equity=None,
        pro_equity=None,
        raw_pnls=[],
        pro_pnls=[],
        funnel_labels=["A"],
        funnel_values=[1],
        filter_labels=["B"],
        filter_values=[1],
    )
    assert paths == {}


def test_end_to_end_evaluation_engine(tmp_path: Path) -> None:
    engine = EMAEvaluationEngine(
        EvaluationConfig(
            out_dir=tmp_path,
            generate_charts=False,
            stride=3,
            min_history_bars=60,
            initial_capital=500_000,
        ),
    )
    frames = {
        "RELIANCE": synthetic_features(symbol="RELIANCE", bars=130),
        "TCS": synthetic_features(symbol="TCS", bars=130),
    }
    report = engine.evaluate_universe(frames)
    assert report.raw.mode == "raw"
    assert report.professional.mode == "professional"
    assert len(report.metric_comparisons) > 0
    assert report.signal_funnel is not None
    paths = engine.export_all(report)
    assert paths["json"].is_file()
    assert paths["markdown"].is_file()
    # Charts optional — with generate_charts=False they are skipped
    assert "chart_equity_curve" not in paths or paths["json"].is_file()