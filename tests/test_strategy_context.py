"""Tests for Strategy Context Provider."""

from __future__ import annotations

import pandas as pd

from app.services.strategy_context import (
    STRATEGY_CONTEXT_REQUIREMENTS,
    ContextRequirement,
    StrategyContextProvider,
    requirements_for,
)
from app.services.trade_recommendation import StrategyValidationFramework
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategies.momentum import MomentumConfig, MomentumStrategy
from app.strategies.previous_day_breakout import (
    PreviousDayBreakoutConfig,
    PreviousDayBreakoutStrategy,
)
from app.strategies.relative_strength import (
    RelativeStrengthConfig,
    RelativeStrengthStrategy,
)
from app.strategy_engine.symbols import attach_symbol


def synthetic_features(*, bars: int = 80, symbol: str = "RELIANCE") -> pd.DataFrame:
    sessions: list[pd.Timestamp] = []
    day = pd.Timestamp("2024-06-03 09:15")
    while len(sessions) < bars:
        for minute in range(0, 6 * 60, 15):
            sessions.append(day + pd.Timedelta(minutes=minute))
            if len(sessions) >= bars:
                break
        day = day + pd.Timedelta(days=1)
        while day.weekday() >= 5:
            day = day + pd.Timedelta(days=1)

    rows = []
    price = 100.0
    for index, ts in enumerate(sessions[:bars]):
        price = 100 + index * 0.3
        close = price
        rows.append(
            {
                "date": ts,
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_500 + index * 10,
                "relative_volume_20": 2.0,
                "atr_14": 1.5,
                "ema_9": close,
                "ema_20": close + 1.0,
                "ema_21": close + 1.0,
                "ema_50": close - 1.0,
                "adx_14": 30.0,
                "rsi_14": 55.0,
                "vwap": close * 0.999,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def test_requirements_map_covers_twelve_strategies() -> None:
    assert len(STRATEGY_CONTEXT_REQUIREMENTS) == 12
    assert ContextRequirement.LEVELS in requirements_for("cpr")
    assert ContextRequirement.RS_RANKING in requirements_for("relative_strength")
    assert ContextRequirement.MOMENTUM_RANKING in requirements_for("momentum")
    assert ContextRequirement.DAILY_OHLCV in requirements_for("previous_day_breakout")


def test_provider_prepares_ema_features_only() -> None:
    provider = StrategyContextProvider()
    strategy = EMATrendStrategy(EMATrendConfig(symbol="RELIANCE", adx_threshold=20.0))
    context = provider.prepare(strategy, "RELIANCE", features=synthetic_features())
    assert context.symbol == "RELIANCE"
    assert context.levels is None
    assert context.rs_ranking is None
    plan = strategy.execute(context)
    assert plan.symbol == "RELIANCE"


def test_provider_binds_daily_and_levels_for_pdb() -> None:
    provider = StrategyContextProvider()
    strategy = PreviousDayBreakoutStrategy(PreviousDayBreakoutConfig(symbol="RELIANCE"))
    context = provider.prepare(strategy, "RELIANCE", features=synthetic_features())
    assert context.daily_ohlcv is not None
    assert context.levels is not None
    assert context.levels.cpr is not None
    provider.apply(strategy, context)
    assert strategy._daily_ohlcv is not None  # noqa: SLF001
    assert strategy._levels_override is not None  # noqa: SLF001
    plan = strategy.execute(context)
    assert plan.symbol == "RELIANCE"


def test_provider_binds_rankings_without_manual_bind() -> None:
    provider = StrategyContextProvider()
    rs = RelativeStrengthStrategy(RelativeStrengthConfig(symbol="RELIANCE"))
    mom = MomentumStrategy(MomentumConfig(symbol="RELIANCE"))
    features = synthetic_features()

    rs_ctx = provider.prepare(rs, "RELIANCE", features=features)
    assert rs_ctx.rs_ranking is not None
    assert rs_ctx.rs_ranking.universe_size >= 1
    plan_rs = rs.execute(rs_ctx)
    assert plan_rs.symbol == "RELIANCE"

    mom_ctx = provider.prepare(mom, "RELIANCE", features=features)
    assert mom_ctx.momentum_ranking is not None
    plan_mom = mom.execute(mom_ctx)
    assert plan_mom.symbol == "RELIANCE"


def test_validation_framework_runs_all_strategies_via_context_provider() -> None:
    framework = StrategyValidationFramework(timeframe="15 Minute")
    report = framework.validate_many(
        synthetic_features(symbol="RELIANCE", bars=100),
        strategy_names=["all"],
        symbol="RELIANCE",
    )
    assert len(report.rows) == 12
    failed = [row for row in report.rows if row.status != "PASS"]
    assert not failed, {
        row.strategy: row.validation_errors for row in failed
    }
