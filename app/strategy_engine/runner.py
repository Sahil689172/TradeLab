"""Orchestrates the BaseStrategy lifecycle over a feature DataFrame."""

from __future__ import annotations

import pandas as pd

from app.core.logging import get_logger
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyEngineError, StrategyValidationError
from app.strategy_engine.models import Signal, TradePlan

logger = get_logger(__name__)


class StrategyRunner:
    """Run a single strategy against feature data and return a TradePlan.

    Lifecycle (no business logic):
        validate → prepare → generate_signal → generate_trade_plan
    """

    def run(self, features: pd.DataFrame, strategy: BaseStrategy) -> TradePlan:
        """Execute ``strategy`` against ``features`` and return a trade plan.

        Args:
            features: Feature DataFrame produced by the feature engineering engine.
            strategy: Concrete ``BaseStrategy`` implementation.

        Returns:
            TradePlan produced by the strategy.

        Raises:
            TypeError: When inputs are not of the expected types.
            StrategyValidationError: When the feature frame is empty/invalid or
                strategy validation fails.
            StrategyEngineError: When prepare/signal/plan stages return invalid types.
        """
        if not isinstance(strategy, BaseStrategy):
            raise TypeError(
                f"Expected BaseStrategy instance, got {type(strategy).__name__}",
            )
        if not isinstance(features, pd.DataFrame):
            raise TypeError(
                f"Expected pandas DataFrame, got {type(features).__name__}",
            )
        if features.empty:
            raise StrategyValidationError("Feature DataFrame must not be empty")

        logger.info("Running strategy '%s' on %d feature rows", strategy.name, len(features))

        strategy.validate(features)
        prepared = strategy.prepare(features)
        if not isinstance(prepared, pd.DataFrame):
            raise StrategyEngineError(
                f"Strategy '{strategy.name}' prepare() must return a DataFrame, "
                f"got {type(prepared).__name__}",
            )
        if prepared.empty:
            raise StrategyValidationError(
                f"Strategy '{strategy.name}' prepare() returned an empty DataFrame",
            )

        signal = strategy.generate_signal(prepared)
        if not isinstance(signal, Signal):
            raise StrategyEngineError(
                f"Strategy '{strategy.name}' generate_signal() must return Signal, "
                f"got {type(signal).__name__}",
            )

        trade_plan = strategy.generate_trade_plan(prepared, signal)
        if not isinstance(trade_plan, TradePlan):
            raise StrategyEngineError(
                f"Strategy '{strategy.name}' generate_trade_plan() must return TradePlan, "
                f"got {type(trade_plan).__name__}",
            )

        logger.info(
            "Strategy '%s' produced %s plan for %s (confidence=%.4f)",
            strategy.name,
            trade_plan.signal.value,
            trade_plan.symbol,
            trade_plan.confidence,
        )
        return trade_plan
