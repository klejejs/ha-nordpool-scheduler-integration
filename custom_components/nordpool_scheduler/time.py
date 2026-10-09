"""Time platform for Nordpool Scheduler: auto mode's hour range."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import time
from typing import TYPE_CHECKING

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START
from .control import async_apply_now
from .entity import build_device_info

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import NordpoolSchedulerConfigEntry


@dataclass(frozen=True, kw_only=True)
class WindowTimeDescription(TimeEntityDescription):
    """A time entity backed by one end of auto mode's hour range."""

    default: time


DESCRIPTIONS: tuple[WindowTimeDescription, ...] = (
    WindowTimeDescription(
        key="window_start",
        translation_key="window_start",
        default=DEFAULT_WINDOW_START,
    ),
    WindowTimeDescription(
        key="window_end",
        translation_key="window_end",
        default=DEFAULT_WINDOW_END,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the hour range times for a config entry."""
    async_add_entities(
        NordpoolSchedulerWindowTime(entry, description) for description in DESCRIPTIONS
    )


class NordpoolSchedulerWindowTime(RestoreEntity, TimeEntity):
    """The start or end of the hours auto mode may pick from."""

    entity_description: WindowTimeDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: NordpoolSchedulerConfigEntry, description: WindowTimeDescription
    ) -> None:
        """Initialize."""
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = build_device_info(entry)
        self._attr_native_value = description.default

    async def async_added_to_hass(self) -> None:
        """Restore the last value and feed it to auto mode."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            # unknown, unavailable or garbage keeps the default
            with suppress(ValueError):
                self._attr_native_value = time.fromisoformat(last_state.state)
        self._store(self._attr_native_value)

    async def async_set_value(self, value: time) -> None:
        """Change the time and re-pick auto mode's slots."""
        self._attr_native_value = value
        self._store(value)
        self.async_write_ha_state()
        await async_apply_now(self.hass, self._entry)

    def _store(self, value: time) -> None:
        runtime = self._entry.runtime_data
        setattr(runtime, self.entity_description.key, value)
        runtime.refresh_auto(self.hass)
