"""Relative Strength Screener — batch NIFTY500 ranking facade."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.core.logging import get_logger
from app.feature_engine.feature_repository import FeatureRepository
from app.market_data.exceptions import RepositoryError
from app.market_data.universe.nifty500 import DEFAULT_SYMBOLS_FILE
from app.strategies.relative_strength.config import RelativeStrengthConfig
from app.strategies.relative_strength.ranking import rank_scores, ranks_dict
from app.strategies.relative_strength.schemas import ScreenerResult, UniverseRanking
from app.strategies.relative_strength.scoring import (
    RelativeStrengthScoringError,
    score_universe,
)

logger = get_logger(__name__)


def load_sector_map(
    symbols_file: Path | str = DEFAULT_SYMBOLS_FILE,
) -> dict[str, str]:
    """Map local Symbol → Industry from the NIFTY500 constituents CSV."""
    path = Path(symbols_file)
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("Series") or "").strip().upper() != "EQ":
                continue
            symbol = (row.get("Symbol") or "").strip().upper()
            industry = (row.get("Industry") or "").strip()
            if symbol and industry:
                mapping[symbol] = industry
    return mapping


def load_universe_frames(
    symbols: list[str],
    repository: FeatureRepository,
    *,
    min_bars: int,
) -> dict[str, pd.DataFrame]:
    """Batch-load feature frames from the Feature Store (skips missing)."""
    loaded: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            if not repository.exists(symbol):
                continue
            frame = repository.read(symbol)
        except RepositoryError as exc:
            logger.debug("Skip %s: %s", symbol, exc)
            continue
        if frame is None or len(frame) < min_bars:
            continue
        loaded[symbol.upper().replace(".NS", "")] = frame
    return loaded


class RelativeStrengthScreener:
    """Produce Top / Worst / Improving / Weakening RS lists for a universe."""

    def __init__(
        self,
        config: RelativeStrengthConfig | None = None,
        *,
        sector_map: dict[str, str] | None = None,
    ) -> None:
        self._config = config or RelativeStrengthConfig()
        self._sector_map = sector_map if sector_map is not None else load_sector_map()
        self._previous_ranks: dict[str, int] = {}

    @property
    def config(self) -> RelativeStrengthConfig:
        return self._config

    def bind_previous_ranking(self, ranking: UniverseRanking) -> RelativeStrengthScreener:
        self._previous_ranks = ranks_dict(ranking)
        return self

    def rank_frames(
        self,
        frames: dict[str, pd.DataFrame],
        benchmark_frame: pd.DataFrame,
        *,
        as_of: pd.Timestamp | datetime | None = None,
        list_size: int = 25,
    ) -> ScreenerResult:
        """Score + rank an in-memory universe (optimized batch path)."""
        scores = score_universe(
            frames,
            benchmark_frame,
            config=self._config,
            sector_by_symbol=self._sector_map,
            as_of=as_of,
        )
        ranking = rank_scores(
            scores,
            benchmark_symbol=self._config.benchmark_symbol,
            previous_ranks=self._previous_ranks or None,
        )
        self._previous_ranks = ranks_dict(ranking)
        return self._to_screener_result(ranking, list_size=list_size)

    def rank_repository(
        self,
        symbols: list[str],
        repository: FeatureRepository,
        *,
        benchmark_symbol: str | None = None,
        as_of: pd.Timestamp | datetime | None = None,
        list_size: int = 25,
    ) -> ScreenerResult:
        """Load Feature Store frames for ``symbols`` + benchmark, then rank."""
        bench = (benchmark_symbol or self._config.benchmark_symbol).upper()
        frames = load_universe_frames(
            symbols,
            repository,
            min_bars=self._config.min_history_bars,
        )
        if bench not in frames and not repository.exists(bench):
            raise RelativeStrengthScoringError(
                f"Benchmark features not found for '{bench}'",
            )
        if bench in frames:
            benchmark_frame = frames.pop(bench)
        else:
            benchmark_frame = repository.read(bench)
        if not frames:
            raise RelativeStrengthScoringError("No universe feature frames available")
        return self.rank_frames(
            frames,
            benchmark_frame,
            as_of=as_of,
            list_size=list_size,
        )

    def _to_screener_result(
        self,
        ranking: UniverseRanking,
        *,
        list_size: int,
    ) -> ScreenerResult:
        size = max(1, list_size)
        improving = sorted(
            [row for row in ranking.ranked if row.rank_change is not None],
            key=lambda row: row.rank_change or 0,
            reverse=True,
        )[:size]
        weakening = sorted(
            [row for row in ranking.ranked if row.rank_change is not None],
            key=lambda row: row.rank_change or 0,
        )[:size]
        return ScreenerResult(
            as_of=ranking.as_of,
            benchmark_symbol=ranking.benchmark_symbol,
            top_ranked=ranking.ranked[:size],
            worst_ranked=list(reversed(ranking.ranked[-size:])) if ranking.ranked else [],
            fastest_improving=improving,
            fastest_weakening=weakening,
            ranking=ranking,
        )
