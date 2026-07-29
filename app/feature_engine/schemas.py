"""Typed contracts for feature generation and caching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureCacheRecord:
    """Persisted identity of source and generated feature data."""

    symbol: str
    source_fingerprint: str
    source_rows: int
    source_last_date: str | None
    feature_rows: int
    feature_last_date: str | None
    pipeline_version: str


@dataclass(frozen=True, slots=True)
class FeatureGenerationResult:
    """Outcome of generating features for one symbol."""

    symbol: str
    status: str
    source_rows: int
    feature_rows: int
    rows_added: int
    cache_hit: bool
    feature_path: str
