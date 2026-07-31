"""Risk engine — stop/target/position-risk planning from features and structure."""

from __future__ import annotations

import pandas as pd

from app.core.logging import get_logger
from app.market_structure.schemas import MarketStructureResult
from app.risk_engine.exceptions import RiskValidationError
from app.risk_engine.schemas import (
    RiskConfig,
    RiskPlan,
    StopLevel,
    StopMethod,
    TradeDirection,
)
from app.risk_engine.stops import (
    atr_stop,
    estimate_confidence,
    percentage_stop,
    position_risk,
    structure_stop,
    swing_stop,
    take_profit_from_risk,
    time_stop,
)

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"


class RiskEngine:
    """Build a reusable risk plan from entry, direction, features, and structure.

    Supported stop families:
        ATR, Swing, Structure, Percentage, Time

    Also computes risk/reward, position risk, holding estimate, and confidence.
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self._config = config or RiskConfig()

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    @property
    def config(self) -> RiskConfig:
        return self._config

    def compute(
        self,
        *,
        entry_price: float,
        direction: TradeDirection | str,
        features: pd.DataFrame,
        market_structure: MarketStructureResult,
        config: RiskConfig | None = None,
    ) -> RiskPlan:
        """Return stop loss, take profit, RR, holding estimate, and confidence.

        Args:
            entry_price: Planned entry.
            direction: ``LONG`` or ``SHORT``.
            features: Feature-engine DataFrame (must include ATR column when used).
            market_structure: Output from ``MarketStructureService``.
            config: Optional per-call config override.
        """
        cfg = config or self._config
        trade_direction = _as_direction(direction)
        _validate_inputs(entry_price, features, market_structure)

        stops = self._collect_stops(
            entry_price=entry_price,
            direction=trade_direction,
            features=features,
            market_structure=market_structure,
            config=cfg,
        )
        selected = self._select_price_stop(stops, cfg.preferred_stop)
        assert selected.price is not None

        take_profit, realized_rr = take_profit_from_risk(
            entry_price,
            selected.price,
            trade_direction,
            cfg.risk_reward,
        )
        holding = next(
            (stop.bars for stop in stops if stop.method is StopMethod.TIME and stop.bars),
            cfg.time_stop_bars,
        )
        pos_risk = position_risk(entry_price, selected.price, cfg)
        confidence = estimate_confidence(
            direction=trade_direction,
            structure=market_structure,
            stop_method=selected.method,
            stops=stops,
            risk_reward=realized_rr,
            requested_risk_reward=cfg.risk_reward,
        )
        reasons = [
            selected.reason,
            f"Take profit at {take_profit:.6g} for RR={realized_rr:g}",
            f"Holding estimate {holding} bars",
            f"Confidence {confidence:.4f}",
        ]

        plan = RiskPlan(
            entry_price=entry_price,
            direction=trade_direction,
            stop_loss=selected.price,
            take_profit=take_profit,
            risk_reward=realized_rr,
            holding_estimate=holding,
            confidence=confidence,
            stop_method=selected.method,
            stops=stops,
            position_risk=pos_risk,
            reasons=reasons,
        )
        logger.info(
            "Risk plan %s entry=%.6g stop=%.6g tp=%.6g rr=%.3f hold=%d conf=%.3f",
            trade_direction.value,
            plan.entry_price,
            plan.stop_loss,
            plan.take_profit,
            plan.risk_reward,
            plan.holding_estimate,
            plan.confidence,
        )
        return plan

    def _collect_stops(
        self,
        *,
        entry_price: float,
        direction: TradeDirection,
        features: pd.DataFrame,
        market_structure: MarketStructureResult,
        config: RiskConfig,
    ) -> list[StopLevel]:
        stops: list[StopLevel] = []
        builders = (
            (StopMethod.ATR, lambda: atr_stop(entry_price, direction, features, config)),
            (StopMethod.PERCENTAGE, lambda: percentage_stop(entry_price, direction, config)),
            (StopMethod.SWING, lambda: swing_stop(entry_price, direction, market_structure, config)),
            (
                StopMethod.STRUCTURE,
                lambda: structure_stop(entry_price, direction, market_structure, config),
            ),
            (StopMethod.TIME, lambda: time_stop(config)),
        )
        for method, builder in builders:
            try:
                stops.append(builder())
            except RiskValidationError as exc:
                logger.debug("Stop method %s unavailable: %s", method.value, exc)
        if not any(stop.price is not None for stop in stops):
            raise RiskValidationError(
                "Unable to compute any price stop from the provided features/structure",
            )
        return stops

    @staticmethod
    def _select_price_stop(stops: list[StopLevel], preferred: StopMethod) -> StopLevel:
        priced = [stop for stop in stops if stop.price is not None]
        for stop in priced:
            if stop.method is preferred:
                return stop
        # Prefer structural stops, then swing, ATR, percentage.
        priority = (
            StopMethod.STRUCTURE,
            StopMethod.SWING,
            StopMethod.ATR,
            StopMethod.PERCENTAGE,
        )
        for method in priority:
            for stop in priced:
                if stop.method is method:
                    return stop
        return priced[0]


def _as_direction(direction: TradeDirection | str) -> TradeDirection:
    if isinstance(direction, TradeDirection):
        return direction
    try:
        return TradeDirection(direction.strip().upper())
    except ValueError as exc:
        raise RiskValidationError(f"Unknown trade direction: {direction!r}") from exc


def _validate_inputs(
    entry_price: float,
    features: pd.DataFrame,
    market_structure: MarketStructureResult,
) -> None:
    if entry_price <= 0:
        raise RiskValidationError("entry_price must be positive")
    if not isinstance(features, pd.DataFrame):
        raise TypeError(f"features must be a DataFrame, got {type(features).__name__}")
    if features.empty:
        raise RiskValidationError("features must not be empty")
    if not isinstance(market_structure, MarketStructureResult):
        raise TypeError(
            f"market_structure must be MarketStructureResult, got {type(market_structure).__name__}",
        )
