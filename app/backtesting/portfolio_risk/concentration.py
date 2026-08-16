"""Concentration metrics from exposure snapshots."""

from __future__ import annotations

from collections.abc import Sequence

from app.backtesting.portfolio_risk.schemas import ConcentrationReport, ExposureSnapshot


def concentration_from_snapshots(snapshots: Sequence[ExposureSnapshot]) -> ConcentrationReport:
    if not snapshots:
        return ConcentrationReport()
    peak_symbol = 0.0
    peak_hhi = 0.0
    best = snapshots[0]
    for snap in snapshots:
        peak_symbol = max(peak_symbol, snap.largest_position_pct)
        peak_hhi = max(peak_hhi, snap.hhi)
        if snap.open_positions > 0 and (
            snap.hhi > best.hhi or (snap.hhi == best.hhi and snap.gross_exposure > best.gross_exposure)
        ):
            best = snap
    if best.open_positions == 0:
        invested = [s for s in snapshots if s.open_positions > 0]
        best = invested[-1] if invested else snapshots[-1]
    return concentration_from_weights(
        best.symbol_weights,
        best.strategy_weights,
        hhi=best.hhi,
        peak_largest_symbol_pct=peak_symbol,
        peak_hhi=peak_hhi,
    )


def concentration_from_weights(
    symbol_weights_pct: dict[str, float],
    strategy_weights_pct: dict[str, float],
    *,
    hhi: float | None = None,
    peak_largest_symbol_pct: float = 0.0,
    peak_hhi: float = 0.0,
) -> ConcentrationReport:
    symbols = sorted(symbol_weights_pct.items(), key=lambda kv: kv[1], reverse=True)
    strategies = sorted(strategy_weights_pct.items(), key=lambda kv: kv[1], reverse=True)
    frac = [w / 100.0 for _, w in symbols]
    computed_hhi = float(sum(w * w for w in frac)) if hhi is None else float(hhi)
    largest_sym, largest_pct = (symbols[0] if symbols else ("", 0.0))
    largest_strat, largest_strat_pct = (strategies[0] if strategies else ("", 0.0))
    top2 = sum(w for _, w in symbols[:2])
    top5 = sum(w for _, w in symbols[:5])
    return ConcentrationReport(
        largest_symbol=largest_sym,
        largest_symbol_pct=largest_pct,
        top2_pct=top2,
        top5_pct=top5,
        largest_strategy=largest_strat,
        largest_strategy_pct=largest_strat_pct,
        hhi=computed_hhi,
        hhi_10000=computed_hhi * 10_000.0,
        peak_largest_symbol_pct=peak_largest_symbol_pct or largest_pct,
        peak_hhi=peak_hhi or computed_hhi,
    )
