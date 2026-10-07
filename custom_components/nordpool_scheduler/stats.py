"""Average price while the target runs, kept as per-day totals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import SLOT_MINUTES, STATS_STORAGE_KEY_PREFIX, STORAGE_VERSION
from .util import is_running, slot_start_for

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

SAVE_DELAY = 30
KEEP_DAYS = 400


@dataclass(frozen=True)
class StatsWindow:
    """A period the average price is reported over.

    ``start`` maps today's local date to the first local date of the window.
    """

    key: str
    start: Callable[[date], date]


WINDOWS: tuple[StatsWindow, ...] = (
    StatsWindow("today", lambda today: today),
    StatsWindow("week", lambda today: today - timedelta(days=today.weekday())),
    StatsWindow("month", lambda today: today.replace(day=1)),
    StatsWindow("year", lambda today: today.replace(month=1, day=1)),
)


class PriceStats:
    """Track seconds running and price-weighted seconds for each local day.

    A prices-only entry has no target and counts as always running, which
    makes its average a plain time-average of the prices.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        price_for: Callable[[datetime], float | None],
    ) -> None:
        """Initialize."""
        self._hass = hass
        self._price_for = price_for
        self._store: Store[dict[str, list[float]]] = Store(
            hass, STORAGE_VERSION, f"{STATS_STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._days: dict[date, list[float]] = {}
        self._since = dt_util.utcnow()
        self._running = False

    async def async_load(self) -> None:
        """Load the per-day totals from disk."""
        stored = await self._store.async_load() or {}
        days: dict[date, list[float]] = {}
        for key, (seconds, price_seconds) in stored.items():
            try:
                days[date.fromisoformat(key)] = [seconds, price_seconds]
            except ValueError:
                continue
        self._days = days

    @callback
    def async_start(self, target_entity: str | None, signal: str) -> CALLBACK_TYPE:
        """Start counting from now and follow the target's state.

        Returns a callback that stops following it. The caller also has to
        call ``sample`` at every slot boundary, when the price changes.
        """
        self._since = dt_util.utcnow()
        if target_entity is None:
            self._running = True
            return lambda: None
        self._running = is_running(self._hass.states.get(target_entity))

        @callback
        def _on_target_change(event: Event[EventStateChangedData]) -> None:
            self.sample(dt_util.utcnow())
            self._running = is_running(event.data["new_state"])
            async_dispatcher_send(self._hass, signal)

        return async_track_state_change_event(
            self._hass, [target_entity], _on_target_change
        )

    def sample(self, now: datetime) -> None:
        """Count the time since the last sample if the target was running."""
        if self._running and now > self._since:
            self.accrue(self._since, now)
        self._since = now

    def accrue(self, start: datetime, end: datetime) -> None:
        """Add ``[start, end)`` to the totals, priced slot by slot.

        Time in a slot with no known price isn't counted at all.
        """
        cursor = start
        while cursor < end:
            slot_start = slot_start_for(cursor)
            slot_end = min(slot_start + timedelta(minutes=SLOT_MINUTES), end)
            price = self._price_for(slot_start)
            if price is not None:
                seconds = (slot_end - cursor).total_seconds()
                # UTC offsets are whole quarter hours, so a slot never
                # straddles local midnight.
                day = dt_util.as_local(slot_start).date()
                totals = self._days.setdefault(day, [0.0, 0.0])
                totals[0] += seconds
                totals[1] += price * seconds
            cursor = slot_end

        cutoff = dt_util.as_local(end).date() - timedelta(days=KEEP_DAYS)
        for day in [day for day in self._days if day < cutoff]:
            del self._days[day]
        self._store.async_delay_save(self._as_stored, SAVE_DELAY)

    def average(self, since: date) -> tuple[float | None, float]:
        """Return the average price and the hours run from ``since`` on."""
        seconds = 0.0
        price_seconds = 0.0
        for day, (day_seconds, day_price_seconds) in self._days.items():
            if day >= since:
                seconds += day_seconds
                price_seconds += day_price_seconds
        if not seconds:
            return None, 0.0
        return round(price_seconds / seconds, 4), round(seconds / 3600, 2)

    async def async_flush(self) -> None:
        """Write the totals out now instead of after the save delay."""
        await self._store.async_save(self._as_stored())

    def _as_stored(self) -> dict[str, list[float]]:
        return {day.isoformat(): totals for day, totals in self._days.items()}
