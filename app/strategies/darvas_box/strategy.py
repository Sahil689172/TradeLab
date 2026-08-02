"""Darvas Box breakout strategy.

Box detection lives in ``app.services.strategy_engine.darvas`` — reusable by
future strategies. This module only applies trade filters and TradePlan math.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.darvas import (
    DarvasBoxEngine,
    DarvasBoxEngineConfig,
    DarvasBoxSnapshot,
    DarvasBoxValidationError,
)
from app.services.strategy_engine.indicators.volume_analysis import (
    VolumeAnalysisService,
    VolumeValidationError,
)
from app.strategies.darvas_box.config import DarvasBoxStrategyConfig
from app.strategies.darvas_box.evaluation import (
    assess_darvas_setup,
    build_confidence,
    ema_trend_bullish,
    select_darvas_stop,
    select_darvas_targets,
)
from app.strategies.darvas_box.schemas import DarvasBoxPlan, DarvasSetup
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, TradePlan

logger = get_logger(__name__)


class DarvasBoxStrategy(BaseStrategy):
    """Classic Darvas Box breakout / breakdown strategy."""

    def __init__(
        self,
        config: DarvasBoxStrategyConfig | None = None,
        *,
        box_engine: DarvasBoxEngine | None = None,
        volume_service: VolumeAnalysisService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or DarvasBoxStrategyConfig()
        self._boxes = box_engine or DarvasBoxEngine(
            DarvasBoxEngineConfig(
                confirm_bars=self._config.confirm_bars,
                min_box_bars=self._config.min_box_bars,
                date_column=self._config.date_column,
                high_column=self._config.high_column,
                low_column=self._config.low_column,
                close_column=self._config.close_column,
            ),
        )
        self._volume = volume_service or VolumeAnalysisService(
            volume_column=self._config.volume_column,
        )
        self._conditions = condition_engine or ConditionEngine()
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        self._cached_snapshot: DarvasBoxSnapshot | None = None
        self._last_detailed_plan: DarvasBoxPlan | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> DarvasBoxStrategyConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> DarvasBoxPlan | None:
        return self._last_detailed_plan

    @property
    def last_box_snapshot(self) -> DarvasBoxSnapshot | None:
        return self._cached_snapshot

    def validate(self, features: pd.DataFrame) -> None:
        if not isinstance(features, pd.DataFrame):
            raise StrategyValidationError("features must be a pandas DataFrame")
        if features.empty:
            raise StrategyValidationError("features must not be empty")
        required = {
            self._config.date_column,
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
            self._config.volume_column,
        }
        missing = sorted(column for column in required if column not in features.columns)
        if missing:
            raise StrategyValidationError(
                f"Darvas strategy missing columns: {', '.join(missing)}",
            )
        if len(features) < self._config.min_history_bars:
            raise StrategyValidationError(
                f"Need at least {self._config.min_history_bars} bars",
            )

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        frame = features.copy()
        frame[self._config.date_column] = pd.to_datetime(frame[self._config.date_column])
        for column in (
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
            self._config.volume_column,
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if self._config.open_column in frame.columns:
            frame[self._config.open_column] = pd.to_numeric(
                frame[self._config.open_column],
                errors="coerce",
            )
        for column in (
            self._config.ema_fast_column,
            self._config.ema_slow_column,
            self._config.atr_column,
        ):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = (
            frame.dropna(
                subset=[
                    self._config.high_column,
                    self._config.low_column,
                    self._config.close_column,
                    self._config.volume_column,
                ],
            )
            .drop_duplicates(subset=[self._config.date_column], keep="last")
            .sort_values(self._config.date_column)
            .reset_index(drop=True)
        )
        if self._config.open_column not in frame.columns:
            frame[self._config.open_column] = frame[self._config.close_column]

        try:
            frame = self._volume.attach(frame)
            self._cached_snapshot = self._boxes.detect(frame)
        except (VolumeValidationError, DarvasBoxValidationError) as exc:
            raise StrategyValidationError(str(exc)) from exc
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        return Signal(
            symbol=self.active_symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=build_confidence(setup),
            reason="; ".join(setup.reasons) if setup.reasons else "Darvas hold",
        )

    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        detailed = self.generate_detailed_trade_plan(features, signal)
        self._last_detailed_plan = detailed
        return TradePlan(
            symbol=detailed.symbol,
            entry_price=detailed.entry_price,
            signal=detailed.signal,
            stop_loss=detailed.stop_loss,
            take_profit_1=detailed.take_profit_1,
            take_profit_2=detailed.take_profit_2,
            holding_period=detailed.expected_holding_bars,
            risk_reward=detailed.risk_reward,
            confidence=detailed.confidence,
            reasons=detailed.reasons,
            strategy_name=detailed.strategy_name,
        )

    def generate_detailed_trade_plan(
        self,
        features: pd.DataFrame,
        signal: Signal | None = None,
    ) -> DarvasBoxPlan:
        setup = self._assess(features)
        if signal is None:
            signal = Signal(
                symbol=self.active_symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=build_confidence(setup),
                reason="; ".join(setup.reasons) if setup.reasons else "Darvas hold",
            )

        box = setup.snapshot.box
        if box is None:
            raise StrategyValidationError("No current Darvas box available for TradePlan")

        entry_price = float(features.iloc[-1][self._config.close_column])
        direction = setup.direction or TradeDirection.LONG
        atr_value = self._latest_atr(features)
        stop_source, stop_loss = select_darvas_stop(
            direction=direction,
            entry_price=entry_price,
            box=box,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_stop_multiplier,
        )
        take_profit_1, take_profit_2, realized_rr = select_darvas_targets(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_reward=self._config.risk_reward_1,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_target_multiplier,
        )

        reasons = [
            *setup.reasons,
            f"Current box: upper={box.upper:.6g} lower={box.lower:.6g}",
            f"Stop ({stop_source.value}): {stop_loss:.6g}",
            f"Target 1 (RR {realized_rr:g}): {take_profit_1:.6g}",
            f"Target 2 (ATR projection): {take_profit_2:.6g}",
            self._exit_note(features, entry_price, stop_loss, direction),
        ]

        plan = DarvasBoxPlan(
            strategy_name=self.name,
            symbol=self.active_symbol,
            entry_price=entry_price,
            direction=direction,
            signal=signal.signal,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confidence=signal.confidence,
            risk_reward=realized_rr,
            expected_holding_bars=self._config.session_bars,
            stop_source=stop_source,
            reasons=reasons,
            current_box=box,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "Darvas plan %s %s entry=%.4f stop=%.4f box=[%.4f, %.4f]",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            box.lower,
            box.upper,
        )
        return plan

    def _assess(self, features: pd.DataFrame) -> DarvasSetup:
        snapshot = self._cached_snapshot
        if snapshot is None:
            try:
                snapshot = self._boxes.detect(features)
            except DarvasBoxValidationError as exc:
                raise StrategyValidationError(str(exc)) from exc
            self._cached_snapshot = snapshot
        volume_stats = self._volume.snapshot(features)
        return assess_darvas_setup(
            snapshot=snapshot,
            volume_stats=volume_stats,
            ema_trend_bullish=ema_trend_bullish(
                features,
                config=self._config,
                conditions=self._conditions,
            ),
        )

    def _latest_atr(self, features: pd.DataFrame) -> float | None:
        if self._config.atr_column not in features.columns:
            return None
        values = pd.to_numeric(features[self._config.atr_column], errors="coerce").dropna()
        return float(values.iloc[-1]) if not values.empty else None

    def _timestamp(self, features: pd.DataFrame) -> datetime:
        return pd.Timestamp(features.iloc[-1][self._config.date_column]).to_pydatetime()

    def _exit_note(
        self,
        features: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
        direction: TradeDirection,
    ) -> str:
        close = float(features.iloc[-1][self._config.close_column])
        high = float(features.iloc[-1][self._config.high_column])
        low = float(features.iloc[-1][self._config.low_column])
        state = make_state(
            entry_price=entry_price,
            direction=direction,
            bars_held=self._config.session_bars,
            extreme_high=max(entry_price, high),
            extreme_low=min(entry_price, low),
        )
        decision = self._exits.evaluate(
            state=state,
            market=features,
            config=ExitConfig(
                initial_stop=stop_loss,
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        return f"Exit engine: {decision.reason} (mark={close:.6g})"
