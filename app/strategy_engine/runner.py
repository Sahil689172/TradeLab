"""Orchestrates the BaseStrategy lifecycle over a feature DataFrame."""

from __future__ import annotations

import pandas as pd

from app.core.logging import get_logger
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyEngineError, StrategyValidationError
from app.strategy_engine.models import Signal, TradePlan
from app.strategy_engine.symbols import resolve_symbol_from_features

logger = get_logger(__name__)


class StrategyRunner:
    """Run a single strategy against feature data and return a TradePlan.

    Lifecycle (no business logic):
        bind symbol from features → validate → prepare → generate_signal →
        generate_trade_plan → optional filter pipeline (A4X.6)
    """

    def run(
        self,
        features: pd.DataFrame,
        strategy: BaseStrategy,
        *,
        apply_filters: bool | None = None,
    ) -> TradePlan:
        """Execute ``strategy`` against ``features`` and return a trade plan.

        Args:
            features: Feature DataFrame produced by the feature engineering engine.
                Symbol should be present in ``features.attrs["symbol"]`` or a
                ``symbol`` column so it propagates into TradePlan automatically.
            strategy: Concrete ``BaseStrategy`` implementation.
            apply_filters: When None, uses ``strategy.filter_pipeline_enabled``
                (default False). When True/False, overrides the strategy config.

        Returns:
            TradePlan produced by the strategy (possibly filter-adjusted).

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

        symbol = resolve_symbol_from_features(features)
        if symbol:
            strategy.bind_symbol(symbol)

        logger.info(
            "Running strategy '%s' on %d feature rows (symbol=%s)",
            strategy.name,
            len(features),
            strategy.active_symbol,
        )

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

        # Preserve symbol attrs across prepare() copies that drop attrs
        if symbol and resolve_symbol_from_features(prepared) is None:
            prepared = prepared.copy(deep=False)
            prepared.attrs = dict(getattr(features, "attrs", {}) or {})
            prepared.attrs["symbol"] = symbol
            strategy.bind_symbol(symbol)

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

        if symbol and trade_plan.symbol != symbol:
            raise StrategyEngineError(
                f"Strategy '{strategy.name}' dropped input symbol: "
                f"expected {symbol!r}, got {trade_plan.symbol!r}",
            )

        should_filter = (
            strategy.filter_pipeline_enabled if apply_filters is None else bool(apply_filters)
        )
        if should_filter:
            from app.strategy_engine.filters.integration import apply_strategy_filter_pipeline

            options = strategy.filter_pipeline_options
            trade_plan, _result = apply_strategy_filter_pipeline(
                trade_plan,
                profile=strategy.filter_profile,
                features=prepared,
                enable_optional=options.get("enable_optional"),
                disable=options.get("disable"),
                param_overrides=options.get("param_overrides"),
            )

        logger.info(
            "Strategy '%s' produced %s plan for %s (confidence=%.4f)",
            strategy.name,
            trade_plan.signal.value,
            trade_plan.symbol,
            trade_plan.confidence,
        )
        return trade_plan
