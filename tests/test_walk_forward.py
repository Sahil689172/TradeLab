"""A5.9 walk-forward / out-of-sample validation."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.backtesting.order_execution.costs import brokerage_charge, execution_price
from app.backtesting.order_execution.orders import OrderSide
from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExitReason
from app.backtesting.walk_forward import (
    CapitalMode,
    SearchSpace,
    WalkForwardConfig,
    WalkForwardEngine,
    cap_frame,
    format_markdown_report,
    generate_windows,
    write_outputs,
)
from app.backtesting.walk_forward.execution import PeriodRun, run_period
from app.backtesting.walk_forward.equity import (
    assert_market_timestamps_only,
    canonical_equity_series,
    market_equity_series,
    sanitize_equity_series,
)
from app.backtesting.walk_forward.isolation import DateCappedMarket, frame_max_date
from app.backtesting.walk_forward.optimizer import select_on_train
from app.backtesting.walk_forward.sample_metrics import build_sample_aware_performance
from app.backtesting.walk_forward.schemas import (
    CandidateMetrics,
    ExecutionAttribution,
    MetricStatus,
    SelectionEligibility,
    TrainSelectionDiagnostic,
)
from app.backtesting.walk_forward.search import config_key
from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategies.ema_trend import EMATrendConfig
from app.strategy_engine.models import SignalType


def _ohlcv(n: int = 50, start: str = "2020-01-02", *, price: float = 100.0, step: float = 0.25) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=n)
    rows = []
    for index, ts in enumerate(dates):
        close = price + index * step
        rows.append(
            {
                "date": ts,
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000 + index * 1000,
            },
        )
    return pd.DataFrame(rows)


def _features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    close = frame["close"]
    for period in (9, 12, 20, 21, 26, 50, 200):
        frame[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()
    frame["adx_14"] = 28.0
    frame["atr_14"] = 1.5
    frame["rsi_14"] = 55.0
    frame["relative_volume_20"] = 1.8
    frame["volume_sma_20"] = frame["volume"].rolling(20, min_periods=1).mean()
    return frame


class _StaticMarket:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_history(self, symbol: str) -> pd.DataFrame:
        return self._frames[symbol.upper()].copy()


class _StaticFeatures:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def load_features(self, symbol: str) -> pd.DataFrame | None:
        return self._frames[symbol.upper()].copy()


class _PulseEvaluator:
    def __init__(self) -> None:
        self._bought = False
        self._sold = False

    def evaluate(self, *, strategy, symbol, window, timestamp, timeframe):  # noqa: ANN001
        close = float(window.iloc[-1]["close"])
        if not self._bought:
            self._bought = True
            signal = SignalType.BUY
        elif not self._sold:
            self._sold = True
            signal = SignalType.SELL
        else:
            signal = SignalType.HOLD
        return TradeRecommendation(
            strategy_name="pulse",
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            signal=signal,
            entry_price=close,
            stop_loss=close * 0.98,
            target_1=close * 1.02,
            target_2=close * 1.04,
            risk_reward=1.0,
            confidence=60.0,
            expected_holding_period=5,
            reasons=["walk-forward pulse"],
            trend_direction=TrendDirection.SIDEWAYS,
            market_structure=TrendDirection.SIDEWAYS,
        )


def _search(**kwargs: object) -> SearchSpace:
    base = dict(
        ema_pair_presets=("9_21",),
        adx_thresholds=(20.0,),
        ema200_filters=(False,),
        max_candidates=8,
    )
    base.update(kwargs)
    return SearchSpace(**base)


def _cfg(**kwargs: object) -> WalkForwardConfig:
    base: dict[str, object] = dict(
        train_days=12,
        test_days=5,
        step_days=12,
        min_history_bars=3,
        initial_capital=100_000.0,
        search=_search(),
        include_monte_carlo=False,
        include_charts=False,
        slippage_bps=0.0,
        brokerage_rate=0.0,
    )
    base.update(kwargs)
    return WalkForwardConfig(**base)


def _metrics(
    *,
    key: str = "fast=9,slow=21,adx=20,ema200=0",
    ret: float = 0.1,
    sharpe: float = 1.0,
    trades: int = 1,
    net: float = 1000.0,
    costs: float = 0.0,
) -> CandidateMetrics:
    return CandidateMetrics(
        config_key=key,
        parameters={
            "fast_ema": 9,
            "slow_ema": 21,
            "adx_threshold": 20.0,
            "ema200_filter": False,
            "mode": "professional",
        },
        score=sharpe + ret,
        return_pct=ret,
        sharpe=sharpe,
        sortino=sharpe,
        max_drawdown=0.05,
        win_rate=0.5,
        profit_factor=1.5,
        trade_count=trades,
        total_costs=costs,
        net_profit=net,
        gross_profit=net + costs,
    )


def _ledger_trade(
    symbol: str,
    entry: datetime,
    *,
    gross_profit: float,
    brokerage: float,
    slippage: float,
    entry_price: float = 100.0,
    quantity: float = 1.0,
) -> ClosedTradeRecord:
    net_profit = gross_profit - brokerage - slippage
    return ClosedTradeRecord(
        symbol=symbol,
        entry_timestamp=entry,
        exit_timestamp=entry + timedelta(days=2),
        entry_price=entry_price,
        exit_price=entry_price + gross_profit / quantity,
        quantity=quantity,
        gross_profit=gross_profit,
        brokerage=brokerage,
        slippage=slippage,
        net_profit=net_profit,
        holding_days=2,
        exit_reason=ExitReason.SELL_RECOMMENDATION,
        strategy_name="ema_professional",
    )


def _closed(symbol: str, entry: datetime, pnl: float, price: float = 100.0) -> ClosedTradeRecord:
    return ClosedTradeRecord(
        symbol=symbol,
        entry_timestamp=entry,
        exit_timestamp=entry + timedelta(days=2),
        entry_price=price,
        exit_price=price + pnl,
        quantity=1.0,
        gross_profit=pnl,
        brokerage=0.0,
        slippage=0.0,
        net_profit=pnl,
        holding_days=2,
        exit_reason=ExitReason.SELL_RECOMMENDATION,
        strategy_name="ema_professional",
    )


def _frozen(symbol: str = "RELIANCE") -> EMATrendConfig:
    return EMATrendConfig.professional(
        symbol=symbol,
        min_history_bars=3,
        ema200_filter=False,
        ema_pair_preset=None,
        fast_ema=9,
        slow_ema=21,
    )


def _train_diagnostic(**kwargs: object) -> TrainSelectionDiagnostic:
    base: dict[str, object] = dict(
        minimum_training_trades=5,
        candidates_evaluated=2,
        eligible_count=2,
        ineligible_count=0,
        zero_trade_candidates=0,
        selected_training_trade_count=5,
        fallback_count=0,
        selected_eligibility=SelectionEligibility.ELIGIBLE,
        note="test stub",
    )
    base.update(kwargs)
    return TrainSelectionDiagnostic(**base)


class _Scripted:
    def __init__(self, pnl_by_year: dict[int, float] | None = None) -> None:
        self.calls: list[tuple[str, date, date, float, str]] = []
        self.selects: list[tuple[str, date, date]] = []
        self.pnl_by_year = pnl_by_year or {}

    def selector(self, *, symbol: str, train_start: date, train_end: date, **kwargs: object):
        self.selects.append((symbol, train_start, train_end))
        cfg = _frozen(symbol)
        return cfg, _metrics(key=config_key(cfg)), 2, train_end, _train_diagnostic()

    def runner(
        self,
        *,
        symbol: str,
        strategy_config: EMATrendConfig,
        start: date,
        end: date,
        initial_capital: float,
        **kwargs: object,
    ) -> PeriodRun:
        key = config_key(strategy_config)
        self.calls.append((symbol, start, end, initial_capital, key))
        pnl = float(self.pnl_by_year.get(start.year, 1000.0))
        entry = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        trade = _closed(symbol, entry, pnl)
        equity = canonical_equity_series(
            [trade],
            initial=initial_capital,
            period_start=start,
            period_end=end,
        )
        metrics = _metrics(key=key, ret=pnl / initial_capital if initial_capital else 0.0, net=pnl, trades=1)
        return PeriodRun(
            trades=[trade],
            equity=equity,
            metrics=metrics,
            used_max=end,
            frozen_key=key,
            attribution=ExecutionAttribution(
                signals_generated=2,
                orders_attempted=2,
                orders_filled=2,
                completed_trades=1,
            ),
            requested_strategy="ema_professional",
            execution_engine="ema_trend",
        )


class _PerSymbolScripted(_Scripted):
    """Scripted runner with symbol-specific P&L maps."""

    def __init__(
        self,
        pnl_by_symbol: dict[str, float] | None = None,
        pnl_by_year: dict[int, float] | None = None,
    ) -> None:
        super().__init__(pnl_by_year=pnl_by_year)
        self.pnl_by_symbol = pnl_by_symbol or {}
        self.select_keys: dict[str, str] = {}

    def selector(self, *, symbol: str, train_start: date, train_end: date, **kwargs: object):
        cfg = _frozen(symbol)
        key = config_key(cfg)
        self.select_keys[symbol] = key
        self.selects.append((symbol, train_start, train_end))
        return cfg, _metrics(key=key), 2, train_end, _train_diagnostic()

    def runner(
        self,
        *,
        symbol: str,
        strategy_config: EMATrendConfig,
        start: date,
        end: date,
        initial_capital: float,
        **kwargs: object,
    ) -> PeriodRun:
        if symbol in self.pnl_by_symbol:
            pnl = float(self.pnl_by_symbol[symbol])
        else:
            pnl = float(self.pnl_by_year.get(start.year, 1000.0))
        entry = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        trade = _closed(symbol, entry, pnl)
        key = config_key(strategy_config)
        self.calls.append((symbol, start, end, initial_capital, key))
        equity = canonical_equity_series(
            [trade],
            initial=initial_capital,
            period_start=start,
            period_end=end,
        )
        metrics = _metrics(key=key, ret=pnl / initial_capital if initial_capital else 0.0, net=pnl, trades=1)
        return PeriodRun(
            trades=[trade],
            equity=equity,
            metrics=metrics,
            used_max=end,
            frozen_key=key,
            attribution=ExecutionAttribution(completed_trades=1),
            requested_strategy="ema_professional",
            execution_engine="ema_trend",
        )


def _ports(n: int = 50, symbols: tuple[str, ...] = ("RELIANCE",), **ohlcv_kwargs: object):
    frames = {name: _ohlcv(n, **ohlcv_kwargs) for name in symbols}
    feats = {name: _features(frames[name]) for name in symbols}
    return _StaticMarket(frames), _StaticFeatures(feats), frames


def _frame_span(features: _StaticFeatures) -> tuple[date, date]:
    frame = features.load_features("RELIANCE")
    stamps = pd.to_datetime(frame["date"])
    return stamps.min().date(), stamps.max().date()


def test_window_generation() -> None:
    windows = generate_windows(
        date(2016, 1, 1),
        date(2024, 12, 31),
        WalkForwardConfig(train_years=5, test_years=1, step_years=1),
    )
    assert windows[0].train_start == date(2016, 1, 1)
    assert windows[0].train_end == date(2020, 12, 31)
    assert windows[0].test_start == date(2021, 1, 1)
    assert windows[0].test_end == date(2021, 12, 31)
    assert windows[1].train_start == date(2017, 1, 1)
    assert windows[1].train_end == date(2021, 12, 31)
    assert windows[1].test_start == date(2022, 1, 1)
    assert windows[-1].test_end <= date(2024, 12, 31)
    assert len(windows) >= 3


def test_no_train_test_overlap() -> None:
    windows = generate_windows(date(2016, 1, 1), date(2023, 12, 31), WalkForwardConfig())
    for window in windows:
        train = pd.bdate_range(window.train_start, window.train_end)
        test = pd.bdate_range(window.test_start, window.test_end)
        assert set(train).isdisjoint(set(test))


def test_train_before_test() -> None:
    windows = generate_windows(date(2016, 1, 1), date(2023, 12, 31), WalkForwardConfig())
    for window in windows:
        assert window.train_end < window.test_start
        assert window.train_start <= window.train_end
        assert window.test_start <= window.test_end


def test_indicator_warmup_does_not_leak_future() -> None:
    frame = _ohlcv(40, start="2022-01-03")
    test_start = frame["date"].iloc[20].date()
    test_end = frame["date"].iloc[30].date()
    poisoned = frame.copy()
    poisoned.loc[poisoned.index[-1], "close"] = 1_000_000.0
    capped = cap_frame(poisoned, until=test_end)
    assert frame_max_date(capped) == test_end
    assert frame_max_date(capped) < poisoned["date"].max().date()
    warm = cap_frame(frame, until=test_end)
    cold = frame.loc[pd.to_datetime(frame["date"]).dt.date >= test_start]
    warm_ema = pd.to_numeric(warm["close"]).ewm(span=10, adjust=False).mean()
    cold_ema = pd.to_numeric(cold["close"]).ewm(span=10, adjust=False).mean()
    warm_val = float(warm_ema.loc[pd.to_datetime(warm["date"]).dt.date == test_start].iloc[0])
    cold_val = float(cold_ema.iloc[0])
    assert abs(warm_val - cold_val) > 1e-9


def test_test_data_cannot_change_training_selection() -> None:
    market_a, feats_a, frames = _ports(40)
    train_start = frames["RELIANCE"]["date"].iloc[0].date()
    train_end = frames["RELIANCE"]["date"].iloc[18].date()
    poisoned = frames["RELIANCE"].copy()
    after = pd.to_datetime(poisoned["date"]).dt.date > train_end
    poisoned.loc[after, "close"] = poisoned.loc[after, "close"] * 50.0
    market_b = _StaticMarket({"RELIANCE": poisoned})
    feats_b = _StaticFeatures({"RELIANCE": _features(poisoned)})
    cfg = _cfg(search=_search(ema_pair_presets=("9_21", "12_26")))
    a, ma, na, _, _ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=train_start,
        train_end=train_end,
        market_data=market_a,
        features=feats_a,
        initial_capital=100_000.0,
    )
    b, mb, nb, _, _ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=train_start,
        train_end=train_end,
        market_data=market_b,
        features=feats_b,
        initial_capital=100_000.0,
    )
    assert config_key(a) == config_key(b)
    assert ma.config_key == mb.config_key
    assert na == nb == 2


def test_parameter_selection_uses_train_only() -> None:
    market, features, frames = _ports(40)
    train_end = frames["RELIANCE"]["date"].iloc[18].date()
    seen: list[date] = []

    def runner(**kwargs: object) -> PeriodRun:
        period = run_period(**kwargs)  # type: ignore[arg-type]
        seen.append(period.used_max)
        return period

    select_on_train(
        symbol="RELIANCE",
        wf_config=_cfg(),
        train_start=frames["RELIANCE"]["date"].iloc[0].date(),
        train_end=train_end,
        market_data=market,
        features=features,
        initial_capital=100_000.0,
        runner=runner,
    )
    assert seen
    assert all(max_seen <= train_end for max_seen in seen)


def test_frozen_configuration_during_test() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    scripted = _Scripted()
    WalkForwardEngine(_cfg(data_start=start, data_end=end), selector=scripted.selector, runner=scripted.runner).run(
        symbols=["RELIANCE"],
        market_data=market,
        features=features,
    )
    assert scripted.selects
    assert scripted.calls
    expected = config_key(_frozen())
    for _symbol, start_d, _end_d, _cap, key in scripted.calls:
        matching = [item for item in scripted.selects if item[2] < start_d]
        assert matching
        assert key == expected


def test_oos_trades_are_test_only() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.oos_trades
    assert len(result.windows) == len(result.oos_trades)
    for row, trade in zip(result.windows, result.oos_trades):
        entry = trade.entry_timestamp.date()
        assert row.window.test_start <= entry <= row.window.test_end
        assert entry > row.window.train_end


def test_combined_oos_equity() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, initial_capital=100_000.0),
        selector=_Scripted().selector,
        runner=_Scripted(pnl_by_year={2020: 1000.0}).runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.oos_trade_count == result.window_count
    assert result.final_oos_equity == pytest.approx(100_000.0 + 1000.0 * result.window_count)
    assert result.equity_curve
    assert result.equity_curve[-1].equity == pytest.approx(result.final_oos_equity)


def test_capital_roll_forward() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, capital_mode=CapitalMode.COMPOUNDED, initial_capital=10_000.0),
        selector=_Scripted().selector,
        runner=_Scripted(pnl_by_year={2020: 250.0}).runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert len(result.windows) >= 2
    for prev, curr in zip(result.windows, result.windows[1:]):
        assert curr.starting_capital == pytest.approx(prev.ending_capital)


def test_small_capital() -> None:
    market, features, _frames = _ports(30, price=50.0)
    start, end = _frame_span(features)
    cfg = _cfg(data_start=start, data_end=end, min_history_bars=3)
    for capital in (500.0, 1_000.0, 10_000.0, 100_000.0):
        period = run_period(
            symbol="RELIANCE",
            strategy_config=_frozen(),
            wf_config=cfg.model_copy(update={"initial_capital": capital}),
            start=start,
            end=end,
            market_data=market,
            features=features,
            initial_capital=capital,
            evaluator=_PulseEvaluator(),
        )
        assert period.trades
        for trade in period.trades:
            assert trade.quantity >= 1.0
            assert abs(trade.quantity - round(trade.quantity)) < 1e-9


def test_insufficient_cash() -> None:
    market, features, _ = _ports(20, price=50_000.0)
    start, end = _frame_span(features)
    period = run_period(
        symbol="RELIANCE",
        strategy_config=_frozen(),
        wf_config=_cfg(data_start=start, data_end=end, initial_capital=500.0, min_quantity=1.0),
        start=start,
        end=end,
        market_data=market,
        features=features,
        initial_capital=500.0,
        evaluator=_PulseEvaluator(),
    )
    assert period.trades == []
    assert period.rejected_count >= 1


def test_deterministic_results() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    cfg = _cfg(data_start=start, data_end=end, include_monte_carlo=True, simulations=20, random_seed=42)
    a = WalkForwardEngine(cfg, selector=_Scripted().selector, runner=_Scripted().runner).run(
        symbols=["RELIANCE"],
        market_data=market,
        features=features,
    )
    b = WalkForwardEngine(cfg, selector=_Scripted().selector, runner=_Scripted().runner).run(
        symbols=["RELIANCE"],
        market_data=market,
        features=features,
    )
    assert a.oos_return == b.oos_return
    assert a.final_oos_equity == b.final_oos_equity
    assert [w.selected.config_key for w in a.windows] == [w.selected.config_key for w in b.windows]
    assert a.monte_carlo_probability_of_loss == b.monte_carlo_probability_of_loss


def test_multi_symbol_isolation() -> None:
    reliance = _ohlcv(40)
    tcs = _ohlcv(40, price=200.0)
    train_end = reliance["date"].iloc[18].date()
    tcs_poisoned = tcs.copy()
    after = pd.to_datetime(tcs_poisoned["date"]).dt.date > train_end
    tcs_poisoned.loc[after, "close"] = 9_999.0
    cfg = _cfg(search=_search(ema_pair_presets=("9_21", "12_26")))
    a, *_ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=reliance["date"].iloc[0].date(),
        train_end=train_end,
        market_data=_StaticMarket({"RELIANCE": reliance, "TCS": tcs}),
        features=_StaticFeatures({"RELIANCE": _features(reliance), "TCS": _features(tcs)}),
        initial_capital=100_000.0,
    )
    b, *_ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=reliance["date"].iloc[0].date(),
        train_end=train_end,
        market_data=_StaticMarket({"RELIANCE": reliance, "TCS": tcs_poisoned}),
        features=_StaticFeatures({"RELIANCE": _features(reliance), "TCS": _features(tcs_poisoned)}),
        initial_capital=100_000.0,
    )
    assert config_key(a) == config_key(b)


def test_costs_use_existing_execution_model() -> None:
    market, features, _ = _ports(25, price=100.0)
    start, end = _frame_span(features)
    cfg = _cfg(slippage_bps=10.0, brokerage_rate=0.001, data_start=start, data_end=end)
    period = run_period(
        symbol="RELIANCE",
        strategy_config=_frozen(),
        wf_config=cfg,
        start=start,
        end=end,
        market_data=market,
        features=features,
        initial_capital=100_000.0,
        evaluator=_PulseEvaluator(),
    )
    assert period.trades
    trade = period.trades[0]
    buy_px = execution_price(OrderSide.BUY, 100.0, 10.0)
    assert trade.brokerage > 0.0
    assert trade.slippage > 0.0
    expected_entry_broker = brokerage_charge(trade.quantity * trade.entry_price, 0.001)
    assert trade.brokerage >= expected_entry_broker * 0.5
    assert buy_px > 100.0


def test_oos_monte_carlo_sample_warning() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(
            data_start=start,
            data_end=end,
            step_days=20,
            include_monte_carlo=True,
            simulations=25,
            random_seed=7,
        ),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.oos_trade_count <= 4
    assert result.verdict.value == "INSUFFICIENT_EVIDENCE"
    text = " ".join(result.warnings)
    assert "OUT-OF-SAMPLE MONTE CARLO" in text
    assert "INSUFFICIENT_EVIDENCE" in text
    assert "does not create new historical observations" in text


def test_output_files(tmp_path: Path) -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    paths = write_outputs(result, output_dir=tmp_path)
    for name in (
        "json",
        "md",
        "leakage",
        "windows",
        "train_metrics",
        "oos_metrics",
        "oos_trades",
        "parameter_history",
        "equity_curve",
    ):
        assert paths[name].exists()
        assert paths[name].stat().st_size > 0
    md = paths["md"].read_text(encoding="utf-8")
    assert "TRADELAB WALK-FORWARD VALIDATION" in md
    assert format_markdown_report(result).startswith("TRADELAB WALK-FORWARD VALIDATION")


def test_cli(tmp_path: Path) -> None:
    frame = _ohlcv(40)
    frame.to_parquet(tmp_path / "RELIANCE.parquet", engine="pyarrow")
    spec = importlib.util.spec_from_file_location(
        "walk_forward_cli",
        Path("backend/scripts/walk_forward.py"),
    )
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    argv = [
        "--symbol",
        "RELIANCE",
        "--train-days",
        "12",
        "--test-days",
        "5",
        "--step-days",
        "20",
        "--min-history",
        "3",
        "--presets",
        "9_21",
        "--ema200",
        "off",
        "--adx",
        "20",
        "--no-monte-carlo",
        "--no-charts",
        "--storage-dir",
        str(tmp_path),
        "--output",
        str(tmp_path / "out"),
        "--initial-capital",
        "10000",
        "--seed",
        "42",
    ]
    args = cli.parse_args(argv)
    assert args.train_days == 12
    assert cli.main(argv) == 0
    assert (tmp_path / "out" / "walk_forward_report.json").exists()
    assert (tmp_path / "out" / "leakage_report.json").exists()


def test_adversarial_lookahead() -> None:
    frame = _ohlcv(40)
    train_end = frame["date"].iloc[18].date()
    a = frame.copy()
    b = frame.copy()
    b.loc[pd.to_datetime(b["date"]).dt.date > train_end, ["open", "high", "low", "close"]] = 1.0
    cfg = _cfg(search=_search(ema_pair_presets=("9_21", "12_26")))
    chosen_a, *_ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=frame["date"].iloc[0].date(),
        train_end=train_end,
        market_data=_StaticMarket({"RELIANCE": a}),
        features=_StaticFeatures({"RELIANCE": _features(a)}),
        initial_capital=50_000.0,
    )
    chosen_b, *_ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=frame["date"].iloc[0].date(),
        train_end=train_end,
        market_data=_StaticMarket({"RELIANCE": b}),
        features=_StaticFeatures({"RELIANCE": _features(b)}),
        initial_capital=50_000.0,
    )
    assert config_key(chosen_a) == config_key(chosen_b)
    capped_b = DateCappedMarket(_StaticMarket({"RELIANCE": b}), train_end).get_history("RELIANCE")
    assert frame_max_date(capped_b) <= train_end


def test_parameter_stability() -> None:
    market, features, frames = _ports(50)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    scripted = _Scripted()
    alt = EMATrendConfig.professional(
        symbol="RELIANCE",
        min_history_bars=3,
        ema200_filter=False,
        ema_pair_preset=None,
        fast_ema=12,
        slow_ema=26,
    )

    def selector(*, symbol: str, train_start: date, train_end: date, **kwargs: object):
        cfg = _frozen(symbol) if train_start.day <= 15 else alt
        scripted.selects.append((symbol, train_start, train_end))
        return cfg, _metrics(key=config_key(cfg)), 2, train_end, _train_diagnostic()

    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, train_days=10, test_days=5, step_days=8),
        selector=selector,
        runner=scripted.runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.parameter_stability.history
    assert 0.0 <= result.parameter_stability.stability_score <= 1.0
    assert result.parameter_stability.most_frequent
    assert result.degradation.note
    assert result.degradation.label.value == "DESCRIPTIVE_DIAGNOSTIC"


def test_equity_curve_has_no_runtime_timestamps() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.equity_curve
    index = pd.DatetimeIndex([p.timestamp for p in result.equity_curve])
    assert index.is_monotonic_increasing
    last_test_end = result.windows[-1].window.test_end
    assert_market_timestamps_only(
        pd.Series([p.equity for p in result.equity_curve], index=index),
        max_date=last_test_end,
        generated_at=result.generated_at,
    )
    if result.generated_at is not None:
        assert (index >= pd.Timestamp(result.generated_at)).sum() == 0


def test_equity_curve_duplicate_timestamps_deterministic() -> None:
    ts = pd.Timestamp("2023-06-01", tz="UTC")
    series = pd.Series([100.0, 101.0, 102.0], index=pd.DatetimeIndex([ts, ts, ts + pd.Timedelta(days=1)]))
    cleaned = sanitize_equity_series(series)
    assert len(cleaned) == 2
    assert float(cleaned.loc[ts]) == 101.0


def test_sample_aware_zero_trade_win_rate() -> None:
    equity = pd.Series([100_000.0, 99_000.0], index=pd.to_datetime(["2023-01-02", "2023-01-03"], utc=True))
    perf = build_sample_aware_performance([], equity, 100_000.0)
    assert perf.win_rate is None
    assert perf.win_rate_status is MetricStatus.NO_TRADES
    assert perf.sharpe is None
    assert perf.sharpe_status is MetricStatus.INSUFFICIENT_SAMPLE


def test_sample_aware_one_trade_sharpe_insufficient() -> None:
    trade = _closed("RELIANCE", datetime(2023, 1, 2, tzinfo=timezone.utc), -500.0)
    equity = pd.Series([100_000.0, 99_500.0], index=pd.to_datetime(["2023-01-02", "2023-01-03"], utc=True))
    perf = build_sample_aware_performance([trade], equity, 100_000.0)
    assert perf.trade_count == 1
    assert perf.sharpe is None
    assert perf.sharpe_status is MetricStatus.INSUFFICIENT_SAMPLE
    assert perf.sharpe_raw is not None


def test_sample_aware_profit_factor_no_winners() -> None:
    trade = _closed("RELIANCE", datetime(2023, 1, 2, tzinfo=timezone.utc), -500.0)
    equity = pd.Series([100_000.0, 99_500.0], index=pd.to_datetime(["2023-01-02", "2023-01-03"], utc=True))
    perf = build_sample_aware_performance([trade], equity, 100_000.0)
    assert perf.profit_factor is None
    assert perf.profit_factor_status is MetricStatus.NO_WINNING_TRADES


def test_rejected_orders_attribution_separate_from_no_signal() -> None:
    market, features, _ = _ports(20, price=50_000.0)
    start, end = _frame_span(features)
    period = run_period(
        symbol="RELIANCE",
        strategy_config=_frozen(),
        wf_config=_cfg(data_start=start, data_end=end, initial_capital=500.0, min_quantity=1.0),
        start=start,
        end=end,
        market_data=market,
        features=features,
        initial_capital=500.0,
        evaluator=_PulseEvaluator(),
    )
    assert period.trades == []
    assert period.attribution is not None
    assert period.attribution.signals_generated >= 1
    assert period.attribution.orders_rejected >= 1
    assert period.attribution.completed_trades == 0


def test_strategy_identity_preserved() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, strategy_alias="ema_professional"),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.strategy_identity is not None
    assert result.strategy_identity.requested_strategy == "ema_professional"
    assert result.strategy_identity.execution_engine == "ema_trend"
    for row in result.windows:
        assert row.requested_strategy == "ema_professional"
        assert row.execution_engine == "ema_trend"


def test_parameter_stability_no_oos_trades_not_robust() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()

    class _NoTradeRunner(_Scripted):
        def runner(self, **kwargs: object) -> PeriodRun:
            period = super().runner(**kwargs)
            start = kwargs["start"]
            end = kwargs["end"]
            initial_capital = float(kwargs["initial_capital"])
            equity = canonical_equity_series(
                [],
                initial=initial_capital,
                period_start=start,
                period_end=end,
            )
            return PeriodRun(
                trades=[],
                equity=equity,
                metrics=_metrics(key=period.frozen_key, ret=0.0, trades=0, net=0.0, sharpe=0.0),
                used_max=period.used_max,
                frozen_key=period.frozen_key,
                attribution=ExecutionAttribution(),
                requested_strategy="ema_professional",
                execution_engine="ema_trend",
            )

    scripted = _NoTradeRunner()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end),
        selector=scripted.selector,
        runner=scripted.runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.oos_trade_count == 0
    assert result.parameter_stability.oos_trade_count == 0
    assert "NO OOS TRADE EVIDENCE" in result.parameter_stability.interpretation.upper()


def test_combined_oos_insufficient_evidence_verdict() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, include_monte_carlo=True, simulations=1000),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.verdict.value == "INSUFFICIENT_EVIDENCE"
    assert result.historical_oos_trades == result.oos_trade_count
    assert result.simulation_count == result.monte_carlo_simulations


def test_multi_symbol_walk_forward_isolation() -> None:
    market, features, frames = _ports(40, symbols=("RELIANCE", "TCS"))
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, step_days=20),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE", "TCS"], market_data=market, features=features)
    symbols = {row.symbol for row in result.windows}
    assert symbols == {"RELIANCE", "TCS"}
    assert set(result.oos_attribution_by_symbol) <= {"RELIANCE", "TCS"}


def test_market_equity_series_rejects_completed_at() -> None:
    from app.backtesting.order_execution.schemas import (
        AccountSnapshot,
        ExecutionAttempt,
        ExecutionConfig,
        ExecutionResult,
        ExecutionSummary,
        RejectedOrderRecord,
        RejectionReason,
    )

    runtime = datetime(2026, 8, 17, 7, 41, 27, tzinfo=timezone.utc)
    market_ts = datetime(2024, 3, 22, tzinfo=timezone.utc)
    account = AccountSnapshot(
        cash=90_000.0,
        initial_capital=100_000.0,
        realized_pnl=-10_000.0,
        unrealized_pnl=0.0,
        equity=90_000.0,
    )
    attempt = ExecutionAttempt(
        accepted=False,
        reason_code=RejectionReason.INSUFFICIENT_CASH,
        rejected=RejectedOrderRecord(
            timestamp=market_ts,
            symbol="RELIANCE",
            reason=RejectionReason.INSUFFICIENT_CASH.value,
            reason_code=RejectionReason.INSUFFICIENT_CASH,
        ),
        account=account,
    )
    result = ExecutionResult(
        config=ExecutionConfig(initial_capital=100_000.0),
        started_at=runtime,
        completed_at=runtime,
        attempts=[attempt],
        final_account=account,
        summary=ExecutionSummary(
            orders_attempted=1,
            orders_rejected=1,
            current_cash=90_000.0,
            current_equity=90_000.0,
        ),
        orders_rejected=1,
    )
    series = market_equity_series(
        result,
        trades=[],
        initial=100_000.0,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
    )
    assert all(ts <= pd.Timestamp("2024-12-31", tz="UTC") + pd.Timedelta(days=1) for ts in series.index)


def test_ledger_final_equity_equals_initial_plus_net_profit() -> None:
    from app.backtesting.walk_forward.accounting import (
        assert_costs_not_double_counted,
        assert_ledger_invariant,
        broker_equivalent_from_ledger,
        ledger_final_equity,
        sum_slippage,
    )
    from app.backtesting.walk_forward.equity import canonical_equity_series

    trades = [
        _ledger_trade(
            "RELIANCE",
            datetime(2022, 11, 4, tzinfo=timezone.utc),
            gross_profit=-2798.394738,
            brokerage=55.905486,
            slippage=93.175133,
        ),
        _ledger_trade(
            "RELIANCE",
            datetime(2024, 3, 26, tzinfo=timezone.utc),
            gross_profit=-938.597513,
            brokerage=54.745867,
            slippage=91.242899,
        ),
        _ledger_trade(
            "RELIANCE",
            datetime(2024, 4, 26, tzinfo=timezone.utc),
            gross_profit=-2548.130233,
            brokerage=53.901189,
            slippage=89.834701,
        ),
    ]
    initial = 100_000.0
    assert_costs_not_double_counted(trades)
    expected = ledger_final_equity(initial, trades)
    assert expected == pytest.approx(93_276.072241, rel=0, abs=1e-3)
    series = canonical_equity_series(
        trades,
        initial=initial,
        period_start=date(2022, 1, 1),
        period_end=date(2025, 12, 31),
    )
    assert float(series.iloc[-1]) == pytest.approx(expected, rel=0, abs=1e-6)
    assert_ledger_invariant(initial=initial, trades=trades, final_equity=float(series.iloc[-1]))
    broker_equiv = broker_equivalent_from_ledger(trades, initial)
    assert broker_equiv - expected == pytest.approx(sum_slippage(trades), rel=0, abs=1e-3)


def test_combined_vs_mean_window_return_semantics() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, step_days=20),
        selector=_Scripted(pnl_by_year={2020: 1000.0, 2021: -500.0}).selector,
        runner=_Scripted(pnl_by_year={2020: 1000.0, 2021: -500.0}).runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.combined_oos_return == pytest.approx(result.oos_return)
    if len(result.windows) > 1:
        assert result.mean_window_oos_return != result.combined_oos_return


def test_walk_forward_ledger_invariant_on_engine_run() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    net_sum = sum(float(t.net_profit) for t in result.oos_trades)
    assert result.final_oos_equity == pytest.approx(result.initial_capital + net_sum, rel=0, abs=1e-4)
    assert result.combined_oos_return == pytest.approx(
        (result.final_oos_equity - result.initial_capital) / result.initial_capital,
        rel=0,
        abs=1e-9,
    )


def test_minimum_training_trades_filter_uses_train_only() -> None:
    market, features, frames = _ports(40)
    train_end = frames["RELIANCE"]["date"].iloc[18].date()
    cfg = _cfg(
        search=_search(ema_pair_presets=("9_21", "12_26")),
        minimum_training_trades=5,
    )
    _chosen, metrics, _n, _used, diagnostic = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=frames["RELIANCE"]["date"].iloc[0].date(),
        train_end=train_end,
        market_data=market,
        features=features,
        initial_capital=100_000.0,
    )
    assert diagnostic.minimum_training_trades == 5
    assert diagnostic.candidates_evaluated >= 1
    assert diagnostic.selected_training_trade_count == metrics.trade_count
    if diagnostic.eligible_count == 0:
        assert diagnostic.selected_eligibility is SelectionEligibility.FALLBACK_INELIGIBLE
        assert metrics.trade_count < 5
        assert diagnostic.fallback_count == diagnostic.ineligible_count
        assert "NOT satisfied" in diagnostic.note
    else:
        assert diagnostic.selected_eligibility is SelectionEligibility.ELIGIBLE
        assert metrics.trade_count >= 5


def test_training_fallback_never_implies_minimum_satisfied() -> None:
    market, features, frames = _ports(40)
    train_end = frames["RELIANCE"]["date"].iloc[18].date()
    cfg = _cfg(
        search=_search(ema_pair_presets=("9_21", "12_26")),
        minimum_training_trades=5,
    )
    _chosen, metrics, _n, _used, diagnostic = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=frames["RELIANCE"]["date"].iloc[0].date(),
        train_end=train_end,
        market_data=market,
        features=features,
        initial_capital=100_000.0,
    )
    if diagnostic.selected_eligibility is SelectionEligibility.FALLBACK_INELIGIBLE:
        assert diagnostic.eligible_count == 0
        assert diagnostic.selected_training_trade_count == metrics.trade_count
        assert metrics.trade_count < diagnostic.minimum_training_trades
        assert diagnostic.fallback_count > 0


def test_oos_data_cannot_change_train_eligibility() -> None:
    market_a, features_a, frames = _ports(40)
    train_start = frames["RELIANCE"]["date"].iloc[0].date()
    train_end = frames["RELIANCE"]["date"].iloc[18].date()
    test_end = frames["RELIANCE"]["date"].iloc[-1].date()
    poisoned = frames["RELIANCE"].copy()
    after_train = pd.to_datetime(poisoned["date"]).dt.date > train_end
    poisoned.loc[after_train, "close"] = poisoned.loc[after_train, "close"] * 50.0
    market_b = _StaticMarket({"RELIANCE": poisoned})
    features_b = _StaticFeatures({"RELIANCE": _features(poisoned)})
    cfg = _cfg(
        search=_search(ema_pair_presets=("9_21", "12_26")),
        minimum_training_trades=5,
        data_start=train_start,
        data_end=test_end,
    )
    result_a = WalkForwardEngine(cfg).run(
        symbols=["RELIANCE"],
        market_data=market_a,
        features=features_a,
    )
    result_b = WalkForwardEngine(cfg).run(
        symbols=["RELIANCE"],
        market_data=market_b,
        features=features_b,
    )
    for row_a, row_b in zip(result_a.windows, result_b.windows, strict=True):
        sel_a = row_a.train_selection
        sel_b = row_b.train_selection
        assert sel_a is not None and sel_b is not None
        assert sel_a.selected_eligibility == sel_b.selected_eligibility
        assert sel_a.selected_training_trade_count == sel_b.selected_training_trade_count
        assert sel_a.eligible_count == sel_b.eligible_count
        assert row_a.selected.config_key == row_b.selected.config_key
    assert result_a.leakage.passed
    assert result_b.leakage.passed
    assert result_a.leakage.train_selection_ignores_test
    assert result_b.leakage.train_selection_ignores_test


def test_slippage_and_brokerage_counted_once_on_execution_path() -> None:
    from app.backtesting.walk_forward.accounting import (
        assert_costs_not_double_counted,
        assert_trade_ledger_identity,
        broker_equivalent_from_ledger,
        ledger_final_equity,
        sum_brokerage,
        sum_slippage,
    )

    market, features, _ = _ports(25, price=100.0)
    start, end = _frame_span(features)
    slippage_bps = 10.0
    brokerage_rate = 0.001
    cfg = _cfg(
        slippage_bps=slippage_bps,
        brokerage_rate=brokerage_rate,
        data_start=start,
        data_end=end,
    )
    period = run_period(
        symbol="RELIANCE",
        strategy_config=_frozen(),
        wf_config=cfg,
        start=start,
        end=end,
        market_data=market,
        features=features,
        initial_capital=100_000.0,
        evaluator=_PulseEvaluator(),
    )
    assert period.trades
    trade = period.trades[0]
    assert_trade_ledger_identity(trade)
    assert_costs_not_double_counted(period.trades)
    assert trade.brokerage > 0.0
    assert trade.slippage > 0.0
    ref_entry = float(trade.entry_price) / (1.0 + slippage_bps / 10_000.0)
    assert trade.entry_price == pytest.approx(
        execution_price(OrderSide.BUY, ref_entry, slippage_bps),
        rel=0,
        abs=1e-9,
    )
    assert trade.brokerage == pytest.approx(sum_brokerage(period.trades), rel=0, abs=1e-9)
    assert trade.slippage == pytest.approx(sum_slippage(period.trades), rel=0, abs=1e-9)
    expected_final = ledger_final_equity(100_000.0, period.trades)
    assert float(period.equity.iloc[-1]) == pytest.approx(expected_final, rel=0, abs=1e-6)
    assert expected_final == pytest.approx(
        100_000.0 + sum(float(t.net_profit) for t in period.trades),
        rel=0,
        abs=1e-6,
    )
    broker_equiv = broker_equivalent_from_ledger(period.trades, 100_000.0)
    assert broker_equiv - expected_final == pytest.approx(sum_slippage(period.trades), rel=0, abs=1e-3)


def test_train_selection_fallback_warning_in_report() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(
            data_start=start,
            data_end=end,
            minimum_training_trades=5,
            search=_search(ema_pair_presets=("9_21", "12_26")),
        ),
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    md = format_markdown_report(result)
    assert "TRAIN SELECTION ELIGIBILITY" in md
    fallback_rows = [
        row
        for row in result.windows
        if row.train_selection
        and row.train_selection.selected_eligibility is SelectionEligibility.FALLBACK_INELIGIBLE
    ]
    if fallback_rows:
        assert any("TRAIN_SELECTION_FALLBACK" in w for w in result.warnings)
        assert "FALLBACK_INELIGIBLE" in md
        assert "WARNING window" in md


def test_sharpe_methodology_documented() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.oos_sharpe_methodology == "canonical_equity_step_returns"
    assert "equity" in result.oos_sharpe_methodology


def test_single_symbol_unchanged_no_portfolio_layer() -> None:
    market, features, frames = _ports(40)
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, initial_capital=100_000.0),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.is_multi_symbol is False
    assert result.symbol_allocation_capital is None
    assert result.symbol_results == []
    assert result.portfolio is None
    assert result.final_oos_equity == pytest.approx(100_000.0 + result.oos_net_profit, rel=0, abs=1e-4)


def test_multi_symbol_equal_allocation_deterministic() -> None:
    market, features, frames = _ports(40, symbols=("RELIANCE", "TCS"))
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    total = 100_000.0
    scripted = _Scripted()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, step_days=20, initial_capital=total),
        selector=scripted.selector,
        runner=scripted.runner,
    ).run(symbols=["RELIANCE", "TCS"], market_data=market, features=features)
    assert result.is_multi_symbol
    assert result.symbol_allocation_capital == pytest.approx(total / 2, rel=0, abs=1e-6)
    first_reliance = next(row for row in result.windows if row.symbol == "RELIANCE")
    first_tcs = next(row for row in result.windows if row.symbol == "TCS")
    assert first_reliance.starting_capital == pytest.approx(total / 2, rel=0, abs=1e-6)
    assert first_tcs.starting_capital == pytest.approx(total / 2, rel=0, abs=1e-6)
    assert len(result.symbol_results) == 2


def test_multi_symbol_portfolio_return_from_summed_equity() -> None:
    market, features, frames = _ports(40, symbols=("RELIANCE", "TCS"))
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    scripted = _PerSymbolScripted(pnl_by_symbol={"RELIANCE": 5000.0, "TCS": 500.0})
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, step_days=20, initial_capital=100_000.0),
        selector=scripted.selector,
        runner=scripted.runner,
    ).run(symbols=["RELIANCE", "TCS"], market_data=market, features=features)
    assert result.portfolio is not None
    expected_return = (result.portfolio.final_equity - result.initial_capital) / result.initial_capital
    assert result.portfolio.oos_return == pytest.approx(expected_return, rel=0, abs=1e-9)
    assert result.combined_oos_return == pytest.approx(expected_return, rel=0, abs=1e-9)
    assert result.portfolio.final_equity == pytest.approx(
        sum(r.final_equity for r in result.symbol_results),
        rel=0,
        abs=1e-4,
    )


def test_multi_symbol_selection_isolated_per_symbol() -> None:
    market, features, frames = _ports(40, symbols=("RELIANCE", "TCS"))
    train_end = frames["RELIANCE"]["date"].iloc[18].date()
    cfg = _cfg(search=_search(ema_pair_presets=("9_21", "12_26")), minimum_training_trades=5)
    a, *_ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=frames["RELIANCE"]["date"].iloc[0].date(),
        train_end=train_end,
        market_data=market,
        features=features,
        initial_capital=50_000.0,
    )
    b, *_ = select_on_train(
        symbol="TCS",
        wf_config=cfg,
        train_start=frames["TCS"]["date"].iloc[0].date(),
        train_end=train_end,
        market_data=market,
        features=features,
        initial_capital=50_000.0,
    )
    assert config_key(a) == config_key(b)


def test_multi_symbol_oos_cannot_affect_other_symbol_selection() -> None:
    market_a, features_a, frames = _ports(40, symbols=("RELIANCE", "TCS"))
    train_end = frames["RELIANCE"]["date"].iloc[18].date()
    poisoned = frames["TCS"].copy()
    after = pd.to_datetime(poisoned["date"]).dt.date > train_end
    poisoned.loc[after, "close"] *= 50.0
    market_b = _StaticMarket({"RELIANCE": frames["RELIANCE"], "TCS": poisoned})
    features_b = _StaticFeatures({"RELIANCE": _features(frames["RELIANCE"]), "TCS": _features(poisoned)})
    cfg = _cfg(search=_search(ema_pair_presets=("9_21", "12_26")), minimum_training_trades=5)
    rel_a, *_ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=frames["RELIANCE"]["date"].iloc[0].date(),
        train_end=train_end,
        market_data=market_a,
        features=features_a,
        initial_capital=50_000.0,
    )
    rel_b, *_ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=frames["RELIANCE"]["date"].iloc[0].date(),
        train_end=train_end,
        market_data=market_b,
        features=features_b,
        initial_capital=50_000.0,
    )
    assert config_key(rel_a) == config_key(rel_b)


def test_multi_symbol_only_oos_trades_in_portfolio_aggregation() -> None:
    market, features, frames = _ports(40, symbols=("RELIANCE", "TCS"))
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, step_days=20),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE", "TCS"], market_data=market, features=features)
    assert result.portfolio is not None
    assert result.oos_trade_count == len(result.oos_trades)
    for trade in result.oos_trades:
        matching = [row for row in result.windows if row.symbol == trade.symbol]
        assert matching
        assert any(row.window.test_start <= trade.entry_timestamp.date() <= row.window.test_end for row in matching)
    assert result.portfolio.oos_trade_count == len(result.oos_trades)


def test_multi_symbol_output_files(tmp_path: Path) -> None:
    market, features, frames = _ports(40, symbols=("RELIANCE", "TCS"))
    start = frames["RELIANCE"]["date"].min().date()
    end = frames["RELIANCE"]["date"].max().date()
    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, step_days=20, include_charts=False),
        selector=_Scripted().selector,
        runner=_Scripted().runner,
    ).run(symbols=["RELIANCE", "TCS"], market_data=market, features=features)
    paths = write_outputs(result, output_dir=tmp_path)
    for name in (
        "json",
        "md",
        "windows",
        "oos_trades",
        "symbol_metrics",
        "portfolio_equity_curve",
        "strategy_symbol_matrix",
    ):
        assert paths[name].exists()
        assert paths[name].stat().st_size > 0
    md = paths["md"].read_text(encoding="utf-8")
    assert "PORTFOLIO OOS" in md
    assert "PER-SYMBOL OOS" in md


def test_symbols_file_cli(tmp_path: Path) -> None:
    frame_r = _ohlcv(40)
    frame_t = _ohlcv(40, price=200.0)
    frame_r.to_parquet(tmp_path / "RELIANCE.parquet", engine="pyarrow")
    frame_t.to_parquet(tmp_path / "TCS.parquet", engine="pyarrow")
    symbols_file = tmp_path / "symbols.txt"
    symbols_file.write_text("RELIANCE\nTCS\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "walk_forward_cli",
        Path("backend/scripts/walk_forward.py"),
    )
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    symbols = cli._resolve_symbols(
        cli.parse_args(
            [
                "--symbols-file",
                str(symbols_file),
                "--storage-dir",
                str(tmp_path),
            ],
        ),
        tmp_path,
    )
    assert symbols == ["RELIANCE", "TCS"]
