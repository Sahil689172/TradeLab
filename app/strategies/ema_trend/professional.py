"""Professional EMA evaluation gates (modular, reusable filters)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from app.strategies.ema_trend.config import EMATrendConfig
from app.strategies.ema_trend.diagnostics import (
    FilterRejection,
    RejectionFilter,
    SignalFunnel,
)
from app.strategy_engine.models import SignalType


@dataclass
class ProfessionalEvalResult:
    """Outcome of professional gate evaluation after a raw crossover."""

    raw_signal: SignalType
    final_signal: SignalType
    rejections: list[FilterRejection] = field(default_factory=list)
    funnel: SignalFunnel = field(default_factory=SignalFunnel)
    notes: list[str] = field(default_factory=list)


def atr_stop_price(
    *,
    entry: float,
    atr: float,
    multiplier: float,
    side: SignalType,
) -> float:
    """Institutional ATR stop: entry ± multiplier × ATR."""
    distance = float(atr) * float(multiplier)
    if side is SignalType.SELL:
        return float(entry) + distance
    return float(entry) - distance


def atr_trailing_stop_price(
    *,
    extreme: float,
    atr: float,
    multiplier: float,
    side: SignalType,
) -> float:
    """Trailing stop from favorable extreme ± multiplier × ATR."""
    distance = float(atr) * float(multiplier)
    if side is SignalType.SELL:
        return float(extreme) + distance
    return float(extreme) - distance


def apply_professional_gates(
    *,
    config: EMATrendConfig,
    symbol: str,
    timestamp: datetime,
    raw_signal: SignalType,
    close: float,
    ema200: float | None,
    adx: float,
    relative_volume: float | None,
    volume: float | None,
    volume_sma: float | None,
    atr: float,
    bar_closed: bool,
    last_emitted: SignalType | None,
) -> ProfessionalEvalResult:
    """Gate a raw BUY/SELL crossover through professional filters.

    Filters are modular and ordered: confirm_on_close → duplicate → EMA200 →
    ADX → Volume → ATR validity. First failure rejects (HOLD) and is recorded.
    """
    if raw_signal not in {SignalType.BUY, SignalType.SELL}:
        return ProfessionalEvalResult(
            raw_signal=raw_signal,
            final_signal=raw_signal,
            funnel=SignalFunnel(),
        )

    funnel_kwargs: dict[str, int] = {
        "raw_buy": 1 if raw_signal is SignalType.BUY else 0,
        "raw_sell": 1 if raw_signal is SignalType.SELL else 0,
    }
    rejections: list[FilterRejection] = []
    notes: list[str] = []

    def reject(filt: RejectionFilter, reason: str) -> ProfessionalEvalResult:
        rejections.append(
            FilterRejection(
                timestamp=timestamp,
                symbol=symbol,
                raw_signal=raw_signal.value,
                reason=reason,
                rejected_by=filt,
            ),
        )
        key = {
            RejectionFilter.EMA200: "rejected_ema200",
            RejectionFilter.ADX: "rejected_adx",
            RejectionFilter.VOLUME: "rejected_volume",
            RejectionFilter.ATR: "rejected_atr",
        }.get(filt, "rejected_other")
        funnel_kwargs[key] = funnel_kwargs.get(key, 0) + 1
        notes.append(f"Rejected by {filt.value}: {reason}")
        return ProfessionalEvalResult(
            raw_signal=raw_signal,
            final_signal=SignalType.HOLD,
            rejections=rejections,
            funnel=SignalFunnel(**funnel_kwargs),
            notes=notes,
        )

    if config.confirm_on_close and not bar_closed:
        return reject(
            RejectionFilter.CONFIRM_ON_CLOSE,
            "Signal requires candle close confirmation",
        )

    # Avoid duplicate BUY/SELL while the same side remains active (no new cross).
    if last_emitted is not None and last_emitted is raw_signal:
        return reject(
            RejectionFilter.DUPLICATE,
            f"Duplicate {raw_signal.value} suppressed while trend unchanged",
        )

    if config.ema200_filter or config.trend_filter:
        if ema200 is None:
            return reject(RejectionFilter.EMA200, "EMA200 unavailable")
        if raw_signal is SignalType.BUY and close <= ema200:
            return reject(
                RejectionFilter.EMA200,
                f"BUY blocked: close {close:.4f} <= EMA200 {ema200:.4f}",
            )
        if raw_signal is SignalType.SELL and close >= ema200:
            return reject(
                RejectionFilter.EMA200,
                f"SELL blocked: close {close:.4f} >= EMA200 {ema200:.4f}",
            )
        notes.append(f"EMA200 filter passed (close={close:.4f}, ema200={ema200:.4f})")

    if config.adx_filter:
        if adx <= config.adx_threshold:
            return reject(
                RejectionFilter.ADX,
                f"ADX {adx:.2f} <= threshold {config.adx_threshold:g}",
            )
        notes.append(f"ADX filter passed ({adx:.2f} > {config.adx_threshold:g})")

    if config.volume_filter:
        volume_ok = False
        detail = ""
        if relative_volume is not None and relative_volume > config.relative_volume:
            volume_ok = True
            detail = (
                f"relative_volume {relative_volume:.3f} > {config.relative_volume:g}"
            )
        elif (
            volume is not None
            and volume_sma is not None
            and volume_sma > 0
            and volume > volume_sma
        ):
            volume_ok = True
            detail = f"volume {volume:.0f} > volume_sma {volume_sma:.0f}"
        if not volume_ok:
            return reject(
                RejectionFilter.VOLUME,
                (
                    f"Volume confirmation failed "
                    f"(rvol={relative_volume}, vol={volume}, sma={volume_sma}; "
                    f"need rvol>{config.relative_volume:g} or vol>sma)"
                ),
            )
        notes.append(f"Volume filter passed ({detail})")

    if config.atr_stop:
        if atr <= 0:
            return reject(RejectionFilter.ATR, f"Invalid ATR for stop: {atr}")
        notes.append(
            f"ATR stop enabled (multiplier={config.atr_stop_multiplier:g}, atr={atr:.4f})",
        )

    funnel_kwargs["final_buy"] = 1 if raw_signal is SignalType.BUY else 0
    funnel_kwargs["final_sell"] = 1 if raw_signal is SignalType.SELL else 0
    return ProfessionalEvalResult(
        raw_signal=raw_signal,
        final_signal=raw_signal,
        rejections=rejections,
        funnel=SignalFunnel(**funnel_kwargs),
        notes=notes,
    )


def read_optional_float(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    value = frame.iloc[-1][column]
    if value is None or (isinstance(value, float) and value != value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
