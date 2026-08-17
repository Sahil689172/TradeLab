"""Strategy catalog and live analysis for the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from app.feature_engine.strategy_frame import ensure_strategy_indicators, load_strategy_features
from app.market_data.utils.symbols import parquet_basename
from app.services.dashboard.schemas import (
    AssumptionBias,
    CurrentAssumption,
    DashboardSignal,
    StrategyAnalysisResponse,
    StrategyCatalogItem,
    StrategySignalRow,
    TimeframeBestStrategy,
)
from app.services.dashboard.timeframes import get_timeframe, resample_ohlcv
from app.services.strategy_context import StrategyContextProvider
from app.services.strategy_context.schemas import ContextProviderConfig
from app.services.trade_recommendation.engine import TradeRecommendationEngine
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.services.trade_recommendation.strategy_validation import (
    StrategyValidationFramework,
    _ALL_REGISTRARS,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.models import SignalType
from app.strategy_engine.registry import StrategyRegistry
from app.strategy_engine.runner import StrategyRunner


STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    "ema_trend": "EMA Professional",
    "supertrend": "Supertrend",
    "break_retest": "Breakout",
    "momentum": "Momentum",
    "donchian": "Donchian Channel",
    "vwap": "VWAP",
    "opening_range_breakout": "Opening Range Breakout",
    "cpr": "CPR",
    "darvas_box": "Darvas Box",
    "previous_day_breakout": "Previous Day Breakout",
    "volume_breakout": "Volume Breakout",
    "relative_strength": "Relative Strength",
}


class StrategyAnalysisService:
    """Run registered strategies via existing context + recommendation engines."""

    def __init__(self) -> None:
        self._runner = StrategyRunner()

    def catalog(self) -> list[StrategyCatalogItem]:
        registry = StrategyRegistry()
        for register in _ALL_REGISTRARS:
            register(registry)
        items: list[StrategyCatalogItem] = []
        for name in sorted(registry.list()):
            items.append(
                StrategyCatalogItem(
                    name=name,
                    display_name=STRATEGY_DISPLAY_NAMES.get(name, name.replace("_", " ").title()),
                ),
            )
        return items

    def analyze(
        self,
        symbol: str,
        *,
        timeframe: str,
        storage_dir: str | None = None,
    ) -> StrategyAnalysisResponse:
        base = parquet_basename(symbol).upper()
        spec = get_timeframe(timeframe)
        generated_at = datetime.now(timezone.utc)
        if not spec.supported:
            return StrategyAnalysisResponse(
                symbol=base,
                timeframe=spec.code,
                generated_at=generated_at,
                strategies=[],
                timeframe_matrix=self._empty_matrix_message(spec.code, spec.reason),
                assumption=CurrentAssumption(
                    symbol=base,
                    timeframe=spec.code,
                    bias=AssumptionBias.NEUTRAL,
                    explanation=spec.reason,
                ),
                data_note=spec.reason,
            )

        features = self._load_features(base, spec.code, storage_dir=storage_dir)
        if features is None or features.empty:
            msg = "No feature/OHLCV data available for this symbol. Bootstrap or refresh first."
            return StrategyAnalysisResponse(
                symbol=base,
                timeframe=spec.code,
                generated_at=generated_at,
                strategies=[],
                timeframe_matrix=self._empty_matrix_message(spec.code, msg),
                assumption=CurrentAssumption(
                    symbol=base,
                    timeframe=spec.code,
                    bias=AssumptionBias.NEUTRAL,
                    explanation=msg,
                ),
                data_note=msg,
            )

        sample_size = len(features)
        evaluation_window = _evaluation_window(features)
        framework = StrategyValidationFramework(
            timeframe=spec.strategy_label,
            context_provider=StrategyContextProvider(
                ContextProviderConfig(timeframe=spec.strategy_label),
                runner=self._runner,
            ),
        )
        strategies = framework.resolve_strategies(["all"])
        rows: list[StrategySignalRow] = []
        for strategy in strategies:
            rows.append(
                self._evaluate_strategy(
                    strategy,
                    features,
                    symbol=base,
                    framework=framework,
                    timeframe=spec.code,
                    sample_size=sample_size,
                    evaluation_window=evaluation_window,
                    generated_at=generated_at,
                ),
            )

        matrix = self._timeframe_matrix(base, storage_dir=storage_dir)
        assumption = self._build_assumption(base, spec.code, rows, sample_size, evaluation_window, generated_at)
        return StrategyAnalysisResponse(
            symbol=base,
            timeframe=spec.code,
            generated_at=generated_at,
            strategies=rows,
            timeframe_matrix=matrix,
            assumption=assumption,
            data_note=(
                "Signals and confidence come from the latest bar of stored historical data. "
                "Confidence is Historical/Model Confidence (0–100), not probability of future profit."
            ),
        )

    def _evaluate_strategy(
        self,
        strategy: BaseStrategy,
        features: pd.DataFrame,
        *,
        symbol: str,
        framework: StrategyValidationFramework,
        timeframe: str,
        sample_size: int,
        evaluation_window: str,
        generated_at: datetime,
    ) -> StrategySignalRow:
        name = strategy.name
        display = STRATEGY_DISPLAY_NAMES.get(name, name.replace("_", " ").title())
        try:
            context = framework._context_provider.prepare(strategy, symbol, features=features)
            plan = strategy.execute(context)
            detailed = getattr(strategy, "last_detailed_plan", None)
            recommendation = framework._engine.recommend(
                plan,
                timeframe=framework._timeframe,
                detailed_plan=detailed,
                recompute_confidence=True,
            )
            signal = _dashboard_signal(recommendation)
            return StrategySignalRow(
                strategy=name,
                display_name=display,
                best_timeframe=timeframe,
                signal=signal,
                confidence=recommendation.confidence,
                strength=_strength_label(recommendation.confidence),
                status="OK",
                sample_size=sample_size,
                evaluation_window=evaluation_window,
                last_evaluated=generated_at,
                reasons=list(recommendation.reasons[:5]),
                warnings=list(recommendation.warnings),
            )
        except Exception as exc:
            return StrategySignalRow(
                strategy=name,
                display_name=display,
                best_timeframe=timeframe,
                signal=DashboardSignal.NEUTRAL,
                confidence=0.0,
                strength="N/A",
                status="ERROR",
                sample_size=sample_size,
                evaluation_window=evaluation_window,
                last_evaluated=generated_at,
                error=str(exc),
            )

    def _timeframe_matrix(self, symbol: str, *, storage_dir: str | None) -> list[TimeframeBestStrategy]:
        rows: list[TimeframeBestStrategy] = []
        for code in ("1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"):
            spec = get_timeframe(code)
            if not spec.supported:
                rows.append(
                    TimeframeBestStrategy(
                        interval=spec.code,
                        interval_label=spec.label,
                        supported=False,
                        message=spec.reason,
                    ),
                )
                continue
            partial = self.analyze(symbol, timeframe=spec.code, storage_dir=storage_dir)
            best = _pick_best_strategy(partial.strategies)
            rows.append(
                TimeframeBestStrategy(
                    interval=spec.code,
                    interval_label=spec.label,
                    supported=True,
                    best_strategy=best.strategy if best else None,
                    best_strategy_display=best.display_name if best else None,
                    signal=best.signal if best else DashboardSignal.NEUTRAL,
                    confidence=best.confidence if best else None,
                    supporting_metric=f"signal={best.signal.value}, confidence={best.confidence:.1f}" if best else "",
                    sample_size=best.sample_size if best else 0,
                    last_evaluated=best.last_evaluated if best else None,
                ),
            )
        return rows

    def _empty_matrix_message(self, timeframe: str, message: str) -> list[TimeframeBestStrategy]:
        return [
            TimeframeBestStrategy(
                interval=timeframe,
                interval_label=get_timeframe(timeframe).label,
                supported=False,
                message=message,
            ),
        ]

    def _load_features(
        self,
        symbol: str,
        timeframe: str,
        *,
        storage_dir: str | None,
    ) -> pd.DataFrame | None:
        from app.core.config import get_settings

        root = storage_dir or str(get_settings().parquet_storage_dir)
        try:
            frame = load_strategy_features(symbol, root, ensure_indicators=True)
        except Exception:
            return None
        if frame is None or frame.empty:
            return None
        spec = get_timeframe(timeframe)
        if spec.resample_rule and "date" in frame.columns:
            ohlcv_cols = [c for c in ("date", "open", "high", "low", "close", "volume") if c in frame.columns]
            if len(ohlcv_cols) >= 6:
                resampled = resample_ohlcv(frame[ohlcv_cols], rule=spec.resample_rule)
                resampled.attrs["symbol"] = symbol
                return ensure_strategy_indicators(resampled)
        frame = ensure_strategy_indicators(frame)
        frame.attrs["symbol"] = symbol
        return frame

    def _build_assumption(
        self,
        symbol: str,
        timeframe: str,
        rows: list[StrategySignalRow],
        sample_size: int,
        evaluation_window: str,
        generated_at: datetime,
    ) -> CurrentAssumption:
        actionable = [r for r in rows if r.status == "OK" and r.signal != DashboardSignal.NEUTRAL]
        buy = [r for r in actionable if r.signal is DashboardSignal.BUY]
        sell = [r for r in actionable if r.signal is DashboardSignal.SELL]
        if len(buy) > len(sell):
            bias = AssumptionBias.BULLISH
            supporters = buy
        elif len(sell) > len(buy):
            bias = AssumptionBias.BEARISH
            supporters = sell
        else:
            bias = AssumptionBias.NEUTRAL
            supporters = rows[:3]
        confidences = [r.confidence for r in supporters if r.confidence > 0]
        confidence = sum(confidences) / len(confidences) if confidences else None
        indicators: set[str] = set()
        for row in supporters:
            indicators.update(row.reasons[:2])
        return CurrentAssumption(
            symbol=symbol,
            timeframe=timeframe,
            bias=bias,
            confidence=confidence,
            supporting_strategies=[r.display_name for r in supporters[:5]],
            supporting_indicators=sorted(indicators)[:8],
            evaluation_window=evaluation_window,
            sample_size=sample_size,
            last_updated=generated_at,
            explanation=(
                f"Derived from {len(rows)} strategy evaluations on stored historical bars. "
                "Not a forecast of future profitability."
            ),
        )


def ensure_default_strategies_registered() -> StrategyRegistry:
    registry = StrategyRegistry()
    for register in _ALL_REGISTRARS:
        register(registry)
    return registry


def _dashboard_signal(recommendation: TradeRecommendation) -> DashboardSignal:
    if recommendation.signal is SignalType.BUY:
        return DashboardSignal.BUY
    if recommendation.signal in (SignalType.SELL, SignalType.EXIT):
        return DashboardSignal.SELL
    return DashboardSignal.NEUTRAL


def _strength_label(confidence: float) -> str:
    if confidence >= 75:
        return "Strong"
    if confidence >= 50:
        return "Moderate"
    if confidence > 0:
        return "Weak"
    return "N/A"


def _pick_best_strategy(rows: list[StrategySignalRow]) -> StrategySignalRow | None:
    candidates = [r for r in rows if r.status == "OK" and r.signal != DashboardSignal.NEUTRAL]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.confidence, r.strategy))


def _evaluation_window(frame: pd.DataFrame) -> str:
    if "date" not in frame.columns or frame.empty:
        return "unknown"
    start = frame["date"].iloc[0]
    end = frame["date"].iloc[-1]
    return f"{start} → {end}"


_strategy_service: StrategyAnalysisService | None = None


def get_strategy_service() -> StrategyAnalysisService:
    global _strategy_service
    if _strategy_service is None:
        _strategy_service = StrategyAnalysisService()
    return _strategy_service
