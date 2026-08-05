"""Metric helpers for strategy audit aggregates."""

from __future__ import annotations

from statistics import mean

from app.strategy_engine.audit.schemas import StrategyAuditMetrics
from app.strategy_engine.models import SignalType, TradePlan


def win_expectancy(confidence: float, risk_reward: float) -> float:
    """Expected R-multiple if confidence approximates win probability.

    ``E = confidence * RR - (1 - confidence) * 1``
    """
    conf = max(0.0, min(1.0, float(confidence)))
    rr = max(0.0, float(risk_reward))
    return conf * rr - (1.0 - conf)


def aggregate_metrics(
    *,
    strategy_name: str,
    symbol: str,
    plans: list[TradePlan],
    filter_accepted: int = 0,
    filter_rejected: int = 0,
    filter_integration_ok: bool = False,
    runtime_errors: list[str] | None = None,
) -> StrategyAuditMetrics:
    """Aggregate TradePlan samples into StrategyAuditMetrics."""
    errors = tuple(runtime_errors or ())
    buy = sell = hold = exit_ = 0
    holds: list[float] = []
    confidences: list[float] = []
    rrs: list[float] = []
    expectancies: list[float] = []

    for plan in plans:
        if plan.signal is SignalType.BUY:
            buy += 1
        elif plan.signal is SignalType.SELL:
            sell += 1
        elif plan.signal is SignalType.EXIT:
            exit_ += 1
        else:
            hold += 1

        holds.append(float(plan.holding_period))
        confidences.append(float(plan.confidence))
        rrs.append(float(plan.risk_reward))
        if plan.signal in {SignalType.BUY, SignalType.SELL}:
            expectancies.append(win_expectancy(plan.confidence, plan.risk_reward))

    filter_evals = int(filter_accepted) + int(filter_rejected)
    accept_rate = (filter_accepted / filter_evals) if filter_evals else 0.0
    reject_rate = (filter_rejected / filter_evals) if filter_evals else 0.0

    # Ready when filter integration passes and at least one evaluation succeeded.
    # Runtime window errors are recorded but do not block readiness if we recovered.
    ready = filter_integration_ok and bool(plans)

    return StrategyAuditMetrics(
        strategy_name=strategy_name,
        symbol=symbol.strip().upper(),
        evaluations=len(plans),
        buy_signals=buy,
        sell_signals=sell,
        hold_signals=hold,
        exit_signals=exit_,
        average_hold=mean(holds) if holds else 0.0,
        average_confidence=mean(confidences) if confidences else 0.0,
        average_risk_reward=mean(rrs) if rrs else 0.0,
        average_win_expectancy=mean(expectancies) if expectancies else 0.0,
        filter_evaluations=filter_evals,
        filter_accepted=filter_accepted,
        filter_rejected=filter_rejected,
        filter_acceptance_rate=accept_rate,
        filter_rejection_rate=reject_rate,
        filter_integration_ok=filter_integration_ok,
        runtime_errors=errors,
        ready=ready,
    )
