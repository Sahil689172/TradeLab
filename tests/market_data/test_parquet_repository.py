"""Tests for Parquet OHLCV repository."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.market_data.exceptions import RepositoryError
from app.market_data.repositories.parquet_repository import FileParquetRepository
from app.market_data.utils.ohlcv_normalizer import assert_ohlcv_schema
from tests.market_data.conftest import make_ohlcv_dataframe


def test_parquet_write_and_read(storage_settings) -> None:
    """Parquet repository writes and reads OHLCV DataFrames."""
    repo = FileParquetRepository(storage_settings.parquet_storage_dir)
    frame = make_ohlcv_dataframe()

    path = repo.write("RELIANCE", frame)
    assert path.name == "RELIANCE.parquet"
    assert path.exists()
    assert repo.exists("RELIANCE") is True

    loaded = repo.read("RELIANCE")
    assert len(loaded) == len(frame)
    assert list(loaded.columns) == list(frame.columns)
    assert_ohlcv_schema(loaded)


def test_parquet_write_normalizes_input_schema(storage_settings) -> None:
    """Write coerces provider-style rows into canonical Parquet dtypes."""
    repo = FileParquetRepository(storage_settings.parquet_storage_dir)
    raw = pd.DataFrame(
        {
            "date": [date(2024, 1, 2), date(2024, 1, 1), date(2024, 1, 1)],
            "open": [101.0, 100.0, 999.0],
            "high": [106.0, 105.0, 999.0],
            "low": [96.0, 95.0, 999.0],
            "close": [103.0, 102.0, 999.0],
            "adj_close": [103.0, 102.0, 999.0],
            "volume": [1100.5, 1000.0, 888.0],
        },
    )

    repo.write("TATASTEEL", raw)
    loaded = repo.read("TATASTEEL")

    assert len(loaded) == 2
    assert loaded.iloc[0]["open"] == 999.0
    assert loaded.iloc[1]["open"] == 101.0
    assert_ohlcv_schema(loaded)


def test_parquet_read_missing_raises(storage_settings) -> None:
    """Reading a missing Parquet file raises RepositoryError."""
    repo = FileParquetRepository(storage_settings.parquet_storage_dir)
    with pytest.raises(RepositoryError, match="not found"):
        repo.read("MISSING")


def test_parquet_invalid_file_raises(storage_settings) -> None:
    """Reading a corrupt Parquet file raises RepositoryError."""
    repo = FileParquetRepository(storage_settings.parquet_storage_dir)
    bad_file = Path(storage_settings.parquet_storage_dir) / "BAD.parquet"
    bad_file.write_bytes(b"not-a-parquet-file")

    with pytest.raises(RepositoryError, match="Invalid or unreadable"):
        repo.read("BAD")


def test_parquet_delete(storage_settings) -> None:
    """Parquet repository deletes symbol files."""
    repo = FileParquetRepository(storage_settings.parquet_storage_dir)
    repo.write("TCS", make_ohlcv_dataframe())

    assert repo.delete("TCS") is True
    assert repo.exists("TCS") is False
    assert repo.delete("TCS") is False


def test_parquet_append_prevents_duplicate_dates(storage_settings) -> None:
    """Appending overlapping rows keeps one row per date."""
    repo = FileParquetRepository(storage_settings.parquet_storage_dir)
    first = make_ohlcv_dataframe(rows=3)
    second = make_ohlcv_dataframe(rows=3)
    second.loc[2, "date"] = second.loc[1, "date"]

    repo.write("INFY", first)
    repo.append("INFY", second)
    combined = repo.read("INFY")

    assert combined["date"].duplicated().sum() == 0


def test_parquet_nse_symbol_maps_to_base_ticker(storage_settings) -> None:
    """NSE Yahoo symbols are stored as base-ticker Parquet files."""
    repo = FileParquetRepository(storage_settings.parquet_storage_dir)
    path = repo.write("RELIANCE.NS", make_ohlcv_dataframe())

    assert path.name == "RELIANCE.parquet"
    assert repo.exists("RELIANCE.NS") is True
    assert len(repo.read("RELIANCE.NS")) == 3
