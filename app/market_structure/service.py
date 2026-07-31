"""Service facade for market structure analysis."""

from __future__ import annotations

import pandas as pd

from app.core.logging import get_logger
from app.market_structure.detector import (
    REQUIRED_OHLCV_COLUMNS,
    alternate_swings,
    classify_trend,
    detect_raw_swings,
    detect_structure_events,
    label_swings,
)
from app.market_structure.exceptions import MarketStructureValidationError
from app.market_structure.schemas import MarketStructureResult, SwingType

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"


class MarketStructureService:
    """Analyze OHLCV bars into reusable swing, trend, BOS, and ChoCH objects.

    The service is deterministic: identical inputs and ``swing_length`` always
    produce identical ``MarketStructureResult`` values.
    """

    def __init__(self, *, swing_length: int = 2) -> None:
        if swing_length < 1:
            raise ValueError("swing_length must be >= 1")
        self._swing_length = swing_length

    @property
    def swing_length(self) -> int:
        return self._swing_length

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    def analyze(
        self,
        ohlcv: pd.DataFrame,
        *,
        symbol: str | None = None,
    ) -> MarketStructureResult:
        """Return a full market-structure snapshot for ``ohlcv``.

        Args:
            ohlcv: Canonical OHLCV frame with ``date/open/high/low/close/volume``.
            symbol: Optional symbol tag stored on the result for downstream use.

        Raises:
            TypeError: When ``ohlcv`` is not a DataFrame.
            MarketStructureValidationError: When columns/shape are invalid.
        """
        frame = self._normalize_ohlcv(ohlcv)
        min_bars = self._swing_length * 2 + 1
        if len(frame) < min_bars:
            raise MarketStructureValidationError(
                f"Need at least {min_bars} bars for swing_length={self._swing_length}, "
                f"got {len(frame)}",
            )

        raw = detect_raw_swings(
            frame["high"],
            frame["low"],
            frame["date"],
            swing_length=self._swing_length,
        )
        swings = label_swings(alternate_swings(raw))
        trend = classify_trend(swings)
        events = detect_structure_events(frame, swings)

        last_high = next(
            (swing for swing in reversed(swings) if swing.swing_type is SwingType.SWING_HIGH),
            None,
        )
        last_low = next(
            (swing for swing in reversed(swings) if swing.swing_type is SwingType.SWING_LOW),
            None,
        )

        result = MarketStructureResult(
            symbol=symbol,
            swing_length=self._swing_length,
            bar_count=len(frame),
            trend=trend,
            swings=swings,
            events=events,
            last_swing_high=last_high,
            last_swing_low=last_low,
        )
        logger.info(
            "Market structure analyzed%s: bars=%d swings=%d events=%d trend=%s",
            f" for {result.symbol}" if result.symbol else "",
            result.bar_count,
            len(result.swings),
            len(result.events),
            result.trend.value,
        )
        return result

    @staticmethod
    def _normalize_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(ohlcv, pd.DataFrame):
            raise TypeError(f"Expected pandas DataFrame, got {type(ohlcv).__name__}")
        if ohlcv.empty:
            raise MarketStructureValidationError("OHLCV DataFrame must not be empty")

        missing = [column for column in REQUIRED_OHLCV_COLUMNS if column not in ohlcv.columns]
        if missing:
            raise MarketStructureValidationError(
                f"Missing required OHLCV columns: {', '.join(missing)}",
            )

        frame = ohlcv.loc[:, list(REQUIRED_OHLCV_COLUMNS)].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).astype("int64")

        if frame[["open", "high", "low", "close"]].isna().any().any():
            raise MarketStructureValidationError("OHLC columns must be numeric and non-null")

        invalid_range = (
            (frame["high"] < frame["low"])
            | (frame["high"] < frame["open"])
            | (frame["high"] < frame["close"])
            | (frame["low"] > frame["open"])
            | (frame["low"] > frame["close"])
        )
        if bool(invalid_range.any()):
            raise MarketStructureValidationError(
                "Invalid OHLC relationship: high must be >= open/close/low and low <= open/close",
            )

        return (
            frame.drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
