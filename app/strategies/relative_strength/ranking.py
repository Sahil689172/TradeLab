"""Cross-sectional ranking of Relative Strength scores."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.strategies.relative_strength.schemas import (
    RankedSymbol,
    RelativeStrengthScore,
    UniverseRanking,
)


def rank_scores(
    scores: list[RelativeStrengthScore],
    *,
    benchmark_symbol: str,
    previous_ranks: dict[str, int] | None = None,
    strongest_count: int = 10,
) -> UniverseRanking:
    """Rank scores by strength_score descending (1 = strongest)."""
    if not scores:
        return UniverseRanking(
            as_of=datetime.now(tz=timezone.utc),
            benchmark_symbol=benchmark_symbol,
            universe_size=0,
            ranked=[],
        )

    ordered = sorted(scores, key=lambda item: item.strength_score, reverse=True)
    n = len(ordered)
    prior = {key.upper(): value for key, value in (previous_ranks or {}).items()}
    ranked: list[RankedSymbol] = []
    for index, score in enumerate(ordered, start=1):
        previous = prior.get(score.symbol.upper())
        rank_change = None if previous is None else previous - index
        percentile = 1.0 - (index - 1) / n
        ranked.append(
            RankedSymbol(
                symbol=score.symbol,
                rank=index,
                previous_rank=previous,
                percentile=percentile,
                score=score,
                rank_change=rank_change,
            ),
        )

    return UniverseRanking(
        as_of=ordered[0].as_of,
        benchmark_symbol=benchmark_symbol,
        universe_size=n,
        ranked=ranked,
        top_10=ranked[:10],
        top_25=ranked[:25],
        top_50=ranked[:50],
        top_100=ranked[:100],
        strongest=ranked[: min(strongest_count, n)],
    )


def lookup_rank(ranking: UniverseRanking, symbol: str) -> RankedSymbol | None:
    """Return the ranked row for ``symbol`` if present."""
    target = symbol.strip().upper()
    for row in ranking.ranked:
        if row.symbol.upper() == target:
            return row
    return None


def in_top_percentile(
    row: RankedSymbol,
    top_percentile: float,
    *,
    universe_size: int | None = None,
) -> bool:
    """True when the symbol is inside the strongest ``top_percentile`` fraction."""
    size = universe_size if universe_size is not None else max(row.rank, 1)
    cutoff = max(1, int(math.ceil(size * top_percentile)))
    return row.rank <= cutoff


def below_sell_percentile(
    row: RankedSymbol,
    sell_rank_percentile: float,
    *,
    universe_size: int,
) -> bool:
    """True when rank has fallen outside the hold band (worse than cut)."""
    cutoff = max(1, int(math.ceil(universe_size * sell_rank_percentile)))
    return row.rank > cutoff


def ranks_dict(ranking: UniverseRanking) -> dict[str, int]:
    """Map symbol → current rank for prior-snapshot comparisons."""
    return {row.symbol.upper(): row.rank for row in ranking.ranked}
