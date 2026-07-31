"""Pydantic contracts for indicator adapter responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IndicatorKind(str, Enum):
    """High-level indicator family."""

    SERIES = "SERIES"
    MACD = "MACD"


class IndicatorPoint(BaseModel):
    """One dated indicator observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    value: float | None = None


class IndicatorSeries(BaseModel):
    """Typed single-column indicator series read from feature data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: IndicatorKind = IndicatorKind.SERIES
    name: str = Field(..., min_length=1)
    column: str = Field(..., min_length=1, description="Resolved feature column name")
    points: list[IndicatorPoint] = Field(default_factory=list)

    @field_validator("name", "column")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @property
    def latest(self) -> IndicatorPoint | None:
        return self.points[-1] if self.points else None

    @property
    def latest_value(self) -> float | None:
        point = self.latest
        return None if point is None else point.value


class MacdIndicator(BaseModel):
    """Typed MACD bundle (line, signal, histogram) from feature columns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: IndicatorKind = IndicatorKind.MACD
    name: str = "macd"
    line: IndicatorSeries
    signal: IndicatorSeries
    histogram: IndicatorSeries

    @model_validator(mode="after")
    def validate_aligned(self) -> MacdIndicator:
        lengths = {len(self.line.points), len(self.signal.points), len(self.histogram.points)}
        if len(lengths) != 1:
            raise ValueError("MACD components must contain the same number of points")
        return self

    @property
    def latest_line(self) -> float | None:
        return self.line.latest_value

    @property
    def latest_signal(self) -> float | None:
        return self.signal.latest_value

    @property
    def latest_histogram(self) -> float | None:
        return self.histogram.latest_value


IndicatorValue = IndicatorSeries | MacdIndicator
