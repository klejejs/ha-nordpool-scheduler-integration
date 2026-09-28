"""Persisted per-slot schedule overrides for a Nordpool Scheduler entry."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    SLOT_MINUTES,
    SLOT_STATE_OFF,
    SLOT_STATE_ON,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

SAVE_DELAY = 5


class ScheduleStore:
    """Load, persist and query slot overrides.

    Overrides are keyed by each slot's UTC start time, ISO-formatted, with
    the value ``"on"`` or ``"off"``. A slot with no key follows the entry's
    configured default state.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        self._store: Store[dict[str, str]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._overrides: dict[datetime, bool] = {}

    async def async_load(self) -> None:
        """Load overrides from disk."""
        stored = await self._store.async_load() or {}
        overrides: dict[datetime, bool] = {}
        for key, value in stored.items():
            start = dt_util.parse_datetime(key)
            if start is None:
                continue
            overrides[dt_util.as_utc(start)] = value == SLOT_STATE_ON
        self._overrides = overrides

    def get(self, slot_start: datetime) -> bool | None:
        """Return the override for a slot, or None if it follows the default."""
        return self._overrides.get(slot_start)

    def as_dict(self) -> dict[datetime, bool]:
        """Return a copy of all overrides."""
        return dict(self._overrides)

    def set_slot(self, slot_start: datetime, *, state: bool | None) -> None:
        """Set (or, with ``state=None``, clear) the override for one slot."""
        if state is None:
            self._overrides.pop(slot_start, None)
        else:
            self._overrides[slot_start] = state
        self._async_save()

    def clear(self) -> None:
        """Remove every override."""
        self._overrides.clear()
        self._async_save()

    def prune_ended(self, now: datetime) -> None:
        """Drop overrides for slots that have already ended."""
        cutoff = now - timedelta(minutes=SLOT_MINUTES)
        stale = [start for start in self._overrides if start < cutoff]
        for start in stale:
            del self._overrides[start]
        if stale:
            self._async_save()

    async def async_flush(self) -> None:
        """Write out a pending delayed save immediately.

        Called on unload: ``Store.async_delay_save`` only writes to disk
        after its delay elapses, which a reload can otherwise race.
        """
        await self._store.async_save(self._as_stored())

    def _as_stored(self) -> dict[str, str]:
        return {
            start.isoformat(): SLOT_STATE_ON if state else SLOT_STATE_OFF
            for start, state in self._overrides.items()
        }

    def _async_save(self) -> None:
        self._store.async_delay_save(self._as_stored, SAVE_DELAY)
