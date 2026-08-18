"""Persistent favorites stored server-side for the paper-trading session."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings, get_settings
from app.market_data.utils.symbols import parquet_basename
from app.services.dashboard.paper_trading_service import get_paper_book

_FAVORITES_FILE = "favorites.json"
_service: FavoritesService | None = None


class FavoritesService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._path = Path(self._settings.parquet_storage_dir).parent / _FAVORITES_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def list_symbols(self) -> list[str]:
        raw = self._read()
        return sorted({parquet_basename(s).upper() for s in raw if s})

    def add(self, symbol: str) -> list[str]:
        base = parquet_basename(symbol).upper()
        items = set(self.list_symbols())
        items.add(base)
        self._write(sorted(items))
        self._sync_book(items)
        return sorted(items)

    def remove(self, symbol: str) -> list[str]:
        base = parquet_basename(symbol).upper()
        items = {s for s in self.list_symbols() if s != base}
        self._write(sorted(items))
        self._sync_book(items)
        return sorted(items)

    def replace(self, symbols: list[str]) -> list[str]:
        items = sorted({parquet_basename(s).upper() for s in symbols if s.strip()})
        self._write(items)
        self._sync_book(set(items))
        return items

    def _read(self) -> list[str]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(s) for s in data]
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _write(self, symbols: list[str]) -> None:
        self._path.write_text(json.dumps(symbols, indent=2), encoding="utf-8")

    def _sync_book(self, symbols: set[str]) -> None:
        book = get_paper_book()
        book.favorites = set(symbols)


def get_favorites_service(settings: Settings | None = None) -> FavoritesService:
    global _service
    if _service is None or settings is not None:
        _service = FavoritesService(settings)
        _service._sync_book(set(_service.list_symbols()))
    return _service


def reset_favorites_service() -> None:
    global _service
    _service = None
