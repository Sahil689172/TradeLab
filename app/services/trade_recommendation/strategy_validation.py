"""Automatic validation framework — run strategies and verify recommendations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from statistics import mean

import pandas as pd

from app.services.strategy_context import (
    ContextProviderConfig,
    StrategyContextError,
    StrategyContextProvider,
)
from app.services.trade_recommendation.engine import TradeRecommendationEngine
from app.services.trade_recommendation.report import format_validation_report_table
from app.services.trade_recommendation.schemas import (
    RecommendationConfig,
    StrategyValidationReport,
    StrategyValidationRow,
)
from app.services.trade_recommendation.validator import TradeRecommendationValidationError
from app.strategies import (
    register_break_retest_strategy,
    register_cpr_strategy,
    register_darvas_box_strategy,
    register_donchian_strategy,
    register_ema_trend_professional_strategy,
    register_ema_trend_strategy,
    register_momentum_strategy,
    register_opening_range_breakout_strategy,
    register_previous_day_breakout_strategy,
    register_relative_strength_strategy,
    register_supertrend_strategy,
    register_volume_breakout_strategy,
    register_vwap_strategy,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyEngineError, StrategyValidationError
from app.strategy_engine.models import SignalType
from app.strategy_engine.registry import StrategyRegistry
from app.strategy_engine.runner import StrategyRunner
from app.strategy_engine.symbols import (
    UNBOUND_SYMBOL,
    resolve_symbol_from_features,
)

RegisterFn = Callable[[StrategyRegistry], BaseStrategy]

# CLI / framework aliases → registry register helpers
STRATEGY_REGISTERARS: dict[str, RegisterFn] = {
    "ema": register_ema_trend_strategy,
    "ema_trend": register_ema_trend_strategy,
    "ema_raw": register_ema_trend_strategy,
    "ema_professional": register_ema_trend_professional_strategy,
    "ema_trend_professional": register_ema_trend_professional_strategy,
    "previous_day_breakout": register_previous_day_breakout_strategy,
    "pdh": register_previous_day_breakout_strategy,
    "pdl": register_previous_day_breakout_strategy,
    "orb": register_opening_range_breakout_strategy,
    "opening_range_breakout": register_opening_range_breakout_strategy,
    "vwap": register_vwap_strategy,
    "cpr": register_cpr_strategy,
    "volume_breakout": register_volume_breakout_strategy,
    "relative_strength": register_relative_strength_strategy,
    "rs": register_relative_strength_strategy,
    "momentum": register_momentum_strategy,
    "darvas": register_darvas_box_strategy,
    "darvas_box": register_darvas_box_strategy,
    "break_retest": register_break_retest_strategy,
    "supertrend": register_supertrend_strategy,
    "donchian": register_donchian_strategy,
}

# Canonical strategy names for --strategy all (unique register callables)
_ALL_REGISTRARS: tuple[RegisterFn, ...] = (
    register_ema_trend_strategy,
    register_previous_day_breakout_strategy,
    register_opening_range_breakout_strategy,
    register_vwap_strategy,
    register_cpr_strategy,
    register_volume_breakout_strategy,
    register_relative_strength_strategy,
    register_momentum_strategy,
    register_darvas_box_strategy,
    register_break_retest_strategy,
    register_supertrend_strategy,
    register_donchian_strategy,
)


class StrategyValidationFramework:
    """Run strategies on feature data and verify TradeRecommendation contracts.

    Execution context (daily / levels / rankings) is prepared exclusively by
    ``StrategyContextProvider`` — this framework never calls ``bind_*`` manually.
    """

    def __init__(
        self,
        *,
        engine: TradeRecommendationEngine | None = None,
        runner: StrategyRunner | None = None,
        context_provider: StrategyContextProvider | None = None,
        config: RecommendationConfig | None = None,
        timeframe: str = "15 Minute",
    ) -> None:
        self._config = config or RecommendationConfig()
        self._engine = engine or TradeRecommendationEngine(self._config)
        self._runner = runner or StrategyRunner()
        self._timeframe = timeframe
        self._context_provider = context_provider or StrategyContextProvider(
            ContextProviderConfig(timeframe=timeframe),
            runner=self._runner,
        )

    def resolve_strategies(self, names: list[str] | None) -> list[BaseStrategy]:
        """Build strategy instances from alias list or all known strategies."""
        registry = StrategyRegistry()
        if not names or any(name.strip().lower() == "all" for name in names):
            for register in _ALL_REGISTRARS:
                register(registry)
            return list(registry.as_mapping().values())

        seen: set[RegisterFn] = set()
        for raw in names:
            key = raw.strip().lower()
            register = STRATEGY_REGISTERARS.get(key)
            if register is None:
                raise KeyError(
                    f"Unknown strategy '{raw}'. Known: {sorted(STRATEGY_REGISTERARS)}",
                )
            if register in seen:
                continue
            register(registry)
            seen.add(register)
        return list(registry.as_mapping().values())

    def validate_strategy(
        self,
        strategy: BaseStrategy,
        features: pd.DataFrame,
        *,
        symbol: str | None = None,
    ) -> StrategyValidationRow:
        """Run one strategy and validate the resulting recommendation."""
        errors: list[str] = []
        buy = sell = hold = exit_ = 0
        confidences: list[float] = []
        holdings: list[float] = []
        signals_generated = 0
        status = "PASS"

        try:
            resolved_symbol = (
                symbol.strip().upper()
                if symbol
                else resolve_symbol_from_features(features)
            )
            if not resolved_symbol or resolved_symbol == UNBOUND_SYMBOL:
                raise StrategyContextError(
                    "Symbol required for StrategyContextProvider.prepare "
                    "(pass symbol= or set features.attrs['symbol'])",
                )

            # Context Provider is the only place that binds daily/levels/ranking.
            context = self._context_provider.prepare(
                strategy,
                resolved_symbol,
                features=features,
            )
            plan = strategy.execute(context)
            signals_generated = 1
            if plan.signal is SignalType.BUY:
                buy = 1
            elif plan.signal is SignalType.SELL:
                sell = 1
            elif plan.signal is SignalType.EXIT:
                exit_ = 1
            else:
                hold = 1

            detailed = getattr(strategy, "last_detailed_plan", None)
            recommendation = self._engine.recommend(
                plan,
                timeframe=self._timeframe,
                detailed_plan=detailed,
                recompute_confidence=True,
            )
            confidences.append(recommendation.confidence)
            holdings.append(float(recommendation.expected_holding_period))

            if recommendation.symbol != resolved_symbol:
                errors.append(
                    f"symbol mismatch: recommendation={recommendation.symbol} "
                    f"expected={resolved_symbol}",
                )
            if recommendation.symbol == UNBOUND_SYMBOL:
                errors.append(
                    "TradeRecommendation.symbol is UNKNOWN — input symbol did not propagate",
                )
        except (
            StrategyContextError,
            StrategyValidationError,
            StrategyEngineError,
            TradeRecommendationValidationError,
            ValueError,
            TypeError,
        ) as exc:
            status = "FAIL"
            errors.append(str(exc))
        except Exception as exc:  # noqa: BLE001 — surface unexpected strategy bugs
            status = "FAIL"
            errors.append(f"Unexpected: {type(exc).__name__}: {exc}")
        if errors and status == "PASS":
            status = "FAIL"

        return StrategyValidationRow(
            strategy=strategy.name,
            status=status,
            signals_generated=signals_generated,
            buy_count=buy,
            sell_count=sell,
            hold_count=hold,
            exit_count=exit_,
            average_confidence=mean(confidences) if confidences else 0.0,
            average_holding=mean(holdings) if holdings else 0.0,
            validation_errors=errors,
        )

    def validate_many(
        self,
        features: pd.DataFrame,
        *,
        strategies: list[BaseStrategy] | None = None,
        strategy_names: list[str] | None = None,
        symbol: str = "UNKNOWN",
    ) -> StrategyValidationReport:
        instances = strategies or self.resolve_strategies(strategy_names)
        rows = [
            self.validate_strategy(strategy, features, symbol=symbol)
            for strategy in instances
        ]
        failed = sum(1 for row in rows if row.status != "PASS")
        passed = len(rows) - failed
        total_errors = sum(len(row.validation_errors) for row in rows)
        return StrategyValidationReport(
            symbol=symbol.strip().upper(),
            timeframe=self._timeframe,
            generated_at=datetime.now(timezone.utc),
            rows=rows,
            total_errors=total_errors,
            passed=passed,
            failed=failed,
        )

    def format_report(self, report: StrategyValidationReport) -> str:
        rows: list[dict[str, object]] = [
            {
                "strategy": row.strategy,
                "status": row.status,
                "signals_generated": row.signals_generated,
                "buy_count": row.buy_count,
                "sell_count": row.sell_count,
                "hold_count": row.hold_count,
                "average_confidence": row.average_confidence,
                "average_holding": row.average_holding,
                "validation_errors": row.validation_errors,
            }
            for row in report.rows
        ]
        header = (
            f"Strategy Validation Report — {report.symbol} @ {report.timeframe}\n"
            f"Generated: {report.generated_at.isoformat()}\n"
            f"Passed: {report.passed}  Failed: {report.failed}  "
            f"Errors: {report.total_errors}\n\n"
        )
        body = format_validation_report_table(rows)
        detail_lines: list[str] = []
        for row in report.rows:
            if row.validation_errors:
                detail_lines.append(f"\n{row.strategy} errors:")
                for err in row.validation_errors:
                    detail_lines.append(f"  - {err}")
        return header + body + "".join(detail_lines)


def known_strategy_aliases() -> Mapping[str, str]:
    """Alias → registrar function name for CLI help."""
    return {alias: fn.__name__ for alias, fn in STRATEGY_REGISTERARS.items()}
