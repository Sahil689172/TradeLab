"""Relative Strength strategy package (cross-sectional vs NIFTY500 — not RSI)."""

from __future__ import annotations

from app.strategies.relative_strength.config import RelativeStrengthConfig
from app.strategies.relative_strength.ranking import (
    below_sell_percentile,
    in_top_percentile,
    lookup_rank,
    rank_scores,
    ranks_dict,
)
from app.strategies.relative_strength.registration import (
    build_relative_strength_strategy,
    register_relative_strength_strategy,
)
from app.strategies.relative_strength.schemas import (
    RankBucket,
    RankedSymbol,
    RelativeStrengthPlan,
    RelativeStrengthScore,
    RelativeStrengthSetup,
    ScreenerResult,
    UniverseRanking,
)
from app.strategies.relative_strength.scoring import (
    RelativeStrengthScoringError,
    batch_period_returns,
    build_close_matrix,
    period_return,
    score_symbol,
    score_universe,
)
from app.strategies.relative_strength.strategy import RelativeStrengthStrategy

__all__ = [
    "RankBucket",
    "RankedSymbol",
    "RelativeStrengthConfig",
    "RelativeStrengthPlan",
    "RelativeStrengthScore",
    "RelativeStrengthScoringError",
    "RelativeStrengthScreener",
    "RelativeStrengthSetup",
    "RelativeStrengthStrategy",
    "ScreenerResult",
    "UniverseRanking",
    "batch_period_returns",
    "below_sell_percentile",
    "build_close_matrix",
    "build_relative_strength_strategy",
    "in_top_percentile",
    "load_sector_map",
    "load_universe_frames",
    "lookup_rank",
    "period_return",
    "rank_scores",
    "ranks_dict",
    "register_relative_strength_strategy",
    "score_symbol",
    "score_universe",
]


def __getattr__(name: str):
    """Lazily load screener helpers so core strategy imports stay lightweight."""
    if name in {"RelativeStrengthScreener", "load_sector_map", "load_universe_frames"}:
        from app.strategies.relative_strength.screener import (
            RelativeStrengthScreener,
            load_sector_map,
            load_universe_frames,
        )

        exports = {
            "RelativeStrengthScreener": RelativeStrengthScreener,
            "load_sector_map": load_sector_map,
            "load_universe_frames": load_universe_frames,
        }
        return exports[name]
    raise AttributeError(name)
