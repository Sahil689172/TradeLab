"""A4Y.1.7.3 — Unambiguous funnel / metric semantics.

Does not change strategy behaviour. Translates existing counters into
explicit layers:

    A. Technical events (EMA crossovers)
    B. Raw strategy signals (EMA20/50 strategy output)
    C. Professional BUY candidates (EMA9/21 crosses entering gates)
    D. Final professional signals (survived sequential filters)
    E. Completed trades (BUY paired with SELL/EXIT fills)

Professional ``SignalFunnel.raw_buy`` is **not** a raw-strategy BUY. It is a
professional-mode crossover candidate counted in ``apply_professional_gates``.
Filters are **sequential first-fail** (EMA200 → ADX → Volume → ATR → Other).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.backtesting.evaluation.backtester import BacktestResult
from app.backtesting.evaluation.integrity import RawSignalDiagnostic
from app.backtesting.evaluation.schemas import SignalFunnelMetrics

FUNNEL_MODE_SEQUENTIAL = "sequential"

METRIC_GLOSSARY: dict[str, str] = {
    "technical_cross_above": (
        "True EMA fast/slow cross-above events on the raw diagnostic walk "
        "(EMA20/EMA50 for raw mode). Not a trade."
    ),
    "technical_cross_below": (
        "True EMA fast/slow cross-below events on the raw diagnostic walk. Not a trade."
    ),
    "raw_buy_signals": (
        "BUY signals emitted by the existing raw EMA strategy "
        "(cross-above AND ADX AND close>slow). Not candidates."
    ),
    "raw_exit_signals": (
        "EXIT/SELL signals emitted by the raw EMA strategy (cross-below)."
    ),
    "professional_buy_candidates": (
        "Professional-mode true EMA9/21 BUY crossovers that entered "
        "apply_professional_gates. Stored internally as SignalFunnel.raw_buy. "
        "Not raw-strategy BUY signals."
    ),
    "ema200_rejections": "Sequential first-fail: BUY candidates rejected by EMA200/trend.",
    "adx_rejections": "Sequential first-fail: remaining BUY candidates rejected by ADX.",
    "volume_rejections": "Sequential first-fail: remaining BUY candidates rejected by volume.",
    "atr_rejections": "Sequential first-fail: remaining BUY candidates rejected by ATR validity.",
    "other_rejections": (
        "Sequential first-fail: remaining BUY candidates rejected by ConfirmOnClose, "
        "Duplicate, or Other."
    ),
    "professional_buy_signals": "BUY signals that passed every professional entry gate.",
    "professional_exit_signals": (
        "SELL/EXIT signals from professional mode (entry filters bypassed)."
    ),
    "raw_completed_trades": "Long-only BUY→EXIT pairs filled by the evaluation backtester.",
    "professional_completed_trades": "Long-only BUY→SELL pairs filled by the evaluation backtester.",
    "professional_buy_candidate_reduction_pct": (
        "(professional_buy_candidates - professional_buy_signals) "
        "/ professional_buy_candidates * 100"
    ),
}


@dataclass(frozen=True)
class SequentialBuyFunnel:
    """First-fail BUY funnel matching ``apply_professional_gates`` order."""

    candidates: int = 0
    ema200_rejections: int = 0
    remaining_after_ema200: int = 0
    adx_rejections: int = 0
    remaining_after_adx: int = 0
    volume_rejections: int = 0
    remaining_after_volume: int = 0
    atr_rejections: int = 0
    remaining_after_atr: int = 0
    other_rejections: int = 0
    final_buy_signals: int = 0
    reconciles: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "funnel_mode": FUNNEL_MODE_SEQUENTIAL,
            "professional_buy_candidates": self.candidates,
            "ema200_rejections": self.ema200_rejections,
            "remaining_after_ema200": self.remaining_after_ema200,
            "adx_rejections": self.adx_rejections,
            "remaining_after_adx": self.remaining_after_adx,
            "volume_rejections": self.volume_rejections,
            "remaining_after_volume": self.remaining_after_volume,
            "atr_rejections": self.atr_rejections,
            "remaining_after_atr": self.remaining_after_atr,
            "other_rejections": self.other_rejections,
            "professional_buy_signals": self.final_buy_signals,
            "reconciles": self.reconciles,
            "identity": (
                "candidates = ema200 + adx + volume + atr + other + final_buy"
            ),
        }


def sequential_buy_funnel(
    *,
    candidates: int,
    rejected_ema200: int,
    rejected_adx: int,
    rejected_volume: int,
    rejected_atr: int,
    rejected_other: int,
    final_buy: int,
) -> SequentialBuyFunnel:
    remaining_ema = max(candidates - rejected_ema200, 0)
    remaining_adx = max(remaining_ema - rejected_adx, 0)
    remaining_vol = max(remaining_adx - rejected_volume, 0)
    remaining_atr = max(remaining_vol - rejected_atr, 0)
    remaining_other = max(remaining_atr - rejected_other, 0)
    total_rejected = (
        rejected_ema200
        + rejected_adx
        + rejected_volume
        + rejected_atr
        + rejected_other
    )
    reconciles = (
        total_rejected + final_buy == candidates
        and remaining_other == final_buy
    )
    return SequentialBuyFunnel(
        candidates=candidates,
        ema200_rejections=rejected_ema200,
        remaining_after_ema200=remaining_ema,
        adx_rejections=rejected_adx,
        remaining_after_adx=remaining_adx,
        volume_rejections=rejected_volume,
        remaining_after_volume=remaining_vol,
        atr_rejections=rejected_atr,
        remaining_after_atr=remaining_atr,
        other_rejections=rejected_other,
        final_buy_signals=final_buy,
        reconciles=reconciles,
    )


def buy_candidate_reduction_pct(candidates: int, final_buy: int) -> float:
    """(candidates - final_buy) / candidates * 100. Zero when no candidates."""
    if candidates <= 0:
        return 0.0
    return (candidates - final_buy) / candidates * 100.0


def build_signal_funnel(
    *,
    raw: BacktestResult,
    professional: BacktestResult,
    diagnostic: RawSignalDiagnostic | None = None,
    raw_trade_count: int | None = None,
    professional_trade_count: int | None = None,
) -> SignalFunnelMetrics:
    """Build evaluation funnel metrics with explicit layer names.

    Backward-compatible fields:
        raw_buy / raw_sell     → professional BUY/SELL *candidates* (legacy name)
        professional_buy/sell  → final professional signals
        signal_reduction_pct   → BUY candidate reduction (not mixed with raw trades)
    """
    raw_strategy_buy = int(raw.signal_counts.get("BUY", 0))
    raw_strategy_exit = int(
        raw.signal_counts.get("SELL", 0) + raw.signal_counts.get("EXIT", 0)
    )
    pro_counts = professional.signal_counts or {}
    pro_buy_signals = int(pro_counts.get("BUY", 0))
    pro_exit_signals = int(pro_counts.get("SELL", 0) + pro_counts.get("EXIT", 0))

    funnel = professional.funnel or {}
    candidates_buy = int(funnel.get("raw_buy", 0))
    candidates_sell = int(funnel.get("raw_sell", 0))
    final_buy = int(funnel.get("final_buy", pro_buy_signals))
    final_sell = int(funnel.get("final_sell", pro_exit_signals))
    rej_ema = int(funnel.get("rejected_ema200", 0))
    rej_adx = int(funnel.get("rejected_adx", 0))
    rej_vol = int(funnel.get("rejected_volume", 0))
    rej_atr = int(funnel.get("rejected_atr", 0))
    rej_other = int(funnel.get("rejected_other", 0))

    if candidates_buy == 0 and candidates_sell == 0:
        candidates_buy = pro_buy_signals
        candidates_sell = pro_exit_signals
        final_buy = pro_buy_signals
        final_sell = pro_exit_signals

    buy_funnel = sequential_buy_funnel(
        candidates=candidates_buy,
        rejected_ema200=rej_ema,
        rejected_adx=rej_adx,
        rejected_volume=rej_vol,
        rejected_atr=rej_atr,
        rejected_other=rej_other,
        final_buy=final_buy,
    )
    reduction = buy_candidate_reduction_pct(candidates_buy, final_buy)
    acceptance = (final_buy / candidates_buy) if candidates_buy else 0.0
    rejection = (buy_funnel.ema200_rejections
                 + buy_funnel.adx_rejections
                 + buy_funnel.volume_rejections
                 + buy_funnel.atr_rejections
                 + buy_funnel.other_rejections) / candidates_buy if candidates_buy else 0.0

    technical_above = diagnostic.cross_above_count if diagnostic is not None else 0
    technical_below = diagnostic.cross_below_count if diagnostic is not None else 0

    return SignalFunnelMetrics(
        # Legacy aliases (documented): raw_buy == professional BUY candidates
        raw_buy=candidates_buy,
        raw_sell=candidates_sell,
        professional_buy=final_buy,
        professional_sell=final_sell,
        rejected_ema200=rej_ema,
        rejected_adx=rej_adx,
        rejected_volume=rej_vol,
        rejected_atr=rej_atr,
        rejected_other=rej_other,
        acceptance_rate=acceptance,
        rejection_rate=rejection,
        signal_reduction_pct=reduction,
        funnel_mode=FUNNEL_MODE_SEQUENTIAL,
        technical_cross_above=technical_above,
        technical_cross_below=technical_below,
        raw_strategy_buy_signals=raw_strategy_buy,
        raw_strategy_exit_signals=raw_strategy_exit,
        professional_buy_candidates=candidates_buy,
        professional_sell_candidates=candidates_sell,
        ema200_rejections=rej_ema,
        adx_rejections=rej_adx,
        volume_rejections=rej_vol,
        atr_rejections=rej_atr,
        other_rejections=rej_other,
        remaining_after_ema200=buy_funnel.remaining_after_ema200,
        remaining_after_adx=buy_funnel.remaining_after_adx,
        remaining_after_volume=buy_funnel.remaining_after_volume,
        remaining_after_atr=buy_funnel.remaining_after_atr,
        professional_buy_signals=final_buy,
        professional_exit_signals=final_sell,
        raw_completed_trades=(
            int(raw_trade_count) if raw_trade_count is not None else len(raw.trades)
        ),
        professional_completed_trades=(
            int(professional_trade_count)
            if professional_trade_count is not None
            else len(professional.trades)
        ),
        professional_buy_candidate_reduction_pct=reduction,
        sequential_funnel_reconciles=buy_funnel.reconciles,
    )


def format_semantic_funnel(metrics: SignalFunnelMetrics) -> str:
    lines = [
        "Metric layers (A4Y.1.7.3)",
        f"  funnel_mode: {metrics.funnel_mode}",
        "  A. Technical crossovers (raw EMA20/50 diagnostic)",
        f"     cross_above={metrics.technical_cross_above}  "
        f"cross_below={metrics.technical_cross_below}",
        "  B. Raw strategy signals (EMA20/50 strategy)",
        f"     BUY={metrics.raw_strategy_buy_signals}  "
        f"EXIT={metrics.raw_strategy_exit_signals}",
        "  C. Professional BUY funnel (sequential first-fail, EMA9/21 candidates)",
        f"     professional_buy_candidates: {metrics.professional_buy_candidates}",
        f"     - EMA200 rejected: {metrics.ema200_rejections}  "
        f"remaining {metrics.remaining_after_ema200}",
        f"     - ADX rejected:    {metrics.adx_rejections}  "
        f"remaining {metrics.remaining_after_adx}",
        f"     - Volume rejected: {metrics.volume_rejections}  "
        f"remaining {metrics.remaining_after_volume}",
        f"     - ATR rejected:    {metrics.atr_rejections}  "
        f"remaining {metrics.remaining_after_atr}",
        f"     - Other rejected:  {metrics.other_rejections}",
        f"     professional_buy_signals (final): {metrics.professional_buy_signals}",
        f"     sequential_reconciles: {metrics.sequential_funnel_reconciles}",
        "  D. Professional exits (filters bypassed)",
        f"     sell_candidates={metrics.professional_sell_candidates}  "
        f"final_exits={metrics.professional_exit_signals}",
        "  E. Completed trades (backtester fills)",
        f"     raw_completed_trades={metrics.raw_completed_trades}  "
        f"professional_completed_trades={metrics.professional_completed_trades}",
        "  Reduction",
        f"     professional_buy_candidate_reduction = "
        f"(candidates - final_buy) / candidates = "
        f"{metrics.professional_buy_candidate_reduction_pct:.1f}%",
    ]
    return "\n".join(lines)
