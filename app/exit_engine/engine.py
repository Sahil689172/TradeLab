"""Exit engine — evaluate exit methods and return a typed decision."""

from __future__ import annotations

import pandas as pd

from app.core.logging import get_logger
from app.exit_engine.exceptions import ExitValidationError
from app.exit_engine.rules import (
    evaluate_atr_exit,
    evaluate_break_even,
    evaluate_ema_exit,
    evaluate_fixed_target,
    evaluate_partial_exit,
    evaluate_supertrend_exit,
    evaluate_time_exit,
    evaluate_trailing_stop,
)
from app.exit_engine.schemas import (
    ExitAction,
    ExitConfig,
    ExitDecision,
    ExitMethod,
    ExitSignal,
    TradeExitState,
)
from app.risk_engine.schemas import TradeDirection

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"

# Priority order when multiple methods trigger on the same bar.
_PRIORITY: tuple[ExitMethod, ...] = (
    ExitMethod.TIME_EXIT,
    ExitMethod.BREAK_EVEN,
    ExitMethod.TRAILING_STOP,
    ExitMethod.ATR_EXIT,
    ExitMethod.SUPERTREND_EXIT,
    ExitMethod.EMA_EXIT,
    ExitMethod.FIXED_TARGET,
    ExitMethod.PARTIAL_EXIT,
)


class ExitEngine:
    """Evaluate exit rules for an open trade and return an ``ExitDecision``.

    Supported methods:
        Fixed Target, ATR Exit, EMA Exit, SuperTrend Exit,
        Trailing Stop, Break Even, Partial Exit, Time Exit
    """

    def __init__(self, config: ExitConfig | None = None) -> None:
        self._config = config or ExitConfig()

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    @property
    def config(self) -> ExitConfig:
        return self._config

    def evaluate(
        self,
        *,
        state: TradeExitState,
        market: pd.DataFrame,
        config: ExitConfig | None = None,
    ) -> ExitDecision:
        """Return exit decision, exit price, and reason.

        Args:
            state: Open trade state (entry, direction, bars held, extremes).
            market: Price/feature history. Requires ``close``. Prefer ``high``/
                ``low`` plus feature columns ``atr_14`` / ``ema_21``.
            config: Optional per-call config override.
        """
        cfg = config or self._config
        frame = _normalize_market(market)
        close = float(frame["close"].iloc[-1])
        high = float(frame["high"].iloc[-1]) if "high" in frame.columns else close
        low = float(frame["low"].iloc[-1]) if "low" in frame.columns else close
        atr_value = _optional_latest(frame, cfg.atr_column)
        ema_value = _optional_latest(frame, cfg.ema_column)
        atr_series = (
            pd.to_numeric(frame[cfg.atr_column], errors="coerce")
            if cfg.atr_column in frame.columns
            else None
        )

        signals: list[ExitSignal] = []
        enabled = set(cfg.enabled_methods)

        if ExitMethod.TIME_EXIT in enabled:
            signals.append(evaluate_time_exit(state, close=close, config=cfg))
        if ExitMethod.FIXED_TARGET in enabled:
            signals.append(
                evaluate_fixed_target(state, close=close, high=high, low=low, config=cfg),
            )
        if ExitMethod.PARTIAL_EXIT in enabled:
            signals.append(
                evaluate_partial_exit(state, close=close, high=high, low=low, config=cfg),
            )
        if ExitMethod.BREAK_EVEN in enabled:
            signals.append(
                evaluate_break_even(state, close=close, high=high, low=low, config=cfg),
            )
        if ExitMethod.TRAILING_STOP in enabled:
            signals.append(
                evaluate_trailing_stop(
                    state,
                    close=close,
                    atr_value=atr_value,
                    config=cfg,
                ),
            )
        if ExitMethod.ATR_EXIT in enabled:
            if atr_value is None:
                signals.append(
                    ExitSignal(
                        method=ExitMethod.ATR_EXIT,
                        triggered=False,
                        reason=f"ATR column '{cfg.atr_column}' unavailable",
                    ),
                )
            else:
                signals.append(
                    evaluate_atr_exit(state, close=close, atr_value=atr_value, config=cfg),
                )
        if ExitMethod.EMA_EXIT in enabled:
            if ema_value is None:
                signals.append(
                    ExitSignal(
                        method=ExitMethod.EMA_EXIT,
                        triggered=False,
                        reason=f"EMA column '{cfg.ema_column}' unavailable",
                    ),
                )
            else:
                signals.append(
                    evaluate_ema_exit(state, close=close, ema_value=ema_value, config=cfg),
                )
        if ExitMethod.SUPERTREND_EXIT in enabled:
            signals.append(
                evaluate_supertrend_exit(state, frame, config=cfg, atr=atr_series),
            )

        decision = _select_decision(signals)
        logger.info(
            "Exit decision %s method=%s price=%s fraction=%.2f — %s",
            decision.decision.value,
            decision.method.value if decision.method else None,
            decision.exit_price,
            decision.exit_fraction,
            decision.reason,
        )
        return decision


def _select_decision(signals: list[ExitSignal]) -> ExitDecision:
    triggered = [signal for signal in signals if signal.triggered]
    if not triggered:
        return ExitDecision(
            decision=ExitAction.HOLD,
            exit_price=None,
            reason="No exit conditions triggered",
            method=None,
            exit_fraction=0.0,
            signals=signals,
        )

    priority_index = {method: index for index, method in enumerate(_PRIORITY)}
    triggered.sort(key=lambda signal: priority_index.get(signal.method, 999))
    chosen = triggered[0]

    if chosen.method is ExitMethod.PARTIAL_EXIT:
        action = ExitAction.PARTIAL_EXIT
    else:
        action = ExitAction.FULL_EXIT
        # Normalize full exits to fraction 1.0 even if signal carried another value.
        chosen = ExitSignal(
            method=chosen.method,
            triggered=True,
            exit_price=chosen.exit_price,
            exit_fraction=1.0,
            reason=chosen.reason,
        )

    return ExitDecision(
        decision=action,
        exit_price=chosen.exit_price,
        reason=chosen.reason,
        method=chosen.method,
        exit_fraction=chosen.exit_fraction,
        signals=signals,
    )


def _normalize_market(market: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(market, pd.DataFrame):
        raise TypeError(f"market must be a DataFrame, got {type(market).__name__}")
    if market.empty:
        raise ExitValidationError("market DataFrame must not be empty")
    if "close" not in market.columns:
        raise ExitValidationError("market DataFrame must contain a 'close' column")

    frame = market.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"])
        frame = (
            frame.drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
    for column in ("open", "high", "low", "close"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame["close"].isna().all():
        raise ExitValidationError("close column has no usable values")
    return frame


def _optional_latest(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        return None
    value = float(series.iloc[-1])
    return value if value > 0 else None


def make_state(
    *,
    entry_price: float,
    direction: TradeDirection | str,
    bars_held: int,
    extreme_high: float,
    extreme_low: float,
    remaining_fraction: float = 1.0,
    break_even_armed: bool = False,
) -> TradeExitState:
    """Convenience constructor accepting string directions."""
    if isinstance(direction, str):
        direction = TradeDirection(direction.strip().upper())
    return TradeExitState(
        entry_price=entry_price,
        direction=direction,
        bars_held=bars_held,
        extreme_high=extreme_high,
        extreme_low=extreme_low,
        remaining_fraction=remaining_fraction,
        break_even_armed=break_even_armed,
    )
