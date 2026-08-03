"""High-resolution timers and thread-safe timing collection."""

from __future__ import annotations

import threading
import time
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TimingRecord:
    """One measured operation."""

    category: str
    name: str
    elapsed_ms: float
    symbol: str | None = None
    strategy: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class TimingCollector:
    """Thread-safe sink for timing samples collected during a profile run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[TimingRecord] = []

    def record(
        self,
        category: str,
        name: str,
        elapsed_ms: float,
        *,
        symbol: str | None = None,
        strategy: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        item = TimingRecord(
            category=category,
            name=name,
            elapsed_ms=float(elapsed_ms),
            symbol=symbol,
            strategy=strategy,
            meta=dict(meta or {}),
        )
        with self._lock:
            self._records.append(item)

    @contextmanager
    def measure(
        self,
        category: str,
        name: str,
        *,
        symbol: str | None = None,
        strategy: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.record(
                category,
                name,
                elapsed_ms,
                symbol=symbol,
                strategy=strategy,
                meta=meta,
            )

    def snapshot(self) -> list[TimingRecord]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


@dataclass(slots=True)
class ProcessResourceSnapshot:
    """CPU / memory sample for the profiling process."""

    wall_ms: float
    cpu_ms: float
    memory_current_bytes: int
    memory_peak_bytes: int


class ResourceMonitor:
    """Wall / CPU / memory sampling via perf_counter + tracemalloc."""

    def __init__(self) -> None:
        self._wall_start = 0.0
        self._cpu_start = 0.0
        self._started = False

    def start(self) -> None:
        tracemalloc.start()
        self._wall_start = time.perf_counter()
        self._cpu_start = time.process_time()
        self._started = True

    def stop(self) -> ProcessResourceSnapshot:
        if not self._started:
            return ProcessResourceSnapshot(0.0, 0.0, 0, 0)
        wall_ms = (time.perf_counter() - self._wall_start) * 1000.0
        cpu_ms = (time.process_time() - self._cpu_start) * 1000.0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self._started = False
        return ProcessResourceSnapshot(
            wall_ms=wall_ms,
            cpu_ms=cpu_ms,
            memory_current_bytes=int(current),
            memory_peak_bytes=int(peak),
        )
