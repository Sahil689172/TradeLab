"""Tests for Phase A5.1 Historical Replay Engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.backtesting.replay_engine import (
    HistoricalReplayEngine,
    NewCandle,
    RecommendationGenerated,
    ReplayCompleted,
    ReplayConfig,
    ReplayLookAheadError,
    ReplaySession,
    ReplaySpeed,
    ReplayStarted,
    ReplayStatus,
    StrategyEvaluation,
)
from app.backtesting.replay_engine.exceptions import ReplaySessionError
from app.backtesting.replay_engine.scheduler import ReplayScheduler
from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType


def _ohlcv(n: int = 80, start: str = "2022-01-03") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=n)
    rows = []
    for index, ts in enumerate(dates):
        close = 100.0 + index * 0.25
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
    frame["ema_9"] = frame["close"]
    frame["ema_20"] = frame["close"] + 0.5
    frame["ema_21"] = frame["close"] + 0.5
    frame["ema_50"] = frame["close"] - 0.5
    frame["adx_14"] = 28.0
    frame["rsi_14"] = 55.0
    frame["atr_14"] = 1.5
    frame["relative_volume_20"] = 1.8
    frame["vwap"] = frame["close"] * 0.999
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


class _RecordingListener:
    def __init__(self) -> None:
        self.events: list[object] = []

    def on_event(self, event: object) -> None:
        self.events.append(event)


class _FakeStrategy:
    name = "fake_replay"

    def bind_symbol(self, symbol: str) -> None:
        self._symbol = symbol

    def execute(self, context: object) -> object:
        from app.strategy_engine.models import TradePlan

        features = context.features  # type: ignore[attr-defined]
        close = float(features.iloc[-1]["close"])
        # Prove look-ahead safety: strategy only sees window length
        self.last_window_size = len(features)
        self.last_last_date = pd.Timestamp(features.iloc[-1]["date"])
        return TradePlan(
            symbol=getattr(self, "_symbol", "TEST"),
            entry_price=close,
            signal=SignalType.HOLD,
            stop_loss=close * 0.98,
            take_profit_1=close * 1.02,
            take_profit_2=close * 1.04,
            holding_period=5,
            risk_reward=1.0,
            confidence=0.5,
            reasons=["replay fake hold"],
            strategy_name=self.name,
        )


class _FakeEvaluator:
    def __init__(self) -> None:
        self.windows: list[pd.DataFrame] = []

    def evaluate(self, *, strategy, symbol, window, timestamp, timeframe):  # noqa: ANN001
        self.windows.append(window.copy())
        close = float(window.iloc[-1]["close"])
        return TradeRecommendation(
            strategy_name=strategy.name,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            signal=SignalType.HOLD,
            entry_price=close,
            stop_loss=close * 0.98,
            target_1=close * 1.02,
            target_2=close * 1.04,
            risk_reward=1.0,
            confidence=50.0,
            expected_holding_period=5,
            reasons=["test recommendation"],
            trend_direction=TrendDirection.SIDEWAYS,
            market_structure=TrendDirection.SIDEWAYS,
        )


class _FakeFactory:
    def __init__(self, strategies: list[object]) -> None:
        self._strategies = strategies

    def resolve(self, names):  # noqa: ANN001
        return list(self._strategies)


def test_replay_order_and_no_future_leakage() -> None:
    ohlcv = _ohlcv(60)
    session = ReplaySession("RELIANCE", ohlcv, start_index=10)
    session.start()
    seen_dates: list[pd.Timestamp] = []
    while session.has_more():
        candle = session.advance()
        ts = pd.Timestamp(candle["date"])
        if seen_dates:
            assert ts > seen_dates[-1]
        seen_dates.append(ts)
        window = session.historical_window()
        assert window["date"].max() == ts
        assert len(window) == session.current_index + 1
        # Inject a future row and ensure guard fires
        poisoned = pd.concat(
            [
                window,
                pd.DataFrame(
                    [
                        {
                            "date": ts + pd.Timedelta(days=5),
                            "open": 1.0,
                            "high": 1.0,
                            "low": 1.0,
                            "close": 1.0,
                            "volume": 1.0,
                        },
                    ],
                ),
            ],
            ignore_index=True,
        )
        with pytest.raises(ReplayLookAheadError):
            session.assert_no_lookahead(poisoned)
    session.mark_completed()
    assert session.status is ReplayStatus.COMPLETED
    assert seen_dates == sorted(seen_dates)


def test_state_transitions() -> None:
    session = ReplaySession("TCS", _ohlcv(20), start_index=0)
    assert session.status is ReplayStatus.READY
    session.start()
    assert session.status is ReplayStatus.RUNNING
    session.pause()
    assert session.status is ReplayStatus.PAUSED
    with pytest.raises(ReplaySessionError):
        session.advance()
    session.start()
    session.advance()
    while session.has_more():
        session.advance()
    session.mark_completed()
    assert session.status is ReplayStatus.COMPLETED


def test_scheduler_fast_no_sleep() -> None:
    slept: list[float] = []
    scheduler = ReplayScheduler(
        ReplaySpeed.FAST,
        sleeper=lambda seconds: slept.append(seconds),
    )
    delay = scheduler.wait_before_next(
        previous_timestamp=datetime(2022, 1, 1, tzinfo=timezone.utc),
        current_timestamp=datetime(2022, 1, 2, tzinfo=timezone.utc),
    )
    assert delay == 0.0
    assert slept == []


def test_scheduler_realtime_uses_sleep() -> None:
    slept: list[float] = []
    scheduler = ReplayScheduler(
        ReplaySpeed.REALTIME,
        realtime_sleep_seconds=0.01,
        sleeper=lambda seconds: slept.append(seconds),
    )
    delay = scheduler.wait_before_next(
        previous_timestamp=None,
        current_timestamp=datetime(2022, 1, 2),
    )
    assert delay == 0.01
    assert slept == [0.01]


def test_engine_events_and_recommendations() -> None:
    ohlcv = _ohlcv(50)
    features = _features(ohlcv)
    listener = _RecordingListener()
    evaluator = _FakeEvaluator()
    strategy = _FakeStrategy()
    engine = HistoricalReplayEngine(
        ReplayConfig(
            symbols=["RELIANCE"],
            strategy_names=["fake_replay"],
            speed=ReplaySpeed.FAST,
            min_history_bars=5,
            max_steps=12,
        ),
        market_data=_StaticMarket({"RELIANCE": ohlcv}),
        features=_StaticFeatures({"RELIANCE": features}),
        evaluator=evaluator,
        strategy_factory=_FakeFactory([strategy]),
        listener=listener,
    )
    result = engine.run()
    assert result.recommendations_generated > 0
    assert result.steps
    assert all(step.signal is SignalType.HOLD for step in result.steps)
    types = [type(event) for event in listener.events]
    assert ReplayStarted in types
    assert NewCandle in types
    assert StrategyEvaluation in types
    assert RecommendationGenerated in types
    assert ReplayCompleted in types
    # No window may include future vs its own last date
    for window in evaluator.windows:
        assert window["date"].is_monotonic_increasing
        assert window["date"].max() == window.iloc[-1]["date"]


def test_multi_symbol_replay() -> None:
    a = _ohlcv(40, start="2022-01-03")
    b = _ohlcv(40, start="2022-01-03")
    b["close"] = b["close"] + 50
    evaluator = _FakeEvaluator()
    engine = HistoricalReplayEngine(
        ReplayConfig(
            symbols=["AAA", "BBB"],
            strategy_names=["fake"],
            min_history_bars=5,
            max_steps=8,
        ),
        market_data=_StaticMarket({"AAA": a, "BBB": b}),
        features=_StaticFeatures({"AAA": _features(a), "BBB": _features(b)}),
        evaluator=evaluator,
        strategy_factory=_FakeFactory([_FakeStrategy()]),
    )
    result = engine.run()
    symbols = {step.symbol for step in result.steps}
    assert symbols == {"AAA", "BBB"}
    assert result.recommendations_generated == len(result.steps)


def test_warmup_respects_strategy_min_history() -> None:
    """Engine must not abort when config warm-up < strategy min_history_bars."""

    class _StrictStrategy(_FakeStrategy):
        class _Cfg:
            min_history_bars = 60

        config = _Cfg()

    ohlcv = _ohlcv(80)
    evaluator = _FakeEvaluator()
    engine = HistoricalReplayEngine(
        ReplayConfig(
            symbols=["RELIANCE"],
            strategy_names=["fake"],
            min_history_bars=40,  # intentionally below strategy requirement
            max_steps=70,
        ),
        market_data=_StaticMarket({"RELIANCE": ohlcv}),
        features=_StaticFeatures({"RELIANCE": _features(ohlcv)}),
        evaluator=evaluator,
        strategy_factory=_FakeFactory([_StrictStrategy()]),
    )
    result = engine.run()
    assert not result.errors
    assert result.recommendations_generated > 0
    # First evaluated window must be at least 60 bars
    assert min(len(window) for window in evaluator.windows) >= 60


def test_start_date_keeps_warmup_history() -> None:
    ohlcv = _ohlcv(80, start="2022-01-03")
    # start mid-series
    start = ohlcv.iloc[30]["date"].date()
    session_frame_loader = HistoricalReplayEngine(
        ReplayConfig(
            symbols=["RELIANCE"],
            strategy_names=["fake"],
            start_date=start,
            min_history_bars=5,
            max_steps=3,
        ),
        market_data=_StaticMarket({"RELIANCE": ohlcv}),
        features=_StaticFeatures({"RELIANCE": _features(ohlcv)}),
        evaluator=_FakeEvaluator(),
        strategy_factory=_FakeFactory([_FakeStrategy()]),
    )
    session = session_frame_loader.create_session("RELIANCE")
    assert session.start_index == 30
    session.start()
    candle = session.advance()
    assert pd.Timestamp(candle["date"]).date() == start
    window = session.historical_window()
    assert len(window) == 31  # includes warm-up bars before start_date
    assert window.iloc[-1]["date"] == candle["date"]
