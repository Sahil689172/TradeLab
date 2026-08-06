"""Signal funnel and filter-effectiveness aggregation."""

from __future__ import annotations

from app.backtesting.evaluation.backtester import BacktestResult
from app.backtesting.evaluation.schemas import (
    FilterEffectivenessRow,
    PerformanceMetrics,
    SignalFunnelMetrics,
)


def build_signal_funnel(
    *,
    raw: BacktestResult,
    professional: BacktestResult,
) -> SignalFunnelMetrics:
    raw_buy = int(raw.signal_counts.get("BUY", 0))
    raw_sell = int(raw.signal_counts.get("SELL", 0) + raw.signal_counts.get("EXIT", 0))
    funnel = professional.funnel or {}
    pro_buy = int(funnel.get("final_buy", professional.signal_counts.get("BUY", 0)))
    pro_sell = int(funnel.get("final_sell", professional.signal_counts.get("SELL", 0)))
    # Prefer strategy funnel raw counts when present
    funnel_raw_buy = int(funnel.get("raw_buy", raw_buy))
    funnel_raw_sell = int(funnel.get("raw_sell", raw_sell))
    rej_ema = int(funnel.get("rejected_ema200", 0))
    rej_adx = int(funnel.get("rejected_adx", 0))
    rej_vol = int(funnel.get("rejected_volume", 0))
    rej_atr = int(funnel.get("rejected_atr", 0))
    rej_other = int(funnel.get("rejected_other", 0))
    raw_actionable = funnel_raw_buy + funnel_raw_sell
    # If professional funnel empty (no crosses), fall back to signal counts
    if raw_actionable == 0:
        raw_actionable = raw_buy + raw_sell
        funnel_raw_buy = raw_buy
        funnel_raw_sell = raw_sell
    final_actionable = pro_buy + pro_sell
    total_rej = rej_ema + rej_adx + rej_vol + rej_atr + rej_other
    acceptance = (final_actionable / raw_actionable) if raw_actionable else 0.0
    rejection = (total_rej / raw_actionable) if raw_actionable else 0.0
    reduction = (
        ((raw_buy + raw_sell) - (pro_buy + pro_sell)) / (raw_buy + raw_sell)
        if (raw_buy + raw_sell)
        else 0.0
    )
    return SignalFunnelMetrics(
        raw_buy=funnel_raw_buy,
        raw_sell=funnel_raw_sell,
        professional_buy=pro_buy,
        professional_sell=pro_sell,
        rejected_ema200=rej_ema,
        rejected_adx=rej_adx,
        rejected_volume=rej_vol,
        rejected_atr=rej_atr,
        rejected_other=rej_other,
        acceptance_rate=acceptance,
        rejection_rate=rejection,
        signal_reduction_pct=reduction * 100.0,
    )


def build_filter_effectiveness(
    funnel: SignalFunnelMetrics,
    *,
    raw_perf: PerformanceMetrics,
    pro_perf: PerformanceMetrics,
) -> list[FilterEffectivenessRow]:
    examined = funnel.raw_buy + funnel.raw_sell
    accepted = funnel.professional_buy + funnel.professional_sell
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
    # Aggregate row
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
