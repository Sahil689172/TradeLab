"""Reusable VWAP calculator for strategies and confluence consumers.

Daily VWAP is implemented. Anchored / weekly / monthly modes are reserved
in the public API but intentionally not implemented yet.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger

logger = get_logger(__name__)


class VWAPMode(str, Enum):
    """VWAP anchoring mode. Only ``DAILY`` is implemented today."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ANCHORED = "anchored"


class VWAPNotImplementedError(NotImplementedError):
    """Raised when a future VWAP mode is requested before implementation."""


class VWAPValidationError(ValueError):
    """Invalid inputs for VWAP computation."""


class VWAPSnapshot(BaseModel):
    """Latest-bar VWAP state for strategy consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: VWAPMode
    value: float = Field(..., gt=0.0)
    slope: float
    slope_positive: bool
    slope_negative: bool
    price_above: bool
    price_below: bool
    column: str = "vwap"


def compute_daily_vwap(
    frame: pd.DataFrame,
    *,
    date_column: str = "date",
    high_column: str = "high",
    low_column: str = "low",
    close_column: str = "close",
    volume_column: str = "volume",
) -> pd.Series:
    """Session-day VWAP: cumulative typical-price × volume / cumulative volume.

    Resets at each calendar day. Returns a float series aligned to ``frame.index``.
    """
    _require_columns(
        frame,
        (date_column, high_column, low_column, close_column, volume_column),
    )
    if frame.empty:
        raise VWAPValidationError("Cannot compute VWAP on an empty frame")

    dates = pd.to_datetime(frame[date_column])
    session = dates.dt.normalize()
    typical = (
        pd.to_numeric(frame[high_column], errors="coerce")
        + pd.to_numeric(frame[low_column], errors="coerce")
        + pd.to_numeric(frame[close_column], errors="coerce")
    ) / 3.0
    volume = pd.to_numeric(frame[volume_column], errors="coerce").fillna(0.0).clip(lower=0.0)
    if (volume <= 0).all():
        raise VWAPValidationError("VWAP requires positive volume")

    tp_vol = typical * volume
    cum_tp_vol = tp_vol.groupby(session).cumsum()
    cum_vol = volume.groupby(session).cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0.0, pd.NA)
    return vwap.astype("float64").rename("vwap")


def compute_vwap_slope(
    vwap: pd.Series,
    *,
    lookback: int = 3,
) -> pd.Series:
    """Point change in VWAP over ``lookback`` bars (positive = rising)."""
    if lookback < 1:
        raise VWAPValidationError("slope lookback must be >= 1")
    return (vwap - vwap.shift(lookback)).astype("float64").rename("vwap_slope")


class VWAPService:
    """Injectable VWAP service used by strategies and future modules.

    Dependency-inject this service so ORB / CPR / EMA / Confluence can share
    one Daily VWAP implementation without duplicating math.
    """

    def __init__(
        self,
        *,
        mode: VWAPMode = VWAPMode.DAILY,
        slope_lookback: int = 3,
        date_column: str = "date",
        high_column: str = "high",
        low_column: str = "low",
        close_column: str = "close",
        volume_column: str = "volume",
        vwap_column: str = "vwap",
        slope_column: str = "vwap_slope",
    ) -> None:
        self._mode = mode
        self._slope_lookback = slope_lookback
        self._date_column = date_column
        self._high_column = high_column
        self._low_column = low_column
        self._close_column = close_column
        self._volume_column = volume_column
        self._vwap_column = vwap_column
        self._slope_column = slope_column

    @property
    def mode(self) -> VWAPMode:
        return self._mode

    @property
    def vwap_column(self) -> str:
        return self._vwap_column

    @property
    def slope_column(self) -> str:
        return self._slope_column

    def compute_series(
        self,
        frame: pd.DataFrame,
        *,
        mode: VWAPMode | None = None,
        anchor: pd.Timestamp | None = None,
    ) -> pd.Series:
        """Return VWAP series for the requested mode (Daily only today)."""
        resolved = mode or self._mode
        if resolved is VWAPMode.DAILY:
            if anchor is not None:
                logger.debug("Ignoring anchor=%s for daily VWAP", anchor)
            return compute_daily_vwap(
                frame,
                date_column=self._date_column,
                high_column=self._high_column,
                low_column=self._low_column,
                close_column=self._close_column,
                volume_column=self._volume_column,
            ).rename(self._vwap_column)

        raise VWAPNotImplementedError(
            f"VWAP mode '{resolved.value}' is reserved for a future release; "
            "only daily VWAP is implemented",
        )

    def attach(
        self,
        frame: pd.DataFrame,
        *,
        mode: VWAPMode | None = None,
        overwrite: bool = False,
    ) -> pd.DataFrame:
        """Return a copy of ``frame`` with VWAP (+ slope) columns attached.

        If ``vwap`` already exists and ``overwrite`` is False, reuses it and
        only (re)computes slope when missing.
        """
        out = frame.copy()
        if self._vwap_column not in out.columns or overwrite:
            out[self._vwap_column] = self.compute_series(out, mode=mode)
        if self._slope_column not in out.columns or overwrite:
            out[self._slope_column] = compute_vwap_slope(
                out[self._vwap_column],
                lookback=self._slope_lookback,
            )
        return out

    def snapshot(
        self,
        frame: pd.DataFrame,
        *,
        close: float | None = None,
    ) -> VWAPSnapshot:
        """Latest VWAP value / slope / price relationship."""
        enriched = self.attach(frame)
        latest = enriched.iloc[-1]
        value = float(latest[self._vwap_column])
        slope_raw = latest[self._slope_column]
        slope = float(slope_raw) if pd.notna(slope_raw) else 0.0
        price = float(close) if close is not None else float(latest[self._close_column])
        return VWAPSnapshot(
            mode=self._mode if self._mode is VWAPMode.DAILY else VWAPMode.DAILY,
            value=value,
            slope=slope,
            slope_positive=slope > 0,
            slope_negative=slope < 0,
            price_above=price > value,
            price_below=price < value,
            column=self._vwap_column,
        )


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise VWAPValidationError(f"VWAP missing columns: {', '.join(missing)}")


# Public typing helper for future consumers selecting a mode via config.
VWAPModeLiteral = Literal["daily", "weekly", "monthly", "anchored"]
