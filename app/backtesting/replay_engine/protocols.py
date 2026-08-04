"""Protocols for Dependency Injection into the replay engine."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.base import BaseStrategy


@runtime_checkable
class MarketDataPort(Protocol):
    """Load full OHLCV history for a symbol (date filtering is the engine's job)."""

    def get_history(self, symbol: str) -> pd.DataFrame:
        """Return OHLCV with at least date/open/high/low/close/volume."""


@runtime_checkable
class FeatureFramePort(Protocol):
    """Optional strategy-ready feature loader (OHLCV+indicators)."""

    def load_features(self, symbol: str) -> pd.DataFrame | None:
        """Return merged features or ``None`` when unavailable."""


@runtime_checkable
class StrategyEvaluatorPort(Protocol):
    """Evaluate strategies on a look-ahead-safe historical window."""

    def evaluate(
        self,
        *,
        strategy: BaseStrategy,
        symbol: str,
        window: pd.DataFrame,
        timestamp: datetime,
        timeframe: str,
    ) -> TradeRecommendation:
        """Run prepare → execute → TradeRecommendation on ``window`` only."""


@runtime_checkable
class ReplayEventListener(Protocol):
    """Optional sink for replay lifecycle events."""

    def on_event(self, event: object) -> None:
        ...


@runtime_checkable
class StrategyFactoryPort(Protocol):
    """Resolve strategy instances from alias / name list."""

    def resolve(self, names: Sequence[str]) -> list[BaseStrategy]:
        ...
