"""Auto mode: pick the cheapest slots of each local day."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import SLOT_MINUTES

if TYPE_CHECKING:
    from datetime import date, time, tzinfo


def select_auto_slots(
    prices: dict[datetime, float],
    tz: tzinfo,
    *,
    run_hours: float,
    max_price: float,
    cheap_price: float,
    window: tuple[time, time] | None = None,
    cheap_all_day: bool = False,
) -> dict[datetime, bool]:
    """Decide on or off for every slot of each fully priced local day.

    Per day, the ``run_hours`` cheapest slots inside ``window`` are on, minus
    any above ``max_price``, plus any inside it at or below ``cheap_price``,
    or anywhere in the day with ``cheap_all_day``. A threshold of 0 is off.
    Days missing a price for any slot are left out, apart from the slots
    outside ``window``, so they follow the default state rather than a
    choice made on half the day.
    """
    run_slots = int(run_hours * 60 // SLOT_MINUTES)
    days = {dt_util.as_utc(start).astimezone(tz).date() for start in prices}

    decisions: dict[datetime, bool] = {}
    for day in days:
        day_slots = _local_day_slots(day, tz)
        in_window = {
            slot
            for slot in day_slots
            if _in_window(dt_util.as_utc(slot).astimezone(tz).time(), window)
        }
        if any(slot not in prices for slot in day_slots):
            # Outside the range is off whatever the prices turn out to be.
            decisions.update(
                (slot, False) for slot in day_slots if slot not in in_window
            )
            continue
        by_price = sorted(in_window, key=lambda slot: (prices[slot], slot))
        picked = {
            slot
            for slot in by_price[:run_slots]
            if max_price == 0 or prices[slot] <= max_price
        }
        for slot in day_slots:
            cheap = (
                cheap_price > 0
                and prices[slot] <= cheap_price
                and (cheap_all_day or slot in in_window)
            )
            decisions[slot] = slot in picked or cheap
    return decisions


def _in_window(at: time, window: tuple[time, time] | None) -> bool:
    """Return whether a local time of day falls in the window.

    An end before the start wraps past midnight, and an end equal to the
    start covers the whole day.
    """
    if window is None:
        return True
    start, end = window
    if start == end:
        return True
    if start < end:
        return start <= at < end
    return at >= start or at < end


def _local_day_slots(day: date, tz: tzinfo) -> list[datetime]:
    """Return the UTC start of every slot in one local day, DST included."""
    start = dt_util.as_utc(datetime.combine(day, datetime.min.time(), tzinfo=tz))
    end = dt_util.as_utc(
        datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    )
    slots = []
    cursor = start
    while cursor < end:
        slots.append(cursor)
        cursor += timedelta(minutes=SLOT_MINUTES)
    return slots
