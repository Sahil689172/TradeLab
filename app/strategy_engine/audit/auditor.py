"""Strategy auditor — evaluate signals, filters, and readiness (Phase A4X.8)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.strategy_engine.audit.comparison import build_comparison
from app.strategy_engine.audit.metrics import aggregate_metrics
from app.strategy_engine.audit.report import build_readiness_report
from app.strategy_engine.audit.schemas import (
    StrategyAuditMetrics,
    StrategyAuditReport,
)
from app.strategy_engine.audit.scorecard import build_scorecard
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.configuration import (
    default_system_config,
    list_bound_strategies,
    materialize_strategy,
)
from app.strategy_engine.exceptions import StrategyEngineError, StrategyValidationError
from app.strategy_engine.filters.integration import apply_strategy_filter_pipeline
from app.strategy_engine.filters.strategy_profiles import get_strategy_filter_profile
from app.strategy_engine.models import Signal, SignalType, TradePlan
from app.strategy_engine.symbols import attach_symbol, resolve_symbol_from_features


def _sample_buy_plan(strategy_name: str, symbol: str = "RELIANCE") -> TradePlan:
    return TradePlan(
        symbol=symbol,
        entry_price=100.0,
        signal=SignalType.BUY,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=115.0,
        holding_period=10,
        risk_reward=2.0,
        confidence=0.75,
        reasons=["audit_filter_probe"],
        strategy_name=strategy_name,
    )


def verify_filter_integration(
    strategy: BaseStrategy,
    *,
    features: pd.DataFrame | None = None,
) -> tuple[bool, str]:
    """Confirm profile exists and pipeline can run on a BUY recommendation."""
    try:
        profile = strategy.filter_profile
        if profile.strategy_name != strategy.name and profile.strategy_name:
            # Profiles are keyed by strategy name; tolerate declared profile
            pass
        get_strategy_filter_profile(strategy.name)
        options = strategy.filter_pipeline_options
        plan = _sample_buy_plan(strategy.name, symbol=strategy.active_symbol or "RELIANCE")
        _filtered, result = apply_strategy_filter_pipeline(
            plan,
            profile=profile,
            features=features,
            enable_optional=options.get("enable_optional"),
            disable=options.get("disable"),
            param_overrides=options.get("param_overrides"),
        )
        _ = result.filters_applied
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 — surface as integration failure
        return False, str(exc)


def _run_via_context(
    strategy: BaseStrategy,
    features: pd.DataFrame,
    *,
    symbol: str,
    apply_filters: bool,
) -> tuple[TradePlan, bool | None]:
    """Single evaluation through StrategyContextProvider (ranking/levels)."""
    from app.services.strategy_context import (
        ContextProviderConfig,
        StrategyContextProvider,
    )

    provider = StrategyContextProvider(ContextProviderConfig(timeframe="15 Minute"))
    context = provider.prepare(strategy, symbol, features=features)
    plan = strategy.execute(context)
    if not apply_filters or plan.signal is SignalType.HOLD:
        return plan, None
    options = strategy.filter_pipeline_options
    filtered, result = apply_strategy_filter_pipeline(
        plan,
        profile=strategy.filter_profile,
        features=features,
        enable_optional=options.get("enable_optional"),
        disable=options.get("disable"),
        param_overrides=options.get("param_overrides"),
    )
    return filtered, (not result.output.rejected)


def _run_lifecycle(
    strategy: BaseStrategy,
    features: pd.DataFrame,
    *,
    apply_filters: bool,
) -> tuple[TradePlan, bool | None]:
    """Validate → prepare → signal → plan → optional filters.

    Returns (plan, filter_accepted) where filter_accepted is None when filters
    were not evaluated (HOLD or apply_filters=False).
    """
    symbol = resolve_symbol_from_features(features)
    if symbol:
        strategy.bind_symbol(symbol)

    strategy.validate(features)
    prepared = strategy.prepare(features)
    if not isinstance(prepared, pd.DataFrame) or prepared.empty:
        raise StrategyValidationError(
            f"Strategy '{strategy.name}' prepare() returned empty/invalid frame",
        )
    if symbol and resolve_symbol_from_features(prepared) is None:
        prepared = attach_symbol(prepared.copy(deep=False), symbol)

    signal = strategy.generate_signal(prepared)
    if not isinstance(signal, Signal):
        raise StrategyEngineError(
            f"Strategy '{strategy.name}' generate_signal() must return Signal",
        )
    plan = strategy.generate_trade_plan(prepared, signal)
    if not isinstance(plan, TradePlan):
        raise StrategyEngineError(
            f"Strategy '{strategy.name}' generate_trade_plan() must return TradePlan",
        )

    if not apply_filters or plan.signal is SignalType.HOLD:
        return plan, None

    options = strategy.filter_pipeline_options
    filtered, result = apply_strategy_filter_pipeline(
        plan,
        profile=strategy.filter_profile,
        features=prepared,
        enable_optional=options.get("enable_optional"),
        disable=options.get("disable"),
        param_overrides=options.get("param_overrides"),
    )
    accepted = not result.output.rejected
    return filtered, accepted


def audit_strategy(
    strategy: BaseStrategy,
    features: pd.DataFrame,
    *,
    symbol: str | None = None,
    min_bars: int = 60,
    stride: int = 5,
    max_evaluations: int | None = 40,
    apply_filters: bool = True,
) -> StrategyAuditMetrics:
    """Audit one strategy over rolling feature windows."""
    if features.empty:
        raise StrategyValidationError("Feature DataFrame must not be empty")

    resolved = (
        symbol.strip().upper()
        if symbol
        else resolve_symbol_from_features(features) or strategy.active_symbol
    )
    frame = attach_symbol(features, resolved) if resolved else features

    filter_ok, filter_detail = verify_filter_integration(strategy, features=frame.tail(1))
    plans: list[TradePlan] = []
    accepted = 0
    rejected = 0
    errors: list[str] = []
    if not filter_ok:
        errors.append(f"filter_integration: {filter_detail}")

    end = len(frame)
    start = min(max(min_bars, 3), end)
    indices = list(range(start, end + 1, max(stride, 1)))
    if not indices and end >= 3:
        indices = [end]
    if max_evaluations is not None:
        indices = indices[-max_evaluations:]

    for cut in indices:
        window = frame.iloc[:cut]
        try:
            plan, filt = _run_lifecycle(strategy, window, apply_filters=apply_filters)
            plans.append(plan)
            if filt is True:
                accepted += 1
            elif filt is False:
                rejected += 1
        except Exception as exc:  # noqa: BLE001 — continue audit across windows
            errors.append(f"bar={cut}: {exc}")
            if len(errors) > 25:
                errors.append("… truncated additional errors")
                break

    # If rolling scan failed entirely, try a single full-frame evaluation
    if not plans and end >= 3:
        try:
            plan, filt = _run_lifecycle(strategy, frame, apply_filters=apply_filters)
            plans.append(plan)
            if filt is True:
                accepted += 1
            elif filt is False:
                rejected += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"full_frame: {exc}")
            # Context-bound strategies (momentum, RS, levels, …)
            try:
                plan, filt = _run_via_context(
                    strategy,
                    frame,
                    symbol=resolved or "UNKNOWN",
                    apply_filters=apply_filters,
                )
                plans.append(plan)
                if filt is True:
                    accepted += 1
                elif filt is False:
                    rejected += 1
                # Recovered via context — drop the prior full_frame error noise
                errors = [e for e in errors if not e.startswith("full_frame:")]
            except Exception as ctx_exc:  # noqa: BLE001
                errors.append(f"context: {ctx_exc}")

    return aggregate_metrics(
        strategy_name=strategy.name,
        symbol=resolved or "UNKNOWN",
        plans=plans,
        filter_accepted=accepted,
        filter_rejected=rejected,
        filter_integration_ok=filter_ok,
        runtime_errors=errors,
    )


def audit_from_plans(
    *,
    strategy_name: str,
    symbol: str,
    plans: list[TradePlan],
    filter_accepted: int = 0,
    filter_rejected: int = 0,
    filter_integration_ok: bool = True,
    runtime_errors: list[str] | None = None,
) -> StrategyAuditMetrics:
    """Build metrics from pre-collected plans (unit-test friendly)."""
    return aggregate_metrics(
        strategy_name=strategy_name,
        symbol=symbol,
        plans=plans,
        filter_accepted=filter_accepted,
        filter_rejected=filter_rejected,
        filter_integration_ok=filter_integration_ok,
        runtime_errors=runtime_errors,
    )


class StrategyAuditor:
    """Audit one or many strategies and produce the full A4X.8 report."""

    def __init__(
        self,
        *,
        min_bars: int = 60,
        stride: int = 5,
        max_evaluations: int | None = 40,
        apply_filters: bool = True,
        enable_filter_pipeline_config: bool = True,
    ) -> None:
        self.min_bars = min_bars
        self.stride = stride
        self.max_evaluations = max_evaluations
        self.apply_filters = apply_filters
        self.enable_filter_pipeline_config = enable_filter_pipeline_config

    def materialize(
        self,
        strategy_name: str,
        *,
        symbol: str = "RELIANCE",
        config_overrides: dict[str, Any] | None = None,
    ) -> BaseStrategy:
        base = default_system_config(strategy_name).to_public_dict()
        parameters = dict(base.get("parameters") or {})
        parameters["symbol"] = symbol
        filters = dict(base.get("filters") or {})
        filters["enable_pipeline"] = self.enable_filter_pipeline_config
        payload: dict[str, Any] = {
            **base,
            "parameters": parameters,
            "filters": filters,
        }
        if config_overrides:
            for key, value in config_overrides.items():
                if key in {"parameters", "filters", "thresholds", "risk", "position"} and isinstance(
                    value,
                    dict,
                ):
                    merged = dict(payload.get(key) or {})
                    merged.update(value)
                    payload[key] = merged
                else:
                    payload[key] = value
        from app.strategy_engine.configuration import load_strategy_config_dict

        return materialize_strategy(load_strategy_config_dict(payload))

    def audit_one(
        self,
        strategy: BaseStrategy,
        features: pd.DataFrame,
        *,
        symbol: str | None = None,
    ) -> StrategyAuditMetrics:
        return audit_strategy(
            strategy,
            features,
            symbol=symbol,
            min_bars=self.min_bars,
            stride=self.stride,
            max_evaluations=self.max_evaluations,
            apply_filters=self.apply_filters,
        )

    def audit_all(
        self,
        features: pd.DataFrame,
        *,
        symbol: str | None = None,
        strategy_names: list[str] | None = None,
    ) -> list[StrategyAuditMetrics]:
        names = strategy_names or list_bound_strategies()
        resolved = (
            symbol.strip().upper()
            if symbol
            else resolve_symbol_from_features(features) or "UNKNOWN"
        )
        results: list[StrategyAuditMetrics] = []
        for name in names:
            try:
                strategy = self.materialize(name, symbol=resolved)
                results.append(self.audit_one(strategy, features, symbol=resolved))
            except Exception as exc:  # noqa: BLE001 — keep auditing siblings
                results.append(
                    aggregate_metrics(
                        strategy_name=name,
                        symbol=resolved,
                        plans=[],
                        filter_integration_ok=False,
                        runtime_errors=[str(exc)],
                    ),
                )
        return results

    def build_report(
        self,
        metrics: list[StrategyAuditMetrics] | tuple[StrategyAuditMetrics, ...],
        *,
        symbol: str,
        tests_passed: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyAuditReport:
        scorecard = build_scorecard(metrics, symbol=symbol)
        comparison = build_comparison(scorecard)
        readiness = build_readiness_report(
            symbol=symbol,
            metrics=metrics,
            scorecard=scorecard,
            comparison=comparison,
            tests_passed=tests_passed,
        )
        return StrategyAuditReport(
            generated_at=datetime.now(timezone.utc),
            symbol=symbol.strip().upper(),
            metrics=tuple(metrics),
            scorecard=scorecard,
            comparison=comparison,
            readiness=readiness,
            metadata=dict(metadata or {}),
        )

    def run(
        self,
        features: pd.DataFrame,
        *,
        symbol: str | None = None,
        strategy_names: list[str] | None = None,
        tests_passed: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyAuditReport:
        resolved = (
            symbol.strip().upper()
            if symbol
            else resolve_symbol_from_features(features) or "UNKNOWN"
        )
        metrics = self.audit_all(
            features,
            symbol=resolved,
            strategy_names=strategy_names,
        )
        return self.build_report(
            metrics,
            symbol=resolved,
            tests_passed=tests_passed,
            metadata=metadata,
        )
