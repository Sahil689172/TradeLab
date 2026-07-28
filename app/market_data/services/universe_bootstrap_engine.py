"""Bulk universe bootstrap with retry, resume, and progress reporting."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.market_data.schemas.api import IngestionOperationResult
from app.market_data.services.bootstrap_engine import BootstrapEngine, BootstrapResult

logger = get_logger(__name__)

ProgressCallback = Callable[["UniverseBootstrapProgress"], None]
SleepFn = Callable[[float], None]


@dataclass(slots=True)
class UniverseBootstrapProgress:
    """Progress snapshot for a running universe bootstrap."""

    current_symbol: str
    processed: int
    total: int
    downloaded: int
    skipped: int
    failed: int
    elapsed_seconds: float


@dataclass(slots=True)
class UniverseBootstrapSummary:
    """Final outcome of a universe bootstrap run."""

    universe_name: str
    total_symbols: int
    downloaded: int
    skipped: int
    failed: int
    elapsed_seconds: float
    failed_symbols: list[str]
    results: list[IngestionOperationResult]


class UniverseBootstrapEngine:
    """Bootstrap many symbols with retry, resume, and rate limiting."""

    def __init__(
        self,
        bootstrap_engine: BootstrapEngine,
        settings: Settings | None = None,
        sleep_fn: SleepFn | None = None,
    ) -> None:
        self._bootstrap_engine = bootstrap_engine
        self._settings = settings or get_settings()
        self._sleep = sleep_fn or time.sleep

    def bootstrap_symbols(
        self,
        symbols: list[str],
        *,
        universe_name: str = "NIFTY500",
        progress_callback: ProgressCallback | None = None,
    ) -> UniverseBootstrapSummary:
        """Bootstrap each symbol, continuing after individual failures."""
        start_time = time.monotonic()
        total = len(symbols)
        downloaded = 0
        skipped = 0
        failed = 0
        failed_symbols: list[str] = []
        results: list[IngestionOperationResult] = []

        logger.info("Universe bootstrap started for %s (%d symbols)", universe_name, total)

        for index, symbol in enumerate(symbols, start=1):
            normalized_symbol = symbol.strip().upper()
            logger.info(
                "Universe bootstrap processing %s (%d/%d)",
                normalized_symbol,
                index,
                total,
            )

            result = self._bootstrap_with_retry(normalized_symbol)
            results.append(IngestionOperationResult(**asdict(result)))

            if result.status == "bootstrapped":
                downloaded += 1
                self._rate_limit_sleep()
            elif result.status == "skipped":
                skipped += 1
            else:
                failed += 1
                failed_symbols.append(normalized_symbol)
                logger.error(
                    "Universe bootstrap failed for %s after retries: %s",
                    normalized_symbol,
                    result.message,
                )
                self._rate_limit_sleep()

            progress = UniverseBootstrapProgress(
                current_symbol=normalized_symbol,
                processed=index,
                total=total,
                downloaded=downloaded,
                skipped=skipped,
                failed=failed,
                elapsed_seconds=time.monotonic() - start_time,
            )
            if progress_callback is not None:
                progress_callback(progress)

        elapsed_seconds = time.monotonic() - start_time
        summary = UniverseBootstrapSummary(
            universe_name=universe_name,
            total_symbols=total,
            downloaded=downloaded,
            skipped=skipped,
            failed=failed,
            elapsed_seconds=elapsed_seconds,
            failed_symbols=failed_symbols,
            results=results,
        )
        logger.info(
            "Universe bootstrap completed for %s: downloaded=%d skipped=%d failed=%d elapsed=%.1fs",
            universe_name,
            downloaded,
            skipped,
            failed,
            elapsed_seconds,
        )
        return summary

    def _bootstrap_with_retry(self, symbol: str) -> BootstrapResult:
        """Retry a single-symbol bootstrap with exponential backoff."""
        max_retries = self._settings.bootstrap_max_retries
        base_delay = self._settings.bootstrap_retry_base_delay_seconds
        last_message = "Unknown error"

        for attempt in range(max_retries):
            try:
                return self._bootstrap_engine.bootstrap_symbol(symbol)
            except Exception as exc:
                last_message = str(exc)
                logger.warning(
                    "Bootstrap attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    max_retries,
                    symbol,
                    exc,
                )
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.info("Retrying %s in %.1f seconds", symbol, delay)
                    self._sleep(delay)

        return BootstrapResult(
            symbol=symbol,
            status="failed",
            rows_downloaded=0,
            metadata=None,
            ingestion_state=None,
            message=last_message,
        )

    def _rate_limit_sleep(self) -> None:
        delay = self._settings.bootstrap_rate_limit_seconds
        if delay > 0:
            self._sleep(delay)


def format_progress(progress: UniverseBootstrapProgress) -> str:
    """Format a progress snapshot for console output."""
    pct = (progress.processed / progress.total * 100) if progress.total else 0.0
    return (
        f"[{progress.processed}/{progress.total} | {pct:5.1f}%] "
        f"{progress.current_symbol} | "
        f"downloaded={progress.downloaded} skipped={progress.skipped} "
        f"failed={progress.failed} | elapsed={progress.elapsed_seconds:.1f}s"
    )


def format_summary(summary: UniverseBootstrapSummary) -> str:
    """Format the final universe bootstrap summary."""
    lines = [
        "=" * 60,
        f"Universe Bootstrap Summary — {summary.universe_name}",
        "=" * 60,
        f"Total symbols:   {summary.total_symbols}",
        f"Downloaded:      {summary.downloaded}",
        f"Skipped:         {summary.skipped}",
        f"Failed:          {summary.failed}",
        f"Elapsed time:    {summary.elapsed_seconds:.1f}s",
    ]
    if summary.failed_symbols:
        lines.append("")
        lines.append("Failed symbols:")
        for symbol in summary.failed_symbols:
            lines.append(f"  - {symbol}")
    lines.append("=" * 60)
    return "\n".join(lines)
