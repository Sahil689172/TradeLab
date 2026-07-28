"""OHLCV data validation before persistence."""

from __future__ import annotations

import pandas as pd

from app.core.logging import get_logger
from app.market_data.exceptions import ValidationError
from app.market_data.schemas.ohlcv_record import OHLCVRecord

logger = get_logger(__name__)

OHLCV_COLUMNS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
)

OHLCV_DTYPES: dict[str, str] = {
    "date": "datetime64[ns]",
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "adj_close": "float64",
    "volume": "int64",
}


class OHLCVValidator:
    """Validate historical OHLCV DataFrames before Parquet persistence."""

    def validate(self, data: pd.DataFrame) -> None:
        """Validate an OHLCV DataFrame and raise on failure.

        Args:
            data: DataFrame with columns ``date``, ``open``, ``high``, ``low``,
                ``close``, ``adj_close``, ``volume``.

        Raises:
            ValidationError: When any validation rule fails.
        """
        errors: list[str] = []

        if data is None or data.empty:
            errors.append("OHLCV data must not be empty")
            self._raise(errors)

        missing_columns = [col for col in OHLCV_COLUMNS if col not in data.columns]
        if missing_columns:
            errors.append(f"Missing required columns: {', '.join(missing_columns)}")
            self._raise(errors)

        frame = data[list(OHLCV_COLUMNS)].copy()
        self._check_dtypes(frame, errors)
        self._check_missing_values(frame, errors)
        self._check_duplicate_dates(frame, errors)
        self._check_price_rules(frame, errors)
        self._check_volume(frame, errors)

        if errors:
            logger.warning("OHLCV validation failed with %d issue(s)", len(errors))
            self._raise(errors)

        logger.debug("OHLCV validation passed for %d row(s)", len(frame))

    def validate_records(self, records: list[OHLCVRecord]) -> None:
        """Validate a list of OHLCV Pydantic records."""
        frame = pd.DataFrame([record.model_dump() for record in records])
        self.validate(frame)

    @staticmethod
    def _check_dtypes(frame: pd.DataFrame, errors: list[str]) -> None:
        for column, expected_dtype in OHLCV_DTYPES.items():
            actual = frame[column].dtype
            if column == "date":
                if not pd.api.types.is_datetime64_any_dtype(actual):
                    errors.append(
                        f"Column 'date' must be datetime64[ns], got {actual}",
                    )
                continue
            if str(actual) != expected_dtype:
                errors.append(
                    f"Column '{column}' must be {expected_dtype}, got {actual}",
                )

    @staticmethod
    def _check_missing_values(frame: pd.DataFrame, errors: list[str]) -> None:
        for column in OHLCV_COLUMNS:
            if frame[column].isna().any():
                errors.append(f"Column '{column}' contains missing values")

    @staticmethod
    def _check_duplicate_dates(frame: pd.DataFrame, errors: list[str]) -> None:
        if frame["date"].duplicated().any():
            duplicate_count = int(frame["date"].duplicated().sum())
            errors.append(f"Duplicate dates found ({duplicate_count} duplicate row(s))")

    @staticmethod
    def _check_price_rules(frame: pd.DataFrame, errors: list[str]) -> None:
        invalid_high_low = frame["high"] < frame["low"]
        if invalid_high_low.any():
            count = int(invalid_high_low.sum())
            errors.append(f"high must be >= low ({count} row(s) invalid)")

        open_outside = (frame["open"] < frame["low"]) | (frame["open"] > frame["high"])
        if open_outside.any():
            count = int(open_outside.sum())
            errors.append(f"open must be within [low, high] ({count} row(s) invalid)")

        close_outside = (frame["close"] < frame["low"]) | (frame["close"] > frame["high"])
        if close_outside.any():
            count = int(close_outside.sum())
            errors.append(f"close must be within [low, high] ({count} row(s) invalid)")

    @staticmethod
    def _check_volume(frame: pd.DataFrame, errors: list[str]) -> None:
        invalid_volume = frame["volume"] < 0
        if invalid_volume.any():
            count = int(invalid_volume.sum())
            errors.append(f"volume must be >= 0 ({count} row(s) invalid)")

    @staticmethod
    def _raise(errors: list[str]) -> None:
        message = "OHLCV validation failed"
        if errors:
            message = f"{message}: {errors[0]}"
        raise ValidationError(message, details=errors)
