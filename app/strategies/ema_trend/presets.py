"""EMA length presets shared by config and professional evaluation."""

from __future__ import annotations

EMA_PAIR_PRESETS: dict[str, tuple[int, int]] = {
    "9_21": (9, 21),
    "12_26": (12, 26),
    "20_50": (20, 50),
    "50_200": (50, 200),
}


def ema_column_for_period(period: int) -> str:
    return f"ema_{int(period)}"
