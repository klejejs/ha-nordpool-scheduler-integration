"""Binary sensor platform for Nordpool Scheduler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_ON
from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_SCHEDULER_NAME,
    CONF_TARGET_SWITCH,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nordpool Scheduler binary sensor based on a config entry."""
    scheduler_name = entry.data[CONF_SCHEDULER_NAME]
    target_entity = entry.data[CONF_TARGET_SWITCH]

    async_add_entities(
        [NordpoolTargetStateSensor(hass, entry, scheduler_name, target_entity)],
        update_before_add=True,
    )


class NordpoolTargetStateSensor(BinarySensorEntity):
    """Binary sensor representing the current state of the target entity."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        scheduler_name: str,
        target_entity: str,
    ) -> None:
        """Initialize the binary sensor."""
        self.hass = hass
        self._entry = entry
        self._scheduler_name = scheduler_name
        self._target_entity = target_entity
        self._attr_unique_id = f"{entry.entry_id}_target_state"
        self._attr_name = "Target State"
        self._attr_is_on = False

        # Track state changes of the target entity
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        """Register state listener when entity is added."""
        await super().async_added_to_hass()

        # Subscribe to target entity state changes
        @callback
        def target_state_listener(event: Event) -> None:
            """Handle target entity state changes."""
            new_state = event.data.get("new_state")
            if new_state:
                self._attr_is_on = new_state.state == STATE_ON
                self.async_write_ha_state()

        # Use entity-specific listener instead of global state_changed bus
        self._unsubscribe = async_track_state_change_event(
            self.hass,
            [self._target_entity],
            target_state_listener,
        )

        # Set initial state
        target_state = self.hass.states.get(self._target_entity)
        if target_state:
            self._attr_is_on = target_state.state == STATE_ON

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from state changes when entity is removed."""
        if self._unsubscribe:
            self._unsubscribe()
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        target_state = self.hass.states.get(self._target_entity)
        return {
            "target_entity": self._target_entity,
            "target_state": target_state.state if target_state else "unavailable",
            "entry_id": self._entry.entry_id,
            "scheduler_name": self._scheduler_name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        target_state = self.hass.states.get(self._target_entity)
        return target_state is not None

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"Nordpool Scheduler - {self._scheduler_name}",
            "manufacturer": "Nordpool",
            "model": "Price Scheduler",
            "sw_version": "1.0.0",
        }
