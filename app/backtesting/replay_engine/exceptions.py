"""Replay engine exceptions."""

from __future__ import annotations


class ReplayEngineError(Exception):
    """Base error for historical replay."""


class ReplayConfigurationError(ReplayEngineError, ValueError):
    """Invalid replay configuration or inputs."""


class ReplaySessionError(ReplayEngineError, RuntimeError):
    """Invalid session state transition or exhausted replay."""


class ReplayLookAheadError(ReplayEngineError, RuntimeError):
    """Raised when a window would expose candles beyond the replay cursor."""
