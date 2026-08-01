"""Reusable volume analysis for strategies and confluence consumers.

Computes relative volume, period averages, spikes, expansion, and contraction.
Strategies must consume this service — do not reimplement volume math inline.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger

logger = get_logger(__name__)


class VolumeValidationError(ValueError):
    """Invalid inputs for volume analysis."""


class VolumeStatistics(BaseModel):
    """Reusable volume diagnostics for the latest bar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    volume: float = Field(..., ge=0.0)
    average_20: float | None = None
    average_5: float | None = None
    relative_volume_20: float | None = None
    relative_volume_5: float | None = None
    spike: bool = False
    expansion: bool = False
    contraction: bool = False
    above_average_20: bool = False
    decreasing: bool = False


class VolumeAnalysisService:
    """Injectable volume confirmation module for every strategy."""

    def __init__(
        self,
        *,
        volume_column: str = "volume",
        short_window: int = 5,
        long_window: int = 20,
        spike_multiple: float = 1.8,
        expansion_lookback: int = 3,
        relative_volume_20_column: str = "relative_volume_20",
        relative_volume_5_column: str = "relative_volume_5",
        average_20_column: str = "volume_sma_20",
        average_5_column: str = "volume_sma_5",
    ) -> None:
        if short_window < 1 or long_window < 1:
            raise VolumeValidationError("volume windows must be >= 1")
        if short_window > long_window:
            raise VolumeValidationError("short_window must be <= long_window")
        if spike_multiple <= 0:
            raise VolumeValidationError("spike_multiple must be > 0")
        self._volume_column = volume_column
        self._short_window = short_window
        self._long_window = long_window
        self._spike_multiple = spike_multiple
        self._expansion_lookback = expansion_lookback
        self._rvol_20_column = relative_volume_20_column
        self._rvol_5_column = relative_volume_5_column
        self._avg_20_column = average_20_column
        self._avg_5_column = average_5_column

    @property
    def relative_volume_20_column(self) -> str:
        return self._rvol_20_column

    @property
    def average_20_column(self) -> str:
        return self._avg_20_column

    def attach(self, frame: pd.DataFrame, *, overwrite: bool = False) -> pd.DataFrame:
        """Return a copy with volume analysis columns attached."""
        if self._volume_column not in frame.columns:
            raise VolumeValidationError(f"Missing volume column '{self._volume_column}'")
        out = frame.copy()
        volume = pd.to_numeric(out[self._volume_column], errors="coerce").fillna(0.0).clip(lower=0.0)

        avg_20 = volume.rolling(self._long_window, min_periods=max(1, self._long_window // 2)).mean()
        avg_5 = volume.rolling(self._short_window, min_periods=max(1, self._short_window // 2)).mean()
        rvol_20 = volume / avg_20.replace(0.0, pd.NA)
        rvol_5 = volume / avg_5.replace(0.0, pd.NA)

        if self._avg_20_column not in out.columns or overwrite:
            out[self._avg_20_column] = avg_20
        if self._avg_5_column not in out.columns or overwrite:
            out[self._avg_5_column] = avg_5
        if self._rvol_20_column not in out.columns or overwrite:
            out[self._rvol_20_column] = rvol_20
        if self._rvol_5_column not in out.columns or overwrite:
            out[self._rvol_5_column] = rvol_5

        # Expansion / contraction / spike flags as series for consumers.
        prior = volume.shift(1)
        expansion = volume > prior
        contraction = volume < prior
        spike = rvol_20 >= self._spike_multiple
        out["volume_expansion"] = expansion.fillna(False).astype(bool)
        out["volume_contraction"] = contraction.fillna(False).astype(bool)
        out["volume_spike"] = spike.fillna(False).astype(bool)
        return out

    def snapshot(self, frame: pd.DataFrame) -> VolumeStatistics:
        """Latest-bar volume statistics."""
        enriched = self.attach(frame)
        latest = enriched.iloc[-1]
        volume = float(latest[self._volume_column])
        avg_20 = _optional_float(latest.get(self._avg_20_column))
        avg_5 = _optional_float(latest.get(self._avg_5_column))
        rvol_20 = _optional_float(latest.get(self._rvol_20_column))
        rvol_5 = _optional_float(latest.get(self._rvol_5_column))

        volumes = pd.to_numeric(enriched[self._volume_column], errors="coerce").fillna(0.0)
        decreasing = False
        if len(volumes) >= self._expansion_lookback + 1:
            window = volumes.iloc[-(self._expansion_lookback + 1) :]
            decreasing = bool((window.diff().dropna() < 0).all())

        expansion = bool(latest.get("volume_expansion", False))
        contraction = bool(latest.get("volume_contraction", False))
        spike = bool(latest.get("volume_spike", False)) or (
            rvol_20 is not None and rvol_20 >= self._spike_multiple
        )
        above_avg = avg_20 is not None and volume > avg_20

        return VolumeStatistics(
            volume=volume,
            average_20=avg_20,
            average_5=avg_5,
            relative_volume_20=rvol_20,
            relative_volume_5=rvol_5,
            spike=spike,
            expansion=expansion,
            contraction=contraction,
            above_average_20=above_avg,
            decreasing=decreasing,
        )

    def meets_relative_threshold(
        self,
        stats: VolumeStatistics,
        *,
        threshold: float,
    ) -> bool:
        """True when 20-period relative volume exceeds ``threshold``."""
        return stats.relative_volume_20 is not None and stats.relative_volume_20 > threshold


def _optional_float(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number
