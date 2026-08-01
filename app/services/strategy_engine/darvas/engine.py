"""Reusable Darvas Box detection engine.

Classic Nicolas Darvas logic:
1. A new high that holds for ``confirm_bars`` becomes the Upper Box.
2. The subsequent swing low (lowest low while the top holds) becomes the Lower Box.
3. Price inside [lower, upper] is Consolidation.
4. Close above upper → Breakout; close below lower → Breakdown.
5. After a breakout, a New Box Formation cycle begins.

Future strategies should inject ``DarvasBoxEngine`` — do not reimplement detection.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.services.strategy_engine.darvas.schemas import (
    DarvasBox,
    DarvasBoxSnapshot,
    DarvasBoxState,
)


class DarvasBoxValidationError(ValueError):
    """Invalid inputs for Darvas box detection."""


@dataclass(frozen=True, slots=True)
class DarvasBoxEngineConfig:
    """Detector knobs (kept separate from strategy trade config)."""

    confirm_bars: int = 3
    min_box_bars: int = 2
    date_column: str = "date"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"

    def __post_init__(self) -> None:
        if self.confirm_bars < 1:
            raise DarvasBoxValidationError("confirm_bars must be >= 1")
        if self.min_box_bars < 1:
            raise DarvasBoxValidationError("min_box_bars must be >= 1")


class DarvasBoxEngine:
    """Injectable Darvas box detector for any OHLCV feature frame."""

    def __init__(self, config: DarvasBoxEngineConfig | None = None) -> None:
        self._config = config or DarvasBoxEngineConfig()

    @property
    def config(self) -> DarvasBoxEngineConfig:
        return self._config

    def detect(self, frame: pd.DataFrame) -> DarvasBoxSnapshot:
        """Detect the active Darvas box and latest state on the last bar."""
        self._validate_frame(frame)
        highs = pd.to_numeric(frame[self._config.high_column], errors="coerce")
        lows = pd.to_numeric(frame[self._config.low_column], errors="coerce")
        closes = pd.to_numeric(frame[self._config.close_column], errors="coerce")
        if highs.isna().any() or lows.isna().any() or closes.isna().any():
            raise DarvasBoxValidationError("OHLC columns must be numeric and non-null")

        dates = (
            pd.to_datetime(frame[self._config.date_column])
            if self._config.date_column in frame.columns
            else None
        )

        completed: list[DarvasBox] = []
        pending_top: float | None = None
        pending_top_index: int | None = None
        confirm_left = 0
        tracking_low: float | None = None
        tracking_low_index: int | None = None
        active: DarvasBox | None = None

        last_event: str | None = None  # breakout | breakdown | new_box
        event_box: DarvasBox | None = None

        n = len(frame)
        for index in range(n):
            high = float(highs.iloc[index])
            low = float(lows.iloc[index])
            close = float(closes.iloc[index])
            is_last = index == n - 1

            if active is not None:
                if close > active.upper:
                    completed.append(active)
                    if is_last:
                        last_event = "breakout"
                        event_box = active
                    # Start new top candidate after breakout
                    pending_top = high
                    pending_top_index = index
                    confirm_left = self._config.confirm_bars
                    tracking_low = low
                    tracking_low_index = index
                    active = None
                    continue
                if close < active.lower:
                    if is_last:
                        last_event = "breakdown"
                        event_box = active
                    # Box invalidated — restart formation from this bar
                    pending_top = high
                    pending_top_index = index
                    confirm_left = self._config.confirm_bars
                    tracking_low = low
                    tracking_low_index = index
                    active = None
                    continue
                # Still consolidating inside active box
                continue

            # Formation path (no active box)
            if pending_top is None:
                pending_top = high
                pending_top_index = index
                confirm_left = self._config.confirm_bars
                tracking_low = low
                tracking_low_index = index
                continue

            assert pending_top_index is not None
            assert tracking_low is not None
            assert tracking_low_index is not None

            if high > pending_top:
                pending_top = high
                pending_top_index = index
                confirm_left = self._config.confirm_bars
                tracking_low = low
                tracking_low_index = index
                continue

            if low < tracking_low:
                tracking_low = low
                tracking_low_index = index

            confirm_left -= 1
            bars_since_top = index - pending_top_index + 1
            if confirm_left <= 0 and bars_since_top >= self._config.min_box_bars:
                top_time = _bar_time(dates, pending_top_index)
                bottom_time = _bar_time(dates, tracking_low_index)
                active = DarvasBox(
                    upper=pending_top,
                    lower=tracking_low,
                    top_index=pending_top_index,
                    bottom_index=tracking_low_index,
                    formed_index=index,
                    top_time=top_time,
                    bottom_time=bottom_time,
                )
                pending_top = None
                pending_top_index = None
                tracking_low = None
                tracking_low_index = None
                confirm_left = 0
                if is_last:
                    last_event = "new_box"
                    event_box = active

        close = float(closes.iloc[-1])
        bar_index = n - 1
        prior = completed[-1] if completed else None

        if last_event == "breakout" and event_box is not None:
            return DarvasBoxSnapshot(
                state=DarvasBoxState.BREAKOUT,
                box=event_box,
                prior_box=prior if prior is not event_box else (
                    completed[-2] if len(completed) > 1 else None
                ),
                consolidating=False,
                breakout=True,
                breakdown=False,
                new_box_formation=True,
                close=close,
                bar_index=bar_index,
                reasons=[
                    f"Breakout: close {close:.6g} above upper box {event_box.upper:.6g}",
                    "New box formation started after breakout",
                ],
            )

        if last_event == "breakdown" and event_box is not None:
            return DarvasBoxSnapshot(
                state=DarvasBoxState.BREAKDOWN,
                box=event_box,
                prior_box=prior,
                consolidating=False,
                breakout=False,
                breakdown=True,
                new_box_formation=True,
                close=close,
                bar_index=bar_index,
                reasons=[
                    f"Breakdown: close {close:.6g} below lower box {event_box.lower:.6g}",
                ],
            )

        if last_event == "new_box" and active is not None:
            return DarvasBoxSnapshot(
                state=DarvasBoxState.NEW_BOX,
                box=active,
                prior_box=prior,
                consolidating=True,
                breakout=False,
                breakdown=False,
                new_box_formation=True,
                close=close,
                bar_index=bar_index,
                reasons=[
                    f"New box formation: upper={active.upper:.6g} lower={active.lower:.6g}",
                ],
            )

        if active is not None:
            consolidating = active.lower <= close <= active.upper
            return DarvasBoxSnapshot(
                state=DarvasBoxState.CONSOLIDATION,
                box=active,
                prior_box=prior,
                consolidating=consolidating,
                breakout=False,
                breakdown=False,
                new_box_formation=False,
                close=close,
                bar_index=bar_index,
                reasons=[
                    f"Consolidation inside [{active.lower:.6g}, {active.upper:.6g}]",
                ],
            )

        # Still forming
        if pending_top is not None and tracking_low is not None and pending_top_index is not None:
            provisional = DarvasBox(
                upper=pending_top,
                lower=tracking_low,
                top_index=pending_top_index,
                bottom_index=tracking_low_index or pending_top_index,
                formed_index=bar_index,
                top_time=_bar_time(dates, pending_top_index),
                bottom_time=_bar_time(dates, tracking_low_index or pending_top_index),
            )
            return DarvasBoxSnapshot(
                state=DarvasBoxState.FORMING,
                box=provisional,
                prior_box=prior,
                consolidating=False,
                breakout=False,
                breakdown=False,
                new_box_formation=True,
                close=close,
                bar_index=bar_index,
                reasons=["Darvas box still forming (awaiting top confirmation)"],
            )

        return DarvasBoxSnapshot(
            state=DarvasBoxState.FORMING,
            box=None,
            prior_box=prior,
            close=close,
            bar_index=bar_index,
            reasons=["No Darvas box detected yet"],
        )

    def _validate_frame(self, frame: pd.DataFrame) -> None:
        if not isinstance(frame, pd.DataFrame):
            raise DarvasBoxValidationError("frame must be a pandas DataFrame")
        if frame.empty:
            raise DarvasBoxValidationError("frame must not be empty")
        required = {
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
        }
        missing = sorted(column for column in required if column not in frame.columns)
        if missing:
            raise DarvasBoxValidationError(
                f"Darvas box missing columns: {', '.join(missing)}",
            )
        min_bars = self._config.confirm_bars + self._config.min_box_bars + 1
        if len(frame) < min_bars:
            raise DarvasBoxValidationError(
                f"Need at least {min_bars} bars for Darvas detection",
            )


def _bar_time(dates: pd.Series | None, index: int):
    if dates is None:
        return None
    return pd.Timestamp(dates.iloc[index]).to_pydatetime()
