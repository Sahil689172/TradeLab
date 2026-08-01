"""Quantitative Momentum strategy package (historical returns — not RSI)."""

from app.strategies.momentum.config import MomentumConfig
from app.strategies.momentum.ranking import (
    in_top_percentile,
    lookup_rank,
    rank_scores,
)
from app.strategies.momentum.registration import (
    build_momentum_strategy,
    register_momentum_strategy,
)
from app.strategies.momentum.schemas import (
    MomentumPlan,
    MomentumScore,
    MomentumSetup,
    MomentumUniverseRanking,
    RankedMomentum,
)
from app.strategies.momentum.scoring import (
    MomentumEngine,
    MomentumScoringError,
    score_symbol,
    score_universe,
)
from app.strategies.momentum.strategy import MomentumStrategy

__all__ = [
    "MomentumConfig",
    "MomentumEngine",
    "MomentumPlan",
    "MomentumScore",
    "MomentumScoringError",
    "MomentumSetup",
    "MomentumStrategy",
    "MomentumUniverseRanking",
    "RankedMomentum",
    "build_momentum_strategy",
    "in_top_percentile",
    "lookup_rank",
    "rank_scores",
    "register_momentum_strategy",
    "score_symbol",
    "score_universe",
]
