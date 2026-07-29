#!/usr/bin/env python3
"""Directly debug Yahoo Finance validation for one NSE symbol."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

import yfinance as yf
from yfinance import shared as yf_shared
from yfinance.exceptions import YFException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def normalize_ticker(value: str) -> str:
    """Normalize a base NSE symbol to Yahoo's ``.NS`` form."""
    ticker = value.strip().upper()
    return ticker if ticker.endswith(".NS") else f"{ticker}.NS"


def main() -> int:
    """Download five days directly from Yahoo and print diagnostics."""
    if len(sys.argv) != 2:
        print("Usage: python backend/scripts/debug_single_symbol.py TATAMOTORS")
        return 2

    ticker = normalize_ticker(sys.argv[1])
    print(f"Ticker tested:    {ticker}")
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
        print(f"Validation result: NETWORK_ERROR (HTTPError: {exc})")
        return 1
    except TimeoutError as exc:
        print(f"Validation result: NETWORK_ERROR (Timeout: {exc})")
        return 1
    except (ConnectionError, URLError) as exc:
        print(f"Validation result: NETWORK_ERROR ({type(exc).__name__}: {exc})")
        return 1
    except YFException as exc:
        print(f"Validation result: NETWORK_ERROR (YFinanceError: {exc})")
        return 1
    except Exception as exc:
        print(f"Validation result: NETWORK_ERROR ({type(exc).__name__}: {exc})")
        return 1

    downloaded_rows = len(frame.index)
    print(f"Downloaded rows:  {downloaded_rows}")
    print(f"Columns:          {list(frame.columns)}")
    print(f"DataFrame shape:  {frame.shape}")
    print(f"DataFrame type:   {type(frame)}")
    print(f"DataFrame empty:  {frame.empty}")
    print("First rows:")
    print(frame.head())
    swallowed_error = yf_shared._ERRORS.get(ticker)
    if downloaded_rows == 0 and swallowed_error:
        print(f"Validation result: NETWORK_ERROR (YFinanceError: {swallowed_error})")
        return 1
    print(f"Validation result: {'VALID' if downloaded_rows > 0 else 'DELISTED'}")
    return 0 if downloaded_rows > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
