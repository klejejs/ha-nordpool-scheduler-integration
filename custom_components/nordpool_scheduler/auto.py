"""Auto mode: pick the cheapest slots of each time window, day by day."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import SLOT_MINUTES

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, tzinfo

# A DP state that can't be reached, e.g. a forced slot turned off.
_INFEASIBLE = (math.inf, math.inf)


@dataclass(frozen=True, kw_only=True)
class AutoWindow:
    """A time of day auto mode runs in, for how long and at what prices.

    An end before the start wraps past midnight, and an end equal to the
    start covers the whole day. A price of 0 turns that limit off.
    """

    start: time
    end: time
    hours: float
    max_price: float = 0.0
    cheap_price: float = 0.0

    @property
    def slot_count(self) -> int:
        """Return how many whole slots the window runs for."""
        return int(self.hours * 60 // SLOT_MINUTES)


def select_auto_slots(
    prices: dict[datetime, float],
    tz: tzinfo,
    *,
    windows: Sequence[AutoWindow],
    max_runs: int | None = None,
) -> dict[datetime, bool]:
    """Decide on or off for every slot of each fully priced local day.

    Per day, each window runs its cheapest ``hours`` inside it, skipping
    slots above its max price, plus every slot inside it at or below its
    cheap price. Slots outside every window are off. Days missing a price
    for any slot are left out, apart from the slots outside every window,
    so they follow the default state rather than a choice made on half
    the day.

    Windows pick narrowest first. With ``max_runs``, each window's picks
    form back-to-back runs: every window gets at least one, the day at
    most ``max_runs`` unless there are more windows than that, and a
    cheap slot only runs when it joins onto a run.
    """
    days = {dt_util.as_utc(start).astimezone(tz).date() for start in prices}

    decisions: dict[datetime, bool] = {}
    for day in days:
        day_slots = _local_day_slots(day, tz)
        local = {slot: dt_util.as_utc(slot).astimezone(tz).time() for slot in day_slots}
        covers = [
            {slot for slot in day_slots if _in_window(local[slot], window)}
            for window in windows
        ]
        if any(slot not in prices for slot in day_slots):
            # Only a window with hours can run before cheap slots are known.
            running = set().union(
                *(
                    cover
                    for window, cover in zip(windows, covers, strict=True)
                    if window.slot_count > 0
                )
            )
            decisions.update((slot, False) for slot in day_slots if slot not in running)
            continue

        order = sorted(
            (i for i, window in enumerate(windows) if window.slot_count > 0),
            key=lambda i: (len(covers[i]), windows[i].start),
        )
        taken: set[datetime] = set()
        for position, i in enumerate(order):
            window = windows[i]
            usable = {
                slot
                for slot in covers[i] - taken
                if _within(prices[slot], window.max_price)
            }
            if max_runs is None:
                by_price = sorted(usable, key=lambda slot: (prices[slot], slot))
                taken |= set(by_price[: window.slot_count])
                continue
            runs_used = _count_runs(day_slots, taken)
            later = len(order) - position - 1
            allowed = runs_used + max(1, max_runs - runs_used - later)
            taken = _pick_runs(
                day_slots, prices, usable, window.slot_count, allowed, taken
            )

        cheap = {
            slot
            for window, cover in zip(windows, covers, strict=True)
            if window.cheap_price > 0
            for slot in cover
            if prices[slot] <= window.cheap_price
            and (max_runs is None or _within(prices[slot], window.max_price))
        }
        on = taken | cheap if max_runs is None else _grow_runs(day_slots, taken, cheap)
        decisions.update((slot, slot in on) for slot in day_slots)
    return decisions


def blocks_slot(slot: datetime, tz: tzinfo, windows: Sequence[AutoWindow]) -> bool:
    """Return whether a slot is off before its day has prices.

    That is a slot outside every window with hours to run.
    """
    at = dt_util.as_utc(slot).astimezone(tz).time()
    return not any(
        window.slot_count > 0 and _in_window(at, window) for window in windows
    )


def _within(price: float, max_price: float) -> bool:
    return max_price == 0 or price <= max_price


def _pick_runs(
    slots: list[datetime],
    prices: dict[datetime, float],
    usable: set[datetime],
    count: int,
    max_runs: int,
    forced: set[datetime] | None = None,
) -> set[datetime]:
    """Return ``forced`` plus the cheapest ``count`` usable slots.

    Together they make at most ``max_runs`` runs of back-to-back slots, so
    ``forced`` must fit in that many. When the runs can't hold ``count``
    more slots, as many as fit are picked. Ties go to the earlier slot.
    """
    forced = forced or set()
    cheapest = set(sorted(usable, key=lambda slot: (prices[slot], slot))[:count])
    if _count_runs(slots, forced | cheapest) <= max_runs:
        return forced | cheapest

    # best[i][prev_on][runs][left] is (-slots picked, total price) over
    # slots[i:], given whether slots[i - 1] is on and the runs and slots
    # still allowed. Lower is better. Forced slots count toward neither.
    runs_cap = min(max_runs, count + _count_runs(slots, forced))
    nothing_left = [[(0, 0.0)] * (count + 1) for _ in range(runs_cap + 1)]
    best = [(nothing_left, nothing_left)]
    for slot in reversed(slots):
        after_off, after_on = best[-1]
        if slot in forced:
            # On either way; after an off slot it opens a run.
            best.append(([[_INFEASIBLE] * (count + 1), *after_on[:-1]], after_on))
            continue
        if slot not in usable:
            best.append((after_off, after_off))
            continue
        price = prices[slot]
        # take[runs][left]: turn this slot on, carrying on a run already open
        take = [
            [_INFEASIBLE, *((n - 1, cost + price) for n, cost in row[:-1])]
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
        if slot in forced:
            picked.add(slot)
            runs = runs if prev_on else runs - 1
            prev_on = True
            continue
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


def _in_window(at: time, window: AutoWindow) -> bool:
    """Return whether a local time of day falls in the window."""
    start, end = window.start, window.end
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
