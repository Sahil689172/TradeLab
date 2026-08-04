"""Mutable replay cursor for one symbol — never exposes future candles."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.backtesting.replay_engine.exceptions import (
    ReplayConfigurationError,
    ReplayLookAheadError,
    ReplaySessionError,
)
from app.backtesting.replay_engine.schemas import ReplaySpeed
from app.backtesting.replay_engine.state import ReplayStatus


_REQUIRED = ("date", "open", "high", "low", "close", "volume")


class ReplaySession:
    """Track symbol, index, timestamp, candle, window, speed, and status.

    The master series is sorted ascending by ``date``. At cursor ``i``, the only
    legal historical window is ``frame.iloc[: i + 1]``.
    """

    def __init__(
        self,
        symbol: str,
        candles: pd.DataFrame,
        *,
        speed: ReplaySpeed = ReplaySpeed.FAST,
        start_index: int = 0,
    ) -> None:
        sym = symbol.strip().upper()
        if not sym:
            raise ReplayConfigurationError("symbol must not be blank")
        frame = _normalize_candles(candles)
        if frame.empty:
            raise ReplayConfigurationError(f"{sym}: candle frame is empty")
        if start_index < 0 or start_index >= len(frame):
            raise ReplayConfigurationError(
                f"{sym}: start_index={start_index} out of range for {len(frame)} candles",
            )

        self._symbol = sym
        self._candles = frame
        self._speed = speed
        self._index = start_index - 1  # before first advance
        self._start_index = start_index
        self._status = ReplayStatus.READY
        self._error: str | None = None

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def speed(self) -> ReplaySpeed:
        return self._speed

    @property
    def status(self) -> ReplayStatus:
        return self._status

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def start_index(self) -> int:
        return self._start_index

    @property
    def total_candles(self) -> int:
        return len(self._candles)

    @property
    def remaining(self) -> int:
        if self._index < self._start_index:
            return len(self._candles) - self._start_index
        return max(0, len(self._candles) - self._index - 1)

    @property
    def is_complete(self) -> bool:
        return self._status is ReplayStatus.COMPLETED

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def current_timestamp(self) -> datetime | None:
        if self._index < self._start_index:
            return None
        return pd.Timestamp(self._candles.iloc[self._index]["date"]).to_pydatetime()

    @property
    def current_candle(self) -> pd.Series | None:
        if self._index < self._start_index:
            return None
        return self._candles.iloc[self._index]

    def historical_window(self) -> pd.DataFrame:
        """Return candles ``[0 .. current_index]`` inclusive — no future rows."""
        if self._index < self._start_index:
            raise ReplaySessionError(
                f"{self._symbol}: cannot build window before the first candle",
            )
        window = self._candles.iloc[: self._index + 1].copy()
        self.assert_no_lookahead(window)
        return window.reset_index(drop=True)

    def assert_no_lookahead(self, window: pd.DataFrame) -> None:
        """Guard: every row in ``window`` must be at or before the cursor timestamp."""
        if self._index < self._start_index:
            raise ReplayLookAheadError(f"{self._symbol}: cursor not advanced")
        cursor_ts = pd.Timestamp(self._candles.iloc[self._index]["date"])
        if window.empty:
            raise ReplayLookAheadError(f"{self._symbol}: empty window")
        dates = pd.to_datetime(window["date"])
        if bool((dates > cursor_ts).any()):
            raise ReplayLookAheadError(
                f"{self._symbol}: window contains timestamps after {cursor_ts.isoformat()}",
            )
        # Also forbid rows beyond the cursor index when frames share the same master series
        if len(window) > self._index + 1:
            raise ReplayLookAheadError(
                f"{self._symbol}: window length {len(window)} exceeds cursor "
                f"{self._index + 1}",
            )

    def start(self) -> None:
        if self._status not in {ReplayStatus.READY, ReplayStatus.PAUSED, ReplayStatus.IDLE}:
            raise ReplaySessionError(
                f"{self._symbol}: cannot start from status {self._status.value}",
            )
        self._status = ReplayStatus.RUNNING

    def pause(self) -> None:
        if self._status is not ReplayStatus.RUNNING:
            raise ReplaySessionError(
                f"{self._symbol}: cannot pause from status {self._status.value}",
            )
        self._status = ReplayStatus.PAUSED

    def fail(self, message: str) -> None:
        self._error = message
        self._status = ReplayStatus.FAILED

    def advance(self) -> pd.Series:
        """Move cursor to the next candle and return it."""
        if self._status is ReplayStatus.PAUSED:
            raise ReplaySessionError(f"{self._symbol}: session is paused")
        if self._status is ReplayStatus.COMPLETED:
            raise ReplaySessionError(f"{self._symbol}: session already completed")
        if self._status is ReplayStatus.FAILED:
            raise ReplaySessionError(f"{self._symbol}: session failed")

        if self._status is ReplayStatus.READY:
            self._status = ReplayStatus.RUNNING

        next_index = self._index + 1 if self._index >= self._start_index else self._start_index
        if next_index >= len(self._candles):
            self._status = ReplayStatus.COMPLETED
            raise ReplaySessionError(f"{self._symbol}: no more candles")

        self._index = next_index
        if self._index >= len(self._candles) - 1:
            # Last candle reached; still RUNNING until mark_completed()
            pass
        return self._candles.iloc[self._index]

    def has_more(self) -> bool:
        if self._status in {ReplayStatus.COMPLETED, ReplayStatus.FAILED}:
            return False
        if self._index < self._start_index:
            return self._start_index < len(self._candles)
        return self._index + 1 < len(self._candles)

    def mark_completed(self) -> None:
        self._status = ReplayStatus.COMPLETED

    def slice_features_to_cursor(self, features: pd.DataFrame) -> pd.DataFrame:
        """Align an external feature frame to timestamps ≤ cursor (no future)."""
        if self._index < self._start_index:
            raise ReplaySessionError(f"{self._symbol}: cursor not advanced")
        if "date" not in features.columns:
            raise ReplayConfigurationError("features must contain a 'date' column")
        cursor_ts = pd.Timestamp(self._candles.iloc[self._index]["date"])
        work = features.copy()
        work["date"] = pd.to_datetime(work["date"])
        clipped = work.loc[work["date"] <= cursor_ts].sort_values("date")
        self.assert_no_lookahead(clipped)
        return clipped.reset_index(drop=True)


def _normalize_candles(candles: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(candles, pd.DataFrame):
        raise ReplayConfigurationError("candles must be a pandas DataFrame")
    missing = [col for col in _REQUIRED if col not in candles.columns]
    if missing:
        raise ReplayConfigurationError(
            f"candles missing columns: {', '.join(missing)}",
        )
    frame = candles.loc[:, list(_REQUIRED)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "open", "high", "low", "close"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return frame
