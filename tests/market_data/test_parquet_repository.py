"""Tests for Parquet OHLCV repository."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.market_data.exceptions import RepositoryError
from app.market_data.repositories.parquet_repository import FileParquetRepository
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
    assert set(loaded.columns) == set(frame.columns)


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
