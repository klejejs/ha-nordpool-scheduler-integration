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
    max_runs: int | None = None,
) -> dict[datetime, bool]:
    """Decide on or off for every slot of each fully priced local day.

    Per day, the ``run_hours`` cheapest slots inside ``window`` are on, minus
    any above ``max_price``, plus any inside it at or below ``cheap_price``,
    or anywhere in the day with ``cheap_all_day``. A threshold of 0 is off.
    Days missing a price for any slot are left out, apart from the slots
    outside ``window``, so they follow the default state rather than a
    choice made on half the day.

    With ``max_runs``, the picks form at most that many runs of back-to-back
    slots, none above ``max_price``, and a cheap slot only runs when it
    joins onto one of them.
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
        cheap = {
            slot
            for slot in day_slots
            if cheap_price > 0
            and prices[slot] <= cheap_price
            and (cheap_all_day or slot in in_window)
        }
        if max_runs is None:
            by_price = sorted(in_window, key=lambda slot: (prices[slot], slot))
            picked = {
                slot
                for slot in by_price[:run_slots]
                if max_price == 0 or prices[slot] <= max_price
            }
            on = picked | cheap
        else:
            usable = {
                slot
                for slot in in_window
                if max_price == 0 or prices[slot] <= max_price
            }
            picked = _pick_runs(day_slots, prices, usable, run_slots, max_runs)
            on = _grow_runs(day_slots, picked, cheap)
        decisions.update((slot, slot in on) for slot in day_slots)
    return decisions


def _pick_runs(
    slots: list[datetime],
    prices: dict[datetime, float],
    usable: set[datetime],
    count: int,
    max_runs: int,
) -> set[datetime]:
    """Return the cheapest ``count`` usable slots in at most ``max_runs`` runs.

    A run is a stretch of back-to-back slots. When the runs can't hold
    ``count`` slots, as many as fit are picked. Ties go to the earlier slot.
    """
    cheapest = set(sorted(usable, key=lambda slot: (prices[slot], slot))[:count])
    if _count_runs(slots, cheapest) <= max_runs:
        return cheapest

    # best[i][prev_on][runs][left] is (-slots picked, total price) over
    # slots[i:], given whether slots[i - 1] is on and the runs and slots
    # still allowed. Lower is better.
    runs_cap = min(max_runs, count)
    not_allowed = (1, 0.0)
    nothing_left = [[(0, 0.0)] * (count + 1) for _ in range(runs_cap + 1)]
    best = [(nothing_left, nothing_left)]
    for slot in reversed(slots):
        after_off, after_on = best[-1]
        if slot not in usable:
            best.append((after_off, after_off))
            continue
        price = prices[slot]
        # take[runs][left]: turn this slot on, carrying on a run already open
        take = [
            [not_allowed, *((n - 1, cost + price) for n, cost in row[:-1])]
            for row in after_on
        ]
        here_on = [
            list(map(min, off, on)) for off, on in zip(after_off, take, strict=True)
        ]
        # Turning on after an off slot opens a run, so it costs one run more.
        here_off = [
            after_off[0],
            *(
                list(map(min, off, on))
                for off, on in zip(after_off[1:], take, strict=False)
            ),
        ]
        best.append((here_off, here_on))
    best.reverse()

    picked: set[datetime] = set()
    runs, left, prev_on = runs_cap, count, False
    for i, slot in enumerate(slots):
        runs_after = runs if prev_on else runs - 1
        take_it = slot in usable and left > 0 and runs_after >= 0
        if take_it:
            n, cost = best[i + 1][1][runs_after][left - 1]
            take_it = (n - 1, cost + prices[slot]) == best[i][prev_on][runs][left]
        if take_it:
            picked.add(slot)
            runs, left = runs_after, left - 1
        prev_on = take_it
    return picked


def _grow_runs(
    slots: list[datetime], picked: set[datetime], extra: set[datetime]
) -> set[datetime]:
    """Return ``picked`` plus the ``extra`` slots that join onto its runs."""
    on = set(picked)
    for order in (slots, slots[::-1]):
        prev_on = False
        for slot in order:
            if prev_on and slot in extra:
                on.add(slot)
            prev_on = slot in on
    return on


def _count_runs(slots: list[datetime], on: set[datetime]) -> int:
    """Return how many runs of back-to-back slots ``on`` makes."""
    return sum(
        slot in on and (i == 0 or slots[i - 1] not in on)
        for i, slot in enumerate(slots)
    )


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
