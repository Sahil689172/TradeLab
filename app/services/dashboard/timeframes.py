"""Dashboard timeframe definitions and OHLCV resampling."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class TimeframeSpec:
    code: str
    label: str
    strategy_label: str
    supported: bool
    resample_rule: str | None = None
    reason: str = ""


TIMEFRAMES: dict[str, TimeframeSpec] = {
    "1m": TimeframeSpec("1m", "1 Minute", "1 Minute", False, reason="Intraday bars are not stored; Yahoo bootstrap uses daily history"),
    "5m": TimeframeSpec("5m", "5 Minute", "5 Minute", False, reason="Intraday bars are not stored; Yahoo bootstrap uses daily history"),
    "15m": TimeframeSpec("15m", "15 Minute", "15 Minute", False, reason="Intraday bars are not stored; Yahoo bootstrap uses daily history"),
    "1h": TimeframeSpec("1h", "1 Hour", "1 Hour", False, reason="Intraday bars are not stored; Yahoo bootstrap uses daily history"),
    "4h": TimeframeSpec("4h", "4 Hour", "4 Hour", False, reason="Intraday bars are not stored; Yahoo bootstrap uses daily history"),
    "1D": TimeframeSpec("1D", "1 Day", "1 Day", True, None),
    "1W": TimeframeSpec("1W", "1 Week", "1 Week", True, "W-FRI"),
    "1M": TimeframeSpec("1M", "1 Month", "1 Month", True, "ME"),
}

SUPPORTED_TIMEFRAMES: tuple[str, ...] = tuple(
    code for code, spec in TIMEFRAMES.items() if spec.supported
)


def get_timeframe(code: str) -> TimeframeSpec:
    key = code.strip()
    if key not in TIMEFRAMES:
        raise KeyError(f"Unknown timeframe '{code}'. Known: {sorted(TIMEFRAMES)}")
    return TIMEFRAMES[key]


def resample_ohlcv(frame: pd.DataFrame, *, rule: str | None) -> pd.DataFrame:
    """Resample canonical OHLCV to the requested rule (daily input)."""
    if frame.empty or rule is None:
        return frame.copy()
    df = frame.copy()
    if "date" not in df.columns:
        raise ValueError("OHLCV frame must include date column")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    agg = df.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        },
    )
    if "adj_close" in df.columns:
        agg["adj_close"] = df["adj_close"].resample(rule).last()
    agg = agg.dropna(subset=["close"]).reset_index()
    return agg
