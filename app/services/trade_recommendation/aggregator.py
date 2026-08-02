"""Multi-strategy recommendation aggregator with consensus rules."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from app.services.trade_recommendation.confidence import combine_confidence
from app.services.trade_recommendation.schemas import (
    AggregatedRecommendation,
    ConfidenceInputs,
    ConsensusSignal,
    RecommendationConfig,
    TradeRecommendation,
)
from app.services.trade_recommendation.validator import TradeRecommendationValidator
from app.strategy_engine.models import SignalType


class RecommendationAggregator:
    """Combine multiple ``TradeRecommendation`` objects into one consensus view.

    Conflict rule: any simultaneous BUY-family and SELL-family signals → HOLD
    with an explanation. Strong agreement (configurable count + confidence) →
    STRONG_BUY / STRONG_SELL.
    """

    def __init__(
        self,
        config: RecommendationConfig | None = None,
        *,
        validator: TradeRecommendationValidator | None = None,
    ) -> None:
        self._config = config or RecommendationConfig()
        self._validator = validator or TradeRecommendationValidator(self._config)

    @property
    def config(self) -> RecommendationConfig:
        return self._config

    def aggregate(
        self,
        recommendations: list[TradeRecommendation],
        *,
        timeframe: str | None = None,
        volume_score: float = 50.0,
        confluence_score: float = 50.0,
    ) -> AggregatedRecommendation:
        if not recommendations:
            raise ValueError("recommendations must not be empty")

        validated: list[TradeRecommendation] = []
        warnings: list[str] = []
        # Fresh id set for this aggregation batch (allow ids unique within batch)
        batch_validator = TradeRecommendationValidator(
            self._config,
            seen_trade_ids=set(self._validator.seen_trade_ids),
        )
        for item in recommendations:
            errors = batch_validator.collect_errors(item)
            if errors:
                warnings.append(
                    f"Skipped {item.strategy_name}: {'; '.join(errors)}",
                )
                continue
            batch_validator.seen_trade_ids.add(item.trade_id)
            validated.append(item)

        if not validated:
            raise ValueError(
                "No valid recommendations to aggregate: " + "; ".join(warnings),
            )

        buy_count = sum(1 for item in validated if item.signal is SignalType.BUY)
        sell_count = sum(1 for item in validated if item.signal is SignalType.SELL)
        hold_count = sum(1 for item in validated if item.signal is SignalType.HOLD)
        exit_count = sum(1 for item in validated if item.signal is SignalType.EXIT)
        total = len(validated)

        consensus, explanation = self._resolve_consensus(
            buy_count=buy_count,
            sell_count=sell_count,
            hold_count=hold_count,
            exit_count=exit_count,
            total=total,
            validated=validated,
        )

        symbol = validated[0].symbol
        tf = timeframe or validated[0].timeframe
        timestamp = max(item.timestamp for item in validated)

        primary = self._select_primary(validated, consensus)
        confidence_inputs = self._blend_inputs(
            validated,
            consensus=consensus,
            volume_score=volume_score,
            confluence_score=confluence_score,
        )
        breakdown = combine_confidence(confidence_inputs, self._config)

        final_rec: TradeRecommendation | None = None
        if primary is not None and consensus not in {
            ConsensusSignal.HOLD,
        }:
            mapped_signal = _consensus_to_signal(consensus)
            final_rec = primary.model_copy(
                update={
                    "signal": mapped_signal,
                    "confidence": breakdown.total,
                    "strategy_name": f"consensus:{primary.strategy_name}",
                    "reasons": [
                        explanation,
                        *primary.reasons,
                        *[f"[{item.strategy_name}] {item.signal.value}" for item in validated],
                    ],
                    "warnings": list({*primary.warnings, *warnings}),
                },
            )
            # Re-validate geometry for mapped BUY/SELL
            if mapped_signal in {SignalType.BUY, SignalType.SELL}:
                final_errors = TradeRecommendationValidator(self._config).collect_errors(
                    final_rec,
                )
                if final_errors:
                    warnings.extend(final_errors)
                    consensus = ConsensusSignal.HOLD
                    explanation = (
                        f"Consensus geometry invalid after merge: {'; '.join(final_errors)}"
                    )
                    final_rec = None

        return AggregatedRecommendation(
            symbol=symbol,
            timeframe=tf,
            timestamp=timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc),
            consensus=consensus,
            confidence=breakdown.total,
            confidence_breakdown=breakdown,
            recommendation=final_rec,
            contributing=validated,
            buy_count=buy_count,
            sell_count=sell_count,
            hold_count=hold_count,
            exit_count=exit_count,
            explanation=explanation,
            warnings=warnings,
        )

    def _resolve_consensus(
        self,
        *,
        buy_count: int,
        sell_count: int,
        hold_count: int,
        exit_count: int,
        total: int,
        validated: list[TradeRecommendation],
    ) -> tuple[ConsensusSignal, str]:
        if buy_count > 0 and sell_count > 0:
            return (
                ConsensusSignal.HOLD,
                (
                    f"Strategies conflict: {buy_count} BUY vs {sell_count} SELL "
                    f"across {total} valid recommendations — holding"
                ),
            )

        if exit_count == total:
            return ConsensusSignal.EXIT, f"All {total} strategies signal EXIT"

        if buy_count > 0 and sell_count == 0:
            ratio = buy_count / total
            avg_conf = mean(item.confidence for item in validated if item.signal is SignalType.BUY)
            if (
                buy_count >= self._config.strong_consensus_min_count
                and avg_conf >= self._config.strong_consensus_min_confidence
                and ratio >= self._config.min_agreement_ratio
            ):
                return (
                    ConsensusSignal.STRONG_BUY,
                    (
                        f"STRONG BUY: {buy_count}/{total} strategies agree "
                        f"(avg confidence {avg_conf:.1f})"
                    ),
                )
            if ratio >= self._config.min_agreement_ratio:
                return (
                    ConsensusSignal.BUY,
                    f"BUY consensus: {buy_count}/{total} strategies agree",
                )
            return (
                ConsensusSignal.HOLD,
                f"Insufficient BUY agreement ({buy_count}/{total} < "
                f"{self._config.min_agreement_ratio:.0%} threshold)",
            )

        if sell_count > 0 and buy_count == 0:
            ratio = sell_count / total
            avg_conf = mean(item.confidence for item in validated if item.signal is SignalType.SELL)
            if (
                sell_count >= self._config.strong_consensus_min_count
                and avg_conf >= self._config.strong_consensus_min_confidence
                and ratio >= self._config.min_agreement_ratio
            ):
                return (
                    ConsensusSignal.STRONG_SELL,
                    (
                        f"STRONG SELL: {sell_count}/{total} strategies agree "
                        f"(avg confidence {avg_conf:.1f})"
                    ),
                )
            if ratio >= self._config.min_agreement_ratio:
                return (
                    ConsensusSignal.SELL,
                    f"SELL consensus: {sell_count}/{total} strategies agree",
                )
            return (
                ConsensusSignal.HOLD,
                f"Insufficient SELL agreement ({sell_count}/{total})",
            )

        if hold_count == total:
            return ConsensusSignal.HOLD, f"All {total} strategies are HOLD"

        return ConsensusSignal.HOLD, "No clear directional consensus"

    def _select_primary(
        self,
        validated: list[TradeRecommendation],
        consensus: ConsensusSignal,
    ) -> TradeRecommendation | None:
        if consensus in {ConsensusSignal.BUY, ConsensusSignal.STRONG_BUY}:
            buys = [item for item in validated if item.signal is SignalType.BUY]
            return max(buys, key=lambda item: item.confidence) if buys else None
        if consensus in {ConsensusSignal.SELL, ConsensusSignal.STRONG_SELL}:
            sells = [item for item in validated if item.signal is SignalType.SELL]
            return max(sells, key=lambda item: item.confidence) if sells else None
        if consensus is ConsensusSignal.EXIT:
            exits = [item for item in validated if item.signal is SignalType.EXIT]
            return exits[0] if exits else validated[0]
        return max(validated, key=lambda item: item.confidence)

    def _blend_inputs(
        self,
        validated: list[TradeRecommendation],
        *,
        consensus: ConsensusSignal,
        volume_score: float,
        confluence_score: float,
    ) -> ConfidenceInputs:
        avg_strategy = mean(item.confidence for item in validated)
        # Boost confluence proxy when consensus is strong
        conf_boost = confluence_score
        if consensus in {ConsensusSignal.STRONG_BUY, ConsensusSignal.STRONG_SELL}:
            conf_boost = max(confluence_score, 90.0)
        elif consensus is ConsensusSignal.HOLD:
            conf_boost = min(confluence_score, 40.0)

        # Representative structure/trend from highest-confidence directional plan
        primary = max(validated, key=lambda item: item.confidence)
        from app.services.trade_recommendation.confidence import (
            risk_reward_to_score,
            structure_to_score,
            trend_to_score,
        )

        signal = primary.signal
        return ConfidenceInputs(
            strategy_confidence=avg_strategy,
            trend_strength=trend_to_score(primary.trend_direction, signal=signal),
            volume_score=volume_score,
            structure_score=structure_to_score(primary.market_structure, signal=signal),
            risk_reward_score=risk_reward_to_score(primary.risk_reward),
            confluence_score=conf_boost,
        )


def _consensus_to_signal(consensus: ConsensusSignal) -> SignalType:
    if consensus in {ConsensusSignal.BUY, ConsensusSignal.STRONG_BUY}:
        return SignalType.BUY
    if consensus in {ConsensusSignal.SELL, ConsensusSignal.STRONG_SELL}:
        return SignalType.SELL
    if consensus is ConsensusSignal.EXIT:
        return SignalType.EXIT
    return SignalType.HOLD
