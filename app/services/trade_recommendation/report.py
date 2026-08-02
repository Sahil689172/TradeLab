"""Human-readable Trade Recommendation reports."""

from __future__ import annotations

from app.services.trade_recommendation.schemas import (
    AggregatedRecommendation,
    RecommendationConfig,
    RecommendationReport,
    TradeRecommendation,
)
from app.strategy_engine.models import SignalType


def format_price(value: float, *, currency: str = "₹") -> str:
    """Format a price for display (INR-style by default)."""
    if value >= 100:
        return f"{currency}{value:,.2f}"
    return f"{currency}{value:.4g}"


def format_risk_reward(value: float) -> str:
    return f"1 : {value:.2g}"


def build_recommendation_report(
    recommendation: TradeRecommendation,
    *,
    config: RecommendationConfig | None = None,
    overall: str | None = None,
) -> RecommendationReport:
    """Build a structured + plaintext recommendation report."""
    cfg = config or RecommendationConfig()
    currency = cfg.currency_symbol
    holding = recommendation.holding_note or (
        f"{recommendation.expected_holding_period} bars/days"
    )
    warnings = recommendation.warnings or ["None"]
    overall_text = overall or _overall_from_signal(recommendation)

    lines = [
        "=" * 52,
        "Trade Recommendation",
        "=" * 52,
        "",
        f"Strategy          {recommendation.strategy_name}",
        f"Symbol            {recommendation.symbol}",
        f"Timeframe         {recommendation.timeframe}",
        f"Trade ID          {recommendation.trade_id}",
        f"Signal            {recommendation.signal.value}",
        f"Entry Price       {format_price(recommendation.entry_price, currency=currency)}",
        f"Stop Loss         {format_price(recommendation.stop_loss, currency=currency)}",
        f"Target 1          {format_price(recommendation.target_1, currency=currency)}",
        f"Target 2          {format_price(recommendation.target_2, currency=currency)}",
        f"Risk Reward       {format_risk_reward(recommendation.risk_reward)}",
        f"Confidence        {recommendation.confidence:.0f}",
        f"Holding           {holding}",
        f"Trend             {recommendation.trend_direction.value.title()}",
        f"Market Structure  {recommendation.market_structure.value.title()}",
        "",
        "Reasons",
    ]
    for reason in recommendation.reasons:
        lines.append(f"  • {reason}")
    lines.append("")
    lines.append("Warnings")
    for warning in warnings:
        lines.append(f"  • {warning}")
    if recommendation.indicators_used:
        lines.append("")
        lines.append("Indicators Used")
        for indicator in recommendation.indicators_used:
            lines.append(f"  • {indicator}")
    lines.extend(
        [
            "",
            f"Overall Recommendation  {overall_text}",
            "=" * 52,
        ],
    )
    body = "\n".join(lines)
    return RecommendationReport(
        strategy_used=recommendation.strategy_name,
        signal=recommendation.signal.value,
        entry=format_price(recommendation.entry_price, currency=currency),
        stop_loss=format_price(recommendation.stop_loss, currency=currency),
        target_1=format_price(recommendation.target_1, currency=currency),
        target_2=format_price(recommendation.target_2, currency=currency),
        risk_reward=format_risk_reward(recommendation.risk_reward),
        holding_period=holding,
        confidence=f"{recommendation.confidence:.0f}",
        trend=recommendation.trend_direction.value.title(),
        reasons=list(recommendation.reasons),
        warnings=list(warnings),
        overall_recommendation=overall_text,
        body=body,
    )


def build_aggregate_report(
    aggregate: AggregatedRecommendation,
    *,
    config: RecommendationConfig | None = None,
) -> RecommendationReport:
    """Report for a multi-strategy consensus result."""
    if aggregate.recommendation is not None:
        return build_recommendation_report(
            aggregate.recommendation,
            config=config,
            overall=f"{aggregate.consensus.value} — {aggregate.explanation}",
        )

    cfg = config or RecommendationConfig()
    lines = [
        "=" * 52,
        "Trade Recommendation (Consensus)",
        "=" * 52,
        "",
        f"Symbol            {aggregate.symbol}",
        f"Timeframe         {aggregate.timeframe}",
        f"Consensus         {aggregate.consensus.value}",
        f"Confidence        {aggregate.confidence:.0f}",
        f"BUY / SELL / HOLD {aggregate.buy_count} / {aggregate.sell_count} / {aggregate.hold_count}",
        "",
        "Explanation",
        f"  {aggregate.explanation}",
        "",
        "Contributing Strategies",
    ]
    for item in aggregate.contributing:
        lines.append(
            f"  • {item.strategy_name}: {item.signal.value} "
            f"(conf {item.confidence:.0f})",
        )
    if aggregate.warnings:
        lines.append("")
        lines.append("Warnings")
        for warning in aggregate.warnings:
            lines.append(f"  • {warning}")
    lines.append("=" * 52)
    body = "\n".join(lines)
    return RecommendationReport(
        strategy_used="consensus",
        signal=aggregate.consensus.value,
        entry="—",
        stop_loss="—",
        target_1="—",
        target_2="—",
        risk_reward="—",
        holding_period="—",
        confidence=f"{aggregate.confidence:.0f}",
        trend="—",
        reasons=[aggregate.explanation],
        warnings=list(aggregate.warnings) or ["None"],
        overall_recommendation=aggregate.consensus.value,
        body=body,
    )


def format_validation_report_table(rows: list[dict[str, object]]) -> str:
    """Simple fixed-width validation table."""
    headers = [
        "Strategy",
        "Status",
        "Signals",
        "BUY",
        "SELL",
        "HOLD",
        "Avg Conf",
        "Avg Hold",
        "Errors",
    ]
    lines = [" | ".join(headers), "-+-".join("-" * len(h) for h in headers)]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    str(row.get("strategy", "")),
                    str(row.get("status", "")),
                    str(row.get("signals_generated", 0)),
                    str(row.get("buy_count", 0)),
                    str(row.get("sell_count", 0)),
                    str(row.get("hold_count", 0)),
                    f"{float(row.get('average_confidence', 0)):.1f}",
                    f"{float(row.get('average_holding', 0)):.1f}",
                    str(len(row.get("validation_errors", []) or [])),
                ],
            ),
        )
    return "\n".join(lines)


def _overall_from_signal(recommendation: TradeRecommendation) -> str:
    if recommendation.signal is SignalType.BUY:
        if recommendation.confidence >= 90:
            return "STRONG BUY"
        return "BUY"
    if recommendation.signal is SignalType.SELL:
        if recommendation.confidence >= 90:
            return "STRONG SELL"
        return "SELL"
    if recommendation.signal is SignalType.EXIT:
        return "EXIT"
    return "HOLD"
