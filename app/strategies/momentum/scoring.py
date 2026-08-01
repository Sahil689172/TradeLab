"""Reusable quantitative Momentum scoring engine (not RSI).

Reuses close-matrix / period-return helpers from Relative Strength to avoid
duplicating batch math. Future AI strategies and portfolio optimizers should
consume ``MomentumScore`` / ``MomentumEngine`` from this module.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.strategies.momentum.config import MomentumConfig
from app.strategies.momentum.schemas import MomentumScore
from app.strategies.relative_strength.scoring import (
    RelativeStrengthScoringError,
    batch_period_returns,
    build_close_matrix,
    period_return,
)


class MomentumScoringError(ValueError):
    """Invalid inputs for momentum scoring."""


def score_universe(
    frames: dict[str, pd.DataFrame],
    *,
    config: MomentumConfig,
    benchmark_frame: pd.DataFrame | None = None,
    as_of: pd.Timestamp | datetime | None = None,
) -> list[MomentumScore]:
    """Batch-score momentum for every symbol (NIFTY500-scale ready)."""
    as_of_ts = pd.Timestamp(as_of) if as_of is not None else None
    try:
        stock_matrix = build_close_matrix(
            frames,
            date_column=config.date_column,
            close_column=config.close_column,
            as_of=as_of_ts,
        )
    except RelativeStrengthScoringError as exc:
        raise MomentumScoringError(str(exc)) from exc

    if len(stock_matrix) <= config.lookback_12m:
        raise MomentumScoringError(
            f"Need more than {config.lookback_12m} bars for momentum scoring",
        )

    bench_6m = 0.0
    if benchmark_frame is not None:
        try:
            bench_matrix = build_close_matrix(
                {config.benchmark_symbol: benchmark_frame},
                date_column=config.date_column,
                close_column=config.close_column,
                as_of=as_of_ts,
            )
            bench_col = (
                config.benchmark_symbol.upper()
                if config.benchmark_symbol.upper() in bench_matrix.columns
                else bench_matrix.columns[0]
            )
            aligned = stock_matrix.join(bench_matrix[bench_col].rename("__BENCH__"), how="inner")
            if len(aligned) <= config.lookback_12m:
                raise MomentumScoringError("Insufficient aligned history vs benchmark")
            stock_matrix = aligned.drop(columns=["__BENCH__"])
            bench_ret = period_return(aligned["__BENCH__"], config.lookback_6m)
            bench_6m = 0.0 if bench_ret is None else bench_ret
        except RelativeStrengthScoringError as exc:
            raise MomentumScoringError(str(exc)) from exc

    r1 = batch_period_returns(stock_matrix, config.lookback_1m)
    r3 = batch_period_returns(stock_matrix, config.lookback_3m)
    r6 = batch_period_returns(stock_matrix, config.lookback_6m)
    r12 = batch_period_returns(stock_matrix, config.lookback_12m)
    as_of_dt = pd.Timestamp(stock_matrix.index[-1]).to_pydatetime()

    scores: list[MomentumScore] = []
    for symbol in stock_matrix.columns:
        v1, v3, v6, v12 = r1.get(symbol), r3.get(symbol), r6.get(symbol), r12.get(symbol)
        if pd.isna(v1) or pd.isna(v3) or pd.isna(v6) or pd.isna(v12):
            continue
        f1, f3, f6, f12 = float(v1), float(v3), float(v6), float(v12)
        momentum = (
            config.weight_1m * f1
            + config.weight_3m * f3
            + config.weight_6m * f6
            + config.weight_12m * f12
        ) / config.weight_total
        acceleration = f1 - f3
        persistence = sum(1 for value in (f1, f3, f6, f12) if value > 0) / 4.0
        relative_strength = f6 - bench_6m
        scores.append(
            MomentumScore(
                symbol=symbol,
                as_of=as_of_dt,
                return_1m=f1,
                return_3m=f3,
                return_6m=f6,
                return_12m=f12,
                momentum_score=momentum,
                acceleration=acceleration,
                persistence=persistence,
                relative_strength=relative_strength,
            ),
        )
    return scores


def score_symbol(
    frame: pd.DataFrame,
    *,
    symbol: str,
    config: MomentumConfig,
    benchmark_frame: pd.DataFrame | None = None,
    as_of: pd.Timestamp | datetime | None = None,
) -> MomentumScore:
    """Score a single symbol via the batch engine."""
    scores = score_universe(
        {symbol: frame},
        config=config,
        benchmark_frame=benchmark_frame,
        as_of=as_of,
    )
    if not scores:
        raise MomentumScoringError(f"Unable to score momentum for '{symbol}'")
    return scores[0]


class MomentumEngine:
    """Injectable momentum engine for strategies, AI, and portfolio code."""

    def __init__(self, config: MomentumConfig | None = None) -> None:
        self._config = config or MomentumConfig()

    @property
    def config(self) -> MomentumConfig:
        return self._config

    def score(
        self,
        frames: dict[str, pd.DataFrame],
        *,
        benchmark_frame: pd.DataFrame | None = None,
        as_of: pd.Timestamp | datetime | None = None,
    ) -> list[MomentumScore]:
        return score_universe(
            frames,
            config=self._config,
            benchmark_frame=benchmark_frame,
            as_of=as_of,
        )

    def score_one(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        benchmark_frame: pd.DataFrame | None = None,
        as_of: pd.Timestamp | datetime | None = None,
    ) -> MomentumScore:
        return score_symbol(
            frame,
            symbol=symbol,
            config=self._config,
            benchmark_frame=benchmark_frame,
            as_of=as_of,
        )
