"""Tests for bulk universe bootstrap."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.core.config import Settings
from app.market_data.exceptions import ProviderError
from app.market_data.providers.base_provider import MarketDataProvider
from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.services.bootstrap_engine import BootstrapEngine
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.market_data.services.universe_bootstrap_engine import (
    UniverseBootstrapEngine,
    format_progress,
    format_summary,
)
from app.market_data.universe.nifty500 import Nifty500Universe
from tests.market_data.conftest import FakeProvider

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
TEST_UNIVERSE_FILE = FIXTURES_DIR / "nifty500_test.csv"


def _quote_validator(symbol: str) -> bool:
    return symbol in {
        "RELIANCE.NS",
        "TCS.NS",
        "INFY.NS",
        "HDFCBANK.NS",
        "SBIN.NS",
    }


def _search_resolver(company_name: str, fallback_symbol: str) -> str | None:
    return None


def _make_universe() -> Nifty500Universe:
    return Nifty500Universe(
        TEST_UNIVERSE_FILE,
        quote_validator=_quote_validator,
        search_resolver=_search_resolver,
        validation_delay_seconds=0.0,
    )


class FlakyProvider(MarketDataProvider):
    """Provider that fails a configurable number of times before succeeding."""

    def __init__(
        self,
        inner: MarketDataProvider,
        *,
        fail_symbols: set[str] | None = None,
        fail_attempts: int = 2,
    ) -> None:
        self._inner = inner
        self._fail_symbols = fail_symbols or set()
        self._fail_attempts = fail_attempts
        self._attempts: dict[str, int] = defaultdict(int)

    def download_history(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        normalized = symbol.strip().upper()
        if normalized in self._fail_symbols:
            self._attempts[normalized] += 1
            if self._attempts[normalized] <= self._fail_attempts:
                raise ProviderError(f"temporary failure for {normalized}")
        return self._inner.download_history(
            symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
        )

    def download_metadata(self, symbol: str) -> CompanyMetadata:
        return self._inner.download_metadata(symbol)

    def download_company_info(self, symbol: str) -> dict[str, object]:
        return self._inner.download_company_info(symbol)


@pytest.fixture()
def bulk_settings(storage_settings: Settings) -> Settings:
    return storage_settings.model_copy(
        update={
            "bootstrap_rate_limit_seconds": 0.0,
            "bootstrap_max_retries": 3,
            "bootstrap_retry_base_delay_seconds": 0.01,
        },
    )


def _build_gateway(
    db_session,
    bulk_settings: Settings,
    provider: MarketDataProvider,
    sleep_fn,
) -> MarketDataGateway:
    inner_gateway = MarketDataGateway(
        db_session,
        settings=bulk_settings,
        provider=provider,
    )
    bootstrap_engine = BootstrapEngine(
        provider,
        inner_gateway._parquet_repo,
        inner_gateway._metadata_repo,
        inner_gateway._ingestion_repo,
        inner_gateway._validator,
        bulk_settings,
    )
    universe_engine = UniverseBootstrapEngine(
        bootstrap_engine,
        bulk_settings,
        sleep_fn=sleep_fn,
    )
    return MarketDataGateway(
        db_session,
        settings=bulk_settings,
        provider=provider,
        universe_bootstrap_engine=universe_engine,
    )


def test_gateway_bootstrap_universe_downloads_all_symbols(
    db_session,
    bulk_settings,
) -> None:
    sleeps: list[float] = []
    gateway = _build_gateway(db_session, bulk_settings, FakeProvider(), sleeps.append)
    universe = _make_universe()

    summary = gateway.bootstrap_universe(universe)

    assert summary.total_symbols == 5
    assert summary.downloaded == 5
    assert summary.skipped == 0
    assert summary.failed == 0
    assert summary.failed_symbols == []
    assert len(summary.results) == 5
    assert all(result.status == "bootstrapped" for result in summary.results)


def test_gateway_bootstrap_universe_skips_existing_symbols(
    db_session,
    bulk_settings,
) -> None:
    gateway = _build_gateway(db_session, bulk_settings, FakeProvider(), lambda _: None)
    universe = _make_universe()

    gateway.bootstrap_symbol("RELIANCE.NS")
    gateway.bootstrap_symbol("TCS.NS")

    summary = gateway.bootstrap_universe(universe)

    assert summary.downloaded == 3
    assert summary.skipped == 2
    assert summary.failed == 0


def test_gateway_bootstrap_universe_resumes_after_partial_run(
    db_session,
    bulk_settings,
) -> None:
    gateway = _build_gateway(db_session, bulk_settings, FakeProvider(), lambda _: None)
    universe = _make_universe()
    symbols = universe.get_symbols()

    first_pass = gateway.bootstrap_universe(
        _make_universe(),
    )
    assert first_pass.downloaded == 5

    second_pass = gateway.bootstrap_universe(universe)

    assert second_pass.downloaded == 0
    assert second_pass.skipped == 5
    assert second_pass.failed == 0
    assert len(symbols) == 5


def test_universe_bootstrap_retries_failed_symbol(
    db_session,
    bulk_settings,
) -> None:
    provider = FlakyProvider(FakeProvider(), fail_symbols={"INFY.NS"}, fail_attempts=2)
    gateway = _build_gateway(db_session, bulk_settings, provider, lambda _: None)
    universe = _make_universe()

    summary = gateway.bootstrap_universe(universe)

    assert summary.failed == 0
    assert summary.downloaded == 5
    assert provider._attempts["INFY.NS"] == 3


def test_universe_bootstrap_marks_symbol_failed_after_retries(
    db_session,
    bulk_settings,
) -> None:
    provider = FlakyProvider(FakeProvider(), fail_symbols={"INFY.NS"}, fail_attempts=5)
    gateway = _build_gateway(db_session, bulk_settings, provider, lambda _: None)

    summary = gateway.bootstrap_universe(_make_universe())

    assert summary.failed == 1
    assert summary.failed_symbols == ["INFY.NS"]
    assert summary.downloaded == 4
    assert summary.skipped == 0


def test_universe_bootstrap_continues_after_failure(
    db_session,
    bulk_settings,
) -> None:
    provider = FlakyProvider(FakeProvider(), fail_symbols={"TCS.NS"}, fail_attempts=5)
    gateway = _build_gateway(db_session, bulk_settings, provider, lambda _: None)

    summary = gateway.bootstrap_universe(_make_universe())

    assert summary.failed == 1
    assert summary.downloaded == 4
    assert gateway.history_exists("RELIANCE.NS") is True
    assert gateway.history_exists("INFY.NS") is True


def test_universe_bootstrap_progress_callback(
    db_session,
    bulk_settings,
) -> None:
    gateway = _build_gateway(db_session, bulk_settings, FakeProvider(), lambda _: None)
    snapshots = []

    gateway.bootstrap_universe(
        _make_universe(),
        progress_callback=snapshots.append,
    )

    assert len(snapshots) == 5
    assert snapshots[-1].processed == 5
    assert snapshots[-1].total == 5
    assert snapshots[-1].downloaded == 5
    assert "downloaded=5" in format_progress(snapshots[-1])


def test_universe_bootstrap_does_not_sleep_when_rate_limit_disabled(
    db_session,
    bulk_settings,
) -> None:
    sleeps: list[float] = []
    gateway = _build_gateway(db_session, bulk_settings, FakeProvider(), sleeps.append)

    gateway.bootstrap_universe(_make_universe())

    assert sleeps == []


def test_universe_bootstrap_sleeps_between_downloads(
    db_session,
    storage_settings: Settings,
) -> None:
    settings = storage_settings.model_copy(
        update={
            "bootstrap_rate_limit_seconds": 0.5,
            "bootstrap_max_retries": 3,
            "bootstrap_retry_base_delay_seconds": 0.01,
        },
    )
    sleeps: list[float] = []
    gateway = _build_gateway(db_session, settings, FakeProvider(), sleeps.append)

    gateway.bootstrap_universe(_make_universe())

    assert sleeps == [0.5, 0.5, 0.5, 0.5, 0.5]


def test_bootstrap_universe_writes_validation_report(
    db_session,
    bulk_settings,
) -> None:
    gateway = _build_gateway(db_session, bulk_settings, FakeProvider(), lambda _: None)

    gateway.bootstrap_universe(_make_universe())

    report_path = Path(bulk_settings.log_directory) / "universe_validation_report.json"
    assert report_path.exists() is True


def test_format_summary_includes_failed_symbols() -> None:
    from app.market_data.services.universe_bootstrap_engine import UniverseBootstrapSummary

    summary = UniverseBootstrapSummary(
        universe_name="NIFTY500",
        total_symbols=2,
        downloaded=1,
        skipped=0,
        failed=1,
        elapsed_seconds=12.5,
        failed_symbols=["BAD.NS"],
        results=[],
    )

    rendered = format_summary(summary)

    assert "Downloaded:      1" in rendered
    assert "Failed:          1" in rendered
    assert "BAD.NS" in rendered
