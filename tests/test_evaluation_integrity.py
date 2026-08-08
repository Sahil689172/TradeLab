"""Phase A4Y.1.7 — Evaluation integrity / accounting unit tests."""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtesting.evaluation.backtester import (
    BacktestSettings,
    run_long_only_backtest,
)
from app.backtesting.evaluation.integrity import (
    CapitalAllocationMode,
    merge_equal_weight_equity,
    periods_per_year_for_stride,
    resolution_for_stride,
    validate_evaluation_metrics,
)
from app.backtesting.evaluation.metrics import compute_performance, max_drawdown
from app.backtesting.evaluation.statistics import overall_recommendation
from app.backtesting.evaluation.schemas import (
    MetricComparison,
    PerformanceMetrics,
    StatisticalSummary,
    Verdict,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.models import Signal, SignalType, TradePlan


class ScriptedStrategy(BaseStrategy):
    """Deterministic BUY/SELL script for accounting tests."""

    def __init__(self, schedule: dict[str, SignalType], symbol: str = "TEST") -> None:
        self._schedule = schedule
        self._symbol = symbol

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def active_symbol(self) -> str:
        return self._symbol

    def validate(self, features: pd.DataFrame) -> None:
        return None

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        return features.reset_index(drop=True)

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        ts = pd.Timestamp(features.iloc[-1]["date"]).to_pydatetime()
        key = str(pd.Timestamp(ts).date())
        sig = self._schedule.get(key, SignalType.HOLD)
        return Signal(
            symbol=self._symbol,
            timestamp=ts,
            signal=sig,
            confidence=0.8,
            reason="scripted",
        )

    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        close = float(features.iloc[-1]["close"])
        return TradePlan(
            symbol=self._symbol,
            entry_price=close,
            signal=signal.signal,
            stop_loss=max(close * 0.95, 0.01),
            take_profit_1=close * 1.05,
            take_profit_2=close * 1.10,
            holding_period=5,
            risk_reward=2.0,
            confidence=signal.confidence,
            reasons=["scripted"],
            strategy_name=self.name,
        )


def _frame(prices: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp(d) for d, _ in prices],
            "open": [p for _, p in prices],
            "high": [p for _, p in prices],
            "low": [p for _, p in prices],
            "close": [p for _, p in prices],
            "volume": 1000.0,
        },
    )


def test_max_drawdown_100_to_90() -> None:
    max_dd, _, _ = max_drawdown([100.0, 90.0])
    assert max_dd == pytest.approx(0.10)


def test_max_drawdown_100_110_99() -> None:
    max_dd, _, _ = max_drawdown([100.0, 110.0, 99.0])
    assert max_dd == pytest.approx((110.0 - 99.0) / 110.0)


