"""Tests for the rules auto mode's time windows follow."""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.nordpool_scheduler.auto import AutoWindow
from custom_components.nordpool_scheduler.validation import window_problems


def _window(start: str, end: str, hours: float, **limits: float) -> AutoWindow:
    return AutoWindow(
        start=time.fromisoformat(start),
        end=time.fromisoformat(end),
        hours=hours,
        **limits,
    )


def _keys(*windows: AutoWindow, max_runs: int | None = None) -> list[str]:
    problems = window_problems(
        windows, runs_limited=max_runs is not None, max_runs=max_runs or 0
    )
    return [key for key, _ in problems]


@pytest.mark.parametrize(
    "windows",
    [
        [_window("00:00", "23:59", 2)],
        [_window("00:00", "00:00", 24)],
        [_window("00:00", "23:59", 24)],
        [_window("22:00", "06:00", 8)],
        [_window("20:00", "00:00", 4)],
        [_window("00:00", "23:59", 0, cheap_price=3)],
        [_window("00:00", "23:59", 0, cheap_price=3, min_run_hours=1)],
        [_window("06:00", "08:00", 1, min_run_hours=1)],
        [_window("06:00", "08:00", 1, max_price=10, cheap_price=10)],
        [_window("06:00", "08:00", 1, cheap_price=10)],
        [
            _window("06:00", "08:00", 0.75, max_price=25),
            _window("19:00", "22:00", 1, max_price=15, cheap_price=3),
            _window("00:00", "23:59", 0.25, max_price=15),
        ],
        [_window("06:00", "08:00", 2), _window("00:00", "23:59", 22)],
    ],
)
def test_valid_windows(windows: list[AutoWindow]) -> None:
    """Windows that keep every rule have no problems."""
    assert window_problems(windows, runs_limited=False, max_runs=1) == []


def test_no_windows() -> None:
    """There has to be at least one window."""
    assert _keys() == ["windows_empty"]


@pytest.mark.parametrize(
    ("start", "end"),
    [("06:05", "08:00"), ("06:00", "08:10"), ("06:00:30", "08:00"), ("23:59", "06:00")],
)
def test_bounds_sit_on_slot_boundaries(start: str, end: str) -> None:
    """From and To fall on a 15-minute boundary; only To may be 23:59."""
    assert _keys(_window(start, end, 0.25)) == ["window_time_not_aligned"]


def test_run_for_fits_in_the_window() -> None:
    """A window can't run for longer than it covers, wrapping included."""
    assert _keys(_window("06:00", "08:00", 2.25)) == ["window_hours_too_long"]
    assert _keys(_window("22:00", "06:00", 8.25)) == ["window_hours_too_long"]


def test_min_run_fits_in_the_window() -> None:
    """A min run can't be longer than the window covers."""
    keys = _keys(_window("06:00", "08:00", 0, cheap_price=3, min_run_hours=3))
    assert keys == ["window_min_run_too_long"]


def test_min_run_is_at_most_run_for() -> None:
    """A window that runs for some time runs at least its min run."""
    keys = _keys(_window("06:00", "08:00", 0.5, min_run_hours=1))
    assert keys == ["window_min_run_above_hours"]


def test_cheap_price_is_at_most_max_price() -> None:
    """A cheap price above the max price contradicts it."""
    keys = _keys(_window("06:00", "08:00", 1, max_price=10, cheap_price=12))
    assert keys == ["window_cheap_above_max"]


def test_window_runs_something() -> None:
    """A window with no hours and no cheap price never turns anything on."""
    assert _keys(_window("06:00", "08:00", 0)) == ["window_does_nothing"]
    assert _keys(_window("06:00", "08:00", 0, max_price=10)) == ["window_does_nothing"]


def test_windows_cover_different_times() -> None:
    """Two windows over the same slots, whole-day spellings included, are one."""
    keys = _keys(_window("06:00", "08:00", 1), _window("06:00", "08:00", 0.5))
    assert keys == ["windows_duplicate"]
    keys = _keys(_window("00:00", "00:00", 1), _window("00:00", "23:59", 1))
    assert keys == ["windows_duplicate"]


def test_windows_hours_fit_together() -> None:
    """Windows can't need more slots than they cover between them."""
    problems = window_problems(
        [
            _window("00:00", "23:59", 1),
            _window("06:00", "08:00", 2),
            _window("06:00", "09:00", 2),
        ],
        runs_limited=False,
        max_runs=1,
    )
    assert problems == [
        ("windows_hours_overflow", {"windows": "06:00 to 08:00, 06:00 to 09:00"})
    ]
    assert _keys(_window("00:00", "23:59", 14), _window("00:00", "00:00", 14)) == [
        "windows_duplicate",
        "windows_hours_overflow",
    ]


def test_run_limit_leaves_each_running_window_a_run() -> None:
    """With Limit runs on, each window that runs for some time needs a run."""
    windows = (_window("06:00", "08:00", 1), _window("18:00", "20:00", 1))
    assert _keys(*windows, max_runs=1) == ["windows_too_many_runs"]
    assert _keys(*windows, max_runs=2) == []
    cheap_only = _window("18:00", "20:00", 0, cheap_price=3)
    assert _keys(windows[0], cheap_only, max_runs=1) == []
