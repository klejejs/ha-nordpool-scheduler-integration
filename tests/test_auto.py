"""Tests for auto mode's cheapest-slot selection."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.nordpool_scheduler.auto import select_auto_slots

TZ = ZoneInfo("Europe/Riga")
DAY = date(2026, 1, 14)


def _day_prices(day: date, prices: list[float]) -> dict[datetime, float]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=TZ).astimezone(UTC)
    return {start + timedelta(minutes=15 * i): p for i, p in enumerate(prices)}


def _on_indexes(decisions: dict[datetime, bool], day: date) -> list[int]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=TZ).astimezone(UTC)
    return sorted(
        int((slot - start).total_seconds() // 900)
        for slot, on in decisions.items()
        if on
    )


def _select(prices: dict[datetime, float], **kwargs: object) -> dict[datetime, bool]:
    settings = {"run_hours": 1.0, "max_price": 0.0, "cheap_price": 0.0, **kwargs}
    return select_auto_slots(prices, TZ, **settings)


def test_picks_cheapest_slots_of_the_day() -> None:
    """The run_hours cheapest slots are on and every other slot is off."""
    raw = [50.0] * 96
    for i, price in {10: 1.0, 40: 2.0, 41: 3.0, 90: 4.0, 91: 5.0}.items():
        raw[i] = price
    decisions = _select(_day_prices(DAY, raw))

    assert len(decisions) == 96
    assert _on_indexes(decisions, DAY) == [10, 40, 41, 90]


def test_ties_go_to_the_earlier_slot() -> None:
    """Equal prices are broken by start time, earliest first."""
    decisions = _select(_day_prices(DAY, [7.0] * 96), run_hours=0.5)
    assert _on_indexes(decisions, DAY) == [0, 1]


def test_max_price_drops_expensive_picks() -> None:
    """A pick above max_price stays off, so fewer than run_hours may run."""
    raw = [50.0] * 96
    raw[0], raw[1] = 5.0, 9.0
    decisions = _select(_day_prices(DAY, raw), run_hours=1.0, max_price=8.0)
    assert _on_indexes(decisions, DAY) == [0]


def test_cheap_price_adds_slots() -> None:
    """Every slot at or below cheap_price is on, beyond the run_hours picks."""
    raw = [50.0] * 96
    for i in range(20, 30):
        raw[i] = 2.0
    decisions = _select(_day_prices(DAY, raw), run_hours=0.25, cheap_price=2.0)
    assert _on_indexes(decisions, DAY) == list(range(20, 30))


def test_zero_disables_thresholds() -> None:
    """max_price and cheap_price of 0 change nothing, even with negative prices."""
    raw = [10.0] * 96
    raw[5] = -3.0
    decisions = _select(_day_prices(DAY, raw), run_hours=0.25)
    assert _on_indexes(decisions, DAY) == [5]


def test_zero_run_hours_picks_nothing() -> None:
    """With no hours to run, the day is decided but every slot is off."""
    decisions = _select(_day_prices(DAY, [1.0] * 96), run_hours=0)
    assert len(decisions) == 96
    assert not any(decisions.values())


def test_incomplete_day_is_left_undecided() -> None:
    """A day missing any slot's price gets no decision at all."""
    today = _day_prices(DAY, [10.0] * 96)
    tomorrow = _day_prices(DAY + timedelta(days=1), [1.0] * 40)
    decisions = _select({**today, **tomorrow})

    assert len(decisions) == 96
    assert all(slot in today for slot in decisions)


@pytest.mark.parametrize(
    ("day", "slots"),
    [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)],
)
def test_dst_days(day: date, slots: int) -> None:
    """A DST day is decided over its real 92 or 100 slots."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=TZ).astimezone(UTC)
    prices = {start + timedelta(minutes=15 * i): float(i) for i in range(slots)}
    decisions = _select(prices)

    assert len(decisions) == slots
    assert sum(decisions.values()) == 4


def test_window_limits_picks() -> None:
    """Only slots inside the window are picked, and every other slot is off."""
    raw = [50.0] * 96
    raw[8] = 1.0  # 02:00, cheapest of the day but outside the window
    for i, price in {68: 9.0, 72: 5.0, 80: 6.0, 90: 7.0}.items():
        raw[i] = price
    decisions = _select(
        _day_prices(DAY, raw), run_hours=0.5, window=(time(17, 0), time(23, 0))
    )

    assert len(decisions) == 96
    assert _on_indexes(decisions, DAY) == [72, 80]


def test_window_smaller_than_run_hours_runs_all_of_it() -> None:
    """With more hours than the window holds, the whole window runs."""
    decisions = _select(
        _day_prices(DAY, [1.0] * 96), run_hours=4, window=(time(17, 0), time(18, 0))
    )
    assert _on_indexes(decisions, DAY) == [68, 69, 70, 71]


def test_window_with_equal_ends_is_the_whole_day() -> None:
    """A window that starts where it ends covers the whole day."""
    raw = [50.0] * 96
    raw[8] = 1.0
    decisions = _select(
        _day_prices(DAY, raw), run_hours=0.25, window=(time(17, 0), time(17, 0))
    )
    assert _on_indexes(decisions, DAY) == [8]


def test_window_wraps_past_midnight() -> None:
    """A window ending before it starts covers the day's night at both ends."""
    raw = [50.0] * 96
    raw[4], raw[40], raw[92] = 2.0, 1.0, 3.0  # 01:00, 10:00 and 23:00
    decisions = _select(
        _day_prices(DAY, raw), run_hours=0.5, window=(time(22, 0), time(6, 0))
    )
    assert _on_indexes(decisions, DAY) == [4, 92]


def test_cheap_price_stays_in_the_window() -> None:
    """Cheap slots outside the window stay off unless cheap_all_day is set."""
    raw = [50.0] * 96
    raw[8] = 1.0
    raw[72] = 1.5
    settings = {
        "run_hours": 0,
        "cheap_price": 2.0,
        "window": (time(17, 0), time(23, 0)),
    }

    decisions = _select(_day_prices(DAY, raw), **settings)
    assert _on_indexes(decisions, DAY) == [72]

    decisions = _select(_day_prices(DAY, raw), **settings, cheap_all_day=True)
    assert _on_indexes(decisions, DAY) == [8, 72]
