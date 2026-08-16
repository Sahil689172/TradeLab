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
from app.backtesting.walk_forward.isolation import DateCappedMarket, frame_max_date
from app.backtesting.walk_forward.optimizer import select_on_train
from app.backtesting.walk_forward.schemas import CandidateMetrics
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


class _Scripted:
    def __init__(self, pnl_by_year: dict[int, float] | None = None) -> None:
        self.calls: list[tuple[str, date, date, float, str]] = []
        self.selects: list[tuple[str, date, date]] = []
        self.pnl_by_year = pnl_by_year or {}

    def selector(self, *, symbol: str, train_start: date, train_end: date, **kwargs: object):
        self.selects.append((symbol, train_start, train_end))
        cfg = _frozen(symbol)
        return cfg, _metrics(key=config_key(cfg)), 2, train_end

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
        idx = pd.DatetimeIndex([entry, entry + timedelta(days=1)])
        equity = pd.Series([initial_capital, initial_capital + pnl], index=idx)
        metrics = _metrics(key=key, ret=pnl / initial_capital if initial_capital else 0.0, net=pnl, trades=1)
        return PeriodRun(trades=[trade], equity=equity, metrics=metrics, used_max=end, frozen_key=key)


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
    a, ma, na, _ = select_on_train(
        symbol="RELIANCE",
        wf_config=cfg,
        train_start=train_start,
        train_end=train_end,
        market_data=market_a,
        features=feats_a,
        initial_capital=100_000.0,
    )
    b, mb, nb, _ = select_on_train(
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
        return cfg, _metrics(key=config_key(cfg)), 2, train_end

    result = WalkForwardEngine(
        _cfg(data_start=start, data_end=end, train_days=10, test_days=5, step_days=8),
        selector=selector,
        runner=scripted.runner,
    ).run(symbols=["RELIANCE"], market_data=market, features=features)
    assert result.parameter_stability.history
    assert 0.0 <= result.parameter_stability.stability_score <= 1.0
    assert result.parameter_stability.most_frequent
    assert result.degradation.note
