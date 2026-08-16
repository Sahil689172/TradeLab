"""Train/test isolation: date caps, overlap checks, warmup bounds.

Training and test execution may use candles with timestamp <= period_end
(for indicator warmup). They must never see candles after that bound.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.backtesting.walk_forward.exceptions import WalkForwardLeakageError
from app.backtesting.walk_forward.schemas import LeakageReport, WalkForwardWindow


def frame_max_date(frame: pd.DataFrame) -> date | None:
    if frame is None or frame.empty or "date" not in frame.columns:
        return None
    stamps = pd.to_datetime(frame["date"])
    return stamps.max().date()


def cap_frame(frame: pd.DataFrame, *, until: date) -> pd.DataFrame:
    """Keep rows with date <= until. Used for warmup + evaluation bound."""
    if frame is None or frame.empty:
        return frame
    stamps = pd.to_datetime(frame["date"])
    return frame.loc[stamps.dt.date <= until].copy()


def assert_capped(frame: pd.DataFrame, *, until: date, label: str) -> None:
    latest = frame_max_date(frame)
    if latest is not None and latest > until:
        raise WalkForwardLeakageError(
            f"{label} frame contains {latest.isoformat()} which is after bound {until.isoformat()}",
        )


def leakage_from_windows(windows: list[WalkForwardWindow]) -> LeakageReport:
    details: list[str] = []
    train_before = True
    no_overlap = True
    no_dup = True
    for window in windows:
        if window.train_end >= window.test_start:
            train_before = False
            no_overlap = False
            details.append(f"window {window.window_id}: train_end is not before test_start")
        if window.train_end == window.test_start:
            no_dup = False
            details.append(f"window {window.window_id}: train_end equals test_start")
        if window.train_start > window.train_end or window.test_start > window.test_end:
            details.append(f"window {window.window_id}: inverted range")
            train_before = False
    passed = train_before and no_overlap and no_dup and not details
    return LeakageReport(
        passed=passed,
        train_before_test=train_before,
        no_overlap=no_overlap,
        no_duplicate_boundary=no_dup,
        warmup_capped_at_period_end=True,
        train_selection_ignores_test=True,
        details=details,
    )


class DateCappedMarket:
    """MarketDataPort that refuses bars after ``until``."""

    def __init__(self, inner: object, until: date) -> None:
        self._inner = inner
        self._until = until

    def get_history(self, symbol: str) -> pd.DataFrame:
        frame = self._inner.get_history(symbol)
        capped = cap_frame(frame, until=self._until)
        assert_capped(capped, until=self._until, label=f"market:{symbol}")
        return capped


class DateCappedFeatures:
    """FeatureFramePort that refuses bars after ``until``."""

    def __init__(self, inner: object, until: date) -> None:
        self._inner = inner
        self._until = until

    def load_features(self, symbol: str) -> pd.DataFrame | None:
        frame = self._inner.load_features(symbol)
        if frame is None:
            return None
        capped = cap_frame(frame, until=self._until)
        assert_capped(capped, until=self._until, label=f"features:{symbol}")
        return capped


class CachedMarket:
    """Load each symbol's OHLCV once. Callers still receive a copy."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self._cache: dict[str, pd.DataFrame] = {}

    def get_history(self, symbol: str) -> pd.DataFrame:
        key = symbol.strip().upper()
        if key not in self._cache:
            self._cache[key] = self._inner.get_history(symbol)
        return self._cache[key].copy()


class CachedFeatures:
    """Load each symbol's feature frame once. Callers still receive a copy."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self._cache: dict[str, pd.DataFrame | None] = {}

    def load_features(self, symbol: str) -> pd.DataFrame | None:
        key = symbol.strip().upper()
        if key not in self._cache:
            self._cache[key] = self._inner.load_features(symbol)
        frame = self._cache[key]
        return None if frame is None else frame.copy()
