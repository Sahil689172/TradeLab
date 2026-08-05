"""Daily VWAP strategy.

Price vs session VWAP with slope, relative volume, structure, and
retest/rejection confirmation. VWAP math lives in
``app.services.strategy_engine.indicators.vwap`` — not here.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.indicator_adapter import IndicatorAdapter, IndicatorAdapterError
from app.levels.exceptions import LevelsValidationError
from app.levels.schemas import LevelsSnapshot
from app.levels.service import LevelsService
from app.market_structure import MarketStructureService
from app.market_structure.schemas import MarketStructureResult
from app.risk_engine.schemas import TradeDirection
from app.risk_engine.stops import take_profit_from_risk
from app.services.strategy_engine.indicators.vwap import (
    VWAPService,
    VWAPSnapshot,
    VWAPValidationError,
)
from app.strategies.vwap.config import VWAPStrategyConfig
from app.strategies.vwap.evaluation import (
    assess_vwap_setup,
    build_confidence,
    select_take_profit_2,
    select_vwap_stop,
)
from app.strategies.vwap.schemas import VWAPSetupAssessment, VWAPTradePlan
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.filters.strategy_profiles import STRATEGY_FILTER_PROFILES
from app.strategy_engine.models import Signal, TradePlan

logger = get_logger(__name__)


class VWAPStrategy(BaseStrategy):
    """Standalone Daily VWAP strategy (intraday only)."""

    FILTER_PROFILE = STRATEGY_FILTER_PROFILES["vwap"]

    def __init__(
        self,
        config: VWAPStrategyConfig | None = None,
        *,
        vwap_service: VWAPService | None = None,
        market_structure: MarketStructureResult | None = None,
        levels: LevelsSnapshot | None = None,
        structure_service: MarketStructureService | None = None,
        levels_service: LevelsService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or VWAPStrategyConfig()
        self._vwap = vwap_service or VWAPService(
            mode=self._config.vwap_mode,
            slope_lookback=self._config.slope_lookback,
            date_column=self._config.date_column,
            high_column=self._config.high_column,
            low_column=self._config.low_column,
            close_column=self._config.close_column,
            volume_column=self._config.volume_column,
            vwap_column=self._config.vwap_column,
            slope_column=self._config.slope_column,
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
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        self._cached_structure: MarketStructureResult | None = None
        self._cached_levels: LevelsSnapshot | None = None
        self._cached_vwap: VWAPSnapshot | None = None
        self._last_detailed_plan: VWAPTradePlan | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> VWAPStrategyConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> VWAPTradePlan | None:
        return self._last_detailed_plan

    def bind_structure(self, structure: MarketStructureResult) -> VWAPStrategy:
        self._structure_override = structure
        self._cached_structure = structure
        return self

    def bind_levels(self, levels: LevelsSnapshot) -> VWAPStrategy:
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
            self._config.open_column,
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
            self._config.relative_volume_column,
        }
        has_vwap = self._config.vwap_column in features.columns
        if not has_vwap:
            required.add(self._config.volume_column)

        missing = sorted(column for column in required if column not in features.columns)
        if missing:
            raise StrategyValidationError(
                f"VWAP strategy missing columns: {', '.join(missing)}",
            )
        if len(features) < self._config.min_history_bars:
            raise StrategyValidationError(
                f"Need at least {self._config.min_history_bars} bars for VWAP strategy",
            )

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        frame = features.copy()
        frame[self._config.date_column] = pd.to_datetime(frame[self._config.date_column])
        for column in (
            self._config.open_column,
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
            self._config.relative_volume_column,
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if self._config.volume_column in frame.columns:
            frame[self._config.volume_column] = pd.to_numeric(
                frame[self._config.volume_column],
                errors="coerce",
            )
        if self._config.atr_column in frame.columns:
            frame[self._config.atr_column] = pd.to_numeric(
                frame[self._config.atr_column],
                errors="coerce",
            )

        subset = [
            self._config.open_column,
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
            self._config.relative_volume_column,
        ]
        frame = (
            frame.dropna(subset=subset)
            .drop_duplicates(subset=[self._config.date_column], keep="last")
            .sort_values(self._config.date_column)
            .reset_index(drop=True)
        )

        try:
            frame = self._vwap.attach(frame)
            self._cached_vwap = self._vwap.snapshot(frame)
        except VWAPValidationError as exc:
            raise StrategyValidationError(str(exc)) from exc

        self._cached_structure = self._resolve_structure(frame)
        self._cached_levels = self._resolve_levels(frame)
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        confidence = build_confidence(setup, self._config.confidence_weights).total / 100.0
        return Signal(
            symbol=self.active_symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=confidence,
            reason="; ".join(setup.reasons) if setup.reasons else "VWAP hold",
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
    ) -> VWAPTradePlan:
        vwap = self._require_vwap()
        structure = self._require_structure()
        setup = self._assess(features)
        if signal is None:
            signal = Signal(
                symbol=self.active_symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=build_confidence(setup, self._config.confidence_weights).total / 100.0,
                reason="; ".join(setup.reasons) if setup.reasons else "VWAP hold",
            )

        entry_price = float(features.iloc[-1][self._config.close_column])
        direction = setup.direction or TradeDirection.LONG
        atr_value = self._latest_atr(features)
        swing = (
            structure.last_swing_low.price
            if direction is TradeDirection.LONG and structure.last_swing_low is not None
            else structure.last_swing_high.price
            if direction is TradeDirection.SHORT and structure.last_swing_high is not None
            else None
        )
        stop_source, stop_loss = select_vwap_stop(
            direction=direction,
            entry_price=entry_price,
            vwap_value=vwap.value,
            previous_swing=swing,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_stop_multiplier,
        )
        take_profit_1, realized_rr = take_profit_from_risk(
            entry_price,
            stop_loss,
            direction,
            self._config.risk_reward_1,
        )
        take_profit_2, target_2_label = select_take_profit_2(
            direction=direction,
            entry_price=entry_price,
            levels=self._cached_levels,
            take_profit_1=take_profit_1,
        )
        if direction is TradeDirection.LONG and take_profit_2 <= take_profit_1:
            take_profit_2 = take_profit_1 + abs(entry_price - stop_loss) * 0.5
            target_2_label = f"{target_2_label} (adjusted above TP1)"
        if direction is TradeDirection.SHORT and take_profit_2 >= take_profit_1:
            take_profit_2 = take_profit_1 - abs(entry_price - stop_loss) * 0.5
            target_2_label = f"{target_2_label} (adjusted below TP1)"

        confidence_breakdown = build_confidence(setup, self._config.confidence_weights)
        exit_note = self._intraday_exit_note(features, entry_price, stop_loss, direction)
        reasons = [
            *setup.reasons,
            f"Daily VWAP={vwap.value:.6g} slope={vwap.slope:.6g}",
            f"Stop ({stop_source.value}): {stop_loss:.6g}",
            f"Target 1 (RR {realized_rr:g}): {take_profit_1:.6g}",
            f"Target 2 ({target_2_label}): {take_profit_2:.6g}",
            f"Market structure: {structure.trend.value}",
            *confidence_breakdown.reasons,
            exit_note,
            "Holding: intraday only — exit before market close",
        ]

        plan = VWAPTradePlan(
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
            target_2_label=target_2_label,
            reasons=reasons,
            market_structure=structure.trend,
            vwap=vwap,
            vwap_mode=self._config.vwap_mode,
            confidence_breakdown=confidence_breakdown,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "VWAP plan %s %s entry=%.4f stop=%.4f tp1=%.4f tp2=%.4f conf=%.3f",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            plan.take_profit_1,
            plan.take_profit_2,
            plan.confidence,
        )
        return plan

    def _assess(self, features: pd.DataFrame) -> VWAPSetupAssessment:
        structure = self._require_structure()
        return assess_vwap_setup(
            features,
            config=self._config,
            structure=structure,
            conditions=self._conditions,
        )

    def _resolve_structure(self, frame: pd.DataFrame) -> MarketStructureResult:
        if self._structure_override is not None:
            return self._structure_override
        structure_frame = frame.copy()
        if "volume" not in structure_frame.columns:
            structure_frame["volume"] = (
                pd.to_numeric(
                    structure_frame[self._config.relative_volume_column],
                    errors="coerce",
                )
                .fillna(1.0)
                .clip(lower=1.0)
                * 1_000
            ).astype("int64")
        return self._structure_service.analyze(structure_frame, symbol=self.active_symbol)

    def _resolve_levels(self, frame: pd.DataFrame) -> LevelsSnapshot | None:
        if self._levels_override is not None:
            return self._levels_override
        if self._levels_service is None:
            return None
        levels_frame = frame.copy()
        if "volume" not in levels_frame.columns and self._config.volume_column in levels_frame.columns:
            levels_frame["volume"] = levels_frame[self._config.volume_column]
        try:
            return self._levels_service.compute(levels_frame, symbol=self.active_symbol)
        except LevelsValidationError as exc:
            logger.debug("Levels unavailable for VWAP TP2: %s", exc)
            return None

    def _require_vwap(self) -> VWAPSnapshot:
        if self._cached_vwap is None:
            raise StrategyValidationError("VWAP not prepared — call prepare() first")
        return self._cached_vwap

    def _require_structure(self) -> MarketStructureResult:
        if self._cached_structure is None:
            raise StrategyValidationError("Structure not prepared — call prepare() first")
        return self._cached_structure

    def _latest_atr(self, features: pd.DataFrame) -> float | None:
        if self._config.atr_column not in features.columns:
            return None
        values = pd.to_numeric(features[self._config.atr_column], errors="coerce").dropna()
        if values.empty:
            return None
        try:
            adapter = IndicatorAdapter(features)
            latest = adapter.indicator("atr").latest_value
            return latest if latest is not None else float(values.iloc[-1])
        except IndicatorAdapterError:
            return float(values.iloc[-1])

    def _timestamp(self, features: pd.DataFrame) -> datetime:
        return pd.Timestamp(features.iloc[-1][self._config.date_column]).to_pydatetime()

    def _intraday_exit_note(
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
