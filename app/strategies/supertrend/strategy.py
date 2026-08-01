"""SuperTrend strategy.

SuperTrend math lives in ``app.services.strategy_engine.indicators.supertrend`` —
reusable by Exit Engine, Confluence, and future Strategy Builder. This module
only applies EMA / volume / structure filters and TradePlan math.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.levels.exceptions import LevelsValidationError
from app.levels.schemas import LevelsSnapshot
from app.levels.service import LevelsService
from app.market_structure import MarketStructureService
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.indicators.supertrend import (
    SuperTrendService,
    SuperTrendSnapshot,
    SuperTrendValidationError,
)
from app.services.strategy_engine.indicators.volume_analysis import (
    VolumeAnalysisService,
    VolumeValidationError,
)
from app.strategies.supertrend.config import SuperTrendStrategyConfig
from app.strategies.supertrend.evaluation import (
    assess_supertrend_setup,
    build_confidence,
    ema_trend_bullish,
    previous_swing_for_stop,
    select_supertrend_stop,
    select_targets,
)
from app.strategies.supertrend.schemas import SuperTrendPlan, SuperTrendSetup
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, TradePlan

logger = get_logger(__name__)


class SuperTrendStrategy(BaseStrategy):
    """Standalone SuperTrend trend-flip strategy with reusable indicator DI."""

    def __init__(
        self,
        config: SuperTrendStrategyConfig | None = None,
        *,
        supertrend_service: SuperTrendService | None = None,
        volume_service: VolumeAnalysisService | None = None,
        market_structure: MarketStructureResult | None = None,
        levels: LevelsSnapshot | None = None,
        structure_service: MarketStructureService | None = None,
        levels_service: LevelsService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or SuperTrendStrategyConfig()
        self._supertrend = supertrend_service or SuperTrendService(
            atr_period=self._config.atr_period,
            multiplier=self._config.atr_multiplier,
            high_column=self._config.high_column,
            low_column=self._config.low_column,
            close_column=self._config.close_column,
            atr_column=None,
            supertrend_column=self._config.supertrend_column,
            direction_column=self._config.supertrend_direction_column,
        )
        self._volume = volume_service or VolumeAnalysisService(
            volume_column=self._config.volume_column,
            relative_volume_20_column=self._config.relative_volume_column,
        )
        self._structure_override = market_structure
        self._levels_override = levels
        self._structure_service = structure_service or MarketStructureService(
            swing_length=self._config.structure_swing_length,
        )
        self._levels_service = levels_service
        self._conditions = condition_engine or ConditionEngine()
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                max_bars=self._config.expected_holding_bars,
                enabled_methods=(ExitMethod.TIME_EXIT, ExitMethod.SUPERTREND_EXIT),
                supertrend_period=self._config.atr_period,
                supertrend_multiplier=self._config.atr_multiplier,
            ),
        )
        self._cached_structure: MarketStructureResult | None = None
        self._cached_levels: LevelsSnapshot | None = None
        self._cached_snapshot: SuperTrendSnapshot | None = None
        self._last_detailed_plan: SuperTrendPlan | None = None
        self._last_setup: SuperTrendSetup | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> SuperTrendStrategyConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> SuperTrendPlan | None:
        return self._last_detailed_plan

    @property
    def last_setup(self) -> SuperTrendSetup | None:
        return self._last_setup

    @property
    def last_supertrend_snapshot(self) -> SuperTrendSnapshot | None:
        return self._cached_snapshot

    def bind_structure(self, structure: MarketStructureResult) -> SuperTrendStrategy:
        self._structure_override = structure
        self._cached_structure = structure
        return self

    def bind_levels(self, levels: LevelsSnapshot) -> SuperTrendStrategy:
        self._levels_override = levels
        self._cached_levels = levels
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
                f"SuperTrend strategy missing columns: {', '.join(missing)}",
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
            frame = self._supertrend.attach(frame, overwrite=True)
            self._cached_snapshot = self._supertrend.snapshot(frame)
        except (VolumeValidationError, SuperTrendValidationError) as exc:
            raise StrategyValidationError(str(exc)) from exc

        self._cached_structure = self._resolve_structure(frame)
        self._cached_levels = self._resolve_levels(frame)
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        self._last_setup = setup
        breakdown = build_confidence(setup, self._config.confidence_weights)
        return Signal(
            symbol=self._config.symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=breakdown.total / 100.0,
            reason="; ".join(setup.reasons) if setup.reasons else "SuperTrend hold",
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
    ) -> SuperTrendPlan:
        setup = self._assess(features)
        self._last_setup = setup
        structure = self._require_structure()
        breakdown = build_confidence(setup, self._config.confidence_weights)
        if signal is None:
            signal = Signal(
                symbol=self._config.symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=breakdown.total / 100.0,
                reason="; ".join(setup.reasons) if setup.reasons else "SuperTrend hold",
            )

        direction = setup.direction or TradeDirection.LONG
        entry_price = float(features.iloc[-1][self._config.close_column])
        atr_value = self._latest_atr(features)
        snapshot = setup.snapshot
        swing = previous_swing_for_stop(structure, direction=direction)
        stop_source, stop_loss = select_supertrend_stop(
            direction=direction,
            entry_price=entry_price,
            supertrend_value=snapshot.value,
            previous_swing=swing,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_stop_multiplier,
        )
        take_profit_1, take_profit_2, realized_rr, target_label = select_targets(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_reward=self._config.risk_reward_1,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_target_multiplier,
            levels=self._cached_levels,
        )

        trend_direction = (
            TrendDirection.BULLISH
            if snapshot.bullish
            else TrendDirection.BEARISH
            if snapshot.bearish
            else structure.trend
        )
        holding_note = (
            f"Swing · Expected holding {self._config.min_holding_bars}–"
            f"{self._config.max_holding_bars} trading days"
        )
        reasons = [
            *setup.reasons,
            f"Trend direction: {trend_direction.value}",
            f"SuperTrend line: {snapshot.value:.6g}",
            f"Stop ({stop_source.value}): {stop_loss:.6g}",
            f"Target 1 (RR {realized_rr:g}): {take_profit_1:.6g}",
            f"Target 2 ({target_label}): {take_profit_2:.6g}",
            holding_note,
            *breakdown.reasons,
            self._exit_note(features, entry_price, stop_loss, direction),
        ]

        plan = SuperTrendPlan(
            strategy_name=self.name,
            symbol=self._config.symbol,
            entry_price=entry_price,
            direction=direction,
            signal=signal.signal,
            trend_direction=trend_direction,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confidence=signal.confidence,
            risk_reward=realized_rr,
            expected_holding_bars=self._config.expected_holding_bars,
            holding_note=holding_note,
            stop_source=stop_source,
            target_2_label=target_label,
            reasons=reasons,
            market_structure=structure.trend,
            snapshot=snapshot,
            confidence_breakdown=breakdown,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "SuperTrend plan %s %s entry=%.4f stop=%.4f dir=%s",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            plan.trend_direction.value,
        )
        return plan

    def _assess(self, features: pd.DataFrame) -> SuperTrendSetup:
        snapshot = self._cached_snapshot
        if snapshot is None:
            try:
                snapshot = self._supertrend.snapshot(features)
            except SuperTrendValidationError as exc:
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
        return assess_supertrend_setup(
            snapshot=snapshot,
            structure=structure,
            ema_bullish=ema_trend_bullish(
                features,
                config=self._config,
                conditions=self._conditions,
            ),
            volume_ok=volume_ok,
            atr_ok=atr_ok,
        )

    def _resolve_structure(self, frame: pd.DataFrame) -> MarketStructureResult:
        if self._structure_override is not None:
            return self._structure_override
        return self._structure_service.analyze(frame, symbol=self._config.symbol)

    def _resolve_levels(self, frame: pd.DataFrame) -> LevelsSnapshot | None:
        if self._levels_override is not None:
            return self._levels_override
        if self._levels_service is None:
            return None
        try:
            return self._levels_service.compute(frame, symbol=self._config.symbol)
        except LevelsValidationError:
            return None

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
            bars_held=self._config.expected_holding_bars,
            extreme_high=max(entry_price, high),
            extreme_low=min(entry_price, low),
        )
        decision = self._exits.evaluate(
            state=state,
            market=features,
            config=ExitConfig(
                initial_stop=stop_loss,
                max_bars=self._config.expected_holding_bars,
                enabled_methods=(ExitMethod.TIME_EXIT, ExitMethod.SUPERTREND_EXIT),
                supertrend_period=self._config.atr_period,
                supertrend_multiplier=self._config.atr_multiplier,
            ),
        )
        return f"Exit engine: {decision.reason} (mark={close:.6g})"
