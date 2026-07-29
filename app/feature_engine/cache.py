"""Source-aware cache metadata for feature generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import pandas as pd

from app.core.logging import get_logger
from app.feature_engine.schemas import FeatureCacheRecord
from app.market_data.utils.symbols import parquet_basename

logger = get_logger(__name__)

CacheDecision = Literal["current", "append", "rebuild"]


class FeatureCache:
    """Detect unchanged, append-only, and revised OHLCV sources."""

    def __init__(self, storage_dir: Path | str) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def manifest_path(self, symbol: str) -> Path:
        return self._storage_dir / f"{parquet_basename(symbol)}_features.cache.json"

    def load(self, symbol: str) -> FeatureCacheRecord | None:
        path = self.manifest_path(symbol)
        if not path.exists():
            return None
        try:
            return FeatureCacheRecord(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Ignoring invalid feature cache manifest %s", path)
            return None

    def save(
        self,
        symbol: str,
        source: pd.DataFrame,
        features: pd.DataFrame,
        pipeline_version: str,
    ) -> FeatureCacheRecord:
        record = FeatureCacheRecord(
            symbol=symbol.strip().upper(),
            source_fingerprint=self.fingerprint(source),
            source_rows=len(source),
            source_last_date=self._last_date(source),
            feature_rows=len(features),
            feature_last_date=self._last_date(features),
            pipeline_version=pipeline_version,
        )
        path = self.manifest_path(symbol)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
        temporary.replace(path)
        return record

    def decide(
        self,
        symbol: str,
        source: pd.DataFrame,
        pipeline_version: str,
        *,
        feature_file_exists: bool,
    ) -> CacheDecision:
        """Classify source state against the persisted cache manifest."""
        record = self.load(symbol)
        if record is None or not feature_file_exists:
            return "rebuild"
        if record.pipeline_version != pipeline_version:
            return "rebuild"

        fingerprint = self.fingerprint(source)
        if record.source_rows == len(source) and record.source_fingerprint == fingerprint:
            return "current"

        if len(source) > record.source_rows:
            prefix = source.iloc[: record.source_rows]
            if self.fingerprint(prefix) == record.source_fingerprint:
                return "append"
        return "rebuild"

    @staticmethod
    def fingerprint(data: pd.DataFrame) -> str:
        """Return a stable content hash, including column names and values."""
        frame = data.copy()
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"])
        digest = hashlib.sha256()
        digest.update("|".join(map(str, frame.columns)).encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
        return digest.hexdigest()

    @staticmethod
    def _last_date(data: pd.DataFrame) -> str | None:
        if data.empty or "date" not in data.columns:
            return None
        return pd.Timestamp(pd.to_datetime(data["date"]).max()).isoformat()
