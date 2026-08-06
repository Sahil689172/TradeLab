"""Strategy scorecard generation."""

from __future__ import annotations

from app.strategy_engine.audit.schemas import (
    StrategyAuditMetrics,
    StrategyScorecard,
    StrategyScorecardRow,
)


def composite_score(metrics: StrategyAuditMetrics) -> float:
    """0–100 composite from confidence, RR, expectancy, and filter acceptance."""
    conf = float(metrics.average_confidence) * 35.0
    # Cap RR contribution around 3.0
    rr = min(float(metrics.average_risk_reward) / 3.0, 1.0) * 25.0
    # Expectancy typically in [-1, ~3]; map via tanh-ish clamp
    exp = float(metrics.average_win_expectancy)
    exp_norm = max(0.0, min(1.0, (exp + 1.0) / 4.0)) * 20.0
    filt = float(metrics.filter_acceptance_rate) * 15.0
    integ = 5.0 if metrics.filter_integration_ok else 0.0
    actionable = metrics.buy_signals + metrics.sell_signals
    activity = min(actionable / max(metrics.evaluations, 1), 1.0) * 0.0  # reserved
    total = conf + rr + exp_norm + filt + integ + activity
    return round(min(100.0, max(0.0, total)), 2)


def build_scorecard(
    metrics_list: list[StrategyAuditMetrics] | tuple[StrategyAuditMetrics, ...],
    *,
    symbol: str,
) -> StrategyScorecard:
    rows: list[StrategyScorecardRow] = []
    for metrics in metrics_list:
        notes_parts: list[str] = []
        if metrics.runtime_errors:
            notes_parts.append(f"errors={len(metrics.runtime_errors)}")
        if not metrics.filter_integration_ok:
            notes_parts.append("filter_integration_failed")
        if metrics.evaluations == 0:
            notes_parts.append("no_evaluations")
        if metrics.raw_buy_signals or metrics.raw_sell_signals:
            notes_parts.append(
                f"funnel raw={metrics.raw_buy_signals}/{metrics.raw_sell_signals} "
                f"final={metrics.final_buy_signals}/{metrics.final_sell_signals} "
                f"rej(ema200={metrics.rejected_ema200},adx={metrics.rejected_adx},"
                f"vol={metrics.rejected_volume},atr={metrics.rejected_atr},"
                f"other={metrics.rejected_other})",
            )
        rows.append(
            StrategyScorecardRow(
                strategy_name=metrics.strategy_name,
                symbol=metrics.symbol,
                buy_signals=metrics.buy_signals,
                sell_signals=metrics.sell_signals,
                hold_signals=metrics.hold_signals,
                average_hold=round(metrics.average_hold, 4),
                average_confidence=round(metrics.average_confidence, 4),
                average_risk_reward=round(metrics.average_risk_reward, 4),
                average_win_expectancy=round(metrics.average_win_expectancy, 4),
                filter_acceptance_rate=round(metrics.filter_acceptance_rate, 4),
                filter_rejection_rate=round(metrics.filter_rejection_rate, 4),
                filter_integration_ok=metrics.filter_integration_ok,
                composite_score=composite_score(metrics),
                ready=metrics.ready,
                notes="; ".join(notes_parts),
            ),
        )
    ready_count = sum(1 for row in rows if row.ready)
    return StrategyScorecard(
        symbol=symbol.strip().upper(),
        rows=tuple(rows),
        ready_count=ready_count,
        total_count=len(rows),
    )
