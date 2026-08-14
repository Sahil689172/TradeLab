"""Signal funnel and filter-effectiveness aggregation."""

from __future__ import annotations

from app.backtesting.evaluation.funnel_semantics import (
    FUNNEL_MODE_SEQUENTIAL,
    METRIC_GLOSSARY,
    SequentialBuyFunnel,
    buy_candidate_reduction_pct,
    build_signal_funnel,
    format_semantic_funnel,
    sequential_buy_funnel,
)
from app.backtesting.evaluation.schemas import (
    FilterEffectivenessRow,
    PerformanceMetrics,
    SignalFunnelMetrics,
)


def build_filter_effectiveness(
    funnel: SignalFunnelMetrics,
    *,
    raw_perf: PerformanceMetrics,
    pro_perf: PerformanceMetrics,
) -> list[FilterEffectivenessRow]:
    examined = funnel.professional_buy_candidates or funnel.raw_buy
    accepted = funnel.professional_buy_signals or funnel.professional_buy
    improvement = 0.0
    if abs(raw_perf.net_profit) > 1e-9:
        improvement = (
            (pro_perf.net_profit - raw_perf.net_profit) / abs(raw_perf.net_profit) * 100.0
        )
    elif pro_perf.net_profit > 0:
        improvement = 100.0

    rows = []
    for name, rejected in (
        ("EMA200", funnel.rejected_ema200),
        ("ADX", funnel.rejected_adx),
        ("Volume", funnel.rejected_volume),
        ("ATR", funnel.rejected_atr),
        ("Other", funnel.rejected_other),
    ):
        rows.append(
            FilterEffectivenessRow(
                filter_name=name,
                signals_examined=examined,
                signals_rejected=rejected,
                signals_accepted=max(examined - rejected, 0),
                average_profit_after_filter=pro_perf.average_profit,
                average_loss_after_filter=pro_perf.average_loss,
                improvement_pct=improvement if rejected else 0.0,
            ),
        )
    rows.append(
        FilterEffectivenessRow(
            filter_name="ALL_FILTERS",
            signals_examined=examined,
            signals_rejected=examined - accepted if examined >= accepted else 0,
            signals_accepted=accepted,
            average_profit_after_filter=pro_perf.average_profit,
            average_loss_after_filter=pro_perf.average_loss,
            improvement_pct=improvement,
        ),
    )
    return rows


__all__ = [
    "FUNNEL_MODE_SEQUENTIAL",
    "METRIC_GLOSSARY",
    "SequentialBuyFunnel",
    "buy_candidate_reduction_pct",
    "build_filter_effectiveness",
    "build_signal_funnel",
    "format_semantic_funnel",
    "sequential_buy_funnel",
]
