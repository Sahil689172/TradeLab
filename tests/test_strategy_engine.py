"""Unit tests for the strategy engine foundation."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from pydantic import ValidationError

from app.strategy_engine import (
    BaseStrategy,
    Signal,
    SignalType,
    StrategyNotFoundError,
    StrategyRegistrationError,
    StrategyRegistry,
    StrategyRunner,
    StrategyValidationError,
    TradePlan,
    attach_symbol,
)
from app.strategy_engine.exceptions import StrategyEngineError


def make_features(rows: int = 5, *, symbol: str | None = "RELIANCE") -> pd.DataFrame:
    """Minimal feature frame used only to exercise the foundation contract."""
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "close": [100.0 + float(i) for i in range(rows)],
            "rsi_14": [50.0] * rows,
        },
    )
    if symbol:
        return attach_symbol(frame, symbol)
    return frame


class StubStrategy(BaseStrategy):
    """Deterministic strategy stub with no trading logic."""

    def __init__(
        self,
        *,
        name: str = "stub_strategy",
        signal_type: SignalType = SignalType.BUY,
        require_columns: tuple[str, ...] = ("date", "close"),
    ) -> None:
        self._name = name
        self._signal_type = signal_type
        self._require_columns = require_columns

    @property
    def name(self) -> str:
        return self._name

    def validate(self, features: pd.DataFrame) -> None:
        missing = [column for column in self._require_columns if column not in features.columns]
        if missing:
            raise StrategyValidationError(
                f"Missing required columns: {', '.join(missing)}",
            )

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        return features.copy()

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        latest = features.iloc[-1]
        timestamp = pd.Timestamp(latest["date"]).to_pydatetime()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return Signal(
            symbol=self.active_symbol,
            timestamp=timestamp,
            signal=self._signal_type,
            confidence=0.75,
            reason="stub signal",
        )

    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        entry_price = float(features.iloc[-1]["close"])
        return TradePlan(
            symbol=self.active_symbol,
            entry_price=entry_price,
            signal=signal.signal,
            stop_loss=entry_price * 0.98,
            take_profit_1=entry_price * 1.02,
            take_profit_2=entry_price * 1.04,
            holding_period=5,
            risk_reward=2.0,
            confidence=signal.confidence,
            reasons=[signal.reason],
            strategy_name=self.name,
        )


class BrokenPrepareStrategy(StubStrategy):
    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        return "not-a-dataframe"  # type: ignore[return-value]


class EmptyPrepareStrategy(StubStrategy):
    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        return features.iloc[0:0].copy()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_signal_type_values() -> None:
    assert set(SignalType) == {
        SignalType.BUY,
        SignalType.SELL,
        SignalType.HOLD,
        SignalType.EXIT,
    }
    assert SignalType.BUY.value == "BUY"


def test_signal_model_normalizes_symbol_and_is_frozen() -> None:
    signal = Signal(
        symbol="  reliance.ns  ",
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        signal=SignalType.HOLD,
        confidence=0.5,
        reason="no setup",
    )

    assert signal.symbol == "RELIANCE.NS"
    with pytest.raises(ValidationError):
        signal.confidence = 0.1  # type: ignore[misc]


def test_signal_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        Signal(
            symbol="RELIANCE",
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            signal=SignalType.BUY,
            confidence=1.5,
            reason="too confident",
        )


def test_trade_plan_requires_non_empty_reasons() -> None:
    with pytest.raises(ValidationError):
        TradePlan(
            symbol="RELIANCE",
            entry_price=100.0,
            signal=SignalType.BUY,
            stop_loss=98.0,
            take_profit_1=102.0,
            take_profit_2=104.0,
            holding_period=5,
            risk_reward=2.0,
            confidence=0.8,
            reasons=["  ", ""],
            strategy_name="stub",
        )


def test_trade_plan_is_frozen() -> None:
    plan = TradePlan(
        symbol="reliance",
        entry_price=100.0,
        signal=SignalType.BUY,
        stop_loss=98.0,
        take_profit_1=102.0,
        take_profit_2=104.0,
        holding_period=5,
        risk_reward=2.0,
        confidence=0.8,
        reasons=["setup"],
        strategy_name="stub",
    )

    assert plan.symbol == "RELIANCE"
    with pytest.raises(ValidationError):
        plan.entry_price = 101.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_register_get_list_unregister() -> None:
    registry = StrategyRegistry()
    strategy = StubStrategy(name="alpha")

    registry.register(strategy)

    assert registry.list() == ["alpha"]
    assert registry.get("alpha") is strategy

    registry.unregister("alpha")
    assert registry.list() == []


def test_registry_rejects_duplicate_registration() -> None:
    registry = StrategyRegistry()
    registry.register(StubStrategy(name="alpha"))

    with pytest.raises(StrategyRegistrationError, match="already registered"):
        registry.register(StubStrategy(name="alpha"))


def test_registry_get_missing_raises() -> None:
    registry = StrategyRegistry()

    with pytest.raises(StrategyNotFoundError, match="not registered"):
        registry.get("missing")


def test_registry_unregister_missing_raises() -> None:
    registry = StrategyRegistry()

    with pytest.raises(StrategyNotFoundError, match="not registered"):
        registry.unregister("missing")


def test_registry_rejects_non_strategy() -> None:
    registry = StrategyRegistry()

    with pytest.raises(TypeError, match="BaseStrategy"):
        registry.register(object())  # type: ignore[arg-type]


def test_registry_clear() -> None:
    registry = StrategyRegistry()
    registry.register(StubStrategy(name="alpha"))
    registry.register(StubStrategy(name="beta"))

    registry.clear()

    assert registry.list() == []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def test_runner_returns_trade_plan() -> None:
    runner = StrategyRunner()
    features = make_features(symbol="RELIANCE")
    strategy = StubStrategy()

    plan = runner.run(features, strategy)

    assert isinstance(plan, TradePlan)
    assert plan.strategy_name == "stub_strategy"
    assert plan.signal == SignalType.BUY
    assert plan.symbol == "RELIANCE"
    assert strategy.active_symbol == "RELIANCE"
    assert plan.entry_price == float(features.iloc[-1]["close"])
    assert plan.reasons == ["stub signal"]


def test_runner_binds_symbol_from_features() -> None:
    runner = StrategyRunner()
    features = make_features(symbol="INFY")
    strategy = StubStrategy()
    assert strategy.active_symbol == "UNKNOWN"
    plan = runner.run(features, strategy)
    assert plan.symbol == "INFY"
    assert strategy.active_symbol == "INFY"


def test_runner_rejects_empty_features() -> None:
    runner = StrategyRunner()

    with pytest.raises(StrategyValidationError, match="must not be empty"):
        runner.run(make_features(0), StubStrategy())


def test_runner_propagates_strategy_validation_error() -> None:
    runner = StrategyRunner()
    features = make_features().drop(columns=["close"])

    with pytest.raises(StrategyValidationError, match="Missing required columns"):
        runner.run(features, StubStrategy())


def test_runner_rejects_invalid_prepare_return_type() -> None:
    runner = StrategyRunner()

    with pytest.raises(StrategyEngineError, match="prepare\\(\\) must return a DataFrame"):
        runner.run(make_features(), BrokenPrepareStrategy())


def test_runner_rejects_empty_prepare_result() -> None:
    runner = StrategyRunner()

    with pytest.raises(StrategyValidationError, match="empty DataFrame"):
        runner.run(make_features(), EmptyPrepareStrategy())


def test_runner_rejects_non_strategy() -> None:
    runner = StrategyRunner()

    with pytest.raises(TypeError, match="BaseStrategy"):
        runner.run(make_features(), object())  # type: ignore[arg-type]


def test_base_strategy_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        BaseStrategy()  # type: ignore[abstract]
