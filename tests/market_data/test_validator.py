"""Tests for OHLCV validation."""

from __future__ import annotations

import pandas as pd
import pytest

from app.market_data.exceptions import ValidationError
from app.market_data.validators.ohlcv_validator import OHLCVValidator
from tests.market_data.conftest import make_ohlcv_dataframe


def test_validator_accepts_valid_dataframe() -> None:
    """Valid OHLCV data passes validation."""
    validator = OHLCVValidator()
    validator.validate(make_ohlcv_dataframe())


def test_validator_rejects_empty_dataframe() -> None:
    """Empty OHLCV data fails validation."""
    validator = OHLCVValidator()
    with pytest.raises(ValidationError, match="must not be empty"):
        validator.validate(pd.DataFrame())


def test_validator_rejects_duplicate_dates() -> None:
    """Duplicate dates fail validation."""
    frame = make_ohlcv_dataframe(rows=2)
    frame.loc[1, "date"] = frame.loc[0, "date"]
    validator = OHLCVValidator()

    with pytest.raises(ValidationError, match="Duplicate dates"):
        validator.validate(frame)


def test_validator_rejects_missing_values() -> None:
    """Missing values fail validation."""
    frame = make_ohlcv_dataframe()
    frame.loc[0, "close"] = None
    validator = OHLCVValidator()

    with pytest.raises(ValidationError, match="missing values"):
        validator.validate(frame)


def test_validator_rejects_high_below_low() -> None:
    """high < low fails validation."""
    frame = make_ohlcv_dataframe()
    frame.loc[0, "high"] = 90.0
    frame.loc[0, "low"] = 95.0
    validator = OHLCVValidator()

    with pytest.raises(ValidationError, match="high must be >= low"):
        validator.validate(frame)


def test_validator_rejects_open_outside_range() -> None:
    """open outside [low, high] fails validation."""
    frame = make_ohlcv_dataframe()
    frame.loc[0, "open"] = 200.0
    validator = OHLCVValidator()

    with pytest.raises(ValidationError, match="open must be within"):
        validator.validate(frame)


def test_validator_rejects_close_outside_range() -> None:
    """close outside [low, high] fails validation."""
    frame = make_ohlcv_dataframe()
    frame.loc[0, "close"] = 50.0
    validator = OHLCVValidator()

    with pytest.raises(ValidationError, match="close must be within"):
        validator.validate(frame)


def test_validator_rejects_negative_volume() -> None:
    """Negative volume fails validation."""
    frame = make_ohlcv_dataframe()
    frame.loc[0, "volume"] = -1.0
    validator = OHLCVValidator()

    with pytest.raises(ValidationError, match="volume must be >= 0"):
        validator.validate(frame)


def test_validator_rejects_invalid_dtypes() -> None:
    """Non-canonical dtypes fail validation."""
    frame = make_ohlcv_dataframe()
    frame["date"] = frame["date"].astype(object)
    validator = OHLCVValidator()

    with pytest.raises(ValidationError, match="datetime64"):
        validator.validate(frame)


def test_validator_includes_details() -> None:
    """ValidationError exposes a details list."""
    validator = OHLCVValidator()
    try:
        validator.validate(pd.DataFrame())
    except ValidationError as exc:
        assert exc.details
    else:
        pytest.fail("Expected ValidationError")
