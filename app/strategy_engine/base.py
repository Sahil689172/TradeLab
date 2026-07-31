"""Abstract strategy contract for TradeLab."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from app.strategy_engine.models import Signal, TradePlan


class BaseStrategy(ABC):
    """Contract every concrete strategy must implement.

    Strategies consume a feature DataFrame only. This foundation defines the
    lifecycle interface — validation, preparation, signal generation, and trade
    plan construction — without embedding indicator, risk, or price-action logic.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable registry key and TradePlan strategy identifier."""

    @abstractmethod
    def validate(self, features: pd.DataFrame) -> None:
        """Validate that ``features`` satisfies strategy prerequisites.

        Raises:
            StrategyValidationError: When required columns, length, or shape
                constraints are not met.
        """

    @abstractmethod
    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        """Return a strategy-ready view of ``features``.

        Implementations may sort, slice, or select columns. They must not mutate
        the caller's DataFrame in place unless that is explicitly documented by
        the concrete strategy.
        """

    @abstractmethod
    def generate_signal(self, features: pd.DataFrame) -> Signal:
        """Produce a trading signal from prepared feature data."""

    @abstractmethod
    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        """Build a trade plan for ``signal`` using prepared feature data."""
