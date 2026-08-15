"""Transparent robustness score and sample-capped evidence verdict.

The numeric band is a diagnostic. The verdict is separately capped by
historical sample size so a tiny trade log cannot be labeled ROBUST.
"""

from __future__ import annotations

import numpy as np

from app.backtesting.monte_carlo.schemas import (
    CostSensitivityRow,
    MonteCarloVerdict,
    RobustnessAssessment,
    RobustnessBand,
    SampleQuality,
    SimulationSummary,
)
from app.backtesting.monte_carlo.simulation import summary_from_batch

FORMULA = (
    "Start at 100. Deduct: min(40, 100*P(loss)); "
    "P95 |max DD| ≥30% −25, ≥20% −15, ≥10% −8; "
    "median return < 0 −20; P05 return < 0 −10; "
    "P95 losing streak ≥8 −10, ≥5 −5; "
    "cost-sensitivity ΔP(loss) ≥10pp −15, ≥5pp −8; "
    "sample size <5 −40 and cap LOW, <10 −25 and cap MEDIUM, <20 −10. "
    "HIGH band only if score≥70, n≥10, P(loss)<20%, P95 |DD|<25%, and median return>0. "
    "Verdict is separate and sample-capped: 0–4 trades → INSUFFICIENT_EVIDENCE; "
    "5–19 max WEAK; 20–49 max LIMITED; 50–99 max PROMISING; 100+ may be ROBUST. "
    "Median profit alone is never sufficient for HIGH or ROBUST. "
    "Simulations do not create new independent historical observations."
)


def classify_sample_quality(historical_trade_count: int) -> SampleQuality:
    """Reporting-quality label. Not a claim of statistical sufficiency."""
    n = historical_trade_count
    if n <= 0:
        return SampleQuality.INVALID
    if n <= 4:
        return SampleQuality.EXTREMELY_LOW
    if n <= 19:
        return SampleQuality.LOW
    if n <= 49:
        return SampleQuality.LIMITED
    if n <= 99:
        return SampleQuality.MODERATE
    return SampleQuality.STRONGER


def _verdict_rank(verdict: MonteCarloVerdict) -> int:
    order = (
        MonteCarloVerdict.INSUFFICIENT_EVIDENCE,
        MonteCarloVerdict.WEAK,
        MonteCarloVerdict.LIMITED,
        MonteCarloVerdict.PROMISING,
        MonteCarloVerdict.ROBUST,
    )
    return order.index(verdict)


def _cap_verdict(quality: SampleQuality, raw: MonteCarloVerdict) -> MonteCarloVerdict:
    ceiling = {
        SampleQuality.INVALID: MonteCarloVerdict.INSUFFICIENT_EVIDENCE,
        SampleQuality.EXTREMELY_LOW: MonteCarloVerdict.INSUFFICIENT_EVIDENCE,
        SampleQuality.LOW: MonteCarloVerdict.WEAK,
        SampleQuality.LIMITED: MonteCarloVerdict.LIMITED,
        SampleQuality.MODERATE: MonteCarloVerdict.PROMISING,
        SampleQuality.STRONGER: MonteCarloVerdict.ROBUST,
    }[quality]
    if _verdict_rank(raw) > _verdict_rank(ceiling):
        return ceiling
    return raw


def assess_verdict(
    *,
    source_trade_count: int,
    probability_of_loss: float,
    median_return: float,
    p95_max_drawdown: float,
    score: float,
) -> MonteCarloVerdict:
    """Distribution-based verdict, then hard-capped by sample quality."""
    n = source_trade_count
    quality = classify_sample_quality(n)
    if n <= 0:
        return MonteCarloVerdict.INSUFFICIENT_EVIDENCE

    p95_dd = abs(p95_max_drawdown)
    if (
        n >= 100
        and score >= 70
        and probability_of_loss < 0.20
        and p95_dd < 0.25
        and median_return > 0
    ):
        raw = MonteCarloVerdict.ROBUST
    elif score >= 60 and median_return > 0 and probability_of_loss < 0.40:
        raw = MonteCarloVerdict.PROMISING
    elif score >= 45:
        raw = MonteCarloVerdict.LIMITED
    elif score > 0:
        raw = MonteCarloVerdict.WEAK
    else:
        raw = MonteCarloVerdict.INSUFFICIENT_EVIDENCE
    return _cap_verdict(quality, raw)


