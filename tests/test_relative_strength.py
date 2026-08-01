"""Unit tests for Relative Strength scoring, ranking, screener, and strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from app.strategies.relative_strength import (
    RelativeStrengthConfig,
    RelativeStrengthScreener,
    RelativeStrengthStrategy,
    period_return,
    rank_scores,
    register_relative_strength_strategy,
    score_universe,
)
from app.strategies.relative_strength.ranking import in_top_percentile, lookup_rank
from app.strategy_engine import SignalType, StrategyRegistry, StrategyRunner


def make_price_frame(
    *,
    start: float,
    daily_return: float,
    rows: int = 40,
    start_date: str = "2023-01-02",
    volume_base: float = 1_000.0,
) -> pd.DataFrame:
    """Synthetic daily OHLCV with constant drift."""
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
                "volume": volume_base + index * 50.0,
                "ema_20": close * 1.01,
                "ema_50": close * 0.99,
                "atr_14": close * 0.02,
            },
        )
    return pd.DataFrame(records)


@pytest.fixture
def rs_config() -> RelativeStrengthConfig:
    return RelativeStrengthConfig(
        symbol="STRONG",
        benchmark_symbol="NIFTY50",
        lookback_3m=5,
        lookback_6m=10,
        lookback_12m=20,
        min_history_bars=30,
        top_percentile=0.25,
        sell_rank_percentile=0.50,
        relative_volume_threshold=1.1,
    )


def test_period_return_calculation() -> None:
    closes = pd.Series([100.0, 102.0, 105.0, 110.0])
    assert period_return(closes, 3) == pytest.approx(110.0 / 100.0 - 1.0)


def test_score_calculation_and_benchmark_comparison(rs_config: RelativeStrengthConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001, rows=40)
    strong = make_price_frame(start=100.0, daily_return=0.01, rows=40)
    weak = make_price_frame(start=100.0, daily_return=-0.005, rows=40)

    scores = score_universe(
        {"STRONG": strong, "WEAK": weak},
        benchmark,
        config=rs_config,
        sector_by_symbol={"STRONG": "IT", "WEAK": "IT"},
    )
    by_symbol = {item.symbol: item for item in scores}
    assert by_symbol["STRONG"].strength_score > by_symbol["WEAK"].strength_score
    assert by_symbol["STRONG"].rs_12m > 0
    assert by_symbol["WEAK"].rs_12m < 0
    assert by_symbol["STRONG"].benchmark_return_3m == pytest.approx(
        by_symbol["WEAK"].benchmark_return_3m,
    )
    assert by_symbol["STRONG"].sector_strength is not None


def test_universe_ranking(rs_config: RelativeStrengthConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001, rows=40)
    frames = {
        "A": make_price_frame(start=100.0, daily_return=0.012, rows=40),
        "B": make_price_frame(start=100.0, daily_return=0.004, rows=40),
        "C": make_price_frame(start=100.0, daily_return=-0.002, rows=40),
        "D": make_price_frame(start=100.0, daily_return=0.008, rows=40),
    }
    scores = score_universe(frames, benchmark, config=rs_config)
    ranking = rank_scores(scores, benchmark_symbol="NIFTY50", strongest_count=2)

    assert ranking.universe_size == 4
    assert ranking.ranked[0].rank == 1
    assert ranking.ranked[0].symbol == "A"
    assert ranking.top_10[0].symbol == "A"
    assert len(ranking.strongest) == 2
    assert in_top_percentile(ranking.ranked[0], 0.25, universe_size=4)


def test_screener_lists(rs_config: RelativeStrengthConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001, rows=40)
    frames = {
        f"S{i}": make_price_frame(start=100.0, daily_return=0.01 - i * 0.002, rows=40)
        for i in range(8)
    }
    screener = RelativeStrengthScreener(rs_config, sector_map={})
    first = screener.rank_frames(frames, benchmark, list_size=3)
    assert len(first.top_ranked) == 3
    assert len(first.worst_ranked) == 3
    assert first.ranking.top_10

    # Second pass with prior ranks → improving / weakening populated
    # Boost a former weak name
    frames["S7"] = make_price_frame(start=100.0, daily_return=0.02, rows=40)
    second = screener.rank_frames(frames, benchmark, list_size=3)
    assert second.fastest_improving or second.ranking.ranked[0].previous_rank is not None


def test_trade_generation_buy(rs_config: RelativeStrengthConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001, rows=40)
    strong = make_price_frame(start=100.0, daily_return=0.015, rows=40)
    # Ensure last bar volume spike for healthy volume
    strong.loc[strong.index[-1], "volume"] = float(strong["volume"].iloc[-2]) * 3.0
    peers = {
        "STRONG": strong,
        "MID": make_price_frame(start=100.0, daily_return=0.002, rows=40),
        "WEAK": make_price_frame(start=100.0, daily_return=-0.003, rows=40),
        "SOFT": make_price_frame(start=100.0, daily_return=0.0, rows=40),
    }
    ranking = rank_scores(
        score_universe(peers, benchmark, config=rs_config),
        benchmark_symbol="NIFTY50",
    )
    assert lookup_rank(ranking, "STRONG") is not None
    assert lookup_rank(ranking, "STRONG").rank == 1

    strategy = RelativeStrengthStrategy(rs_config, ranking=ranking)
    plan = StrategyRunner().run(strong, strategy)
    detailed = strategy.last_detailed_plan

    assert plan.signal is SignalType.BUY
    assert plan.strategy_name == "relative_strength"
    assert detailed is not None
    assert detailed.current_rank == 1
    assert detailed.strength_score is not None
    assert detailed.benchmark_comparison is not None
    assert "EMA" in " ".join(detailed.reasons) or "rank" in " ".join(detailed.reasons).lower()


def test_sell_when_rank_falls(rs_config: RelativeStrengthConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001, rows=40)
    weak = make_price_frame(start=100.0, daily_return=-0.01, rows=40)
    peers = {
        "STRONG": make_price_frame(start=100.0, daily_return=0.02, rows=40),
        "MID": make_price_frame(start=100.0, daily_return=0.005, rows=40),
        "WEAK": weak,
        "SOFT": make_price_frame(start=100.0, daily_return=0.001, rows=40),
    }
    ranking = rank_scores(
        score_universe(peers, benchmark, config=rs_config),
        benchmark_symbol="NIFTY50",
    )
    config = rs_config.model_copy(update={"symbol": "WEAK"})
    strategy = RelativeStrengthStrategy(config, ranking=ranking)
    signal = strategy.generate_signal(strategy.prepare(weak))
    assert signal.signal is SignalType.SELL


def test_registry_integration(rs_config: RelativeStrengthConfig) -> None:
    benchmark = make_price_frame(start=100.0, daily_return=0.001, rows=40)
    strong = make_price_frame(start=100.0, daily_return=0.02, rows=40)
    strong.loc[strong.index[-1], "volume"] = float(strong["volume"].iloc[-2]) * 3.0
    peers = {
        "STRONG": strong,
        "B": make_price_frame(start=100.0, daily_return=0.0, rows=40),
        "C": make_price_frame(start=100.0, daily_return=-0.01, rows=40),
        "D": make_price_frame(start=100.0, daily_return=0.002, rows=40),
    }
    ranking = rank_scores(
        score_universe(peers, benchmark, config=rs_config),
        benchmark_symbol="NIFTY50",
    )
    registry = StrategyRegistry()
    register_relative_strength_strategy(registry, rs_config, ranking=ranking)
    plan = StrategyRunner().run(strong, registry.get("relative_strength"))
    assert plan.signal is SignalType.BUY
