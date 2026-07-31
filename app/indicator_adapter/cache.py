"""In-memory caches for feature frames and resolved indicator objects."""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock

import pandas as pd

from app.indicator_adapter.schemas import IndicatorValue


class LRUCache[T]:
    """Simple thread-safe LRU cache."""

    def __init__(self, maxsize: int = 128) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._data: OrderedDict[str, T] = OrderedDict()
        self._lock = RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> T | None:
        with self._lock:
            if key not in self._data:
                self.misses += 1
                return None
            self.hits += 1
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: str, value: T) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class IndicatorCache:
    """Caches bound feature frames and resolved indicator payloads."""

    def __init__(self, *, frame_maxsize: int = 32, indicator_maxsize: int = 256) -> None:
        self.frames: LRUCache[pd.DataFrame] = LRUCache(maxsize=frame_maxsize)
        self.indicators: LRUCache[IndicatorValue] = LRUCache(maxsize=indicator_maxsize)

    def clear(self) -> None:
        self.frames.clear()
        self.indicators.clear()

    def stats(self) -> dict[str, int]:
        return {
            "frame_hits": self.frames.hits,
            "frame_misses": self.frames.misses,
            "frame_size": len(self.frames),
            "indicator_hits": self.indicators.hits,
            "indicator_misses": self.indicators.misses,
            "indicator_size": len(self.indicators),
        }
