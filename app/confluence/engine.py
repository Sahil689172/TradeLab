"""Confluence engine — weighted multi-module scoring with explanations."""

from __future__ import annotations

import pandas as pd

from app.confluence.exceptions import ConfluenceValidationError
from app.confluence.schemas import (
    ConfluenceConfig,
    ConfluenceModule,
    ConfluenceResult,
    ConfluenceVerdict,
    ModuleScore,
    SignalContribution,
)
from app.confluence.scorers import (
    score_atr,
    score_ema,
    score_levels,
    score_rsi,
    score_signal_list,
    score_structure,
    score_trend,
    score_volume,
)
from app.core.logging import get_logger
from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"


class ConfluenceEngine:
    """Aggregate indicator, structure, volume, trend, and level evidence.

    Each enabled module returns a raw score in ``[-1, 1]``. Relative weights
    (default EMA 20, RSI 15, Volume 20, Structure 20, ATR 10, Levels 15, Trend 20)
    are normalized to 100 so the total score lies in ``[-100, 100]``.
    """

    def __init__(self, config: ConfluenceConfig | None = None) -> None:
        self._config = config or ConfluenceConfig()

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    @property
    def config(self) -> ConfluenceConfig:
        return self._config

    def evaluate(
        self,
        *,
        features: pd.DataFrame,
        market_structure: MarketStructureResult | None = None,
        levels: LevelsSnapshot | None = None,
        indicator_signals: list[SignalContribution] | None = None,
        price_action_signals: list[SignalContribution] | None = None,
        symbol: str | None = None,
        config: ConfluenceConfig | None = None,
    ) -> ConfluenceResult:
        """Return a confluence verdict with module scores and explanation."""
        cfg = config or self._config
        frame = _normalize_features(features, cfg)
        weights = cfg.weights.as_mapping()
        active = {module: weight for module, weight in weights.items() if weight > 0}
        weight_total = sum(active.values())
        if weight_total <= 0:
            raise ConfluenceValidationError("No positive module weights configured")

        price = None
        if cfg.close_column in frame.columns:
            series = pd.to_numeric(frame[cfg.close_column], errors="coerce").dropna()
            if not series.empty:
                price = float(series.iloc[-1])
        elif levels is not None:
            price = levels.reference_price

        raw_scores: dict[ConfluenceModule, tuple[float, str]] = {}
        if ConfluenceModule.EMA in active:
            raw_scores[ConfluenceModule.EMA] = score_ema(frame, cfg)
        if ConfluenceModule.RSI in active:
            raw_scores[ConfluenceModule.RSI] = score_rsi(frame, cfg)
        if ConfluenceModule.VOLUME in active:
            raw_scores[ConfluenceModule.VOLUME] = score_volume(frame, cfg)
        if ConfluenceModule.STRUCTURE in active:
            raw_scores[ConfluenceModule.STRUCTURE] = score_structure(market_structure)
        if ConfluenceModule.ATR in active:
            raw_scores[ConfluenceModule.ATR] = score_atr(frame, cfg)
        if ConfluenceModule.LEVELS in active:
            raw_scores[ConfluenceModule.LEVELS] = score_levels(levels, price=price, config=cfg)
        if ConfluenceModule.TREND in active:
            raw_scores[ConfluenceModule.TREND] = score_trend(frame, cfg)
        if ConfluenceModule.PRICE_ACTION in active:
            raw_scores[ConfluenceModule.PRICE_ACTION] = score_signal_list(
                price_action_signals,
                label="price-action signals",
            )
        if ConfluenceModule.INDICATOR_SIGNALS in active:
            raw_scores[ConfluenceModule.INDICATOR_SIGNALS] = score_signal_list(
                indicator_signals,
                label="indicator signals",
            )

        modules: list[ModuleScore] = []
        total = 0.0
        for module, weight in active.items():
            raw, reason = raw_scores[module]
            normalized_weight = (weight / weight_total) * 100.0
            contribution = normalized_weight * raw
            total += contribution
            modules.append(
                ModuleScore(
                    module=module,
                    weight=weight,
                    normalized_weight=round(normalized_weight, 4),
                    raw_score=round(raw, 4),
                    contribution=round(contribution, 4),
                    reason=reason,
                ),
            )

        total = float(max(-100.0, min(100.0, round(total, 4))))
        verdict = _verdict_from_score(total, cfg)
        explanation = _build_explanation(verdict, total, modules)

        result = ConfluenceResult(
            verdict=verdict,
            total_score=total,
            modules=modules,
            explanation=explanation,
            symbol=symbol.strip().upper() if symbol else None,
        )
        logger.info(
            "Confluence %s score=%.2f verdict=%s",
            result.symbol or "n/a",
            result.total_score,
            result.verdict.value,
        )
        return result


def _verdict_from_score(total: float, config: ConfluenceConfig) -> ConfluenceVerdict:
    thresholds = config.thresholds
    if total >= thresholds.strong_buy:
        return ConfluenceVerdict.STRONG_BUY
    if total >= thresholds.buy:
        return ConfluenceVerdict.BUY
    if total <= thresholds.strong_sell:
        return ConfluenceVerdict.STRONG_SELL
    if total <= thresholds.sell:
        return ConfluenceVerdict.SELL
    return ConfluenceVerdict.HOLD


def _build_explanation(
    verdict: ConfluenceVerdict,
    total: float,
    modules: list[ModuleScore],
) -> str:
    ranked = sorted(modules, key=lambda item: abs(item.contribution), reverse=True)
    top = ranked[:4]
    parts = [
        f"Verdict {verdict.value} from total score {total:.2f}/100.",
        "Module contributions (normalized weights):",
    ]
    for item in modules:
        parts.append(
            f"- {item.module.value}: raw={item.raw_score:+.2f}, "
            f"weight={item.normalized_weight:.1f}, contribution={item.contribution:+.2f} "
            f"({item.reason})",
        )
    if top:
        drivers = ", ".join(
            f"{item.module.value} ({item.contribution:+.1f})" for item in top if item.contribution != 0
        )
        if drivers:
            parts.append(f"Primary drivers: {drivers}.")
    return "\n".join(parts)


def _normalize_features(features: pd.DataFrame, config: ConfluenceConfig) -> pd.DataFrame:
    if not isinstance(features, pd.DataFrame):
        raise TypeError(f"features must be a DataFrame, got {type(features).__name__}")
    if features.empty:
        raise ConfluenceValidationError("features must not be empty")

    frame = features.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"])
        frame = (
            frame.drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )

    # Feature-engine frames include OHLCV + indicators (pipeline keeps source columns).
    required_any = {
        config.ema_fast_column,
        config.ema_slow_column,
        config.rsi_column,
    }
    missing_core = [column for column in required_any if column not in frame.columns]
    if missing_core:
        raise ConfluenceValidationError(
            f"features missing required columns: {', '.join(missing_core)}",
        )
    return frame
