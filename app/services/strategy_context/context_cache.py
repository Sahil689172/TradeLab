"""Thread-safe run-scoped caches for strategy context artifacts.

Caches are shared across strategies (and optionally across worker threads)
within a single validation / profiling run. They never mutate cached
DataFrames in place after insert — callers receive references that must be
treated as immutable, or ``.copy()`` before mutation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd

T = TypeVar("T")


@dataclass
class SymbolContextArtifacts:
    """Reusable per-symbol context pieces (lazy-filled)."""

    base_features: pd.DataFrame | None = None
    daily: pd.DataFrame | None = None
    levels: Any | None = None
    structure_by_key: dict[str, Any] = field(default_factory=dict)
    session_features: pd.DataFrame | None = None
    vwap_features: pd.DataFrame | None = None
    relative_volume_features: pd.DataFrame | None = None


class ContextRunCache:
    """Process-wide (run-scoped) cache safe for ThreadPoolExecutor workers.

    Design rules:
    - No shared *mutable* DataFrame state between workers: stored frames are
      treated as immutable after publication.
    - Double-checked locking per key avoids duplicate expensive builds.
    - Ranking / parquet caches are shared so peer OHLCV is read once per path.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._symbol: dict[str, SymbolContextArtifacts] = {}
        self._parquet: dict[str, pd.DataFrame] = {}
        self._rankings: dict[str, Any] = {}
        self._universe_frames: dict[str, dict[str, pd.DataFrame]] = {}
        self._build_locks: dict[str, threading.Lock] = {}

    def clear(self) -> None:
        with self._lock:
            self._symbol.clear()
            self._parquet.clear()
            self._rankings.clear()
            self._universe_frames.clear()
            self._build_locks.clear()

    def _key_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lock = self._build_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._build_locks[key] = lock
            return lock

    def symbol_artifacts(self, symbol: str) -> SymbolContextArtifacts:
        key = symbol.strip().upper()
        with self._lock:
            artifacts = self._symbol.get(key)
            if artifacts is None:
                artifacts = SymbolContextArtifacts()
                self._symbol[key] = artifacts
            return artifacts

    def get_parquet(self, path: Path | str) -> pd.DataFrame | None:
        key = str(Path(path).resolve()) if Path(path).exists() else str(path)
        with self._lock:
            frame = self._parquet.get(key)
            return None if frame is None else frame

    def set_parquet(self, path: Path | str, frame: pd.DataFrame) -> pd.DataFrame:
        key = str(Path(path).resolve()) if Path(path).exists() else str(path)
        with self._lock:
            existing = self._parquet.get(key)
            if existing is not None:
                return existing
            self._parquet[key] = frame
            return frame

    def get_or_load_parquet(self, path: Path) -> pd.DataFrame | None:
        """Load parquet once per path for the run; return None if missing."""
        resolved = Path(path)
        key = str(resolved.resolve()) if resolved.exists() else str(resolved)
        with self._lock:
            cached = self._parquet.get(key)
            if cached is not None:
                return cached
        if not resolved.exists():
            return None
        lock = self._key_lock(f"parquet:{key}")
        with lock:
            with self._lock:
                cached = self._parquet.get(key)
                if cached is not None:
                    return cached
            frame = pd.read_parquet(resolved, engine="pyarrow")
            with self._lock:
                self._parquet[key] = frame
                return frame

    def get_ranking(self, key: str) -> Any | None:
        with self._lock:
            return self._rankings.get(key)

    def set_ranking(self, key: str, ranking: Any) -> Any:
        with self._lock:
            existing = self._rankings.get(key)
            if existing is not None:
                return existing
            self._rankings[key] = ranking
            return ranking

    def get_or_build_ranking(self, key: str, builder: Any) -> Any:
        """Build ranking once per key (thread-safe)."""
        with self._lock:
            cached = self._rankings.get(key)
            if cached is not None:
                return cached
        lock = self._key_lock(f"ranking:{key}")
        with lock:
            with self._lock:
                cached = self._rankings.get(key)
                if cached is not None:
                    return cached
            ranking = builder()
            with self._lock:
                self._rankings[key] = ranking
                return ranking

    def get_universe_frames(self, key: str) -> dict[str, pd.DataFrame] | None:
        with self._lock:
            frames = self._universe_frames.get(key)
            return None if frames is None else frames

    def set_universe_frames(
        self,
        key: str,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, pd.DataFrame]:
        with self._lock:
            existing = self._universe_frames.get(key)
            if existing is not None:
                return existing
            self._universe_frames[key] = frames
            return frames

    def get_or_build(
        self,
        bucket: str,
        key: str,
        builder: Any,
    ) -> T:
        """Generic double-checked build helper for arbitrary cached values."""
        full = f"{bucket}:{key}"
        with self._lock:
            # Rankings-style store for generic objects lives in _rankings too
            cached = self._rankings.get(full)
            if cached is not None:
                return cached  # type: ignore[no-any-return]
        lock = self._key_lock(full)
        with lock:
            with self._lock:
                cached = self._rankings.get(full)
                if cached is not None:
                    return cached  # type: ignore[no-any-return]
            value = builder()
            with self._lock:
                self._rankings[full] = value
                return value  # type: ignore[no-any-return]


def features_fingerprint(features: pd.DataFrame) -> str:
    """Stable-enough fingerprint for caller-supplied feature frames."""
    n = len(features)
    if n == 0:
        return "empty"
    date_col = "date" if "date" in features.columns else None
    last = ""
    if date_col is not None:
        last = str(features[date_col].iloc[-1])
    cols = ",".join(features.columns.astype(str).tolist()[:24])
    return f"n={n}|last={last}|cols={cols}"


def structure_cache_key(features: pd.DataFrame, *, swing_length: int) -> str:
    return f"structure|swing={swing_length}|{features_fingerprint(features)}"
