"""Cross-sectional ranking of quantitative Momentum scores."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.strategies.momentum.schemas import (
    MomentumScore,
    MomentumUniverseRanking,
    RankedMomentum,
)


def rank_scores(
    scores: list[MomentumScore],
    *,
    top_percentile: float = 0.20,
    portfolio_size: int | None = None,
) -> MomentumUniverseRanking:
    """Rank by momentum_score descending (1 = strongest)."""
    if not scores:
        return MomentumUniverseRanking(
            as_of=datetime.now(tz=timezone.utc),
            universe_size=0,
            ranked=[],
        )

    ordered = sorted(scores, key=lambda item: item.momentum_score, reverse=True)
    n = len(ordered)
    ranked: list[RankedMomentum] = []
    for index, score in enumerate(ordered, start=1):
        percentile = 1.0 - (index - 1) / n
        ranked.append(
            RankedMomentum(
                symbol=score.symbol,
                rank=index,
                percentile=percentile,
                score=score,
            ),
        )

    cutoff = max(1, int(math.ceil(n * top_percentile)))
    if portfolio_size is not None:
        cutoff = max(1, min(portfolio_size, n))

    return MomentumUniverseRanking(
        as_of=ordered[0].as_of,
        universe_size=n,
        ranked=ranked,
        top_10=ranked[:10],
        top_25=ranked[:25],
        top_50=ranked[:50],
        portfolio=ranked[:cutoff],
    )


def lookup_rank(ranking: MomentumUniverseRanking, symbol: str) -> RankedMomentum | None:
    target = symbol.strip().upper()
    for row in ranking.ranked:
        if row.symbol.upper() == target:
            return row
    return None


def in_top_percentile(
    row: RankedMomentum,
    top_percentile: float,
    *,
    universe_size: int,
) -> bool:
    cutoff = max(1, int(math.ceil(universe_size * top_percentile)))
    return row.rank <= cutoff
