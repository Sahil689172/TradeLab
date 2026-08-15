"""Transparent robustness score. Not a black-box rating and not a profitability proof."""

from __future__ import annotations

from app.backtesting.monte_carlo.schemas import (
    CostSensitivityRow,
    RobustnessAssessment,
    RobustnessBand,
    SimulationSummary,
)

FORMULA = (
    "Start at 100. Deduct: min(40, 100*P(loss)); "
    "P95 |max DD| ≥30% −25, ≥20% −15, ≥10% −8; "
    "median return < 0 −20; P05 return < 0 −10; "
    "P95 losing streak ≥8 −10, ≥5 −5; "
    "cost-sensitivity ΔP(loss) ≥10pp −15, ≥5pp −8; "
    "sample size <5 −40 and cap LOW, <10 −25 and cap MEDIUM, <20 −10. "
    "HIGH only if score≥70, n≥10, P(loss)<20%, P95 |DD|<25%, and median return>0. "
    "Median profit alone is never sufficient for HIGH."
)


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
