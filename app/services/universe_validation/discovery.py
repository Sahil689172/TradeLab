"""Discover OHLCV symbols for universe validation."""

from __future__ import annotations

from pathlib import Path

from app.market_data.utils.symbols import parquet_basename
from app.strategy_engine.symbols import normalize_symbol


def discover_ohlcv_symbols(storage_dir: Path | str) -> list[str]:
    """Return sorted symbols that have a source OHLCV parquet file.

    Ignores ``*_features.parquet``. Only ``SYMBOL.parquet`` files count.
    """
    root = Path(storage_dir)
    if not root.exists():
        return []

    symbols: list[str] = []
    for path in sorted(root.glob("*.parquet")):
        name = path.name
        if name.endswith("_features.parquet"):
            continue
        stem = path.stem.strip()
        if not stem:
            continue
        symbols.append(normalize_symbol(stem))
    return symbols


def resolve_universe_symbols(
    storage_dir: Path | str,
    *,
    symbols: list[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    """Resolve the symbol list for a universe run.

    - ``symbols`` None / empty / containing ``all`` → discover OHLCV files
    - otherwise use the provided symbols (normalized, de-duplicated, sorted)
    - ``limit`` truncates after sorting (deterministic)
    """
    if not symbols or any(item.strip().lower() == "all" for item in symbols):
        resolved = discover_ohlcv_symbols(storage_dir)
    else:
        seen: set[str] = set()
        resolved = []
        for raw in symbols:
            sym = normalize_symbol(raw)
            if sym in seen:
                continue
            seen.add(sym)
            resolved.append(sym)
        resolved.sort()

    if limit is not None:
        resolved = resolved[: max(0, limit)]
    return resolved


def ohlcv_path(storage_dir: Path | str, symbol: str) -> Path:
    """Path to the source OHLCV parquet for ``symbol``."""
    return Path(storage_dir) / f"{parquet_basename(symbol)}.parquet"


def features_path(storage_dir: Path | str, symbol: str) -> Path:
    """Path to the optional features parquet for ``symbol``."""
    return Path(storage_dir) / f"{parquet_basename(symbol)}_features.parquet"
