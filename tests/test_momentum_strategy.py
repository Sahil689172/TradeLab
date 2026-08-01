"""Unit tests for quantitative Momentum scoring, ranking, and strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from app.strategies.momentum import (
    MomentumConfig,
    MomentumEngine,
    MomentumStrategy,
    rank_scores,
    register_momentum_strategy,
    score_universe,
)
from app.strategies.momentum.ranking import in_top_percentile, lookup_rank
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner


def make_price_frame(
    *,
    start: float,
    daily_return: float,
    rows: int = 55,
    start_date: str = "2023-01-02",
    volume_base: float = 1_000.0,
    ema_bullish: bool = True,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start_date, periods=rows)
    closes = [start]
    for _ in range(1, rows):
        closes.append(closes[-1] * (1.0 + daily_return))
    records = []
    for index, (date, close) in enumerate(zip(dates, closes, strict=True)):
        records.append(
            {
                "date": date,
                "open": close * 0.99,
                "high": close,
                "low": close * 0.98,
                "close": close,
                "volume": volume_base + index * 40.0,
                "ema_20": close * (1.01 if ema_bullish else 0.98),
                "ema_50": close * (0.99 if ema_bullish else 1.02),
                "atr_14": close * 0.02,
            },
        )
    return pd.DataFrame(records)


@pytest.fixture
def mom_config() -> MomentumConfig:
    return MomentumConfig(
        symbol="HOT",
        benchmark_symbol="NIFTY50",
        lookback_1m=5,
        lookback_3m=10,
        lookback_6m=20,
        lookback_12m=40,
        min_history_bars=45,
        top_percentile=0.25,
        momentum_sell_threshold=0.0,
        relative_strength_threshold=0.0,
        relative_volume_threshold=1.1,
    )


def test_momentum_score(mom_config: MomentumConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001)
    hot = make_price_frame(start=100.0, daily_return=0.012)
    cold = make_price_frame(start=100.0, daily_return=-0.004)

    scores = score_universe(
        {"HOT": hot, "COLD": cold},
        config=mom_config,
        benchmark_frame=benchmark,
    )
    by_symbol = {item.symbol: item for item in scores}
    assert by_symbol["HOT"].momentum_score > by_symbol["COLD"].momentum_score
    assert by_symbol["HOT"].return_12m > 0
    assert by_symbol["HOT"].persistence >= by_symbol["COLD"].persistence
    assert by_symbol["HOT"].relative_strength > by_symbol["COLD"].relative_strength


def test_momentum_ranking(mom_config: MomentumConfig) -> None:
    frames = {
        "A": make_price_frame(start=100.0, daily_return=0.015),
        "B": make_price_frame(start=100.0, daily_return=0.004),
        "C": make_price_frame(start=100.0, daily_return=-0.003),
        "D": make_price_frame(start=100.0, daily_return=0.008),
    }
    ranking = rank_scores(
        score_universe(frames, config=mom_config),
        top_percentile=0.25,
    )
    assert ranking.universe_size == 4
    assert ranking.ranked[0].symbol == "A"
    assert ranking.ranked[0].rank == 1
    assert ranking.portfolio
    assert in_top_percentile(ranking.ranked[0], 0.25, universe_size=4)


def test_portfolio_ranking(mom_config: MomentumConfig) -> None:
    frames = {
        f"S{i}": make_price_frame(start=100.0, daily_return=0.01 - i * 0.002)
        for i in range(8)
    }
    ranking = rank_scores(
        score_universe(frames, config=mom_config),
        top_percentile=0.25,
    )
    assert len(ranking.portfolio) == 2  # ceil(8 * 0.25) = 2
    assert ranking.top_10[0].rank == 1


def test_batch_processing_via_engine(mom_config: MomentumConfig) -> None:
    engine = MomentumEngine(mom_config)
    benchmark = make_price_frame(start=100.0, daily_return=0.001)
    frames = {
        "X": make_price_frame(start=100.0, daily_return=0.01),
        "Y": make_price_frame(start=100.0, daily_return=0.002),
        "Z": make_price_frame(start=100.0, daily_return=-0.005),
    }
    scores = engine.score(frames, benchmark_frame=benchmark)
    assert len(scores) == 3
    ranking = rank_scores(scores, top_percentile=0.34)
    assert ranking.universe_size == 3
    assert lookup_rank(ranking, "X") is not None


def test_trade_generation(mom_config: MomentumConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001)
    hot = make_price_frame(start=100.0, daily_return=0.015)
    hot.loc[hot.index[-1], "volume"] = float(hot["volume"].iloc[-2]) * 3.0
    peers = {
        "HOT": hot,
        "MID": make_price_frame(start=100.0, daily_return=0.002),
        "SOFT": make_price_frame(start=100.0, daily_return=0.0),
        "COLD": make_price_frame(start=100.0, daily_return=-0.004),
    }
    ranking = rank_scores(
        score_universe(peers, config=mom_config, benchmark_frame=benchmark),
        top_percentile=0.25,
    )
    assert lookup_rank(ranking, "HOT").rank == 1

    strategy = MomentumStrategy(mom_config, ranking=ranking)
    plan = StrategyRunner().run(hot, strategy)
    detailed = strategy.last_detailed_plan

    assert plan.signal is SignalType.BUY
    assert plan.strategy_name == "momentum"
    assert detailed is not None
    assert detailed.momentum_rank == 1
    assert detailed.momentum_score is not None
    assert detailed.relative_strength is not None
    assert any("holding" in reason.lower() for reason in plan.reasons)


def test_sell_on_weak_momentum(mom_config: MomentumConfig) -> None:
    cold = make_price_frame(start=100.0, daily_return=-0.01, ema_bullish=True)
    peers = {
        "HOT": make_price_frame(start=100.0, daily_return=0.02),
        "MID": make_price_frame(start=100.0, daily_return=0.005),
        "COLD": cold,
        "SOFT": make_price_frame(start=100.0, daily_return=0.001),
    }
    ranking = rank_scores(score_universe(peers, config=mom_config), top_percentile=0.25)
    config = mom_config.model_copy(update={"symbol": "COLD"})
    strategy = MomentumStrategy(config, ranking=ranking)
    signal = strategy.generate_signal(strategy.prepare(cold))
    assert signal.signal is SignalType.SELL
    assert "momentum score" in signal.reason.lower()


def test_registry_integration(mom_config: MomentumConfig) -> None:
    hot = make_price_frame(start=100.0, daily_return=0.02)
    hot.loc[hot.index[-1], "volume"] = float(hot["volume"].iloc[-2]) * 3.0
    peers = {
        "HOT": hot,
        "B": make_price_frame(start=100.0, daily_return=0.0),
        "C": make_price_frame(start=100.0, daily_return=-0.01),
        "D": make_price_frame(start=100.0, daily_return=0.003),
    }
    ranking = rank_scores(score_universe(peers, config=mom_config), top_percentile=0.25)
    registry = StrategyRegistry()
    register_momentum_strategy(registry, mom_config, ranking=ranking)
    plan = StrategyRunner().run(hot, registry.get("momentum"))
    assert plan.signal is SignalType.BUY
