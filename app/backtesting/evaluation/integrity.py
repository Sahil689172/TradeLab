"""Evaluation integrity helpers (Phase A4Y.1.7).

Audit-only utilities: capital allocation, equity aggregation, raw-signal
diagnostics, and recommendation validity gates. Does not modify strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.models import SignalType
from app.strategy_engine.symbols import attach_symbol, resolve_symbol_from_features


class CapitalAllocationMode(str, Enum):
    """How multi-stock evaluations treat capital.

    ``equal_weight``
        Each symbol is backtested with ``initial_capital / N``. Equity curves
        are summed; missing dates use that sleeve's idle cash (allocated
        capital). This is an equal-weight independent-sleeve portfolio.

    ``per_symbol_full``
        Legacy: each symbol is backtested with the full ``initial_capital``.
        Portfolio metrics from a naive sum are **not** a shared book — only
        valid for single-symbol runs or per-symbol reporting.
    """

    EQUAL_WEIGHT = "equal_weight"
    PER_SYMBOL_FULL = "per_symbol_full"


class EvaluationResolution(str, Enum):
    FULL_BACKTEST = "FULL_BACKTEST"
    FAST_SAMPLED = "FAST_SAMPLED_EVALUATION"


def resolution_for_stride(stride: int) -> EvaluationResolution:
    return (
        EvaluationResolution.FULL_BACKTEST
        if int(stride) <= 1
        else EvaluationResolution.FAST_SAMPLED
    )


def periods_per_year_for_stride(stride: int, *, base: float = 252.0) -> float:
    """Annualisation factor when equity observations are every ``stride`` bars.

    If stride=10, each return spans ~10 sessions, so use ``252/10`` — not 252 —
    otherwise Sharpe is inflated by roughly ``sqrt(stride)``.
    """
    s = max(int(stride), 1)
    return float(base) / float(s)


def merge_equal_weight_equity(
    curves: list[pd.Series],
    initial: float,
) -> pd.Series | None:
    """Sum independent equal-weight sleeves into one portfolio equity curve.

    Each curve is assumed to have been simulated with capital ``initial / N``.
    Dates missing for a sleeve are filled with that sleeve's allocated cash
    (idle capital), **not** zero — zero-fill was the MaxDD > 100% root cause.
    """
    usable = [c for c in curves if c is not None and len(c) > 0]
    if not usable:
        return None
    n = len(usable)
    alloc = float(initial) / float(n)
    scaled: list[pd.Series] = []
    for curve in usable:
        start = float(curve.iloc[0])
        if start <= 0:
            continue
        # Rescale in case the curve was run at a different capital level.
        factor = alloc / start
        sleeve = (curve.astype(float) - start) * factor + alloc
        sleeve = sleeve[~sleeve.index.duplicated(keep="last")].sort_index()
        scaled.append(sleeve)
    if not scaled:
        return None
    union = scaled[0]
    for sleeve in scaled[1:]:
        union = union.add(sleeve, fill_value=alloc)
    # Idle sleeves for dates before any trading still count as cash.
    if len(union):
        # Guard: long-only cash+MV should not go negative; clip tiny float noise.
        union = union.clip(lower=0.0)
        union = union - float(union.iloc[0]) + float(initial)
    return union.sort_index()


def merge_per_symbol_full_equity(
    curves: list[pd.Series],
    initial: float,
) -> pd.Series | None:
    """Legacy merge: average relative PnL across full-capital symbol runs.

    Not a shared portfolio. Kept for explicit opt-in / single-symbol paths.
    """
    usable = [c for c in curves if c is not None and len(c) > 0]
    if not usable:
        return None
    n = len(usable)
    base: pd.Series | None = None
    for curve in usable:
        start = float(curve.iloc[0])
        if start <= 0:
            continue
        rel = (curve.astype(float) - start) * (initial / start) / n
        sleeve = rel + (initial / n)
        sleeve = sleeve[~sleeve.index.duplicated(keep="last")].sort_index()
        base = sleeve if base is None else base.add(sleeve, fill_value=initial / n)
    if base is None or not len(base):
        return None
    base = base.clip(lower=0.0)
    return (base - float(base.iloc[0]) + float(initial)).sort_index()


@dataclass
class RawSignalDiagnostic:
    """Counts for raw-mode signal path before professional filters."""

    symbol: str
    bars_examined: int = 0
    cross_above_count: int = 0
    cross_below_count: int = 0
    buy_count: int = 0
    exit_count: int = 0
    hold_count: int = 0
    blocked_adx: int = 0
    blocked_close_above_slow: int = 0
    blocked_both: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bars_examined": self.bars_examined,
            "cross_above_count": self.cross_above_count,
            "cross_below_count": self.cross_below_count,
            "buy_count": self.buy_count,
            "exit_count": self.exit_count,
            "hold_count": self.hold_count,
            "blocked_adx": self.blocked_adx,
            "blocked_close_above_slow": self.blocked_close_above_slow,
            "blocked_both": self.blocked_both,
            "notes": list(self.notes),
        }


def diagnose_raw_signals(
    strategy: BaseStrategy,
    features: pd.DataFrame,
    *,
    symbol: str | None = None,
    min_history_bars: int = 60,
    stride: int = 1,
) -> RawSignalDiagnostic:
    """Walk bars and count raw crosses / BUY / EXIT / HOLD with block reasons.

    Does not alter strategy logic — only observes ``generate_signal`` and
    internal snapshot fields when available.
    """
    resolved = (
        symbol.strip().upper()
        if symbol
        else resolve_symbol_from_features(features) or strategy.active_symbol
    )
    diag = RawSignalDiagnostic(symbol=resolved)
    frame = attach_symbol(features.copy(), resolved)
    try:
        strategy.validate(frame)
        prepared = strategy.prepare(frame)
    except Exception as exc:  # noqa: BLE001
        diag.notes.append(f"prepare failed: {exc}")
        return diag

    n = len(prepared)
    start = min(max(min_history_bars, 2), n)
    for cut in range(start, n + 1, max(stride, 1)):
        window = prepared.iloc[:cut]
        diag.bars_examined += 1
        try:
            # Prefer snapshot for cross/block attribution when strategy exposes it.
            snapshot = None
            if hasattr(strategy, "_snapshot"):
                snapshot = strategy._snapshot(window)  # noqa: SLF001 — audit probe
                if snapshot.cross_above.value:
                    diag.cross_above_count += 1
                if snapshot.cross_below.value:
                    diag.cross_below_count += 1
            signal = strategy.generate_signal(window)
            sig = signal.signal
            if sig is SignalType.BUY:
                diag.buy_count += 1
            elif sig in {SignalType.SELL, SignalType.EXIT}:
                diag.exit_count += 1
            else:
                diag.hold_count += 1
                if snapshot is not None and snapshot.cross_above.value:
                    adx_block = not snapshot.adx_ok.value
                    close_block = not snapshot.close_above_slow.value
                    if adx_block and close_block:
                        diag.blocked_both += 1
                    elif adx_block:
                        diag.blocked_adx += 1
                    elif close_block:
                        diag.blocked_close_above_slow += 1
        except Exception as exc:  # noqa: BLE001
            diag.notes.append(f"bar {cut}: {exc}")
            if len(diag.notes) > 20:
                break

    if diag.cross_above_count == 0:
        diag.notes.append(
            "No ema_fast/ema_slow cross-above events in examined bars "
            "(raw BUY requires a true cross).",
        )
    elif diag.buy_count == 0:
        diag.notes.append(
            "Cross-above events exist but raw BUY never fired — blocked by "
            "ADX and/or close>slow gate (not an evaluation detection bug).",
        )
    return diag


@dataclass(frozen=True)
class ValidityVerdict:
    ok: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reasons": list(self.reasons)}


def validate_evaluation_metrics(
    *,
    raw_trades: int,
    professional_trades: int,
    raw_max_dd: float,
    pro_max_dd: float,
    raw_sharpe: float,
    pro_sharpe: float,
    raw_final_equity: float,
    pro_final_equity: float,
    stride: int,
    min_professional_trades: int = 1,
) -> ValidityVerdict:
    """Hard gates before Professional may be recommended.

    Rules (documented, not arbitrary profit tuning):
    1. Baseline (raw) must have >= 1 completed trade for a comparative YES.
    2. Professional must have >= min_professional_trades.
    3. Max drawdown must be in [0, 1] for long-only non-negative equity.
    4. Sharpe / equity must be finite.
    5. Final equity must be non-negative.
    6. Sampled evaluations (stride>1) may still report metrics but recommendation
       is blocked — sampled runs are not full backtests.
    """
    reasons: list[str] = []
    if raw_trades < 1:
        reasons.append("baseline_raw_has_zero_trades")
    if professional_trades < min_professional_trades:
        reasons.append("professional_insufficient_trades")
    for label, dd in (("raw", raw_max_dd), ("professional", pro_max_dd)):
        if dd != dd or dd == float("inf") or dd < 0:
            reasons.append(f"{label}_max_drawdown_invalid")
        elif dd > 1.0 + 1e-9:
            reasons.append(f"{label}_max_drawdown_exceeds_100pct")
    for label, sh in (("raw", raw_sharpe), ("professional", pro_sharpe)):
        if sh != sh or sh == float("inf") or sh == float("-inf"):
            reasons.append(f"{label}_sharpe_non_finite")
    for label, eq in (("raw", raw_final_equity), ("professional", pro_final_equity)):
        if eq != eq or eq < 0:
            reasons.append(f"{label}_equity_invalid")
    if int(stride) > 1:
        reasons.append("sampled_evaluation_not_full_backtest")
    return ValidityVerdict(ok=len(reasons) == 0, reasons=tuple(reasons))
