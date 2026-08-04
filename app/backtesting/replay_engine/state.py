"""Replay session status."""

from __future__ import annotations

from enum import Enum


class ReplayStatus(str, Enum):
    """Lifecycle of a single-symbol replay session."""

    IDLE = "IDLE"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
