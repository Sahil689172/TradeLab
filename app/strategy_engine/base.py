"""Abstract strategy contract for TradeLab."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pandas as pd

from app.strategy_engine.models import Signal, TradePlan
from app.strategy_engine.symbols import UNBOUND_SYMBOL, normalize_symbol

if TYPE_CHECKING:
    from app.services.strategy_context.schemas import StrategyContext
    from app.strategy_engine.filters.profiles import StrategyFilterProfile


class BaseStrategy(ABC):
    """Contract every concrete strategy must implement.

    Strategies consume a feature DataFrame only. This foundation defines the
    lifecycle interface — validation, preparation, signal generation, and trade
    plan construction — without embedding indicator, risk, or price-action logic.

    Filter pipeline (A4X.6)
    -----------------------
    Strategies declare a ``filter_profile`` (mandatory / optional / default /
    configurable). Raw signal logic is unchanged. ``StrategyRunner`` applies the
    pipeline only when ``filter_pipeline_enabled`` is True (default False for
    backwards compatibility).
    """

    def bind_symbol(self, symbol: str) -> BaseStrategy:
        """Bind the runtime trading symbol for this strategy instance."""
        self._runtime_symbol = normalize_symbol(symbol)
        return self

    @property
    def active_symbol(self) -> str:
        """Symbol that must appear on Signal / TradePlan outputs.

        Precedence: runtime bind → config.symbol → ``UNKNOWN``.
        """
        runtime = getattr(self, "_runtime_symbol", None)
        if runtime:
            return str(runtime)
        config = getattr(self, "_config", None)
        if config is not None:
            value = getattr(config, "symbol", None)
            if value is not None and str(value).strip():
                return str(value).strip().upper()
        return UNBOUND_SYMBOL

    @property
    def filter_profile(self) -> StrategyFilterProfile:
        """Research-default filter profile for this strategy (overridable)."""
        declared = getattr(type(self), "FILTER_PROFILE", None)
        if declared is not None:
            return declared
        from app.strategy_engine.filters.strategy_profiles import get_strategy_filter_profile

        return get_strategy_filter_profile(self.name)

    @property
    def filter_pipeline_enabled(self) -> bool:
        """When True, StrategyRunner runs the filter pipeline after TradePlan."""
        config = getattr(self, "_config", None)
        if config is not None and hasattr(config, "enable_filter_pipeline"):
            return bool(getattr(config, "enable_filter_pipeline"))
        return False

    @property
    def filter_pipeline_options(self) -> dict[str, Any]:
        """Optional enable_optional / disable / param_overrides from config."""
        config = getattr(self, "_config", None)
        if config is None:
            return {}
        options: dict[str, Any] = {}
        if hasattr(config, "filter_enable_optional"):
            options["enable_optional"] = set(getattr(config, "filter_enable_optional") or ())
        if hasattr(config, "filter_disable"):
            options["disable"] = set(getattr(config, "filter_disable") or ())
        if hasattr(config, "filter_param_overrides"):
            options["param_overrides"] = dict(getattr(config, "filter_param_overrides") or {})
        return options

    def execute(self, context: StrategyContext) -> TradePlan:
        """Apply prepared context and run the strategy lifecycle.

        Context binding (daily / levels / rankings) is owned by
        ``StrategyContextProvider`` — strategies stay independent of data loading.
        """
        from app.services.strategy_context.context_provider import StrategyContextProvider

        return StrategyContextProvider().execute_context(self, context)

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