def assess_robustness(
    *,
    source_trade_count: int,
    probability_of_loss: float,
    median_return: float,
    p05_return: float,
    p95_max_drawdown: float,
    p95_losing_streak: float,
    cost_rows: list[CostSensitivityRow],
) -> RobustnessAssessment:
    n = source_trade_count
    reasons: list[str] = []
    score = 100.0
    cap: RobustnessBand | None = None

    if n <= 0:
        return RobustnessAssessment(
            band=RobustnessBand.LOW,
            score=0.0,
            formula=FORMULA,
            reasons=["no completed trades — Monte Carlo cannot manufacture evidence"],
        )

    if n < 5:
        score -= 40
        cap = RobustnessBand.LOW
        reasons.append(f"only {n} historical trades (−40, cannot exceed LOW)")
    elif n < 10:
        score -= 25
        cap = RobustnessBand.MEDIUM
        reasons.append(f"only {n} historical trades (−25, cannot exceed MEDIUM)")
    elif n < 20:
        score -= 10
        reasons.append(f"{n} historical trades (−10 sample-size penalty)")

    loss_pen = min(40.0, 100.0 * probability_of_loss)
    score -= loss_pen
    reasons.append(f"probability of loss = {probability_of_loss:.1%} (−{loss_pen:.1f})")

    p95_dd = abs(p95_max_drawdown)
    if p95_dd >= 0.30:
        score -= 25
        reasons.append(f"P95 |max drawdown| = {p95_dd:.1%} ≥ 30% (−25)")
    elif p95_dd >= 0.20:
        score -= 15
        reasons.append(f"P95 |max drawdown| = {p95_dd:.1%} ≥ 20% (−15)")
    elif p95_dd >= 0.10:
        score -= 8
        reasons.append(f"P95 |max drawdown| = {p95_dd:.1%} ≥ 10% (−8)")
    else:
        reasons.append(f"P95 |max drawdown| = {p95_dd:.1%}")

    if median_return < 0:
        score -= 20
        reasons.append("median return is negative (−20)")
    if p05_return < 0:
        score -= 10
        reasons.append("P05 return is negative (−10)")

    if p95_losing_streak >= 8:
        score -= 10
        reasons.append(f"P95 losing streak = {p95_losing_streak:.0f} (−10)")
    elif p95_losing_streak >= 5:
        score -= 5
        reasons.append(f"P95 losing streak = {p95_losing_streak:.0f} (−5)")

    if cost_rows:
        base = cost_rows[0].probability_of_loss
        worst = max(row.probability_of_loss for row in cost_rows)
        delta = max(0.0, worst - base)
        if delta >= 0.10:
            score -= 15
            reasons.append(f"cost sensitivity: P(loss) rises {delta:.1%} (−15)")
        elif delta >= 0.05:
            score -= 8
            reasons.append(f"cost sensitivity: P(loss) rises {delta:.1%} (−8)")

    score = max(0.0, min(100.0, score))

    if score >= 70 and n >= 10 and probability_of_loss < 0.20 and p95_dd < 0.25 and median_return > 0:
        band = RobustnessBand.HIGH
    elif score >= 45:
        band = RobustnessBand.MEDIUM
    else:
        band = RobustnessBand.LOW

    if cap is RobustnessBand.LOW:
        band = RobustnessBand.LOW
    elif cap is RobustnessBand.MEDIUM and band is RobustnessBand.HIGH:
        band = RobustnessBand.MEDIUM

    reasons.append(
        f"sample quality = {classify_sample_quality(n).value}; "
        "verdict is capped by historical trade count, not by simulation count",
    )

    return RobustnessAssessment(
        band=band,
        score=round(score, 1),
        formula=FORMULA,
        reasons=reasons,
    )


def pick_cases(
    summaries: list[SimulationSummary],
) -> tuple[SimulationSummary | None, SimulationSummary | None, SimulationSummary | None]:
    if not summaries:
        return None, None, None
    by_final = sorted(summaries, key=lambda s: s.final_equity)
    worst = by_final[0]
    best = by_final[-1]
    median = by_final[len(by_final) // 2]
    return worst, median, best


def pick_cases_from_batch(
    batch: dict[str, np.ndarray],
) -> tuple[SimulationSummary | None, SimulationSummary | None, SimulationSummary | None]:
    finals = batch["final"]
    if finals.size == 0:
        return None, None, None
    order = np.argsort(finals, kind="mergesort")
    worst_i = int(order[0])
    best_i = int(order[-1])
    median_i = int(order[finals.size // 2])
    return (
        summary_from_batch(batch, worst_i),
        summary_from_batch(batch, median_i),
        summary_from_batch(batch, best_i),
    )
