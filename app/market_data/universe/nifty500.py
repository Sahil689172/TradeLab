"""NIFTY 500 universe loading and staged Yahoo Finance validation."""

from __future__ import annotations

import csv
import json
import re
import time
from urllib.error import HTTPError, URLError
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yfinance as yf
from yfinance import shared as yf_shared
from yfinance.exceptions import YFException

from app.core.logging import get_logger
from app.market_data.universe.symbol_mapper import (
    SymbolDiscoveryNetworkError,
    SymbolMapper,
)

logger = get_logger(__name__)

DEFAULT_SYMBOLS_FILE = Path(__file__).resolve().parent / "data" / "ind_nifty500list.csv"
NSE_SUFFIX = ".NS"
DEFAULT_VALIDATION_DELAY_SECONDS = 0.25
VALID_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9&-]+$")

ValidationStatus = Literal[
    "VALID",
    "RENAMED",
    "DELISTED",
    "NETWORK_ERROR",
    "INVALID_FORMAT",
]
DownloadFn = Callable[[str], pd.DataFrame]


@dataclass(slots=True)
class UniverseCandidate:
    """One raw local-universe constituent."""

    company_name: str
    symbol: str


@dataclass(slots=True)
class UniverseValidationEntry:
    """Final, mutually exclusive classification for one company."""

    original_symbol: str
    mapped_symbol: str | None
    validation_ticker: str | None
    status: ValidationStatus
    reason: str


