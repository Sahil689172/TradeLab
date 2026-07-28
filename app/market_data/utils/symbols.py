"""Symbol normalization helpers."""

from __future__ import annotations


def parquet_basename(symbol: str) -> str:
    """Return the Parquet filename stem for a Yahoo/NSE symbol.

    Examples:
        RELIANCE.NS -> RELIANCE
        TCS.NS -> TCS
        INFY -> INFY
    """
    cleaned = symbol.strip().upper()
    for suffix in (".NS", ".BO"):
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)]
    return cleaned
