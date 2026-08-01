"""Reusable Donchian Channel calculator for Turtle-style breakout strategies.

Exposes upper / middle / lower bands, entry vs exit lookbacks, and breakout
status for strategies, Confluence, and future Strategy Builder consumers.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class DonchianValidationError(ValueError):
    """Invalid inputs for Donchian Channel computation."""


class DonchianSnapshot(BaseModel):
    """Latest-bar Donchian Channel state for strategy / confluence consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    upper: float
    lower: float
    middle: float
    entry_upper: float
    entry_lower: float
    exit_upper: float
    exit_lower: float
    entry_lookback: int = Field(..., ge=1)
    exit_lookback: int = Field(..., ge=1)
    breakout_above: bool
    breakout_below: bool
    false_breakout_above: bool
    false_breakout_below: bool
    close_below_exit_channel: bool
    close_above_exit_channel: bool
    bars_since_upper_breakout: int | None = None
    bars_since_lower_breakout: int | None = None
    close: float


def compute_donchian(
    high: pd.Series,
    low: pd.Series,
    *,
    lookback: int = 20,
) -> pd.DataFrame:
    """Return Donchian upper / lower / middle for ``lookback`` periods.

    Upper = rolling max high, Lower = rolling min low, Middle = midpoint.
    Values use the window ending on each bar (includes the current bar).
    """
    if lookback < 1:
        raise DonchianValidationError("lookback must be >= 1")
    if len(high) != len(low):
        raise DonchianValidationError("high/low must be aligned")
    if len(high) == 0:
        raise DonchianValidationError("Cannot compute Donchian on empty series")

    high_n = pd.to_numeric(high, errors="coerce").astype("float64")
    low_n = pd.to_numeric(low, errors="coerce").astype("float64")
    upper = high_n.rolling(window=lookback, min_periods=lookback).max()
    lower = low_n.rolling(window=lookback, min_periods=lookback).min()
    middle = (upper + lower) / 2.0
    return pd.DataFrame(
        {
            "upper": upper,
            "lower": lower,
            "middle": middle,
        },
        index=high.index,
    )


def compute_prior_channel(
    high: pd.Series,
    low: pd.Series,
    *,
    lookback: int = 20,
) -> pd.DataFrame:
    """Donchian of the *prior* ``lookback`` bars (excludes current bar).

    Used for Turtle-style breakout: close vs prior N-bar high/low avoids the
    look-ahead bias of comparing close to a channel that includes today's high.
    """
    prior_high = pd.to_numeric(high, errors="coerce").shift(1)
    prior_low = pd.to_numeric(low, errors="coerce").shift(1)
    return compute_donchian(prior_high, prior_low, lookback=lookback)


