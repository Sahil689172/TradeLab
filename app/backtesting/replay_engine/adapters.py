"""Default adapters wiring Market Data / Features / Strategy Engine into replay."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.feature_engine.strategy_frame import load_strategy_features
from app.services.strategy_context import ContextProviderConfig, StrategyContextProvider
from app.services.trade_recommendation.engine import TradeRecommendationEngine
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.services.trade_recommendation.strategy_validation import (
    StrategyValidationFramework,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.symbols import attach_symbol


class ParquetFeatureFrameAdapter:
    """Load strategy-ready frames from parquet storage."""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        settings = get_settings()
        self._storage_dir = Path(storage_dir or settings.parquet_storage_dir)

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    def load_features(self, symbol: str) -> pd.DataFrame | None:
        frame = load_strategy_features(symbol, self._storage_dir)
        if frame is None:
            return None
        return attach_symbol(frame, symbol)


class GatewayMarketDataAdapter:
    """Thin adapter over ``MarketDataGateway.get_history``."""

    def __init__(self, gateway: object) -> None:
        self._gateway = gateway

    def get_history(self, symbol: str) -> pd.DataFrame:
        return self._gateway.get_history(symbol)  # type: ignore[no-any-return]


class ParquetMarketDataAdapter:
    """Load OHLCV directly from parquet without a live DB session."""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        from app.market_data.utils.symbols import parquet_basename

        settings = get_settings()
        self._storage_dir = Path(storage_dir or settings.parquet_storage_dir)
        self._basename = parquet_basename

    def get_history(self, symbol: str) -> pd.DataFrame:
        path = self._storage_dir / f"{self._basename(symbol)}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"OHLCV parquet not found: {path}")
        return pd.read_parquet(path, engine="pyarrow")


class ContextStrategyEvaluator:
    """Reuse StrategyContextProvider + TradeRecommendationEngine (no strategy edits)."""

    def __init__(
        self,
        *,
        context_provider: StrategyContextProvider | None = None,
        recommendation_engine: TradeRecommendationEngine | None = None,
        storage_dir: Path | str | None = None,
        timeframe: str = "1 Day",
    ) -> None:
        settings = get_settings()
        storage = Path(storage_dir or settings.parquet_storage_dir)
        self._provider = context_provider or StrategyContextProvider(
            ContextProviderConfig(
                timeframe=timeframe,
                storage_dir=str(storage),
                allow_synthetic_features=False,
            ),
            storage_dir=storage,
        )
        self._engine = recommendation_engine or TradeRecommendationEngine()
        self._timeframe = timeframe

    def evaluate(
        self,
        *,
        strategy: BaseStrategy,
        symbol: str,
        window: pd.DataFrame,
        timestamp: datetime,
        timeframe: str | None = None,
    ) -> TradeRecommendation:
        frame = attach_symbol(window, symbol)
        context = self._provider.prepare(strategy, symbol, features=frame)
        plan = strategy.execute(context)
        detailed = getattr(strategy, "last_detailed_plan", None)
        return self._engine.recommend(
            plan,
            timeframe=timeframe or self._timeframe,
            timestamp=timestamp,
            detailed_plan=detailed,
            recompute_confidence=True,
        )


class FrameworkStrategyFactory:
    """Resolve strategies via ``StrategyValidationFramework`` aliases."""

    def __init__(self, *, timeframe: str = "1 Day") -> None:
        self._framework = StrategyValidationFramework(timeframe=timeframe)

    def resolve(self, names: Sequence[str]) -> list[BaseStrategy]:
        return self._framework.resolve_strategies(list(names))
