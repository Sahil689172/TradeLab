"""Corporate-action symbol mapping and rename discovery."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MAPPING_FILE = Path(__file__).resolve().parent / "data" / "symbol_mapping.json"
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
NSE_SUFFIX = ".NS"

DiscoveryFn = Callable[[str, str], str | None]


class SymbolDiscoveryNetworkError(Exception):
    """Raised when automatic symbol discovery cannot reach Yahoo Finance."""


class SymbolMapper:
    """Resolve known corporate actions and discover likely Yahoo replacements."""

    def __init__(
        self,
        mapping_file: Path | str | None = None,
        *,
        discoverer: DiscoveryFn | None = None,
    ) -> None:
        self._mapping_file = Path(mapping_file) if mapping_file else DEFAULT_MAPPING_FILE
        self._mapping = self._load_mapping()
        self._discoverer = discoverer or self._discover_from_yahoo

    def map_symbol(self, original_symbol: str) -> str:
        """Return a versioned corporate-action replacement, if configured."""
        normalized = self.normalize_symbol(original_symbol)
        return self._mapping.get(normalized, normalized)

    def has_mapping(self, original_symbol: str) -> bool:
        """Return whether an explicit corporate-action mapping exists."""
        return self.normalize_symbol(original_symbol) in self._mapping

    def discover_symbol(self, original_symbol: str, company_name: str) -> str | None:
        """Attempt automatic rename discovery for an unmapped failed ticker."""
        normalized = self.normalize_symbol(original_symbol)
        discovered = self._discoverer(company_name, normalized)
        if not discovered:
            return None
        replacement = self.normalize_symbol(discovered)
        if replacement == normalized:
            return None
        logger.info("Discovered symbol replacement %s -> %s", normalized, replacement)
        return replacement

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Normalize a raw or Yahoo NSE symbol to its base NSE symbol."""
        normalized = symbol.strip().upper()
        if normalized.endswith(NSE_SUFFIX):
            normalized = normalized[: -len(NSE_SUFFIX)]
        return normalized

    def _load_mapping(self) -> dict[str, str]:
        if not self._mapping_file.exists():
            raise FileNotFoundError(f"Symbol mapping file not found: {self._mapping_file}")
        payload = json.loads(self._mapping_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Symbol mapping JSON must contain an object")
        return {
            self.normalize_symbol(str(source)): self.normalize_symbol(str(target))
            for source, target in payload.items()
        }

    @staticmethod
    def _discover_from_yahoo(company_name: str, original_symbol: str) -> str | None:
        params = urllib.parse.urlencode(
            {"q": company_name, "quotesCount": 10, "newsCount": 0},
        )
        request = urllib.request.Request(
            f"{YAHOO_SEARCH_URL}?{params}",
            headers={"User-Agent": "TradeLab/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SymbolDiscoveryNetworkError(
                f"Yahoo symbol discovery failed for {original_symbol}: {exc}",
            ) from exc
        except json.JSONDecodeError:
            return None

        for quote in payload.get("quotes", []):
            yahoo_symbol = str(quote.get("symbol") or "").upper()
            quote_type = str(quote.get("quoteType") or "").upper()
            if not yahoo_symbol.endswith(NSE_SUFFIX):
                continue
            if quote_type and quote_type != "EQUITY":
                continue
            candidate = SymbolMapper.normalize_symbol(yahoo_symbol)
            if candidate != original_symbol:
                return candidate
        return None