class DonchianChannelService:
    """Injectable Donchian Channel service for strategies and confluence.

    Configurable entry / exit lookbacks support classic Turtle (20/10) and
    longer Turtle entry (55) without hardcoding.
    """

    def __init__(
        self,
        *,
        entry_lookback: int = 20,
        exit_lookback: int = 10,
        high_column: str = "high",
        low_column: str = "low",
        close_column: str = "close",
        upper_column: str = "donchian_upper",
        lower_column: str = "donchian_lower",
        middle_column: str = "donchian_middle",
        entry_upper_column: str = "donchian_entry_upper",
        entry_lower_column: str = "donchian_entry_lower",
        exit_upper_column: str = "donchian_exit_upper",
        exit_lower_column: str = "donchian_exit_lower",
    ) -> None:
        if entry_lookback < 1:
            raise DonchianValidationError("entry_lookback must be >= 1")
        if exit_lookback < 1:
            raise DonchianValidationError("exit_lookback must be >= 1")
        self._entry_lookback = entry_lookback
        self._exit_lookback = exit_lookback
        self._high_column = high_column
        self._low_column = low_column
        self._close_column = close_column
        self._upper_column = upper_column
        self._lower_column = lower_column
        self._middle_column = middle_column
        self._entry_upper_column = entry_upper_column
        self._entry_lower_column = entry_lower_column
        self._exit_upper_column = exit_upper_column
        self._exit_lower_column = exit_lower_column

    @property
    def entry_lookback(self) -> int:
        return self._entry_lookback

    @property
    def exit_lookback(self) -> int:
        return self._exit_lookback

    @property
    def upper_column(self) -> str:
        return self._upper_column

    @property
    def lower_column(self) -> str:
        return self._lower_column

    @property
    def middle_column(self) -> str:
        return self._middle_column

    def compute(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return channel columns aligned to ``frame.index``."""
        self._validate(frame)
        high = frame[self._high_column]
        low = frame[self._low_column]
        display = compute_donchian(high, low, lookback=self._entry_lookback)
        entry = compute_prior_channel(high, low, lookback=self._entry_lookback)
        exit_ch = compute_prior_channel(high, low, lookback=self._exit_lookback)
        return pd.DataFrame(
            {
                self._upper_column: display["upper"],
                self._lower_column: display["lower"],
                self._middle_column: display["middle"],
                self._entry_upper_column: entry["upper"],
                self._entry_lower_column: entry["lower"],
                self._exit_upper_column: exit_ch["upper"],
                self._exit_lower_column: exit_ch["lower"],
            },
            index=frame.index,
        )

    def attach(self, frame: pd.DataFrame, *, overwrite: bool = False) -> pd.DataFrame:
        """Attach Donchian display, entry, and exit channel columns."""
        out = frame.copy()
        computed = self.compute(out)
        for column in computed.columns:
            if column in out.columns and not overwrite:
                raise DonchianValidationError(
                    f"Column {column!r} already present; pass overwrite=True to replace",
                )
            out[column] = computed[column].to_numpy()
        return out

    def snapshot(self, frame: pd.DataFrame) -> DonchianSnapshot:
        """Latest-bar channel + breakout diagnostics (attaches if needed)."""
        required = {
            self._upper_column,
            self._lower_column,
            self._middle_column,
            self._entry_upper_column,
            self._entry_lower_column,
            self._exit_upper_column,
            self._exit_lower_column,
        }
        if not required.issubset(frame.columns):
            frame = self.attach(frame, overwrite=True)
        if len(frame) < 1:
            raise DonchianValidationError("Cannot snapshot empty frame")

        latest = frame.iloc[-1]
        close = float(latest[self._close_column])
        high = float(latest[self._high_column])
        low = float(latest[self._low_column])
        entry_upper = float(latest[self._entry_upper_column])
        entry_lower = float(latest[self._entry_lower_column])
        exit_upper = float(latest[self._exit_upper_column])
        exit_lower = float(latest[self._exit_lower_column])

        breakout_above = close > entry_upper
        breakout_below = close < entry_lower
        false_above = (not breakout_above) and high > entry_upper
        false_below = (not breakout_below) and low < entry_lower

        return DonchianSnapshot(
            upper=float(latest[self._upper_column]),
            lower=float(latest[self._lower_column]),
            middle=float(latest[self._middle_column]),
            entry_upper=entry_upper,
            entry_lower=entry_lower,
            exit_upper=exit_upper,
            exit_lower=exit_lower,
            entry_lookback=self._entry_lookback,
            exit_lookback=self._exit_lookback,
            breakout_above=breakout_above,
            breakout_below=breakout_below,
            false_breakout_above=false_above,
            false_breakout_below=false_below,
            close_below_exit_channel=close < exit_lower,
            close_above_exit_channel=close > exit_upper,
            bars_since_upper_breakout=_bars_since_breakout(
                frame,
                close_column=self._close_column,
                level_column=self._entry_upper_column,
                side="above",
            ),
            bars_since_lower_breakout=_bars_since_breakout(
                frame,
                close_column=self._close_column,
                level_column=self._entry_lower_column,
                side="below",
            ),
            close=close,
        )

    def _validate(self, frame: pd.DataFrame) -> None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise DonchianValidationError("frame must be a non-empty DataFrame")
        required = {self._high_column, self._low_column, self._close_column}
        missing = sorted(column for column in required if column not in frame.columns)
        if missing:
            raise DonchianValidationError(
                f"Donchian missing columns: {', '.join(missing)}",
            )
        need = max(self._entry_lookback, self._exit_lookback) + 2
        if len(frame) < need:
            raise DonchianValidationError(
                f"Need at least {need} bars for Donchian lookbacks",
            )


def _bars_since_breakout(
    frame: pd.DataFrame,
    *,
    close_column: str,
    level_column: str,
    side: str,
) -> int | None:
    """Bars since the most recent prior close breakout (excludes latest bar)."""
    if len(frame) < 2:
        return None
    body = frame.iloc[:-1]
    closes = pd.to_numeric(body[close_column], errors="coerce")
    levels = pd.to_numeric(body[level_column], errors="coerce")
    if side == "above":
        hits = closes > levels
    else:
        hits = closes < levels
    if not bool(hits.any()):
        return None
    last_hit = int(hits.to_numpy().nonzero()[0][-1])
    # Distance from last hit index to the bar before latest (= len(body)-1)
    return (len(body) - 1) - last_hit
