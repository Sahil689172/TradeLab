"""Tests for staged NIFTY 500 universe validation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from yfinance import shared as yf_shared

from app.market_data.universe.nifty500 import (
    DEFAULT_SYMBOLS_FILE,
    Nifty500Universe,
    UniverseNetworkError,
)
from app.market_data.universe.symbol_mapper import SymbolMapper

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
TEST_UNIVERSE_FILE = FIXTURES_DIR / "nifty500_test.csv"


def _write_csv(path: Path, symbols: list[str]) -> None:
    rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
    rows.extend(
        f"{symbol} Limited,INDUSTRIALS,{symbol},EQ,INE000A01010"
        for symbol in symbols
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _valid_download(_: str) -> pd.DataFrame:
    return pd.DataFrame({"Close": [100.0]})


def test_default_universe_file_contains_501_companies() -> None:
    universe = Nifty500Universe(
        DEFAULT_SYMBOLS_FILE,
        downloader=_valid_download,
        validation_delay_seconds=0.0,
    )
    assert universe.get_count() == 501


def test_nifty500_universe_deduplicates_symbols(tmp_path: Path) -> None:
    csv_path = tmp_path / "dup.csv"
    _write_csv(csv_path, ["RELIANCE", "RELIANCE"])
    universe = Nifty500Universe(
        csv_path,
        downloader=_valid_download,
        validation_delay_seconds=0.0,
    )
    assert universe.get_count() == 1


def test_nifty500_universe_rejects_empty_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    _write_csv(csv_path, [])
    with pytest.raises(ValueError, match="No EQ symbols"):
        Nifty500Universe(csv_path)


def test_report_has_one_exact_status_per_company(tmp_path: Path) -> None:
    csv_path = tmp_path / "mixed.csv"
    _write_csv(csv_path, ["RELIANCE", "LTI", "DELISTED", "BAD.SYMBOL", "NETWORK"])
    mapper = SymbolMapper(discoverer=lambda *_: None)

    def downloader(ticker: str) -> pd.DataFrame:
        if ticker == "NETWORK.NS":
            raise TimeoutError("request timed out")
        if ticker in {"RELIANCE.NS", "LTIM.NS"}:
            return pd.DataFrame({"Close": [100.0]})
        return pd.DataFrame()

    report_path = tmp_path / "report.json"
    universe = Nifty500Universe(
        csv_path,
        symbol_mapper=mapper,
        downloader=downloader,
        validation_delay_seconds=0.0,
    )
    report = universe.validate(report_path)

    assert [entry.status for entry in report.entries] == [
        "VALID",
        "RENAMED",
        "DELISTED",
        "INVALID_FORMAT",
        "NETWORK_ERROR",
    ]
    assert report.valid_symbols == ["RELIANCE.NS", "LTIM.NS"]

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["statistics"]["universe_size"] == 5
    assert payload["entries"][1] == {
        "original_symbol": "LTI",
        "mapped_symbol": "LTIM",
        "validation_ticker": "LTIM.NS",
        "status": "RENAMED",
        "reason": "Validated mapped corporate-action ticker",
    }


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("LTI", "LTIM"),
        ("MINDTREE", "LTIM"),
        ("PVR", "PVRINOX"),
        ("CADILAHC", "ZYDUSLIFE"),
        ("HDFC", "HDFCBANK"),
        ("MOTHERSUMI", "MOTHERSON"),
    ],
)
def test_required_corporate_actions_are_renamed(
    tmp_path: Path,
    original: str,
    replacement: str,
) -> None:
    csv_path = tmp_path / f"{original}.csv"
    _write_csv(csv_path, [original])
    calls: list[str] = []

    def downloader(ticker: str) -> pd.DataFrame:
        calls.append(ticker)
        return pd.DataFrame({"Close": [100.0]})

    report = Nifty500Universe(
        csv_path,
        downloader=downloader,
        validation_delay_seconds=0.0,
    ).validate()

    assert report.entries[0].status == "RENAMED"
    assert report.entries[0].mapped_symbol == replacement
    assert report.entries[0].validation_ticker == f"{replacement}.NS"
    assert calls == [f"{replacement}.NS"]


@pytest.mark.parametrize(
    "symbol",
    ["LTIM", "AKZOINDIA", "GSPL", "PEL", "TATAMOTORS", "SWANENERGY", "WELSPUNIND"],
)
def test_known_active_symbols_validate_from_nonempty_history(
    tmp_path: Path,
    symbol: str,
) -> None:
    csv_path = tmp_path / f"{symbol}.csv"
    _write_csv(csv_path, [symbol])

    report = Nifty500Universe(
        csv_path,
        downloader=_valid_download,
        validation_delay_seconds=0.0,
    ).validate()

    assert report.entries[0].status == "VALID"
    assert report.valid_symbols == [f"{symbol}.NS"]


def test_nonzero_index_is_valid_even_when_empty_property_is_true(tmp_path: Path) -> None:
    """Regression: validity depends only on index length, never ``df.empty``."""

    class MisleadingDataFrame(pd.DataFrame):
        @property
        def empty(self) -> bool:
            return True

    csv_path = tmp_path / "TATAMOTORS.csv"
    _write_csv(csv_path, ["TATAMOTORS"])
    frame = MisleadingDataFrame({"Close": [100.0]})

    report = Nifty500Universe(
        csv_path,
        downloader=lambda _: frame,
        validation_delay_seconds=0.0,
    ).validate()

    assert len(frame.index) == 1
    assert frame.empty is True
    assert report.entries[0].status == "VALID"


def test_production_downloader_uses_required_yfinance_call(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_download(ticker: str, **kwargs: object) -> pd.DataFrame:
        calls.append((ticker, kwargs))
        return pd.DataFrame({"Close": [100.0]})

    monkeypatch.setattr("app.market_data.universe.nifty500.yf.download", fake_download)
    frame = Nifty500Universe._download_five_day_history("TATAMOTORS.NS")

    assert not frame.empty
    assert calls == [
        (
            "TATAMOTORS.NS",
            {
                "period": "5d",
                "progress": False,
                "auto_adjust": False,
                "threads": False,
            },
        ),
    ]


def test_swallowed_yfinance_error_is_not_treated_as_delisted(monkeypatch) -> None:
    def failed_download(ticker: str, **_: object) -> pd.DataFrame:
        yf_shared._ERRORS[ticker] = "Timeout while contacting Yahoo"
        return pd.DataFrame()

    monkeypatch.setattr("app.market_data.universe.nifty500.yf.download", failed_download)

    with pytest.raises(UniverseNetworkError, match="YFinanceError"):
        Nifty500Universe._download_five_day_history("PEL.NS")
