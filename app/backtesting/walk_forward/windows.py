"""Rolling train/test window generation. No data is loaded here."""

from __future__ import annotations

from datetime import date, timedelta

from app.backtesting.walk_forward.exceptions import WalkForwardConfigError
from app.backtesting.walk_forward.schemas import WalkForwardConfig, WalkForwardWindow


def generate_windows(
    data_start: date,
    data_end: date,
    config: WalkForwardConfig,
) -> list[WalkForwardWindow]:
    if data_end <= data_start:
        raise WalkForwardConfigError("data_end must be after data_start")
    use_days = config.train_days is not None or config.test_days is not None
    if use_days:
        train_len = int(config.train_days or 252 * config.train_years)
        test_len = int(config.test_days or 252 * config.test_years)
        step_len = int(config.step_days or 252 * config.step_years)
        return _day_windows(data_start, data_end, train_len, test_len, step_len, config.embargo_days)
    return _year_windows(data_start, data_end, config)


def _year_windows(
    data_start: date,
    data_end: date,
    config: WalkForwardConfig,
) -> list[WalkForwardWindow]:
    windows: list[WalkForwardWindow] = []
    train_start = data_start
    window_id = 1
    while True:
        train_end = _add_years(train_start, config.train_years) - timedelta(days=1)
        test_start = train_end + timedelta(days=1 + config.embargo_days)
        test_end = _add_years(test_start, config.test_years) - timedelta(days=1)
        if test_end > data_end:
            break
        if test_start > data_end:
            break
        windows.append(
            WalkForwardWindow(
                window_id=window_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=min(test_end, data_end),
            ),
        )
        window_id += 1
        train_start = _add_years(train_start, config.step_years)
        if train_start >= data_end:
            break
    _validate_windows(windows)
    return windows


def _day_windows(
    data_start: date,
    data_end: date,
    train_len: int,
    test_len: int,
    step_len: int,
    embargo_days: int,
) -> list[WalkForwardWindow]:
    windows: list[WalkForwardWindow] = []
    train_start = data_start
    window_id = 1
    while True:
        train_end = train_start + timedelta(days=train_len - 1)
        test_start = train_end + timedelta(days=1 + embargo_days)
        test_end = test_start + timedelta(days=test_len - 1)
        if test_end > data_end:
            break
        windows.append(
            WalkForwardWindow(
                window_id=window_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=min(test_end, data_end),
            ),
        )
        window_id += 1
        train_start = train_start + timedelta(days=step_len)
        if train_start >= data_end:
            break
    _validate_windows(windows)
    return windows


def _validate_windows(windows: list[WalkForwardWindow]) -> None:
    for window in windows:
        if not (window.train_start <= window.train_end < window.test_start <= window.test_end):
            raise WalkForwardConfigError(
                f"invalid window {window.window_id}: train must end before test starts",
            )


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)
