"""Binary sensor platform for Nordpool Scheduler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import CONF_DEFAULT_STATE, CONF_TARGET_ENTITY, STATE_DEFAULT_ON
from .entity import build_device_info
from .util import slot_start_for

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import NordpoolSchedulerConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the scheduled-on binary sensor for a config entry."""
    async_add_entities([NordpoolSchedulerScheduledOnSensor(entry)])


class NordpoolSchedulerScheduledOnSensor(BinarySensorEntity):
    """Whether the schedule wants the target entity on right now."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_has_entity_name = True
    _attr_translation_key = "scheduled_on"
    _attr_should_poll = False

    def __init__(self, entry: NordpoolSchedulerConfigEntry) -> None:
        """Initialize."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_scheduled_on"
        self._attr_device_info = build_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to schedule updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._entry.runtime_data.update_signal, self._async_refresh
            )
        )

    @callback
    def _async_refresh(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return whether the current slot is scheduled on."""
        settings = {**self._entry.data, **self._entry.options}
        default_on = settings.get(CONF_DEFAULT_STATE) == STATE_DEFAULT_ON
        slot_start = slot_start_for(dt_util.utcnow())
        override = self._entry.runtime_data.schedule.get(slot_start)
        return default_on if override is None else override

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        target_entity = self._entry.data[CONF_TARGET_ENTITY]
        target_state = self.hass.states.get(target_entity)
        return {
            "target_entity": target_entity,
            "target_state": target_state.state if target_state else "unavailable",
        }
