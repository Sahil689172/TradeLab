"""Tests for symbol normalization helpers."""

from app.market_data.utils.symbols import parquet_basename


def test_parquet_basename_strips_nse_suffix() -> None:
    assert parquet_basename("RELIANCE.NS") == "RELIANCE"


def test_parquet_basename_strips_bse_suffix() -> None:
    assert parquet_basename("tcs.bo") == "TCS"


def test_parquet_basename_keeps_plain_symbol() -> None:
    assert parquet_basename("INFY") == "INFY"
