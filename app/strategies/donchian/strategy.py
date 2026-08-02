"""Donchian Channel (Turtle Trading) strategy.

Channel math lives in ``app.services.strategy_engine.indicators.donchian`` —
reusable by future breakout strategies and Confluence. This module applies
EMA / volume / structure filters, cooldown, exits, and TradePlan math.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod
from app.market_structure import MarketStructureService
from app.market_structure.schemas import MarketStructureResult
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.indicators.donchian import (
    DonchianChannelService,
    DonchianSnapshot,
    DonchianValidationError,
)
from app.services.strategy_engine.indicators.volume_analysis import (
    VolumeAnalysisService,
    VolumeValidationError,
)
from app.strategies.donchian.config import DonchianStrategyConfig
from app.strategies.donchian.evaluation import (
    assess_donchian_setup,
    build_confidence,
    ema_trend_bullish,
    evaluate_donchian_exit,
    previous_swing_for_stop,
    select_donchian_stop,
    select_targets,
)
from app.strategies.donchian.schemas import (
    DonchianExitAssessment,
    DonchianPlan,
    DonchianSetup,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, TradePlan

logger = get_logger(__name__)


class DonchianStrategy(BaseStrategy):
    """Standalone Donchian / Turtle breakout strategy with reusable channel DI."""

    def __init__(
        self,
        config: DonchianStrategyConfig | None = None,
        *,
        donchian_service: DonchianChannelService | None = None,
        volume_service: VolumeAnalysisService | None = None,
        market_structure: MarketStructureResult | None = None,
        structure_service: MarketStructureService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or DonchianStrategyConfig()
        self._donchian = donchian_service or DonchianChannelService(
            entry_lookback=self._config.entry_lookback,
            exit_lookback=self._config.exit_lookback,
            high_column=self._config.high_column,
            low_column=self._config.low_column,
            close_column=self._config.close_column,
        )
        self._volume = volume_service or VolumeAnalysisService(
            volume_column=self._config.volume_column,
            relative_volume_20_column=self._config.relative_volume_column,
        )
        self._structure_override = market_structure
        self._structure_service = structure_service or MarketStructureService(
            swing_length=self._config.structure_swing_length,
        )
        self._conditions = condition_engine or ConditionEngine()
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                atr_column=self._config.atr_column,
                atr_multiplier=self._config.atr_exit_multiplier,
                trailing_atr_multiplier=self._config.atr_trail_multiplier,
                max_bars=self._config.expected_holding_bars,
                enabled_methods=(ExitMethod.TRAILING_STOP, ExitMethod.ATR_EXIT),
            ),
        )
        self._cached_structure: MarketStructureResult | None = None
        self._cached_snapshot: DonchianSnapshot | None = None
        self._last_detailed_plan: DonchianPlan | None = None
        self._last_setup: DonchianSetup | None = None
        self._last_exit: DonchianExitAssessment | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> DonchianStrategyConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> DonchianPlan | None:
        return self._last_detailed_plan

    @property
    def last_setup(self) -> DonchianSetup | None:
        return self._last_setup

    @property
    def last_exit_assessment(self) -> DonchianExitAssessment | None:
        return self._last_exit

    @property
    def last_donchian_snapshot(self) -> DonchianSnapshot | None:
        return self._cached_snapshot

    def bind_structure(self, structure: MarketStructureResult) -> DonchianStrategy:
        self._structure_override = structure
        self._cached_structure = structure
        return self

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
                f"Donchian strategy missing columns: {', '.join(missing)}",
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
            self._config.relative_volume_column,
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
            if self._config.relative_volume_column not in frame.columns:
                frame = self._volume.attach(frame)
            frame = self._donchian.attach(frame, overwrite=True)
            self._cached_snapshot = self._donchian.snapshot(frame)
        except (VolumeValidationError, DonchianValidationError) as exc:
            raise StrategyValidationError(str(exc)) from exc

        self._cached_structure = self._resolve_structure(frame)
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        self._last_setup = setup
        breakdown = build_confidence(setup, self._config.confidence_weights)
        return Signal(
            symbol=self.active_symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=breakdown.total / 100.0,
            reason="; ".join(setup.reasons) if setup.reasons else "Donchian hold",
        )

    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        detailed = self.generate_detailed_trade_plan(features, signal)
        self._last_detailed_plan = detailed
        # Foundation TradePlan requires take_profit fields; use RR target or entry proxy
        tp1 = detailed.take_profit_1
        tp2 = detailed.take_profit_2
        if tp1 is None:
            # Open trend-following: synthesize soft targets from stop distance
            risk = abs(detailed.entry_price - detailed.stop_loss)
            if detailed.direction is TradeDirection.LONG:
                tp1 = detailed.entry_price + risk * max(self._config.risk_reward_1, 1.0)
                tp2 = tp2 or detailed.entry_price + risk * max(self._config.risk_reward_1, 1.0) * 1.5
            else:
                tp1 = detailed.entry_price - risk * max(self._config.risk_reward_1, 1.0)
                tp2 = tp2 or detailed.entry_price - risk * max(self._config.risk_reward_1, 1.0) * 1.5
        if tp2 is None:
            tp2 = tp1
        return TradePlan(
            symbol=detailed.symbol,
            entry_price=detailed.entry_price,
            signal=detailed.signal,
            stop_loss=detailed.stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            holding_period=detailed.expected_holding_bars,
            risk_reward=detailed.risk_reward if detailed.risk_reward > 0 else self._config.risk_reward_1,
            confidence=detailed.confidence,
            reasons=detailed.reasons,
            strategy_name=detailed.strategy_name,
        )

    def generate_detailed_trade_plan(
        self,
        features: pd.DataFrame,
        signal: Signal | None = None,
    ) -> DonchianPlan:
        setup = self._assess(features)
        self._last_setup = setup
        structure = self._require_structure()
        breakdown = build_confidence(setup, self._config.confidence_weights)
        if signal is None:
            signal = Signal(
                symbol=self.active_symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=breakdown.total / 100.0,
                reason="; ".join(setup.reasons) if setup.reasons else "Donchian hold",
            )

        direction = setup.direction or TradeDirection.LONG
        entry_price = float(features.iloc[-1][self._config.close_column])
        atr_value = self._latest_atr(features)
        snapshot = setup.snapshot
        swing = previous_swing_for_stop(structure, direction=direction)
        stop_source, stop_loss = select_donchian_stop(
            direction=direction,
            entry_price=entry_price,
            middle=snapshot.middle,
            previous_swing=swing,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_stop_multiplier,
        )
        take_profit_1, take_profit_2, realized_rr, target_note = select_targets(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_reward=self._config.risk_reward_1,
            use_fixed_rr=self._config.use_fixed_risk_reward,
            snapshot=snapshot,
        )

        holding_note = (
            f"Swing / positional · Expected holding {self._config.min_holding_bars}–"
            f"{self._config.max_holding_bars} trading days"
        )
        reasons = [
            *setup.reasons,
            f"Upper channel: {snapshot.upper:.6g}",
            f"Lower channel: {snapshot.lower:.6g}",
            f"Middle channel: {snapshot.middle:.6g}",
            f"Entry channel [{snapshot.entry_lookback}]: "
            f"{snapshot.entry_lower:.6g} – {snapshot.entry_upper:.6g}",
            f"Stop ({stop_source.value}): {stop_loss:.6g}",
            target_note,
            holding_note,
            *breakdown.reasons,
        ]
        if take_profit_1 is not None:
            reasons.append(f"Target 1 (RR {realized_rr:g}): {take_profit_1:.6g}")
        if take_profit_2 is not None:
            reasons.append(f"Trailing Donchian reference: {take_profit_2:.6g}")

        plan = DonchianPlan(
            strategy_name=self.name,
            symbol=self.active_symbol,
            entry_price=entry_price,
            direction=direction,
            signal=signal.signal,
            upper_channel=snapshot.upper,
            lower_channel=snapshot.lower,
            middle_channel=snapshot.middle,
            entry_upper=snapshot.entry_upper,
            entry_lower=snapshot.entry_lower,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confidence=signal.confidence,
            risk_reward=realized_rr if realized_rr > 0 else self._config.risk_reward_1,
            expected_holding_bars=self._config.expected_holding_bars,
            holding_note=holding_note,
            stop_source=stop_source,
            target_note=target_note,
            reasons=reasons,
            market_structure=structure.trend,
            snapshot=snapshot,
            confidence_breakdown=breakdown,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "Donchian plan %s %s entry=%.4f stop=%.4f upper=%.4f lower=%.4f",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            plan.upper_channel,
            plan.lower_channel,
        )
        return plan

    def evaluate_exit(
        self,
        features: pd.DataFrame,
        *,
        direction: TradeDirection,
        entry_price: float,
        bars_held: int | None = None,
    ) -> DonchianExitAssessment:
        """Evaluate Turtle-style exits against the latest bar."""
        snapshot = self._cached_snapshot
        if snapshot is None:
            try:
                snapshot = self._donchian.snapshot(features)
            except DonchianValidationError as exc:
                raise StrategyValidationError(str(exc)) from exc
            self._cached_snapshot = snapshot
        structure = self._require_structure()
        atr_value = self._latest_atr(features)
        high = float(features.iloc[-1][self._config.high_column])
        low = float(features.iloc[-1][self._config.low_column])
        held = bars_held if bars_held is not None else self._config.expected_holding_bars
        assessment = evaluate_donchian_exit(
            direction=direction,
            snapshot=snapshot,
            structure=structure,
            entry_price=entry_price,
            atr_value=atr_value,
            config=self._config,
            features=features,
            exit_engine=self._exits,
            bars_held=held,
            extreme_high=max(entry_price, high),
            extreme_low=min(entry_price, low),
        )
        self._last_exit = assessment
        return assessment

    def _assess(self, features: pd.DataFrame) -> DonchianSetup:
        snapshot = self._cached_snapshot
        if snapshot is None:
            try:
                snapshot = self._donchian.snapshot(features)
            except DonchianValidationError as exc:
                raise StrategyValidationError(str(exc)) from exc
            self._cached_snapshot = snapshot

        volume_ok = False
        if self._config.relative_volume_column in features.columns:
            rvol = pd.to_numeric(
                features[self._config.relative_volume_column],
                errors="coerce",
            ).iloc[-1]
            volume_ok = bool(
                rvol is not None
                and not pd.isna(rvol)
                and float(rvol) > self._config.relative_volume_threshold
            )
        else:
            stats = self._volume.snapshot(features)
            volume_ok = self._volume.meets_relative_threshold(
                stats,
                threshold=self._config.relative_volume_threshold,
            )

        atr_value = self._latest_atr(features)
        atr_ok = atr_value is not None and atr_value > self._config.min_atr
        structure = self._require_structure()
        return assess_donchian_setup(
            snapshot=snapshot,
            structure=structure,
            ema_bullish=ema_trend_bullish(
                features,
                config=self._config,
                conditions=self._conditions,
            ),
            volume_ok=volume_ok,
            atr_ok=atr_ok,
            cooldown_bars=self._config.breakout_cooldown_bars,
        )

    def _resolve_structure(self, frame: pd.DataFrame) -> MarketStructureResult:
        if self._structure_override is not None:
            return self._structure_override
        return self._structure_service.analyze(frame, symbol=self.active_symbol)

    def _require_structure(self) -> MarketStructureResult:
        if self._cached_structure is None:
            raise StrategyValidationError(
                "Market structure not available; call prepare() or bind_structure()",
            )
        return self._cached_structure

    def _latest_atr(self, features: pd.DataFrame) -> float | None:
        if self._config.atr_column not in features.columns:
            return None
        values = pd.to_numeric(features[self._config.atr_column], errors="coerce").dropna()
        return float(values.iloc[-1]) if not values.empty else None

    def _timestamp(self, features: pd.DataFrame) -> datetime:
        return pd.Timestamp(features.iloc[-1][self._config.date_column]).to_pydatetime()
