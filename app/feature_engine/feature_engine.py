"""High-level feature generation orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

import pandas as pd

from app.core.logging import get_logger
from app.feature_engine.cache import FeatureCache
from app.feature_engine.feature_repository import FeatureRepository
from app.feature_engine.pipeline import FeaturePipeline
from app.feature_engine.schemas import FeatureGenerationResult

logger = get_logger(__name__)


class MarketDataReader(Protocol):
    """Minimal market-data dependency required by the feature engine."""

    def get_history(self, symbol: str) -> pd.DataFrame:
        """Return canonical OHLCV history for a symbol."""


class FeatureEngine:
    """Generate, persist, cache, and incrementally update feature datasets."""

    def __init__(
        self,
        market_data: MarketDataReader,
        repository: FeatureRepository,
        cache: FeatureCache,
        pipeline: FeaturePipeline | None = None,
    ) -> None:
        self._market_data = market_data
        self._repository = repository
        self._cache = cache
        self._pipeline = pipeline or FeaturePipeline()

    def generate(self, symbol: str, *, force: bool = False) -> FeatureGenerationResult:
        """Generate features for one symbol."""
        normalized_symbol = symbol.strip().upper()
        source = self._market_data.get_history(normalized_symbol)
        decision = "rebuild" if force else self._cache.decide(
            normalized_symbol,
            source,
            self._pipeline.version,
            feature_file_exists=self._repository.exists(normalized_symbol),
        )
        path = self._repository.path_for(normalized_symbol)

        if decision == "current":
            record = self._cache.load(normalized_symbol)
            feature_rows = record.feature_rows if record else len(self._repository.read(normalized_symbol))
            logger.info("Feature cache hit for %s", normalized_symbol)
            return FeatureGenerationResult(
                symbol=normalized_symbol,
                status="cached",
                source_rows=len(source),
                feature_rows=feature_rows,
                rows_added=0,
                cache_hit=True,
                feature_path=str(path),
            )

        generated = self._pipeline.transform(source)
        rows_added = len(generated)
        status = "generated"

        if decision == "append" and self._repository.exists(normalized_symbol):
            existing = self._repository.read(normalized_symbol)
            latest_date = pd.to_datetime(existing["date"]).max()
            additions = generated[pd.to_datetime(generated["date"]) > latest_date].copy()
            if not additions.empty:
                self._repository.append(normalized_symbol, additions)
            rows_added = len(additions)
            status = "updated"
        else:
            self._repository.write(normalized_symbol, generated)

        stored = self._repository.read(normalized_symbol)
        self._cache.save(
            normalized_symbol,
            source,
            stored,
            self._pipeline.version,
        )
        logger.info(
            "Feature generation %s for %s: source=%d features=%d added=%d",
            status,
            normalized_symbol,
            len(source),
            len(stored),
            rows_added,
        )
        return FeatureGenerationResult(
            symbol=normalized_symbol,
            status=status,
            source_rows=len(source),
            feature_rows=len(stored),
            rows_added=rows_added,
            cache_hit=False,
            feature_path=str(path),
        )

    def generate_all(
        self,
        symbols: Iterable[str],
        *,
        force: bool = False,
    ) -> list[FeatureGenerationResult]:
        """Generate features for symbols independently, in input order."""
        return [self.generate(symbol, force=force) for symbol in symbols]
