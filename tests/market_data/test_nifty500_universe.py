"""Tests for NIFTY 500 universe provider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.market_data.universe.nifty500 import DEFAULT_SYMBOLS_FILE, Nifty500Universe

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
TEST_UNIVERSE_FILE = FIXTURES_DIR / "nifty500_test.csv"


def _quote_validator(symbol: str) -> bool:
    return symbol in {
        "RELIANCE.NS",
        "TCS.NS",
        "INFY.NS",
        "HDFCBANK.NS",
        "SBIN.NS",
        "LTIM.NS",
    }


def _search_resolver(company_name: str, fallback_symbol: str) -> str | None:
    if company_name == "LTIMindtree Ltd.":
        return "LTIM.NS"
    if company_name == "Bad Lookup Ltd.":
        raise RuntimeError("validator unavailable")
    return None


def test_default_universe_file_is_local_and_versioned() -> None:
    assert DEFAULT_SYMBOLS_FILE.exists()
    assert DEFAULT_SYMBOLS_FILE.name == "ind_nifty500list.csv"
    universe = Nifty500Universe(
        DEFAULT_SYMBOLS_FILE,
        quote_validator=lambda _: True,
        search_resolver=lambda *_: None,
        validation_delay_seconds=0.0,
    )
    assert universe.get_count() >= 400


def test_nifty500_universe_loads_yahoo_symbols() -> None:
    universe = Nifty500Universe(
        TEST_UNIVERSE_FILE,
        quote_validator=_quote_validator,
        search_resolver=_search_resolver,
        validation_delay_seconds=0.0,
    )

    assert universe.get_count() == 5
    assert universe.get_symbols() == [
        "RELIANCE.NS",
        "TCS.NS",
        "INFY.NS",
        "HDFCBANK.NS",
        "SBIN.NS",
    ]


def test_nifty500_universe_deduplicates_symbols(tmp_path: Path) -> None:
    csv_path = tmp_path / "dup.csv"
    csv_path.write_text(
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        "Reliance Industries Ltd.,ENERGY,RELIANCE,EQ,INE002A01018\n"
        "Reliance Industries Ltd.,ENERGY,RELIANCE,EQ,INE002A01018\n",
        encoding="utf-8",
    )

    universe = Nifty500Universe(
        csv_path,
        quote_validator=_quote_validator,
        search_resolver=_search_resolver,
        validation_delay_seconds=0.0,
    )

    assert universe.get_count() == 1
    assert universe.get_symbols() == ["RELIANCE.NS"]


def test_nifty500_universe_rejects_empty_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("Company Name,Industry,Symbol,Series,ISIN Code\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No EQ symbols"):
        Nifty500Universe(
            csv_path,
            quote_validator=_quote_validator,
            search_resolver=_search_resolver,
            validation_delay_seconds=0.0,
        )


def test_nifty500_universe_requires_local_csv(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    with pytest.raises(FileNotFoundError, match="version-controlled"):
        Nifty500Universe(missing)


def test_nifty500_universe_validation_report(tmp_path: Path) -> None:
    csv_path = tmp_path / "validation.csv"
    csv_path.write_text(
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        "Reliance Industries Ltd.,ENERGY,RELIANCE,EQ,INE002A01018\n"
        "LTIMindtree Ltd.,IT,LTI,EQ,INE214T01019\n"
        "Delisted Co Ltd.,FINANCIAL SERVICES,OLDBANK,EQ,INE000A01010\n"
        "Bad Lookup Ltd.,IT,BADLOOK,EQ,INE111A01011\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    universe = Nifty500Universe(
        csv_path,
        quote_validator=_quote_validator,
        search_resolver=_search_resolver,
        validation_delay_seconds=0.0,
    )

    report = universe.validate(report_path)

    assert report.valid_symbols == ["RELIANCE.NS", "LTIM.NS"]
    assert report.renamed_symbols[0].symbol == "LTI"
    assert report.renamed_symbols[0].yahoo_symbol == "LTIM.NS"
    assert report.delisted_symbols[0].symbol == "OLDBANK"
    assert report.invalid_symbols[0].symbol == "BADLOOK"
    assert universe.get_symbols() == ["RELIANCE.NS", "LTIM.NS"]

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["valid_symbols"] == ["RELIANCE.NS", "LTIM.NS"]
    assert payload["renamed_symbols"][0]["symbol"] == "LTI"


def test_validation_continues_when_some_symbols_fail(tmp_path: Path) -> None:
    csv_path = tmp_path / "mixed.csv"
    csv_path.write_text(
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        "Reliance Industries Ltd.,ENERGY,RELIANCE,EQ,INE002A01018\n"
        "Delisted Co Ltd.,FINANCIAL SERVICES,OLDBANK,EQ,INE000A01010\n"
        "Infosys Ltd.,IT,INFY,EQ,INE009A01021\n",
        encoding="utf-8",
    )
    universe = Nifty500Universe(
        csv_path,
        quote_validator=_quote_validator,
        search_resolver=_search_resolver,
        validation_delay_seconds=0.0,
    )

    report = universe.validate()

    assert report.valid_symbols == ["RELIANCE.NS", "INFY.NS"]
    assert len(report.delisted_symbols) == 1
    assert report.total_candidates == 3
