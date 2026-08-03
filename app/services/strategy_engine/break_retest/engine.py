"""Break & Retest sequence engine — reusable across strategies."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.conditions import ConditionEngine
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.break_retest.detection import (
    detect_break,
    detect_confirmation_candle,
    detect_failed_retest,
    detect_retest,
    make_break_event,
    make_retest_event,
    resolve_break_level,
)
from app.services.strategy_engine.break_retest.schemas import (
    BreakRetestSequence,
    BreakRetestStage,
)


class BreakRetestValidationError(ValueError):
    """Invalid inputs for break/retest scanning."""


@dataclass(frozen=True, slots=True)
class BreakRetestEngineConfig:
    """Detector knobs shared by any consumer strategy."""

    lookback: int = 20
    retest_tolerance_pct: float = 0.0015
    min_body_ratio: float = 0.4
    level_exclude_tail: int = 3
    open_column: str = "open"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"

    def __post_init__(self) -> None:
        if self.lookback < 3:
            raise BreakRetestValidationError("lookback must be >= 3")
        if self.min_body_ratio <= 0 or self.min_body_ratio >= 1:
            raise BreakRetestValidationError("min_body_ratio must be in (0, 1)")
        if self.level_exclude_tail < 1:
            raise BreakRetestValidationError("level_exclude_tail must be >= 1")


class BreakRetestEngine:
    """Scan a frame for break → retest → confirmation sequences.

    Future strategies should inject this engine rather than reimplementing
    break/retest/confirmation logic.
    """

    def __init__(
        self,
        config: BreakRetestEngineConfig | None = None,
        *,
        condition_engine: ConditionEngine | None = None,
    ) -> None:
        self._config = config or BreakRetestEngineConfig()
        self._conditions = condition_engine or ConditionEngine()

    @property
    def config(self) -> BreakRetestEngineConfig:
        return self._config

    def scan(
        self,
        frame: pd.DataFrame,
        *,
        direction: TradeDirection,
        level: float | None = None,
        _arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
    ) -> BreakRetestSequence:
        """Scan for a long (resistance) or short (support) break/retest sequence."""
        self._validate(frame)
        resolved = level
        if resolved is None:
            resolved = resolve_break_level(
                frame,
                direction=direction,
                lookback=self._config.lookback,
                high_column=self._config.high_column,
                low_column=self._config.low_column,
                exclude_tail=self._config.level_exclude_tail,
            )
        if resolved is None or resolved <= 0:
            return BreakRetestSequence(
                direction=direction,
                stage=BreakRetestStage.NONE,
                level=0.0,
                reasons=["Unable to resolve break level"],
            )

        if _arrays is None:
            opens, highs, lows, closes = self._extract_arrays(frame)
        else:
            opens, highs, lows, closes = _arrays

        tolerance = abs(resolved) * self._config.retest_tolerance_pct
        broken = False
        retested = False
        failed = False
        break_event = None
        retest_event = None
        reasons: list[str] = []
        n = len(closes)

        for index in range(1, n):
            prev_close = float(closes[index - 1])
            close = float(closes[index])
            high = float(highs[index])
            low = float(lows[index])

            if not broken:
                if detect_break(
                    previous_close=prev_close,
                    current_close=close,
                    level=resolved,
                    direction=direction,
                    conditions=self._conditions,
                ):
                    broken = True
                    break_event = make_break_event(
                        direction=direction,
                        level=resolved,
                        bar_index=index,
                        close=close,
                    )
                continue

            if broken and not retested and not failed:
                if detect_failed_retest(close=close, level=resolved, direction=direction):
                    # Ignore same-bar noise right after break; fail only after break bar
                    if break_event is not None and index > break_event.bar_index:
                        failed = True
                        retest_event = make_retest_event(
                            direction=direction,
                            level=resolved,
                            bar_index=index,
                            low=low,
                            high=high,
                            successful=False,
                        )
                        reasons.append(
                            f"Failed retest: close {close:.6g} back through level {resolved:.6g}",
                        )
                    continue

                if detect_retest(
                    low=low,
                    high=high,
                    close=close,
                    level=resolved,
                    direction=direction,
                    conditions=self._conditions,
                    tolerance=tolerance,
                ):
                    retested = True
                    retest_event = make_retest_event(
                        direction=direction,
                        level=resolved,
                        bar_index=index,
                        low=low,
                        high=high,
                        successful=True,
                    )

        confirmation = detect_confirmation_candle(
            open_=float(opens[-1]),
            high=float(highs[-1]),
            low=float(lows[-1]),
            close=float(closes[-1]),
            previous_close=float(closes[-2]),
            direction=direction,
            min_body_ratio=self._config.min_body_ratio,
        )

        # Break without a successful retest (still on the break side) = false breakout.
        false_breakout = bool(broken and not retested and not failed)

        if failed:
            stage = BreakRetestStage.FAILED_RETEST
        elif broken and retested and confirmation.confirmed:
            stage = BreakRetestStage.CONFIRMED
            reasons = [
                f"{'Resistance' if direction is TradeDirection.LONG else 'Support'} "
                f"{resolved:.6g} broken",
                "Successful retest",
                "Confirmation candle present",
            ]
        elif broken and retested:
            stage = BreakRetestStage.RETESTED
            reasons.append("Retest complete; waiting for confirmation candle")
        elif broken:
            stage = BreakRetestStage.BROKEN
            reasons.append("Level broken; waiting for retest")
        else:
            stage = BreakRetestStage.NONE
            reasons.append("No break detected")

        return BreakRetestSequence(
            direction=direction,
            stage=stage,
            level=resolved,
            break_event=break_event,
            retest_event=retest_event,
            confirmation=confirmation,
            false_breakout=false_breakout,
            reasons=reasons,
        )

    def scan_both(
        self,
        frame: pd.DataFrame,
        *,
        resistance: float | None = None,
        support: float | None = None,
    ) -> tuple[BreakRetestSequence, BreakRetestSequence]:
        """Scan long and short sequences in one call (shared OHLCV arrays)."""
        self._validate(frame)
        arrays = self._extract_arrays(frame)
        long_seq = self.scan(
            frame,
            direction=TradeDirection.LONG,
            level=resistance,
            _arrays=arrays,
        )
        short_seq = self.scan(
            frame,
            direction=TradeDirection.SHORT,
            level=support,
            _arrays=arrays,
        )
        return long_seq, short_seq

    def _extract_arrays(
        self,
        frame: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        opens = np.asarray(
            pd.to_numeric(frame[self._config.open_column], errors="coerce"),
            dtype=np.float64,
        )
        highs = np.asarray(
            pd.to_numeric(frame[self._config.high_column], errors="coerce"),
            dtype=np.float64,
        )
        lows = np.asarray(
            pd.to_numeric(frame[self._config.low_column], errors="coerce"),
            dtype=np.float64,
        )
        closes = np.asarray(
            pd.to_numeric(frame[self._config.close_column], errors="coerce"),
            dtype=np.float64,
        )
        return opens, highs, lows, closes

    def _validate(self, frame: pd.DataFrame) -> None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise BreakRetestValidationError("frame must be a non-empty DataFrame")
        required = {
            self._config.open_column,
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
        }
        missing = sorted(column for column in required if column not in frame.columns)
        if missing:
            raise BreakRetestValidationError(
                f"Break/retest missing columns: {', '.join(missing)}",
            )
        if len(frame) < self._config.lookback + 2:
            raise BreakRetestValidationError(
                f"Need at least {self._config.lookback + 2} bars",
            )
