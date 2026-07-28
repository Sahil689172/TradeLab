"""OHLCV Parquet schema normalization."""

from __future__ import annotations

import pandas as pd

from app.market_data.validators.ohlcv_validator import OHLCV_COLUMNS, OHLCV_DTYPES

PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "adj_close")


def normalize_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize an OHLCV DataFrame to the canonical Parquet schema.

    Converts ``date`` to ``datetime64[ns]``, sorts ascending, removes duplicate
    dates (keeping the last row), resets the index, and casts all columns to
    their storage dtypes.
    """
    frame = data[list(OHLCV_COLUMNS)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = (
        frame.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )

    for column in PRICE_COLUMNS:
        frame[column] = frame[column].astype("float64")

    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).astype("int64")
    return frame


def assert_ohlcv_schema(frame: pd.DataFrame) -> None:
    """Raise ``AssertionError`` when ``frame`` does not match the canonical schema."""
    for column, expected_dtype in OHLCV_DTYPES.items():
        if column not in frame.columns:
            raise AssertionError(f"Missing column '{column}'")
        actual = frame[column].dtype
        if column == "date":
            if not pd.api.types.is_datetime64_any_dtype(actual):
                raise AssertionError(
                    f"Column 'date' must be datetime64[ns], got {actual}",
                )
            continue
        if str(actual) != expected_dtype:
            raise AssertionError(
                f"Column '{column}' must be {expected_dtype}, got {actual}",
            )
