"""Unit tests for the risk engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.feature_engine.pipeline import FeaturePipeline
from app.market_structure.schemas import (
    MarketStructureResult,
    StructureLabel,
    SwingPoint,
    SwingType,
    TrendDirection,
)
from app.risk_engine import (
    RiskConfig,
    RiskEngine,
    RiskValidationError,
    StopMethod,
    TradeDirection,
)
from app.risk_engine.stops import (
    atr_stop,
    percentage_stop,
    position_risk,
    structure_stop,
    swing_stop,
    take_profit_from_risk,
    time_stop,
)
from tests.test_indicators import make_prices


def make_structure(
    *,
    trend: TrendDirection = TrendDirection.BULLISH,
    swing_low: float = 95.0,
    swing_high: float = 110.0,
) -> MarketStructureResult:
    low = SwingPoint(
        index=5,
        timestamp=datetime(2024, 1, 6, tzinfo=timezone.utc),
        price=swing_low,
        swing_type=SwingType.SWING_LOW,
        structure_label=StructureLabel.HIGHER_LOW,
        confirmation_index=6,
    )
    high = SwingPoint(
        index=8,
        timestamp=datetime(2024, 1, 9, tzinfo=timezone.utc),
        price=swing_high,
        swing_type=SwingType.SWING_HIGH,
        structure_label=StructureLabel.HIGHER_HIGH,
        confirmation_index=9,
    )
    return MarketStructureResult(
        symbol="RELIANCE",
        swing_length=1,
        bar_count=20,
        trend=trend,
        swings=[low, high],
        events=[],
        last_swing_high=high,
        last_swing_low=low,
    )


@pytest.fixture
def features():
    return FeaturePipeline().transform(make_prices(220))


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine(
        RiskConfig(
            preferred_stop=StopMethod.ATR,
            atr_multiplier=1.5,
            percentage_stop=0.02,
            risk_reward=2.0,
            time_stop_bars=12,
            account_equity=100_000.0,
            risk_fraction=0.01,
            swing_buffer=0.5,
        ),
    )


def test_atr_stop_long(features, engine: RiskEngine) -> None:
    atr = float(features["atr_14"].dropna().iloc[-1])
    entry = 200.0
    stop = atr_stop(entry, TradeDirection.LONG, features, engine.config)

    assert stop.method is StopMethod.ATR
    assert stop.price == pytest.approx(entry - atr * 1.5)


def test_percentage_stop_short(engine: RiskEngine) -> None:
    stop = percentage_stop(100.0, TradeDirection.SHORT, engine.config)

    assert stop.price == pytest.approx(102.0)


def test_swing_and_structure_stops(engine: RiskEngine) -> None:
    structure = make_structure(swing_low=95.0, swing_high=110.0)
    swing = swing_stop(100.0, TradeDirection.LONG, structure, engine.config)
    structural = structure_stop(100.0, TradeDirection.LONG, structure, engine.config)

    assert swing.method is StopMethod.SWING
    assert swing.price == pytest.approx(94.5)  # 95 - 0.5 buffer
    assert structural.method is StopMethod.STRUCTURE
    assert structural.price == pytest.approx(94.5)


def test_time_stop(engine: RiskEngine) -> None:
    stop = time_stop(engine.config)

    assert stop.method is StopMethod.TIME
    assert stop.price is None
    assert stop.bars == 12


def test_risk_reward_and_position_risk(engine: RiskEngine) -> None:
    tp, rr = take_profit_from_risk(100.0, 95.0, TradeDirection.LONG, 2.0)
    risk = position_risk(100.0, 95.0, engine.config)

    assert tp == pytest.approx(110.0)
    assert rr == 2.0
    assert risk.risk_per_unit == pytest.approx(5.0)
    assert risk.capital_at_risk == pytest.approx(1000.0)
    assert risk.position_size == pytest.approx(200.0)


def test_compute_returns_full_risk_plan(features, engine: RiskEngine) -> None:
    structure = make_structure(trend=TrendDirection.BULLISH, swing_low=90.0)
    plan = engine.compute(
        entry_price=100.0,
        direction="LONG",
        features=features,
        market_structure=structure,
    )

    assert plan.direction is TradeDirection.LONG
    assert plan.stop_loss < plan.entry_price < plan.take_profit
    assert plan.risk_reward == pytest.approx(2.0)
    assert plan.holding_estimate == 12
    assert 0.0 <= plan.confidence <= 1.0
    assert plan.stop_method is StopMethod.ATR
    methods = {stop.method for stop in plan.stops}
    assert StopMethod.ATR in methods
    assert StopMethod.SWING in methods
    assert StopMethod.STRUCTURE in methods
    assert StopMethod.PERCENTAGE in methods
    assert StopMethod.TIME in methods
    assert plan.position_risk.position_size is not None
    assert plan.reasons


def test_preferred_swing_stop(features, engine: RiskEngine) -> None:
    structure = make_structure(swing_low=92.0)
    plan = engine.compute(
        entry_price=100.0,
        direction=TradeDirection.LONG,
        features=features,
        market_structure=structure,
        config=engine.config.model_copy(update={"preferred_stop": StopMethod.SWING}),
    )

    assert plan.stop_method is StopMethod.SWING
    assert plan.stop_loss == pytest.approx(91.5)


def test_short_plan_geometry(features, engine: RiskEngine) -> None:
    structure = make_structure(
        trend=TrendDirection.BEARISH,
        swing_low=90.0,
        swing_high=108.0,
    )
    # Relabel for bearish structure preference.
    high = structure.last_swing_high
    assert high is not None
    bearish = structure.model_copy(
        update={
            "trend": TrendDirection.BEARISH,
            "last_swing_high": high.model_copy(
                update={"structure_label": StructureLabel.LOWER_HIGH},
            ),
            "swings": [
                structure.swings[0],
                high.model_copy(update={"structure_label": StructureLabel.LOWER_HIGH}),
            ],
        },
    )
    plan = engine.compute(
        entry_price=100.0,
        direction=TradeDirection.SHORT,
        features=features,
        market_structure=bearish,
        config=engine.config.model_copy(update={"preferred_stop": StopMethod.STRUCTURE}),
    )

    assert plan.take_profit < plan.entry_price < plan.stop_loss
    assert plan.stop_method is StopMethod.STRUCTURE


def test_missing_atr_falls_back_when_preferred_unavailable(features, engine: RiskEngine) -> None:
    structure = make_structure(swing_low=93.0)
    frame = features.drop(columns=["atr_14"])
    plan = engine.compute(
        entry_price=100.0,
        direction=TradeDirection.LONG,
        features=frame,
        market_structure=structure,
        config=engine.config.model_copy(update={"preferred_stop": StopMethod.ATR}),
    )

    assert plan.stop_method in {
        StopMethod.STRUCTURE,
        StopMethod.SWING,
        StopMethod.PERCENTAGE,
    }
    assert plan.stop_loss < 100.0


def test_invalid_entry_raises(features, engine: RiskEngine) -> None:
    with pytest.raises(RiskValidationError, match="entry_price"):
        engine.compute(
            entry_price=0.0,
            direction=TradeDirection.LONG,
            features=features,
            market_structure=make_structure(),
        )


def test_confidence_higher_when_trend_aligned(features, engine: RiskEngine) -> None:
    bullish = engine.compute(
        entry_price=100.0,
        direction=TradeDirection.LONG,
        features=features,
        market_structure=make_structure(trend=TrendDirection.BULLISH, swing_low=90.0),
    )
    mismatched = engine.compute(
        entry_price=100.0,
        direction=TradeDirection.LONG,
        features=features,
        market_structure=make_structure(trend=TrendDirection.BEARISH, swing_low=90.0),
    )

    assert bullish.confidence > mismatched.confidence
