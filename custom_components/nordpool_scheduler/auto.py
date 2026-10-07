"""Auto mode: pick the cheapest slots of each local day."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import SLOT_MINUTES

if TYPE_CHECKING:
    from datetime import date, tzinfo


def select_auto_slots(
    prices: dict[datetime, float],
    tz: tzinfo,
    *,
    run_hours: float,
    max_price: float,
    cheap_price: float,
) -> dict[datetime, bool]:
    """Decide on or off for every slot of each fully priced local day.

    Per day, the ``run_hours`` cheapest slots are on, minus any above
    ``max_price``, plus any at or below ``cheap_price``. A threshold of 0 is
    off. Days missing a price for any slot are left out, so they follow the
    default state rather than a choice made on half the day.
    """
    run_slots = int(run_hours * 60 // SLOT_MINUTES)
    days = {dt_util.as_utc(start).astimezone(tz).date() for start in prices}

    decisions: dict[datetime, bool] = {}
    for day in days:
        day_slots = _local_day_slots(day, tz)
        if any(slot not in prices for slot in day_slots):
            continue
        by_price = sorted(day_slots, key=lambda slot: (prices[slot], slot))
        picked = {
            slot
            for slot in by_price[:run_slots]
            if max_price == 0 or prices[slot] <= max_price
        }
        for slot in day_slots:
            cheap = cheap_price > 0 and prices[slot] <= cheap_price
            decisions[slot] = slot in picked or cheap
    return decisions


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
