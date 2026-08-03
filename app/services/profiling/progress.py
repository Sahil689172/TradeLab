"""Progress reporting for long profiling / validation runs."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class ProgressUpdate:
    completed: int
    total: int
    symbol: str
    elapsed_s: float
    eta_s: float | None


class ProgressReporter:
    """Thread-safe ``[n/total]`` progress with ETA."""

    def __init__(
        self,
        total: int,
        *,
        label: str = "Profiling",
        sink: Callable[[str], None] | None = None,
        milestones: tuple[float, ...] = (0.05, 0.25, 0.50, 0.75, 1.0),
        every_symbol: bool = True,
    ) -> None:
        self._total = max(0, total)
        self._label = label
        self._sink = sink or (lambda message: print(message, flush=True))
        self._every_symbol = every_symbol
        self._milestones = sorted(milestones)
        self._completed = 0
        self._lock = threading.Lock()
        self._start = time.perf_counter()
        self._fired: set[float] = set()

    def start(self) -> None:
        self._sink(
            f"{self._label}: 0/{self._total} symbols "
            f"(started)",
        )

    def tick(self, symbol: str = "") -> ProgressUpdate:
        with self._lock:
            self._completed += 1
            completed = self._completed
            elapsed = time.perf_counter() - self._start
            eta = None
            if completed > 0 and completed < self._total:
                rate = elapsed / completed
                eta = rate * (self._total - completed)
            update = ProgressUpdate(
                completed=completed,
                total=self._total,
                symbol=symbol,
                elapsed_s=elapsed,
                eta_s=eta,
            )
            should_print = self._every_symbol or self._should_emit_milestone(completed)
            if should_print:
                self._sink(self.format(update))
            return update

    def _should_emit_milestone(self, completed: int) -> bool:
        if self._total <= 0:
            return False
        ratio = completed / self._total
        for mark in self._milestones:
            if mark in self._fired:
                continue
            if ratio + 1e-12 >= mark:
                self._fired.add(mark)
                return True
        return False

    @staticmethod
    def format(update: ProgressUpdate) -> str:
        eta = (
            f"  ETA {_format_duration(update.eta_s)}"
            if update.eta_s is not None
            else "  ETA —"
        )
        if update.completed >= update.total:
            eta = "  done"
        symbol = f"  {update.symbol}" if update.symbol else ""
        return (
            f"[{update.completed}/{update.total}]{symbol}  "
            f"elapsed {_format_duration(update.elapsed_s)}{eta}"
        )


def _format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds >= 3600:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
    if seconds >= 60:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    return f"{seconds:.1f}s"
