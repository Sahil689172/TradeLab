"""Unit tests for the confluence engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.confluence import (
    ConfluenceConfig,
    ConfluenceEngine,
    ConfluenceModule,
    ConfluenceVerdict,
    ModuleWeights,
    SignalContribution,
    VerdictThresholds,
)
from app.feature_engine.pipeline import FeaturePipeline
from app.levels.calculator import cpr_levels
from app.levels.schemas import (
    CamarillaPivotLevels,
    ClassicPivotLevels,
    LevelKind,
    LevelsSnapshot,
    PeriodRange,
    PriceLevel,
)
from app.market_structure.schemas import (
    MarketStructureResult,
    StructureEvent,
    StructureEventType,
    StructureLabel,
    SwingPoint,
    SwingType,
    TrendDirection,
)
from tests.test_indicators import make_prices


def make_structure(trend: TrendDirection = TrendDirection.BULLISH) -> MarketStructureResult:
    low = SwingPoint(
        index=3,
        timestamp=datetime(2024, 1, 4, tzinfo=timezone.utc),
        price=95.0,
        swing_type=SwingType.SWING_LOW,
        structure_label=StructureLabel.HIGHER_LOW,
        confirmation_index=4,
    )
    high = SwingPoint(
        index=6,
        timestamp=datetime(2024, 1, 7, tzinfo=timezone.utc),
        price=110.0,
        swing_type=SwingType.SWING_HIGH,
        structure_label=StructureLabel.HIGHER_HIGH,
        confirmation_index=7,
    )
    event = StructureEvent(
        index=8,
        timestamp=datetime(2024, 1, 9, tzinfo=timezone.utc),
        event_type=StructureEventType.BREAK_OF_STRUCTURE,
        direction=TrendDirection.BULLISH if trend is TrendDirection.BULLISH else TrendDirection.BEARISH,
        broken_level=110.0 if trend is TrendDirection.BULLISH else 95.0,
        reference_swing_index=6 if trend is TrendDirection.BULLISH else 3,
        confirmation_price=112.0 if trend is TrendDirection.BULLISH else 93.0,
    )
    return MarketStructureResult(
        symbol="RELIANCE",
        swing_length=1,
        bar_count=20,
        trend=trend,
        swings=[low, high],
        events=[event],
        last_swing_high=high,
        last_swing_low=low,
    )


def make_levels(*, reference: float = 105.0, support: float = 104.8, resistance: float = 120.0) -> LevelsSnapshot:
    classic = ClassicPivotLevels(
        pivot=100.0,
        resistance_1=105.0,
        resistance_2=110.0,
        resistance_3=115.0,
        support_1=95.0,
        support_2=90.0,
        support_3=85.0,
    )
    camarilla = CamarillaPivotLevels(
        reference_close=100.0,
        resistance_1=101.0,
        resistance_2=102.0,
        resistance_3=103.0,
        resistance_4=104.0,
        support_1=99.0,
        support_2=98.0,
        support_3=97.0,
        support_4=96.0,
    )
    period = PeriodRange(
        high=110.0,
        low=90.0,
        close=100.0,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    return LevelsSnapshot(
        symbol="RELIANCE",
        as_of=datetime(2024, 1, 10, tzinfo=timezone.utc),
        reference_price=reference,
        opening_range_bars=1,
        previous_day_high=108.0,
        previous_day_low=98.0,
        previous_week_high=112.0,
        previous_week_low=94.0,
        previous_month_high=120.0,
        previous_month_low=85.0,
        opening_range_high=106.0,
        opening_range_low=104.0,
        daily_pivot=100.0,
        weekly_pivot=99.0,
        classic_pivot=classic,
        camarilla_pivot=camarilla,
        cpr=cpr_levels(108.0, 98.0, 100.0),
        supports=[
            PriceLevel(kind=LevelKind.PREVIOUS_DAY_LOW, price=support, label="Previous Day Low"),
        ],
        resistances=[
            PriceLevel(kind=LevelKind.PREVIOUS_DAY_HIGH, price=resistance, label="Previous Day High"),
        ],
        previous_day=period,
        previous_week=period,
        previous_month=period,
    )


@pytest.fixture
def market_features() -> pd.DataFrame:
    ohlcv = make_prices(120)
    features = FeaturePipeline().transform(ohlcv)
    return ohlcv.merge(features, on="date", how="left")


def test_default_weights_match_scorecard() -> None:
    weights = ModuleWeights()
    assert weights.ema == 20
    assert weights.rsi == 15
    assert weights.volume == 20
    assert weights.structure == 20
    assert weights.atr == 10
    assert weights.levels == 15
    assert weights.trend == 20


def test_evaluate_returns_verdict_and_explanation(market_features: pd.DataFrame) -> None:
    engine = ConfluenceEngine()
    result = engine.evaluate(
        features=market_features,
        market_structure=make_structure(TrendDirection.BULLISH),
        levels=make_levels(reference=float(market_features.iloc[-1]["close"])),
        symbol="RELIANCE",
    )

    assert result.verdict in set(ConfluenceVerdict)
    assert -100.0 <= result.total_score <= 100.0
    assert result.symbol == "RELIANCE"
    assert result.explanation
    assert "Verdict" in result.explanation
    modules = {item.module for item in result.modules}
    assert ConfluenceModule.EMA in modules
    assert ConfluenceModule.RSI in modules
    assert ConfluenceModule.VOLUME in modules
    assert ConfluenceModule.STRUCTURE in modules
    assert ConfluenceModule.ATR in modules
    assert ConfluenceModule.LEVELS in modules
    assert ConfluenceModule.TREND in modules
    # Normalized weights should sum to ~100 for active default modules.
    assert sum(item.normalized_weight for item in result.modules) == pytest.approx(100.0)


def test_bullish_inputs_score_higher_than_bearish(market_features: pd.DataFrame) -> None:
    engine = ConfluenceEngine()
    bullish = engine.evaluate(
        features=market_features,
        market_structure=make_structure(TrendDirection.BULLISH),
        levels=make_levels(
            reference=float(market_features.iloc[-1]["close"]),
            support=float(market_features.iloc[-1]["close"]) * 0.999,
            resistance=float(market_features.iloc[-1]["close"]) * 1.1,
        ),
        price_action_signals=[
            SignalContribution(name="engulfing", score=0.8, reason="bullish engulfing"),
        ],
        indicator_signals=[
            SignalContribution(name="macd_cross", score=0.7, reason="macd cross above"),
        ],
        config=ConfluenceConfig(
            weights=ModuleWeights(price_action=10, indicator_signals=10),
        ),
    )
    bearish = engine.evaluate(
        features=market_features,
        market_structure=make_structure(TrendDirection.BEARISH),
        levels=make_levels(
            reference=float(market_features.iloc[-1]["close"]),
            support=float(market_features.iloc[-1]["close"]) * 0.9,
            resistance=float(market_features.iloc[-1]["close"]) * 1.001,
        ),
        config=ConfluenceConfig(
            weights=ModuleWeights(price_action=0, indicator_signals=0),
        ),
    )

    assert bullish.total_score > bearish.total_score


def test_verdict_thresholds_are_configurable() -> None:
    engine = ConfluenceEngine(
        ConfluenceConfig(thresholds=VerdictThresholds(strong_buy=10, buy=5, sell=-5, strong_sell=-10)),
    )
    # Force a synthetic high score by weighting only a bullish external signal.
    features = FeaturePipeline().transform(make_prices(80))
    # Attach dummy required columns already present from pipeline.
    result = engine.evaluate(
        features=features,
        indicator_signals=[SignalContribution(name="custom", score=1.0, reason="forced bullish")],
        config=ConfluenceConfig(
            weights=ModuleWeights(
                ema=0,
                rsi=0,
                volume=0,
                structure=0,
                atr=0,
                levels=0,
                trend=0,
                indicator_signals=100,
            ),
            thresholds=VerdictThresholds(strong_buy=10, buy=5, sell=-5, strong_sell=-10),
        ),
    )

    assert result.verdict is ConfluenceVerdict.STRONG_BUY
    assert result.total_score == pytest.approx(100.0)
    assert "INDICATOR_SIGNALS" in result.explanation


def test_module_contribution_math() -> None:
    engine = ConfluenceEngine()
    features = FeaturePipeline().transform(make_prices(80))
    result = engine.evaluate(
        features=features,
        config=ConfluenceConfig(
            weights=ModuleWeights(
                ema=0,
                rsi=0,
                volume=0,
                structure=0,
                atr=0,
                levels=0,
                trend=0,
                price_action=50,
                indicator_signals=50,
            ),
        ),
        price_action_signals=[SignalContribution(name="pa", score=1.0, reason="up")],
        indicator_signals=[SignalContribution(name="ind", score=-1.0, reason="down")],
    )

    assert result.total_score == pytest.approx(0.0)
    assert result.verdict is ConfluenceVerdict.HOLD
    by_module = {item.module: item for item in result.modules}
    assert by_module[ConfluenceModule.PRICE_ACTION].contribution == pytest.approx(50.0)
    assert by_module[ConfluenceModule.INDICATOR_SIGNALS].contribution == pytest.approx(-50.0)


def test_missing_core_columns_raise() -> None:
    from app.confluence import ConfluenceValidationError

    engine = ConfluenceEngine()
    with pytest.raises(ConfluenceValidationError, match="missing required columns"):
        engine.evaluate(features=pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3)}))
