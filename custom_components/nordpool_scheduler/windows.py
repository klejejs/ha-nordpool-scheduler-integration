"""Persisted auto mode time windows, and their migration from older settings."""

from __future__ import annotations

from contextlib import suppress
from datetime import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.storage import Store

from .auto import AutoWindow
from .const import (
    ATTR_CHEAP_PRICE,
    ATTR_END,
    ATTR_HOURS,
    ATTR_MAX_PRICE,
    ATTR_START,
    DEFAULT_RUN_HOURS,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    DOMAIN,
    STORAGE_VERSION,
    WINDOWS_STORAGE_KEY_PREFIX,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

SAVE_DELAY = 5

DEFAULT_WINDOWS = (
    AutoWindow(
        start=DEFAULT_WINDOW_START, end=DEFAULT_WINDOW_END, hours=DEFAULT_RUN_HOURS
    ),
)

# The settings time windows replaced, keyed by unique ID suffix, with the
# domain their entity had and the value it started at.
_OLD_SETTINGS: dict[str, tuple[str, Any]] = {
    "run_hours": ("number", DEFAULT_RUN_HOURS),
    "max_price": ("number", 0.0),
    "cheap_price": ("number", 0.0),
    "window_enabled": ("switch", False),
    "window_start": ("time", time(17, 0)),
    "window_end": ("time", time(23, 0)),
    "cheap_all_day": ("switch", False),
}


def whole_minute(at: time) -> time:
    """Round a time up to the next whole minute.

    Slots start on whole minutes, so a window bound with seconds picks the
    same slots as the next minute, and is stored and shown as that.
    """
    if not at.second and not at.microsecond:
        return at
    minutes = min(at.hour * 60 + at.minute + 1, 23 * 60 + 59)
    return time(minutes // 60, minutes % 60)


def window_as_dict(window: AutoWindow) -> dict[str, Any]:
    """Return a window as stored on disk and sent to the card."""
    return {
        ATTR_START: window.start.strftime("%H:%M"),
        ATTR_END: window.end.strftime("%H:%M"),
        ATTR_HOURS: window.hours,
        ATTR_MAX_PRICE: window.max_price,
        ATTR_CHEAP_PRICE: window.cheap_price,
    }


def _window_from_dict(data: dict[str, Any]) -> AutoWindow | None:
    try:
        return AutoWindow(
            start=time.fromisoformat(data[ATTR_START]),
            end=time.fromisoformat(data[ATTR_END]),
            hours=float(data[ATTR_HOURS]),
            max_price=float(data.get(ATTR_MAX_PRICE, 0)),
            cheap_price=float(data.get(ATTR_CHEAP_PRICE, 0)),
        )
    except KeyError, TypeError, ValueError:
        return None


class AutoWindowStore:
    """Load, persist and replace a scheduler's auto mode time windows."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{WINDOWS_STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._windows: tuple[AutoWindow, ...] = DEFAULT_WINDOWS

    @property
    def windows(self) -> tuple[AutoWindow, ...]:
        """Return the windows, sorted by start."""
        return self._windows

    async def async_load(self) -> None:
        """Load the windows from disk, or keep the default if none are saved."""
        stored = await self._store.async_load()
        if stored is None:
            return
        windows = (_window_from_dict(data) for data in stored.get("windows", []))
        self._windows = _sorted(window for window in windows if window is not None)

    def set_windows(self, windows: list[AutoWindow]) -> None:
        """Replace every window."""
        self._windows = _sorted(windows)
        self._store.async_delay_save(self._as_stored, SAVE_DELAY)

    async def async_save(self, windows: list[AutoWindow]) -> None:
        """Replace every window and write them to disk straight away."""
        self._windows = _sorted(windows)
        await self.async_flush()

    async def async_flush(self) -> None:
        """Write out a pending delayed save immediately."""
        await self._store.async_save(self._as_stored())

    def _as_stored(self) -> dict[str, Any]:
        return {"windows": [window_as_dict(window) for window in self._windows]}


def _sorted(windows: Any) -> tuple[AutoWindow, ...]:
    return tuple(sorted(windows, key=lambda window: (window.start, window.end)))


def migrated_windows(settings: dict[str, Any]) -> list[AutoWindow]:
    """Return the windows that pick the same slots as the old auto settings."""
    whole_day = {"start": DEFAULT_WINDOW_START, "end": DEFAULT_WINDOW_END}
    prices = {
        "max_price": settings["max_price"],
        "cheap_price": settings["cheap_price"],
    }
    if not settings["window_enabled"]:
        return [AutoWindow(**whole_day, hours=settings["run_hours"], **prices)]
    windows = [
        AutoWindow(
            start=settings["window_start"],
            end=settings["window_end"],
            hours=settings["run_hours"],
            **prices,
        )
    ]
    if settings["cheap_all_day"] and settings["cheap_price"] > 0:
        windows.append(AutoWindow(**whole_day, hours=0, **prices))
    return windows


async def async_migrate_windows(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Turn the old per-day auto settings into time windows.

    The old entities' last values are read from restore state, then the
    entities are removed.
    """
    registry = er.async_get(hass)
    last_states = restore_state.async_get(hass).last_states
    settings: dict[str, Any] = {}
    for key, (domain, default) in _OLD_SETTINGS.items():
        settings[key] = default
        entity_id = registry.async_get_entity_id(
            domain, DOMAIN, f"{entry.entry_id}_{key}"
        )
        if entity_id is None:
            continue
        stored = last_states.get(entity_id)
        if stored is not None:
            with suppress(TypeError, ValueError):
                settings[key] = _parse(domain, stored)
        registry.async_remove(entity_id)

    await AutoWindowStore(hass, entry.entry_id).async_save(migrated_windows(settings))


def _parse(domain: str, stored: restore_state.StoredState) -> Any:
    if domain == "switch":
        return stored.state.state == STATE_ON
    if domain == "time":
        return whole_minute(time.fromisoformat(stored.state.state))
    extra = stored.extra_data.as_dict() if stored.extra_data else {}
    value = extra.get("native_value")
    return float(stored.state.state if value is None else value)
