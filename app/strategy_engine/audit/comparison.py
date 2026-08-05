"""Cross-strategy comparison table."""

from __future__ import annotations

from app.strategy_engine.audit.schemas import (
    StrategyComparisonRow,
    StrategyComparisonTable,
    StrategyScorecard,
)


def build_comparison(scorecard: StrategyScorecard) -> StrategyComparisonTable:
    ranked = sorted(
        scorecard.rows,
        key=lambda row: (-row.composite_score, row.strategy_name),
    )
    rows: list[StrategyComparisonRow] = []
    for index, row in enumerate(ranked, start=1):
        rows.append(
            StrategyComparisonRow(
                rank=index,
                strategy_name=row.strategy_name,
                composite_score=row.composite_score,
                average_confidence=row.average_confidence,
                average_risk_reward=row.average_risk_reward,
                average_win_expectancy=row.average_win_expectancy,
                filter_acceptance_rate=row.filter_acceptance_rate,
                actionable_signals=row.buy_signals + row.sell_signals,
                ready=row.ready,
            ),
        )
    return StrategyComparisonTable(symbol=scorecard.symbol, rows=tuple(rows))