@dataclass(slots=True)
class UniverseValidationReport:
    """Complete validation report for all local-universe companies."""

    universe_size: int
    entries: list[UniverseValidationEntry]

    @property
    def valid_symbols(self) -> list[str]:
        """Yahoo tickers eligible for bootstrap."""
        return list(
            dict.fromkeys(
                entry.validation_ticker
                for entry in self.entries
                if entry.status in {"VALID", "RENAMED"} and entry.validation_ticker
            ),
        )

    @property
    def valid_entries(self) -> list[UniverseValidationEntry]:
        return [entry for entry in self.entries if entry.status == "VALID"]

    @property
    def renamed_symbols(self) -> list[UniverseValidationEntry]:
        return [entry for entry in self.entries if entry.status == "RENAMED"]

    @property
    def delisted_symbols(self) -> list[UniverseValidationEntry]:
        return [entry for entry in self.entries if entry.status == "DELISTED"]

    @property
    def network_errors(self) -> list[UniverseValidationEntry]:
        return [entry for entry in self.entries if entry.status == "NETWORK_ERROR"]

    @property
    def invalid_format_symbols(self) -> list[UniverseValidationEntry]:
        return [entry for entry in self.entries if entry.status == "INVALID_FORMAT"]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report with summary statistics."""
        return {
            "statistics": {
                "universe_size": self.universe_size,
                "mapped_symbols": len(self.renamed_symbols),
                "valid_symbols": len(self.valid_symbols),
                "delisted": len(self.delisted_symbols),
                "network_errors": len(self.network_errors),
                "invalid_format": len(self.invalid_format_symbols),
            },
            "entries": [asdict(entry) for entry in self.entries],
        }


class UniverseNetworkError(Exception):
    """Raised when Yahoo validation cannot complete due to connectivity."""


class Nifty500Universe:
    """Load the local NIFTY 500 CSV and validate it in three stages."""

    def __init__(
        self,
        symbols_file: Path | str | None = None,
        *,
        symbol_mapper: SymbolMapper | None = None,
        downloader: DownloadFn | None = None,
        validation_delay_seconds: float = DEFAULT_VALIDATION_DELAY_SECONDS,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._symbols_file = Path(symbols_file) if symbols_file else DEFAULT_SYMBOLS_FILE
        self._symbol_mapper = symbol_mapper or SymbolMapper()
        self._downloader = downloader or self._download_five_day_history
        self._validation_delay_seconds = max(0.0, validation_delay_seconds)
        self._sleep = sleep_fn or time.sleep
        self._candidates = self._load_candidates()
        self._validation_report: UniverseValidationReport | None = None

    def get_symbols(self) -> list[str]:
        """Return validated tickers, or mapped local tickers before validation."""
        if self._validation_report is not None:
            return self._validation_report.valid_symbols
        symbols = [
            self._to_yahoo_symbol(self._symbol_mapper.map_symbol(candidate.symbol))
            for candidate in self._candidates
            if self._is_valid_format(candidate.symbol)
        ]
        return list(dict.fromkeys(symbols))

    def get_count(self) -> int:
        """Return the source universe size, which remains stable after validation."""
        return len(self._candidates)

    def validate(self, report_path: Path | str | None = None) -> UniverseValidationReport:
        """Run mapping, five-day OHLCV validation, and final classification."""
        entries: list[UniverseValidationEntry] = []
        total = len(self._candidates)

        for index, candidate in enumerate(self._candidates, start=1):
            logger.info(
                "Validating universe symbol %s (%d/%d)",
                candidate.symbol,
                index,
                total,
            )
            entries.append(self._validate_candidate(candidate))
            if self._validation_delay_seconds > 0 and index < total:
                self._sleep(self._validation_delay_seconds)

        report = UniverseValidationReport(universe_size=total, entries=entries)
        self._validation_report = report
        if report_path is not None:
            target = Path(report_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

        logger.info(
            "Universe validation completed: size=%d mapped=%d valid=%d "
            "delisted=%d network=%d invalid_format=%d",
            report.universe_size,
            len(report.renamed_symbols),
            len(report.valid_symbols),
            len(report.delisted_symbols),
            len(report.network_errors),
            len(report.invalid_format_symbols),
        )
        return report

    def get_validation_report(self) -> UniverseValidationReport | None:
        """Return the most recent report."""
        return self._validation_report

    def _validate_candidate(self, candidate: UniverseCandidate) -> UniverseValidationEntry:
        original = candidate.symbol
        if not self._is_valid_format(original):
            return UniverseValidationEntry(
                original_symbol=original,
                mapped_symbol=None,
                validation_ticker=None,
                status="INVALID_FORMAT",
                reason="Symbol contains unsupported characters",
            )

        mapped = self._symbol_mapper.map_symbol(original)
        ticker = self._to_yahoo_symbol(mapped)
        try:
            if self._has_history(ticker):
                status: ValidationStatus = "RENAMED" if mapped != original else "VALID"
                reason = (
                    "Validated mapped corporate-action ticker"
                    if status == "RENAMED"
                    else "Five-day OHLCV history is available"
                )
                return UniverseValidationEntry(original, mapped, ticker, status, reason)

            discovered = self._symbol_mapper.discover_symbol(original, candidate.company_name)
            if discovered:
                discovered_ticker = self._to_yahoo_symbol(discovered)
                if self._has_history(discovered_ticker):
                    return UniverseValidationEntry(
                        original,
                        discovered,
                        discovered_ticker,
                        "RENAMED",
                        "Automatically discovered and validated replacement ticker",
                    )

            return UniverseValidationEntry(
                original,
                mapped,
                ticker,
                "DELISTED",
                "No five-day OHLCV history for mapped or discovered ticker",
            )
        except (UniverseNetworkError, SymbolDiscoveryNetworkError) as exc:
            return UniverseValidationEntry(
                original,
                mapped,
                ticker,
                "NETWORK_ERROR",
                str(exc),
            )

    def _has_history(self, ticker: str) -> bool:
        try:
            frame = self._downloader(ticker)
        except UniverseNetworkError:
            raise
        except Exception as exc:
            raise UniverseNetworkError(
                f"Unexpected validation error for {ticker}: {type(exc).__name__}: {exc}",
            ) from exc
        if frame is None:
            logger.info("Ticker %s returned None instead of a DataFrame", ticker)
            return False
        valid = len(frame.index) > 0
        logger.info("Ticker %s validation result: %s", ticker, valid)
        return valid

    def _load_candidates(self) -> list[UniverseCandidate]:
        if not self._symbols_file.exists():
            raise FileNotFoundError(
                f"NIFTY 500 symbols file not found: {self._symbols_file}",
            )

        candidates: list[UniverseCandidate] = []
        seen: set[str] = set()
        with self._symbols_file.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                symbol = (row.get("Symbol") or "").strip().upper()
                company_name = (row.get("Company Name") or "").strip()
                series = (row.get("Series") or "EQ").strip().upper()
                if not symbol or not company_name or series != "EQ" or symbol in seen:
                    continue
                seen.add(symbol)
                candidates.append(UniverseCandidate(company_name, symbol))

        if not candidates:
            raise ValueError(f"No EQ symbols found in NIFTY 500 file: {self._symbols_file}")
        logger.info("Loaded %d companies from local universe %s", len(candidates), self._symbols_file)
        return candidates

    @staticmethod
    def _download_five_day_history(ticker: str) -> pd.DataFrame:
        """Validate strictly through Yahoo's five-day price download."""
        logger.info("Ticker: %s", ticker)
        yf_shared._ERRORS.pop(ticker, None)
        try:
            frame = yf.download(
                ticker,
                period="5d",
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except HTTPError as exc:
            logger.exception("HTTPError validating %s", ticker)
            raise UniverseNetworkError(f"HTTPError for {ticker}: {exc}") from exc
        except TimeoutError as exc:
            logger.exception("Timeout validating %s", ticker)
            raise UniverseNetworkError(f"Timeout for {ticker}: {exc}") from exc
        except (ConnectionError, URLError) as exc:
            logger.exception("NetworkError validating %s", ticker)
            raise UniverseNetworkError(f"NetworkError for {ticker}: {exc}") from exc
        except YFException as exc:
            logger.exception("YFinanceError validating %s", ticker)
            raise UniverseNetworkError(f"YFinanceError for {ticker}: {exc}") from exc
        except Exception as exc:
            logger.exception("Unexpected Yahoo error validating %s", ticker)
            raise UniverseNetworkError(
                f"Unexpected Yahoo error for {ticker}: {type(exc).__name__}: {exc}",
            ) from exc

        logger.info("Ticker %s DataFrame type: %s", ticker, type(frame))
        logger.info("Ticker %s DataFrame shape: %s", ticker, frame.shape)
        logger.info("Ticker %s DataFrame columns: %s", ticker, list(frame.columns))
        logger.info("Ticker %s DataFrame empty: %s", ticker, frame.empty)
        logger.info("Ticker %s downloaded rows: %d", ticker, len(frame))
        swallowed_error = yf_shared._ERRORS.get(ticker)
        if len(frame.index) == 0 and swallowed_error:
            raise UniverseNetworkError(
                f"YFinanceError for {ticker}: {swallowed_error}",
            )
        return frame

    @staticmethod
    def _is_valid_format(symbol: str) -> bool:
        return bool(VALID_SYMBOL_PATTERN.fullmatch(symbol))

    @staticmethod
    def _to_yahoo_symbol(symbol: str) -> str:
        normalized = SymbolMapper.normalize_symbol(symbol)
        return f"{normalized}{NSE_SUFFIX}"
