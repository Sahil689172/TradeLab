"""Replay pacing — realtime sleep vs fast (no delay)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from app.backtesting.replay_engine.schemas import ReplaySpeed


class ReplayScheduler:
    """Decide how long to wait between candle advances."""

    def __init__(
        self,
        speed: ReplaySpeed = ReplaySpeed.FAST,
        *,
        realtime_sleep_seconds: float = 0.0,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._speed = speed
        self._realtime_sleep_seconds = max(0.0, float(realtime_sleep_seconds))
        self._clock = clock or time.perf_counter
        self._sleeper = sleeper or time.sleep
        self._last_wall: float | None = None
        self._last_candle_ts: datetime | None = None

    @property
    def speed(self) -> ReplaySpeed:
        return self._speed

    def wait_before_next(
        self,
        *,
        previous_timestamp: datetime | None,
        current_timestamp: datetime,
    ) -> float:
        """Block according to speed; return seconds slept."""
        if self._speed is ReplaySpeed.FAST:
            self._last_candle_ts = current_timestamp
            self._last_wall = self._clock()
            return 0.0

        if self._realtime_sleep_seconds > 0:
            delay = self._realtime_sleep_seconds
        elif previous_timestamp is not None:
            delta = (current_timestamp - previous_timestamp).total_seconds()
            delay = min(max(delta, 0.0), 1.0)
        else:
            delay = 0.0

        if delay > 0:
            self._sleeper(delay)
        self._last_candle_ts = current_timestamp
        self._last_wall = self._clock()
        return delay