def test_winning_trade_plus_10_percent() -> None:
    """BUY 100 → SELL 110; expect ~+10% gross before costs."""
    frame = _frame(
        [
            ("2024-01-01", 100.0),
            ("2024-01-02", 100.0),
            ("2024-01-03", 110.0),
            ("2024-01-04", 110.0),
        ],
    )
    schedule = {
        "2024-01-02": SignalType.BUY,
        "2024-01-03": SignalType.SELL,
    }
    result = run_long_only_backtest(
        ScriptedStrategy(schedule),
        frame,
        mode="test",
        settings=BacktestSettings(
            initial_capital=100_000.0,
            percent=100.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
            min_history_bars=2,
            stride=1,
        ),
        symbol="TEST",
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(100.0)
    assert trade.exit_price == pytest.approx(110.0)
    assert trade.gross_profit == pytest.approx(trade.quantity * 10.0)
    assert trade.net_profit == pytest.approx(trade.gross_profit)


def test_losing_trade_minus_10_percent() -> None:
    frame = _frame(
        [
            ("2024-01-01", 100.0),
            ("2024-01-02", 100.0),
            ("2024-01-03", 90.0),
            ("2024-01-04", 90.0),
        ],
    )
    schedule = {"2024-01-02": SignalType.BUY, "2024-01-03": SignalType.SELL}
    result = run_long_only_backtest(
        ScriptedStrategy(schedule),
        frame,
        mode="test",
        settings=BacktestSettings(
            initial_capital=100_000.0,
            percent=100.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
            min_history_bars=2,
            stride=1,
        ),
        symbol="TEST",
    )
    assert len(result.trades) == 1
    assert result.trades[0].gross_profit == pytest.approx(-result.trades[0].quantity * 10.0)


def test_zero_trades() -> None:
    frame = _frame([("2024-01-01", 100.0), ("2024-01-02", 101.0), ("2024-01-03", 102.0)])
    result = run_long_only_backtest(
        ScriptedStrategy({}),
        frame,
        mode="test",
        settings=BacktestSettings(min_history_bars=2, stride=1, initial_capital=100_000),
        symbol="TEST",
    )
    assert result.trades == []


def test_two_sequential_trades() -> None:
    frame = _frame(
        [
            ("2024-01-01", 100.0),
            ("2024-01-02", 100.0),  # BUY1
            ("2024-01-03", 105.0),  # SELL1
            ("2024-01-04", 105.0),  # BUY2
            ("2024-01-05", 100.0),  # SELL2
            ("2024-01-06", 100.0),
        ],
    )
    schedule = {
        "2024-01-02": SignalType.BUY,
        "2024-01-03": SignalType.SELL,
        "2024-01-04": SignalType.BUY,
        "2024-01-05": SignalType.SELL,
    }
    result = run_long_only_backtest(
        ScriptedStrategy(schedule),
        frame,
        mode="test",
        settings=BacktestSettings(
            initial_capital=100_000.0,
            percent=100.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
            min_history_bars=2,
            stride=1,
        ),
        symbol="TEST",
    )
    assert len(result.trades) == 2
    assert result.trades[0].exit_reason == "SELL"
    assert result.trades[1].exit_reason == "SELL"


def test_sell_without_position_creates_no_trade() -> None:
    frame = _frame(
        [
            ("2024-01-01", 100.0),
            ("2024-01-02", 100.0),
            ("2024-01-03", 90.0),
        ],
    )
    schedule = {"2024-01-02": SignalType.SELL, "2024-01-03": SignalType.SELL}
    result = run_long_only_backtest(
        ScriptedStrategy(schedule),
        frame,
        mode="test",
        settings=BacktestSettings(min_history_bars=2, stride=1),
        symbol="TEST",
    )
    assert result.trades == []


def test_buy_does_not_pyramid() -> None:
    frame = _frame(
        [
            ("2024-01-01", 100.0),
            ("2024-01-02", 100.0),  # BUY
            ("2024-01-03", 101.0),  # BUY again (ignored)
            ("2024-01-04", 110.0),  # SELL
            ("2024-01-05", 110.0),
        ],
    )
    schedule = {
        "2024-01-02": SignalType.BUY,
        "2024-01-03": SignalType.BUY,
        "2024-01-04": SignalType.SELL,
    }
    result = run_long_only_backtest(
        ScriptedStrategy(schedule),
        frame,
        mode="test",
        settings=BacktestSettings(
            initial_capital=100_000.0,
            percent=100.0,
            slippage_bps=0.0,
            brokerage_rate=0.0,
            min_history_bars=2,
            stride=1,
        ),
        symbol="TEST",
    )
    assert len(result.trades) == 1


def test_manual_accounting_buy_50000_sell_55000() -> None:
    """Initial 100k; buy ~50k notional; sell at +10%; gross ≈ 5k before costs."""
    # 500 shares @ 100 = 50_000; sell @ 110 = 55_000; gross = 5_000
    frame = _frame(
        [
            ("2024-01-01", 100.0),
            ("2024-01-02", 100.0),
            ("2024-01-03", 110.0),
            ("2024-01-04", 110.0),
        ],
    )
    schedule = {"2024-01-02": SignalType.BUY, "2024-01-03": SignalType.SELL}
    result = run_long_only_backtest(
        ScriptedStrategy(schedule),
        frame,
        mode="test",
        settings=BacktestSettings(
            initial_capital=100_000.0,
            percent=50.0,  # deploy half capital → ~50k notional
            slippage_bps=0.0,
            brokerage_rate=0.0,
            min_history_bars=2,
            stride=1,
        ),
        symbol="TEST",
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.quantity == pytest.approx(500.0)
    assert trade.gross_profit == pytest.approx(5_000.0)
    # Final equity = initial + gross (no costs)
    assert result.equity_curve is not None
    assert float(result.equity_curve.iloc[-1]) == pytest.approx(105_000.0)


def test_equal_weight_merge_idle_cash_no_fake_drawdown() -> None:
    """Missing dates must fill with sleeve cash, not 0 (MaxDD>100% root cause)."""
    idx_a = pd.date_range("2024-01-01", periods=5, freq="B")
    idx_b = pd.date_range("2024-01-03", periods=5, freq="B")
    curve_a = pd.Series([50_000, 50_000, 55_000, 55_000, 55_000], index=idx_a)
    curve_b = pd.Series([50_000, 50_000, 50_000, 50_000, 50_000], index=idx_b)
    merged = merge_equal_weight_equity([curve_a, curve_b], initial=100_000.0)
    assert merged is not None
    assert float(merged.min()) >= 0.0
    max_dd, _, _ = max_drawdown(merged.tolist())
    assert max_dd <= 1.0 + 1e-9
    # Should not collapse toward zero on non-overlapping dates
    assert float(merged.min()) > 40_000.0


def test_multiple_stocks_equal_weight_net_return() -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    a = pd.Series([50_000.0, 55_000.0, 55_000.0], index=idx)  # +10%
    b = pd.Series([50_000.0, 50_000.0, 45_000.0], index=idx)  # -10%
    merged = merge_equal_weight_equity([a, b], initial=100_000.0)
    assert merged is not None
    # Portfolio: 100k → 100k ( +5k -5k )
    assert float(merged.iloc[-1]) == pytest.approx(100_000.0)
    perf = compute_performance(
        mode="test",
        trades=[],
        equity_curve=merged,
        initial_capital=100_000.0,
        symbols_evaluated=2,
    )
    assert perf.return_pct == pytest.approx(0.0)


def test_stride_resolution_and_annualisation() -> None:
    assert resolution_for_stride(1).value == "FULL_BACKTEST"
    assert resolution_for_stride(10).value == "FAST_SAMPLED_EVALUATION"
    assert periods_per_year_for_stride(10) == pytest.approx(25.2)


def test_recommendation_blocked_when_raw_zero_trades() -> None:
    raw = PerformanceMetrics(mode="raw", total_trades=0, sharpe_ratio=0.0, max_drawdown=0.0)
    pro = PerformanceMetrics(
        mode="professional",
        total_trades=4,
        sharpe_ratio=0.5,
        max_drawdown=0.1,
        return_pct=0.2,
        final_equity=120_000,
    )
    validity = validate_evaluation_metrics(
        raw_trades=0,
        professional_trades=4,
        raw_max_dd=0.0,
        pro_max_dd=0.1,
        raw_sharpe=0.0,
        pro_sharpe=0.5,
        raw_final_equity=100_000,
        pro_final_equity=120_000,
        stride=1,
    )
    assert validity.ok is False
    assert "baseline_raw_has_zero_trades" in validity.reasons
    comparisons = [
        MetricComparison(
            metric="sharpe_ratio",
            raw_value=0.0,
            professional_value=0.5,
            delta=0.5,
            verdict=Verdict.IMPROVED,
        ),
    ]
    stats = StatisticalSummary(overall_verdict=Verdict.IMPROVED, trade_count_professional=4)
    overall, recommended, summary = overall_recommendation(
        comparisons,
        stats,
        raw=raw,
        professional=pro,
        validity_ok=validity.ok,
        validity_reasons=validity.reasons,
    )
    assert recommended is False
    assert "Validity gates FAILED" in summary


def test_recommendation_blocked_for_sampled_stride() -> None:
    validity = validate_evaluation_metrics(
        raw_trades=5,
        professional_trades=5,
        raw_max_dd=0.1,
        pro_max_dd=0.1,
        raw_sharpe=0.5,
        pro_sharpe=0.6,
        raw_final_equity=100_000,
        pro_final_equity=110_000,
        stride=10,
    )
    assert validity.ok is False
    assert "sampled_evaluation_not_full_backtest" in validity.reasons


def test_recommendation_blocked_when_maxdd_over_100() -> None:
    validity = validate_evaluation_metrics(
        raw_trades=5,
        professional_trades=5,
        raw_max_dd=0.1,
        pro_max_dd=1.064,
        raw_sharpe=0.5,
        pro_sharpe=0.6,
        raw_final_equity=100_000,
        pro_final_equity=110_000,
        stride=1,
    )
    assert validity.ok is False
    assert "professional_max_drawdown_exceeds_100pct" in validity.reasons


def test_capital_mode_enum() -> None:
    assert CapitalAllocationMode.EQUAL_WEIGHT.value == "equal_weight"
