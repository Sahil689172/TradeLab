"""Trade recommendation validation — reject invalid recommendations before emit."""

from __future__ import annotations

from datetime import datetime

from app.services.trade_recommendation.schemas import (
    RecommendationConfig,
    TradeRecommendation,
)
from app.strategy_engine.models import SignalType


class TradeRecommendationValidationError(ValueError):
    """Raised when a TradeRecommendation fails business-rule validation."""


class TradeRecommendationValidator:
    """Validate geometry, confidence, RR, timestamps, and trade-id uniqueness."""

    def __init__(
        self,
        config: RecommendationConfig | None = None,
        *,
        seen_trade_ids: set[str] | None = None,
    ) -> None:
        self._config = config or RecommendationConfig()
        self._seen_trade_ids: set[str] = seen_trade_ids if seen_trade_ids is not None else set()

    @property
    def config(self) -> RecommendationConfig:
        return self._config

    @property
    def seen_trade_ids(self) -> set[str]:
        return self._seen_trade_ids

    def validate(self, recommendation: TradeRecommendation) -> TradeRecommendation:
        """Validate and return ``recommendation``, or raise.

        Side effect: registers ``trade_id`` in the seen set on success.
        """
        errors = self.collect_errors(recommendation)
        if errors:
            raise TradeRecommendationValidationError("; ".join(errors))
        self._seen_trade_ids.add(recommendation.trade_id)
        return recommendation

    def collect_errors(self, recommendation: TradeRecommendation) -> list[str]:
        """Return a list of validation error messages (empty if valid)."""
        errors: list[str] = []
        errors.extend(self._price_errors(recommendation))
        errors.extend(self._directional_errors(recommendation))
        errors.extend(self._confidence_errors(recommendation))
        errors.extend(self._risk_reward_errors(recommendation))
        errors.extend(self._timestamp_errors(recommendation))
        errors.extend(self._trade_id_errors(recommendation))
        return errors

    def is_valid(self, recommendation: TradeRecommendation) -> bool:
        return not self.collect_errors(recommendation)

    def _price_errors(self, rec: TradeRecommendation) -> list[str]:
        errors: list[str] = []
        for label, value in (
            ("entry_price", rec.entry_price),
            ("stop_loss", rec.stop_loss),
            ("target_1", rec.target_1),
            ("target_2", rec.target_2),
        ):
            if value <= 0:
                errors.append(f"{label} must be positive (got {value})")
        return errors

    def _directional_errors(self, rec: TradeRecommendation) -> list[str]:
        if rec.signal is SignalType.HOLD:
            return []
        if rec.signal is SignalType.EXIT:
            # EXIT may flatten geometry; still require positive prices (checked above)
            return []

        errors: list[str] = []
        if rec.signal is SignalType.BUY:
            if not (rec.stop_loss < rec.entry_price):
                errors.append(
                    f"BUY requires stop_loss < entry "
                    f"({rec.stop_loss} !< {rec.entry_price})",
                )
            if not (rec.target_1 > rec.entry_price):
                errors.append(
                    f"BUY requires target_1 > entry "
                    f"({rec.target_1} !> {rec.entry_price})",
                )
            if not (rec.target_2 > rec.target_1):
                errors.append(
                    f"BUY requires target_2 > target_1 "
                    f"({rec.target_2} !> {rec.target_1})",
                )
        elif rec.signal is SignalType.SELL:
            if not (rec.stop_loss > rec.entry_price):
                errors.append(
                    f"SELL requires stop_loss > entry "
                    f"({rec.stop_loss} !> {rec.entry_price})",
                )
            if not (rec.target_1 < rec.entry_price):
                errors.append(
                    f"SELL requires target_1 < entry "
                    f"({rec.target_1} !< {rec.entry_price})",
                )
            if not (rec.target_2 < rec.target_1):
                errors.append(
                    f"SELL requires target_2 < target_1 "
                    f"({rec.target_2} !< {rec.target_1})",
                )
        return errors

    def _confidence_errors(self, rec: TradeRecommendation) -> list[str]:
        if not 0.0 <= rec.confidence <= 100.0:
            return [f"confidence must be in [0, 100] (got {rec.confidence})"]
        return []

    def _risk_reward_errors(self, rec: TradeRecommendation) -> list[str]:
        if rec.signal in {SignalType.BUY, SignalType.SELL}:
            if rec.risk_reward < self._config.min_risk_reward:
                return [
                    f"risk_reward {rec.risk_reward:g} below minimum "
                    f"{self._config.min_risk_reward:g}",
                ]
        if rec.risk_reward < 0:
            return [f"risk_reward must be non-negative (got {rec.risk_reward})"]
        return []

    def _timestamp_errors(self, rec: TradeRecommendation) -> list[str]:
        if not isinstance(rec.timestamp, datetime):
            return ["timestamp must be a datetime"]
        # Reject naive sentinel / clearly invalid extremes
        if rec.timestamp.year < 1970 or rec.timestamp.year > 2100:
            return [f"timestamp year out of range: {rec.timestamp.isoformat()}"]
        return []

    def _trade_id_errors(self, rec: TradeRecommendation) -> list[str]:
        if not rec.trade_id.strip():
            return ["trade_id must not be blank"]
        if rec.trade_id in self._seen_trade_ids:
            return [f"duplicate trade_id: {rec.trade_id}"]
        return []
