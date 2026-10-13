"""Auto mode: pick the cheapest slots of each time window, day by day."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import cache
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
    start covers the whole day. A price or minimum run of 0 turns that
    limit off.
    """

    start: time
    end: time
    hours: float
    max_price: float = 0.0
    cheap_price: float = 0.0
    min_run_hours: float = 0.0

    @property
    def slot_count(self) -> int:
        """Return how many whole slots the window runs for.

        A window that runs at all runs for at least its minimum run.
        """
        slots = int(self.hours * 60 // SLOT_MINUTES)
        return max(slots, self.min_run_slots) if slots else 0

    @property
    def min_run_slots(self) -> int:
        """Return how many whole slots each run it starts lasts at least."""
        return int(self.min_run_hours * 60 // SLOT_MINUTES)

    @property
    def run_hours(self) -> float:
        """Return how long the window runs for each day."""
        return max(self.hours, self.min_run_hours) if self.slot_count else self.hours


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
    cheap slot only runs when it joins onto a run. A window's minimum run
    is the shortest run it may start, counting slots that other windows
    picked, and the shortest stretch of its cheap slots that runs alone.
    """
    days = {dt_util.as_utc(start).astimezone(tz).date() for start in prices}

    decisions: dict[datetime, bool] = {}
    for day in days:
        day_slots = _local_day_slots(day, tz)
        local = {slot: dt_util.as_utc(slot).astimezone(tz).time() for slot in day_slots}
        covers = [
            {slot for slot in day_slots if in_window(local[slot], window)}
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
        # A window too short for its minimum run runs its longest stretch.
        min_lens = [
            min(
                window.min_run_slots,
                max(map(len, _stretches(day_slots, cover)), default=0),
            )
            for window, cover in zip(windows, covers, strict=True)
        ]
        taken: set[datetime] = set()
        for position, i in enumerate(order):
            window = windows[i]
            usable = {
                slot
                for slot in covers[i] - taken
                if _within(prices[slot], window.max_price)
            }
            allowed = None
            if max_runs is not None:
                runs_used = len(_stretches(day_slots, taken))
                later = len(order) - position - 1
                allowed = runs_used + max(1, max_runs - runs_used - later)
            taken = _pick_runs(
                day_slots,
                prices,
                usable,
                window.slot_count,
                max_runs=allowed,
                min_len=min_lens[i],
                forced=taken,
            )

        # The shortest minimum run among the windows each cheap slot is cheap in.
        cheap: dict[datetime, int] = {}
        for window, cover, min_len in zip(windows, covers, min_lens, strict=True):
            if window.cheap_price <= 0:
                continue
            for slot in cover:
                if prices[slot] <= window.cheap_price and (
                    max_runs is None or _within(prices[slot], window.max_price)
                ):
                    cheap[slot] = min(cheap.get(slot, min_len), min_len)
        on = (
            taken | set(cheap)
            if max_runs is None
            else _grow_runs(day_slots, taken, set(cheap))
        )
        # Dropping a cheap slot can shorten the stretch its neighbours are in.
        while short := {
            slot
            for run in _stretches(day_slots, on)
            if run.isdisjoint(taken)
            for slot in run
            if cheap[slot] > len(run)
        }:
            on -= short
        decisions.update((slot, slot in on) for slot in day_slots)
    return decisions


def blocks_slot(slot: datetime, tz: tzinfo, windows: Sequence[AutoWindow]) -> bool:
    """Return whether a slot is off before its day has prices.

    That is a slot outside every window with hours to run.
    """
    at = dt_util.as_utc(slot).astimezone(tz).time()
    return not any(
        window.slot_count > 0 and in_window(at, window) for window in windows
    )


def _within(price: float, max_price: float) -> bool:
    return max_price == 0 or price <= max_price


def _pick_runs(
    slots: list[datetime],
    prices: dict[datetime, float],
    usable: set[datetime],
    count: int,
    *,
    max_runs: int | None = None,
    min_len: int = 0,
    forced: set[datetime] | None = None,
) -> set[datetime]:
    """Return ``forced`` plus the cheapest ``count`` usable slots.

    With ``max_runs``, together they make at most that many runs of
    back-to-back slots, so ``forced`` must fit in that many. Every run
    holding a picked slot is at least ``min_len`` slots long, forced slots
    in it included. When that can't hold ``count`` more slots, as many as
    fit are picked. Ties go to the earlier slot.
    """
    forced = forced or set()
    cheapest = set(sorted(usable, key=lambda slot: (prices[slot], slot))[:count])
    runs = _stretches(slots, forced | cheapest)
    if (max_runs is None or len(runs) <= max_runs) and all(
        len(run) >= min_len for run in runs if not run.isdisjoint(cheapest)
    ):
        return forced | cheapest

    min_len = max(min_len, 1)

    def opened(run: int, runs: int) -> int | None:
        """Return the runs used once the next slot is on, or None past the limit."""
        if run or max_runs is None:
            return runs
        return runs + 1 if runs < max_runs else None

    # ``run`` is how long the run ending at slots[i - 1] is, capped at min_len:
    # positive when it holds a picked slot, negative when it doesn't, 0 if off.
    @cache
    def best(i: int, run: int, runs: int, left: int) -> tuple[float, float]:
        """Return (-slots picked, total price) over slots[i:]. Lower is better."""
        short = 0 < run < min_len
        if i == len(slots):
            return _INFEASIBLE if short else (0, 0.0)
        slot, runs_on = slots[i], opened(run, runs)
        grown = min(abs(run) + 1, min_len)
        if slot in forced:
            if runs_on is None:
                return _INFEASIBLE
            return best(i + 1, grown if run > 0 else -grown, runs_on, left)
        off = _INFEASIBLE if short else best(i + 1, 0, runs, left)
        if slot not in usable or not left or runs_on is None:
            return off
        n, cost = best(i + 1, grown, runs_on, left - 1)
        return min(off, (n - 1, cost + prices[slot]))

    picked = set(forced)
    run, runs, left = 0, 0, count
    for i, slot in enumerate(slots):
        runs_on, grown = opened(run, runs), min(abs(run) + 1, min_len)
        if slot in forced:
            run, runs = grown if run > 0 else -grown, runs_on
            continue
        if slot in usable and left and runs_on is not None:
            n, cost = best(i + 1, grown, runs_on, left - 1)
            if (n - 1, cost + prices[slot]) == best(i, run, runs, left):
                picked.add(slot)
                run, runs, left = grown, runs_on, left - 1
                continue
        run = 0
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


def _stretches(slots: list[datetime], on: set[datetime]) -> list[set[datetime]]:
    """Return the runs of back-to-back slots ``on`` makes."""
    runs: list[set[datetime]] = []
    for i, slot in enumerate(slots):
        if slot in on:
            if i == 0 or slots[i - 1] not in on:
                runs.append(set())
            runs[-1].add(slot)
    return runs


def in_window(at: time, window: AutoWindow) -> bool:
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
