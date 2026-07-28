"""NIFTY 500 index universe provider and Yahoo ticker validator."""

from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yfinance as yf

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_SYMBOLS_FILE = Path(__file__).resolve().parent / "data" / "ind_nifty500list.csv"
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
NSE_SUFFIX = ".NS"
DEFAULT_VALIDATION_DELAY_SECONDS = 0.25


@dataclass(slots=True)
class UniverseCandidate:
    """A raw NIFTY 500 constituent before Yahoo validation."""

    company_name: str
    symbol: str
    yahoo_symbol: str


@dataclass(slots=True)
class UniverseValidationItem:
    """One validated, renamed, delisted, or invalid universe entry."""

    symbol: str
    yahoo_symbol: str | None
    company_name: str
    reason: str


@dataclass(slots=True)
class UniverseValidationReport:
    """Structured result of validating a NIFTY 500 universe."""

    total_candidates: int
    valid_symbols: list[str]
    renamed_symbols: list[UniverseValidationItem]
    delisted_symbols: list[UniverseValidationItem]
    invalid_symbols: list[UniverseValidationItem]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report."""
        return {
            "total_candidates": self.total_candidates,
            "valid_symbols": list(self.valid_symbols),
            "renamed_symbols": [asdict(item) for item in self.renamed_symbols],
            "delisted_symbols": [asdict(item) for item in self.delisted_symbols],
            "invalid_symbols": [asdict(item) for item in self.invalid_symbols],
        }


class Nifty500Universe:
    """Load the local NIFTY 500 CSV and validate Yahoo Finance tickers.

    The constituent list is read from a version-controlled CSV under
    ``app/market_data/universe/data/``. No remote NSE download is performed.
    """

    def __init__(
        self,
        symbols_file: Path | str | None = None,
        *,
        quote_validator: Callable[[str], bool] | None = None,
        search_resolver: Callable[[str, str], str | None] | None = None,
        validation_delay_seconds: float = DEFAULT_VALIDATION_DELAY_SECONDS,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._symbols_file = Path(symbols_file) if symbols_file is not None else DEFAULT_SYMBOLS_FILE
        self._quote_validator = quote_validator or self._default_quote_validator
        self._search_resolver = search_resolver or self._default_search_resolver
        self._validation_delay_seconds = max(0.0, validation_delay_seconds)
        self._sleep = sleep_fn or time.sleep
        self._candidates = self._load_candidates()
        self._validated_symbols: list[str] | None = None
        self._validation_report: UniverseValidationReport | None = None

    def get_symbols(self) -> list[str]:
        """Return validated symbols, or raw CSV symbols when not yet validated."""
        if self._validated_symbols is not None:
            return list(self._validated_symbols)
        return [candidate.yahoo_symbol for candidate in self._candidates]

    def get_count(self) -> int:
        """Return the number of currently selected symbols."""
        return len(self.get_symbols())

    def validate(self, report_path: Path | str | None = None) -> UniverseValidationReport:
        """Validate Yahoo tickers and optionally write a JSON report.

        Invalid, delisted, and permanently unavailable symbols are excluded from
        ``valid_symbols``. Renamed symbols are rewritten to the current Yahoo ticker.
        Bootstrap continues with every validated symbol.
        """
        valid_symbols: list[str] = []
        renamed_symbols: list[UniverseValidationItem] = []
        delisted_symbols: list[UniverseValidationItem] = []
        invalid_symbols: list[UniverseValidationItem] = []

        for index, candidate in enumerate(self._candidates, start=1):
            logger.info(
                "Validating universe symbol %s (%d/%d)",
                candidate.yahoo_symbol,
                index,
                len(self._candidates),
            )
            try:
                if self._quote_validator(candidate.yahoo_symbol):
                    valid_symbols.append(candidate.yahoo_symbol)
                else:
                    replacement = self._search_resolver(
                        candidate.company_name,
                        candidate.yahoo_symbol,
                    )
                    if replacement and replacement != candidate.yahoo_symbol:
                        if self._quote_validator(replacement):
                            valid_symbols.append(replacement)
                            renamed_symbols.append(
                                UniverseValidationItem(
                                    symbol=candidate.symbol,
                                    yahoo_symbol=replacement,
                                    company_name=candidate.company_name,
                                    reason="Renamed or symbol changed on Yahoo Finance",
                                ),
                            )
                        else:
                            delisted_symbols.append(
                                UniverseValidationItem(
                                    symbol=candidate.symbol,
                                    yahoo_symbol=candidate.yahoo_symbol,
                                    company_name=candidate.company_name,
                                    reason="Unavailable or delisted on Yahoo Finance",
                                ),
                            )
                    else:
                        delisted_symbols.append(
                            UniverseValidationItem(
                                symbol=candidate.symbol,
                                yahoo_symbol=candidate.yahoo_symbol,
                                company_name=candidate.company_name,
                                reason="Unavailable or delisted on Yahoo Finance",
                            ),
                        )
            except Exception as exc:
                invalid_symbols.append(
                    UniverseValidationItem(
                        symbol=candidate.symbol,
                        yahoo_symbol=candidate.yahoo_symbol,
                        company_name=candidate.company_name,
                        reason=str(exc),
                    ),
                )

            if self._validation_delay_seconds > 0 and index < len(self._candidates):
                self._sleep(self._validation_delay_seconds)

        report = UniverseValidationReport(
            total_candidates=len(self._candidates),
            valid_symbols=list(dict.fromkeys(valid_symbols)),
            renamed_symbols=renamed_symbols,
            delisted_symbols=delisted_symbols,
            invalid_symbols=invalid_symbols,
        )
        self._validated_symbols = report.valid_symbols
        self._validation_report = report

        if report_path is not None:
            target = Path(report_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

        logger.info(
            "Validated NIFTY 500 universe from %s: valid=%d renamed=%d delisted=%d invalid=%d",
            self._symbols_file,
            len(report.valid_symbols),
            len(report.renamed_symbols),
            len(report.delisted_symbols),
            len(report.invalid_symbols),
        )
        return report

    def get_validation_report(self) -> UniverseValidationReport | None:
        """Return the last validation report, if one exists."""
        return self._validation_report

    def _load_candidates(self) -> list[UniverseCandidate]:
        if not self._symbols_file.exists():
            msg = (
                f"NIFTY 500 symbols file not found: {self._symbols_file}. "
                "The universe CSV must be version-controlled under "
                "app/market_data/universe/data/."
            )
            raise FileNotFoundError(msg)

        candidates: list[UniverseCandidate] = []
        seen: set[str] = set()

        with self._symbols_file.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw_symbol = (row.get("Symbol") or "").strip().upper()
                company_name = (row.get("Company Name") or "").strip()
                series = (row.get("Series") or "EQ").strip().upper()
                if not raw_symbol or not company_name or series != "EQ":
                    continue
                yahoo_symbol = (
                    raw_symbol if raw_symbol.endswith(NSE_SUFFIX) else f"{raw_symbol}{NSE_SUFFIX}"
                )
                if yahoo_symbol in seen:
                    continue
                seen.add(yahoo_symbol)
                candidates.append(
                    UniverseCandidate(
                        company_name=company_name,
                        symbol=raw_symbol,
                        yahoo_symbol=yahoo_symbol,
                    ),
                )

        if not candidates:
            msg = f"No EQ symbols found in NIFTY 500 file: {self._symbols_file}"
            raise ValueError(msg)

        logger.info(
            "Loaded %d NIFTY 500 candidates from local file %s",
            len(candidates),
            self._symbols_file,
        )
        return candidates

    @staticmethod
    def _default_quote_validator(yahoo_symbol: str) -> bool:
        """Return True when Yahoo Finance has recent OHLCV for the ticker."""
        ticker = yf.Ticker(yahoo_symbol)
        history = ticker.history(period="5d", auto_adjust=False, actions=False)
        return history is not None and not history.empty

    @staticmethod
    def _default_search_resolver(company_name: str, fallback_symbol: str) -> str | None:
        """Find a current NSE Yahoo ticker for a renamed company via Yahoo search."""
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
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None

        quotes = payload.get("quotes", [])
        for quote in quotes:
            quote_symbol = str(quote.get("symbol") or "").upper()
            quote_type = str(quote.get("quoteType") or "").upper()
            if not quote_symbol.endswith(NSE_SUFFIX):
                continue
            if quote_type and quote_type not in {"EQUITY", ""}:
                continue
            if quote_symbol == fallback_symbol.upper():
                continue
            return quote_symbol

        return None
